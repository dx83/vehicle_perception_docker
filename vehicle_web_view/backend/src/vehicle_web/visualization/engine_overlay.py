"""Draw public runtime results; no inference or disk output."""
import cv2
import numpy as np


COLORS = {"vehicle": (80, 220, 80), "person": (50, 180, 255),
          "two_wheeler": (220, 140, 80)}


def render(frame, result):
    output = frame.copy()
    height, width = frame.shape[:2]
    for obj in result.objects:
        color = COLORS.get(obj.class_name, (200, 200, 200))
        mask = obj.mask
        if mask is not None:
            if not (0 <= mask.x < width and 0 <= mask.y < height and
                    mask.x + mask.width <= width and mask.y + mask.height <= height):
                raise ValueError("mask ROI outside source frame")
            binary = np.unpackbits(np.frombuffer(mask.packed_bits, dtype=np.uint8),
                                   bitorder="big", count=mask.width * mask.height)
            binary = binary.reshape(mask.height, mask.width).astype(bool)
            roi = output[mask.y:mask.y + mask.height, mask.x:mask.x + mask.width]
            roi[binary] = (roi[binary] * 0.65 + np.asarray(color) * 0.35).astype(np.uint8)
        x1, y1, x2, y2 = [int(v) for v in obj.bbox]
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        distance = "N/A" if obj.distance_m is None else f"{obj.distance_m:.1f}m"
        track = "-" if obj.track_id is None else str(obj.track_id)
        cv2.putText(output, f"{obj.class_name} #{track} {distance}",
                    (max(0, x1), max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    return output
