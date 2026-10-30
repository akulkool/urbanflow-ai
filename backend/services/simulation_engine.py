"""What-If Traffic Simulation Engine for UrbanFlow AI.

Executes hypothetical scenarios (road closures, hypothetical incidents, congestion
changes, and multi-scenario comparisons) against isolated copies of the road network
and incident state.

Guarantees:
- Never mutates the baseline road network or real incident records.
- Uses deterministic, reproducible scenario IDs derived from scenario inputs.
- Explicitly labels hypothetical incidents and modelled outcomes.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

import networkx as nx

from backend.services.incident_manager import (
    Incident,
    IncidentCategory,
    IncidentError,
    IncidentIntelligenceService,
    IncidentSeverity,
    IncidentSource,
    IncidentStatus,
    classify_incident_severity,
)
from backend.services.road_network import (
    RoadNetwork,
    RoadNetworkError,
    RoadSegmentNotFoundError,
)
from backend.services.routing_engine import (
    NoRouteFoundError,
    RouteCalculationResult,
    RoutingObjective,
    RoutingWeights,
    SmartRoutingEngine,
)


class SimulationError(ValueError):
    """Base error for simulation operations."""


class SimulationNotFoundError(SimulationError):
    """Raised when a simulation ID does not exist in the simulation store."""


class ScenarioType(str, Enum):
    ROAD_CLOSURE = "road_closure"
    HYPOTHETICAL_INCIDENT = "hypothetical_incident"
    CONGESTION_CHANGE = "congestion_change"
    COMBINED = "combined"


HYPOTHETICAL_INCIDENT_CATEGORIES: set[str] = {
    IncidentCategory.ACCIDENT.value,
    IncidentCategory.VEHICLE_BREAKDOWN.value,
    IncidentCategory.ROAD_OBSTRUCTION.value,
    IncidentCategory.CONSTRUCTION_WORK.value,
    IncidentCategory.WATERLOGGING.value,
    IncidentCategory.ROAD_CLOSURE.value,
    IncidentCategory.UNUSUAL_CONGESTION.value,
}


def _stable_scenario_id(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return f"sim_{prefix}_{digest}"


@dataclass
class SimulationResult:
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
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrafficSimulationEngine:
    """Isolated what-if simulation engine for road closures, incidents, and congestion."""

    def __init__(
        self,
        road_network: RoadNetwork,
        incident_service: IncidentIntelligenceService,
        routing_engine: SmartRoutingEngine,
    ) -> None:
        self._lock = threading.RLock()
        self.road_network = road_network
        self.incident_service = incident_service
        self.routing_engine = routing_engine
        self._simulations: dict[str, SimulationResult] = {}

    def get_simulation(self, simulation_id: str) -> SimulationResult:
        with self._lock:
            if simulation_id not in self._simulations:
                raise SimulationNotFoundError(f"Simulation not found: '{simulation_id}'")
            return copy.deepcopy(self._simulations[simulation_id])

    def list_simulations(self) -> list[SimulationResult]:
        with self._lock:
            return [copy.deepcopy(s) for s in self._simulations.values()]

    def _compute_inaccessible(
        self,
        base_net: RoadNetwork,
        sim_net: RoadNetwork,
        sim_incidents: list[Incident],
        weights: RoutingWeights,
    ) -> tuple[list[str], list[str]]:
        """Identify road segments and intersection nodes made completely unreachable."""
        by_road, closed_by_inc = self.routing_engine._active_incidents_by_road(sim_incidents)
        g_sim, closed_roads = self.routing_engine._build_traversal_graph(
            sim_net, by_road, closed_by_inc, weights, include_closed=False
        )
        inaccessible_nodes: list[str] = []
        for nid in sim_net.nodes:
            if g_sim.in_degree(nid) == 0 and g_sim.out_degree(nid) == 0:
                inaccessible_nodes.append(nid)
            elif not any(nx.has_path(g_sim, other, nid) for other in sim_net.nodes if other != nid):
                inaccessible_nodes.append(nid)
        return sorted(set(closed_roads)), sorted(set(inaccessible_nodes))

    def _run_isolated_scenario(
        self,
        *,
        scenario_type: ScenarioType,
        scenario_name: str,
        description: str,
        origin_node: str,
        destination_node: str,
        closed_roads: list[str] | None = None,
        closure_reason: str | None = None,
        hypothetical_incidents_spec: list[dict[str, Any]] | None = None,
        congestion_updates: list[dict[str, Any]] | None = None,
        objective: RoutingObjective | str = RoutingObjective.INCIDENT_AWARE,
        weights: RoutingWeights | None = None,
        max_alternatives: int = 3,
    ) -> SimulationResult:
        # Validate inputs before running
        orig = self.routing_engine.resolve_endpoint(origin_node)
        dest = self.routing_engine.resolve_endpoint(destination_node)
        obj = RoutingObjective(objective) if not isinstance(objective, RoutingObjective) else objective
        active_weights = (weights or self.routing_engine.default_weights).for_objective(obj)

        closed_roads = sorted(dict.fromkeys(closed_roads or []))
        for rid in closed_roads:
            if not self.road_network.has_segment(rid):
                raise RoadSegmentNotFoundError(f"Unknown road segment for closure: '{rid}'")

        congestion_updates = list(congestion_updates or [])
        for upd in congestion_updates:
            rid = upd.get("road_id")
            if not rid or not self.road_network.has_segment(rid):
                raise RoadSegmentNotFoundError(f"Unknown road segment for congestion simulation: '{rid}'")

        hyp_specs = list(hypothetical_incidents_spec or [])
        for spec in hyp_specs:
            cat = str(spec.get("category", "")).lower().strip()
            if cat not in HYPOTHETICAL_INCIDENT_CATEGORIES:
                raise SimulationError(
                    f"Unsupported hypothetical incident category '{cat}'. "
                    f"Supported: {sorted(HYPOTHETICAL_INCIDENT_CATEGORIES)}"
                )
            for rid in spec.get("affected_roads", []):
                if not self.road_network.has_segment(rid):
                    raise RoadSegmentNotFoundError(f"Unknown road segment in hypothetical incident: '{rid}'")

        # 1. Snapshot isolated copies of baseline network & active real incidents
        base_net = self.road_network.clone()
        sim_net = self.road_network.clone()
        real_incidents = self.incident_service.clone_active_incidents()
        sim_incidents = copy.deepcopy(real_incidents)

        # 2. Compute baseline route on untouched state
        baseline_calc: RouteCalculationResult | None = None
        try:
            baseline_calc = self.routing_engine.calculate_route(
                orig,
                dest,
                objective=obj,
                weights=active_weights,
                max_alternatives=max_alternatives,
                network_override=base_net,
                incidents_override=real_incidents,
            )
        except NoRouteFoundError:
            baseline_calc = None

        # 3. Apply hypothetical modifications ONLY to sim_net and sim_incidents
        affected_segments: set[str] = set()
        affected_regions: set[str] = set()
        congestion_diffs: list[dict[str, Any]] = []
        created_hyp_incidents: list[Incident] = []

        for rid in closed_roads:
            seg_before = sim_net.get_segment(rid)
            sim_net.set_road_closed(rid, True, reason=closure_reason or "Hypothetical simulated road closure")
            affected_segments.add(rid)
            affected_regions.add(seg_before.region)

        for upd in congestion_updates:
            rid = upd["road_id"]
            before = sim_net.get_segment(rid)
            after = sim_net.set_road_congestion(
                rid,
                congestion_level=upd.get("congestion_level"),
                congestion_penalty=upd.get("congestion_penalty"),
            )
            affected_segments.add(rid)
            affected_regions.add(after.region)
            congestion_diffs.append(
                {
                    "road_id": rid,
                    "road_name": after.name,
                    "region": after.region,
                    "before_level": before.congestion_level,
                    "after_level": after.congestion_level,
                    "before_penalty": round(before.congestion_penalty, 3),
                    "after_penalty": round(after.congestion_penalty, 3),
                    "penalty_delta": round(after.congestion_penalty - before.congestion_penalty, 3),
                }
            )

        for idx, spec in enumerate(hyp_specs, start=1):
            cat = str(spec["category"]).lower().strip()
            roads = list(dict.fromkeys(spec.get("affected_roads", [])))
            ev = copy.deepcopy(spec.get("evidence") or {})
            if spec.get("road_blocked") is True or cat == IncidentCategory.ROAD_CLOSURE.value:
                ev["road_blocked"] = True
            if spec.get("severity"):
                sev = IncidentSeverity(str(spec["severity"]).upper())
                reason = spec.get("severity_reason") or f"Hypothetical scenario severity set to {sev.value}."
            else:
                sev, reason = classify_incident_severity(cat, ev, roads, self.incident_service.severity_rules)
            reg = spec.get("region") or (sim_net.get_segment(roads[0]).region if roads else None)
            for rid in roads:
                affected_segments.add(rid)
                affected_regions.add(sim_net.get_segment(rid).region)
            if reg:
                affected_regions.add(reg)

            hyp_inc = Incident(
                id=f"hyp_inc_{idx}",
                category=cat,
                severity=sev,
                severity_reason=reason,
                status=IncidentStatus.CONFIRMED,
                source=IncidentSource.HYPOTHETICAL,
                title=spec.get("title") or f"Hypothetical {cat.replace('_', ' ')}",
                description=spec.get("description") or f"Isolated hypothetical {cat} scenario.",
                affected_roads=roads,
                region=reg,
                coordinates=None,
                evidence=ev,
                is_hypothetical=True,
                is_synthetic=True,
            )
            sim_incidents.append(hyp_inc)
            created_hyp_incidents.append(hyp_inc)

        # 4. Calculate simulated route on modified isolated copy
        sim_calc: RouteCalculationResult | None = None
        route_reachable = True
        try:
            sim_calc = self.routing_engine.calculate_route(
                orig,
                dest,
                objective=obj,
                weights=active_weights,
                max_alternatives=max_alternatives,
                network_override=sim_net,
                incidents_override=sim_incidents,
            )
        except NoRouteFoundError:
            route_reachable = False
            sim_calc = None

        inaccessible_roads, inaccessible_nodes = self._compute_inaccessible(
            base_net, sim_net, sim_incidents, active_weights
        )

        # Find real nearby incidents in affected regions or roads
        nearby_real: list[dict[str, Any]] = []
        for inc in real_incidents:
            if not inc.is_active_for_routing:
                continue
            if any(r in affected_segments for r in inc.affected_roads) or (inc.region in affected_regions):
                nearby_real.append(inc.to_dict())

        base_route_dict = baseline_calc.recommended_route.to_dict() if baseline_calc else None
        sim_route_dict = sim_calc.recommended_route.to_dict() if sim_calc else None
        alt_dicts = [r.to_dict() for r in sim_calc.alternatives] if sim_calc else []

        if base_route_dict and sim_route_dict:
            route_changed = base_route_dict["road_segments"] != sim_route_dict["road_segments"]
            cost_diff = round(sim_route_dict["total_modelled_cost"] - base_route_dict["total_modelled_cost"], 3)
            dist_diff = round(sim_route_dict["total_distance_km"] - base_route_dict["total_distance_km"], 3)
        elif base_route_dict and not sim_route_dict:
            route_changed = True
            cost_diff = None
            dist_diff = None
        else:
            route_changed = False
            cost_diff = None
            dist_diff = None

        params_payload = {
            "scenario_type": scenario_type.value,
            "scenario_name": scenario_name,
            "origin_node": orig,
            "destination_node": dest,
            "objective": obj.value,
            "weights": {
                "lambda_congestion": active_weights.congestion_weight,
                "mu_incident": active_weights.incident_weight,
            },
            "closed_roads": closed_roads,
            "closure_reason": closure_reason,
            "hypothetical_incidents": hyp_specs,
            "congestion_updates": sorted(congestion_updates, key=lambda x: x.get("road_id", "")),
        }
        sim_id = _stable_scenario_id(scenario_type.value, params_payload)

        warnings: list[dict[str, Any]] = []
        if sim_calc:
            warnings.extend(sim_calc.recommended_route.incident_warnings)
            for inc_w in sim_calc.incidents_affecting_shortest_path:
                if not any(w["incident_id"] == inc_w["incident_id"] for w in warnings):
                    warnings.append(inc_w)

        res = SimulationResult(
            simulation_id=sim_id,
            scenario_type=scenario_type.value,
            scenario_name=scenario_name,
            description=description,
            is_hypothetical=True,
            is_synthetic=True,
            origin_node=orig,
            destination_node=dest,
            baseline_route=base_route_dict,
            simulated_route=sim_route_dict,
            alternative_routes=alt_dicts,
            route_changed=route_changed,
            route_reachable=route_reachable,
            cost_difference=cost_diff,
            distance_difference_km=dist_diff,
            affected_road_segments=sorted(affected_segments),
            affected_regions=sorted(affected_regions),
            inaccessible_roads=inaccessible_roads,
            inaccessible_nodes=inaccessible_nodes,
            nearby_incidents=nearby_real,
            hypothetical_incidents=[h.to_dict() for h in created_hyp_incidents],
            congestion_differences=congestion_diffs,
            incident_warnings=warnings,
            parameters=params_payload,
            created_at=datetime.now(timezone.utc).isoformat(),
            notes=[
                "Hypothetical simulation executed on an isolated road graph copy; permanent road state and real incidents were not modified.",
                "All costs and differences are modelled weighted route costs, not calibrated travel time.",
            ],
        )
        with self._lock:
            self._simulations[sim_id] = copy.deepcopy(res)
        return res

    def simulate_road_closure(
        self,
        closed_roads: str | Iterable[str],
        origin_node: str,
        destination_node: str,
        *,
        scenario_name: str = "Road Closure Simulation",
        closure_reason: str = "Simulated road closure",
        objective: RoutingObjective | str = RoutingObjective.INCIDENT_AWARE,
        weights: RoutingWeights | None = None,
        max_alternatives: int = 3,
    ) -> SimulationResult:
        roads = [closed_roads] if isinstance(closed_roads, str) else list(closed_roads)
        if not roads:
            raise SimulationError("Specify at least one road segment ID to close.")
        return self._run_isolated_scenario(
            scenario_type=ScenarioType.ROAD_CLOSURE,
            scenario_name=scenario_name,
            description=f"Hypothetical closure of road segment(s): {', '.join(roads)}.",
            origin_node=origin_node,
            destination_node=destination_node,
            closed_roads=roads,
            closure_reason=closure_reason,
            objective=objective,
            weights=weights,
            max_alternatives=max_alternatives,
        )

    def simulate_hypothetical_incident(
        self,
        category: str,
        affected_roads: str | Iterable[str],
        origin_node: str,
        destination_node: str,
        *,
        scenario_name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        severity: str | None = None,
        road_blocked: bool = False,
        evidence: dict[str, Any] | None = None,
        objective: RoutingObjective | str = RoutingObjective.INCIDENT_AWARE,
        weights: RoutingWeights | None = None,
        max_alternatives: int = 3,
    ) -> SimulationResult:
        roads = [affected_roads] if isinstance(affected_roads, str) else list(affected_roads)
        if not roads:
            raise SimulationError("Specify at least one affected road segment for hypothetical incident.")
        cat = category.lower().strip()
        spec = {
            "category": cat,
            "affected_roads": roads,
            "title": title or f"Hypothetical {cat.replace('_', ' ')} on {', '.join(roads)}",
            "description": description or f"Simulated {cat.replace('_', ' ')} affecting {', '.join(roads)}.",
            "severity": severity,
            "road_blocked": road_blocked,
            "evidence": evidence or {},
        }
        return self._run_isolated_scenario(
            scenario_type=ScenarioType.HYPOTHETICAL_INCIDENT,
            scenario_name=scenario_name or f"Hypothetical {cat.replace('_', ' ').title()}",
            description=spec["description"],
            origin_node=origin_node,
            destination_node=destination_node,
            hypothetical_incidents_spec=[spec],
            objective=objective,
            weights=weights,
            max_alternatives=max_alternatives,
        )

    def simulate_congestion(
        self,
        congestion_updates: Iterable[dict[str, Any]],
        origin_node: str,
        destination_node: str,
        *,
        scenario_name: str = "Congestion Surge Simulation",
        description: str = "Hypothetical congestion adjustment on selected road segments.",
        objective: RoutingObjective | str = RoutingObjective.INCIDENT_AWARE,
        weights: RoutingWeights | None = None,
        max_alternatives: int = 3,
    ) -> SimulationResult:
        updates = list(congestion_updates)
        if not updates:
            raise SimulationError("Provide at least one road congestion update.")
        return self._run_isolated_scenario(
            scenario_type=ScenarioType.CONGESTION_CHANGE,
            scenario_name=scenario_name,
            description=description,
            origin_node=origin_node,
            destination_node=destination_node,
            congestion_updates=updates,
            objective=objective,
            weights=weights,
            max_alternatives=max_alternatives,
        )

    def compare_scenarios(
        self,
        origin_node: str,
        destination_node: str,
        scenarios: Iterable[dict[str, Any]],
        *,
        objective: RoutingObjective | str = RoutingObjective.INCIDENT_AWARE,
        weights: RoutingWeights | None = None,
        max_alternatives: int = 3,
    ) -> dict[str, Any]:
        """Execute or retrieve multiple scenarios against a common baseline and compare them."""
        scenario_list = list(scenarios)
        if not scenario_list:
            raise SimulationError("Provide at least one scenario to compare.")

        orig = self.routing_engine.resolve_endpoint(origin_node)
        dest = self.routing_engine.resolve_endpoint(destination_node)
        obj = RoutingObjective(objective) if not isinstance(objective, RoutingObjective) else objective
        active_weights = (weights or self.routing_engine.default_weights).for_objective(obj)

        base_calc = self.routing_engine.calculate_route(
            orig, dest, objective=obj, weights=active_weights, max_alternatives=max_alternatives
        )
        baseline_route = base_calc.recommended_route.to_dict()

        compared: list[dict[str, Any]] = []
        for idx, sc in enumerate(scenario_list, start=1):
            name = sc.get("scenario_name") or f"Scenario #{idx}"
            desc = sc.get("description") or f"Comparison scenario #{idx}"
            closed = sc.get("closed_roads") or []
            hyp_incs = sc.get("hypothetical_incidents") or []
            cong_upds = sc.get("congestion_updates") or []

            if closed and not hyp_incs and not cong_upds:
                stype = ScenarioType.ROAD_CLOSURE
            elif hyp_incs and not closed and not cong_upds:
                stype = ScenarioType.HYPOTHETICAL_INCIDENT
            elif cong_upds and not closed and not hyp_incs:
                stype = ScenarioType.CONGESTION_CHANGE
            else:
                stype = ScenarioType.COMBINED

            sim_res = self._run_isolated_scenario(
                scenario_type=stype,
                scenario_name=name,
                description=desc,
                origin_node=orig,
                destination_node=dest,
                closed_roads=closed,
                closure_reason=sc.get("closure_reason"),
                hypothetical_incidents_spec=hyp_incs,
                congestion_updates=cong_upds,
                objective=obj,
                weights=active_weights,
                max_alternatives=max_alternatives,
            )
            compared.append(
                {
                    "simulation_id": sim_res.simulation_id,
                    "scenario_name": sim_res.scenario_name,
                    "scenario_type": sim_res.scenario_type,
                    "description": sim_res.description,
                    "route_reachable": sim_res.route_reachable,
                    "route_changed": sim_res.route_changed,
                    "simulated_route": sim_res.simulated_route,
                    "cost_difference": sim_res.cost_difference,
                    "distance_difference_km": sim_res.distance_difference_km,
                    "affected_road_segments": sim_res.affected_road_segments,
                    "affected_regions": sim_res.affected_regions,
                    "inaccessible_roads": sim_res.inaccessible_roads,
                    "incident_warnings": sim_res.incident_warnings,
                }
            )

        comparison_id = _stable_scenario_id(
            "compare",
            {
                "origin_node": orig,
                "destination_node": dest,
                "objective": obj.value,
                "simulation_ids": [c["simulation_id"] for c in compared],
            },
        )
        return {
            "comparison_id": comparison_id,
            "is_hypothetical": True,
            "is_synthetic": True,
            "origin_node": orig,
            "destination_node": dest,
            "objective": obj.value,
            "baseline_metrics": {
                "route_id": baseline_route["route_id"],
                "nodes": baseline_route["nodes"],
                "road_segments": baseline_route["road_segments"],
                "total_distance_km": baseline_route["total_distance_km"],
                "congestion_penalty_cost": baseline_route["congestion_penalty_cost"],
                "incident_penalty_cost": baseline_route["incident_penalty_cost"],
                "total_modelled_cost": baseline_route["total_modelled_cost"],
            },
            "scenarios": compared,
            "notes": [
                "All scenarios were evaluated on isolated road-network copies against the same baseline.",
                "Baseline road network and real incident records remain unchanged.",
            ],
        }
