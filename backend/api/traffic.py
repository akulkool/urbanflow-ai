"""FastAPI Backend Integration for UrbanFlow AI.

Registers all Incidents, Smart Routing, and Traffic Simulation endpoints under `/api`:
- GET    /api/incidents
- POST   /api/incidents
- GET    /api/incidents/{id}
- PATCH  /api/incidents/{id}
- POST   /api/incidents/{id}/confirm
- POST   /api/incidents/{id}/dismiss
- POST   /api/incidents/{id}/resolve
- POST   /api/incidents/{id}/reopen
- POST   /api/routes/calculate
- POST   /api/routes/alternatives
- POST   /api/simulations/road-closure
- POST   /api/simulations/incident
- POST   /api/simulations/congestion
- POST   /api/simulations/compare
- GET    /api/simulations/{id}
- GET    /api/network
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, status

from backend.schemas.traffic import (
    CongestionSimulationRequest,
    HypotheticalIncidentSimulationRequest,
    IncidentActionRequest,
    IncidentCreateRequest,
    IncidentResponse,
    IncidentUpdateRequest,
    RoadClosureSimulationRequest,
    RouteCalculateRequest,
    RouteCalculationResponse,
    ScenarioComparisonRequest,
    SimulationResponse,
)
from backend.services.incident_manager import (
    IncidentError,
    IncidentNotFoundError,
    InvalidIncidentTransitionError,
)
from backend.services.india_geo_registry import (
    GEOFABRIK_ZONES,
    INDIA_MAX_LAT,
    INDIA_MAX_LON,
    INDIA_MIN_LAT,
    INDIA_MIN_LON,
    OSM_ATTRIBUTION,
    OSM_LICENCE,
    OSM_LICENCE_URL,
    OSM_SOURCE_URL,
    find_state,
)
from backend.services.osm_ingestor import OSMIngestionError
from backend.services.road_network import (
    BoundingBox,
    CoverageUnavailableError,
    InvalidBoundingBoxError,
    InvalidCoordinatesError,
    NodeNotFoundError,
    RoadNetworkError,
    RoadSegmentNotFoundError,
)
from backend.services.routing_engine import (
    NoRouteFoundError,
    RoutingError,
    RoutingWeights,
)
from backend.services.simulation_engine import (
    SimulationError,
    SimulationNotFoundError,
)
from backend.services.vision_engine import (
    UrbanFlowPlatformState,
    get_platform_state,
)

router = APIRouter(prefix="/api", tags=["urbanflow-traffic"])


def _weights_from_schema(w_schema: Any) -> RoutingWeights | None:
    if w_schema is None:
        return None
    return RoutingWeights(
        congestion_weight=w_schema.congestion_weight,
        incident_weight=w_schema.incident_weight,
    )


def _handle_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (IncidentNotFoundError, SimulationNotFoundError, NodeNotFoundError, RoadSegmentNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (InvalidIncidentTransitionError, NoRouteFoundError)):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(
        exc,
        (
            InvalidBoundingBoxError,
            CoverageUnavailableError,
            InvalidCoordinatesError,
            OSMIngestionError,
            IncidentError,
            RoutingError,
            SimulationError,
            RoadNetworkError,
            ValueError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ---------------------------------------------------------------------------
# Road Network Inspection
# ---------------------------------------------------------------------------


@router.get("/network", summary="Inspect the road network nodes and road segments")
def get_road_network(state: UrbanFlowPlatformState = Depends(get_platform_state)) -> dict[str, Any]:
    return state.road_network.summary()


# ---------------------------------------------------------------------------
# Incident Intelligence Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/incidents",
    response_model=list[IncidentResponse],
    summary="List incidents with optional filters",
)
def list_incidents(
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    region: str | None = Query(default=None),
    state_code: str | None = Query(default=None, alias="state"),
    district_id: str | None = Query(default=None, alias="district"),
    city_id: str | None = Query(default=None, alias="city"),
    road_id: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> list[dict[str, Any]]:
    try:
        items = state.incident_service.list_incidents(
            status=status_filter,
            category=category,
            severity=severity,
            region=region,
            state_code=state_code,
            district_id=district_id,
            city_id=city_id,
            road_id=road_id,
            active_only=active_only,
        )
        return [i.to_dict() for i in items]
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/incidents",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or report a traffic incident",
)
def create_incident(
    payload: IncidentCreateRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        coords = payload.coordinates.model_dump() if payload.coordinates else None
        inc = state.incident_service.create_incident(
            category=payload.category,
            title=payload.title,
            description=payload.description,
            affected_roads=payload.affected_roads,
            region=payload.region,
            state_code=payload.state_code,
            district_id=payload.district_id,
            city_id=payload.city_id,
            coordinates=coords,
            severity=payload.severity,
            severity_reason=payload.severity_reason,
            source=payload.source,
            status=payload.status,
            evidence=payload.evidence,
            is_synthetic=payload.is_synthetic,
            auto_match_road=payload.auto_match_road,
            travel_bearing_deg=payload.travel_bearing_deg,
        )
        return inc.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    summary="Get an incident by ID",
)
def get_incident(
    incident_id: str,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        return state.incident_service.get_incident(incident_id).to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.patch(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    summary="Update incident severity, status, location, or affected roads",
)
def update_incident(
    incident_id: str,
    payload: IncidentUpdateRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        coords = payload.coordinates.model_dump() if payload.coordinates else None
        inc = state.incident_service.update_incident(
            incident_id,
            title=payload.title,
            description=payload.description,
            category=payload.category,
            severity=payload.severity,
            severity_reason=payload.severity_reason,
            status=payload.status,
            affected_roads=payload.affected_roads,
            region=payload.region,
            state_code=payload.state_code,
            district_id=payload.district_id,
            city_id=payload.city_id,
            coordinates=coords,
            evidence=payload.evidence,
            resolution_notes=payload.resolution_notes,
            auto_match_road=payload.auto_match_road,
            travel_bearing_deg=payload.travel_bearing_deg,
        )
        return inc.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/incidents/{incident_id}/confirm",
    response_model=IncidentResponse,
    summary="Confirm an incident candidate or reported incident",
)
def confirm_incident(
    incident_id: str,
    payload: IncidentActionRequest | None = None,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        notes = payload.notes if payload else None
        return state.incident_service.confirm_incident(incident_id, notes=notes).to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/incidents/{incident_id}/dismiss",
    response_model=IncidentResponse,
    summary="Dismiss an incident candidate as a false positive",
)
def dismiss_incident(
    incident_id: str,
    payload: IncidentActionRequest | None = None,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        notes = payload.notes if payload else None
        return state.incident_service.dismiss_incident(incident_id, reason=notes).to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=IncidentResponse,
    summary="Mark an incident as resolved",
)
def resolve_incident(
    incident_id: str,
    payload: IncidentActionRequest | None = None,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        notes = payload.notes if payload else None
        return state.incident_service.resolve_incident(incident_id, resolution_notes=notes).to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/incidents/{incident_id}/reopen",
    response_model=IncidentResponse,
    summary="Reopen a resolved or dismissed incident",
)
def reopen_incident(
    incident_id: str,
    payload: IncidentActionRequest | None = None,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        notes = payload.notes if payload else None
        return state.incident_service.reopen_incident(incident_id, notes=notes).to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


# ---------------------------------------------------------------------------
# Smart Routing Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/routes/calculate",
    response_model=RouteCalculationResponse,
    summary="Calculate optimal route with incident & congestion awareness",
)
def calculate_route(
    payload: RouteCalculateRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        orig_coords = payload.origin_coordinates.model_dump() if payload.origin_coordinates else None
        dest_coords = payload.destination_coordinates.model_dump() if payload.destination_coordinates else None
        res = state.routing_engine.calculate_route(
            origin_node=payload.origin_node,
            destination_node=payload.destination_node,
            origin_coordinates=orig_coords,
            destination_coordinates=dest_coords,
            objective=payload.objective,
            weights=_weights_from_schema(payload.weights),
            max_alternatives=payload.max_alternatives,
            bbox=payload.bbox,
            use_regional_extract=payload.use_regional_extract,
        )
        return res.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/routes/alternatives",
    response_model=RouteCalculationResponse,
    summary="Generate ranked alternative routes and route comparisons",
)
def calculate_alternative_routes(
    payload: RouteCalculateRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        orig_coords = payload.origin_coordinates.model_dump() if payload.origin_coordinates else None
        dest_coords = payload.destination_coordinates.model_dump() if payload.destination_coordinates else None
        res = state.routing_engine.calculate_route(
            origin_node=payload.origin_node,
            destination_node=payload.destination_node,
            origin_coordinates=orig_coords,
            destination_coordinates=dest_coords,
            objective=payload.objective,
            weights=_weights_from_schema(payload.weights),
            max_alternatives=max(payload.max_alternatives, 3),
            bbox=payload.bbox,
            use_regional_extract=payload.use_regional_extract,
        )
        return res.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


# ---------------------------------------------------------------------------
# Traffic Simulation Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/simulations/road-closure",
    response_model=SimulationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate closing one or more road segments on an isolated graph copy",
)
def simulate_road_closure(
    payload: RoadClosureSimulationRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        res = state.simulation_engine.simulate_road_closure(
            closed_roads=payload.closed_roads,
            origin_node=payload.origin_node,
            destination_node=payload.destination_node,
            scenario_name=payload.scenario_name,
            closure_reason=payload.closure_reason,
            objective=payload.objective,
            weights=_weights_from_schema(payload.weights),
            max_alternatives=payload.max_alternatives,
        )
        return res.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/simulations/incident",
    response_model=SimulationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate a hypothetical incident on an isolated graph copy",
)
def simulate_incident(
    payload: HypotheticalIncidentSimulationRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        res = state.simulation_engine.simulate_hypothetical_incident(
            category=payload.category,
            affected_roads=payload.affected_roads,
            origin_node=payload.origin_node,
            destination_node=payload.destination_node,
            scenario_name=payload.scenario_name,
            title=payload.title,
            description=payload.description,
            severity=payload.severity,
            road_blocked=payload.road_blocked,
            evidence=payload.evidence,
            objective=payload.objective,
            weights=_weights_from_schema(payload.weights),
            max_alternatives=payload.max_alternatives,
        )
        return res.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/simulations/congestion",
    response_model=SimulationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Simulate congestion changes on selected road segments",
)
def simulate_congestion(
    payload: CongestionSimulationRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        updates = [u.model_dump() for u in payload.congestion_updates]
        res = state.simulation_engine.simulate_congestion(
            congestion_updates=updates,
            origin_node=payload.origin_node,
            destination_node=payload.destination_node,
            scenario_name=payload.scenario_name,
            description=payload.description,
            objective=payload.objective,
            weights=_weights_from_schema(payload.weights),
            max_alternatives=payload.max_alternatives,
        )
        return res.to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.post(
    "/simulations/compare",
    summary="Compare multiple hypothetical scenarios against a common baseline",
)
def compare_simulations(
    payload: ScenarioComparisonRequest,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        scenarios = [s.model_dump() for s in payload.scenarios]
        return state.simulation_engine.compare_scenarios(
            origin_node=payload.origin_node,
            destination_node=payload.destination_node,
            scenarios=scenarios,
            objective=payload.objective,
            weights=_weights_from_schema(payload.weights),
            max_alternatives=payload.max_alternatives,
        )
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationResponse,
    summary="Retrieve a stored simulation result by ID",
)
def get_simulation(
    simulation_id: str,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        return state.simulation_engine.get_simulation(simulation_id).to_dict()
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


# ---------------------------------------------------------------------------
# India-Wide Geospatial & OpenStreetMap Endpoints (/api/geo/*)
# ---------------------------------------------------------------------------


@router.get(
    "/geo/india",
    summary="India-wide geographic overview, administrative hierarchy, and OSM source attribution",
)
def get_geo_india(state: UrbanFlowPlatformState = Depends(get_platform_state)) -> dict[str, Any]:
    cov = state.spatial_db.coverage_summary(state.road_network)
    return {
        "country": "India",
        "iso_code": "IN",
        "srid": 4326,
        "bounds": {
            "min_lon": INDIA_MIN_LON,
            "min_lat": INDIA_MIN_LAT,
            "max_lon": INDIA_MAX_LON,
            "max_lat": INDIA_MAX_LAT,
        },
        "administrative_hierarchy": cov["administrative_hierarchy"],
        "geofabrik_zones": GEOFABRIK_ZONES,
        "osm_source_url": OSM_SOURCE_URL,
        "osm_licence": OSM_LICENCE,
        "osm_licence_url": OSM_LICENCE_URL,
        "osm_attribution": OSM_ATTRIBUTION,
        "road_network_coverage": cov["road_network"],
    }


@router.get(
    "/geo/states",
    summary="List all 28 Indian states and 8 Union Territories",
)
def get_geo_states(
    territory_type: str | None = Query(default=None, description="Filter by 'state' or 'union_territory'"),
    zone: str | None = Query(default=None, description="Filter by Geofabrik zone (e.g. southern-zone)"),
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        items = state.spatial_db.list_states(territory_type=territory_type, zone=zone)
        return {
            "count": len(items),
            "states": items,
            "attribution": OSM_ATTRIBUTION,
        }
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/geo/districts",
    summary="Query Indian districts with optional state filter and pagination",
)
def get_geo_districts(
    state_filter: str | None = Query(default=None, alias="state", description="State/UT ISO code or name (e.g. KA, Karnataka)"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        if state_filter and find_state(state_filter) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown Indian state or Union Territory: '{state_filter}'",
            )
        items = state.spatial_db.list_districts(state=state_filter, limit=limit, offset=offset)
        return {
            "count": len(items),
            "state_filter": state_filter,
            "limit": limit,
            "offset": offset,
            "districts": items,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/geo/cities",
    summary="Query Indian cities and towns with optional district or state filter",
)
def get_geo_cities(
    district: str | None = Query(default=None, description="District ID or name (e.g. KA-BLR or Bengaluru Urban)"),
    state_filter: str | None = Query(default=None, alias="state", description="Optional state code or name"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        items = state.spatial_db.list_cities(district=district, state=state_filter, limit=limit, offset=offset)
        return {
            "count": len(items),
            "district_filter": district,
            "state_filter": state_filter,
            "limit": limit,
            "offset": offset,
            "cities": items,
        }
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/geo/roads",
    summary="Query road segments inside a bounding box as a GeoJSON FeatureCollection",
)
def get_geo_roads(
    bbox: str = Query(..., description="Bounding box 'min_lon,min_lat,max_lon,max_lat' in WGS84 (SRID 4326)"),
    highway: str | None = Query(default=None, description="Optional OSM highway class filter (e.g. primary, trunk)"),
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        parsed_bbox = BoundingBox.from_string(bbox)
        result = state.road_network.query_roads_in_bbox(
            parsed_bbox,
            highway=highway,
            limit=limit,
            offset=offset,
        )
        result["attribution"] = OSM_ATTRIBUTION
        result["licence"] = OSM_LICENCE
        return result
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/geo/roads/{road_id}",
    summary="Inspect a specific road segment's OSM attributes, geometry, and active incidents",
)
def get_geo_road_by_id(
    road_id: str,
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        seg = state.road_network.get_segment(road_id)
        u_node = state.road_network.get_node(seg.source)
        v_node = state.road_network.get_node(seg.target)
        active_incidents = state.incident_service.list_incidents(road_id=road_id, active_only=True)
        return {
            "road": seg.to_dict(),
            "geojson": seg.to_geojson_feature(),
            "source_node": u_node.to_dict(),
            "target_node": v_node.to_dict(),
            "active_incidents": [inc.to_dict() for inc in active_incidents],
            "attribution": OSM_ATTRIBUTION,
            "licence": OSM_LICENCE,
        }
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/geo/search",
    summary="Search across Indian states, districts, cities, intersections, and road segments",
)
def search_geo_locations(
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(default=25, ge=1, le=100),
    state: UrbanFlowPlatformState = Depends(get_platform_state),
) -> dict[str, Any]:
    try:
        if not q.strip():
            raise InvalidCoordinatesError("Search query 'q' must not be empty.")
        state.spatial_db.sync_from_road_network(state.road_network)
        return state.spatial_db.search_locations(q, limit=limit)
    except Exception as exc:
        raise _handle_domain_error(exc) from exc


@router.get(
    "/geo/coverage",
    summary="Inspect geographic database status, OSM import batches, and regional road coverage",
)
def get_geo_coverage(state: UrbanFlowPlatformState = Depends(get_platform_state)) -> dict[str, Any]:
    state.spatial_db.sync_from_road_network(state.road_network)
    return state.spatial_db.coverage_summary(state.road_network)


@router.get(
    "/health",
    summary="Platform health check including spatial database, road graph, and CV model status",
)
def get_health(state: UrbanFlowPlatformState = Depends(get_platform_state)) -> dict[str, Any]:
    from backend.config.vision_config import DEFAULT_MODEL_KEY, MODEL_REGISTRY

    models_status = {
        key: {
            "weights_path": str(spec.weights_path),
            "weights_present": spec.weights_path.exists(),
            "licence": spec.license,
        }
        for key, spec in MODEL_REGISTRY.items()
    }
    return {
        "status": "ok",
        "service": "UrbanFlow AI",
        "database": state.spatial_db.pool.health_check(),
        "road_network": {
            "city": state.road_network.city,
            "node_count": len(state.road_network.nodes),
            "segment_count": len(state.road_network.segments),
            "regional_cache_size": state.road_network.regional_cache_size,
        },
        "cv_models": {
            "default_model": DEFAULT_MODEL_KEY,
            "models": models_status,
        },
    }


def create_app(state: UrbanFlowPlatformState | None = None) -> FastAPI:
    app = FastAPI(
        title="UrbanFlow AI — Smart Traffic, Geospatial & Incident Intelligence API",
        version="3.0.0",
        description=(
            "India-wide smart traffic analytics, OpenStreetMap geospatial backend, "
            "incident intelligence, incident-aware routing, and isolated traffic simulation API."
        ),
    )
    if state is not None:
        app.dependency_overrides[get_platform_state] = lambda: state
    app.include_router(router)
    return app


app = create_app()
