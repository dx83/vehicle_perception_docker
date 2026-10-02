import pytest
from aiortc.codecs import h264, vpx
from vehicle_web.common.engine_paths import load_settings
from vehicle_web.streaming.engine_video_quality import configure_video_bitrate, validate_video_bitrate


def test_encoder_start_and_feedback_limits(monkeypatch):
    policy = load_settings().viewer_bitrate_bps
    for codec in (h264, vpx):
        for name in ("MIN_BITRATE", "DEFAULT_BITRATE", "MAX_BITRATE"):
            monkeypatch.setattr(codec, name, getattr(codec, name))
    configure_video_bitrate(policy)
    for encoder in (h264.H264Encoder(), vpx.Vp8Encoder()):
        assert encoder.target_bitrate == 4_000_000
        encoder.target_bitrate = 20_000_000
        assert encoder.target_bitrate == 8_000_000
        encoder.target_bitrate = 500_000
        assert encoder.target_bitrate == 500_000


@pytest.mark.parametrize("value", [
    {}, {"min": 250000, "start": 9000000, "max": 8000000},
    {"min": True, "start": 4000000, "max": 8000000},
    {"min": 250000, "start": 4000000, "max": 30000000},
])
def test_invalid_policy(value):
    with pytest.raises(ValueError, match="viewer_bitrate"):
        validate_video_bitrate(value)
