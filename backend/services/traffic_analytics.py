"""Unified traffic analytics: counting + density + congestion + time windows.

Orchestrates the existing VehicleCounter, DensityAnalyzer and CongestionAnalyzer
frame by frame. State is lightweight (no frames are retained). Time comes from the
source FPS: ``time_s = frame_index / fps``.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from backend.config.vision_config import DEFAULT_WINDOW_SECONDS
from backend.schemas.traffic import (
    DensityLevel,
    FrameStats,
    TrafficAnalyticsResult,
    WindowSummary,
)
from backend.services.congestion_analyzer import CongestionAnalyzer, detect_trend
from backend.services.density_analyzer import DensityAnalyzer
from backend.services.tracker import TrackedVehicle
from backend.services.vehicle_counter import VehicleCounter


class AnalyticsConfigError(ValueError):
    """Raised for invalid analytics configuration."""


class _Window:
    def __init__(self, index: int) -> None:
        self.index = index
        self.frames = 0
        self.detections = 0
        self.ids: set[int] = set()
        self.by_direction: dict[str, int] = {}
        self.by_class: dict[str, int] = {}
        self.region_sum: dict[str, int] = {}
        self.peak_density: dict[str, DensityLevel] = {}
        self.congestion: dict[str, str] = {}


class TrafficAnalytics:
    def __init__(
        self,
        counter: VehicleCounter | None = None,
        density: DensityAnalyzer | None = None,
        congestion: CongestionAnalyzer | None = None,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
    ) -> None:
        if not (isinstance(window_seconds, (int, float)) and math.isfinite(window_seconds) and window_seconds > 0):
            raise AnalyticsConfigError("window_seconds must be a positive number.")
        if congestion is not None and density is None:
            raise AnalyticsConfigError("CongestionAnalyzer needs a DensityAnalyzer (regions) to work from.")
        if density is not None and congestion is None:
            congestion = CongestionAnalyzer()
        self.counter, self.density, self.congestion = counter, density, congestion
        self.window_seconds = float(window_seconds)
        self.reset(25.0)

    def reset(self, fps: float) -> None:
        """Start a new video: clears all analytics state (including the counter)."""
        if not (isinstance(fps, (int, float)) and math.isfinite(fps) and fps > 0):
            raise AnalyticsConfigError("fps must be a positive number.")
        self.fps = float(fps)
        for part in (self.counter, self.density, self.congestion):
            if part is not None:
                part.reset()
        self._frames = 0
        self._last_index = -1
        self._detections = 0
        self._ids_class: dict[int, str] = {}
        self._max_vehicles = 0
        self._peak_frame = None
        self._window: _Window | None = None
        self._windows: list[WindowSummary] = []
        self._window_means: list[float] = []

    def update(
        self,
        frame_index: int,
        vehicles: Iterable[TrackedVehicle],
        speeds_kmh: dict[str, float] | None = None,
    ) -> FrameStats:
        vehicles = list(vehicles)
        t = frame_index / self.fps
        widx = int(t // self.window_seconds)
        if self._window is None or widx != self._window.index:
            self._close_window()
            self._window = _Window(widx)
        w = self._window

        events = [e.to_dict() for e in self.counter.update(vehicles)] if self.counter else []
        densities = self.density.update(vehicles) if self.density else []
        cong = self.congestion.update(densities, t, speeds_kmh) if self.congestion else []

        n = len(vehicles)
        self._frames += 1
        self._last_index = frame_index
        self._detections += n
        if n > self._max_vehicles:
            self._max_vehicles, self._peak_frame = n, frame_index
        for v in vehicles:
            self._ids_class[v.track_id] = v.class_name
        w.frames += 1
        w.detections += n
        w.ids.update(v.track_id for v in vehicles)
        for e in events:
            w.by_direction[e["direction"]] = w.by_direction.get(e["direction"], 0) + 1
            w.by_class[e["class_name"]] = w.by_class.get(e["class_name"], 0) + 1
        for d in densities:
            w.region_sum[d.region] = w.region_sum.get(d.region, 0) + d.vehicle_count
            if d.region not in w.peak_density or d.level.rank > w.peak_density[d.region].rank:
                w.peak_density[d.region] = d.level
        for c in cong:
            w.congestion[c.region] = c.level.value

        return FrameStats(frame_index, t, n, sorted(v.track_id for v in vehicles), events, densities, cong)

    def _close_window(self) -> None:
        w = self._window
        if w is None or w.frames == 0:
            return
        self._windows.append(self._summarise(w))
        self._window_means.append(w.detections / w.frames)

    def _summarise(self, w: _Window) -> WindowSummary:
        start = w.index * self.window_seconds
        return WindowSummary(
            window_index=w.index,
            start_s=round(start, 3),
            end_s=round(start + self.window_seconds, 3),
            frames=w.frames,
            detections=w.detections,
            unique_vehicles=len(w.ids),
            mean_vehicles_per_frame=round(w.detections / w.frames, 3),
            crossings_by_direction=dict(sorted(w.by_direction.items())),
            crossings_by_class=dict(sorted(w.by_class.items())),
            mean_region_vehicle_count={k: round(v / w.frames, 3) for k, v in sorted(w.region_sum.items())},
            peak_density_level={k: v.value for k, v in sorted(w.peak_density.items())},
            congestion_level=dict(sorted(w.congestion.items())),
        )

    def summary(self) -> TrafficAnalyticsResult:
        """Final (or running) analytics. Includes the in-progress window as a partial one."""
        windows = [w.to_dict() for w in self._windows]
        if self._window is not None and self._window.frames:
            windows.append(self._summarise(self._window).to_dict())
        by_class: dict[str, int] = {}
        for name in self._ids_class.values():
            by_class[name] = by_class.get(name, 0) + 1
        notes = [
            "total_detections counts tracked-vehicle observations per frame (one vehicle seen in N frames counts N times).",
            "unique_vehicles is the number of distinct tracker IDs; ID switches can inflate it.",
            "Actual vehicle counts are the virtual-line crossings in 'crossings'.",
            "Not evaluated against labelled Indian traffic footage; no accuracy is claimed.",
        ]
        if self.congestion is not None:
            notes.append(self.congestion.summary()["note"])
        if self.density is None:
            notes.append("No road regions configured: density and congestion are not computed.")

        if self.congestion is not None:
            trend = self.congestion.trend().value
        else:
            means = self._window_means + (
                [self._window.detections / self._window.frames] if self._window and self._window.frames else []
            )
            trend = detect_trend(means).value
        mean_v = self._detections / self._frames if self._frames else 0.0
        return TrafficAnalyticsResult(
            fps=self.fps,
            frames=self._frames,
            duration_s=round((self._last_index + 1) / self.fps, 3) if self._frames else 0.0,
            total_detections=self._detections,
            unique_vehicles=len(self._ids_class),
            unique_vehicles_by_class=dict(sorted(by_class.items())),
            crossings=self.counter.summary() if self.counter else None,
            density=self.density.summary() if self.density else None,
            congestion=self.congestion.summary() if self.congestion else None,
            traffic_trend=trend,
            frame_stats={
                "frames": self._frames,
                "mean_vehicles_per_frame": round(mean_v, 3),
                "max_vehicles_in_frame": self._max_vehicles,
                "peak_frame_index": self._peak_frame,
            },
            windows=windows,
            window_seconds=self.window_seconds,
            notes=notes,
        )
