"""Process-wide aiortc encoder policy for the single web application."""
from importlib.metadata import version

from aiortc.codecs import h264, vpx


def validate_video_bitrate(value):
    if (not isinstance(value, dict) or set(value) != {"min", "start", "max"} or
            any(type(item) is not int for item in value.values()) or
            not 100_000 <= value["min"] <= value["start"] <= value["max"] <= 20_000_000):
        raise ValueError("viewer_bitrate_bps requires integer min <= start <= max, 100000..20000000")
    return dict(value)


def configure_video_bitrate(value):
    """Keep REMB congestion adaptation; raise encoder start and ceiling only.

    aiortc 1.15.0 exposes no public encoder bitrate configuration API.
    Its codec module defaults apply process-wide to future outbound encoders.
    Use one app / policy per process; do not change this while serving viewers.
    This does not configure the smartphone's independent encoder.
    """
    policy = validate_video_bitrate(value)
    if version("aiortc") != "1.15.0":
        raise RuntimeError("video bitrate adapter requires aiortc==1.15.0")
    for codec in (h264, vpx):
        codec.MIN_BITRATE = policy["min"]
        codec.DEFAULT_BITRATE = policy["start"]
        codec.MAX_BITRATE = policy["max"]
