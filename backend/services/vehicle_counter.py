"""Virtual-line vehicle counting from tracked vehicles (counting only).

Each ``TrackedVehicle`` is reduced to a ground point (bottom-centre of its box).
Its signed distance to each counting line gives a side. To resist bounding-box
jitter, a track's side is only (re)confirmed when it is farther than ``tolerance``
pixels from the line (a dead-band). A crossing is counted when the track moves from
a confirmed side to the opposite confirmed side AND the path between the two
confirmed points intersects the line *segment* (not its infinite extension).
A track ID is counted at most once per line and direction. Vehicles that merely
appear near or beyond the line are never counted.

Directions: with the line running A -> B, signed distance is
``cross(B - A, P - A) / |B - A|``. Moving from the negative side to the positive
side is "forward"; positive to negative is "reverse".
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from backend.services.tracker import TrackedVehicle

FORWARD = "forward"
REVERSE = "reverse"
DIRECTIONS = (FORWARD, REVERSE)

Point = tuple[float, float]


class LineConfigError(ValueError):
    """Raised for an invalid counting-line or counter configuration."""


@dataclass(frozen=True)
class CountingLine:
    name: str
    start: Point  # image coordinates (x, y) in pixels
    end: Point

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise LineConfigError("Line name must be a non-empty string.")
        for label, pt in (("start", self.start), ("end", self.end)):
            if (
                not isinstance(pt, (tuple, list))
                or len(pt) != 2
                or not all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in pt)
            ):
                raise LineConfigError(f"Line '{self.name}' {label} must be two finite numbers (x, y).")
        object.__setattr__(self, "start", (float(self.start[0]), float(self.start[1])))
        object.__setattr__(self, "end", (float(self.end[0]), float(self.end[1])))
        if self.start == self.end:
            raise LineConfigError(f"Line '{self.name}' start and end must differ.")

    @property
    def length(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def signed_distance(self, p: Point) -> float:
        (ax, ay), (bx, by) = self.start, self.end
        return ((bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)) / self.length


@dataclass(frozen=True)
class CrossingEvent:
    line: str
    track_id: int
    class_id: int
    class_name: str
    direction: str
    frame_index: int

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class _TrackState:
    anchor: Point  # last position confirmed outside the dead-band
    side: int  # +1 / -1
    last_seen: int


def ground_point(v: TrackedVehicle) -> Point:
    x1, y1, x2, y2 = v.bbox
    return ((x1 + x2) / 2.0, max(y1, y2))


class VehicleCounter:
    def __init__(
        self,
        lines: CountingLine | Iterable[CountingLine],
        tolerance: float = 5.0,
        max_missing_frames: int = 30,
    ) -> None:
        self.lines = [lines] if isinstance(lines, CountingLine) else list(lines)
        if not self.lines or not all(isinstance(l, CountingLine) for l in self.lines):
            raise LineConfigError("Provide at least one CountingLine.")
        if len({l.name for l in self.lines}) != len(self.lines):
            raise LineConfigError("Counting line names must be unique.")
        if not isinstance(tolerance, (int, float)) or not math.isfinite(tolerance) or tolerance < 0:
            raise LineConfigError("tolerance must be a non-negative number.")
        if not isinstance(max_missing_frames, int) or max_missing_frames < 0:
            raise LineConfigError("max_missing_frames must be a non-negative integer.")
        self.tolerance = float(tolerance)
        self.max_missing_frames = max_missing_frames
        self.reset()

    def reset(self) -> None:
        """Clear all counts and track state (call at the start of each video)."""
        self.frame_index = 0
        self._states: dict[tuple[str, int], _TrackState] = {}
        self._counted: set[tuple[str, int, str]] = set()
        # line -> direction -> class_name -> count
        self._counts: dict[str, dict[str, dict[str, int]]] = {
            l.name: {d: {} for d in DIRECTIONS} for l in self.lines
        }

    @property
    def active_tracks(self) -> int:
        return len({tid for _, tid in self._states})

    def update(self, vehicles: Iterable[TrackedVehicle]) -> list[CrossingEvent]:
        """Process one frame of tracked vehicles; returns crossings counted this frame."""
        events: list[CrossingEvent] = []
        for v in vehicles:
            p = ground_point(v)
            for line in self.lines:
                ev = self._observe(line, v, p)
                if ev:
                    events.append(ev)
        self._prune()
        self.frame_index += 1
        return events

    def _observe(self, line: CountingLine, v: TrackedVehicle, p: Point) -> CrossingEvent | None:
        key = (line.name, v.track_id)
        d = line.signed_distance(p)
        state = self._states.get(key)
        if abs(d) <= self.tolerance:  # inside dead-band: ambiguous, just keep it alive
            if state:
                state.last_seen = self.frame_index
            return None
        side = 1 if d > 0 else -1
        if state is None:
            self._states[key] = _TrackState(p, side, self.frame_index)
            return None

        event = None
        if side != state.side and self._path_hits_segment(line, state.anchor, p):
            direction = FORWARD if side > 0 else REVERSE
            ckey = (line.name, v.track_id, direction)
            if ckey not in self._counted:
                self._counted.add(ckey)
                by_class = self._counts[line.name][direction]
                by_class[v.class_name] = by_class.get(v.class_name, 0) + 1
                event = CrossingEvent(line.name, v.track_id, v.class_id, v.class_name, direction, self.frame_index)
        state.anchor, state.side, state.last_seen = p, side, self.frame_index
        return event

    @staticmethod
    def _path_hits_segment(line: CountingLine, p0: Point, p1: Point) -> bool:
        d0, d1 = line.signed_distance(p0), line.signed_distance(p1)
        if d0 == d1:
            return False
        r = d0 / (d0 - d1)
        x, y = p0[0] + r * (p1[0] - p0[0]), p0[1] + r * (p1[1] - p0[1])
        (ax, ay), (bx, by) = line.start, line.end
        u = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / (line.length**2)
        return 0.0 <= u <= 1.0

    def _prune(self) -> None:
        """Drop previous positions of tracks unseen for too long (counted IDs are kept)."""
        cutoff = self.frame_index - self.max_missing_frames
        stale = [k for k, s in self._states.items() if s.last_seen < cutoff]
        for k in stale:
            del self._states[k]

    def summary(self) -> dict[str, Any]:
        """JSON-serialisable counts per line plus overall totals."""
        lines: dict[str, Any] = {}
        total_by_class: dict[str, int] = {}
        for l in self.lines:
            c = self._counts[l.name]
            by_class: dict[str, int] = {}
            for d in DIRECTIONS:
                for name, n in c[d].items():
                    by_class[name] = by_class.get(name, 0) + n
                    total_by_class[name] = total_by_class.get(name, 0) + n
            lines[l.name] = {
                "line": {"start": list(l.start), "end": list(l.end)},
                "total": sum(by_class.values()),
                FORWARD: sum(c[FORWARD].values()),
                REVERSE: sum(c[REVERSE].values()),
                "by_class": dict(sorted(by_class.items())),
                "by_direction_and_class": {d: dict(sorted(c[d].items())) for d in DIRECTIONS},
            }
        return {
            "frames_processed": self.frame_index,
            "total": sum(total_by_class.values()),
            "by_class": dict(sorted(total_by_class.items())),
            "lines": lines,
        }
