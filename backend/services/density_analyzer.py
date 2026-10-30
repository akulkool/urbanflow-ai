"""Region-based traffic density analysis.

Two distinct measurements are reported per region and must not be conflated:
* ``level`` / ``vehicle_count``: COUNT-based density (vehicles whose ground point
  lies inside the region polygon, thresholds configurable).
* ``occupancy_estimate``: fraction of the region's image area covered by those
  vehicles' bounding boxes. This is an image-plane geometric estimate (affected by
  perspective and box overlap handling), NOT measured road occupancy.
``vehicles_per_100m`` is only given if the user supplied a calibrated ``road_length_m``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import cv2
import numpy as np

from backend.schemas.traffic import (
    DENSITY_BASIS,
    OCCUPANCY_BASIS,
    DensityLevel,
    RegionDensity,
)
from backend.services.tracker import TrackedVehicle
from backend.services.vehicle_counter import ground_point


class RegionConfigError(ValueError):
    """Raised for invalid region or threshold configuration."""


@dataclass(frozen=True)
class DensityThresholds:
    """Minimum vehicle counts in a region for each level (below moderate_min -> LOW)."""

    moderate_min: int = 4
    high_min: int = 8
    very_high_min: int = 15

    def __post_init__(self) -> None:
        vals = (self.moderate_min, self.high_min, self.very_high_min)
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
            raise RegionConfigError("Density thresholds must be integers.")
        if not 0 < self.moderate_min < self.high_min < self.very_high_min:
            raise RegionConfigError("Density thresholds must satisfy 0 < moderate < high < very_high.")

    def classify(self, count: int) -> DensityLevel:
        if count >= self.very_high_min:
            return DensityLevel.VERY_HIGH
        if count >= self.high_min:
            return DensityLevel.HIGH
        if count >= self.moderate_min:
            return DensityLevel.MODERATE
        return DensityLevel.LOW


class Region:
    """A named road region defined by a polygon in image coordinates."""

    def __init__(
        self,
        name: str,
        polygon: Iterable[tuple[float, float]],
        road_length_m: float | None = None,
        thresholds: DensityThresholds | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise RegionConfigError("Region name must be a non-empty string.")
        try:
            pts = [(float(x), float(y)) for x, y in polygon]
        except (TypeError, ValueError) as exc:
            raise RegionConfigError(f"Region '{name}' polygon must be a list of (x, y) numbers.") from exc
        if len(pts) < 3 or not all(math.isfinite(c) for p in pts for c in p):
            raise RegionConfigError(f"Region '{name}' needs at least 3 finite points.")
        area = 0.5 * abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])))
        if area <= 0:
            raise RegionConfigError(f"Region '{name}' polygon has zero area.")
        if road_length_m is not None and not (isinstance(road_length_m, (int, float)) and road_length_m > 0):
            raise RegionConfigError(f"Region '{name}' road_length_m must be positive.")

        self.name = name
        self.polygon = pts
        self.road_length_m = float(road_length_m) if road_length_m is not None else None
        self.thresholds = thresholds
        self._contour = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
        self.x0, self.y0 = int(math.floor(min(p[0] for p in pts))), int(math.floor(min(p[1] for p in pts)))
        x1, y1 = int(math.ceil(max(p[0] for p in pts))), int(math.ceil(max(p[1] for p in pts)))
        self.w, self.h = max(x1 - self.x0, 1), max(y1 - self.y0, 1)
        mask = np.zeros((self.h, self.w), np.uint8)
        local = np.round(np.array(pts) - (self.x0, self.y0)).astype(np.int32)
        cv2.fillPoly(mask, [local], 1)
        self._mask = mask
        self.area_px = int(mask.sum())
        if self.area_px == 0:
            raise RegionConfigError(f"Region '{name}' is too small to rasterise.")

    def contains(self, point: tuple[float, float]) -> bool:
        return cv2.pointPolygonTest(self._contour, (float(point[0]), float(point[1])), False) >= 0

    def coverage(self, boxes: list[tuple[float, float, float, float]]) -> float:
        """Fraction (0..1) of this region covered by the union of the given boxes."""
        if not boxes:
            return 0.0
        canvas = np.zeros((self.h, self.w), np.uint8)
        for bx1, by1, bx2, by2 in boxes:
            lx1, lx2 = int(max(math.floor(bx1) - self.x0, 0)), int(min(math.ceil(bx2) - self.x0, self.w))
            ly1, ly2 = int(max(math.floor(by1) - self.y0, 0)), int(min(math.ceil(by2) - self.y0, self.h))
            if lx2 > lx1 and ly2 > ly1:
                canvas[ly1:ly2, lx1:lx2] = 1
        return float(np.count_nonzero(canvas & self._mask)) / self.area_px

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "polygon": [list(p) for p in self.polygon], "road_length_m": self.road_length_m}


class _History:
    def __init__(self) -> None:
        self.frames = 0
        self.count_sum = 0
        self.count_max = 0
        self.level_frames: dict[str, int] = {l.value: 0 for l in DensityLevel}
        self.class_sum: dict[str, int] = {}
        self.occ_sum = 0.0
        self.occ_max = 0.0


class DensityAnalyzer:
    def __init__(self, regions: Region | Iterable[Region], thresholds: DensityThresholds | None = None) -> None:
        self.regions = [regions] if isinstance(regions, Region) else list(regions)
        if not self.regions or not all(isinstance(r, Region) for r in self.regions):
            raise RegionConfigError("Provide at least one Region.")
        if len({r.name for r in self.regions}) != len(self.regions):
            raise RegionConfigError("Region names must be unique.")
        self.default_thresholds = thresholds or DensityThresholds()
        self.reset()

    def reset(self) -> None:
        self._history = {r.name: _History() for r in self.regions}

    def update(self, vehicles: Iterable[TrackedVehicle]) -> list[RegionDensity]:
        """Frame-level density for every region (empty regions report zero / LOW)."""
        vehicles = list(vehicles)
        points = [ground_point(v) for v in vehicles]
        out: list[RegionDensity] = []
        for r in self.regions:
            inside = [v for v, p in zip(vehicles, points) if r.contains(p)]
            by_class: dict[str, int] = {}
            for v in inside:
                by_class[v.class_name] = by_class.get(v.class_name, 0) + 1
            count = len(inside)
            occ = r.coverage([v.bbox for v in inside])
            level = (r.thresholds or self.default_thresholds).classify(count)
            per_100m = round(count / r.road_length_m * 100.0, 3) if r.road_length_m else None
            out.append(RegionDensity(r.name, count, dict(sorted(by_class.items())), level, round(occ, 4), per_100m))
            h = self._history[r.name]
            h.frames += 1
            h.count_sum += count
            h.count_max = max(h.count_max, count)
            h.level_frames[level.value] += 1
            h.occ_sum += occ
            h.occ_max = max(h.occ_max, occ)
            for k, n in by_class.items():
                h.class_sum[k] = h.class_sum.get(k, 0) + n
        return out

    def summary(self) -> dict[str, Any]:
        regions: dict[str, Any] = {}
        for r in self.regions:
            h = self._history[r.name]
            n = max(h.frames, 1)
            peak = max((DensityLevel(k) for k, v in h.level_frames.items() if v), key=lambda l: l.rank, default=None)
            regions[r.name] = {
                "frames": h.frames,
                "mean_vehicle_count": round(h.count_sum / n, 3),
                "max_vehicle_count": h.count_max,
                "peak_level": peak.value if peak else None,
                "level_frame_fractions": {k: round(v / n, 3) for k, v in h.level_frames.items()},
                "mean_vehicles_per_frame_by_class": {k: round(v / n, 3) for k, v in sorted(h.class_sum.items())},
                "mean_occupancy_estimate": round(h.occ_sum / n, 4),
                "max_occupancy_estimate": round(h.occ_max, 4),
                "region_area_px": r.area_px,
            }
        return {
            "density_basis": DENSITY_BASIS,
            "occupancy_basis": OCCUPANCY_BASIS,
            "note": "Density levels are vehicle-count based. Occupancy is an image-plane "
            "bounding-box coverage estimate, not measured road occupancy.",
            "regions": regions,
        }
