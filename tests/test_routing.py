import json

import pytest

from backend.services.incident_manager import IncidentIntelligenceService
from backend.services.road_network import (
    InvalidCoordinatesError,
    NodeNotFoundError,
    RoadNetwork,
    RoadNode,
    RoadSegment,
    RoadSegmentNotFoundError,
    create_bengaluru_demo_network,
)
from backend.services.routing_engine import (
    NoRouteFoundError,
    RoutingError,
    RoutingObjective,
    RoutingWeights,
    SmartRoutingEngine,
)


def make_routing() -> tuple[RoadNetwork, IncidentIntelligenceService, SmartRoutingEngine]:
    net = create_bengaluru_demo_network()
    inc_svc = IncidentIntelligenceService(road_network=net)
    eng = SmartRoutingEngine(road_network=net, incident_service=inc_svc)
    return net, inc_svc, eng


def test_shortest_distance_route():
    _, _, eng = make_routing()
    res = eng.calculate_route(
        "mg_road",
        "marathahalli",
        objective=RoutingObjective.SHORTEST_DISTANCE,
    )
    rec = res.recommended_route
    # Direct path: mg_road -> indiranagar (4.2) -> marathahalli (7.1) = 11.3 km
    assert rec.nodes == ["mg_road", "indiranagar", "marathahalli"]
    assert rec.road_segments == ["seg_mg_indira", "seg_indira_mara"]
    assert rec.total_distance_km == pytest.approx(11.3)
    assert rec.congestion_penalty_cost == 0.0
    assert rec.incident_penalty_cost == 0.0
    assert rec.total_modelled_cost == pytest.approx(11.3)


def test_congestion_aware_route_detours_when_direct_heavily_congested():
    net, _, eng = make_routing()
    # Increase congestion on HAL Old Airport Road (seg_indira_mara)
    net.set_road_congestion("seg_indira_mara", congestion_penalty=3.0)
    res = eng.calculate_route(
        "indiranagar",
        "marathahalli",
        objective=RoutingObjective.CONGESTION_AWARE,
        weights=RoutingWeights(congestion_weight=2.0, incident_weight=0.0),
    )
    # Direct path indiranagar -> marathahalli has high congestion cost; detour via kr_puram or koramangala/bellandur is preferred
    assert res.recommended_route.road_segments != ["seg_indira_mara"]
    assert res.comparison["modelled_cost_reduction_vs_shortest_open"] > 0


def test_incident_aware_route_avoids_accident_and_explains():
    _, inc_svc, eng = make_routing()
    inc = inc_svc.create_incident(
        category="accident",
        title="Major multi-vehicle accident on HAL Old Airport Road",
        affected_roads=["seg_indira_mara"],
        severity="CRITICAL",
        source="operator",
    )
    res = eng.calculate_route(
        "mg_road",
        "marathahalli",
        objective=RoutingObjective.INCIDENT_AWARE,
        weights=RoutingWeights(congestion_weight=1.0, incident_weight=2.5),
    )
    assert "seg_indira_mara" not in res.recommended_route.road_segments
    assert "seg_indira_mara" in res.avoided_incident_roads
    assert any(i["incident_id"] == inc.id for i in res.incidents_affecting_shortest_path)
    assert "seg_indira_mara" in res.explanation


def test_road_closure_strictly_excluded_from_routes():
    net, _, eng = make_routing()
    net.set_road_closed("seg_indira_mara", closed=True, reason="Flyover structural work")
    res = eng.calculate_route(
        "mg_road",
        "marathahalli",
        objective=RoutingObjective.SHORTEST_DISTANCE,
        max_alternatives=5,
    )
    for cand in res.alternatives:
        assert "seg_indira_mara" not in cand.road_segments
    assert "seg_indira_mara" in res.avoided_closed_roads


def test_road_closure_incident_also_excludes_road():
    _, inc_svc, eng = make_routing()
    inc_svc.create_incident(
        category="road_closure",
        title="Complete closure on Hosur Elevated Expressway",
        affected_roads=["seg_silk_ecity"],
        source="operator",
    )
    res = eng.calculate_route("silk_board", "electronic_city")
    assert "seg_silk_ecity" not in res.recommended_route.road_segments
    assert "seg_bell_ecity" in res.recommended_route.road_segments


def test_alternative_routes_generation_and_ranking():
    _, _, eng = make_routing()
    res = eng.calculate_route("mg_road", "whitefield", max_alternatives=4)
    assert len(res.alternatives) >= 3
    costs = [r.total_modelled_cost for r in res.alternatives]
    assert costs == sorted(costs)
    assert [r.rank for r in res.alternatives] == list(range(1, len(res.alternatives) + 1))
    assert all(r.recommendation_reason for r in res.alternatives)


def test_coordinate_based_endpoint_resolution():
    _, _, eng = make_routing()
    res = eng.calculate_route(
        origin_coordinates={"lat": 12.9756, "lon": 77.6066},  # MG Road
        destination_coordinates={"lat": 12.9698, "lon": 77.7499},  # Whitefield
    )
    assert res.origin_node == "mg_road"
    assert res.destination_node == "whitefield"


def test_disconnected_graph_raises_no_route_found():
    nodes = [
        RoadNode("a", "Node A", 12.90, 77.60, "r1"),
        RoadNode("b", "Node B", 12.91, 77.61, "r1"),
        RoadNode("c", "Isolated Node C", 12.95, 77.65, "r2"),
    ]
    segs = [RoadSegment("seg_ab", "Road AB", "a", "b", 2.0, "r1")]
    net = RoadNetwork(nodes, segs)
    eng = SmartRoutingEngine(net)
    with pytest.raises(NoRouteFoundError):
        eng.calculate_route("a", "c")


def test_missing_node_road_and_invalid_coordinates():
    net, _, eng = make_routing()
    with pytest.raises(NodeNotFoundError):
        eng.calculate_route("unknown_node", "mg_road")
    with pytest.raises(RoadSegmentNotFoundError):
        net.get_segment("seg_missing")
    with pytest.raises(InvalidCoordinatesError):
        eng.calculate_route(
            origin_coordinates={"lat": 28.6139, "lon": 77.2090},  # New Delhi (>25km from Bengaluru)
            destination_node="mg_road",
        )
    with pytest.raises(RoutingError):
        RoutingWeights(congestion_weight=-1.0)


def test_route_result_json_serializable():
    _, _, eng = make_routing()
    res = eng.calculate_route("mg_road", "electronic_city")
    payload = json.loads(json.dumps(res.to_dict()))
    assert payload["recommended_route"]["cost_basis"] == "modelled_weighted_distance_cost_not_travel_time"
    assert any("not calibrated travel time" in n for n in payload["notes"])
