"""Single-camera lifecycle; models reused, tracker reset via process_stream."""
import asyncio
from collections import deque
from threading import Thread, Lock
import time
import uuid

from .engine_adapter import create_engine
from ..streaming.engine_latest import LatestInput, PairedSource
from ..streaming.engine_media import Broadcast, ThreadPublisher
from ..visualization.engine_overlay import render


class RuntimeHolder:
    def __init__(self, settings, factory=create_engine):
        self.settings = settings
        self.factory = factory
        self.engine = None

    def get(self):
        if self.engine is None:
            self.engine = self.factory(self.settings)
        return self.engine

    def close(self):
        if self.engine:
            self.engine.close()
            self.engine = None


class Session:
    def __init__(self, settings, camera, holder):
        self.id = uuid.uuid4().hex
        self.token = uuid.uuid4().hex
        self.settings, self.camera, self.holder = settings, camera, holder
        self.calibrated = settings.calibrated(camera)
        self.state = "WAITING_FOR_CAMERA" if self.calibrated else "CALIBRATION_REQUIRED"
        self.error = None
        self.input = LatestInput()
        self.source = PairedSource(self.input)
        self.broadcast = Broadcast()
        self.publisher = ThreadPublisher(asyncio.get_running_loop(), self.broadcast)
        self.worker = None
        self.closed = False
        self.metrics_lock = Lock()
        self.input_times = deque(maxlen=120)
        self.output_times = deque(maxlen=120)
        self.timings = {}
        self.processed = 0
        self.last_source_index = None
        self.last_frame_id = None
        self.peers = set()
        self.viewer_peers = set()
        self.tasks = set()
        self.phone_connected = False
        self.viewer_metrics = {}
        self.receive_conversion_ms = None
        self.warmup_frames = 0
        self.received_width = None
        self.received_height = None

    async def receive(self, frame):
        if self.closed:
            return
        now = time.monotonic()
        with self.metrics_lock:
            self.input_times.append(now)
            self.received_height, self.received_width = frame.shape[:2]
        if not self.calibrated:
            self.input.received += 1
            self.input.last_received = now
            await self.broadcast.publish(frame)
            return
        expected = (self.camera["height"], self.camera["width"])
        if frame.shape[:2] != expected:
            self.error = f"transmitted frame size {frame.shape[:2]} does not match calibration {expected}"
            self.state = "CAMERA_PROFILE_MISMATCH"
            self.source.close()
            return
        if self.error:
            return
        self.input.put(frame)
        if self.worker is None:
            self.worker = Thread(target=self._infer, name="vehicle-session", daemon=False)
            self.worker.start()

    def _infer(self):
        # Boundary exception is kept for API status; inference failures are never ignored.
        try:
            self.state = "WARMING_UP"
            first = self.input.get()
            if first is None:
                return
            engine = self.holder.get()
            engine.warmup(first.frame, iterations=1)
            self.warmup_frames = 1
            if self.closed or self.error:
                return
            self.state = "INFERENCING"
            results = engine.process_stream(self.source)
            try:
                for result in results:
                    observation = self.source.take(result.frame_id)
                    if self.closed or self.error:
                        continue
                    started = time.monotonic()
                    annotated = render(observation.frame, result)
                    now = time.monotonic()
                    with self.metrics_lock:
                        self.output_times.append(now)
                        self.processed += 1
                        self.last_source_index = observation.source_index
                        self.last_frame_id = result.frame_id
                        self.timings = {
                            **(engine.diagnostics.get("last_frame_profile") or {}),
                            "overlay_ms": (now - started) * 1000,
                            "receive_to_overlay_ms": (now - observation.received_at) * 1000,
                        }
                    self.publisher.publish(annotated)
            finally:
                self.source.close()
                results.close()
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"
            self.state = "INFERENCE_FAILED"
            self.source.close()

    def status(self):
        now = time.monotonic()
        def fps(times):
            if len(times) < 2 or now - times[-1] > 2:
                return 0.0
            return (len(times) - 1) / max(times[-1] - times[0], 1e-6)
        with self.metrics_lock:
            return {
                "session_id": self.id, "state": self.state, "error": self.error,
                "camera": self.camera, "calibrated": self.calibrated,
                "received_width": self.received_width,
                "received_height": self.received_height,
                "received_frames": self.input.received, "inferred_frames": self.processed,
                "dropped_before_inference": self.input.dropped,
                "input_fps": fps(self.input_times), "inference_fps": fps(self.output_times),
                "last_source_index": self.last_source_index, "last_frame_id": self.last_frame_id,
                "timings": dict(self.timings), "viewers": len(self.viewer_peers),
                "last_receive_age_sec": now - self.input.last_received,
                "artifact_free": True,
                "warmup_frames": self.warmup_frames,
                "receive_conversion_ms": self.receive_conversion_ms,
                "viewer_transport": {key: dict(value) for key, value in self.viewer_metrics.items()},
            }

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.source.close()  # Wake blocking runtime source before joining.
        await self.broadcast.close()
        await self.publisher.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.worker:
            await asyncio.to_thread(self.worker.join)
        await asyncio.gather(*(peer.close() for peer in list(self.peers)))
        self.state = "CLOSED"
