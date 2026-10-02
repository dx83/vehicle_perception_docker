"""Public API for the lightweight vehicle perception runtime."""

from .engine import PerceptionEngine
from .result import DetectedObject, InferenceResult, MaskGeometry

__all__ = ("PerceptionEngine", "DetectedObject", "InferenceResult", "MaskGeometry")
