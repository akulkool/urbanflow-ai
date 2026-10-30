"""Spatial Database & Storage Layer for UrbanFlow AI.

Provides:
1. Connection pooling and automatic backend selection (`DATABASE_URL` for PostgreSQL/PostGIS
   in production, or SQLite with spatial BBox indexes for zero-config local/test runs).
2. Automatic seeding of all 28 Indian States and 8 Union Territories, districts, and cities/towns.
3. Persistence for OSM road segments, intersections, and `osm_import_batches` metadata.
4. Spatial queries (bounding-box GeoJSON queries, location search, administrative hierarchy
   filtering, and coverage reporting).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, LifoQueue
from typing import Any, Iterable

from backend.services.india_geo_registry import (
    GEOFABRIK_INDIA_INDEX_URL,
    GEOFABRIK_ZONES,
    INDIA_CITIES,
    INDIA_DISTRICTS,
    INDIA_STATES_AND_UTS,
    OSM_ATTRIBUTION,
    OSM_LICENCE,
)
from backend.services.road_network import (
    BoundingBox,
    RoadNetwork,
    RoadNetworkError,
    RoadNode,
    RoadSegment,
)

logger = logging.getLogger(__name__)

DATABASE_URL_ENV = "DATABASE_URL"


class SpatialDatabaseError(RuntimeError):
    """Raised on spatial database errors."""


class SQLiteConnectionPool:
    """Thread-safe connection pool for SQLite (supports `:memory:` via shared URI or file DB)."""

    def __init__(self, database_path: str = ":memory:", pool_size: int = 5) -> None:
        self.database_path = database_path
        self.pool_size = max(1, int(pool_size))
        self._lock = threading.RLock()
        self._pool: LifoQueue[sqlite3.Connection] = LifoQueue(maxsize=self.pool_size)
        self._is_memory = database_path == ":memory:"
        self._shared_uri = f"file:urbanflow_mem_{id(self)}?mode=memory&cache=shared"
        # Keep one anchor connection open so shared in-memory DB persists across checkouts
        self._anchor_conn = self._create_connection()

    def _create_connection(self) -> sqlite3.Connection:
        if self._is_memory:
            conn = sqlite3.connect(self._shared_uri, uri=True, check_same_thread=False)
        else:
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def acquire(self) -> sqlite3.Connection:
        try:
            return self._pool.get_nowait()
        except Empty:
            return self._create_connection()

    def release(self, conn: sqlite3.Connection) -> None:
        try:
            self._pool.put_nowait(conn)
        except Exception:
            conn.close()

    def health_check(self) -> dict[str, Any]:
        conn = self.acquire()
        try:
            conn.execute("SELECT 1").fetchone()
            return {
                "healthy": True,
                "database_path": self.database_path,
                "pool_size": self.pool_size,
            }
        finally:
            self.release(conn)


class SpatialDatabase:
    """Unified India-wide geospatial storage engine with connection pooling and spatial indexes."""

    def __init__(self, database_url: str | None = None, pool_size: int = 5) -> None:
        self._lock = threading.RLock()
        self.database_url = database_url or os.environ.get(DATABASE_URL_ENV, "sqlite:///:memory:")
        self.backend_type = "postgresql_postgis" if self.database_url.startswith("postgresql") else "sqlite_spatial"
        self.postgis_migration_file = (
            Path(__file__).resolve().parents[1] / "db" / "migrations" / "001_postgis_schema.sql"
        )

        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "", 1)
        else:
            db_path = ":memory:"
        self.pool = SQLiteConnectionPool(database_path=db_path, pool_size=pool_size)
        self._init_schema_and_seed()

    def _init_schema_and_seed(self) -> None:
        conn = self.pool.acquire()
        try:
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS geo_states (
                        code TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        territory_type TEXT NOT NULL,
                        capital TEXT NOT NULL,
                        zone TEXT NOT NULL,
                        iso_code TEXT NOT NULL,
                        center_lat REAL NOT NULL,
                        center_lon REAL NOT NULL,
                        min_lon REAL NOT NULL,
                        min_lat REAL NOT NULL,
                        max_lon REAL NOT NULL,
                        max_lat REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_geo_states_name ON geo_states (name);
                    CREATE INDEX IF NOT EXISTS idx_geo_states_type ON geo_states (territory_type);

                    CREATE TABLE IF NOT EXISTS geo_districts (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        state_code TEXT NOT NULL REFERENCES geo_states(code) ON DELETE CASCADE,
                        state_name TEXT NOT NULL,
                        headquarters TEXT,
                        center_lat REAL NOT NULL,
                        center_lon REAL NOT NULL,
                        min_lon REAL NOT NULL,
                        min_lat REAL NOT NULL,
                        max_lon REAL NOT NULL,
                        max_lat REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_geo_districts_state ON geo_districts (state_code);
                    CREATE INDEX IF NOT EXISTS idx_geo_districts_name ON geo_districts (name);

                    CREATE TABLE IF NOT EXISTS geo_cities (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        district_id TEXT NOT NULL REFERENCES geo_districts(id) ON DELETE CASCADE,
                        district_name TEXT NOT NULL,
                        state_code TEXT NOT NULL REFERENCES geo_states(code) ON DELETE CASCADE,
                        state_name TEXT NOT NULL,
                        place_type TEXT NOT NULL,
                        population INTEGER,
                        lat REAL NOT NULL,
                        lon REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_geo_cities_district ON geo_cities (district_id);
                    CREATE INDEX IF NOT EXISTS idx_geo_cities_state ON geo_cities (state_code);
                    CREATE INDEX IF NOT EXISTS idx_geo_cities_name ON geo_cities (name);

                    CREATE TABLE IF NOT EXISTS geo_intersections (
                        id TEXT PRIMARY KEY,
                        osm_node_id INTEGER,
                        name TEXT NOT NULL,
                        lat REAL NOT NULL,
                        lon REAL NOT NULL,
                        state_code TEXT,
                        district_id TEXT,
                        city_id TEXT,
                        region TEXT NOT NULL,
                        junction_type TEXT NOT NULL,
                        osm_tags TEXT NOT NULL,
                        is_synthetic INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_geo_intersections_coords ON geo_intersections (lat, lon);
                    CREATE INDEX IF NOT EXISTS idx_geo_intersections_state ON geo_intersections (state_code);

                    CREATE TABLE IF NOT EXISTS geo_road_segments (
                        id TEXT PRIMARY KEY,
                        osm_way_id INTEGER,
                        name TEXT NOT NULL,
                        source_node TEXT NOT NULL,
                        target_node TEXT NOT NULL,
                        state_code TEXT,
                        district_id TEXT,
                        city_id TEXT,
                        region TEXT NOT NULL,
                        highway TEXT NOT NULL,
                        road_type TEXT NOT NULL,
                        lanes INTEGER NOT NULL,
                        length_km REAL NOT NULL,
                        surface TEXT,
                        maxspeed_kmh REAL,
                        oneway TEXT NOT NULL,
                        access TEXT NOT NULL,
                        is_bridge INTEGER NOT NULL,
                        is_tunnel INTEGER NOT NULL,
                        congestion_level TEXT NOT NULL,
                        congestion_penalty REAL NOT NULL,
                        closed INTEGER NOT NULL,
                        closure_reason TEXT,
                        min_lon REAL NOT NULL,
                        min_lat REAL NOT NULL,
                        max_lon REAL NOT NULL,
                        max_lat REAL NOT NULL,
                        geometry_json TEXT NOT NULL,
                        osm_tags TEXT NOT NULL,
                        is_synthetic INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_geo_roads_bbox ON geo_road_segments (min_lon, min_lat, max_lon, max_lat);
                    CREATE INDEX IF NOT EXISTS idx_geo_roads_state ON geo_road_segments (state_code, district_id);
                    CREATE INDEX IF NOT EXISTS idx_geo_roads_highway ON geo_road_segments (highway);

                    CREATE TABLE IF NOT EXISTS osm_import_batches (
                        import_id TEXT PRIMARY KEY,
                        region_name TEXT NOT NULL,
                        state_code TEXT,
                        source_file TEXT NOT NULL,
                        source_format TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        file_sha256 TEXT NOT NULL UNIQUE,
                        file_size_bytes INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        imported_nodes INTEGER NOT NULL,
                        imported_roads INTEGER NOT NULL,
                        skipped_elements INTEGER NOT NULL,
                        min_lon REAL,
                        min_lat REAL,
                        max_lon REAL,
                        max_lat REAL,
                        licence TEXT NOT NULL,
                        attribution TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        completed_at TEXT,
                        error_message TEXT
                    );
                    """
                )
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO geo_states
                    (code, name, territory_type, capital, zone, iso_code, center_lat, center_lon, min_lon, min_lat, max_lon, max_lat)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    INDIA_STATES_AND_UTS,
                )
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO geo_districts
                    (id, name, state_code, state_name, headquarters, center_lat, center_lon, min_lon, min_lat, max_lon, max_lat)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    INDIA_DISTRICTS,
                )
                conn.executemany(
                    """
                    INSERT OR IGNORE INTO geo_cities
                    (id, name, district_id, district_name, state_code, state_name, place_type, population, lat, lon)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    INDIA_CITIES,
                )
        finally:
            self.pool.release(conn)

    def sync_from_road_network(self, network: RoadNetwork) -> None:
        """Persist nodes and road segments from a RoadNetwork into the spatial database."""
        conn = self.pool.acquire()
        try:
            with conn:
                for node in network.nodes.values():
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO geo_intersections
                        (id, osm_node_id, name, lat, lon, state_code, district_id, city_id, region, junction_type, osm_tags, is_synthetic)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            node.id,
                            node.osm_node_id,
                            node.name,
                            node.lat,
                            node.lon,
                            node.state_code,
                            node.district_id,
                            node.city_id,
                            node.region,
                            node.junction_type,
                            json.dumps(node.osm_tags),
                            1 if node.is_synthetic else 0,
                        ),
                    )
                nodes_map = network.nodes
                for seg in network.segments.values():
                    coords = seg.geometry or [
                        (nodes_map[seg.source].lon, nodes_map[seg.source].lat),
                        (nodes_map[seg.target].lon, nodes_map[seg.target].lat),
                    ]
                    lons = [c[0] for c in coords]
                    lats = [c[1] for c in coords]
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO geo_road_segments
                        (id, osm_way_id, name, source_node, target_node, state_code, district_id, city_id,
                         region, highway, road_type, lanes, length_km, surface, maxspeed_kmh, oneway, access,
                         is_bridge, is_tunnel, congestion_level, congestion_penalty, closed, closure_reason,
                         min_lon, min_lat, max_lon, max_lat, geometry_json, osm_tags, is_synthetic)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            seg.id,
                            seg.osm_way_id,
                            seg.name,
                            seg.source,
                            seg.target,
                            seg.state_code,
                            seg.district_id,
                            seg.city_id,
                            seg.region,
                            seg.highway or seg.road_type,
                            seg.road_type,
                            seg.lanes,
                            seg.distance_km,
                            seg.surface,
                            seg.maxspeed_kmh,
                            seg.oneway or ("no" if seg.bidirectional else "yes"),
                            seg.access,
                            1 if seg.is_bridge else 0,
                            1 if seg.is_tunnel else 0,
                            seg.congestion_level,
                            seg.congestion_penalty,
                            1 if seg.closed else 0,
                            seg.closure_reason,
                            min(lons),
                            min(lats),
                            max(lons),
                            max(lats),
                            json.dumps([[float(lon), float(lat)] for lon, lat in coords]),
                            json.dumps(seg.osm_tags),
                            1 if seg.is_synthetic else 0,
                        ),
                    )
        finally:
            self.pool.release(conn)

    def list_states(self, territory_type: str | None = None, zone: str | None = None) -> list[dict[str, Any]]:
        conn = self.pool.acquire()
        try:
            sql = "SELECT * FROM geo_states WHERE 1=1"
            params: list[Any] = []
            if territory_type:
                t = territory_type.lower().strip()
                if t not in {"state", "union_territory"}:
                    raise ValueError("territory_type must be 'state' or 'union_territory'.")
                sql += " AND territory_type = ?"
                params.append(t)
            if zone:
                sql += " AND LOWER(zone) = LOWER(?)"
                params.append(zone.strip())
            sql += " ORDER BY name ASC"
            rows = conn.execute(sql, params).fetchall()
            return [self._format_state_row(dict(r)) for r in rows]
        finally:
            self.pool.release(conn)

    def get_state(self, state_query: str) -> dict[str, Any] | None:
        q = state_query.strip()
        conn = self.pool.acquire()
        try:
            row = conn.execute(
                "SELECT * FROM geo_states WHERE UPPER(code) = UPPER(?) OR LOWER(name) = LOWER(?) OR UPPER(iso_code) = UPPER(?)",
                (q, q, q),
            ).fetchone()
            return self._format_state_row(dict(row)) if row else None
        finally:
            self.pool.release(conn)

    def list_districts(self, state: str | None = None, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500 or offset < 0:
            raise ValueError("Invalid pagination parameters (1 <= limit <= 500, offset >= 0).")
        conn = self.pool.acquire()
        try:
            sql = "SELECT * FROM geo_districts WHERE 1=1"
            params: list[Any] = []
            if state:
                st = state.strip()
                sql += " AND (UPPER(state_code) = UPPER(?) OR LOWER(state_name) = LOWER(?))"
                params.extend([st, st])
            sql += " ORDER BY state_code ASC, name ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            return [self._format_district_row(dict(r)) for r in rows]
        finally:
            self.pool.release(conn)

    def list_cities(
        self,
        district: str | None = None,
        state: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 500 or offset < 0:
            raise ValueError("Invalid pagination parameters (1 <= limit <= 500, offset >= 0).")
        conn = self.pool.acquire()
        try:
            sql = "SELECT * FROM geo_cities WHERE 1=1"
            params: list[Any] = []
            if district:
                d = district.strip()
                sql += " AND (UPPER(district_id) = UPPER(?) OR LOWER(district_name) = LOWER(?))"
                params.extend([d, d])
            if state:
                st = state.strip()
                sql += " AND (UPPER(state_code) = UPPER(?) OR LOWER(state_name) = LOWER(?))"
                params.extend([st, st])
            sql += " ORDER BY population DESC, name ASC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            self.pool.release(conn)

    def resolve_administrative_area(self, lat: float, lon: float) -> dict[str, str | None]:
        """Resolve (state_code, state_name, district_id, district_name, city_id, city_name) for coordinates."""
        conn = self.pool.acquire()
        try:
            dist = conn.execute(
                """
                SELECT * FROM geo_districts
                WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?
                ORDER BY ((center_lat - ?) * (center_lat - ?) + (center_lon - ?) * (center_lon - ?)) ASC
                LIMIT 1
                """,
                (lon, lon, lat, lat, lat, lat, lon, lon),
            ).fetchone()
            state_row = conn.execute(
                """
                SELECT * FROM geo_states
                WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?
                ORDER BY ((center_lat - ?) * (center_lat - ?) + (center_lon - ?) * (center_lon - ?)) ASC
                LIMIT 1
                """,
                (lon, lon, lat, lat, lat, lat, lon, lon),
            ).fetchone()
            city_row = conn.execute(
                """
                SELECT *, ((lat - ?) * (lat - ?) + (lon - ?) * (lon - ?)) AS d2
                FROM geo_cities
                ORDER BY d2 ASC LIMIT 1
                """,
                (lat, lat, lon, lon),
            ).fetchone()
            city_match = dict(city_row) if city_row and city_row["d2"] <= 0.25 else None

            if dist:
                return {
                    "state_code": dist["state_code"],
                    "state_name": dist["state_name"],
                    "district_id": dist["id"],
                    "district_name": dist["name"],
                    "city_id": city_match["id"] if city_match else None,
                    "city_name": city_match["name"] if city_match else None,
                }
            if state_row:
                return {
                    "state_code": state_row["code"],
                    "state_name": state_row["name"],
                    "district_id": None,
                    "district_name": None,
                    "city_id": city_match["id"] if city_match else None,
                    "city_name": city_match["name"] if city_match else None,
                }
            return {
                "state_code": None,
                "state_name": None,
                "district_id": None,
                "district_name": None,
                "city_id": None,
                "city_name": None,
            }
        finally:
            self.pool.release(conn)

    def search_locations(self, query: str, limit: int = 25) -> dict[str, Any]:
        q = (query or "").strip()
        if not q:
            raise ValueError("Search query 'q' must be a non-empty string.")
        if limit < 1 or limit > 100:
            raise ValueError("Search limit must be between 1 and 100.")
        pattern = f"%{q}%"
        conn = self.pool.acquire()
        try:
            results: list[dict[str, Any]] = []
            for r in conn.execute(
                "SELECT * FROM geo_states WHERE name LIKE ? OR code LIKE ? OR capital LIKE ? LIMIT ?",
                (pattern, pattern, pattern, limit),
            ).fetchall():
                results.append(
                    {
                        "type": r["territory_type"],
                        "id": r["code"],
                        "name": r["name"],
                        "state_code": r["code"],
                        "lat": r["center_lat"],
                        "lon": r["center_lon"],
                    }
                )
            for r in conn.execute(
                "SELECT * FROM geo_districts WHERE name LIKE ? OR id LIKE ? LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall():
                results.append(
                    {
                        "type": "district",
                        "id": r["id"],
                        "name": r["name"],
                        "state_code": r["state_code"],
                        "state_name": r["state_name"],
                        "lat": r["center_lat"],
                        "lon": r["center_lon"],
                    }
                )
            for r in conn.execute(
                "SELECT * FROM geo_cities WHERE name LIKE ? OR id LIKE ? LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall():
                results.append(
                    {
                        "type": "city",
                        "id": r["id"],
                        "name": r["name"],
                        "district_id": r["district_id"],
                        "state_code": r["state_code"],
                        "lat": r["lat"],
                        "lon": r["lon"],
                    }
                )
            for r in conn.execute(
                "SELECT * FROM geo_intersections WHERE name LIKE ? OR id LIKE ? LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall():
                results.append(
                    {
                        "type": "intersection",
                        "id": r["id"],
                        "name": r["name"],
                        "state_code": r["state_code"],
                        "region": r["region"],
                        "lat": r["lat"],
                        "lon": r["lon"],
                    }
                )
            for r in conn.execute(
                "SELECT * FROM geo_road_segments WHERE name LIKE ? OR id LIKE ? LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall():
                results.append(
                    {
                        "type": "road_segment",
                        "id": r["id"],
                        "name": r["name"],
                        "highway": r["highway"],
                        "state_code": r["state_code"],
                        "region": r["region"],
                        "lat": (r["min_lat"] + r["max_lat"]) / 2.0,
                        "lon": (r["min_lon"] + r["max_lon"]) / 2.0,
                    }
                )
            return {"query": q, "count": len(results[:limit]), "results": results[:limit]}
        finally:
            self.pool.release(conn)

    def record_import_batch(self, batch: dict[str, Any]) -> None:
        conn = self.pool.acquire()
        try:
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO osm_import_batches
                    (import_id, region_name, state_code, source_file, source_format, source_url,
                     file_sha256, file_size_bytes, status, imported_nodes, imported_roads,
                     skipped_elements, min_lon, min_lat, max_lon, max_lat, licence, attribution,
                     started_at, completed_at, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        batch["import_id"],
                        batch["region_name"],
                        batch.get("state_code"),
                        batch["source_file"],
                        batch["source_format"],
                        batch["source_url"],
                        batch["file_sha256"],
                        batch["file_size_bytes"],
                        batch["status"],
                        batch.get("imported_nodes", 0),
                        batch.get("imported_roads", 0),
                        batch.get("skipped_elements", 0),
                        batch.get("min_lon"),
                        batch.get("min_lat"),
                        batch.get("max_lon"),
                        batch.get("max_lat"),
                        batch.get("licence", OSM_LICENCE),
                        batch.get("attribution", OSM_ATTRIBUTION),
                        batch["started_at"],
                        batch.get("completed_at"),
                        batch.get("error_message"),
                    ),
                )
        finally:
            self.pool.release(conn)

    def get_import_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        conn = self.pool.acquire()
        try:
            row = conn.execute(
                "SELECT * FROM osm_import_batches WHERE file_sha256 = ? AND status = 'completed'",
                (sha256,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            self.pool.release(conn)

    def find_import_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        return self.get_import_by_sha256(sha256)

    def list_import_batches(self) -> list[dict[str, Any]]:
        conn = self.pool.acquire()
        try:
            rows = conn.execute("SELECT * FROM osm_import_batches ORDER BY started_at DESC").fetchall()
            return [dict(r) for r in rows]
        finally:
            self.pool.release(conn)

    def coverage_summary(self, road_network: RoadNetwork | None = None) -> dict[str, Any]:
        if road_network is not None:
            self.sync_from_road_network(road_network)
        conn = self.pool.acquire()
        try:
            total_states = conn.execute("SELECT COUNT(*) FROM geo_states WHERE territory_type = 'state'").fetchone()[0]
            total_uts = conn.execute("SELECT COUNT(*) FROM geo_states WHERE territory_type = 'union_territory'").fetchone()[0]
            total_districts = conn.execute("SELECT COUNT(*) FROM geo_districts").fetchone()[0]
            total_cities = conn.execute("SELECT COUNT(*) FROM geo_cities").fetchone()[0]
            total_nodes = conn.execute("SELECT COUNT(*) FROM geo_intersections").fetchone()[0]
            synth_nodes = conn.execute("SELECT COUNT(*) FROM geo_intersections WHERE is_synthetic = 1").fetchone()[0]
            osm_nodes = total_nodes - synth_nodes
            total_roads = conn.execute("SELECT COUNT(*) FROM geo_road_segments").fetchone()[0]
            synth_roads = conn.execute("SELECT COUNT(*) FROM geo_road_segments WHERE is_synthetic = 1").fetchone()[0]
            osm_roads = total_roads - synth_roads
            states_with_roads = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT state_code FROM geo_road_segments WHERE state_code IS NOT NULL ORDER BY state_code"
                ).fetchall()
            ]
            imports = [dict(r) for r in conn.execute("SELECT * FROM osm_import_batches ORDER BY started_at DESC").fetchall()]
            admin_reg = {
                "states_count": total_states,
                "union_territories_count": total_uts,
                "total_states_and_uts": total_states + total_uts,
                "districts_count": total_districts,
                "cities_and_towns_count": total_cities,
            }
            road_stats = {
                "total_intersections": total_nodes,
                "synthetic_demo_intersections": synth_nodes,
                "imported_osm_intersections": osm_nodes,
                "total_road_segments": total_roads,
                "synthetic_demo_road_segments": synth_roads,
                "imported_osm_road_segments": osm_roads,
                "states_with_road_segments": states_with_roads,
            }
            return {
                "country": "India",
                "nationwide_osm_imported": False,
                "storage_backend": self.backend_type,
                "postgis_migration_ready": self.postgis_migration_file.is_file(),
                "postgis_migration_path": str(self.postgis_migration_file),
                "administrative_registry": admin_reg,
                "administrative_hierarchy": admin_reg,
                "road_network_statistics": road_stats,
                "road_network": road_stats,
                "import_batches": imports,
                "osm_source_info": {
                    "geofabrik_india_url": GEOFABRIK_INDIA_INDEX_URL,
                    "regional_zones": GEOFABRIK_ZONES,
                    "licence": OSM_LICENCE,
                    "attribution": OSM_ATTRIBUTION,
                },
                "notes": [
                    "All 28 Indian States and 8 Union Territories are registered in the spatial database.",
                    "Nationwide India PBF (~1.5 GB compressed) has NOT been blindly downloaded; use the regional OSM ingestion pipeline to import regional/state extracts incrementally.",
                ],
            }
        finally:
            self.pool.release(conn)

    @staticmethod
    def _format_state_row(r: dict[str, Any]) -> dict[str, Any]:
        r["bbox"] = [r["min_lon"], r["min_lat"], r["max_lon"], r["max_lat"]]
        return r

    @staticmethod
    def _format_district_row(r: dict[str, Any]) -> dict[str, Any]:
        r["bbox"] = [r["min_lon"], r["min_lat"], r["max_lon"], r["max_lat"]]
        return r
