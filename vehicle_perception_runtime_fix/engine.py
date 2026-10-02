"""Minimal stateful production perception engine."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time
from typing import Callable

import numpy as np

from .config import RuntimeConfig, load_config
from .depth import DepthEstimator
from .distance import distance_zone, fuse_distances
from .engine_pipeline import FramePacket, OrderedStreamPipeline
from .lifecycle import Lifecycle
from .result import DetectedObject, InferenceResult, MaskGeometry
from .segmentation import Segmenter
from .tracking import Tracker


def _intersection_over_smaller(first, second) -> float:
    first, second = np.asarray(first), np.asarray(second)
    intersection = float(np.maximum(
        0, np.minimum(first[2:], second[2:]) - np.maximum(first[:2], second[:2])).prod())
    areas = [float(np.maximum(0, row[2:] - row[:2]).prod()) for row in (first, second)]
    return intersection / min(areas) if min(areas) else 0.0


def _occlusion_proxies(rows: list[dict]) -> list[float]:
    return [max((_intersection_over_smaller(row["bbox"], other["bbox"])
                 for offset, other in enumerate(rows) if index != offset), default=0.0)
            for index, row in enumerate(rows)]


class PerceptionEngine:
    """Artifact-free Stage28 N2 runtime with bounded ordered streaming."""

    def __init__(self, config_path="vehicle_perceptzion_runtime/config.yaml", *,
                 return_masks: bool = False,
                 _components: dict[str, object] | None = None) -> None:
        if not isinstance(return_masks, bool):
            raise TypeError("return_masks must be a boolean")
        self._return_masks = return_masks
        self.config: RuntimeConfig = load_config(config_path)
        components = _components or {}
        self._segmenter = components.get("segmenter") or Segmenter(
            self.config.segmentation_model, self.config.confidence, self.config.device)
        self._tracker = components.get("tracker") or Tracker(self.config.tracker)
        self._depth = components.get("depth") or DepthEstimator(self.config)
        self._fusion: Callable = components.get("fusion") or fuse_distances
        self._lifecycle = components.get("lifecycle") or Lifecycle()
        self._segment_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="perception-segment")
        self._depth_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="perception-depth")
        self._segment_stream = self._depth_stream = None
        if self.config.device.startswith("cuda") and not components:
            import torch
            self._segment_stream = torch.cuda.Stream(device=self.config.device)
            self._depth_stream = torch.cuda.Stream(device=self.config.device)
        self._next_frame = 0
        self._closed = False
        self._processing = False
        self._workers_joined = False
        self._streams_processed = 0
        self._last_stream_health: dict[str, object] | None = None
        self._last_frame_profile: dict[str, float] | None = None

    @staticmethod
    def _predict(component, frame, stream):
        if stream is None:
            return component.predict(frame)
        import torch
        with torch.cuda.stream(stream):
            result = component.predict(frame)
        stream.synchronize()
        return result

    @classmethod
    def _predict_timed(cls, component, frame, stream):
        started = time.perf_counter()
        result = cls._predict(component, frame, stream)
        return result, (time.perf_counter() - started) * 1000.0

    @staticmethod
    def _validate_frame(frame: np.ndarray) -> None:
        if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or
                frame.ndim != 3 or frame.shape[2] != 3 or frame.size == 0):
            raise ValueError("frame must be a non-empty uint8 HxWx3 OpenCV BGR array")

    def warmup(self, frame: np.ndarray, iterations: int = 3) -> None:
        """Compile/warm model paths without advancing tracking or lifecycle state."""
        if self._closed:
            raise RuntimeError("PerceptionEngine is closed")
        self._validate_frame(frame)
        if not isinstance(iterations, int) or iterations < 1:
            raise ValueError("warmup iterations must be a positive integer")
        for _ in range(iterations):
            segmentation = self._segment_pool.submit(
                self._predict, self._segmenter, frame, self._segment_stream)
            depth = self._depth_pool.submit(
                self._predict, self._depth, frame, self._depth_stream)
            segmentation.result(); depth.result()

    def _schedule(self, frame: np.ndarray):
        self._validate_frame(frame)
        return (
            self._segment_pool.submit(
                self._predict_timed, self._segmenter, frame, self._segment_stream),
            self._depth_pool.submit(
                self._predict_timed, self._depth, frame, self._depth_stream),
        )

    def _commit(self, frame_id: int, timestamp: float, frame: np.ndarray,
                scheduled) -> InferenceResult:
        segmentation_future, depth_future = scheduled
        wait_started = time.perf_counter()
        segmentation, segmentation_ms = segmentation_future.result()
        segmentation_wait_ms = (time.perf_counter() - wait_started) * 1000.0
        rows = [{
                "object_index": index,
                "raw_class_name": obj.class_name,
                "application_class": self.config.application_classes[obj.class_name],
                "confidence": float(obj.confidence),
                "bbox": obj.bbox,
        } for index, obj in enumerate(segmentation.objects)
            if obj.class_name in self.config.application_classes]
        started = time.perf_counter()
        assignments = self._tracker.update(frame_id, rows, frame)
        tracking_ms = (time.perf_counter() - started) * 1000.0
        wait_started = time.perf_counter()
        depth, depth_ms = depth_future.result()
        depth_wait_ms = (time.perf_counter() - wait_started) * 1000.0
        started = time.perf_counter()
        metrics = self._fusion(segmentation, depth, self.config.application_classes)
        fusion_ms = (time.perf_counter() - started) * 1000.0
        by_index = {row["object_index"]: row for row in metrics}
        if set(by_index) != {row["object_index"] for row in rows}:
            raise ValueError("tracker and distance observations differ")
        observations = []
        for row, assignment, proxy in zip(rows, assignments, _occlusion_proxies(rows)):
            observations.append({**row, **by_index[row["object_index"]], **assignment,
                                 "occlusion_proxy": proxy})
        started = time.perf_counter()
        stabilized = self._lifecycle.process(frame_id, observations)
        lifecycle_ms = (time.perf_counter() - started) * 1000.0
        objects = tuple(DetectedObject(
            track_id=row["track_id"],
            class_name=row["application_class"],
            confidence=float(row["confidence"]),
            bbox=tuple(float(value) for value in row["bbox"]),
            distance_m=row["raw_distance_m"],
            distance_zone=distance_zone(row["raw_distance_m"], self.config.near_max_m,
                                        self.config.mid_max_m),
            state=row["distance_state"],
            lifecycle_state=row["lifecycle_state"],
            mask=(MaskGeometry.from_binary(segmentation.objects[row["object_index"]].mask)
                  if self._return_masks else None),
        ) for row in stabilized)
        self._last_frame_profile = {
            "segmentation_ms": segmentation_ms,
            "segmentation_wait_ms": segmentation_wait_ms,
            "tracking_ms": tracking_ms,
            "depth_ms": depth_ms,
            "depth_wait_ms": depth_wait_ms,
            "fusion_ms": fusion_ms,
            "lifecycle_ms": lifecycle_ms,
        }
        return InferenceResult(frame_id, timestamp, objects)

    def process(self, frame: np.ndarray, timestamp: float | None = None) -> InferenceResult:
        if self._closed:
            raise RuntimeError("PerceptionEngine is closed")
        if self._processing:
            raise RuntimeError("PerceptionEngine.process is not thread-safe or reentrant")
        self._validate_frame(frame)
        self._processing = True
        try:
            frame_id = self._next_frame
            result = self._commit(
                frame_id, float(time.time() if timestamp is None else timestamp),
                frame, self._schedule(frame))
            self._next_frame += 1
            return result
        finally:
            self._processing = False

    def _reset_stream_state(self) -> None:
        if not hasattr(self._tracker, "reset") or not hasattr(self._lifecycle, "reset"):
            if self._next_frame:
                raise RuntimeError("injected stream state components must implement reset()")
        else:
            self._tracker.reset()
            self._lifecycle.reset()
        self._next_frame = 0

    def process_stream(self, frame_source):
        """Yield ordered results from a bounded iterable frame source."""
        if self._closed:
            raise RuntimeError("PerceptionEngine is closed")
        if self._processing:
            raise RuntimeError("PerceptionEngine is not thread-safe or reentrant")
        self._processing = True
        pipeline = OrderedStreamPipeline(
            self.config.queue_capacity, self.config.max_inflight_frames)
        try:
            self._reset_stream_state()

            def schedule(packet: FramePacket):
                return self._schedule(packet.frame)

            def commit(packet: FramePacket, scheduled):
                result = self._commit(
                    packet.index, packet.timestamp, packet.frame, scheduled)
                self._next_frame = packet.index + 1
                return result

            yield from pipeline.run(frame_source, schedule, commit)
            self._streams_processed += 1
        finally:
            self._last_stream_health = pipeline.health
            self._processing = False

    @property
    def diagnostics(self) -> dict[str, object]:
        return {
            "segmentation_model_initializations": 1,
            "depth_model_initializations": 1,
            "streams_processed": self._streams_processed,
            "engine_workers_joined": self._workers_joined,
            "last_stream_health": (
                dict(self._last_stream_health) if self._last_stream_health else None),
            "last_frame_profile": (
                dict(self._last_frame_profile) if self._last_frame_profile else None),
        }

    def close(self) -> None:
        if not self._closed:
            self._lifecycle.close()
            self._segment_pool.shutdown(wait=True, cancel_futures=True)
            self._depth_pool.shutdown(wait=True, cancel_futures=True)
            self._workers_joined = True
            self._closed = True
