"""Comprehensive automated tests for the India-Wide Geospatial Backend:
- All 28 Indian States and 8 Union Territories, districts, and cities/towns
- PostGIS DDL migration verification & pooled SpatialDatabase
- OpenStreetMap (OSM) ingestion pipeline (.osm.pbf, .osm XML, .osm.json, .geojson)
- SHA-256 duplicate import prevention and force_reimport safe updates
- Strict topological intersection splitting (never connecting crossing geometries without a shared OSM node)
- One-way ('yes', 'reverse', 'no') and access-restricted road graph enforcement
- Regional bounding-box subgraph extraction and LRU caching
- Spatial incident-to-road matching with distance and directional bearing alignment
- Routing and isolated simulations over imported OSM road networks
- FastAPI /api/geo/* and /api/health endpoints
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.traffic import create_app
from backend.services.india_geo_registry import (
    INDIA_STATES_AND_UTS,
    OSM_ATTRIBUTION,
    OSM_LICENCE,
    find_state,
)
from backend.services.osm_ingestor import (
    OSMIngestionError,
    OSMIngestionPipeline,
    build_osm_pbf_bytes,
)
from backend.services.road_network import (
    BoundingBox,
    CoverageUnavailableError,
    GeoPoint,
    InvalidBoundingBoxError,
    RoadNetwork,
    create_bengaluru_demo_network,
)
from backend.services.routing_engine import NoRouteFoundError
from backend.services.spatial_db import SpatialDatabase
from backend.services.vision_engine import UrbanFlowPlatformState


def make_client() -> tuple[TestClient, UrbanFlowPlatformState]:
    state = UrbanFlowPlatformState()
    app = create_app(state=state)
    return TestClient(app), state


# ---------------------------------------------------------------------------
# 1. India Administrative Hierarchy (28 States + 8 Union Territories)
# ---------------------------------------------------------------------------


def test_india_all_28_states_and_8_union_territories_seeded():
    client, state = make_client()
    assert len(INDIA_STATES_AND_UTS) == 36

    resp = client.get("/api/geo/states")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 36
    assert OSM_ATTRIBUTION in body["attribution"]

    states_only = client.get("/api/geo/states", params={"territory_type": "state"}).json()
    uts_only = client.get("/api/geo/states", params={"territory_type": "union_territory"}).json()
    assert states_only["count"] == 28
    assert uts_only["count"] == 8

    southern = client.get("/api/geo/states", params={"zone": "Southern Zone"}).json()
    southern_codes = {s["code"] for s in southern["states"]}
    assert {"KA", "TN", "KL", "AP", "TG", "PY", "AN", "LD"}.issubset(southern_codes)

    # Invalid territory_type returns 422
    bad = client.get("/api/geo/states", params={"territory_type": "empire"})
    assert bad.status_code == 422


def test_districts_and_cities_queries_and_pagination():
    client, _ = make_client()

    # Query districts in Karnataka by code and by full name
    ka_dist = client.get("/api/geo/districts", params={"state": "KA"}).json()
    assert ka_dist["count"] >= 4
    ka_names = {d["name"] for d in ka_dist["districts"]}
    assert "Bengaluru Urban" in ka_names
    assert "Mysuru" in ka_names

    mh_dist = client.get("/api/geo/districts", params={"state": "Maharashtra"}).json()
    assert any(d["name"] == "Mumbai City" for d in mh_dist["districts"])

    # Pagination
    paged = client.get("/api/geo/districts", params={"limit": 3, "offset": 0}).json()
    assert paged["count"] == 3

    # Unknown state returns 404
    not_found = client.get("/api/geo/districts", params={"state": "Atlantis"})
    assert not_found.status_code == 404

    # Query cities by district and by state
    blr_cities = client.get("/api/geo/cities", params={"district": "KA_BLR_U"}).json()
    city_names = {c["name"] for c in blr_cities["cities"]}
    assert {"Bengaluru", "Yelahanka", "Electronic City"}.issubset(city_names)

    tn_cities = client.get("/api/geo/cities", params={"state": "TN"}).json()
    assert any(c["name"] == "Chennai" for c in tn_cities["cities"])


# ---------------------------------------------------------------------------
# 2. Bounding-Box Road Queries, Validation & Road Detail Lookup
# ---------------------------------------------------------------------------


def test_bbox_roads_geojson_and_validation():
    client, _ = make_client()

    # Valid bbox covering central/south Bengaluru
    resp = client.get("/api/geo/roads", params={"bbox": "77.55,12.80,77.78,13.05"})
    assert resp.status_code == 200
    fc = resp.json()
    assert fc["type"] == "FeatureCollection"
    assert fc["total_matched"] == 19
    assert len(fc["features"]) == 19
    first_feat = fc["features"][0]
    assert first_feat["type"] == "Feature"
    assert first_feat["geometry"]["type"] == "LineString"
    assert len(first_feat["geometry"]["coordinates"]) >= 2
    assert "road_id" in first_feat["properties"]

    # Pagination on /api/geo/roads
    paged = client.get("/api/geo/roads", params={"bbox": "77.55,12.80,77.78,13.05", "limit": 5, "offset": 0}).json()
    assert paged["total_matched"] == 19
    assert paged["returned_count"] == 5

    # Invalid bounding boxes -> 422
    for bad_bbox in [
        "invalid_bbox",
        "77.5,12.8,77.7",  # only 3 numbers
        "77.80,12.80,77.55,13.05",  # min_lon > max_lon
        "77.55,13.10,77.78,12.80",  # min_lat > max_lat
        "68.0,8.0,97.0,35.0",  # span > 5.0 degrees limit
        "-200.0,12.0,77.0,13.0",  # out-of-range longitude
    ]:
        r = client.get("/api/geo/roads", params={"bbox": bad_bbox})
        assert r.status_code == 422, f"Expected 422 for bbox={bad_bbox}"


def test_road_detail_endpoint_and_404():
    client, _ = make_client()

    resp = client.get("/api/geo/roads/seg_kora_silk")
    assert resp.status_code == 200
    data = resp.json()
    assert data["road"]["id"] == "seg_kora_silk"
    assert data["geojson"]["type"] == "Feature"
    assert data["source_node"]["id"] == "koramangala"
    assert data["target_node"]["id"] == "silk_board"
    assert data["licence"] == OSM_LICENCE

    missing = client.get("/api/geo/roads/seg_does_not_exist")
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# 3. Location Search, Coverage & India Overview Endpoints
# ---------------------------------------------------------------------------


def test_geo_search_coverage_india_and_health_endpoints():
    client, _ = make_client()

    # Search for state, city, intersection, and road
    s_ka = client.get("/api/geo/search", params={"q": "Karnataka"}).json()
    assert any(item["type"] == "state" and item["id"] == "KA" for item in s_ka["results"])

    s_silk = client.get("/api/geo/search", params={"q": "Silk Board"}).json()
    assert any(item["type"] == "intersection" and item["id"] == "silk_board" for item in s_silk["results"])

    s_hosur = client.get("/api/geo/search", params={"q": "Hosur"}).json()
    assert any(item["type"] == "road_segment" for item in s_hosur["results"])

    # Empty whitespace search query -> 422
    assert client.get("/api/geo/search", params={"q": "   "}).status_code == 422

    # Coverage endpoint
    cov = client.get("/api/geo/coverage").json()
    assert cov["country"] == "India"
    assert cov["nationwide_osm_imported"] is False
    assert cov["postgis_migration_ready"] is True
    assert Path(cov["postgis_migration_path"]).exists()
    assert cov["administrative_registry"]["states_count"] == 28
    assert cov["administrative_registry"]["union_territories_count"] == 8
    assert cov["road_network_statistics"]["synthetic_demo_road_segments"] == 19

    # India overview endpoint
    india = client.get("/api/geo/india").json()
    assert india["country"] == "India"
    assert india["srid"] == 4326
    assert "Southern Zone" in india["geofabrik_zones"]
    assert india["osm_licence"] == OSM_LICENCE

    # Health check endpoint
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["database"]["healthy"] is True
    assert health["road_network"]["segment_count"] == 19


# ---------------------------------------------------------------------------
# 4. OSM Ingestion Pipeline (.osm XML, .osm.pbf Binary, .geojson) & Topology
# ---------------------------------------------------------------------------


SAMPLE_OSM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="UrbanFlowTest">
  <!-- Shared intersection nodes in Chennai (Tamil Nadu) -->
  <node id="1001" lat="13.0400" lon="80.2300">
    <tag k="name" v="T Nagar Terminus"/>
  </node>
  <node id="1002" lat="13.0450" lon="80.2400">
    <tag k="name" v="Anna Salai Crossing"/>
    <tag k="highway" v="traffic_signals"/>
  </node>
  <node id="1003" lat="13.0500" lon="80.2500">
    <tag k="name" v="Marina Link Junction"/>
  </node>
  <node id="1004" lat="13.0380" lon="80.2400">
    <tag k="name" v="Saidapet North"/>
  </node>
  <node id="1005" lat="13.0520" lon="80.2400">
    <tag k="name" v="Thousand Lights"/>
  </node>

  <!-- Overpass bridge way (1006 -> 1007) whose geometry crosses over node 1002 WITHOUT sharing node 1002 -->
  <node id="1006" lat="13.0450" lon="80.2350">
    <tag k="name" v="Flyover West Ramp"/>
  </node>
  <node id="1007" lat="13.0450" lon="80.2450">
    <tag k="name" v="Flyover East Ramp"/>
  </node>

  <!-- Way 5001: 1001 -> 1002 -> 1003 (splits at shared intersection 1002) -->
  <way id="5001">
    <nd ref="1001"/>
    <nd ref="1002"/>
    <nd ref="1003"/>
    <tag k="highway" v="primary"/>
    <tag k="name" v="Anna Salai Arterial"/>
    <tag k="lanes" v="4"/>
    <tag k="maxspeed" v="60 km/h"/>
    <tag k="surface" v="asphalt"/>
    <tag k="oneway" v="no"/>
  </way>

  <!-- Way 5002: 1004 -> 1002 -> 1005 (one-way northbound through shared node 1002) -->
  <way id="5002">
    <nd ref="1004"/>
    <nd ref="1002"/>
    <nd ref="1005"/>
    <tag k="highway" v="secondary"/>
    <tag k="name" v="Mount Road OneWay"/>
    <tag k="lanes" v="2"/>
    <tag k="maxspeed" v="40"/>
    <tag k="oneway" v="yes"/>
  </way>

  <!-- Way 5003: 1003 -> 1005 with reverse oneway (-1) so traffic flows 1005 -> 1003 -->
  <way id="5003">
    <nd ref="1003"/>
    <nd ref="1005"/>
    <tag k="highway" v="tertiary"/>
    <tag k="name" v="Cathedral Reverse Link"/>
    <tag k="oneway" v="-1"/>
  </way>

  <!-- Way 5004: Flyover crossing geometrically over (13.0450, 80.2400) but NOT sharing node 1002 -->
  <way id="5004">
    <nd ref="1006"/>
    <nd ref="1007"/>
    <tag k="highway" v="trunk"/>
    <tag k="name" v="Isolated Grade Flyover"/>
    <tag k="bridge" v="yes"/>
    <tag k="oneway" v="yes"/>
  </way>

  <!-- Non-highway way (building) should be skipped cleanly -->
  <way id="5099">
    <nd ref="1001"/>
    <nd ref="1004"/>
    <tag k="building" v="commercial"/>
  </way>
</osm>
"""


def test_osm_xml_ingestion_topological_splitting_oneway_and_deduplication(tmp_path: Path):
    client, state = make_client()
    osm_file = tmp_path / "chennai_extract.osm"
    osm_file.write_text(SAMPLE_OSM_XML, encoding="utf-8")

    report = state.osm_ingestor.ingest_file(
        osm_file,
        region_name="chennai_central",
        state_code="TN",
        district_id="TN_CHN",
        city_id="city_chennai",
    )
    assert report.status == "completed"
    assert report.state_code == "TN"
    assert report.imported_nodes == 7
    # Way 5001 split into 2 segments, Way 5002 split into 2 segments, Way 5003 = 1, Way 5004 = 1 -> 6 segments
    assert report.imported_roads == 6
    assert report.skipped_elements == 1

    # Duplicate import with same SHA-256 is skipped automatically
    dup_report = state.osm_ingestor.ingest_file(
        osm_file,
        region_name="chennai_central",
        state_code="TN",
    )
    assert dup_report.status == "skipped_duplicate"
    assert dup_report.import_id == report.import_id

    # Force re-import updates cleanly without duplicating nodes/edges
    forced = state.osm_ingestor.ingest_file(
        osm_file,
        region_name="chennai_central",
        state_code="TN",
        force_reimport=True,
    )
    assert forced.status == "completed"

    # Verify strict topological isolation: Flyover (osm_n_1006 -> osm_n_1007) does NOT connect to Anna Salai (osm_n_1001)
    with pytest.raises(NoRouteFoundError):
        state.routing_engine.calculate_route(
            origin_node="osm_n_1006",
            destination_node="osm_n_1001",
        )

    # Verify one-way enforcement on Way 5002 (1004 -> 1002 -> 1005 is allowed, but 1002 -> 1004 is forbidden)
    route_forward = state.routing_engine.calculate_route(
        origin_node="osm_n_1004",
        destination_node="osm_n_1005",
    )
    assert route_forward.recommended_route.nodes == ["osm_n_1004", "osm_n_1002", "osm_n_1005"]

    with pytest.raises(NoRouteFoundError):
        state.routing_engine.calculate_route(
            origin_node="osm_n_1002",
            destination_node="osm_n_1004",
        )

    # Verify reverse one-way (-1) on Way 5003: allows 1005 -> 1003
    route_via_reverse = state.routing_engine.calculate_route(
        origin_node="osm_n_1004",
        destination_node="osm_n_1003",
    )
    assert route_via_reverse.recommended_route.nodes[0] == "osm_n_1004"
    assert route_via_reverse.recommended_route.nodes[-1] == "osm_n_1003"


def test_osm_pbf_binary_and_geojson_ingestion(tmp_path: Path):
    _, state = make_client()

    # Build a real zlib-compressed `.osm.pbf` binary for Mumbai (Maharashtra)
    pbf_bytes = build_osm_pbf_bytes(
        nodes=[
            (2001, 19.0760, 72.8777, {"name": "Dadar TT Circle"}),
            (2002, 19.0820, 72.8820, {"name": "Sion Junction"}),
            (2003, 19.0900, 72.8900, {"name": "Kurla West"}),
        ],
        ways=[
            (
                6001,
                [2001, 2002, 2003],
                {
                    "highway": "trunk",
                    "name": "Lal Bahadur Shastri Marg",
                    "lanes": "4",
                    "maxspeed": "60",
                    "surface": "concrete",
                    "oneway": "no",
                },
            )
        ],
    )
    pbf_path = tmp_path / "mumbai_sion.osm.pbf"
    pbf_path.write_bytes(pbf_bytes)

    pbf_report = state.osm_ingestor.ingest_file(
        pbf_path,
        region_name="mumbai_central",
        state_code="MH",
    )
    assert pbf_report.status == "completed"
    assert pbf_report.source_format == "osm.pbf"
    assert pbf_report.imported_roads == 1
    seg = state.road_network.get_segment("osm_w_6001")
    assert seg.name == "Lal Bahadur Shastri Marg"
    assert seg.surface == "concrete"
    assert seg.state_code == "MH"
    assert len(seg.geometry) == 3

    # Build a GeoJSON extract for New Delhi
    geojson_payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": 7001,
                "properties": {
                    "osm_way_id": 7001,
                    "osm_node_ids": [3001, 3002],
                    "highway": "primary",
                    "name": "Janpath Road",
                    "lanes": 4,
                    "maxspeed": "50",
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[77.2167, 28.6139], [77.2200, 28.6300]],
                },
            }
        ],
    }
    geojson_path = tmp_path / "delhi_janpath.geojson"
    geojson_path.write_text(json.dumps(geojson_payload), encoding="utf-8")

    gj_report = state.osm_ingestor.ingest_file(
        geojson_path,
        region_name="new_delhi_central",
        state_code="DL",
    )
    assert gj_report.status == "completed"
    assert gj_report.imported_roads == 1
    assert state.road_network.has_segment("osm_w_7001")


def test_osm_ingestion_rejects_corrupted_or_out_of_india_files(tmp_path: Path):
    _, state = make_client()

    # Empty file
    empty_f = tmp_path / "empty.osm"
    empty_f.write_text("", encoding="utf-8")
    with pytest.raises(OSMIngestionError):
        state.osm_ingestor.ingest_file(empty_f, region_name="bad")

    # Corrupted PBF
    bad_pbf = tmp_path / "corrupt.osm.pbf"
    bad_pbf.write_bytes(b"NOT_A_VALID_PBF_HEADER_STREAM")
    with pytest.raises(OSMIngestionError):
        state.osm_ingestor.ingest_file(bad_pbf, region_name="bad")

    # Coordinates outside India (e.g. London)
    london_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <osm version="0.6">
      <node id="1" lat="51.5074" lon="-0.1278"/>
      <node id="2" lat="51.5080" lon="-0.1285"/>
      <way id="10">
        <nd ref="1"/><nd ref="2"/>
        <tag k="highway" v="primary"/>
      </way>
    </osm>
    """
    london_f = tmp_path / "london.osm"
    london_f.write_text(london_xml, encoding="utf-8")
    with pytest.raises(OSMIngestionError, match="outside India bounds"):
        state.osm_ingestor.ingest_file(london_f, region_name="london")


# ---------------------------------------------------------------------------
# 5. Regional Graph Caching, Spatial Incident Matching & Isolated Simulation
# ---------------------------------------------------------------------------


def test_regional_graph_extraction_cache_and_incident_spatial_matching(tmp_path: Path):
    client, state = make_client()
    osm_file = tmp_path / "chennai_extract.osm"
    osm_file.write_text(SAMPLE_OSM_XML, encoding="utf-8")
    state.osm_ingestor.ingest_file(osm_file, region_name="chennai_central", state_code="TN")

    # Extract Chennai regional network via bbox and verify LRU cache population
    bbox = BoundingBox.from_string("80.22,13.03,80.26,13.06")
    reg_net = state.road_network.extract_regional_network(bbox)
    assert len(reg_net.segments) == 6
    assert state.road_network.regional_cache_size >= 1

    # Route using regional bbox over API
    route_resp = client.post(
        "/api/routes/calculate",
        json={
            "origin_node": "osm_n_1001",
            "destination_node": "osm_n_1003",
            "bbox": "80.22,13.03,80.26,13.06",
            "objective": "incident_aware",
        },
    )
    assert route_resp.status_code == 200
    assert route_resp.json()["recommended_route"]["nodes"] == ["osm_n_1001", "osm_n_1002", "osm_n_1003"]

    # Create an incident by coordinates ONLY (near Anna Salai 13.0425, 80.2350) -> auto-matches osm_w_5001_p1
    inc_resp = client.post(
        "/api/incidents",
        json={
            "category": "accident",
            "title": "Collision on Anna Salai",
            "coordinates": {"lat": 13.0425, "lon": 80.2350},
            "source": "operator",
        },
    )
    assert inc_resp.status_code == 201
    inc_data = inc_resp.json()
    assert "osm_w_5001_p1" in inc_data["affected_roads"]
    assert inc_data["state_code"] == "TN"
    assert inc_data["matched_road_distance_km"] is not None
    assert inc_data["matched_road_distance_km"] < 0.05

    # Run an isolated road-closure simulation on imported OSM road segment
    sim_resp = client.post(
        "/api/simulations/road-closure",
        json={
            "closed_roads": ["osm_w_5001_p2"],
            "origin_node": "osm_n_1001",
            "destination_node": "osm_n_1005",
            "scenario_name": "Anna Salai East Closure",
        },
    )
    assert sim_resp.status_code == 201
    sim_data = sim_resp.json()
    assert sim_data["is_hypothetical"] is True
    # Live OSM road segment remains open
    assert state.road_network.get_segment("osm_w_5001_p2").closed is False

    # Requesting route for coordinates in a region with no imported road coverage (> 25 km from any node) -> 422
    no_cov = client.post(
        "/api/routes/calculate",
        json={
            "origin_coordinates": {"lat": 26.9124, "lon": 75.7873},  # Jaipur (no OSM roads imported yet)
            "destination_coordinates": {"lat": 26.9200, "lon": 75.8000},
        },
    )
    assert no_cov.status_code == 422


def test_directional_bearing_matching_on_parallel_oneway_carriageways(tmp_path: Path):
    """When two parallel one-way carriageways run in opposite directions (e.g. Northbound vs Southbound),
    `travel_bearing_deg` selects the carriageway matching the direction of travel."""
    _, state = make_client()
    overpass_json = {
        "version": 0.6,
        "elements": [
            {"type": "node", "id": 8001, "lat": 17.4000, "lon": 78.4800},
            {"type": "node", "id": 8002, "lat": 17.4100, "lon": 78.4800},
            {"type": "node", "id": 8003, "lat": 17.4000, "lon": 78.4802},
            {"type": "node", "id": 8004, "lat": 17.4100, "lon": 78.4802},
            # Northbound carriageway (8001 -> 8002, bearing ~0 deg)
            {
                "type": "way",
                "id": 9001,
                "nodes": [8001, 8002],
                "tags": {"highway": "trunk", "name": "NH44 Northbound", "oneway": "yes"},
            },
            # Southbound carriageway (8004 -> 8003, bearing ~180 deg)
            {
                "type": "way",
                "id": 9002,
                "nodes": [8004, 8003],
                "tags": {"highway": "trunk", "name": "NH44 Southbound", "oneway": "yes"},
            },
        ],
    }
    json_path = tmp_path / "hyderabad_nh44.osm.json"
    json_path.write_text(json.dumps(overpass_json), encoding="utf-8")
    rep = state.osm_ingestor.ingest_file(json_path, region_name="hyderabad_nh44", state_code="TG")
    assert rep.status == "completed"
    assert rep.imported_roads == 2

    pt = GeoPoint(17.4050, 78.4801)  # Midpoint between the two parallel carriageways
    seg_nb, _ = state.road_network.match_nearest_road_segment(pt, travel_bearing_deg=5.0)
    seg_sb, _ = state.road_network.match_nearest_road_segment(pt, travel_bearing_deg=175.0)
    assert seg_nb.id == "osm_w_9001"
    assert seg_sb.id == "osm_w_9002"

