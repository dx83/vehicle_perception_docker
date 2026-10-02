"""Stage28 N2 exact positive-finite instance-mask median fusion."""
from __future__ import annotations

import math


def _exact_quantile(values, quantile: float):
    count = int(values.numel())
    if count == 0:
        raise ValueError("quantile requires at least one value")
    position = (count - 1) * quantile
    lower, upper = math.floor(position), math.ceil(position)
    low = values.kthvalue(lower + 1).values
    if lower == upper:
        return low
    high = values.kthvalue(upper + 1).values
    return low + (high - low) * (position - lower)


def fuse_distances(segmentation, depth, application_classes: dict[str, str]) -> list[dict]:
    import torch
    if (segmentation.width, segmentation.height) != (depth.width, depth.height):
        raise ValueError("segmentation and depth are not aligned")
    targets = [(index, obj, application_classes.get(obj.class_name))
               for index, obj in enumerate(segmentation.objects)
               if application_classes.get(obj.class_name) is not None]
    if not targets:
        return []
    # Same-device tensor inputs stay on the GPU. NumPy inputs remain supported
    # for callers that inject their own segmentation component.
    mask_tensors = [torch.as_tensor(obj.mask, dtype=torch.bool, device=depth.tensor.device)
                    for _, obj, _ in targets]
    if any(tuple(mask.shape) != (depth.height, depth.width) for mask in mask_tensors):
        raise ValueError("instance mask shape mismatch")
    masks = torch.stack(mask_tensors)
    mask_counts = masks.sum(dim=(1, 2))
    valid_depth = torch.isfinite(depth.tensor) & (depth.tensor > 0)
    workspace = torch.empty_like(valid_depth)
    scalar_rows = []
    for offset in range(len(targets)):
        torch.logical_and(masks[offset], valid_depth, out=workspace)
        values = depth.tensor[workspace]
        median = (_exact_quantile(values, 0.5).to(torch.float64) if values.numel()
                  else torch.full((), float("nan"), device=depth.tensor.device,
                                  dtype=torch.float64))
        scalar_rows.append(torch.stack((
            mask_counts[offset].to(torch.float64),
            torch.as_tensor(int(values.numel()), device=depth.tensor.device,
                            dtype=torch.float64),
            median,
        )))
    host = torch.stack(scalar_rows).cpu().numpy()
    rows = []
    for (object_index, obj, group), values in zip(targets, host):
        valid_count = int(values[1])
        rows.append({
            "object_index": object_index,
            "raw_class_name": obj.class_name,
            "application_class": group,
            "confidence": float(obj.confidence),
            "bbox": obj.bbox,
            "mask_area": int(values[0]),
            "raw_distance_m": float(values[2]) if valid_count else None,
        })
    return rows


def distance_zone(value: float | None, near_max_m: float, mid_max_m: float) -> str:
    if value is None or not math.isfinite(value) or value <= 0:
        return "UNKNOWN"
    if value <= near_max_m:
        return "NEAR"
    if value <= mid_max_m:
        return "MID"
    return "FAR"
