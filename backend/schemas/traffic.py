"""Shared, JSON-serialisable result types for the traffic analytics engine.

Density levels are derived from vehicle COUNTS. Occupancy values are an image-plane
bounding-box coverage estimate, not measured road occupancy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DensityLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

    @property
    def rank(self) -> int:
        return list(DensityLevel).index(self)


class CongestionLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"

    @property
    def rank(self) -> int:
        return list(CongestionLevel).index(self)


class Trend(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


DENSITY_BASIS = "vehicle_count"
OCCUPANCY_BASIS = "image_plane_bbox_coverage_estimate"
CONGESTION_BASIS_ESTIMATE = "model_estimate_from_vehicle_count_and_bbox_coverage"
CONGESTION_BASIS_SPEED = "calibrated_speed_with_count_and_bbox_coverage"


@dataclass(frozen=True)
class RegionDensity:
    region: str
    vehicle_count: int
    by_class: dict[str, int]
    level: DensityLevel  # count-based
    occupancy_estimate: float | None  # 0..1 image-plane bbox coverage of the region
    vehicles_per_100m: float | None  # only when the region has a user-supplied road_length_m
    density_basis: str = DENSITY_BASIS
    occupancy_basis: str = OCCUPANCY_BASIS

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["level"] = self.level.value
        return d


@dataclass(frozen=True)
class RegionCongestion:
    region: str
    level: CongestionLevel
    smoothed_vehicle_count: float
    smoothed_occupancy_estimate: float | None
    speed_kmh: float | None  # only when calibrated speed was supplied by the caller
    signals: dict[str, str]  # per-signal level that fed the decision
    basis: str
    is_estimate: bool  # True when no calibrated speed was available

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["level"] = self.level.value
        return d


@dataclass
class FrameStats:
    frame_index: int
    time_s: float
    vehicle_count: int
    track_ids: list[int]
    crossings: list[dict[str, Any]] = field(default_factory=list)
    densities: list[RegionDensity] = field(default_factory=list)
    congestion: list[RegionCongestion] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_index": self.frame_index,
            "time_s": round(self.time_s, 3),
            "vehicle_count": self.vehicle_count,
            "track_ids": list(self.track_ids),
            "crossings": list(self.crossings),
            "densities": [d.to_dict() for d in self.densities],
            "congestion": [c.to_dict() for c in self.congestion],
        }


@dataclass
class WindowSummary:
    window_index: int
    start_s: float
    end_s: float
    frames: int
    detections: int
    unique_vehicles: int
    mean_vehicles_per_frame: float
    crossings_by_direction: dict[str, int]
    crossings_by_class: dict[str, int]
    mean_region_vehicle_count: dict[str, float]
    peak_density_level: dict[str, str]
    congestion_level: dict[str, str]  # level at the last frame of the window

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

@dataclass
class TrafficAnalyticsResult:
    fps: float
    frames: int
    duration_s: float
    total_detections: int
    unique_vehicles: int
    unique_vehicles_by_class: dict[str, int]
    crossings: dict[str, Any] | None
    density: dict[str, Any] | None
    congestion: dict[str, Any] | None
    traffic_trend: str
    frame_stats: dict[str, Any]
    windows: list[dict[str, Any]]
    window_seconds: float
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# Pydantic v2 Request / Response Schemas for Incidents, Routing & Simulation
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class CoordinatesSchema(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0, description="Latitude in degrees")
    lon: float = Field(..., ge=-180.0, le=180.0, description="Longitude in degrees")


class IncidentCreateRequest(BaseModel):
    category: str = Field(..., min_length=1, description="Incident category (e.g. accident, waterlogging)")
    title: str = Field(..., min_length=1, description="Short descriptive title")
    description: str = Field(default="", description="Detailed description")
    affected_roads: list[str] = Field(default_factory=list, description="Affected road segment IDs")
    region: str | None = Field(default=None, description="Optional region identifier")
    state_code: str | None = Field(default=None, description="Optional Indian state/UT code (e.g. KA, MH, DL)")
    district_id: str | None = Field(default=None, description="Optional district ID (e.g. KA-BLR)")
    city_id: str | None = Field(default=None, description="Optional city ID (e.g. IN-BLR)")
    coordinates: CoordinatesSchema | None = Field(default=None, description="Geographic coordinates")
    auto_match_road: bool = Field(default=True, description="Automatically match coordinates to nearest road segment when affected_roads is empty")
    travel_bearing_deg: float | None = Field(default=None, ge=0.0, le=360.0, description="Optional travel direction bearing in degrees (0=N, 90=E)")
    severity: str | None = Field(default=None, description="Optional explicit severity (LOW, MODERATE, HIGH, CRITICAL)")
    severity_reason: str | None = Field(default=None, description="Optional explanation for explicit severity")
    source: str = Field(default="manual_report", description="auto_cv, manual_report, or operator")
    status: str | None = Field(default=None, description="Optional initial status override")
    evidence: dict[str, Any] = Field(default_factory=dict, description="Structured evidence dictionary")
    is_synthetic: bool = Field(default=False, description="Whether this incident is synthetic demonstration data")


class IncidentUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    severity: str | None = None
    severity_reason: str | None = None
    status: str | None = None
    affected_roads: list[str] | None = None
    region: str | None = None
    state_code: str | None = None
    district_id: str | None = None
    city_id: str | None = None
    coordinates: CoordinatesSchema | None = None
    auto_match_road: bool = False
    travel_bearing_deg: float | None = None
    evidence: dict[str, Any] | None = None
    resolution_notes: str | None = None


class IncidentActionRequest(BaseModel):
    notes: str | None = Field(default=None, description="Confirmation, dismissal, or resolution notes")


class IncidentResponse(BaseModel):
    id: str
    category: str
    severity: str
    severity_reason: str
    status: str
    source: str
    title: str
    description: str
    affected_roads: list[str]
    region: str | None
    state_code: str | None = None
    district_id: str | None = None
    city_id: str | None = None
    coordinates: CoordinatesSchema | None
    matched_road_distance_km: float | None = None
    evidence: dict[str, Any]
    is_hypothetical: bool
    is_synthetic: bool
    is_active_for_routing: bool
    created_at: str
    updated_at: str
    confirmed_at: str | None
    dismissed_at: str | None
    resolved_at: str | None
    resolution_notes: str | None


class RoutingWeightsSchema(BaseModel):
    congestion_weight: float = Field(default=1.0, ge=0.0, description="Lambda weight for congestion penalty T(e)")
    incident_weight: float = Field(default=1.5, ge=0.0, description="Mu weight for incident penalty I(e)")


class RouteCalculateRequest(BaseModel):
    origin_node: str | None = Field(default=None, description="Origin intersection node ID")
    destination_node: str | None = Field(default=None, description="Destination intersection node ID")
    origin_coordinates: CoordinatesSchema | None = Field(default=None, description="Origin coordinates (resolved to nearest node)")
    destination_coordinates: CoordinatesSchema | None = Field(default=None, description="Destination coordinates (resolved to nearest node)")
    objective: str = Field(default="incident_aware", description="shortest_distance, congestion_aware, or incident_aware")
    weights: RoutingWeightsSchema | None = Field(default=None, description="Custom routing weights")
    max_alternatives: int = Field(default=3, ge=1, le=10, description="Maximum number of alternative routes")
    bbox: str | None = Field(default=None, description="Optional regional bounding box 'min_lon,min_lat,max_lon,max_lat'")
    use_regional_extract: bool = Field(default=False, description="Extract regional subgraph around endpoints before routing")


class RouteCandidateSchema(BaseModel):
    route_id: str
    rank: int
    objective: str
    nodes: list[str]
    node_names: list[str]
    road_segments: list[str]
    road_names: list[str]
    regions: list[str]
    total_distance_km: float
    congestion_penalty_cost: float
    incident_penalty_cost: float
    total_modelled_cost: float
    affected_roads: list[str]
    closed_road_warnings: list[str]
    incident_warnings: list[dict[str, Any]]
    recommendation_reason: str
    cost_basis: str


class RouteCalculationResponse(BaseModel):
    origin_node: str
    destination_node: str
    objective: str
    weights: dict[str, float]
    recommended_route: RouteCandidateSchema
    shortest_distance_baseline: RouteCandidateSchema | None
    alternatives: list[RouteCandidateSchema]
    avoided_closed_roads: list[str]
    avoided_incident_roads: list[str]
    incidents_affecting_shortest_path: list[dict[str, Any]]
    explanation: str
    comparison: dict[str, Any]
    notes: list[str]


class RoadClosureSimulationRequest(BaseModel):
    closed_roads: list[str] = Field(..., min_length=1, description="Road segment IDs to hypothetically close")
    origin_node: str = Field(..., min_length=1)
    destination_node: str = Field(..., min_length=1)
    scenario_name: str = Field(default="Road Closure Simulation")
    closure_reason: str = Field(default="Simulated road closure")
    objective: str = Field(default="incident_aware")
    weights: RoutingWeightsSchema | None = None
    max_alternatives: int = Field(default=3, ge=1, le=10)


class HypotheticalIncidentSimulationRequest(BaseModel):
    category: str = Field(..., min_length=1, description="accident, vehicle_breakdown, road_obstruction, construction_work, waterlogging")
    affected_roads: list[str] = Field(..., min_length=1, description="Road segment IDs affected by hypothetical incident")
    origin_node: str = Field(..., min_length=1)
    destination_node: str = Field(..., min_length=1)
    scenario_name: str | None = None
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    road_blocked: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)
    objective: str = Field(default="incident_aware")
    weights: RoutingWeightsSchema | None = None
    max_alternatives: int = Field(default=3, ge=1, le=10)


class RoadCongestionUpdateItem(BaseModel):
    road_id: str = Field(..., min_length=1)
    congestion_level: str | None = Field(default=None, description="LOW, MODERATE, HIGH, or SEVERE")
    congestion_penalty: float | None = Field(default=None, ge=0.0, description="Normalized penalty >= 0.0")


class CongestionSimulationRequest(BaseModel):
    congestion_updates: list[RoadCongestionUpdateItem] = Field(..., min_length=1)
    origin_node: str = Field(..., min_length=1)
    destination_node: str = Field(..., min_length=1)
    scenario_name: str = Field(default="Congestion Surge Simulation")
    description: str = Field(default="Hypothetical congestion adjustment on selected road segments.")
    objective: str = Field(default="incident_aware")
    weights: RoutingWeightsSchema | None = None
    max_alternatives: int = Field(default=3, ge=1, le=10)


class ScenarioComparisonItem(BaseModel):
    scenario_name: str = Field(..., min_length=1)
    description: str = Field(default="")
    closed_roads: list[str] = Field(default_factory=list)
    closure_reason: str | None = None
    hypothetical_incidents: list[dict[str, Any]] = Field(default_factory=list)
    congestion_updates: list[RoadCongestionUpdateItem] = Field(default_factory=list)


class ScenarioComparisonRequest(BaseModel):
    origin_node: str = Field(..., min_length=1)
    destination_node: str = Field(..., min_length=1)
    scenarios: list[ScenarioComparisonItem] = Field(..., min_length=1)
    objective: str = Field(default="incident_aware")
    weights: RoutingWeightsSchema | None = None
    max_alternatives: int = Field(default=3, ge=1, le=10)


class SimulationResponse(BaseModel):
    simulation_id: str
    scenario_type: str
    scenario_name: str
    description: str
    is_hypothetical: bool
    is_synthetic: bool
    origin_node: str
    destination_node: str
    baseline_route: dict[str, Any] | None
    simulated_route: dict[str, Any] | None
    alternative_routes: list[dict[str, Any]]
    route_changed: bool
    route_reachable: bool
    cost_difference: float | None
    distance_difference_km: float | None
    affected_road_segments: list[str]
    affected_regions: list[str]
    inaccessible_roads: list[str]
    inaccessible_nodes: list[str]
    nearby_incidents: list[dict[str, Any]]
    hypothetical_incidents: list[dict[str, Any]]
    congestion_differences: list[dict[str, Any]]
    incident_warnings: list[dict[str, Any]]
    parameters: dict[str, Any]
    created_at: str
    notes: list[str]

