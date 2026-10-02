"""Frozen Stage21 one-frame distance hold and track lifecycle."""
from __future__ import annotations
from dataclasses import dataclass

import math
import numpy as np


@dataclass(frozen=True, slots=True)
class StabilityPolicy:
    jump_abs_m: float = 8.0
    jump_relative: float = 0.45
    confirm_relative: float = 0.20
    min_track_age: int = 3
    history_reset_gap: int = 3


def _valid(value):
    return value is not None and math.isfinite(value) and value > 0


def _overlap(a, b):
    a, b = np.asarray(a), np.asarray(b)
    intersection = float(np.maximum(0, np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2])).prod())
    areas = [float(np.maximum(0, row[2:] - row[:2]).prod()) for row in (a, b)]
    union = sum(areas) - intersection
    return intersection / union if union else 0.0


class Lifecycle:
    def __init__(self, policy=StabilityPolicy()) -> None:
        self.policy = policy
        self._last_frame = -1
        self._last: dict[tuple[int, str], dict] = {}
        self._history: dict[tuple[int, str], dict] = {}

    def _distance_update(self, row: dict) -> dict:
        raw = row["raw_distance_m"]
        key = (row["track_id"], row["application_class"])
        previous = self._history.get(key) if row["track_id"] is not None else None
        gap = row["frame_id"] - previous["frame"] - 1 if previous else 0
        if previous and gap < 0:
            raise ValueError("distance history must be strictly ascending")
        if previous and gap > self.policy.history_reset_gap:
            previous = None
        display, state, decision = raw, "NORMAL", "PASS_RAW"
        history_age = previous["age"] + 1 if previous else 1
        pending = None
        if not _valid(raw):
            display, state, decision = None, "NO_DISTANCE", "NO_VALUE_INVENTED"
            self._history.pop(key, None)
        elif row["track_id"] is None:
            state = "UNTRACKED"
        elif (not previous or history_age < self.policy.min_track_age or
              row["track_age"] < self.policy.min_track_age):
            state = "NEW_TRACK"
        elif previous["pending"] is not None and gap == 0:
            old, candidate = previous["display"], previous["pending"]
            if abs(raw - old) / max(abs(old), 1.0) <= self.policy.confirm_relative:
                state, decision = "OUTLIER_REJECTED", "PREVIOUS_RAW_OUTLIER_RETAINED"
            elif abs(raw - candidate) / max(abs(candidate), 1.0) <= self.policy.confirm_relative:
                state, decision = "SHIFT_CONFIRMED", "ACCEPT_SUPPORTED_NEW_LEVEL"
            else:
                state, decision = "JUMP_SUSPECT", "ACCEPT_UNCERTAIN_RAW_NO_SECOND_HOLD"
        elif previous["pending"] is not None:
            state, decision = "NORMAL", "ACCEPT_RAW_PENDING_EXPIRED_AFTER_GAP"
        else:
            relative = abs(raw - previous["display"]) / max(abs(previous["display"]), 1.0)
            suspect = (abs(raw - previous["display"]) >= self.policy.jump_abs_m and
                       relative >= self.policy.jump_relative)
            if suspect and row["track_confirmed"]:
                display, state = previous["display"], "HELD_ONE_FRAME"
                decision, pending = "HOLD_ONCE_AWAIT_NEXT_OBSERVATION", raw
            elif row["occlusion_proxy"] >= 0.5:
                state = "OCCLUSION_SUSPECT"
        if row["track_id"] is not None and _valid(raw):
            self._history[key] = {"frame": row["frame_id"], "raw": raw,
                                  "display": display, "pending": pending,
                                  "age": history_age}
        return {"display_distance_m": display, "distance_state": state,
                "decision": decision}

    def process(self, frame_id: int, rows: list[dict]) -> list[dict]:
        if frame_id != self._last_frame + 1:
            raise ValueError("lifecycle requires sequential frames")
        self._last_frame = frame_id
        identities = [row["track_id"] for row in rows if row["track_id"] is not None]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate track ID in one frame")
        output = []
        for source in rows:
            row = dict(source)
            track_id = row["track_id"]
            key = (track_id, row["application_class"])
            prior = self._last.get(key) if track_id is not None else None
            gap = frame_id - prior["frame_id"] - 1 if prior else 0
            discontinuity = bool(prior and gap > 0 and
                                 _overlap(prior["bbox"], row["bbox"]) < 0.1)
            reset = bool(prior and gap > 0 and (gap > 2 or discontinuity))
            if reset:
                self._history.pop(key, None)
            row["frame_id"] = frame_id
            result = self._distance_update(row)
            if gap > 0 and result["distance_state"] == "HELD_ONE_FRAME":
                self._history.pop(key, None)
                result = self._distance_update(row)
                reset = True
            row.update(**result,
                       lifecycle_state="HISTORY_RESET" if reset else
                       "REAPPEARED" if gap > 0 else "OBSERVED")
            if track_id is not None:
                self._last[key] = row
            output.append(row)
        return output

    def close(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last_frame = -1
        self._last.clear()
        self._history.clear()
