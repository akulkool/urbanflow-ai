"""Region-wise congestion classification.

Congestion is a MODEL-BASED ESTIMATE built from smoothed vehicle counts and image-plane
bounding-box coverage. Calibrated speed is used only if the caller supplies it
(``speeds_kmh``); this module never derives or invents speeds or travel times.
Direction-wise congestion is not computed: it needs per-direction regions or
calibrated per-direction speeds. Define one region per carriageway for that.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from backend.schemas.traffic import (
    CONGESTION_BASIS_ESTIMATE,
    CONGESTION_BASIS_SPEED,
    CongestionLevel,
    RegionCongestion,
    RegionDensity,
    Trend,
)

LEVELS = list(CongestionLevel)


class CongestionConfigError(ValueError):
    """Raised for invalid congestion configuration."""


@dataclass(frozen=True)
class CongestionThresholds:
    """Smoothed-signal thresholds. Counts/occupancy: at-or-above; speed: at-or-below."""

    count_moderate: float = 4
    count_high: float = 8
    count_severe: float = 15
    occupancy_moderate: float = 0.20
    occupancy_high: float = 0.40
    occupancy_severe: float = 0.60
    speed_kmh_moderate: float = 30.0
    speed_kmh_high: float = 20.0
    speed_kmh_severe: float = 10.0
    # bbox coverage is ignored below this smoothed vehicle count: a single large,
    # near-camera vehicle can cover much of a region without any congestion.
    min_vehicles_for_occupancy: float = 3

    def __post_init__(self) -> None:
        if not 0 < self.count_moderate < self.count_high < self.count_severe:
            raise CongestionConfigError("Count thresholds must satisfy 0 < moderate < high < severe.")
        if not 0 < self.occupancy_moderate < self.occupancy_high < self.occupancy_severe <= 1:
            raise CongestionConfigError("Occupancy thresholds must satisfy 0 < moderate < high < severe <= 1.")
        if not self.speed_kmh_moderate > self.speed_kmh_high > self.speed_kmh_severe > 0:
            raise CongestionConfigError("Speed thresholds must satisfy moderate > high > severe > 0.")

    @staticmethod
    def _rank(value: float, mod: float, high: float, sev: float, lower_is_worse: bool = False) -> CongestionLevel:
        if lower_is_worse:
            r = 3 if value <= sev else 2 if value <= high else 1 if value <= mod else 0
        else:
            r = 3 if value >= sev else 2 if value >= high else 1 if value >= mod else 0
        return LEVELS[r]

    def by_count(self, v: float) -> CongestionLevel:
        return self._rank(v, self.count_moderate, self.count_high, self.count_severe)

    def by_occupancy(self, v: float) -> CongestionLevel:
        return self._rank(v, self.occupancy_moderate, self.occupancy_high, self.occupancy_severe)

    def by_speed(self, v: float) -> CongestionLevel:
        return self._rank(v, self.speed_kmh_moderate, self.speed_kmh_high, self.speed_kmh_severe, True)


def detect_trend(values: Sequence[float], rel_tol: float = 0.15, min_abs_delta: float = 1.0) -> Trend:
    """Compare the mean of the latest k samples with the k before (k = min(5, n // 2))."""
    n = len(values)
    if n < 2:
        return Trend.INSUFFICIENT_DATA
    k = min(5, n // 2)
    prev = sum(values[-2 * k : -k]) / k
    recent = sum(values[-k:]) / k
    delta = recent - prev
    if abs(delta) < max(min_abs_delta, rel_tol * max(prev, 0.0)):
        return Trend.STABLE
    return Trend.INCREASING if delta > 0 else Trend.DECREASING


class CongestionAnalyzer:
    def __init__(
        self,
        thresholds: CongestionThresholds | None = None,
        smoothing_frames: int = 15,
        history_interval_s: float = 1.0,
        history_limit: int = 600,
    ) -> None:
        if not isinstance(smoothing_frames, int) or smoothing_frames < 1:
            raise CongestionConfigError("smoothing_frames must be a positive integer.")
        if not (isinstance(history_interval_s, (int, float)) and history_interval_s > 0):
            raise CongestionConfigError("history_interval_s must be positive.")
        if not isinstance(history_limit, int) or history_limit < 2:
            raise CongestionConfigError("history_limit must be an integer >= 2.")
        self.thresholds = thresholds or CongestionThresholds()
        self.smoothing_frames = smoothing_frames
        self.history_interval_s = float(history_interval_s)
        self.history_limit = history_limit
        self.reset()

    def reset(self) -> None:
        self._windows: dict[str, deque] = {}
        self._level_frames: dict[str, dict[str, int]] = {}
        self._history: deque = deque(maxlen=self.history_limit)
        self._last_sample_t: float | None = None
        self._used_speed = False

    def update(
        self,
        densities: Iterable[RegionDensity],
        time_s: float,
        speeds_kmh: dict[str, float] | None = None,
    ) -> list[RegionCongestion]:
        """Classify each region for this frame from its (smoothed) density measurements."""
        speeds_kmh = speeds_kmh or {}
        out: list[RegionCongestion] = []
        pressure = 0.0
        for d in densities:
            win = self._windows.setdefault(d.region, deque(maxlen=self.smoothing_frames))
            win.append((d.vehicle_count, d.occupancy_estimate))
            mean_count = sum(c for c, _ in win) / len(win)
            occs = [o for _, o in win if o is not None]
            mean_occ = sum(occs) / len(occs) if occs else None

            signals = {"vehicle_count": self.thresholds.by_count(mean_count)}
            if mean_occ is not None and mean_count >= self.thresholds.min_vehicles_for_occupancy:
                signals["bbox_coverage"] = self.thresholds.by_occupancy(mean_occ)
            speed = speeds_kmh.get(d.region)
            if speed is not None:
                if not (isinstance(speed, (int, float)) and math.isfinite(speed) and speed >= 0):
                    raise CongestionConfigError(f"Invalid speed for region '{d.region}': {speed!r}")
                signals["calibrated_speed"] = self.thresholds.by_speed(speed)
                self._used_speed = True
            level = max(signals.values(), key=lambda l: l.rank)
            out.append(
                RegionCongestion(
                    region=d.region,
                    level=level,
                    smoothed_vehicle_count=round(mean_count, 3),
                    smoothed_occupancy_estimate=round(mean_occ, 4) if mean_occ is not None else None,
                    speed_kmh=float(speed) if speed is not None else None,
                    signals={k: v.value for k, v in signals.items()},
                    basis=CONGESTION_BASIS_SPEED if speed is not None else CONGESTION_BASIS_ESTIMATE,
                    is_estimate=speed is None,
                )
            )
            lf = self._level_frames.setdefault(d.region, {l.value: 0 for l in CongestionLevel})
            lf[level.value] += 1
            pressure += mean_count

        if out and (self._last_sample_t is None or time_s - self._last_sample_t >= self.history_interval_s):
            self._last_sample_t = time_s
            self._history.append(
                {
                    "time_s": round(time_s, 3),
                    "overall_level": max((c.level for c in out), key=lambda l: l.rank).value,
                    "levels": {c.region: c.level.value for c in out},
                    "pressure_vehicles": round(pressure, 3),
                }
            )
        return out

    def trend(self) -> Trend:
        """Trend of total smoothed vehicle count across regions over the sampled history."""
        return detect_trend([h["pressure_vehicles"] for h in self._history])

    def summary(self) -> dict[str, Any]:
        regions = {}
        for name, lf in self._level_frames.items():
            total = max(sum(lf.values()), 1)
            peak = max((CongestionLevel(k) for k, v in lf.items() if v), key=lambda l: l.rank)
            regions[name] = {
                "peak_level": peak.value,
                "level_frame_fractions": {k: round(v / total, 3) for k, v in lf.items()},
            }
        return {
            "is_estimate": not self._used_speed,
            "basis": CONGESTION_BASIS_SPEED if self._used_speed else CONGESTION_BASIS_ESTIMATE,
            "note": "Model-based estimate from vehicle counts and image-plane bbox coverage"
            + ("; calibrated speed supplied for some regions." if self._used_speed else "; no calibrated speed available."),
            "trend": self.trend().value,
            "regions": regions,
            "direction_congestion": {
                "supported": False,
                "reason": "Requires per-direction regions or calibrated per-direction speeds.",
            },
            "history": list(self._history),
        }
