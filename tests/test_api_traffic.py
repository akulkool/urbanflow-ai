from fastapi.testclient import TestClient

from backend.api.traffic import create_app
from backend.services.vision_engine import UrbanFlowPlatformState


def make_client() -> tuple[TestClient, UrbanFlowPlatformState]:
    state = UrbanFlowPlatformState()
    app = create_app(state=state)
    return TestClient(app), state


def test_network_endpoint():
    client, _ = make_client()
    r = client.get("/api/network")
    assert r.status_code == 200
    data = r.json()
    assert data["is_synthetic"] is True
    assert data["node_count"] >= 10
    assert data["segment_count"] >= 15


def test_incident_endpoints_full_lifecycle():
    client, _ = make_client()
    # Create
    r = client.post(
        "/api/incidents",
        json={
            "category": "waterlogging",
            "title": "Waterlogging at Bellandur Junction",
            "description": "Heavy rain accumulation across outer lanes",
            "affected_roads": ["seg_silk_bell"],
            "coordinates": {"lat": 12.9304, "lon": 77.6784},
            "source": "auto_cv",
        },
    )
    assert r.status_code == 201
    inc = r.json()
    inc_id = inc["id"]
    assert inc["status"] == "candidate"
    assert inc["severity"] == "HIGH"

    # List & filter
    r_list = client.get("/api/incidents", params={"status": "candidate", "road_id": "seg_silk_bell"})
    assert r_list.status_code == 200
    assert len(r_list.json()) == 1

    # Get by ID
    r_get = client.get(f"/api/incidents/{inc_id}")
    assert r_get.status_code == 200
    assert r_get.json()["id"] == inc_id

    # Patch severity & title
    r_patch = client.patch(
        f"/api/incidents/{inc_id}",
        json={"severity": "CRITICAL", "severity_reason": "Two lanes submerged"},
    )
    assert r_patch.status_code == 200
    assert r_patch.json()["severity"] == "CRITICAL"

    # Confirm
    r_conf = client.post(f"/api/incidents/{inc_id}/confirm", json={"notes": "Confirmed via traffic camera"})
    assert r_conf.status_code == 200
    assert r_conf.json()["status"] == "confirmed"

    # Resolve
    r_res = client.post(f"/api/incidents/{inc_id}/resolve", json={"notes": "Pumps cleared water"})
    assert r_res.status_code == 200
    assert r_res.json()["status"] == "resolved"
    assert r_res.json()["is_active_for_routing"] is False

    # Dismissing an already resolved incident returns 409 Conflict
    r_bad = client.post(f"/api/incidents/{inc_id}/dismiss")
    assert r_bad.status_code == 409

    # Reopen and then dismiss candidate
    r_reopen = client.post(f"/api/incidents/{inc_id}/reopen", json={"notes": "Re-evaluating"})
    assert r_reopen.status_code == 200
    assert r_reopen.json()["status"] == "confirmed"


def test_incident_dismiss_endpoint():
    client, _ = make_client()
    r = client.post(
        "/api/incidents",
        json={"category": "stationary_vehicle", "title": "Stopped cab", "source": "auto_cv"},
    )
    inc_id = r.json()["id"]
    r_dis = client.post(f"/api/incidents/{inc_id}/dismiss", json={"notes": "False positive"})
    assert r_dis.status_code == 200
    assert r_dis.json()["status"] == "dismissed"


def test_routing_endpoints_calculate_and_alternatives():
    client, _ = make_client()
    # Add an incident on seg_indira_mara
    client.post(
        "/api/incidents",
        json={
            "category": "accident",
            "title": "Accident on HAL Old Airport Road",
            "affected_roads": ["seg_indira_mara"],
            "severity": "CRITICAL",
            "source": "operator",
        },
    )

    r_calc = client.post(
        "/api/routes/calculate",
        json={
            "origin_node": "mg_road",
            "destination_node": "marathahalli",
            "objective": "incident_aware",
            "weights": {"congestion_weight": 1.0, "incident_weight": 2.0},
        },
    )
    assert r_calc.status_code == 200
    calc = r_calc.json()
    assert "seg_indira_mara" not in calc["recommended_route"]["road_segments"]
    assert "seg_indira_mara" in calc["avoided_incident_roads"]

    r_alt = client.post(
        "/api/routes/alternatives",
        json={
            "origin_node": "mg_road",
            "destination_node": "whitefield",
            "max_alternatives": 4,
        },
    )
    assert r_alt.status_code == 200
    assert len(r_alt.json()["alternatives"]) >= 3


def test_simulation_endpoints_and_isolation():
    client, state = make_client()
    # 1. Road closure simulation
    r_close = client.post(
        "/api/simulations/road-closure",
        json={
            "closed_roads": ["seg_indira_mara"],
            "origin_node": "mg_road",
            "destination_node": "marathahalli",
        },
    )
    assert r_close.status_code == 201
    sim_close = r_close.json()
    sim_id = sim_close["simulation_id"]
    assert sim_close["route_changed"] is True

    # GET simulation by ID
    r_get = client.get(f"/api/simulations/{sim_id}")
    assert r_get.status_code == 200
    assert r_get.json()["simulation_id"] == sim_id

    # 2. Hypothetical incident simulation
    r_inc = client.post(
        "/api/simulations/incident",
        json={
            "category": "waterlogging",
            "affected_roads": ["seg_silk_bell"],
            "origin_node": "silk_board",
            "destination_node": "marathahalli",
            "severity": "CRITICAL",
        },
    )
    assert r_inc.status_code == 201
    assert r_inc.json()["is_hypothetical"] is True

    # 3. Congestion simulation
    r_cong = client.post(
        "/api/simulations/congestion",
        json={
            "congestion_updates": [{"road_id": "seg_mg_indira", "congestion_level": "SEVERE"}],
            "origin_node": "mg_road",
            "destination_node": "indiranagar",
        },
    )
    assert r_cong.status_code == 201
    assert r_cong.json()["cost_difference"] > 0

    # 4. Multi-scenario compare
    r_comp = client.post(
        "/api/simulations/compare",
        json={
            "origin_node": "mg_road",
            "destination_node": "marathahalli",
            "scenarios": [
                {"scenario_name": "Close HAL", "closed_roads": ["seg_indira_mara"]},
                {
                    "scenario_name": "Congest IRR",
                    "congestion_updates": [{"road_id": "seg_indira_kora", "congestion_level": "SEVERE"}],
                },
            ],
        },
    )
    assert r_comp.status_code == 200
    assert len(r_comp.json()["scenarios"]) == 2

    # Ensure real incident store and real road network were not polluted by any simulation
    assert state.incident_service.list_incidents() == []
    assert state.road_network.get_segment("seg_indira_mara").closed is False


def test_api_validation_and_error_responses():
    client, _ = make_client()
    assert client.get("/api/incidents/inc_missing").status_code == 404
    assert client.get("/api/simulations/sim_missing").status_code == 404
    assert (
        client.post(
            "/api/routes/calculate",
            json={"origin_node": "nonexistent_node", "destination_node": "mg_road"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/incidents",
            json={"category": "unknown_category", "title": "Bad"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/simulations/road-closure",
            json={"closed_roads": [], "origin_node": "mg_road", "destination_node": "whitefield"},
        ).status_code
        == 422
    )
