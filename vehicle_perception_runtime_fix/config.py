"""Single-file immutable runtime configuration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


FROZEN_TRACKER = {
    "tracker": "botsort",
    "track_high_thresh": 0.25,
    "track_low_thresh": 0.1,
    "new_track_thresh": 0.25,
    "track_buffer": 30,
    "match_thresh": 0.8,
    "fuse_score": True,
    "gmc": "sparseOptFlow",
    "proximity_thresh": 0.5,
    "appearance_thresh": 0.8,
    "reid": False,
}


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    config_path: Path
    segmentation_model: Path
    depth_model: Path
    runtime_root: Path
    device: str
    confidence: float
    tracker: dict[str, Any]
    application_classes: dict[str, str]
    camera_intrinsic: tuple[tuple[float, float, float], ...]
    near_max_m: float
    mid_max_m: float
    artifacts_enabled: bool
    queue_capacity: int
    max_inflight_frames: int
    depth_resolution_level: int


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a mapping")
    return value


def _resolve(base: Path, value: object, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty path")
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def load_config(path: str | Path) -> RuntimeConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise FileNotFoundError(config_path)
    root = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "config")
    required = {"models", "device", "inference", "tracking", "distance", "paths",
                "classes", "camera", "artifacts", "pipeline"}
    if set(root) != required:
        raise ValueError(f"config keys must be exactly {sorted(required)}")

    paths = _mapping(root["paths"], "paths")
    models = _mapping(root["models"], "models")
    device = _mapping(root["device"], "device")
    inference = _mapping(root["inference"], "inference")
    tracking = _mapping(root["tracking"], "tracking")
    distance = _mapping(root["distance"], "distance")
    camera = _mapping(root["camera"], "camera")
    classes = _mapping(root["classes"], "classes")
    artifacts = _mapping(root["artifacts"], "artifacts")
    pipeline = _mapping(root["pipeline"], "pipeline")

    model_root = _resolve(config_path.parent, paths.get("model_root"), "paths.model_root")
    runtime_root = _resolve(config_path.parent, paths.get("runtime_root"), "paths.runtime_root")
    segmentation = _resolve(model_root, models.get("segmentation"), "models.segmentation")
    depth = _resolve(model_root, models.get("depth"), "models.depth")
    device_type = device.get("type")
    gpu_id = device.get("gpu_id")
    if device_type not in {"cpu", "cuda"}:
        raise ValueError("device.type must be cpu or cuda")
    if not isinstance(gpu_id, int) or gpu_id < 0:
        raise ValueError("device.gpu_id must be a nonnegative integer")
    logical_device = "cpu" if device_type == "cpu" else f"cuda:{gpu_id}"
    confidence = float(inference.get("confidence"))
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("inference.confidence must be in [0, 1]")
    resolution_level = inference.get("resolution_level")
    if type(resolution_level) is not int or not 0 <= resolution_level < 10:
        raise ValueError("inference.resolution_level must be an integer in [0, 9]")
    if tracking != FROZEN_TRACKER:
        raise ValueError("tracking configuration differs from the frozen Stage28 policy")
    if distance.get("method") != "mask_exact_median":
        raise ValueError("distance.method must be mask_exact_median")
    near, mid = float(distance.get("near_max_m")), float(distance.get("mid_max_m"))
    if not 0 < near < mid:
        raise ValueError("distance zones must satisfy 0 < near_max_m < mid_max_m")
    matrix = camera.get("intrinsic")
    if (not isinstance(matrix, list) or len(matrix) != 3 or
            any(not isinstance(row, list) or len(row) != 3 for row in matrix)):
        raise ValueError("camera.intrinsic must be a 3x3 matrix")
    intrinsic = tuple(tuple(float(value) for value in row) for row in matrix)
    application_classes = {str(key): str(value) for key, value in classes.items()}
    if set(application_classes.values()) - {"vehicle", "person", "two_wheeler"}:
        raise ValueError("classes contains an unsupported application class")
    if artifacts != {"enabled": False}:
        raise ValueError("production core requires artifacts.enabled=false")
    if pipeline != {"queue_capacity": 3, "max_inflight_frames": 3, "group_size": 1}:
        raise ValueError("pipeline configuration differs from the frozen Stage28 policy")
    return RuntimeConfig(
        config_path, segmentation, depth, runtime_root, logical_device, confidence,
        dict(tracking), application_classes, intrinsic, near, mid, False, 3, 3,
        resolution_level,
    )
