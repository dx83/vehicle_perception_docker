import asyncio
from dataclasses import replace

from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from fastapi.testclient import TestClient
import httpx
import numpy as np

from vehicle_web.api.engine_app import create_app
from vehicle_web.common.engine_paths import load_settings


CAMERA = dict(device_id="test", camera_id="0", width=1280, height=720, orientation="landscape", zoom=1)


def test_session_conflict_authorization_and_reconnect():
    with TestClient(create_app()) as client:
        assert client.get("/api/health").json()["recording"] is False
        session = client.post("/api/sessions", json=CAMERA).json()
        assert session["state"] == "CALIBRATION_REQUIRED"
        assert client.post("/api/sessions", json=CAMERA).status_code == 409
        url = f'/api/sessions/{session["session_id"]}'
        assert client.delete(url).status_code == 403
        assert client.delete(url, headers={"X-Session-Token": session["token"]}).status_code == 200
        assert client.get("/api/state").json()["state"] == "NO_CAMERA"
        assert client.post("/api/sessions", json=CAMERA).json()["session_id"] != session["session_id"]


def test_metrics_websocket_and_invalid_camera():
    with TestClient(create_app()) as client:
        with client.websocket_connect("/api/metrics") as socket:
            assert socket.receive_json()["state"] == "NO_CAMERA"
        assert client.post("/api/sessions", json={**CAMERA, "zoom": 2}).status_code == 422
        assert client.post("/api/sessions", json={**CAMERA, "width": 640}).status_code == 422


class SyntheticCamera(VideoStreamTrack):
    async def recv(self):
        pts, time_base = await self.next_timestamp()
        array = np.zeros((720, 1280, 3), np.uint8)
        array[:, :, 1] = 100
        frame = VideoFrame.from_ndarray(array, format="bgr24")
        frame.pts, frame.time_base = pts, time_base
        return frame


def webrtc_roundtrip(calibrated):
    async def check():
        config = load_settings()
        if calibrated:
            from test_live_core import FakeEngine
            config = replace(config, camera_profile={**CAMERA, "verified": True})
            app = create_app(config, lambda _: FakeEngine())
        else:
            app = create_app(config)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
                session = (await client.post("/api/sessions", json=CAMERA)).json()
                base = f'/api/sessions/{session["session_id"]}'
                phone = RTCPeerConnection(RTCConfiguration(iceServers=[]))
                viewer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
                try:
                    phone.addTrack(SyntheticCamera())
                    await phone.setLocalDescription(await phone.createOffer())
                    response = await client.post(base + "/phone/offer", json={"type": "offer", "sdp": phone.localDescription.sdp},
                                                 headers={"X-Session-Token": session["token"]})
                    assert response.status_code == 200
                    await phone.setRemoteDescription(RTCSessionDescription(**response.json()))
                    incoming = asyncio.get_running_loop().create_future()
                    @viewer.on("track")
                    def on_track(track): incoming.set_result(track)
                    viewer.addTransceiver("video", direction="recvonly")
                    await viewer.setLocalDescription(await viewer.createOffer())
                    response = await client.post(base + "/viewer/offer", json={"type": "offer", "sdp": viewer.localDescription.sdp})
                    assert response.status_code == 200
                    await viewer.setRemoteDescription(RTCSessionDescription(**response.json()))
                    track = await asyncio.wait_for(incoming, 10)
                    frame = await asyncio.wait_for(track.recv(), 10)
                    assert (frame.width, frame.height) == (1280, 720)
                    status = (await client.get(base)).json()
                    assert status["received_frames"] > 0
                    assert (status["inferred_frames"] > 0) if calibrated else (status["inferred_frames"] == 0)
                    metrics = next(iter(status["viewer_transport"].values()))
                    assert metrics["encoded_frames"] > 0
                    assert metrics["encode_and_prepare_ms"] > 0
                    await client.delete(base, headers={"X-Session-Token": session["token"]})
                finally:
                    await phone.close(); await viewer.close()
    asyncio.run(check())


def test_actual_webrtc_phone_to_browser_raw_preview():
    webrtc_roundtrip(False)


def test_actual_webrtc_phone_to_browser_with_inference_adapter():
    webrtc_roundtrip(True)
