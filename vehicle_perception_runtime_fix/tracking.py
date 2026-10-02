"""Frozen ReID-OFF BoT-SORT with one shared sparseOptFlow warp per frame."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np


GROUPS = ("person", "two_wheeler", "vehicle")


class _SharedWarpFactory:
    @staticmethod
    def build(config):
        from ultralytics.trackers.bot_sort import BOTSORT

        class SharedWarpBOTSORT(BOTSORT):
            runtime_warp = None

            def _pre_first_associate(self, strack_pool, unconfirmed, img, results_high):
                if self.runtime_warp is None:
                    raise RuntimeError("shared sparseOptFlow warp was not supplied")
                from ultralytics.trackers.utils.stracks import multi_gmc
                multi_gmc(strack_pool, self.runtime_warp)
                multi_gmc(unconfirmed, self.runtime_warp)

        native = {
            "tracker_type": "botsort",
            "track_high_thresh": config["track_high_thresh"],
            "track_low_thresh": config["track_low_thresh"],
            "new_track_thresh": config["new_track_thresh"],
            "track_buffer": config["track_buffer"],
            "match_thresh": config["match_thresh"],
            "fuse_score": config["fuse_score"],
            "gmc_method": config["gmc"],
            "proximity_thresh": config["proximity_thresh"],
            "appearance_thresh": config["appearance_thresh"],
            "with_reid": config["reid"],
            "model": "auto",
        }
        return SharedWarpBOTSORT(SimpleNamespace(**native))


class Tracker:
    def __init__(self, config: dict[str, object]) -> None:
        if config["tracker"] != "botsort" or config["reid"] is not False:
            raise ValueError("production tracking requires BoT-SORT with ReID OFF")
        if config["gmc"] != "sparseOptFlow":
            raise ValueError("production tracking requires sparseOptFlow GMC")
        self._group_trackers = {group: _SharedWarpFactory.build(config) for group in GROUPS}
        from ultralytics.trackers.utils.gmc import GMC
        self._gmc = GMC(method="sparseOptFlow")
        self._last_frame = -1
        self._identities: dict[tuple[str, int], int] = {}
        self._history: dict[int, dict[str, int]] = {}
        self._class_ids: dict[str, int] = {}

    def reset(self) -> None:
        for group_tracker in self._group_trackers.values():
            group_tracker.reset()
            group_tracker.runtime_warp = None
        self._gmc.reset_params()
        self._last_frame = -1
        self._identities.clear()
        self._history.clear()
        self._class_ids.clear()

    def update(self, frame_id: int, rows: list[dict], frame: np.ndarray) -> list[dict]:
        from ultralytics.engine.results import Boxes
        if frame_id != self._last_frame + 1:
            raise ValueError("frames must be processed sequentially from frame zero")
        self._last_frame = frame_id
        for row in rows:
            self._class_ids.setdefault(row["raw_class_name"], len(self._class_ids))
        values = np.empty((len(rows), 6), dtype=np.float32)
        groups = []
        for index, row in enumerate(rows):
            values[index] = (*row["bbox"], row["confidence"], self._class_ids[row["raw_class_name"]])
            groups.append(row["application_class"])
        warp = self._gmc.apply(frame)
        assignments = [{"track_id": None, "track_age": None, "track_confirmed": False,
                        "track_gap": None, "track_state": "UNTRACKED"} for _ in rows]
        group_values = np.asarray(groups)
        for group, group_tracker in self._group_trackers.items():
            indices = np.flatnonzero(group_values == group)
            group_tracker.runtime_warp = warp
            output = group_tracker.update(Boxes(values[indices], frame.shape[:2]), img=frame)
            for tracked in output:
                if len(tracked) != 8:
                    raise RuntimeError("unsupported installed BoT-SORT output schema")
                local = int(tracked[-1])
                if local < 0 or local >= len(indices) or tracked[-1] != local:
                    raise ValueError("invalid BoT-SORT detection index")
                index = int(indices[local])
                key = group, int(tracked[4])
                identity = self._identities.setdefault(key, len(self._identities) + 1)
                previous = self._history.get(identity)
                age = previous["age"] + 1 if previous else 1
                gap = frame_id - previous["frame"] - 1 if previous else 0
                assignments[index] = {"track_id": identity, "track_age": age,
                                      "track_confirmed": True, "track_gap": gap,
                                      "track_state": "TRACKED"}
                self._history[identity] = {"age": age, "frame": frame_id}
        ids = [row["track_id"] for row in assignments if row["track_id"] is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate track ID in one frame")
        return assignments
