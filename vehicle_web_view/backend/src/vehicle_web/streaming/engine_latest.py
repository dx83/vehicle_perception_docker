"""One-slot latest input and bounded frame/result pairing."""
from dataclasses import dataclass
from threading import Condition
import time

import numpy as np


@dataclass(frozen=True)
class Observation:
    frame: np.ndarray
    source_index: int
    received_at: float


class LatestInput:
    def __init__(self):
        self.condition = Condition()
        self.pending = None
        self.closed = False
        self.received = 0
        self.dropped = 0
        self.last_received = time.monotonic()

    def put(self, frame):
        with self.condition:
            if self.closed:
                return
            if self.pending is not None:
                self.dropped += 1
            self.last_received = time.monotonic()
            self.pending = Observation(frame, self.received, self.last_received)
            self.received += 1
            self.condition.notify_all()

    def get(self):
        with self.condition:
            self.condition.wait_for(lambda: self.pending is not None or self.closed)
            if self.closed:
                return None
            item, self.pending = self.pending, None
            return item

    def close(self):
        with self.condition:
            self.closed = True
            self.pending = None
            self.condition.notify_all()


class PairedSource:
    """Reserve an ID only for frames admitted to the runtime FIFO."""
    def __init__(self, source, capacity=8):
        self.source = source
        self.capacity = capacity
        self.condition = Condition()
        self.frames = {}
        self.closed = False

    def __iter__(self):
        index = 0
        while True:
            with self.condition:
                self.condition.wait_for(lambda: len(self.frames) < self.capacity or self.closed)
                if self.closed:
                    return
            observation = self.source.get()
            if observation is None:
                return
            with self.condition:
                if self.closed:
                    return
                self.frames[index] = observation
            index += 1
            yield observation.frame

    def take(self, frame_id):
        with self.condition:
            item = self.frames.pop(frame_id)
            self.condition.notify_all()
            return item

    def close(self):
        self.source.close()
        with self.condition:
            self.closed = True
            self.condition.notify_all()
