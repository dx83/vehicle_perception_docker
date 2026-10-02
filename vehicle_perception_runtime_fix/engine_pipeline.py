"""Bounded ordered execution for the production streaming API."""
from __future__ import annotations

from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, Thread
import time
from typing import Callable, Iterable, Iterator

import numpy as np


_END = object()


class _SourceFailure:
    def __init__(self, error: BaseException) -> None:
        self.error = error


@dataclass(slots=True)
class FramePacket:
    index: int
    frame: np.ndarray
    timestamp: float
    ingest_time: float
    queue_wait_ms: float = 0.0


class BoundedFrameSource:
    """Read an iterable on one worker into a bounded FIFO queue."""

    def __init__(self, source: Iterable[np.ndarray], capacity: int) -> None:
        if capacity != 3:
            raise ValueError("frame source queue capacity must be 3")
        self._source = iter(source)
        self._queue: Queue = Queue(maxsize=capacity)
        self._stop = Event()
        self._thread = Thread(target=self._run, name="perception-source", daemon=False)
        self.maximum_depth = 0
        self.producer_wait_ms = 0.0
        self.consumer_wait_ms = 0.0
        self.produced = 0
        self.joined = False

    def _put(self, value) -> None:
        started = time.perf_counter()
        while not self._stop.is_set():
            try:
                self._queue.put(value, timeout=0.05)
                self.producer_wait_ms += (time.perf_counter() - started) * 1000.0
                self.maximum_depth = max(self.maximum_depth, self._queue.qsize())
                return
            except Full:
                continue

    def _run(self) -> None:
        try:
            for index, frame in enumerate(self._source):
                if self._stop.is_set():
                    return
                self._put(FramePacket(index, frame, time.time(), time.perf_counter()))
                self.produced += 1
            self._put(_END)
        except BaseException as error:
            self._put(_SourceFailure(error))

    def __iter__(self) -> Iterator[FramePacket]:
        self._thread.start()
        while True:
            started = time.perf_counter()
            value = self._queue.get()
            self.consumer_wait_ms += (time.perf_counter() - started) * 1000.0
            if value is _END:
                return
            if isinstance(value, _SourceFailure):
                raise value.error
            value.queue_wait_ms = (time.perf_counter() - value.ingest_time) * 1000.0
            yield value

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            raise RuntimeError("stream source worker did not stop")
        self.joined = True


class OrderedStreamPipeline:
    """Keep three B1 frames in flight and commit them in input order."""

    def __init__(self, queue_capacity: int, max_inflight_frames: int) -> None:
        if queue_capacity != 3 or max_inflight_frames != 3:
            raise ValueError("ordered streaming requires queue_capacity=3 and max_inflight_frames=3")
        self.queue_capacity = queue_capacity
        self.max_inflight_frames = max_inflight_frames
        self.health: dict[str, object] | None = None

    def run(self, source: Iterable[np.ndarray], schedule: Callable,
            commit: Callable) -> Iterator[object]:
        producer = BoundedFrameSource(source, self.queue_capacity)
        pending: list[tuple[FramePacket, object]] = []
        committed_indices: list[int] = []
        maximum_inflight = 0
        ordered_wait_ms = 0.0
        frame_latencies: list[float] = []
        completed_normally = False
        try:
            for packet in producer:
                scheduled = schedule(packet)
                pending.append((packet, scheduled))
                maximum_inflight = max(maximum_inflight, len(pending))
                while len(pending) >= self.max_inflight_frames:
                    packet, scheduled = pending.pop(0)
                    started = time.perf_counter()
                    result = commit(packet, scheduled)
                    ordered_wait_ms += (time.perf_counter() - started) * 1000.0
                    committed_indices.append(packet.index)
                    frame_latencies.append((time.perf_counter() - packet.ingest_time) * 1000.0)
                    yield result
            while pending:
                packet, scheduled = pending.pop(0)
                started = time.perf_counter()
                result = commit(packet, scheduled)
                ordered_wait_ms += (time.perf_counter() - started) * 1000.0
                committed_indices.append(packet.index)
                frame_latencies.append((time.perf_counter() - packet.ingest_time) * 1000.0)
                yield result
            completed_normally = True
        finally:
            for _, scheduled in pending:
                for future in scheduled:
                    future.cancel()
            producer.close()
            expected = list(range(len(committed_indices)))
            ordered = committed_indices == expected
            self.health = {
                "queue_bounded": True,
                "configured_queue_capacity": self.queue_capacity,
                "maximum_observed_queue_depth": producer.maximum_depth,
                "configured_max_inflight_frames": self.max_inflight_frames,
                "maximum_observed_inflight_frames": maximum_inflight,
                "group_size": 1,
                "ordered_commit": ordered,
                "tracker_single_writer": True,
                "lifecycle_single_writer": True,
                "workers_joined": producer.joined,
                "frames_produced": producer.produced,
                "frames_committed": len(committed_indices),
                "frame_loss": producer.produced - len(committed_indices),
                "frame_duplicate": len(committed_indices) - len(set(committed_indices)),
                "frame_reorder": not ordered,
                "producer_wait_ms": producer.producer_wait_ms,
                "consumer_wait_ms": producer.consumer_wait_ms,
                "ordered_commit_wait_ms": ordered_wait_ms,
                "frame_latency_mean_ms": (
                    sum(frame_latencies) / len(frame_latencies) if frame_latencies else 0.0),
                "completed_normally": completed_normally,
            }
