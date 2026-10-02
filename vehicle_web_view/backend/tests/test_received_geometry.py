import asyncio
import numpy as np
from vehicle_web.common.engine_paths import load_settings
from vehicle_web.runtime.engine_session import RuntimeHolder, Session


def test_reports_decoded_geometry_not_camera_claim():
    async def check():
        settings = load_settings()
        camera = {"width": 1280, "height": 720}
        holder = RuntimeHolder(settings, lambda _: None)
        session = Session(settings, camera, holder)
        assert session.status()["received_width"] is None
        await session.receive(np.zeros((180, 320, 3), np.uint8))
        assert session.status()["received_width"] == 320
        assert session.status()["received_height"] == 180
        await session.receive(np.zeros((720, 1280, 3), np.uint8))
        assert session.status()["received_width"] == 1280
        assert session.status()["received_height"] == 720
        assert session.status()["inferred_frames"] == 0
        await session.close()
    asyncio.run(check())
