import asyncio
from dataclasses import replace
from threading import Thread
from types import SimpleNamespace
import time

import numpy as np
import pytest

from vehicle_web.common.engine_paths import load_settings, validate_intrinsic
from vehicle_web.runtime.engine_session import RuntimeHolder, Session
from vehicle_web.streaming.engine_latest import LatestInput, PairedSource
from vehicle_web.streaming.engine_media import Broadcast, ViewerTrack, ThreadPublisher
from vehicle_web.visualization.engine_overlay import render


def settings(calibrated=False):
    config = load_settings()
    profile = dict(device_id="phone", camera_id="0", width=1280, height=720,
                   orientation="landscape", zoom=1.0, verified=calibrated)
    return replace(config, camera_profile=profile)


def camera():
    return {key: value for key, value in settings().camera_profile.items() if key != "verified"}


class FakeEngine:
    def __init__(self):
        self.streams = 0
        self.closed = False
        self.diagnostics = {"last_frame_profile": {"depth_ms": 2.0}}

    def warmup(self, frame, iterations=1):
        pass

    def process_stream(self, source):
        self.streams += 1
        for index, frame in enumerate(source):
            time.sleep(0.005)
            yield SimpleNamespace(frame_id=index, objects=())

    def close(self):
        self.closed = True


def test_latest_keeps_only_newest():
    source = LatestInput()
    for i in range(100):
        source.put(np.full((2, 2, 3), i, dtype=np.uint8))
    observation = source.get()
    assert observation.source_index == 99
    assert source.dropped == 99
    assert source.pending is None


def test_close_wakes_blocked_source():
    source = LatestInput()
    results = []
    worker = Thread(target=lambda: results.append(source.get()))
    worker.start(); source.close(); worker.join(1)
    assert not worker.is_alive() and results == [None]


def test_pairing_survives_drops_and_is_bounded():
    latest = LatestInput(); source = PairedSource(latest, capacity=1)
    frames = iter(source)
    latest.put(np.zeros((2, 2, 3), np.uint8)); next(frames)
    for i in range(1, 5): latest.put(np.full((2, 2, 3), i, np.uint8))
    assert len(source.frames) == 1
    assert source.take(0).source_index == 0
    next(frames)
    assert source.take(1).source_index == 4
    source.close()
    assert list(frames) == []


def test_phone_specific_calibration_gate():
    config = settings(True)
    assert config.calibrated(camera())
    for key, value in (("device_id", "other"), ("camera_id", "1"), ("width", 1920), ("zoom", 2)):
        assert not config.calibrated({**camera(), key: value})
    assert not settings(False).calibrated(camera())


@pytest.mark.parametrize("matrix", [None, [[0, 0, 1], [0, 10, 1], [0, 0, 1]],
                                   [[100, 0, 1500], [0, 100, 360], [0, 0, 1]]])
def test_invalid_intrinsic_rejected(matrix):
    with pytest.raises(ValueError): validate_intrinsic(matrix, 1280, 720)


def test_valid_intrinsic():
    validate_intrinsic([[900, 0, 640], [0, 900, 360], [0, 0, 1]], 1280, 720)


def test_mask_render_only_changes_selected_pixels():
    mask = SimpleNamespace(x=2, y=2, width=2, height=2,
                           packed_bits=np.packbits([1, 0, 0, 1]).tobytes())
    obj = SimpleNamespace(class_name="vehicle", mask=mask, bbox=(10, 30, 40, 50),
                          track_id=7, distance_m=15.5)
    frame = np.zeros((80, 80, 3), np.uint8)
    output = render(frame, SimpleNamespace(objects=(obj,)))
    assert output[2, 2].any() and not output[2, 3].any()
    assert not frame.any()


def test_broadcast_viewers_do_not_share_consumption():
    async def check():
        hub = Broadcast(); first, second = ViewerTrack(hub), ViewerTrack(hub)
        await hub.publish(np.zeros((4, 4, 3), np.uint8))
        a, b = await asyncio.gather(first.recv(), second.recv())
        assert a.pts == b.pts
        for i in range(10): await hub.publish(np.full((4, 4, 3), i, np.uint8))
        assert (await first.recv()).to_ndarray(format="bgr24")[0, 0, 0] == 9
        assert (await second.recv()).to_ndarray(format="bgr24")[0, 0, 0] == 9
        await hub.close()
    asyncio.run(check())


def test_thread_publisher_coalesces():
    async def check():
        hub = Broadcast(); publisher = ThreadPublisher(asyncio.get_running_loop(), hub)
        def produce():
            for i in range(100): publisher.publish(np.full((2, 2, 3), i, np.uint8))
        worker = Thread(target=produce); worker.start(); worker.join()
        await asyncio.sleep(0.01)
        assert hub.sequence == 1 and hub.latest[0][0, 0, 0] == 99
        await publisher.close(); await hub.close()
    asyncio.run(check())


def test_sessions_reuse_models_but_reset_stream():
    async def check():
        config = settings(True); engine = FakeEngine()
        holder = RuntimeHolder(config, lambda _: engine)
        for _ in range(2):
            session = Session(config, camera(), holder)
            for i in range(8):
                await session.receive(np.full((720, 1280, 3), i, np.uint8))
                await asyncio.sleep(0.015)
            assert session.processed > 0
            assert len(session.source.frames) <= 8
            await session.close()
            assert not session.worker.is_alive()
        assert engine.streams == 2
        holder.close(); assert engine.closed
    asyncio.run(check())


def test_raw_preview_never_initializes_model():
    async def check():
        config = settings(False)
        holder = RuntimeHolder(config, lambda _: pytest.fail("calibration gate bypassed"))
        session = Session(config, camera(), holder)
        await session.receive(np.zeros((720, 1280, 3), np.uint8))
        assert session.broadcast.sequence == 1 and session.worker is None
        await session.close()
    asyncio.run(check())


def test_actual_dimensions_must_match_calibration():
    async def check():
        config = settings(True)
        session = Session(config, camera(), RuntimeHolder(config, lambda _: FakeEngine()))
        await session.receive(np.zeros((1080, 1920, 3), np.uint8))
        assert session.state == "CAMERA_PROFILE_MISMATCH" and session.worker is None
        await session.close()
    asyncio.run(check())


def test_input_overload_has_bounded_history_and_pending_frames():
    async def check():
        config = settings(True)
        session = Session(config, camera(), RuntimeHolder(config, lambda _: FakeEngine()))
        frame = np.zeros((720, 1280, 3), np.uint8)
        for _ in range(10000):
            await session.receive(frame)
        await asyncio.sleep(0.03)
        assert session.input.dropped > 0
        assert len(session.input_times) == 120
        assert len(session.output_times) <= 120
        assert len(session.source.frames) <= 8
        await session.close()
    asyncio.run(check())
