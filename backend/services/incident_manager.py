"""Incident Intelligence Engine for UrbanFlow AI.

Supports:
1. Configurable incident categories (accident, vehicle_breakdown, road_obstruction,
   road_closure, waterlogging, construction_work, unusual_congestion, stationary_vehicle).
2. Deterministic candidate detection from computer-vision & traffic analytics outputs
   (stationary vehicles, sudden regional density spikes, sudden congestion jumps,
   unusual traffic-flow changes, significant movement anomalies).
   Never claims a stationary vehicle is automatically an accident.
3. Explicit status & source distinction:
   - candidate (auto-detected)
   - reported (manually reported)
   - confirmed
   - dismissed (false positive)
   - resolved
4. Deterministic, configurable severity classification (LOW, MODERATE, HIGH, CRITICAL)
   storing the exact reasoning.
5. Full lifecycle management (create, update, confirm, dismiss, resolve, reopen,
   severity/location/affected-road updates, deduplication).
"""

from __future__ import annotations

import copy
import math
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

from backend.schemas.traffic import CongestionLevel, FrameStats
from backend.services.road_network import (
    GeoPoint,
    InvalidCoordinatesError,
    RoadNetwork,
    RoadSegmentNotFoundError,
    haversine_km,
)
from backend.services.tracker import TrackedVehicle
from backend.services.vehicle_counter import ground_point


class IncidentError(ValueError):
    """Base error for incident intelligence operations."""


class IncidentNotFoundError(IncidentError):
    """Raised when an incident ID does not exist."""


class InvalidIncidentTransitionError(IncidentError):
    """Raised when an invalid status transition is attempted."""


class IncidentCategory(str, Enum):
    ACCIDENT = "accident"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"
    ROAD_OBSTRUCTION = "road_obstruction"
    ROAD_CLOSURE = "road_closure"
    WATERLOGGING = "waterlogging"
    CONSTRUCTION_WORK = "construction_work"
    UNUSUAL_CONGESTION = "unusual_congestion"
    STATIONARY_VEHICLE = "stationary_vehicle"


DEFAULT_INCIDENT_CATEGORIES: tuple[str, ...] = tuple(c.value for c in IncidentCategory)


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return list(IncidentSeverity).index(self)


class IncidentStatus(str, Enum):
    CANDIDATE = "candidate"  # Automatically detected candidate
    REPORTED = "reported"  # Manually reported incident (unconfirmed)
    CONFIRMED = "confirmed"  # Confirmed active incident
    DISMISSED = "dismissed"  # Dismissed false positive
    RESOLVED = "resolved"  # Resolved incident


class IncidentSource(str, Enum):
    AUTO_CV = "auto_cv"  # Automatically detected candidate from CV/analytics
    MANUAL_REPORT = "manual_report"  # Manually reported by operator/citizen
    OPERATOR = "operator"  # Created directly as confirmed by traffic control
    HYPOTHETICAL = "hypothetical"  # Isolated simulation-only incident


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SeverityRuleConfig:
    """Configurable deterministic rules for severity classification and routing penalties."""

    # Base severity per incident category
    category_base_severity: dict[str, IncidentSeverity] = field(
        default_factory=lambda: {
            IncidentCategory.ACCIDENT.value: IncidentSeverity.HIGH,
            IncidentCategory.ROAD_CLOSURE.value: IncidentSeverity.CRITICAL,
            IncidentCategory.WATERLOGGING.value: IncidentSeverity.HIGH,
            IncidentCategory.ROAD_OBSTRUCTION.value: IncidentSeverity.MODERATE,
            IncidentCategory.CONSTRUCTION_WORK.value: IncidentSeverity.MODERATE,
            IncidentCategory.VEHICLE_BREAKDOWN.value: IncidentSeverity.MODERATE,
            IncidentCategory.UNUSUAL_CONGESTION.value: IncidentSeverity.MODERATE,
            IncidentCategory.STATIONARY_VEHICLE.value: IncidentSeverity.LOW,
        }
    )
    stationary_high_seconds: float = 30.0
    stationary_moderate_seconds: float = 12.0
    density_spike_high_delta: int = 10
    density_spike_critical_delta: int = 16
    heavy_vehicle_classes: set[str] = field(default_factory=lambda: {"bus", "truck", "tractor"})
    # Normalized routing penalty I(e) per severity rank
    severity_routing_penalty: dict[str, float] = field(
        default_factory=lambda: {
            IncidentSeverity.LOW.value: 0.25,
            IncidentSeverity.MODERATE.value: 0.60,
            IncidentSeverity.HIGH.value: 1.20,
            IncidentSeverity.CRITICAL.value: 2.50,
        }
    )
    # Candidate incidents have a discounted routing penalty unless confirmed
    candidate_penalty_factor: float = 0.5


@dataclass
class CandidateDetectionConfig:
    """Configurable thresholds for automatic CV/analytics incident candidate detection."""

    stationary_px_threshold: float = 8.0  # Max ground-point drift in image pixels
    stationary_min_duration_s: float = 5.0  # Minimum duration before flagging stationary candidate
    stationary_min_frames: int = 5
    density_spike_min_delta: int = 6  # Sudden jump in regional vehicle count
    density_spike_ratio: float = 2.0  # Or ratio vs rolling baseline
    congestion_jump_min_ranks: int = 2  # e.g. LOW -> HIGH or MODERATE -> SEVERE
    flow_drop_ratio: float = 0.25  # Flow drops below 25% of previous window while density is HIGH/VERY_HIGH
    dedup_cooldown_s: float = 60.0  # Minimum seconds before re-emitting identical candidate


@dataclass
class Incident:
    id: str
    category: str
    severity: IncidentSeverity
    severity_reason: str
    status: IncidentStatus
    source: IncidentSource
    title: str
    description: str
    affected_roads: list[str] = field(default_factory=list)
    region: str | None = None
    state_code: str | None = None
    district_id: str | None = None
    city_id: str | None = None
    coordinates: GeoPoint | None = None
    matched_road_distance_km: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    is_hypothetical: bool = False
    is_synthetic: bool = False
    dedup_key: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    confirmed_at: str | None = None
    dismissed_at: str | None = None
    resolved_at: str | None = None
    resolution_notes: str | None = None

    @property
    def is_active_for_routing(self) -> bool:
        """Dismissed and resolved incidents do not penalize routes."""
        return self.status in {
            IncidentStatus.CANDIDATE,
            IncidentStatus.REPORTED,
            IncidentStatus.CONFIRMED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity.value,
            "severity_reason": self.severity_reason,
            "status": self.status.value,
            "source": self.source.value,
            "title": self.title,
            "description": self.description,
            "affected_roads": list(self.affected_roads),
            "region": self.region,
            "state_code": self.state_code,
            "district_id": self.district_id,
            "city_id": self.city_id,
            "coordinates": self.coordinates.to_dict() if self.coordinates else None,
            "matched_road_distance_km": self.matched_road_distance_km,
            "evidence": copy.deepcopy(self.evidence),
            "is_hypothetical": self.is_hypothetical,
            "is_synthetic": self.is_synthetic,
            "is_active_for_routing": self.is_active_for_routing,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "confirmed_at": self.confirmed_at,
            "dismissed_at": self.dismissed_at,
            "resolved_at": self.resolved_at,
            "resolution_notes": self.resolution_notes,
        }


def classify_incident_severity(
    category: str,
    evidence: dict[str, Any] | None = None,
    affected_roads: list[str] | None = None,
    rules: SeverityRuleConfig | None = None,
) -> tuple[IncidentSeverity, str]:
    """Deterministically compute (IncidentSeverity, reason) from available evidence."""
    cfg = rules or SeverityRuleConfig()
    evidence = evidence or {}
    affected_roads = affected_roads or []

    base = cfg.category_base_severity.get(category, IncidentSeverity.MODERATE)
    rank = base.rank
    reasons: list[str] = [f"Base severity for '{category}' is {base.value}"]

    if evidence.get("road_blocked") is True or category == IncidentCategory.ROAD_CLOSURE.value:
        rank = max(rank, IncidentSeverity.CRITICAL.rank)
        reasons.append("full road blockage/closure reported")

    stationary_s = evidence.get("stationary_duration_s")
    if isinstance(stationary_s, (int, float)) and stationary_s >= cfg.stationary_high_seconds:
        rank = max(rank, IncidentSeverity.HIGH.rank)
        reasons.append(f"stationary duration {stationary_s:.1f}s >= {cfg.stationary_high_seconds:.1f}s")
    elif isinstance(stationary_s, (int, float)) and stationary_s >= cfg.stationary_moderate_seconds:
        rank = max(rank, IncidentSeverity.MODERATE.rank)
        reasons.append(f"stationary duration {stationary_s:.1f}s >= {cfg.stationary_moderate_seconds:.1f}s")

    vclass = str(evidence.get("vehicle_class", "")).lower()
    if vclass in cfg.heavy_vehicle_classes:
        rank = min(rank + 1, IncidentSeverity.CRITICAL.rank)
        reasons.append(f"involves heavy vehicle ({vclass})")

    delta = evidence.get("density_delta")
    if isinstance(delta, (int, float)):
        if delta >= cfg.density_spike_critical_delta:
            rank = max(rank, IncidentSeverity.CRITICAL.rank)
            reasons.append(f"regional vehicle count jumped by +{delta}")
        elif delta >= cfg.density_spike_high_delta:
            rank = max(rank, IncidentSeverity.HIGH.rank)
            reasons.append(f"regional vehicle count jumped by +{delta}")

    cong = str(evidence.get("congestion_level", "")).upper()
    if cong == "SEVERE":
        rank = max(rank, IncidentSeverity.HIGH.rank)
        reasons.append("associated with SEVERE regional congestion")

    if len(affected_roads) >= 3 and rank < IncidentSeverity.HIGH.rank:
        rank = IncidentSeverity.HIGH.rank
        reasons.append(f"affects {len(affected_roads)} road segments")

    final_sev = list(IncidentSeverity)[rank]
    return final_sev, "; ".join(reasons) + "."


@dataclass
class _StationaryTrackWatch:
    track_id: int
    class_name: str
    anchor_point: tuple[float, float]
    first_seen_s: float
    last_seen_s: float
    frames: int = 1
    region: str | None = None


class IncidentIntelligenceService:
    """Manages incident lifecycle, storage, deduplication, and automatic CV candidate detection."""

    def __init__(
        self,
        road_network: RoadNetwork | None = None,
        categories: Iterable[str] = DEFAULT_INCIDENT_CATEGORIES,
        severity_rules: SeverityRuleConfig | None = None,
        candidate_config: CandidateDetectionConfig | None = None,
        spatial_db: Any = None,
    ) -> None:
        self._lock = threading.RLock()
        self.road_network = road_network
        self.spatial_db = spatial_db
        self.allowed_categories: set[str] = {c.lower().strip() for c in categories}
        if not self.allowed_categories:
            raise IncidentError("At least one incident category must be configured.")
        self.severity_rules = severity_rules or SeverityRuleConfig()
        self.candidate_config = candidate_config or CandidateDetectionConfig()

        self._incidents: dict[str, Incident] = {}
        # Candidate detector state
        self._stationary_watches: dict[int, _StationaryTrackWatch] = {}
        self._region_prev_counts: dict[str, int] = {}
        self._region_prev_congestion: dict[str, CongestionLevel] = {}
        self._dedup_last_time_s: dict[str, float] = {}

    def clone_active_incidents(self) -> list[Incident]:
        """Return deep copies of all stored incidents (used for isolated simulation)."""
        with self._lock:
            return [copy.deepcopy(inc) for inc in self._incidents.values()]

    def reset_candidate_detector(self) -> None:
        with self._lock:
            self._stationary_watches.clear()
            self._region_prev_counts.clear()
            self._region_prev_congestion.clear()
            self._dedup_last_time_s.clear()

    def _validate_category(self, category: str) -> str:
        cat = category.lower().strip()
        if cat not in self.allowed_categories:
            raise IncidentError(
                f"Unsupported incident category '{category}'. Allowed: {sorted(self.allowed_categories)}"
            )
        return cat

    def _validate_roads(self, affected_roads: Iterable[str] | None) -> list[str]:
        if not affected_roads:
            return []
        roads = list(dict.fromkeys(str(r).strip() for r in affected_roads if str(r).strip()))
        if self.road_network is not None:
            for r in roads:
                if not self.road_network.has_segment(r):
                    raise RoadSegmentNotFoundError(f"Unknown affected road segment '{r}'")
        return roads

    def _parse_coordinates(self, coordinates: GeoPoint | dict[str, float] | tuple[float, float] | None) -> GeoPoint | None:
        if coordinates is None:
            return None
        if isinstance(coordinates, GeoPoint):
            return coordinates
        if isinstance(coordinates, dict):
            if "lat" not in coordinates or "lon" not in coordinates:
                raise InvalidCoordinatesError("Coordinates dict must contain 'lat' and 'lon'.")
            return GeoPoint(coordinates["lat"], coordinates["lon"])
        if isinstance(coordinates, (tuple, list)) and len(coordinates) == 2:
            return GeoPoint(coordinates[0], coordinates[1])
        raise InvalidCoordinatesError(f"Unsupported coordinates format: {coordinates!r}")

    def _find_duplicate_active(
        self,
        category: str,
        affected_roads: list[str],
        region: str | None,
        coordinates: GeoPoint | None,
        dedup_key: str | None,
    ) -> Incident | None:
        for inc in self._incidents.values():
            if inc.status in {IncidentStatus.DISMISSED, IncidentStatus.RESOLVED}:
                continue
            if dedup_key and inc.dedup_key == dedup_key:
                return inc
            if inc.category != category:
                continue
            if affected_roads and inc.affected_roads and set(affected_roads) == set(inc.affected_roads):
                return inc
            if coordinates and inc.coordinates and haversine_km(coordinates, inc.coordinates) <= 0.05:
                return inc
            if not affected_roads and not coordinates and region and inc.region == region and dedup_key is not None:
                return inc
        return None

    def create_incident(
        self,
        category: str,
        title: str,
        description: str = "",
        affected_roads: Iterable[str] | None = None,
        region: str | None = None,
        state_code: str | None = None,
        district_id: str | None = None,
        city_id: str | None = None,
        coordinates: GeoPoint | dict[str, float] | tuple[float, float] | None = None,
        severity: IncidentSeverity | str | None = None,
        severity_reason: str | None = None,
        source: IncidentSource | str = IncidentSource.MANUAL_REPORT,
        status: IncidentStatus | str | None = None,
        evidence: dict[str, Any] | None = None,
        dedup_key: str | None = None,
        is_synthetic: bool = False,
        allow_duplicate: bool = False,
        auto_match_road: bool = True,
        travel_bearing_deg: float | None = None,
        max_match_distance_km: float = 0.35,
    ) -> Incident:
        """Create a new incident or update & return an existing active duplicate."""
        with self._lock:
            cat = self._validate_category(category)
            if not isinstance(title, str) or not title.strip():
                raise IncidentError("Incident title must be a non-empty string.")
            roads = self._validate_roads(affected_roads)
            coords = self._parse_coordinates(coordinates)
            src = IncidentSource(source) if not isinstance(source, IncidentSource) else source

            matched_dist_km: float | None = None
            if not roads and coords is not None and auto_match_road and self.road_network is not None:
                try:
                    matched_seg, dist_km = self.road_network.match_nearest_road_segment(
                        coords,
                        max_distance_km=max_match_distance_km,
                        travel_bearing_deg=travel_bearing_deg,
                    )
                    if matched_seg is not None:
                        roads = [matched_seg.id]
                        matched_dist_km = dist_km
                except RoadSegmentNotFoundError:
                    pass

            if roads and self.road_network is not None:
                first_seg = self.road_network.get_segment(roads[0])
                if not region:
                    region = first_seg.region
                if not state_code:
                    state_code = first_seg.state_code
                if not district_id:
                    district_id = first_seg.district_id
                if not city_id:
                    city_id = first_seg.city_id

            if coords is not None and self.spatial_db is not None and not (state_code and district_id and city_id):
                admin = self.spatial_db.resolve_administrative_area(coords.lat, coords.lon)
                state_code = state_code or admin.get("state_code")
                district_id = district_id or admin.get("district_id")
                city_id = city_id or admin.get("city_id")

            if not allow_duplicate:
                dup = self._find_duplicate_active(cat, roads, region, coords, dedup_key)
                if dup is not None:
                    dup.updated_at = _utc_now_iso()
                    if evidence:
                        dup.evidence.update(evidence)
                        if severity is None:
                            new_sev, new_reason = classify_incident_severity(
                                dup.category, dup.evidence, dup.affected_roads, self.severity_rules
                            )
                            if new_sev.rank > dup.severity.rank:
                                dup.severity = new_sev
                                dup.severity_reason = new_reason
                    return copy.deepcopy(dup)

            ev = copy.deepcopy(evidence) if evidence else {}
            if matched_dist_km is not None:
                ev.setdefault("matched_road_distance_km", matched_dist_km)
            if severity is not None:
                sev = IncidentSeverity(severity.upper() if isinstance(severity, str) else severity)
                reason = severity_reason or f"Explicitly set to {sev.value} on creation."
            else:
                sev, reason = classify_incident_severity(cat, ev, roads, self.severity_rules)
                if severity_reason:
                    reason = f"{severity_reason} ({reason})"

            if status is not None:
                st = IncidentStatus(status.lower() if isinstance(status, str) else status)
            elif src == IncidentSource.AUTO_CV:
                st = IncidentStatus.CANDIDATE
            elif src == IncidentSource.OPERATOR:
                st = IncidentStatus.CONFIRMED
            else:
                st = IncidentStatus.REPORTED

            now = _utc_now_iso()
            inc = Incident(
                id=f"inc_{uuid.uuid4().hex[:10]}",
                category=cat,
                severity=sev,
                severity_reason=reason,
                status=st,
                source=src,
                title=title.strip(),
                description=description.strip(),
                affected_roads=roads,
                region=region,
                state_code=state_code,
                district_id=district_id,
                city_id=city_id,
                coordinates=coords,
                matched_road_distance_km=matched_dist_km,
                evidence=ev,
                is_hypothetical=False,
                is_synthetic=is_synthetic,
                dedup_key=dedup_key,
                created_at=now,
                updated_at=now,
                confirmed_at=now if st == IncidentStatus.CONFIRMED else None,
            )
            self._incidents[inc.id] = inc
            return copy.deepcopy(inc)

    def get_incident(self, incident_id: str) -> Incident:
        with self._lock:
            if incident_id not in self._incidents:
                raise IncidentNotFoundError(f"Incident not found: '{incident_id}'")
            return copy.deepcopy(self._incidents[incident_id])

    def list_incidents(
        self,
        status: str | None = None,
        category: str | None = None,
        severity: str | None = None,
        region: str | None = None,
        state_code: str | None = None,
        district_id: str | None = None,
        city_id: str | None = None,
        road_id: str | None = None,
        active_only: bool = False,
    ) -> list[Incident]:
        with self._lock:
            items = list(self._incidents.values())
            if status:
                st = IncidentStatus(status.lower())
                items = [i for i in items if i.status == st]
            if category:
                cat = category.lower().strip()
                items = [i for i in items if i.category == cat]
            if severity:
                sev = IncidentSeverity(severity.upper())
                items = [i for i in items if i.severity == sev]
            if region:
                items = [i for i in items if i.region == region]
            if state_code:
                sc = state_code.upper().strip()
                items = [i for i in items if (i.state_code or "").upper() == sc]
            if district_id:
                did = district_id.upper().strip()
                items = [i for i in items if (i.district_id or "").upper() == did]
            if city_id:
                cid = city_id.upper().strip()
                items = [i for i in items if (i.city_id or "").upper() == cid]
            if road_id:
                items = [i for i in items if road_id in i.affected_roads]
            if active_only:
                items = [i for i in items if i.is_active_for_routing]
            return [copy.deepcopy(i) for i in items]

    def update_incident(
        self,
        incident_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        category: str | None = None,
        severity: IncidentSeverity | str | None = None,
        severity_reason: str | None = None,
        status: IncidentStatus | str | None = None,
        affected_roads: Iterable[str] | None = None,
        region: str | None = None,
        state_code: str | None = None,
        district_id: str | None = None,
        city_id: str | None = None,
        coordinates: GeoPoint | dict[str, float] | tuple[float, float] | None = None,
        evidence: dict[str, Any] | None = None,
        resolution_notes: str | None = None,
        auto_match_road: bool = False,
        travel_bearing_deg: float | None = None,
    ) -> Incident:
        with self._lock:
            if incident_id not in self._incidents:
                raise IncidentNotFoundError(f"Incident not found: '{incident_id}'")
            inc = self._incidents[incident_id]
            if title is not None:
                if not title.strip():
                    raise IncidentError("Incident title cannot be empty.")
                inc.title = title.strip()
            if description is not None:
                inc.description = description.strip()
            if category is not None:
                inc.category = self._validate_category(category)
            if affected_roads is not None:
                inc.affected_roads = self._validate_roads(affected_roads)
            if region is not None:
                inc.region = region
            if state_code is not None:
                inc.state_code = state_code
            if district_id is not None:
                inc.district_id = district_id
            if city_id is not None:
                inc.city_id = city_id
            if coordinates is not None:
                inc.coordinates = self._parse_coordinates(coordinates)
                if auto_match_road and not inc.affected_roads and self.road_network is not None:
                    matched_seg, dist_km = self.road_network.match_nearest_road_segment(
                        inc.coordinates,
                        travel_bearing_deg=travel_bearing_deg,
                    )
                    if matched_seg is not None:
                        inc.affected_roads = [matched_seg.id]
                        inc.matched_road_distance_km = dist_km
            if evidence is not None:
                inc.evidence.update(evidence)
            if severity is not None:
                inc.severity = IncidentSeverity(severity.upper() if isinstance(severity, str) else severity)
                inc.severity_reason = severity_reason or f"Manually updated severity to {inc.severity.value}."
            elif severity_reason is not None:
                inc.severity_reason = severity_reason
            if resolution_notes is not None:
                inc.resolution_notes = resolution_notes
            if status is not None:
                target = IncidentStatus(status.lower() if isinstance(status, str) else status)
                self._apply_status_transition(inc, target, notes=resolution_notes)
            inc.updated_at = _utc_now_iso()
            return copy.deepcopy(inc)

    def _apply_status_transition(
        self,
        inc: Incident,
        target: IncidentStatus,
        notes: str | None = None,
    ) -> None:
        now = _utc_now_iso()
        if target == IncidentStatus.CONFIRMED:
            if inc.status == IncidentStatus.DISMISSED:
                raise InvalidIncidentTransitionError("Cannot confirm a dismissed false-positive incident without reopening it first.")
            inc.status = IncidentStatus.CONFIRMED
            inc.confirmed_at = now
        elif target == IncidentStatus.DISMISSED:
            if inc.status == IncidentStatus.RESOLVED:
                raise InvalidIncidentTransitionError("Cannot dismiss an already resolved incident.")
            inc.status = IncidentStatus.DISMISSED
            inc.dismissed_at = now
            if notes:
                inc.resolution_notes = notes
        elif target == IncidentStatus.RESOLVED:
            if inc.status == IncidentStatus.DISMISSED:
                raise InvalidIncidentTransitionError("Cannot resolve a dismissed false-positive incident.")
            inc.status = IncidentStatus.RESOLVED
            inc.resolved_at = now
            if notes:
                inc.resolution_notes = notes
        elif target in {IncidentStatus.REPORTED, IncidentStatus.CANDIDATE}:
            # Reopening a resolved or dismissed incident
            inc.status = target
            inc.resolved_at = None
            inc.dismissed_at = None
        else:
            raise InvalidIncidentTransitionError(f"Unsupported target status: {target}")
        inc.updated_at = now

    def confirm_incident(self, incident_id: str, notes: str | None = None) -> Incident:
        with self._lock:
            if incident_id not in self._incidents:
                raise IncidentNotFoundError(f"Incident not found: '{incident_id}'")
            inc = self._incidents[incident_id]
            self._apply_status_transition(inc, IncidentStatus.CONFIRMED, notes=notes)
            return copy.deepcopy(inc)

    def dismiss_incident(self, incident_id: str, reason: str | None = None) -> Incident:
        with self._lock:
            if incident_id not in self._incidents:
                raise IncidentNotFoundError(f"Incident not found: '{incident_id}'")
            inc = self._incidents[incident_id]
            self._apply_status_transition(inc, IncidentStatus.DISMISSED, notes=reason)
            return copy.deepcopy(inc)

    def resolve_incident(self, incident_id: str, resolution_notes: str | None = None) -> Incident:
        with self._lock:
            if incident_id not in self._incidents:
                raise IncidentNotFoundError(f"Incident not found: '{incident_id}'")
            inc = self._incidents[incident_id]
            self._apply_status_transition(inc, IncidentStatus.RESOLVED, notes=resolution_notes)
            return copy.deepcopy(inc)

    def reopen_incident(self, incident_id: str, as_confirmed: bool = True, notes: str | None = None) -> Incident:
        with self._lock:
            if incident_id not in self._incidents:
                raise IncidentNotFoundError(f"Incident not found: '{incident_id}'")
            inc = self._incidents[incident_id]
            if inc.status not in {IncidentStatus.RESOLVED, IncidentStatus.DISMISSED}:
                raise InvalidIncidentTransitionError(f"Incident '{incident_id}' is already open (status={inc.status.value}).")
            inc.resolved_at = None
            inc.dismissed_at = None
            inc.status = IncidentStatus.CONFIRMED if as_confirmed else IncidentStatus.REPORTED
            if as_confirmed:
                inc.confirmed_at = _utc_now_iso()
            if notes:
                inc.resolution_notes = notes
            inc.updated_at = _utc_now_iso()
            return copy.deepcopy(inc)

    def evaluate_frame_candidates(
        self,
        frame_stats: FrameStats,
        vehicles: Iterable[TrackedVehicle],
        region_to_roads: dict[str, list[str]] | None = None,
    ) -> list[Incident]:
        """Inspect a frame's tracked vehicles and regional density/congestion to emit
        deterministic incident candidates (status=CANDIDATE, source=AUTO_CV).

        Never claims a stationary vehicle is automatically an accident.
        """
        with self._lock:
            cfg = self.candidate_config
            t = frame_stats.time_s
            region_to_roads = region_to_roads or {}
            created_or_updated: list[Incident] = []

            # 1. Stationary vehicle detection
            seen_ids: set[int] = set()
            for v in vehicles:
                seen_ids.add(v.track_id)
                gp = ground_point(v)
                watch = self._stationary_watches.get(v.track_id)
                if watch is None:
                    self._stationary_watches[v.track_id] = _StationaryTrackWatch(
                        track_id=v.track_id,
                        class_name=v.class_name,
                        anchor_point=gp,
                        first_seen_s=t,
                        last_seen_s=t,
                        frames=1,
                    )
                else:
                    drift = math.hypot(gp[0] - watch.anchor_point[0], gp[1] - watch.anchor_point[1])
                    if drift <= cfg.stationary_px_threshold:
                        watch.last_seen_s = t
                        watch.frames += 1
                        duration = watch.last_seen_s - watch.first_seen_s
                        if duration >= cfg.stationary_min_duration_s and watch.frames >= cfg.stationary_min_frames:
                            dkey = f"stationary_track_{v.track_id}"
                            last_emit = self._dedup_last_time_s.get(dkey, -1e9)
                            if t - last_emit >= cfg.dedup_cooldown_s:
                                self._dedup_last_time_s[dkey] = t
                                region = watch.region or (frame_stats.densities[0].region if frame_stats.densities else None)
                                roads = self._resolve_region_roads(region, region_to_roads)
                                inc = self.create_incident(
                                    category=IncidentCategory.STATIONARY_VEHICLE.value,
                                    title=f"Stationary {v.class_name} candidate (Track #{v.track_id})",
                                    description=(
                                        f"Tracked {v.class_name} (ID {v.track_id}) remained within "
                                        f"{cfg.stationary_px_threshold:.1f}px for {duration:.1f}s. "
                                        "Automatically detected candidate only; not confirmed as an accident or breakdown."
                                    ),
                                    affected_roads=roads,
                                    region=region,
                                    source=IncidentSource.AUTO_CV,
                                    status=IncidentStatus.CANDIDATE,
                                    evidence={
                                        "signal": "stationary_tracked_vehicle",
                                        "track_id": v.track_id,
                                        "vehicle_class": v.class_name,
                                        "stationary_duration_s": round(duration, 2),
                                        "drift_px": round(drift, 2),
                                        "frame_index": frame_stats.frame_index,
                                        "note": "Stationary vehicle candidate; requires operator confirmation.",
                                    },
                                    dedup_key=dkey,
                                )
                                created_or_updated.append(inc)
                    else:
                        # Vehicle moved significantly: reset its stationary anchor
                        watch.anchor_point = gp
                        watch.first_seen_s = t
                        watch.last_seen_s = t
                        watch.frames = 1

            # Prune tracks not seen for > 5 seconds
            stale = [tid for tid, w in self._stationary_watches.items() if tid not in seen_ids and (t - w.last_seen_s) > 5.0]
            for tid in stale:
                del self._stationary_watches[tid]

            # 2. Sudden regional density spike
            for d in frame_stats.densities:
                prev_count = self._region_prev_counts.get(d.region)
                self._region_prev_counts[d.region] = d.vehicle_count
                if prev_count is not None:
                    delta = d.vehicle_count - prev_count
                    if delta >= cfg.density_spike_min_delta:
                        dkey = f"density_spike_{d.region}"
                        if t - self._dedup_last_time_s.get(dkey, -1e9) >= cfg.dedup_cooldown_s:
                            self._dedup_last_time_s[dkey] = t
                            roads = self._resolve_region_roads(d.region, region_to_roads)
                            inc = self.create_incident(
                                category=IncidentCategory.UNUSUAL_CONGESTION.value,
                                title=f"Sudden density surge in region '{d.region}'",
                                description=(
                                    f"Vehicle count in '{d.region}' jumped from {prev_count} to {d.vehicle_count} "
                                    f"(+{delta}) at t={t:.1f}s."
                                ),
                                affected_roads=roads,
                                region=d.region,
                                source=IncidentSource.AUTO_CV,
                                status=IncidentStatus.CANDIDATE,
                                evidence={
                                    "signal": "sudden_density_increase",
                                    "previous_vehicle_count": prev_count,
                                    "current_vehicle_count": d.vehicle_count,
                                    "density_delta": delta,
                                    "density_level": d.level.value,
                                    "frame_index": frame_stats.frame_index,
                                },
                                dedup_key=dkey,
                            )
                            created_or_updated.append(inc)

            # 3. Sudden congestion-level increase
            for c in frame_stats.congestion:
                prev_lvl = self._region_prev_congestion.get(c.region)
                self._region_prev_congestion[c.region] = c.level
                if prev_lvl is not None and (c.level.rank - prev_lvl.rank) >= cfg.congestion_jump_min_ranks:
                    dkey = f"congestion_jump_{c.region}"
                    if t - self._dedup_last_time_s.get(dkey, -1e9) >= cfg.dedup_cooldown_s:
                        self._dedup_last_time_s[dkey] = t
                        roads = self._resolve_region_roads(c.region, region_to_roads)
                        inc = self.create_incident(
                            category=IncidentCategory.UNUSUAL_CONGESTION.value,
                            title=f"Rapid congestion escalation in '{c.region}' ({prev_lvl.value} -> {c.level.value})",
                            description=(
                                f"Regional congestion estimate in '{c.region}' jumped from {prev_lvl.value} "
                                f"to {c.level.value} at t={t:.1f}s."
                            ),
                            affected_roads=roads,
                            region=c.region,
                            source=IncidentSource.AUTO_CV,
                            status=IncidentStatus.CANDIDATE,
                            evidence={
                                "signal": "sudden_congestion_increase",
                                "previous_level": prev_lvl.value,
                                "congestion_level": c.level.value,
                                "smoothed_vehicle_count": c.smoothed_vehicle_count,
                                "is_estimate": c.is_estimate,
                                "frame_index": frame_stats.frame_index,
                            },
                            dedup_key=dkey,
                        )
                        created_or_updated.append(inc)

            return created_or_updated

    def evaluate_flow_anomaly(
        self,
        region: str,
        previous_window_crossings: int,
        current_window_crossings: int,
        current_congestion_level: str,
        affected_roads: list[str] | None = None,
    ) -> Incident | None:
        """Detect unusual traffic-flow drops (e.g. crossings collapse while congestion is HIGH/SEVERE),
        which indicates a potential downstream road obstruction."""
        with self._lock:
            cfg = self.candidate_config
            lvl = current_congestion_level.upper().strip()
            if previous_window_crossings <= 0 or lvl not in {"HIGH", "SEVERE"}:
                return None
            ratio = current_window_crossings / previous_window_crossings
            if ratio > cfg.flow_drop_ratio:
                return None
            roads = self._validate_roads(affected_roads)
            if not roads and self.road_network is not None:
                roads = [s.id for s in self.road_network.segments_in_region(region)]
            return self.create_incident(
                category=IncidentCategory.ROAD_OBSTRUCTION.value,
                title=f"Traffic flow drop candidate in '{region}'",
                description=(
                    f"Line crossings dropped from {previous_window_crossings} to {current_window_crossings} "
                    f"(ratio {ratio:.2f}) while regional congestion is {lvl}. Potential obstruction candidate."
                ),
                affected_roads=roads,
                region=region,
                source=IncidentSource.AUTO_CV,
                status=IncidentStatus.CANDIDATE,
                evidence={
                    "signal": "unusual_traffic_flow_drop",
                    "previous_window_crossings": previous_window_crossings,
                    "current_window_crossings": current_window_crossings,
                    "flow_ratio": round(ratio, 3),
                    "congestion_level": lvl,
                },
                dedup_key=f"flow_anomaly_{region}",
            )

    def _resolve_region_roads(self, region: str | None, region_to_roads: dict[str, list[str]]) -> list[str]:
        if not region:
            return []
        if region in region_to_roads:
            return self._validate_roads(region_to_roads[region])
        if self.road_network is not None:
            return [s.id for s in self.road_network.segments_in_region(region)]
        return []
