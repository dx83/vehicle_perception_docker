"""Stable, renderer-independent public result schema."""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from torch import Tensor


@dataclass(frozen=True, slots=True)
class MaskGeometry:
    """Immutable packed binary ROI in source-frame pixel coordinates."""

    x: int
    y: int
    width: int
    height: int
    packed_bits: bytes

    @classmethod
    def from_binary(cls, mask: np.ndarray | Tensor) -> MaskGeometry | None:
        import torch

        if isinstance(mask, torch.Tensor):
            if mask.ndim != 2 or mask.dtype != torch.bool:
                raise ValueError("mask must be a 2D boolean array")
            ys = torch.nonzero(mask.any(dim=1), as_tuple=True)[0]
            xs = torch.nonzero(mask.any(dim=0), as_tuple=True)[0]
            if not xs.numel():
                return None
            x1, y1, x2, y2 = torch.stack((
                xs[0], ys[0], xs[-1] + 1, ys[-1] + 1,
            )).tolist()
            # Only a requested public ROI is copied to the CPU for packing.
            roi = mask[y1:y2, x1:x2].detach().cpu().numpy()
            return cls(x1, y1, x2 - x1, y2 - y1,
                       np.packbits(roi, bitorder="big").tobytes())
        if mask.ndim != 2 or mask.dtype != np.bool_:
            raise ValueError("mask must be a 2D boolean array")
        ys, xs = np.nonzero(mask)
        if not len(xs):
            return None
        x1, x2 = int(xs.min()), int(xs.max()) + 1
        y1, y2 = int(ys.min()), int(ys.max()) + 1
        roi = mask[y1:y2, x1:x2]
        return cls(x1, y1, x2 - x1, y2 - y1,
                   np.packbits(roi, bitorder="big").tobytes())


@dataclass(frozen=True, slots=True)
class DetectedObject:
    track_id: int | None
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]
    distance_m: float | None
    distance_zone: str
    state: str
    lifecycle_state: str
    mask: MaskGeometry | None = None


@dataclass(frozen=True, slots=True)
class InferenceResult:
    frame_id: int
    timestamp: float
    objects: tuple[DetectedObject, ...]
