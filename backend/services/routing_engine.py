"""Intelligent Smart Routing Engine for UrbanFlow AI.

Implements an incident-aware, congestion-aware routing engine over the NetworkX
road network using the configurable weighted edge-cost model:

    C(e) = D(e) * (1 + lambda * T(e) + mu * I(e))

Where:
- D(e): road-segment distance in km (strictly positive).
- T(e): normalized congestion penalty (>= 0).
- I(e): incident penalty on road segment e (>= 0).
- lambda: configurable congestion weight (>= 0).
- mu: configurable incident weight (>= 0).

Closed roads (either segment.closed == True or an active confirmed ROAD_CLOSURE
incident on that road) are excluded from route traversal.

Never presents modelled route cost C(e) as actual travel time or travel-time savings.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

import networkx as nx

from backend.services.incident_manager import (
    Incident,
    IncidentCategory,
    IncidentIntelligenceService,
    IncidentStatus,
    SeverityRuleConfig,
)
from backend.services.road_network import (
    RESTRICTED_ACCESS_VALUES,
    BoundingBox,
    CoverageUnavailableError,
    GeoPoint,
    NodeNotFoundError,
    RoadNetwork,
    RoadNetworkError,
    RoadSegment,
)


class RoutingError(RoadNetworkError):
    """Base error for routing calculations."""


class NoRouteFoundError(RoutingError):
    """Raised when no valid path connects origin and destination."""


class RoutingObjective(str, Enum):
    SHORTEST_DISTANCE = "shortest_distance"  # lambda = 0, mu = 0 (still avoids closed roads)
    CONGESTION_AWARE = "congestion_aware"  # lambda > 0, mu = 0
    INCIDENT_AWARE = "incident_aware"  # lambda > 0, mu > 0 (default smart routing)


@dataclass(frozen=True)
class RoutingWeights:
    """Configurable weights for C(e) = D(e) * (1 + lambda * T(e) + mu * I(e))."""

    congestion_weight: float = 1.0  # lambda
    incident_weight: float = 1.5  # mu

    def __post_init__(self) -> None:
        if (
            not isinstance(self.congestion_weight, (int, float))
            or isinstance(self.congestion_weight, bool)
            or not math.isfinite(self.congestion_weight)
            or self.congestion_weight < 0
        ):
            raise RoutingError("congestion_weight (lambda) must be a non-negative finite number.")
        if (
            not isinstance(self.incident_weight, (int, float))
            or isinstance(self.incident_weight, bool)
            or not math.isfinite(self.incident_weight)
            or self.incident_weight < 0
        ):
            raise RoutingError("incident_weight (mu) must be a non-negative finite number.")
        object.__setattr__(self, "congestion_weight", float(self.congestion_weight))
        object.__setattr__(self, "incident_weight", float(self.incident_weight))

    def for_objective(self, objective: RoutingObjective | str) -> "RoutingWeights":
        obj = RoutingObjective(objective) if not isinstance(objective, RoutingObjective) else objective
        if obj == RoutingObjective.SHORTEST_DISTANCE:
            return RoutingWeights(congestion_weight=0.0, incident_weight=0.0)
        if obj == RoutingObjective.CONGESTION_AWARE:
            return RoutingWeights(congestion_weight=self.congestion_weight, incident_weight=0.0)
        return self


@dataclass
class RouteCandidate:
    route_id: str
    rank: int
    objective: str
    nodes: list[str]
    node_names: list[str]
    road_segments: list[str]
    road_names: list[str]
    regions: list[str]
    total_distance_km: float
    congestion_penalty_cost: float  # sum of D(e) * lambda * T(e)
    incident_penalty_cost: float  # sum of D(e) * mu * I(e)
    total_modelled_cost: float  # sum of C(e)
    affected_roads: list[str] = field(default_factory=list)
    closed_road_warnings: list[str] = field(default_factory=list)
    incident_warnings: list[dict[str, Any]] = field(default_factory=list)
    recommendation_reason: str = ""
    cost_basis: str = "modelled_weighted_distance_cost_not_travel_time"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RouteCalculationResult:
    origin_node: str
    destination_node: str
    objective: str
    weights: dict[str, float]
    recommended_route: RouteCandidate
    shortest_distance_baseline: RouteCandidate | None
    alternatives: list[RouteCandidate]
    avoided_closed_roads: list[str]
    avoided_incident_roads: list[str]
    incidents_affecting_shortest_path: list[dict[str, Any]]
    explanation: str
    comparison: dict[str, Any]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_node": self.origin_node,
            "destination_node": self.destination_node,
            "objective": self.objective,
            "weights": dict(self.weights),
            "recommended_route": self.recommended_route.to_dict(),
            "shortest_distance_baseline": (
                self.shortest_distance_baseline.to_dict() if self.shortest_distance_baseline else None
            ),
            "alternatives": [r.to_dict() for r in self.alternatives],
            "avoided_closed_roads": list(self.avoided_closed_roads),
            "avoided_incident_roads": list(self.avoided_incident_roads),
            "incidents_affecting_shortest_path": copy.deepcopy(self.incidents_affecting_shortest_path),
            "explanation": self.explanation,
            "comparison": copy.deepcopy(self.comparison),
            "notes": list(self.notes),
        }


class SmartRoutingEngine:
    """Computes incident-aware, congestion-aware, and shortest-distance routes."""

    def __init__(
        self,
        road_network: RoadNetwork,
        incident_service: IncidentIntelligenceService | None = None,
        default_weights: RoutingWeights | None = None,
        severity_rules: SeverityRuleConfig | None = None,
    ) -> None:
        self.road_network = road_network
        self.incident_service = incident_service
        self.default_weights = default_weights or RoutingWeights()
        self.severity_rules = severity_rules or SeverityRuleConfig()

    def resolve_endpoint(
        self,
        node_id: str | None = None,
        coordinates: GeoPoint | dict[str, float] | tuple[float, float] | None = None,
        network: RoadNetwork | None = None,
    ) -> str:
        net = network or self.road_network
        if node_id is not None:
            nid = str(node_id).strip()
            if not net.has_node(nid):
                raise NodeNotFoundError(f"Unknown road node '{nid}'")
            return nid
        if coordinates is not None:
            if isinstance(coordinates, GeoPoint):
                pt = coordinates
            elif isinstance(coordinates, dict) and "lat" in coordinates and "lon" in coordinates:
                pt = GeoPoint(coordinates["lat"], coordinates["lon"])
            elif isinstance(coordinates, (tuple, list)) and len(coordinates) == 2:
                pt = GeoPoint(coordinates[0], coordinates[1])
            else:
                raise RoutingError(f"Invalid endpoint coordinates: {coordinates!r}")
            return net.nearest_node(pt).id
        raise RoutingError("Provide either node_id or coordinates for route endpoint.")

    def _active_incidents_by_road(
        self,
        incidents_override: Iterable[Incident] | None = None,
    ) -> tuple[dict[str, list[Incident]], set[str]]:
        if incidents_override is not None:
            incidents = [i for i in incidents_override if i.is_active_for_routing]
        elif self.incident_service is not None:
            incidents = self.incident_service.list_incidents(active_only=True)
        else:
            incidents = []

        by_road: dict[str, list[Incident]] = {}
        incident_closed_roads: set[str] = set()
        for inc in incidents:
            for road_id in inc.affected_roads:
                by_road.setdefault(road_id, []).append(inc)
                if (
                    inc.category == IncidentCategory.ROAD_CLOSURE.value
                    and inc.status in {IncidentStatus.CONFIRMED, IncidentStatus.REPORTED}
                ) or inc.evidence.get("road_blocked") is True:
                    incident_closed_roads.add(road_id)
        return by_road, incident_closed_roads

    def edge_incident_penalty(self, road_incidents: list[Incident]) -> float:
        """Compute normalized incident penalty I(e) >= 0 from active incidents on road e."""
        if not road_incidents:
            return 0.0
        total = 0.0
        for inc in road_incidents:
            base = self.severity_rules.severity_routing_penalty.get(inc.severity.value, 0.5)
            if inc.status == IncidentStatus.CANDIDATE:
                base *= self.severity_rules.candidate_penalty_factor
            total += base
        return round(total, 4)

    def segment_cost_components(
        self,
        seg: RoadSegment,
        road_incidents: list[Incident],
        weights: RoutingWeights,
    ) -> tuple[float, float, float, float]:
        """Return (D(e), D(e)*lambda*T(e), D(e)*mu*I(e), C(e)). Guarantees C(e) > 0."""
        d = seg.distance_km
        t_pen = max(0.0, seg.congestion_penalty)
        i_pen = max(0.0, self.edge_incident_penalty(road_incidents))
        cong_cost = d * weights.congestion_weight * t_pen
        inc_cost = d * weights.incident_weight * i_pen
        total_cost = d * (1.0 + weights.congestion_weight * t_pen + weights.incident_weight * i_pen)
        if not math.isfinite(total_cost) or total_cost <= 0:
            raise RoutingError(f"Invalid computed edge cost {total_cost} on road '{seg.id}'")
        return d, cong_cost, inc_cost, total_cost

    def _build_traversal_graph(
        self,
        net: RoadNetwork,
        by_road: dict[str, list[Incident]],
        incident_closed_roads: set[str],
        weights: RoutingWeights,
        include_closed: bool = False,
    ) -> tuple[nx.DiGraph, list[str]]:
        """Build a light NetworkX view with edge weights C(e), excluding closed roads."""
        g = nx.DiGraph()
        for nid, node in net.nodes.items():
            g.add_node(nid, name=node.name)

        closed_roads: list[str] = []
        for seg_id, seg in net.segments.items():
            is_closed = seg.closed or (seg_id in incident_closed_roads) or (seg.access in RESTRICTED_ACCESS_VALUES)
            if is_closed:
                closed_roads.append(seg_id)
                if not include_closed:
                    continue
            road_incs = by_road.get(seg_id, [])
            d, cong_c, inc_c, total_c = self.segment_cost_components(seg, road_incs, weights)
            edge_attrs = {
                "segment_id": seg_id,
                "distance_km": d,
                "congestion_cost": cong_c,
                "incident_cost": inc_c,
                "weight": total_c,
                "closed": is_closed,
            }
            if seg.oneway == "reverse":
                g.add_edge(seg.target, seg.source, **edge_attrs)
            elif seg.oneway == "yes" or not seg.bidirectional:
                g.add_edge(seg.source, seg.target, **edge_attrs)
            else:
                g.add_edge(seg.source, seg.target, **edge_attrs)
                g.add_edge(seg.target, seg.source, **edge_attrs)
        return g, sorted(set(closed_roads))

    def _materialize_candidate(
        self,
        route_id: str,
        rank: int,
        objective: str,
        node_path: list[str],
        net: RoadNetwork,
        by_road: dict[str, list[Incident]],
        incident_closed_roads: set[str],
        weights: RoutingWeights,
    ) -> RouteCandidate:
        nodes_map = net.nodes
        seg_ids: list[str] = []
        seg_names: list[str] = []
        regions: list[str] = []
        total_d = 0.0
        total_cong = 0.0
        total_inc = 0.0
        total_cost = 0.0
        affected_roads: list[str] = []
        closed_warnings: list[str] = []
        inc_warnings: list[dict[str, Any]] = []
        seen_inc_ids: set[str] = set()

        for u, v in zip(node_path[:-1], node_path[1:]):
            seg = net.segment_between(u, v)
            seg_ids.append(seg.id)
            seg_names.append(seg.name)
            if seg.region not in regions:
                regions.append(seg.region)
            r_incs = by_road.get(seg.id, [])
            d, cc, ic, tc = self.segment_cost_components(seg, r_incs, weights)
            total_d += d
            total_cong += cc
            total_inc += ic
            total_cost += tc

            if seg.closed or seg.id in incident_closed_roads:
                reason = seg.closure_reason or "Active road closure incident"
                closed_warnings.append(f"Road '{seg.name}' ({seg.id}) is closed: {reason}")
            if r_incs or seg.congestion_level in {"HIGH", "SEVERE"}:
                affected_roads.append(seg.id)
            for inc in r_incs:
                if inc.id not in seen_inc_ids:
                    seen_inc_ids.add(inc.id)
                    inc_warnings.append(
                        {
                            "incident_id": inc.id,
                            "road_id": seg.id,
                            "road_name": seg.name,
                            "category": inc.category,
                            "severity": inc.severity.value,
                            "status": inc.status.value,
                            "title": inc.title,
                            "is_hypothetical": inc.is_hypothetical,
                        }
                    )

        return RouteCandidate(
            route_id=route_id,
            rank=rank,
            objective=objective,
            nodes=list(node_path),
            node_names=[nodes_map[n].name for n in node_path],
            road_segments=seg_ids,
            road_names=seg_names,
            regions=regions,
            total_distance_km=round(total_d, 3),
            congestion_penalty_cost=round(total_cong, 3),
            incident_penalty_cost=round(total_inc, 3),
            total_modelled_cost=round(total_cost, 3),
            affected_roads=affected_roads,
            closed_road_warnings=closed_warnings,
            incident_warnings=inc_warnings,
        )

    def calculate_route(
        self,
        origin_node: str | None = None,
        destination_node: str | None = None,
        *,
        origin_coordinates: GeoPoint | dict[str, float] | tuple[float, float] | None = None,
        destination_coordinates: GeoPoint | dict[str, float] | tuple[float, float] | None = None,
        objective: RoutingObjective | str = RoutingObjective.INCIDENT_AWARE,
        weights: RoutingWeights | None = None,
        max_alternatives: int = 3,
        bbox: BoundingBox | str | None = None,
        use_regional_extract: bool = False,
        network_override: RoadNetwork | None = None,
        incidents_override: Iterable[Incident] | None = None,
    ) -> RouteCalculationResult:
        """Calculate the optimal route and ranked alternatives between origin and destination."""
        if not isinstance(max_alternatives, int) or max_alternatives < 1:
            raise RoutingError("max_alternatives must be a positive integer.")

        base_net = network_override or self.road_network
        if bbox is not None:
            parsed_bbox = BoundingBox.from_string(bbox) if isinstance(bbox, str) else bbox
            net = base_net.extract_regional_network(parsed_bbox)
            if not net.nodes or not net.segments:
                raise CoverageUnavailableError(
                    "No road network coverage available in the requested bounding box."
                )
        elif use_regional_extract:
            orig_id = self.resolve_endpoint(origin_node, origin_coordinates, base_net)
            dest_id = self.resolve_endpoint(destination_node, destination_coordinates, base_net)
            u_n = base_net.get_node(orig_id)
            v_n = base_net.get_node(dest_id)
            pad = 0.08  # ~8-9 km padding around origin/destination envelope
            auto_bbox = BoundingBox(
                min_lon=min(u_n.lon, v_n.lon) - pad,
                min_lat=min(u_n.lat, v_n.lat) - pad,
                max_lon=max(u_n.lon, v_n.lon) + pad,
                max_lat=max(u_n.lat, v_n.lat) + pad,
            )
            net = base_net.extract_regional_network(auto_bbox)
        else:
            net = base_net

        orig = self.resolve_endpoint(origin_node, origin_coordinates, net)
        dest = self.resolve_endpoint(destination_node, destination_coordinates, net)
        obj = RoutingObjective(objective) if not isinstance(objective, RoutingObjective) else objective
        base_weights = weights or self.default_weights
        active_weights = base_weights.for_objective(obj)

        by_road, incident_closed_roads = self._active_incidents_by_road(incidents_override)
        g, all_closed_roads = self._build_traversal_graph(net, by_road, incident_closed_roads, active_weights)

        if orig == dest:
            trivial = RouteCandidate(
                route_id="route_1",
                rank=1,
                objective=obj.value,
                nodes=[orig],
                node_names=[net.get_node(orig).name],
                road_segments=[],
                road_names=[],
                regions=[net.get_node(orig).region],
                total_distance_km=0.0,
                congestion_penalty_cost=0.0,
                incident_penalty_cost=0.0,
                total_modelled_cost=0.0,
                recommendation_reason="Origin and destination are the same node.",
            )
            return RouteCalculationResult(
                origin_node=orig,
                destination_node=dest,
                objective=obj.value,
                weights={"lambda_congestion": active_weights.congestion_weight, "mu_incident": active_weights.incident_weight},
                recommended_route=trivial,
                shortest_distance_baseline=trivial,
                alternatives=[trivial],
                avoided_closed_roads=[],
                avoided_incident_roads=[],
                incidents_affecting_shortest_path=[],
                explanation="Origin and destination are identical.",
                comparison={"cost_delta_vs_shortest": 0.0, "distance_delta_km_vs_shortest": 0.0},
                notes=["Route cost is a dimensionless weighted distance model, not calibrated travel time."],
            )

        if not nx.has_path(g, orig, dest):
            raise NoRouteFoundError(
                f"No open route exists between '{orig}' and '{dest}' "
                f"(closed roads: {all_closed_roads or 'none'})."
            )

        # Generate k-shortest simple paths ordered by the active objective's edge weight C(e)
        raw_paths: list[list[str]] = []
        for path in nx.shortest_simple_paths(g, orig, dest, weight="weight"):
            raw_paths.append(path)
            if len(raw_paths) >= max_alternatives:
                break

        candidates: list[RouteCandidate] = []
        for idx, path in enumerate(raw_paths, start=1):
            cand = self._materialize_candidate(
                route_id=f"route_{idx}",
                rank=idx,
                objective=obj.value,
                node_path=path,
                net=net,
                by_road=by_road,
                incident_closed_roads=incident_closed_roads,
                weights=active_weights,
            )
            candidates.append(cand)

        recommended = candidates[0]

        # Compare against the pure shortest-distance path (even across closed roads if needed for explanation)
        g_all, _ = self._build_traversal_graph(
            net, by_road, incident_closed_roads, RoutingWeights(0.0, 0.0), include_closed=True
        )
        shortest_open_g, _ = self._build_traversal_graph(
            net, by_road, incident_closed_roads, RoutingWeights(0.0, 0.0), include_closed=False
        )
        shortest_baseline: RouteCandidate | None = None
        unobstructed_physical_path: list[str] | None = None
        if nx.has_path(g_all, orig, dest):
            unobstructed_physical_path = nx.shortest_path(g_all, orig, dest, weight="distance_km")
        if nx.has_path(shortest_open_g, orig, dest):
            sp_nodes = nx.shortest_path(shortest_open_g, orig, dest, weight="distance_km")
            shortest_baseline = self._materialize_candidate(
                route_id="shortest_distance_baseline",
                rank=1,
                objective=RoutingObjective.SHORTEST_DISTANCE.value,
                node_path=sp_nodes,
                net=net,
                by_road=by_road,
                incident_closed_roads=incident_closed_roads,
                weights=active_weights,
            )

        avoided_closed: list[str] = []
        avoided_incident_roads: list[str] = []
        incidents_on_shortest: list[dict[str, Any]] = []

        ref_nodes = unobstructed_physical_path or (shortest_baseline.nodes if shortest_baseline else [])
        if ref_nodes and len(ref_nodes) >= 2:
            ref_segs = [net.segment_between(u, v).id for u, v in zip(ref_nodes[:-1], ref_nodes[1:])]
            for sid in ref_segs:
                if sid in all_closed_roads and sid not in recommended.road_segments:
                    avoided_closed.append(sid)
                if sid in by_road and sid not in recommended.road_segments:
                    avoided_incident_roads.append(sid)
                for inc in by_road.get(sid, []):
                    incidents_on_shortest.append(
                        {
                            "incident_id": inc.id,
                            "road_id": sid,
                            "category": inc.category,
                            "severity": inc.severity.value,
                            "status": inc.status.value,
                            "title": inc.title,
                        }
                    )

        explanation, rec_reason = self._build_explanation(
            recommended=recommended,
            shortest_baseline=shortest_baseline,
            alternatives=candidates,
            avoided_closed=avoided_closed,
            avoided_incident_roads=avoided_incident_roads,
            objective=obj,
        )
        recommended.recommendation_reason = rec_reason
        for alt in candidates[1:]:
            delta_c = round(alt.total_modelled_cost - recommended.total_modelled_cost, 3)
            delta_d = round(alt.total_distance_km - recommended.total_distance_km, 3)
            alt.recommendation_reason = (
                f"Alternative rank #{alt.rank}: +{delta_c} modelled cost "
                f"({delta_d:+.2f} km distance vs recommended route)."
            )

        comparison = {
            "candidate_count": len(candidates),
            "recommended_route_id": recommended.route_id,
            "recommended_distance_km": recommended.total_distance_km,
            "recommended_modelled_cost": recommended.total_modelled_cost,
            "shortest_open_distance_km": shortest_baseline.total_distance_km if shortest_baseline else None,
            "shortest_open_modelled_cost": shortest_baseline.total_modelled_cost if shortest_baseline else None,
            "distance_delta_km_vs_shortest_open": (
                round(recommended.total_distance_km - shortest_baseline.total_distance_km, 3)
                if shortest_baseline
                else 0.0
            ),
            "modelled_cost_reduction_vs_shortest_open": (
                round(shortest_baseline.total_modelled_cost - recommended.total_modelled_cost, 3)
                if shortest_baseline
                else 0.0
            ),
        }

        return RouteCalculationResult(
            origin_node=orig,
            destination_node=dest,
            objective=obj.value,
            weights={
                "lambda_congestion": active_weights.congestion_weight,
                "mu_incident": active_weights.incident_weight,
            },
            recommended_route=recommended,
            shortest_distance_baseline=shortest_baseline,
            alternatives=candidates,
            avoided_closed_roads=avoided_closed,
            avoided_incident_roads=avoided_incident_roads,
            incidents_affecting_shortest_path=incidents_on_shortest,
            explanation=explanation,
            comparison=comparison,
            notes=[
                "Cost C(e) = D(e) * (1 + lambda*T(e) + mu*I(e)) is a modelled routing cost, not calibrated travel time.",
                "Closed roads are strictly excluded from route candidates.",
            ],
        )

    @staticmethod
    def _build_explanation(
        recommended: RouteCandidate,
        shortest_baseline: RouteCandidate | None,
        alternatives: list[RouteCandidate],
        avoided_closed: list[str],
        avoided_incident_roads: list[str],
        objective: RoutingObjective,
    ) -> tuple[str, str]:
        parts: list[str] = [
            f"Selected '{recommended.route_id}' ({' -> '.join(recommended.node_names)}) "
            f"under objective '{objective.value}' with total distance {recommended.total_distance_km:.2f} km "
            f"and modelled cost {recommended.total_modelled_cost:.2f}."
        ]
        if avoided_closed:
            parts.append(f"Avoided closed road segment(s): {', '.join(avoided_closed)}.")
        if avoided_incident_roads:
            parts.append(f"Detoured around incident-affected road segment(s): {', '.join(avoided_incident_roads)}.")
        if shortest_baseline and shortest_baseline.road_segments != recommended.road_segments:
            saving = round(shortest_baseline.total_modelled_cost - recommended.total_modelled_cost, 2)
            extra_km = round(recommended.total_distance_km - shortest_baseline.total_distance_km, 2)
            parts.append(
                f"Compared with the shortest-distance path ({shortest_baseline.total_distance_km:.2f} km, "
                f"modelled cost {shortest_baseline.total_modelled_cost:.2f}), this route adds {extra_km:+.2f} km "
                f"to reduce modelled congestion/incident cost by {saving:.2f} (modelled cost units, not travel time)."
            )
        if len(alternatives) > 1:
            nxt = alternatives[1]
            parts.append(
                f"Next best alternative '{nxt.route_id}' has modelled cost {nxt.total_modelled_cost:.2f} "
                f"({nxt.total_distance_km:.2f} km)."
            )
        else:
            parts.append("No other simple open path exists in the network.")
        summary = " ".join(parts)
        return summary, parts[0]
