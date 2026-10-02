"""File-relative application settings and calibration gate."""
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from ..streaming.engine_video_quality import validate_video_bitrate


BACKEND_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    runtime_root: Path
    runtime_config: Path
    frontend_dist: Path
    camera_profile: dict
    ice_servers: list
    max_viewers: int
    idle_timeout_sec: float
    viewer_bitrate_bps: dict = field(default_factory=lambda: {
        "min": 250_000, "start": 4_000_000, "max": 8_000_000})

    def calibrated(self, camera: dict) -> bool:
        profile = self.camera_profile
        return profile.get("verified") is True and all(
            camera.get(key) == profile.get(key)
            for key in ("device_id", "camera_id", "width", "height", "orientation", "zoom")
        )


def load_settings(path: Path = BACKEND_ROOT / "config.yaml") -> Settings:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    def resolve(key):
        return (path.parent / data[key]).resolve()
    profile = data["camera_profile"]
    if profile.get("verified") is True:
        if not profile.get("device_id") or not profile.get("camera_id"):
            raise ValueError("verified camera profile requires device_id and camera_id")
        raw = yaml.safe_load(resolve("runtime_config").read_text(encoding="utf-8"))
        validate_intrinsic(raw["camera"]["intrinsic"], profile["width"], profile["height"])
    viewers = data["max_viewers"]
    timeout = float(data["idle_timeout_sec"])
    if type(viewers) is not int or viewers < 1 or timeout <= 0:
        raise ValueError("max_viewers and idle_timeout_sec must be positive")
    return Settings(resolve("runtime_root"), resolve("runtime_config"),
                    resolve("frontend_dist"), profile, data["ice_servers"], viewers, timeout,
                    validate_video_bitrate(data.get("viewer_bitrate_bps", {
                        "min": 250_000, "start": 4_000_000, "max": 8_000_000})))


def validate_intrinsic(value, width, height):
    k = np.asarray(value, dtype=float)
    if (k.shape != (3, 3) or not np.isfinite(k).all() or
            k[0, 0] <= 0 or k[1, 1] <= 0 or
            not 0 <= k[0, 2] < width or not 0 <= k[1, 2] < height or
            not np.allclose(k[2], [0, 0, 1])):
        raise ValueError("camera intrinsic must be calibrated for the transmitted frame")
