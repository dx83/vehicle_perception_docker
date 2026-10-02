"""HTTP signaling / metrics only; WebRTC carries video."""
import asyncio
from contextlib import asynccontextmanager
import secrets
import time
import uuid

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..common.engine_paths import load_settings
from ..runtime.engine_session import RuntimeHolder, Session
from ..streaming.engine_media import ViewerTrack
from ..streaming.engine_video_quality import configure_video_bitrate
from ..streaming.engine_rtc_metrics import measure_sender, collect_transport


class Camera(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)
    camera_id: str = Field(min_length=1, max_length=100)
    width: int = Field(ge=1, le=1920)
    height: int = Field(ge=1, le=1080)
    orientation: str = "landscape"
    zoom: float = Field(ge=1, le=1)


class Offer(BaseModel):
    sdp: str = Field(min_length=1, max_length=100000)
    type: str = "offer"


def create_app(settings=None, engine_factory=None):
    settings = settings or load_settings()
    configure_video_bitrate(settings.viewer_bitrate_bps)
    holder = RuntimeHolder(settings) if engine_factory is None else RuntimeHolder(settings, engine_factory)
    active = None
    lifecycle_lock = asyncio.Lock()

    async def stop(session):
        nonlocal active
        async with lifecycle_lock:
            if active is session:
                await session.close()
                active = None

    async def watchdog():
        while True:
            await asyncio.sleep(2)
            session = active
            if session and session.status()["last_receive_age_sec"] > settings.idle_timeout_sec:
                await stop(session)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(watchdog())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if active:
            await stop(active)
        await asyncio.to_thread(holder.close)

    app = FastAPI(lifespan=lifespan)

    def get_session(session_id):
        if not active or active.id != session_id or active.closed:
            raise HTTPException(404, "session not found")
        return active

    def authorize(session, token):
        if not secrets.compare_digest(token or "", session.token):
            raise HTTPException(403, "invalid session token")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "recording": False}

    @app.get("/api/state")
    async def state():
        return active.status() if active else {"state": "NO_CAMERA", "session_id": None}

    @app.get("/api/rtc-config")
    async def rtc_config():
        return {"iceServers": settings.ice_servers}

    @app.post("/api/sessions", status_code=201)
    async def start(camera: Camera):
        nonlocal active
        async with lifecycle_lock:
            if active is not None:
                raise HTTPException(409, "one phone session is already active")
            if (camera.width, camera.height, camera.orientation) != (1280, 720, "landscape"):
                raise HTTPException(422, "v1 requires rear-camera landscape 1280x720 at zoom 1")
            active = Session(settings, camera.model_dump(), holder)
            return {**active.status(), "token": active.token}

    @app.delete("/api/sessions/{session_id}")
    async def end(session_id: str, x_session_token: str | None = Header(default=None)):
        session = get_session(session_id)
        authorize(session, x_session_token)
        await stop(session)
        return {"state": "CLOSED"}

    @app.get("/api/sessions/{session_id}")
    async def status(session_id: str):
        return get_session(session_id).status()

    async def ingest(session, track):
        try:
            while not session.closed:
                frame = await track.recv()
                started = time.perf_counter()
                array = frame.to_ndarray(format="bgr24")
                session.receive_conversion_ms = (time.perf_counter() - started) * 1000
                await session.receive(array)
        except MediaStreamError:
            pass
        finally:
            # Do not await self-cancellation in Session.close().
            asyncio.create_task(stop(session))

    @app.post("/api/sessions/{session_id}/{role}/offer")
    async def negotiate(session_id: str, role: str, offer: Offer,
                        x_session_token: str | None = Header(default=None)):
        session = get_session(session_id)
        if offer.type != "offer" or role not in {"phone", "viewer"}:
            raise HTTPException(422, "expected phone/viewer SDP offer")
        if role == "phone":
            authorize(session, x_session_token)
            if session.phone_connected:
                raise HTTPException(409, "phone peer already exists")
            session.phone_connected = True
        elif len(session.viewer_peers) >= settings.max_viewers:
            raise HTTPException(409, "viewer limit reached")
        ice = [RTCIceServer(**item) for item in settings.ice_servers]
        peer = RTCPeerConnection(RTCConfiguration(iceServers=ice))
        peer_id = uuid.uuid4().hex[:8]
        session.peers.add(peer)
        if role == "viewer":
            session.viewer_peers.add(peer)
            track = ViewerTrack(session.broadcast)
            sender = peer.addTrack(track)
            session.viewer_metrics[peer_id] = measure_sender(sender, track)
            async def poll_transport():
                while not session.closed and peer.connectionState not in {"closed", "failed"}:
                    metrics = session.viewer_metrics.get(peer_id)
                    if metrics is None:
                        return
                    await collect_transport(peer, sender, metrics)
                    await asyncio.sleep(1)
            poll_task = asyncio.create_task(poll_transport())
            session.tasks.add(poll_task)
            poll_task.add_done_callback(session.tasks.discard)

        @peer.on("track")
        def on_track(track):
            if role == "phone" and track.kind == "video":
                task = asyncio.create_task(ingest(session, track))
                session.tasks.add(task)
                task.add_done_callback(session.tasks.discard)

        @peer.on("connectionstatechange")
        async def connection_changed():
            if peer.connectionState in {"failed", "closed"}:
                session.viewer_peers.discard(peer)
                if role == "viewer":
                    poll_task.cancel()
                    session.viewer_metrics.pop(peer_id, None)
                if role == "phone" and not session.closed:
                    asyncio.create_task(stop(session))
                await peer.close()
                session.peers.discard(peer)

        try:
            await peer.setRemoteDescription(RTCSessionDescription(offer.sdp, offer.type))
            video_tracks = [item for item in peer.getTransceivers() if item.kind == "video"]
            if role == "phone" and len(video_tracks) != 1:
                raise HTTPException(422, "phone must provide exactly one video track")
            await peer.setLocalDescription(await peer.createAnswer())
        except Exception:
            await peer.close()
            session.peers.discard(peer)
            session.viewer_peers.discard(peer)
            if role == "phone":
                await stop(session)
            raise
        return {"sdp": peer.localDescription.sdp, "type": peer.localDescription.type}

    @app.websocket("/api/metrics")
    async def metrics(socket: WebSocket):
        await socket.accept()
        try:
            while True:
                await socket.send_json(active.status() if active else {"state": "NO_CAMERA", "session_id": None})
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            pass

    if settings.frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
    return app
