"""Synthetic Bengaluru demonstration road network, India-wide OSM road attributes,
and directed NetworkX graph storage for UrbanFlow AI.

Supports:
- Full OpenStreetMap road attributes (osm_way_id, highway, surface, maxspeed_kmh,
  oneway='yes'|'no'|'reverse', access, bridge, tunnel, geometry coordinates, GeoJSON).
- Administrative hierarchy links (state_code, district_id, city_id).
- Strict topological connectivity via explicit intersection nodes (never connects roads
  merely because their geometries pass close to one another).
- Regional bounding-box graph extraction with LRU caching so nationwide graphs never need
  to be loaded into memory per request.
- Spatial nearest-road segment matching with distance and directional alignment checks.
"""

from __future__ import annotations

import copy
import math
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

import networkx as nx


class RoadNetworkError(ValueError):
    """Base error for road network operations."""


class NodeNotFoundError(RoadNetworkError):
    """Raised when a road intersection/node ID does not exist."""


class RoadSegmentNotFoundError(RoadNetworkError):
    """Raised when a road segment ID does not exist."""


class InvalidCoordinatesError(RoadNetworkError):
    """Raised when geographic coordinates are missing or invalid."""


class InvalidBoundingBoxError(RoadNetworkError):
    """Raised when a geographic bounding box is malformed or exceeds query limits."""


class CoverageUnavailableError(InvalidCoordinatesError):
    """Raised when requested coordinates or bounds have no imported geographic road coverage."""


RESTRICTED_ACCESS_VALUES: frozenset[str] = frozenset({"no", "private"})

SUPPORTED_OSM_HIGHWAY_TYPES: frozenset[str] = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
        "road",
    }
)

DEFAULT_HIGHWAY_MAXSPEED_KMH: dict[str, float] = {
    "motorway": 100.0,
    "motorway_link": 60.0,
    "trunk": 80.0,
    "trunk_link": 50.0,
    "primary": 60.0,
    "primary_link": 45.0,
    "secondary": 50.0,
    "secondary_link": 40.0,
    "tertiary": 40.0,
    "tertiary_link": 35.0,
    "unclassified": 40.0,
    "residential": 30.0,
    "living_street": 20.0,
    "service": 20.0,
    "road": 40.0,
}


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if (
            not isinstance(self.lat, (int, float))
            or isinstance(self.lat, bool)
            or not isinstance(self.lon, (int, float))
            or isinstance(self.lon, bool)
            or not math.isfinite(self.lat)
            or not math.isfinite(self.lon)
            or not (-90.0 <= float(self.lat) <= 90.0)
            or not (-180.0 <= float(self.lon) <= 180.0)
        ):
            raise InvalidCoordinatesError(f"Invalid geographic coordinates: ({self.lat}, {self.lon})")
        object.__setattr__(self, "lat", float(self.lat))
        object.__setattr__(self, "lon", float(self.lon))

    def to_dict(self) -> dict[str, float]:
        return {"lat": self.lat, "lon": self.lon}


@dataclass(frozen=True)
class BoundingBox:
    """Geographic bounding box in WGS84 (min_lon, min_lat, max_lon, max_lat)."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    def __post_init__(self) -> None:
        vals = (self.min_lon, self.min_lat, self.max_lon, self.max_lat)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vals):
            raise InvalidBoundingBoxError("Bounding box coordinates must be four finite numbers.")
        if not (-180.0 <= self.min_lon <= 180.0 and -180.0 <= self.max_lon <= 180.0):
            raise InvalidBoundingBoxError("Longitude values in bounding box must be within [-180, 180].")
        if not (-90.0 <= self.min_lat <= 90.0 and -90.0 <= self.max_lat <= 90.0):
            raise InvalidBoundingBoxError("Latitude values in bounding box must be within [-90, 90].")
        if self.min_lon >= self.max_lon or self.min_lat >= self.max_lat:
            raise InvalidBoundingBoxError(
                f"Bounding box min must be strictly less than max: "
                f"({self.min_lon}, {self.min_lat}, {self.max_lon}, {self.max_lat})"
            )
        object.__setattr__(self, "min_lon", float(self.min_lon))
        object.__setattr__(self, "min_lat", float(self.min_lat))
        object.__setattr__(self, "max_lon", float(self.max_lon))
        object.__setattr__(self, "max_lat", float(self.max_lat))

    @classmethod
    def from_string(cls, bbox_str: str, max_span_degrees: float = 10.0) -> "BoundingBox":
        if not isinstance(bbox_str, str) or not bbox_str.strip():
            raise InvalidBoundingBoxError("Bounding box string cannot be empty. Expected 'min_lon,min_lat,max_lon,max_lat'.")
        parts = [p.strip() for p in bbox_str.split(",")]
        if len(parts) != 4:
            raise InvalidBoundingBoxError(f"Expected 4 comma-separated values for bbox, got {len(parts)}.")
        try:
            b = cls(float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError as exc:
            raise InvalidBoundingBoxError(f"Invalid numeric values in bbox '{bbox_str}': {exc}") from exc
        if (b.max_lon - b.min_lon) > max_span_degrees or (b.max_lat - b.min_lat) > max_span_degrees:
            raise InvalidBoundingBoxError(
                f"Bounding box span exceeds maximum allowed regional query span of {max_span_degrees} degrees. "
                "Request a smaller regional bounding box instead of nationwide geometry."
            )
        return b

    def contains_point(self, lat: float, lon: float) -> bool:
        return self.min_lon <= lon <= self.max_lon and self.min_lat <= lat <= self.max_lat

    def intersects(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> bool:
        return not (max_lon < self.min_lon or min_lon > self.max_lon or max_lat < self.min_lat or min_lat > self.max_lat)

    def to_list(self) -> list[float]:
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]


def haversine_km(p1: GeoPoint, p2: GeoPoint) -> float:
    """Great-circle distance in kilometres between two GeoPoints."""
    r = 6371.0
    lat1, lon1 = math.radians(p1.lat), math.radians(p1.lon)
    lat2, lon2 = math.radians(p2.lat), math.radians(p2.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def bearing_degrees(p1: GeoPoint, p2: GeoPoint) -> float:
    """Initial compass bearing in degrees [0, 360) from p1 to p2."""
    lat1, lon1 = math.radians(p1.lat), math.radians(p1.lon)
    lat2, lon2 = math.radians(p2.lat), math.radians(p2.lon)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def point_to_segment_distance_km(pt: GeoPoint, a: GeoPoint, b: GeoPoint) -> tuple[float, GeoPoint]:
    """Shortest distance in km from GeoPoint `pt` to line segment `a -> b`, plus closest point."""
    if a.lat == b.lat and a.lon == b.lon:
        return haversine_km(pt, a), a
    cos_lat = math.cos(math.radians((a.lat + b.lat + pt.lat) / 3.0))
    ax, ay = a.lon * cos_lat, a.lat
    bx, by = b.lon * cos_lat, b.lat
    px, py = pt.lon * cos_lat, pt.lat
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom)) if denom > 0 else 0.0
    proj_lat = a.lat + t * (b.lat - a.lat)
    proj_lon = a.lon + t * (b.lon - a.lon)
    proj = GeoPoint(proj_lat, proj_lon)
    return haversine_km(pt, proj), proj


@dataclass
class RoadNode:
    id: str
    name: str
    lat: float
    lon: float
    region: str
    junction_type: str = "signalized_intersection"
    is_synthetic: bool = True
    osm_node_id: int | None = None
    state_code: str | None = "KA"
    district_id: str | None = "KA_BLR_U"
    city_id: str | None = "city_bengaluru"
    osm_tags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        pt = GeoPoint(self.lat, self.lon)
        self.lat, self.lon = pt.lat, pt.lon

    @property
    def point(self) -> GeoPoint:
        return GeoPoint(self.lat, self.lon)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ONEWAY_VALUES = {"yes", "no", "reverse"}


@dataclass
class RoadSegment:
    id: str
    name: str
    source: str
    target: str
    distance_km: float
    region: str
    road_type: str = "arterial"
    lanes: int = 2
    congestion_level: str = "LOW"  # LOW, MODERATE, HIGH, SEVERE
    congestion_penalty: float = 0.1  # normalized [0.0, 1.0+]
    closed: bool = False
    closure_reason: str | None = None
    bidirectional: bool = True
    is_synthetic: bool = True
    # Extended OpenStreetMap & India geospatial attributes
    osm_way_id: int | None = None
    highway: str | None = None
    surface: str | None = "asphalt"
    maxspeed_kmh: float | None = None
    oneway: str | None = None  # 'yes', 'no', 'reverse'
    access: str = "yes"
    is_bridge: bool = False
    is_tunnel: bool = False
    state_code: str | None = "KA"
    district_id: str | None = "KA_BLR_U"
    city_id: str | None = "city_bengaluru"
    geometry: list[tuple[float, float]] = field(default_factory=list)  # list of (lon, lat) coordinates
    osm_tags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.distance_km, (int, float)) or not math.isfinite(self.distance_km) or self.distance_km <= 0:
            raise RoadNetworkError(f"Road segment '{self.id}' distance_km must be positive.")
        if not isinstance(self.congestion_penalty, (int, float)) or not math.isfinite(self.congestion_penalty) or self.congestion_penalty < 0:
            raise RoadNetworkError(f"Road segment '{self.id}' congestion_penalty must be non-negative.")
        self.distance_km = float(self.distance_km)
        self.congestion_penalty = float(self.congestion_penalty)
        if self.highway is None:
            self.highway = self.road_type
        if self.oneway is None:
            self.oneway = "no" if self.bidirectional else "yes"
        else:
            ow = str(self.oneway).lower().strip()
            if ow in {"1", "true", "yes"}:
                self.oneway = "yes"
                self.bidirectional = False
            elif ow in {"-1", "reverse"}:
                self.oneway = "reverse"
                self.bidirectional = False
            elif ow in {"0", "false", "no"}:
                self.oneway = "no"
                self.bidirectional = True
            else:
                raise RoadNetworkError(f"Invalid oneway value '{self.oneway}' on road '{self.id}'")

    def geojson_geometry(
        self,
        source_node: RoadNode | None = None,
        target_node: RoadNode | None = None,
    ) -> dict[str, Any]:
        """Return standard GeoJSON LineString geometry ([lon, lat] coordinate order)."""
        if self.geometry and len(self.geometry) >= 2:
            coords = [[float(lon), float(lat)] for lon, lat in self.geometry]
        elif source_node is not None and target_node is not None:
            coords = [[source_node.lon, source_node.lat], [target_node.lon, target_node.lat]]
        else:
            coords = []
        return {"type": "LineString", "coordinates": coords}

    def to_geojson_feature(
        self,
        source_node: RoadNode | None = None,
        target_node: RoadNode | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": self.geojson_geometry(source_node, target_node),
            "properties": {
                "id": self.id,
                "road_id": self.id,
                "osm_way_id": self.osm_way_id,
                "name": self.name,
                "source": self.source,
                "target": self.target,
                "distance_km": self.distance_km,
                "region": self.region,
                "road_type": self.road_type,
                "highway": self.highway,
                "lanes": self.lanes,
                "surface": self.surface,
                "maxspeed_kmh": self.maxspeed_kmh,
                "oneway": self.oneway,
                "bidirectional": self.bidirectional,
                "access": self.access,
                "is_bridge": self.is_bridge,
                "is_tunnel": self.is_tunnel,
                "congestion_level": self.congestion_level,
                "congestion_penalty": self.congestion_penalty,
                "closed": self.closed,
                "closure_reason": self.closure_reason,
                "state_code": self.state_code,
                "district_id": self.district_id,
                "city_id": self.city_id,
                "is_synthetic": self.is_synthetic,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["geometry"] = [[float(lon), float(lat)] for lon, lat in self.geometry]
        return d


CONGESTION_LEVEL_PENALTY: dict[str, float] = {
    "LOW": 0.10,
    "MODERATE": 0.35,
    "HIGH": 0.70,
    "SEVERE": 1.00,
}


def penalty_for_congestion_level(level: str) -> float:
    key = level.upper().strip()
    if key not in CONGESTION_LEVEL_PENALTY:
        raise RoadNetworkError(f"Unsupported congestion level '{level}'. Expected {list(CONGESTION_LEVEL_PENALTY)}")
    return CONGESTION_LEVEL_PENALTY[key]


def level_for_congestion_penalty(penalty: float) -> str:
    if penalty >= 0.85:
        return "SEVERE"
    if penalty >= 0.55:
        return "HIGH"
    if penalty >= 0.25:
        return "MODERATE"
    return "LOW"


class RoadNetwork:
    """Thread-safe directed road network backed by NetworkX DiGraph.

    - Handles one-way ('yes', 'reverse') and bidirectional ('no') roads accurately.
    - Supports instant isolated cloning (`clone()`) for what-if simulations.
    - Supports regional bounding-box subgraph extraction with LRU caching so nationwide
      data is never loaded all at once for regional queries.
    """

    def __init__(
        self,
        nodes: Iterable[RoadNode],
        segments: Iterable[RoadSegment],
        city: str = "Bengaluru (Synthetic Demo)",
        region_cache_size: int = 32,
    ) -> None:
        self._lock = threading.RLock()
        self.city = city
        self.is_synthetic = True
        self._nodes: dict[str, RoadNode] = {}
        self._segments: dict[str, RoadSegment] = {}
        self._pair_to_segment: dict[tuple[str, str], str] = {}
        self._graph: nx.DiGraph = nx.DiGraph()
        self._region_cache_size = max(4, int(region_cache_size))
        self._regional_cache: OrderedDict[tuple[float, float, float, float], "RoadNetwork"] = OrderedDict()

        for node in nodes:
            self.add_node(node)

        for seg in segments:
            self.add_segment(seg)

    def _invalidate_cache(self) -> None:
        self._regional_cache.clear()

    def add_node(self, node: RoadNode, allow_upsert: bool = False) -> RoadNode:
        with self._lock:
            if node.id in self._nodes and not allow_upsert:
                raise RoadNetworkError(f"Duplicate node ID: {node.id}")
            copied = copy.deepcopy(node)
            self._nodes[copied.id] = copied
            self._graph.add_node(copied.id, data=copied)
            if not copied.is_synthetic:
                self.is_synthetic = False
            self._invalidate_cache()
            return copy.deepcopy(copied)

    def add_segment(self, seg: RoadSegment, allow_upsert: bool = False) -> RoadSegment:
        with self._lock:
            if seg.id in self._segments and not allow_upsert:
                raise RoadNetworkError(f"Duplicate road segment ID: {seg.id}")
            if seg.source not in self._nodes:
                raise NodeNotFoundError(f"Unknown source node '{seg.source}' for road '{seg.id}'")
            if seg.target not in self._nodes:
                raise NodeNotFoundError(f"Unknown target node '{seg.target}' for road '{seg.id}'")

            copied = copy.deepcopy(seg)
            u_node = self._nodes[copied.source]
            v_node = self._nodes[copied.target]
            if not copied.geometry:
                copied.geometry = [(u_node.lon, u_node.lat), (v_node.lon, v_node.lat)]

            # Remove prior directed edges if upserting
            if copied.id in self._segments:
                old = self._segments[copied.id]
                self._pair_to_segment.pop((old.source, old.target), None)
                self._pair_to_segment.pop((old.target, old.source), None)
                if self._graph.has_edge(old.source, old.target):
                    self._graph.remove_edge(old.source, old.target)
                if self._graph.has_edge(old.target, old.source):
                    self._graph.remove_edge(old.target, old.source)

            self._segments[copied.id] = copied
            # Respect access restrictions and one-way directionality
            if copied.access not in {"no", "private"}:
                if copied.oneway == "reverse":
                    self._graph.add_edge(copied.target, copied.source, segment_id=copied.id)
                    self._pair_to_segment[(copied.target, copied.source)] = copied.id
                elif copied.oneway == "yes" or not copied.bidirectional:
                    self._graph.add_edge(copied.source, copied.target, segment_id=copied.id)
                    self._pair_to_segment[(copied.source, copied.target)] = copied.id
                else:
                    self._graph.add_edge(copied.source, copied.target, segment_id=copied.id)
                    self._pair_to_segment[(copied.source, copied.target)] = copied.id
                    self._graph.add_edge(copied.target, copied.source, segment_id=copied.id)
                    self._pair_to_segment[(copied.target, copied.source)] = copied.id

            if not copied.is_synthetic:
                self.is_synthetic = False
            self._invalidate_cache()
            return copy.deepcopy(copied)

    def clone(self) -> "RoadNetwork":
        """Return a deep, isolated copy of this road network for simulation."""
        with self._lock:
            cloned = RoadNetwork(
                nodes=[copy.deepcopy(n) for n in self._nodes.values()],
                segments=[copy.deepcopy(s) for s in self._segments.values()],
                city=self.city,
                region_cache_size=self._region_cache_size,
            )
            cloned.is_synthetic = self.is_synthetic
            return cloned

    def extract_regional_network(self, bbox: BoundingBox) -> "RoadNetwork":
        """Extract a regional RoadNetwork within `bbox` (cached with LRU eviction)."""
        key = (round(bbox.min_lon, 4), round(bbox.min_lat, 4), round(bbox.max_lon, 4), round(bbox.max_lat, 4))
        with self._lock:
            if key in self._regional_cache:
                self._regional_cache.move_to_end(key)
                return self._regional_cache[key].clone()

            matched_segments: list[RoadSegment] = []
            needed_nodes: set[str] = set()
            for seg in self._segments.values():
                coords = seg.geometry or [
                    (self._nodes[seg.source].lon, self._nodes[seg.source].lat),
                    (self._nodes[seg.target].lon, self._nodes[seg.target].lat),
                ]
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                if bbox.intersects(min(lons), min(lats), max(lons), max(lats)):
                    matched_segments.append(copy.deepcopy(seg))
                    needed_nodes.add(seg.source)
                    needed_nodes.add(seg.target)

            for nid, node in self._nodes.items():
                if bbox.contains_point(node.lat, node.lon):
                    needed_nodes.add(nid)

            sub_nodes = [copy.deepcopy(self._nodes[nid]) for nid in sorted(needed_nodes)]
            sub_net = RoadNetwork(
                nodes=sub_nodes,
                segments=matched_segments,
                city=f"{self.city} [Regional Extract {key}]",
            )
            self._regional_cache[key] = sub_net
            while len(self._regional_cache) > self._region_cache_size:
                self._regional_cache.popitem(last=False)
            return sub_net.clone()

    @property
    def regional_cache_size(self) -> int:
        with self._lock:
            return len(self._regional_cache)

    @property
    def nodes(self) -> dict[str, RoadNode]:
        with self._lock:
            return {k: copy.deepcopy(v) for k, v in self._nodes.items()}

    @property
    def segments(self) -> dict[str, RoadSegment]:
        with self._lock:
            return {k: copy.deepcopy(v) for k, v in self._segments.items()}

    def get_node(self, node_id: str) -> RoadNode:
        with self._lock:
            if node_id not in self._nodes:
                raise NodeNotFoundError(f"Road node not found: '{node_id}'")
            return copy.deepcopy(self._nodes[node_id])

    def get_segment(self, segment_id: str) -> RoadSegment:
        with self._lock:
            if segment_id not in self._segments:
                raise RoadSegmentNotFoundError(f"Road segment not found: '{segment_id}'")
            return copy.deepcopy(self._segments[segment_id])

    def get_segment_geojson(self, segment_id: str) -> dict[str, Any]:
        with self._lock:
            if segment_id not in self._segments:
                raise RoadSegmentNotFoundError(f"Road segment not found: '{segment_id}'")
            seg = self._segments[segment_id]
            return seg.to_geojson_feature(self._nodes.get(seg.source), self._nodes.get(seg.target))

    def has_node(self, node_id: str) -> bool:
        with self._lock:
            return node_id in self._nodes

    def has_segment(self, segment_id: str) -> bool:
        with self._lock:
            return segment_id in self._segments

    def segment_between(self, u: str, v: str) -> RoadSegment:
        with self._lock:
            seg_id = self._pair_to_segment.get((u, v))
            if seg_id is None:
                raise RoadSegmentNotFoundError(f"No directed road segment connecting '{u}' -> '{v}'")
            return copy.deepcopy(self._segments[seg_id])

    def set_road_closed(self, segment_id: str, closed: bool = True, reason: str | None = None) -> RoadSegment:
        with self._lock:
            if segment_id not in self._segments:
                raise RoadSegmentNotFoundError(f"Road segment not found: '{segment_id}'")
            seg = self._segments[segment_id]
            seg.closed = bool(closed)
            seg.closure_reason = reason if closed else None
            self._invalidate_cache()
            return copy.deepcopy(seg)

    def set_road_congestion(
        self,
        segment_id: str,
        congestion_level: str | None = None,
        congestion_penalty: float | None = None,
    ) -> RoadSegment:
        with self._lock:
            if segment_id not in self._segments:
                raise RoadSegmentNotFoundError(f"Road segment not found: '{segment_id}'")
            seg = self._segments[segment_id]
            if congestion_penalty is not None:
                if not isinstance(congestion_penalty, (int, float)) or not math.isfinite(congestion_penalty) or congestion_penalty < 0:
                    raise RoadNetworkError("congestion_penalty must be a non-negative finite number.")
                seg.congestion_penalty = float(congestion_penalty)
                seg.congestion_level = (
                    congestion_level.upper().strip()
                    if congestion_level is not None
                    else level_for_congestion_penalty(seg.congestion_penalty)
                )
            elif congestion_level is not None:
                seg.congestion_penalty = penalty_for_congestion_level(congestion_level)
                seg.congestion_level = congestion_level.upper().strip()
            else:
                raise RoadNetworkError("Provide congestion_level or congestion_penalty.")
            self._invalidate_cache()
            return copy.deepcopy(seg)

    def nearest_node(self, point: GeoPoint, max_distance_km: float = 25.0) -> RoadNode:
        """Resolve a geographic point to the nearest road intersection node."""
        if not isinstance(point, GeoPoint):
            point = GeoPoint(point.lat, point.lon)
        with self._lock:
            best_node: RoadNode | None = None
            best_dist = float("inf")
            for node in self._nodes.values():
                d = haversine_km(point, node.point)
                if d < best_dist:
                    best_dist = d
                    best_node = node
            if best_node is None or best_dist > max_distance_km:
                raise InvalidCoordinatesError(
                    f"Coordinates ({point.lat}, {point.lon}) are outside the road network "
                    f"(nearest node is {best_dist:.2f} km away, max {max_distance_km} km)."
                )
            return copy.deepcopy(best_node)

    def match_nearest_road_segment(
        self,
        point: GeoPoint,
        max_distance_km: float = 2.0,
        travel_bearing_deg: float | None = None,
        bearing_tolerance_deg: float = 75.0,
    ) -> tuple[RoadSegment, float]:
        """Spatially associate a coordinate with the nearest suitable road segment,
        respecting distance limits and optional directional travel bearing on one-way roads."""
        if not isinstance(point, GeoPoint):
            point = GeoPoint(point.lat, point.lon)
        with self._lock:
            best_seg: RoadSegment | None = None
            best_dist = float("inf")
            for seg in self._segments.values():
                if seg.access in {"no", "private"}:
                    continue
                coords = seg.geometry or [
                    (self._nodes[seg.source].lon, self._nodes[seg.source].lat),
                    (self._nodes[seg.target].lon, self._nodes[seg.target].lat),
                ]
                for (lon1, lat1), (lon2, lat2) in zip(coords[:-1], coords[1:]):
                    p1, p2 = GeoPoint(lat1, lon1), GeoPoint(lat2, lon2)
                    d, _ = point_to_segment_distance_km(point, p1, p2)
                    if d > max_distance_km or d >= best_dist:
                        continue
                    if travel_bearing_deg is not None:
                        fwd_b = bearing_degrees(p1, p2)
                        rev_b = (fwd_b + 180.0) % 360.0
                        allowed_bearings: list[float] = []
                        if seg.oneway == "yes":
                            allowed_bearings = [fwd_b]
                        elif seg.oneway == "reverse":
                            allowed_bearings = [rev_b]
                        else:
                            allowed_bearings = [fwd_b, rev_b]
                        if not any(
                            min((travel_bearing_deg - ab) % 360.0, (ab - travel_bearing_deg) % 360.0) <= bearing_tolerance_deg
                            for ab in allowed_bearings
                        ):
                            continue
                    best_dist = d
                    best_seg = seg

            if best_seg is None:
                raise RoadSegmentNotFoundError(
                    f"No matching road segment within {max_distance_km} km of ({point.lat}, {point.lon})."
                )
            return copy.deepcopy(best_seg), round(best_dist, 4)

    def query_roads_in_bbox(
        self,
        bbox: BoundingBox,
        highway: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return a GeoJSON FeatureCollection of road segments intersecting `bbox`."""
        if limit < 1 or limit > 1000:
            raise RoadNetworkError("limit must be between 1 and 1000.")
        if offset < 0:
            raise RoadNetworkError("offset must be non-negative.")
        hw_filter = highway.lower().strip() if highway else None

        with self._lock:
            matched: list[RoadSegment] = []
            for seg in self._segments.values():
                if hw_filter and (seg.highway or "").lower() != hw_filter and seg.road_type.lower() != hw_filter:
                    continue
                coords = seg.geometry or [
                    (self._nodes[seg.source].lon, self._nodes[seg.source].lat),
                    (self._nodes[seg.target].lon, self._nodes[seg.target].lat),
                ]
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                if bbox.intersects(min(lons), min(lats), max(lons), max(lats)):
                    matched.append(seg)

            total = len(matched)
            sliced = matched[offset : offset + limit]
            features = [
                s.to_geojson_feature(self._nodes.get(s.source), self._nodes.get(s.target))
                for s in sliced
            ]
            return {
                "type": "FeatureCollection",
                "bbox": bbox.to_list(),
                "total_matched": total,
                "limit": limit,
                "offset": offset,
                "returned": len(features),
                "returned_count": len(features),
                "features": features,
            }

    def segments_in_region(self, region: str) -> list[RoadSegment]:
        with self._lock:
            return [copy.deepcopy(s) for s in self._segments.values() if s.region == region]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "city": self.city,
                "is_synthetic": self.is_synthetic,
                "node_count": len(self._nodes),
                "segment_count": len(self._segments),
                "nodes": [n.to_dict() for n in self._nodes.values()],
                "segments": [s.to_dict() for s in self._segments.values()],
            }


def create_bengaluru_demo_network() -> RoadNetwork:
    """Create the deterministic synthetic Bengaluru road network used as default."""
    nodes = [
        RoadNode("mg_road", "MG Road Junction", 12.9756, 77.6066, "cbd", "signalized_intersection"),
        RoadNode("indiranagar", "Indiranagar 100ft Junction", 12.9784, 77.6408, "east_core", "signalized_intersection"),
        RoadNode("koramangala", "Koramangala Sony World", 12.9352, 77.6245, "south_east", "signalized_intersection"),
        RoadNode("silk_board", "Silk Board Flyover Junction", 12.9176, 77.6233, "orr_south", "multi_level_flyover"),
        RoadNode("marathahalli", "Marathahalli Bridge", 12.9569, 77.7011, "orr_east", "grade_separated_junction"),
        RoadNode("whitefield", "Whitefield ITPL Main", 12.9698, 77.7499, "it_corridor", "signalized_intersection"),
        RoadNode("bellandur", "Bellandur ORR Junction", 12.9304, 77.6784, "orr_east", "signalized_intersection"),
        RoadNode("electronic_city", "Electronic City Phase 1", 12.8452, 77.6602, "hosur_corridor", "toll_interchange"),
        RoadNode("hebbal", "Hebbal Flyover", 13.0358, 77.5970, "north_corridor", "cloverleaf_flyover"),
        RoadNode("kr_puram", "KR Puram Hanging Bridge", 13.0012, 77.6951, "old_madras_corridor", "cable_bridge_junction"),
        RoadNode("jayanagar", "Jayanagar 4th Block", 12.9250, 77.5838, "south_core", "roundabout"),
    ]
    segments = [
        RoadSegment("seg_mg_indira", "MG Road - Indiranagar Corridor", "mg_road", "indiranagar", 4.2, "east_core", "arterial", 3, "MODERATE", 0.35),
        RoadSegment("seg_indira_mara", "HAL Old Airport Road", "indiranagar", "marathahalli", 7.1, "orr_east", "arterial", 3, "HIGH", 0.70),
        RoadSegment("seg_mara_white", "Varthur - Whitefield Main Road", "marathahalli", "whitefield", 5.8, "it_corridor", "arterial", 2, "HIGH", 0.70),
        RoadSegment("seg_mg_kora", "Hosmat - Adugodi Link Road", "mg_road", "koramangala", 5.4, "south_east", "arterial", 2, "MODERATE", 0.35),
        RoadSegment("seg_indira_kora", "Intermediate Ring Road (IRR)", "indiranagar", "koramangala", 4.9, "south_east", "ring_road", 3, "MODERATE", 0.35),
        RoadSegment("seg_kora_silk", "Koramangala - Silk Board Main", "koramangala", "silk_board", 2.8, "orr_south", "arterial", 3, "HIGH", 0.70),
        RoadSegment("seg_silk_bell", "Outer Ring Road (Silk Board - Bellandur)", "silk_board", "bellandur", 6.4, "orr_east", "ring_road", 4, "HIGH", 0.70, is_bridge=True),
        RoadSegment("seg_bell_mara", "Outer Ring Road (Bellandur - Marathahalli)", "bellandur", "marathahalli", 4.3, "orr_east", "ring_road", 4, "MODERATE", 0.35),
        RoadSegment("seg_kora_bell", "Sarjapur Road Connector", "koramangala", "bellandur", 6.2, "south_east", "arterial", 2, "LOW", 0.10),
        RoadSegment("seg_silk_ecity", "Hosur Elevated Expressway", "silk_board", "electronic_city", 9.5, "hosur_corridor", "expressway", 4, "MODERATE", 0.35, is_bridge=True),
        RoadSegment("seg_bell_ecity", "Hosa Road - Electronic City Link", "bellandur", "electronic_city", 11.2, "hosur_corridor", "secondary", 2, "LOW", 0.10),
        RoadSegment("seg_mg_hebbal", "Bellary Road (MG Road - Hebbal)", "mg_road", "hebbal", 7.8, "north_corridor", "arterial", 4, "MODERATE", 0.35),
        RoadSegment("seg_hebbal_krp", "Outer Ring Road North (Hebbal - KR Puram)", "hebbal", "kr_puram", 11.8, "north_corridor", "ring_road", 3, "MODERATE", 0.35),
        RoadSegment("seg_indira_krp", "Old Madras Road", "indiranagar", "kr_puram", 6.5, "old_madras_corridor", "highway", 4, "MODERATE", 0.35),
        RoadSegment("seg_krp_mara", "Outer Ring Road (KR Puram - Marathahalli)", "kr_puram", "marathahalli", 5.9, "orr_east", "ring_road", 4, "HIGH", 0.70),
        RoadSegment("seg_krp_white", "Hoodi - ITPL Road", "kr_puram", "whitefield", 7.4, "it_corridor", "arterial", 3, "LOW", 0.10),
        RoadSegment("seg_mg_jaya", "Lalbagh Road", "mg_road", "jayanagar", 6.0, "south_core", "arterial", 2, "LOW", 0.10),
        RoadSegment("seg_jaya_silk", "BTM Layout Main Road", "jayanagar", "silk_board", 4.5, "orr_south", "arterial", 3, "MODERATE", 0.35),
        RoadSegment("seg_jaya_kora", "Diary Circle Link Road", "jayanagar", "koramangala", 4.1, "south_core", "secondary", 2, "LOW", 0.10),
    ]
    return RoadNetwork(nodes=nodes, segments=segments)
