-- UrbanFlow AI — Migration 001: India-Wide Geospatial & PostGIS Schema
-- Target: PostgreSQL 15/16 + PostGIS 3.4 (SRID 4326 WGS84)
-- Licence / Attribution: OpenStreetMap data © OpenStreetMap contributors (ODbL 1.0)

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(64) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS geo_states (
    code VARCHAR(16) PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    territory_type VARCHAR(32) NOT NULL CHECK (territory_type IN ('state', 'union_territory')),
    capital VARCHAR(128) NOT NULL,
    zone VARCHAR(64) NOT NULL,
    iso_code VARCHAR(16) NOT NULL,
    center_lat DOUBLE PRECISION NOT NULL,
    center_lon DOUBLE PRECISION NOT NULL,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Polygon, 4326),
    Boundary_srid INTEGER NOT NULL DEFAULT 4326
);

CREATE INDEX IF NOT EXISTS idx_geo_states_name ON geo_states (name);
CREATE INDEX IF NOT EXISTS idx_geo_states_type ON geo_states (territory_type);
CREATE INDEX IF NOT EXISTS idx_geo_states_geom ON geo_states USING GIST (geom);

CREATE TABLE IF NOT EXISTS geo_districts (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    state_code VARCHAR(16) NOT NULL REFERENCES geo_states(code) ON DELETE CASCADE,
    state_name VARCHAR(128) NOT NULL,
    headquarters VARCHAR(128),
    center_lat DOUBLE PRECISION NOT NULL,
    center_lon DOUBLE PRECISION NOT NULL,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Polygon, 4326)
);

CREATE INDEX IF NOT EXISTS idx_geo_districts_state_code ON geo_districts (state_code);
CREATE INDEX IF NOT EXISTS idx_geo_districts_name ON geo_districts (name);
CREATE INDEX IF NOT EXISTS idx_geo_districts_geom ON geo_districts USING GIST (geom);

CREATE TABLE IF NOT EXISTS geo_cities (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    district_id VARCHAR(64) NOT NULL REFERENCES geo_districts(id) ON DELETE CASCADE,
    district_name VARCHAR(128) NOT NULL,
    state_code VARCHAR(16) NOT NULL REFERENCES geo_states(code) ON DELETE CASCADE,
    state_name VARCHAR(128) NOT NULL,
    place_type VARCHAR(32) NOT NULL DEFAULT 'city',
    population INTEGER,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    geom GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_geo_cities_district ON geo_cities (district_id);
CREATE INDEX IF NOT EXISTS idx_geo_cities_state ON geo_cities (state_code);
CREATE INDEX IF NOT EXISTS idx_geo_cities_name ON geo_cities (name);
CREATE INDEX IF NOT EXISTS idx_geo_cities_geom ON geo_cities USING GIST (geom);

CREATE TABLE IF NOT EXISTS geo_intersections (
    id VARCHAR(64) PRIMARY KEY,
    osm_node_id BIGINT UNIQUE,
    name VARCHAR(256) NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    state_code VARCHAR(16),
    district_id VARCHAR(64),
    city_id VARCHAR(64),
    region VARCHAR(128) NOT NULL DEFAULT 'default',
    junction_type VARCHAR(64) NOT NULL DEFAULT 'intersection',
    osm_tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    geom GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS idx_geo_intersections_state ON geo_intersections (state_code);
CREATE INDEX IF NOT EXISTS idx_geo_intersections_region ON geo_intersections (region);
CREATE INDEX IF NOT EXISTS idx_geo_intersections_coords ON geo_intersections (lat, lon);
CREATE INDEX IF NOT EXISTS idx_geo_intersections_geom ON geo_intersections USING GIST (geom);

CREATE TABLE IF NOT EXISTS geo_road_segments (
    id VARCHAR(128) PRIMARY KEY,
    osm_way_id BIGINT,
    name VARCHAR(256) NOT NULL,
    source_node VARCHAR(64) NOT NULL REFERENCES geo_intersections(id) ON DELETE CASCADE,
    target_node VARCHAR(64) NOT NULL REFERENCES geo_intersections(id) ON DELETE CASCADE,
    state_code VARCHAR(16),
    district_id VARCHAR(64),
    city_id VARCHAR(64),
    region VARCHAR(128) NOT NULL DEFAULT 'default',
    highway VARCHAR(64) NOT NULL DEFAULT 'arterial',
    road_class VARCHAR(64) NOT NULL DEFAULT 'arterial',
    lanes INTEGER NOT NULL DEFAULT 2,
    length_km DOUBLE PRECISION NOT NULL CHECK (length_km > 0),
    surface VARCHAR(64),
    maxspeed_kmh DOUBLE PRECISION,
    oneway VARCHAR(16) NOT NULL DEFAULT 'no' CHECK (oneway IN ('yes', 'no', 'reverse')),
    access VARCHAR(64) NOT NULL DEFAULT 'yes',
    is_bridge BOOLEAN NOT NULL DEFAULT FALSE,
    is_tunnel BOOLEAN NOT NULL DEFAULT FALSE,
    congestion_level VARCHAR(16) NOT NULL DEFAULT 'LOW',
    congestion_penalty DOUBLE PRECISION NOT NULL DEFAULT 0.10 CHECK (congestion_penalty >= 0),
    closed BOOLEAN NOT NULL DEFAULT FALSE,
    closure_reason TEXT,
    min_lon DOUBLE PRECISION NOT NULL,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lon DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    geometry_geojson JSONB NOT NULL,
    osm_tags JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    geom GEOMETRY(LineString, 4326)
);

CREATE INDEX IF NOT EXISTS idx_geo_roads_osm_way ON geo_road_segments (osm_way_id);
CREATE INDEX IF NOT EXISTS idx_geo_roads_source_target ON geo_road_segments (source_node, target_node);
CREATE INDEX IF NOT EXISTS idx_geo_roads_state_district ON geo_road_segments (state_code, district_id);
CREATE INDEX IF NOT EXISTS idx_geo_roads_highway ON geo_road_segments (highway);
CREATE INDEX IF NOT EXISTS idx_geo_roads_bbox ON geo_road_segments (min_lon, min_lat, max_lon, max_lat);
CREATE INDEX IF NOT EXISTS idx_geo_roads_geom ON geo_road_segments USING GIST (geom);

CREATE TABLE IF NOT EXISTS osm_import_batches (
    import_id VARCHAR(64) PRIMARY KEY,
    region_name VARCHAR(128) NOT NULL,
    state_code VARCHAR(16),
    source_file TEXT NOT NULL,
    source_format VARCHAR(32) NOT NULL,
    source_url TEXT NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL UNIQUE,
    file_size_bytes BIGINT NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'skipped_duplicate')),
    imported_nodes INTEGER NOT NULL DEFAULT 0,
    imported_roads INTEGER NOT NULL DEFAULT 0,
    skipped_elements INTEGER NOT NULL DEFAULT 0,
    min_lon DOUBLE PRECISION,
    min_lat DOUBLE PRECISION,
    max_lon DOUBLE PRECISION,
    max_lat DOUBLE PRECISION,
    licence VARCHAR(64) NOT NULL DEFAULT 'ODbL-1.0',
    attribution TEXT NOT NULL DEFAULT '© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_osm_imports_status ON osm_import_batches (status);
CREATE INDEX IF NOT EXISTS idx_osm_imports_state ON osm_import_batches (state_code);

CREATE TABLE IF NOT EXISTS geo_incident_road_links (
    incident_id VARCHAR(64) NOT NULL,
    road_id VARCHAR(128) NOT NULL REFERENCES geo_road_segments(id) ON DELETE CASCADE,
    distance_km DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    direction_aligned BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (incident_id, road_id)
);

INSERT INTO schema_migrations (version, description)
VALUES ('001_postgis_india_geospatial', 'Initial India-wide PostGIS schema for states, districts, cities, intersections, OSM road segments, and import metadata')
ON CONFLICT (version) DO NOTHING;
