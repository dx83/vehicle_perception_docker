"""Isolated aiortc 1.15 timing hook; never changes media/encoding policy."""
from collections import deque
import time

from importlib.metadata import version


def measure_sender(sender, track):
    # aiortc has no public totalEncodeTime field. Keep this versioned hook separate.
    if version("aiortc") != "1.15.0" or not hasattr(sender, "_next_encoded_frame"):
        raise RuntimeError("encode timing adapter requires aiortc 1.15.0")
    original = sender._next_encoded_frame
    metrics = {"encoded_frames": 0, "encode_and_prepare_ms": None,
               "video_frame_conversion_ms": None, "encoded_fps": 0.0,
               "packets_sent": 0, "bytes_sent": 0, "round_trip_ms": None}
    times = deque(maxlen=120)

    async def measured(codec):
        result = await original(codec)
        if result is not None:
            now = time.perf_counter()
            # recv() sets delivery time immediately before returning. Input wait excluded.
            metrics["encode_and_prepare_ms"] = (now - track.delivered_at) * 1000
            metrics["video_frame_conversion_ms"] = track.conversion_ms
            metrics["encoded_frames"] += 1
            times.append(now)
            metrics["encoded_fps"] = ((len(times) - 1) / (times[-1] - times[0])
                                      if len(times) > 1 and times[-1] > times[0] else 0)
        return result

    sender._next_encoded_frame = measured
    return metrics


async def collect_transport(peer, sender, metrics):
    report = await sender.getStats()
    for row in report.values():
        if row.type == "outbound-rtp":
            metrics["packets_sent"] = row.packetsSent
            metrics["bytes_sent"] = row.bytesSent
        elif row.type == "remote-inbound-rtp":
            value = getattr(row, "roundTripTime", None)
            metrics["round_trip_ms"] = None if value is None else value * 1000
