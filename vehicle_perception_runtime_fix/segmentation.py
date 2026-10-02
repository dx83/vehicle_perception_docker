"""Local YOLO26m instance-segmentation adapter."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from torch import Tensor


@dataclass(frozen=True, slots=True)
class SegmentationObject:
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]
    mask: Tensor | np.ndarray


@dataclass(frozen=True, slots=True)
class SegmentationFrame:
    width: int
    height: int
    objects: tuple[SegmentationObject, ...]


class Segmenter:
    def __init__(self, model_path: Path, confidence: float, device: str) -> None:
        if not model_path.is_file():
            raise FileNotFoundError(f"Local segmentation model not found: {model_path}")
        if model_path.suffix.lower() != ".pt":
            raise ValueError("segmentation model must be a local .pt file")
        from ultralytics import YOLO
        self._model: Any = YOLO(str(model_path))
        self._confidence = confidence
        self._device = device

    def predict(self, frame: np.ndarray) -> SegmentationFrame:
        import torch.nn.functional as functional

        height, width = frame.shape[:2]
        results = self._model.predict(
            source=frame, conf=self._confidence, device=self._device,
            retina_masks=True, verbose=False,
        )
        if not results or results[0].boxes is None or results[0].masks is None:
            return SegmentationFrame(width, height, ())
        result = results[0]
        boxes = result.boxes.xyxy.detach().cpu().numpy()
        classes = result.boxes.cls.detach().cpu().numpy().astype(int)
        scores = result.boxes.conf.detach().cpu().numpy()
        masks = result.masks.data.detach()
        if not (len(boxes) == len(classes) == len(scores) == len(masks)):
            raise RuntimeError("Ultralytics returned inconsistent segmentation results")
        if tuple(masks.shape[1:]) != (height, width):
            masks = functional.interpolate(
                masks.unsqueeze(1).float(), size=(height, width), mode="nearest",
            ).squeeze(1)
        masks = masks > 0.5
        names = result.names
        objects = []
        for bbox, class_id, score, mask in zip(boxes, classes, scores, masks):
            objects.append(SegmentationObject(
                str(names[int(class_id)]), float(score),
                tuple(float(value) for value in bbox),
                mask,
            ))
        return SegmentationFrame(width, height, tuple(objects))
