# UrbanFlow AI — Computer Vision & VehicleNet-Y26m Documentation

## 1. Model Attribution & Licence Notice

### Primary Indian Traffic Model: VehicleNet-Y26m
- **Model Name**: `VehicleNet-Y26m`
- **Model Author**: `Perception365`
- **Original Repository URL**: https://huggingface.co/Perception365/VehicleNet-Y26m
- **Licence**: GNU Affero General Public License v3.0 (`AGPL-3.0`) — https://ultralytics.com/license
- **Architecture**: Ultralytics `YOLO26m` (`ultralytics.nn.tasks.DetectionModel`, `yolo26m.yaml`, 14 classes)
- **Fine-Tuning Dataset**: `UVH-26` (Indian traffic multi-vehicle dataset)
- **Local Checkpoint Path**: `ai/models/VehicleNet-Y26m/weights/best.pt`
- **Checkpoint Size**: 44,061,849 bytes (42.02 MB)
- **SHA-256**: `da353b7f6fa02b552b3aaa7f8cb4ecf4cd92d63aca7922ca6f2163fcd2010c9d`
- **Download Date**: 2026-10-30
- **Usage Scope**: Academic Smart Cities & Mobility research and hackathon demonstration only (not for commercialisation).

### Fallback Model: YOLO26m (COCO Pretrained)
- **Model Name**: `YOLO26m`
- **Model Author**: `Ultralytics`
- **Original Repository URL**: https://github.com/ultralytics/ultralytics
- **Licence**: `AGPL-3.0`
- **Local Checkpoint Path**: `ai/models/yolo26m.pt`

---

## 2. Verified 14-Class Mapping (`VehicleNet-Y26m`)

| Class ID | Class Name |
|---:|---|
| `0` | `Hatchback` |
| `1` | `Sedan` |
| `2` | `SUV` |
| `3` | `MUV` |
| `4` | `Bus` |
| `5` | `Truck` |
| `6` | `Three-wheeler` |
| `7` | `Two-wheeler` |
| `8` | `LCV` |
| `9` | `Mini-bus` |
| `10` | `Tempo-traveller` |
| `11` | `Bicycle` |
| `12` | `Van` |
| `13` | `Others` |

---

## 3. Model Selection & Configuration

Model selection is controlled via `backend/config/vision_config.py` and `VehicleDetector`:
- **Environment Variable**: `URBANFLOW_MODEL=vehiclenet` (or `URBANFLOW_MODEL=yolo26m`)
- **CLI Flag**: `--model vehiclenet` or `--model yolo26m`
- **Python API**: `VehicleDetector(model_name="vehiclenet")`

---

## 4. Known Limitations

1. **Formal UVH-26 Benchmark Pending**: The UVH-26 validation dataset split is not downloaded locally; therefore, no mAP or real-world Indian traffic accuracy claims are made.
2. **No Pedestrian Class in VehicleNet-Y26m**: `VehicleNet-Y26m` is dedicated exclusively to 14 vehicle categories and does not detect pedestrians (`person`).
3. **Checkpoint Storage**: Model weights (`*.pt`) are large binary artifacts and should not be committed in duplicate to Git.

---

## 5. India-Wide Geospatial Architecture & OpenStreetMap Attribution

### OpenStreetMap Data Source & Licence Notice
- **Data Source**: OpenStreetMap via Geofabrik India Regional Extracts — https://download.geofabrik.de/asia/india.html
- **Licence**: Open Data Commons Open Database License (`ODbL-1.0`) — https://opendatacommons.org/licenses/odbl/1-0/
- **Required Attribution**: `© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)`
- **Incremental Regional Strategy**: The nationwide `india-latest.osm.pbf` (~1.5 GB compressed) is **not** blindly downloaded or loaded into memory all at once. Instead, UrbanFlow AI seeds all **28 Indian States** and **8 Union Territories** (plus representative districts and cities/towns), retains the fast synthetic Bengaluru demonstration network by default, and ingests regional/state/city OpenStreetMap extracts incrementally.

---

## 6. Spatial Storage, PostGIS Schema & Setup

### PostgreSQL + PostGIS (Production / Docker)
1. Start the PostGIS 16 + 3.4 container:
   ```bash
   docker compose -f docker-compose.postgis.yml up -d
   ```
2. The non-destructive migration script `backend/db/migrations/001_postgis_schema.sql` runs automatically on initialization (or manually via `psql $DATABASE_URL -f backend/db/migrations/001_postgis_schema.sql`) and creates:
   - `CREATE EXTENSION IF NOT EXISTS postgis;`
   - `geo_states`, `geo_districts`, `geo_cities`, `geo_intersections`, `geo_road_segments`, `osm_import_batches`, and `geo_incident_road_links`
   - `GEOMETRY(..., 4326)` columns with `USING GIST (geom)` spatial indexes and B-tree indexes on administrative codes and road classifications.

### Pooled Local Spatial Engine (Zero-Config Development & Testing)
- `backend/services/spatial_db.py` provides `SpatialDatabase` with connection pooling (`SQLiteConnectionPool` by default or `DATABASE_URL` configuration), seeding all 28 Indian States and 8 Union Territories and indexing bounding boxes for deterministic offline testing.

---

## 7. OpenStreetMap Regional Ingestion Pipeline

Use `backend/services/osm_ingestor.py` to import regional `.osm.pbf`, `.osm` (XML), `.osm.json` (Overpass JSON), or `.geojson` extracts:

```bash
.venv312/bin/python -m backend.services.osm_ingestor path/to/extract.osm.pbf \
  --region "Chennai Central" \
  --state TN \
  --district TN_CHN \
  --city city_chennai
```

Key ingestion guarantees:
- **Source Validation & SHA-256 Deduplication**: Rejects empty, malformed, or out-of-India-bounds files and skips duplicate imports matching a previously completed `file_sha256` unless `--force` (`force_reimport=True`) is supplied.
- **Strict Topological Intersection Splitting**: Splits OSM highway ways only at shared OSM node IDs. Roads whose geometries cross without sharing an OSM node (such as grade-separated flyovers) are never artificially connected.
- **Directed Road Attributes**: Extracts `osm_way_id`, `highway`, `lanes`, `maxspeed_kmh`, `surface`, `oneway` (`yes`, `no`, `reverse` / `-1`), `access`, `is_bridge`, `is_tunnel`, and full polyline `geometry`.

---

## 8. NetworkX vs pgRouting Architectural Evaluation

- **Regional & City-Scale Routing (Implemented)**: `RoadNetwork` (`backend/services/road_network.py`) and `SmartRoutingEngine` (`backend/services/routing_engine.py`) use a directed `networkx.DiGraph` with `extract_regional_network(bbox)` and an LRU cache (`region_cache_size=32`). For city and regional subgraphs (up to ~50k–100k edges), in-memory NetworkX supports microsecond isolated graph cloning (`clone()`) for what-if road-closure, incident, and congestion simulations without mutating the spatial database.
- **Nationwide Multi-State Routing (pgRouting Path)**: Loading all of India's millions of OSM road ways into a single Python process is impractical. When full multi-state highway routing is required in production PostGIS deployments, `geo_road_segments` (`source_node`, `target_node`, `length_km`, `geom`) is structured for direct use with `pgRouting` (`pgr_dijkstra` / `pgr_ksp`) over spatial bounding-box views while keeping city-level what-if simulations in regional `RoadNetwork` extracts.

---

## 9. Geographic REST APIs (`/api/geo/*` & `/api/health`)

- `GET /api/geo/india` — India overview, administrative hierarchy counts, Geofabrik zones, and ODbL 1.0 attribution.
- `GET /api/geo/states` — List all 28 states and 8 Union Territories (`?territory_type=state|union_territory&zone=...`).
- `GET /api/geo/districts?state={state}` — Query districts by state code or name with pagination (`limit`, `offset`).
- `GET /api/geo/cities?district={district}&state={state}` — Query cities and towns with pagination.
- `GET /api/geo/roads?bbox=min_lon,min_lat,max_lon,max_lat` — Query road segments in a validated bounding box as a GeoJSON `FeatureCollection`.
- `GET /api/geo/roads/{road_id}` — Detailed road segment attributes, GeoJSON `Feature`, endpoints, and active incidents.
- `GET /api/geo/search?q={query}` — Search across Indian states, districts, cities, intersections, and road segments.
- `GET /api/geo/coverage` — Inspect PostGIS migration status, OSM import batches, and synthetic vs imported road coverage.
- `GET /api/health` — Platform health check for the database pool, road network, and computer-vision models.

