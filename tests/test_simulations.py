import json

import pytest

from backend.services.incident_manager import IncidentIntelligenceService
from backend.services.road_network import (
    RoadNetwork,
    RoadSegmentNotFoundError,
    create_bengaluru_demo_network,
)
from backend.services.routing_engine import SmartRoutingEngine
from backend.services.simulation_engine import (
    SimulationError,
    SimulationNotFoundError,
    TrafficSimulationEngine,
)


def make_sim() -> tuple[RoadNetwork, IncidentIntelligenceService, SmartRoutingEngine, TrafficSimulationEngine]:
    net = create_bengaluru_demo_network()
    inc_svc = IncidentIntelligenceService(road_network=net)
    routing = SmartRoutingEngine(road_network=net, incident_service=inc_svc)
    sim = TrafficSimulationEngine(road_network=net, incident_service=inc_svc, routing_engine=routing)
    return net, inc_svc, routing, sim


def test_road_closure_simulation_and_isolation():
    net, inc_svc, _, sim = make_sim()
    res = sim.simulate_road_closure(
        closed_roads=["seg_indira_mara"],
        origin_node="mg_road",
        destination_node="marathahalli",
        scenario_name="Close HAL Old Airport Road",
    )
    assert res.simulation_id.startswith("sim_road_closure_")
    assert res.is_hypothetical is True
    assert res.route_changed is True
    assert "seg_indira_mara" in res.baseline_route["road_segments"]
    assert "seg_indira_mara" not in res.simulated_route["road_segments"]
    assert "seg_indira_mara" in res.inaccessible_roads
    assert "orr_east" in res.affected_regions

    # Verify original road network and incidents remain completely untouched
    assert net.get_segment("seg_indira_mara").closed is False
    assert inc_svc.list_incidents() == []

    # Retrieve from simulation store
    stored = sim.get_simulation(res.simulation_id)
    assert stored.to_dict() == res.to_dict()


def test_hypothetical_accident_and_obstruction_scenarios():
    net, inc_svc, _, sim = make_sim()
    acc = sim.simulate_hypothetical_incident(
        category="accident",
        affected_roads=["seg_indira_mara"],
        origin_node="mg_road",
        destination_node="marathahalli",
        severity="CRITICAL",
    )
    assert acc.is_hypothetical is True
    assert len(acc.hypothetical_incidents) == 1
    assert acc.hypothetical_incidents[0]["is_hypothetical"] is True
    assert acc.route_changed is True
    assert acc.cost_difference is not None

    obs = sim.simulate_hypothetical_incident(
        category="road_obstruction",
        affected_roads=["seg_kora_silk"],
        origin_node="koramangala",
        destination_node="silk_board",
        road_blocked=True,
    )
    assert "seg_kora_silk" not in obs.simulated_route["road_segments"]

    # Confirm zero real incidents were created
    assert inc_svc.list_incidents() == []
    assert net.get_segment("seg_kora_silk").closed is False


def test_congestion_increase_simulation():
    net, _, _, sim = make_sim()
    original_pen = net.get_segment("seg_mg_indira").congestion_penalty
    res = sim.simulate_congestion(
        congestion_updates=[{"road_id": "seg_mg_indira", "congestion_level": "SEVERE", "congestion_penalty": 2.5}],
        origin_node="mg_road",
        destination_node="marathahalli",
    )
    assert len(res.congestion_differences) == 1
    diff = res.congestion_differences[0]
    assert diff["road_id"] == "seg_mg_indira"
    assert diff["before_penalty"] == pytest.approx(original_pen)
    assert diff["after_penalty"] == pytest.approx(2.5)
    assert diff["penalty_delta"] > 0

    # Original network untouched
    assert net.get_segment("seg_mg_indira").congestion_penalty == pytest.approx(original_pen)


def test_multiple_scenario_comparison_and_reproducibility():
    net, inc_svc, _, sim = make_sim()
    scenarios = [
        {
            "scenario_name": "HAL Road Closure",
            "closed_roads": ["seg_indira_mara"],
        },
        {
            "scenario_name": "Bellandur Waterlogging",
            "hypothetical_incidents": [
                {"category": "waterlogging", "affected_roads": ["seg_silk_bell", "seg_bell_mara"], "severity": "HIGH"}
            ],
        },
        {
            "scenario_name": "Silk Board Severe Congestion",
            "congestion_updates": [{"road_id": "seg_kora_silk", "congestion_level": "SEVERE"}],
        },
    ]
    comp1 = sim.compare_scenarios("mg_road", "whitefield", scenarios)
    comp2 = sim.compare_scenarios("mg_road", "whitefield", scenarios)

    # Stable scenario IDs and comparison ID
    assert comp1["comparison_id"] == comp2["comparison_id"]
    assert [s["simulation_id"] for s in comp1["scenarios"]] == [s["simulation_id"] for s in comp2["scenarios"]]
    assert len(comp1["scenarios"]) == 3
    assert comp1["baseline_metrics"]["total_distance_km"] > 0
    assert inc_svc.list_incidents() == []
    assert net.get_segment("seg_indira_mara").closed is False
    assert json.loads(json.dumps(comp1))["comparison_id"] == comp1["comparison_id"]


def test_simulation_identifies_inaccessible_nodes_when_all_links_closed():
    _, _, _, sim = make_sim()
    # Close both roads connected to electronic_city (seg_silk_ecity and seg_bell_ecity)
    res = sim.simulate_road_closure(
        closed_roads=["seg_silk_ecity", "seg_bell_ecity"],
        origin_node="mg_road",
        destination_node="electronic_city",
    )
    assert res.route_reachable is False
    assert res.simulated_route is None
    assert "electronic_city" in res.inaccessible_nodes


def test_simulation_error_handling():
    _, _, _, sim = make_sim()
    with pytest.raises(SimulationNotFoundError):
        sim.get_simulation("sim_does_not_exist")
    with pytest.raises(RoadSegmentNotFoundError):
        sim.simulate_road_closure(["seg_bad"], "mg_road", "whitefield")
    with pytest.raises(SimulationError):
        sim.simulate_hypothetical_incident("invalid_cat", ["seg_mg_indira"], "mg_road", "whitefield")
