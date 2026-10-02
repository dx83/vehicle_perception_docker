"""Offline UniDepth V2 metric-depth backend configured by RuntimeConfig."""
from __future__ import annotations
from dataclasses import dataclass

import os
import numpy as np

from .config import RuntimeConfig


@dataclass(frozen=True, slots=True)
class DepthFrame:
    width: int
    height: int
    tensor: object


class DepthEstimator:
    def __init__(self, config: RuntimeConfig) -> None:
        model_path = config.depth_model
        required = ("config.json", "model.safetensors")
        missing = [name for name in required if not (model_path / name).is_file()]
        if missing:
            raise FileNotFoundError(f"Local UniDepth model is incomplete: {missing}")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import torch
        from unidepth.models import UniDepthV2
        self._device = torch.device(config.device)
        self._camera_intrinsic = np.asarray(config.camera_intrinsic, dtype=np.float32).copy()
        self._model = UniDepthV2.from_pretrained(
            str(model_path), local_files_only=True).to(self._device).eval()
        self._model.resolution_level = config.depth_resolution_level
        self._model.encode_decode = torch.compile(
            self._model.encode_decode, mode="default", fullgraph=False)

    def predict(self, frame: np.ndarray) -> DepthFrame:
        import torch
        height, width = frame.shape[:2]
        rgb = torch.from_numpy(frame[:, :, ::-1].copy()).permute(2, 0, 1).to(self._device)
        camera = torch.as_tensor(self._camera_intrinsic.copy(), device=self._device)
        with torch.inference_mode():
            output = self._model.infer(rgb, camera)
        depth = output["depth"]
        if tuple(depth.shape) != (1, 1, height, width):
            raise RuntimeError("UniDepth output is not aligned to the native frame")
        return DepthFrame(width, height, depth[0, 0].detach().float())
