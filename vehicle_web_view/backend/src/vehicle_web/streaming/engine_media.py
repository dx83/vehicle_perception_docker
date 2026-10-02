"""Latest-only fan-out, independent of viewer encoding speed."""
import asyncio
from fractions import Fraction
from threading import Lock
import time

from aiortc import VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame


class Broadcast:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.latest = None
        self.sequence = 0
        self.closed = False
        self.started = time.monotonic()
        self.last_pts = 0

    async def publish(self, frame):
        async with self.condition:
            if self.closed:
                return
            self.last_pts = max(self.last_pts + 1, int((time.monotonic() - self.started) * 90000))
            self.latest = (frame, self.last_pts)
            self.sequence += 1
            self.condition.notify_all()

    async def next(self, previous):
        async with self.condition:
            await self.condition.wait_for(lambda: self.sequence > previous or self.closed)
            if self.closed:
                raise MediaStreamError
            return self.sequence, self.latest

    async def close(self):
        async with self.condition:
            self.closed = True
            self.latest = None
            self.condition.notify_all()


class ViewerTrack(VideoStreamTrack):
    def __init__(self, broadcast):
        super().__init__()
        self.broadcast = broadcast
        self.sequence = 0
        self.delivered_at = 0.0
        self.conversion_ms = 0.0

    async def recv(self):
        self.sequence, (array, pts) = await self.broadcast.next(self.sequence)
        started = time.perf_counter()
        frame = VideoFrame.from_ndarray(array, format="bgr24")
        frame.pts = pts
        frame.time_base = Fraction(1, 90000)
        self.delivered_at = time.perf_counter()
        self.conversion_ms = (self.delivered_at - started) * 1000
        return frame


class ThreadPublisher:
    """At most one pending callback and frame cross the thread/event-loop boundary."""
    def __init__(self, loop, broadcast):
        self.loop = loop
        self.broadcast = broadcast
        self.lock = Lock()
        self.pending = None
        self.scheduled = False
        self.closed = False
        self.task = None

    def publish(self, frame):
        with self.lock:
            if self.closed:
                return
            self.pending = frame
            if not self.scheduled:
                self.scheduled = True
                self.loop.call_soon_threadsafe(self._schedule)

    def _schedule(self):
        self.task = asyncio.create_task(self._flush())

    async def _flush(self):
        while True:
            with self.lock:
                frame, self.pending = self.pending, None
                if frame is None or self.closed:
                    self.scheduled = False
                    return
            await self.broadcast.publish(frame)

    async def close(self):
        with self.lock:
            self.closed = True
            self.pending = None
        if self.task:
            await self.task
