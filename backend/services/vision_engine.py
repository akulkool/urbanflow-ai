"""Unified Vision & Traffic Intelligence Engine for UrbanFlow AI.

Provides a single runtime container holding the road network, incident intelligence
service, smart routing engine, and traffic simulation engine, while lazy-loading
the heavy computer-vision model (`VehicleDetector`) only when CV inference is requested.
"""

from __future__ import annotations

import threading
from typing import Any

from pathlib import Path

from backend.services.incident_manager import IncidentIntelligenceService
from backend.services.osm_ingestor import OSMIngestionPipeline
from backend.services.road_network import RoadNetwork, create_bengaluru_demo_network
from backend.services.routing_engine import SmartRoutingEngine
from backend.services.simulation_engine import TrafficSimulationEngine
from backend.services.spatial_db import SpatialDatabase


class UrbanFlowPlatformState:
    """Thread-safe container for the road network, spatial DB, OSM ingestor, incidents, routing, and simulations."""

    def __init__(
        self,
        road_network: RoadNetwork | None = None,
        model_name: str | None = None,
        spatial_db: SpatialDatabase | None = None,
        database_url: str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.road_network: RoadNetwork = road_network or create_bengaluru_demo_network()
        self.spatial_db: SpatialDatabase = spatial_db or SpatialDatabase(database_url=database_url)
        self.spatial_db.sync_from_road_network(self.road_network)
        self.osm_ingestor = OSMIngestionPipeline(
            road_network=self.road_network,
            spatial_db=self.spatial_db,
        )
        self.incident_service = IncidentIntelligenceService(
            road_network=self.road_network,
            spatial_db=self.spatial_db,
        )
        self.routing_engine = SmartRoutingEngine(
            road_network=self.road_network,
            incident_service=self.incident_service,
        )
        self.simulation_engine = TrafficSimulationEngine(
            road_network=self.road_network,
            incident_service=self.incident_service,
            routing_engine=self.routing_engine,
        )
        self.model_name = model_name
        self._detector: Any = None

    def get_detector(self, model_name: str | None = None) -> Any:
        """Lazy-load and reuse the VehicleDetector instance (supports VehicleNet-Y26m or YOLO26m)."""
        with self._lock:
            target = model_name or self.model_name
            if self._detector is None or (target is not None and self._detector.model_key != target):
                from backend.services.detector import VehicleDetector

                self._detector = VehicleDetector(model_name=target)
            return self._detector


_DEFAULT_STATE: UrbanFlowPlatformState | None = None
_STATE_LOCK = threading.Lock()


def get_platform_state() -> UrbanFlowPlatformState:
    global _DEFAULT_STATE
    with _STATE_LOCK:
        if _DEFAULT_STATE is None:
            _DEFAULT_STATE = UrbanFlowPlatformState()
        return _DEFAULT_STATE


def set_platform_state(state: UrbanFlowPlatformState) -> None:
    global _DEFAULT_STATE
    with _STATE_LOCK:
        _DEFAULT_STATE = state
