"""OpenStreetMap (OSM) Regional & State Data Ingestion Pipeline for UrbanFlow AI.

Supports importing real OpenStreetMap road networks for Indian states, districts,
and cities into the UrbanFlow AI RoadNetwork and SpatialDatabase (PostGIS / SQLite).

Supported input formats (pure Python, zero external binary dependencies required):
- `.osm.pbf` — OpenStreetMap Protocolbuffer Binary Format (raw & zlib-compressed blobs)
- `.osm` / `.xml` — Standard OpenStreetMap XML format
- `.osm.json` / `.json` — Overpass API / OSM JSON format
- `.geojson` — GeoJSON FeatureCollection of LineString road ways

Key engineering guarantees:
1. Validates source file existence, non-empty size, format signature, and coordinate bounds.
2. Computes SHA-256 checksum to prevent duplicate imports unless `force_reimport=True`.
3. Splits highway ways at shared intersection nodes so topological connectivity is exact.
4. Never connects road ways merely because their geometries cross or are close without a shared OSM node.
5. Preserves one-way directionality (`yes`, `no`, `reverse` / `-1`), access restrictions,
   lane counts, speed limits, road surface, bridge/tunnel flags, and full polyline geometry.
6. Resolves Indian state, district, and city hierarchy for each imported node and road segment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import uuid
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.india_geo_registry import (
    INDIA_MAX_LAT,
    INDIA_MAX_LON,
    INDIA_MIN_LAT,
    INDIA_MIN_LON,
    OSM_ATTRIBUTION,
    OSM_LICENCE,
    OSM_SOURCE_URL,
    find_state,
)
from backend.services.road_network import (
    DEFAULT_HIGHWAY_MAXSPEED_KMH,
    SUPPORTED_OSM_HIGHWAY_TYPES,
    GeoPoint,
    RoadNetwork,
    RoadNode,
    RoadSegment,
    haversine_km,
)
from backend.services.spatial_db import SpatialDatabase


class OSMIngestionError(ValueError):
    """Raised when an OSM source file is invalid, corrupted, or fails ingestion."""


@dataclass
class OSMWayRecord:
    osm_way_id: int
    node_refs: list[int]
    tags: dict[str, str]


@dataclass
class OSMNodeRecord:
    osm_node_id: int
    lat: float
    lon: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class OSMImportReport:
    import_id: str
    region_name: str
    state_code: str | None
    source_path: str
    source_format: str
    source_url: str
    licence: str
    attribution: str
    file_sha256: str
    status: str  # "completed", "skipped_duplicate", "failed"
    started_at: str
    completed_at: str
    imported_nodes: int
    imported_roads: int
    skipped_elements: int
    bbox: dict[str, float] | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_lanes(raw: str | int | None, highway: str) -> int:
    if raw is not None:
        s = str(raw).strip()
        for part in s.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit() and int(part) > 0:
                return min(int(part), 16)
    defaults = {
        "motorway": 4,
        "trunk": 4,
        "primary": 3,
        "secondary": 2,
        "tertiary": 2,
    }
    return defaults.get(highway, 2)


def parse_maxspeed_kmh(raw: str | float | int | None, highway: str) -> float:
    if raw is not None:
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        s = str(raw).lower().strip()
        is_mph = "mph" in s
        num_chars = []
        for ch in s:
            if ch.isdigit() or ch == ".":
                num_chars.append(ch)
            elif num_chars:
                break
        if num_chars:
            try:
                val = float("".join(num_chars))
                if val > 0:
                    return round(val * 1.60934, 1) if is_mph else round(val, 1)
            except ValueError:
                pass
    return DEFAULT_HIGHWAY_MAXSPEED_KMH.get(highway, 40.0)


def parse_oneway(tags: dict[str, str], highway: str) -> tuple[str, bool]:
    """Return (`oneway`, `bidirectional`) where `oneway` is 'yes', 'no', or 'reverse'."""
    raw = str(tags.get("oneway", "")).lower().strip()
    if raw in {"-1", "reverse"}:
        return "reverse", False
    if raw in {"yes", "true", "1"}:
        return "yes", False
    if raw in {"no", "false", "0"}:
        return "no", True
    if highway in {"motorway", "motorway_link"} or tags.get("junction") == "roundabout":
        return "yes", False
    return "no", True


def parse_bool_tag(value: str | None) -> bool:
    if not value:
        return False
    return value.lower().strip() not in {"no", "false", "0", ""}


# ---------------------------------------------------------------------------
# Pure-Python Protobuf Wire-Format Reader & Writer for `.osm.pbf`
# ---------------------------------------------------------------------------


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    length = len(buf)
    while pos < length:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift >= 64:
            raise OSMIngestionError("Corrupted protobuf varint in PBF stream.")
    raise OSMIngestionError("Unexpected EOF while reading protobuf varint in PBF stream.")


def _decode_zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _iter_proto_fields(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    pos = 0
    length = len(buf)
    fields: list[tuple[int, int, int | bytes]] = []
    while pos < length:
        tag, pos = _read_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 0x07
        if wire_type == 0:  # varint
            val, pos = _read_varint(buf, pos)
            fields.append((field_num, wire_type, val))
        elif wire_type == 2:  # length-delimited
            size, pos = _read_varint(buf, pos)
            if size < 0 or pos + size > length:
                raise OSMIngestionError("Truncated length-delimited field in PBF stream.")
            fields.append((field_num, wire_type, buf[pos : pos + size]))
            pos += size
        elif wire_type == 1:  # 64-bit
            if pos + 8 > length:
                raise OSMIngestionError("Truncated 64-bit field in PBF stream.")
            fields.append((field_num, wire_type, buf[pos : pos + 8]))
            pos += 8
        elif wire_type == 5:  # 32-bit
            if pos + 4 > length:
                raise OSMIngestionError("Truncated 32-bit field in PBF stream.")
            fields.append((field_num, wire_type, buf[pos : pos + 4]))
            pos += 4
        else:
            raise OSMIngestionError(f"Unsupported protobuf wire type {wire_type} in PBF file.")
    return fields


def _unpack_packed_varints(buf: bytes, signed: bool = False) -> list[int]:
    pos = 0
    out: list[int] = []
    while pos < len(buf):
        v, pos = _read_varint(buf, pos)
        out.append(_decode_zigzag(v) if signed else v)
    return out


def _parse_pbf_file(path: Path) -> tuple[dict[int, OSMNodeRecord], list[OSMWayRecord], int]:
    """Parse an OpenStreetMap `.osm.pbf` binary file into nodes and highway ways."""
    data = path.read_bytes()
    if len(data) < 8:
        raise OSMIngestionError(f"OSM PBF file '{path.name}' is too small ({len(data)} bytes).")

    pos = 0
    saw_header = False
    nodes: dict[int, OSMNodeRecord] = {}
    ways: list[OSMWayRecord] = []
    skipped = 0

    while pos < len(data):
        if pos + 4 > len(data):
            raise OSMIngestionError("Truncated PBF block header length prefix.")
        (header_len,) = struct.unpack(">I", data[pos : pos + 4])
        pos += 4
        if header_len <= 0 or header_len > 65536 or pos + header_len > len(data):
            raise OSMIngestionError(f"Invalid PBF BlobHeader size ({header_len}) in '{path.name}'.")

        header_bytes = data[pos : pos + header_len]
        pos += header_len
        block_type = ""
        datasize = -1
        for fnum, wtype, val in _iter_proto_fields(header_bytes):
            if fnum == 1 and isinstance(val, bytes):
                block_type = val.decode("utf-8", errors="replace")
            elif fnum == 3 and isinstance(val, int):
                datasize = val

        if block_type not in {"OSMHeader", "OSMData"} or datasize < 0 or pos + datasize > len(data):
            raise OSMIngestionError(
                f"Corrupted PBF block (type={block_type!r}, datasize={datasize}) in '{path.name}'."
            )

        blob_bytes = data[pos : pos + datasize]
        pos += datasize
        payload: bytes | None = None
        for fnum, wtype, val in _iter_proto_fields(blob_bytes):
            if fnum == 1 and isinstance(val, bytes):  # raw
                payload = val
            elif fnum == 3 and isinstance(val, bytes):  # zlib_data
                try:
                    payload = zlib.decompress(val)
                except zlib.error as exc:
                    raise OSMIngestionError(f"Failed to decompress PBF zlib blob: {exc}") from exc

        if payload is None:
            raise OSMIngestionError(f"PBF Blob in '{path.name}' contains neither raw nor zlib payload.")

        if block_type == "OSMHeader":
            saw_header = True
            continue

        # Parse PrimitiveBlock
        stringtable: list[str] = []
        prim_groups: list[bytes] = []
        granularity = 100
        lat_offset = 0
        lon_offset = 0

        for fnum, wtype, val in _iter_proto_fields(payload):
            if fnum == 1 and isinstance(val, bytes):
                for sfnum, _, sval in _iter_proto_fields(val):
                    if sfnum == 1 and isinstance(sval, bytes):
                        stringtable.append(sval.decode("utf-8", errors="replace"))
            elif fnum == 2 and isinstance(val, bytes):
                prim_groups.append(val)
            elif fnum == 17 and isinstance(val, int):
                granularity = val
            elif fnum == 19 and isinstance(val, int):
                lat_offset = _decode_zigzag(val)
            elif fnum == 20 and isinstance(val, int):
                lon_offset = _decode_zigzag(val)

        for pg in prim_groups:
            for gfnum, _, gval in _iter_proto_fields(pg):
                if gfnum == 1 and isinstance(gval, bytes):  # Node
                    nid = None
                    raw_lat = None
                    raw_lon = None
                    keys: list[int] = []
                    vals: list[int] = []
                    for nfnum, _, nval in _iter_proto_fields(gval):
                        if nfnum == 1 and isinstance(nval, int):
                            nid = nval
                        elif nfnum == 2 and isinstance(nval, bytes):
                            keys.extend(_unpack_packed_varints(nval, signed=False))
                        elif nfnum == 3 and isinstance(nval, bytes):
                            vals.extend(_unpack_packed_varints(nval, signed=False))
                        elif nfnum == 8 and isinstance(nval, int):
                            raw_lat = _decode_zigzag(nval)
                        elif nfnum == 9 and isinstance(nval, int):
                            raw_lon = _decode_zigzag(nval)
                    if nid is not None and raw_lat is not None and raw_lon is not None:
                        lat = 1e-9 * (lat_offset + granularity * raw_lat)
                        lon = 1e-9 * (lon_offset + granularity * raw_lon)
                        ntags = {
                            stringtable[k]: stringtable[v]
                            for k, v in zip(keys, vals)
                            if k < len(stringtable) and v < len(stringtable)
                        }
                        nodes[nid] = OSMNodeRecord(osm_node_id=nid, lat=lat, lon=lon, tags=ntags)
                elif gfnum == 2 and isinstance(gval, bytes):  # DenseNodes
                    d_ids: list[int] = []
                    d_lats: list[int] = []
                    d_lons: list[int] = []
                    d_kv: list[int] = []
                    for dfnum, _, dval in _iter_proto_fields(gval):
                        if dfnum == 1 and isinstance(dval, bytes):
                            d_ids = _unpack_packed_varints(dval, signed=True)
                        elif dfnum == 8 and isinstance(dval, bytes):
                            d_lats = _unpack_packed_varints(dval, signed=True)
                        elif dfnum == 9 and isinstance(dval, bytes):
                            d_lons = _unpack_packed_varints(dval, signed=True)
                        elif dfnum == 10 and isinstance(dval, bytes):
                            d_kv = _unpack_packed_varints(dval, signed=False)
                    cur_id = 0
                    cur_lat = 0
                    cur_lon = 0
                    kv_idx = 0
                    for delta_id, delta_lat, delta_lon in zip(d_ids, d_lats, d_lons):
                        cur_id += delta_id
                        cur_lat += delta_lat
                        cur_lon += delta_lon
                        lat = 1e-9 * (lat_offset + granularity * cur_lat)
                        lon = 1e-9 * (lon_offset + granularity * cur_lon)
                        ntags: dict[str, str] = {}
                        while kv_idx < len(d_kv):
                            k = d_kv[kv_idx]
                            kv_idx += 1
                            if k == 0:
                                break
                            if kv_idx < len(d_kv):
                                v = d_kv[kv_idx]
                                kv_idx += 1
                                if k < len(stringtable) and v < len(stringtable):
                                    ntags[stringtable[k]] = stringtable[v]
                        nodes[cur_id] = OSMNodeRecord(osm_node_id=cur_id, lat=lat, lon=lon, tags=ntags)
                elif gfnum == 3 and isinstance(gval, bytes):  # Way
                    wid = None
                    keys = []
                    vals = []
                    ref_deltas: list[int] = []
                    for wfnum, _, wval in _iter_proto_fields(gval):
                        if wfnum == 1 and isinstance(wval, int):
                            wid = wval
                        elif wfnum == 2 and isinstance(wval, bytes):
                            keys.extend(_unpack_packed_varints(wval, signed=False))
                        elif wfnum == 3 and isinstance(wval, bytes):
                            vals.extend(_unpack_packed_varints(wval, signed=False))
                        elif wfnum == 8 and isinstance(wval, bytes):
                            ref_deltas.extend(_unpack_packed_varints(wval, signed=True))
                    if wid is not None:
                        wtags = {
                            stringtable[k]: stringtable[v]
                            for k, v in zip(keys, vals)
                            if k < len(stringtable) and v < len(stringtable)
                        }
                        if wtags.get("highway") in SUPPORTED_OSM_HIGHWAY_TYPES:
                            refs: list[int] = []
                            cur_ref = 0
                            for dr in ref_deltas:
                                cur_ref += dr
                                refs.append(cur_ref)
                            if len(refs) >= 2:
                                ways.append(OSMWayRecord(osm_way_id=wid, node_refs=refs, tags=wtags))
                            else:
                                skipped += 1
                        else:
                            skipped += 1

    if not saw_header:
        raise OSMIngestionError(f"Missing OSMHeader block in PBF file '{path.name}'.")
    return nodes, ways, skipped


# ---------------------------------------------------------------------------
# Helper to build a valid binary `.osm.pbf` file (for tests & regional exports)
# ---------------------------------------------------------------------------


def _encode_varint(val: int) -> bytes:
    out = bytearray()
    while val > 0x7F:
        out.append((val & 0x7F) | 0x80)
        val >>= 7
    out.append(val & 0x7F)
    return bytes(out)


def _encode_zigzag(val: int) -> int:
    return (val << 1) ^ (val >> 63)


def _proto_field_varint(field_num: int, val: int) -> bytes:
    return _encode_varint((field_num << 3) | 0) + _encode_varint(val)


def _proto_field_bytes(field_num: int, payload: bytes) -> bytes:
    return _encode_varint((field_num << 3) | 2) + _encode_varint(len(payload)) + payload


def build_osm_pbf_bytes(
    nodes: list[tuple[int, float, float, dict[str, str]]],
    ways: list[tuple[int, list[int], dict[str, str]]],
) -> bytes:
    """Serialize nodes and ways into a standard zlib-compressed `.osm.pbf` binary stream."""
    # 1. OSMHeader block
    header_block = _proto_field_bytes(4, b"OsmSchema-V0.6") + _proto_field_bytes(4, b"DenseNodes")
    header_blob = _proto_field_bytes(3, zlib.compress(header_block))
    header_blob_hdr = _proto_field_bytes(1, b"OSMHeader") + _proto_field_varint(3, len(header_blob))

    # 2. Build StringTable
    strings = [""]
    str_index: dict[str, int] = {"": 0}
    for _, _, _, ntags in nodes:
        for k, v in ntags.items():
            for s in (k, v):
                if s not in str_index:
                    str_index[s] = len(strings)
                    strings.append(s)
    for _, _, wtags in ways:
        for k, v in wtags.items():
            for s in (k, v):
                if s not in str_index:
                    str_index[s] = len(strings)
                    strings.append(s)

    st_bytes = b"".join(_proto_field_bytes(1, s.encode("utf-8")) for s in strings)

    # 3. Build DenseNodes
    d_ids = bytearray()
    d_lats = bytearray()
    d_lons = bytearray()
    d_kv = bytearray()
    prev_id = 0
    prev_lat = 0
    prev_lon = 0
    for nid, lat, lon, ntags in nodes:
        raw_lat = int(round(lat * 1e7))
        raw_lon = int(round(lon * 1e7))
        d_ids.extend(_encode_varint(_encode_zigzag(nid - prev_id)))
        d_lats.extend(_encode_varint(_encode_zigzag(raw_lat - prev_lat)))
        d_lons.extend(_encode_varint(_encode_zigzag(raw_lon - prev_lon)))
        prev_id = nid
        prev_lat = raw_lat
        prev_lon = raw_lon
        for k, v in ntags.items():
            d_kv.extend(_encode_varint(str_index[k]))
            d_kv.extend(_encode_varint(str_index[v]))
        d_kv.extend(_encode_varint(0))

    dense_msg = (
        _proto_field_bytes(1, bytes(d_ids))
        + _proto_field_bytes(8, bytes(d_lats))
        + _proto_field_bytes(9, bytes(d_lons))
        + _proto_field_bytes(10, bytes(d_kv))
    )
    pg_nodes = _proto_field_bytes(2, dense_msg)

    # 4. Build Ways PrimitiveGroup
    way_msgs = bytearray()
    for wid, refs, wtags in ways:
        keys_packed = b"".join(_encode_varint(str_index[k]) for k in wtags)
        vals_packed = b"".join(_encode_varint(str_index[v]) for v in wtags.values())
        refs_packed = bytearray()
        prev_ref = 0
        for r in refs:
            refs_packed.extend(_encode_varint(_encode_zigzag(r - prev_ref)))
            prev_ref = r
        w_msg = (
            _proto_field_varint(1, wid)
            + _proto_field_bytes(2, keys_packed)
            + _proto_field_bytes(3, vals_packed)
            + _proto_field_bytes(8, bytes(refs_packed))
        )
        way_msgs.extend(_proto_field_bytes(3, w_msg))

    prim_block = (
        _proto_field_bytes(1, st_bytes)
        + _proto_field_bytes(2, pg_nodes)
        + _proto_field_bytes(2, bytes(way_msgs))
        + _proto_field_varint(17, 100)
    )
    data_blob = _proto_field_bytes(3, zlib.compress(prim_block))
    data_blob_hdr = _proto_field_bytes(1, b"OSMData") + _proto_field_varint(3, len(data_blob))

    return (
        struct.pack(">I", len(header_blob_hdr))
        + header_blob_hdr
        + header_blob
        + struct.pack(">I", len(data_blob_hdr))
        + data_blob_hdr
        + data_blob
    )


# ---------------------------------------------------------------------------
# XML / Overpass JSON / GeoJSON Parsers
# ---------------------------------------------------------------------------


def _parse_osm_xml(path: Path) -> tuple[dict[int, OSMNodeRecord], list[OSMWayRecord], int]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise OSMIngestionError(f"Malformed OSM XML file '{path.name}': {exc}") from exc

    root = tree.getroot()
    if root.tag != "osm":
        raise OSMIngestionError(f"Expected <osm> root element in '{path.name}', found <{root.tag}>.")

    nodes: dict[int, OSMNodeRecord] = {}
    ways: list[OSMWayRecord] = []
    skipped = 0

    for elem in root:
        if elem.tag == "node":
            try:
                nid = int(elem.attrib["id"])
                lat = float(elem.attrib["lat"])
                lon = float(elem.attrib["lon"])
            except (KeyError, ValueError) as exc:
                raise OSMIngestionError(f"Invalid <node> attributes in '{path.name}': {exc}") from exc
            ntags = {
                t.attrib["k"]: t.attrib["v"]
                for t in elem.findall("tag")
                if "k" in t.attrib and "v" in t.attrib
            }
            nodes[nid] = OSMNodeRecord(osm_node_id=nid, lat=lat, lon=lon, tags=ntags)
        elif elem.tag == "way":
            try:
                wid = int(elem.attrib["id"])
            except (KeyError, ValueError) as exc:
                raise OSMIngestionError(f"Invalid <way> id in '{path.name}': {exc}") from exc
            wtags = {
                t.attrib["k"]: t.attrib["v"]
                for t in elem.findall("tag")
                if "k" in t.attrib and "v" in t.attrib
            }
            highway = wtags.get("highway", "")
            if highway not in SUPPORTED_OSM_HIGHWAY_TYPES:
                skipped += 1
                continue
            refs: list[int] = []
            for nd in elem.findall("nd"):
                if "ref" in nd.attrib:
                    refs.append(int(nd.attrib["ref"]))
            if len(refs) >= 2:
                ways.append(OSMWayRecord(osm_way_id=wid, node_refs=refs, tags=wtags))
            else:
                skipped += 1

    return nodes, ways, skipped


def _parse_osm_json_or_geojson(path: Path) -> tuple[dict[int, OSMNodeRecord], list[OSMWayRecord], int]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise OSMIngestionError(f"Malformed JSON in '{path.name}': {exc}") from exc

    if not isinstance(payload, dict):
        raise OSMIngestionError(f"Expected JSON object in '{path.name}'.")

    nodes: dict[int, OSMNodeRecord] = {}
    ways: list[OSMWayRecord] = []
    skipped = 0

    # Case 1: Overpass API / OSM JSON (`elements` array)
    if "elements" in payload and isinstance(payload["elements"], list):
        for el in payload["elements"]:
            if not isinstance(el, dict):
                continue
            etype = el.get("type")
            if etype == "node":
                nid = int(el["id"])
                lat = float(el["lat"])
                lon = float(el["lon"])
                tags = {str(k): str(v) for k, v in (el.get("tags") or {}).items()}
                nodes[nid] = OSMNodeRecord(osm_node_id=nid, lat=lat, lon=lon, tags=tags)
            elif etype == "way":
                wid = int(el["id"])
                tags = {str(k): str(v) for k, v in (el.get("tags") or {}).items()}
                if tags.get("highway") not in SUPPORTED_OSM_HIGHWAY_TYPES:
                    skipped += 1
                    continue
                refs = [int(r) for r in (el.get("nodes") or [])]
                if len(refs) >= 2:
                    ways.append(OSMWayRecord(osm_way_id=wid, node_refs=refs, tags=tags))
                else:
                    skipped += 1
        return nodes, ways, skipped

    # Case 2: GeoJSON FeatureCollection
    if payload.get("type") == "FeatureCollection" and isinstance(payload.get("features"), list):
        coord_to_nid: dict[tuple[float, float], int] = {}
        next_synth_nid = 900_000_000
        for idx, feat in enumerate(payload["features"], start=1):
            if not isinstance(feat, dict):
                continue
            geom = feat.get("geometry") or {}
            props = {str(k): str(v) for k, v in (feat.get("properties") or {}).items() if v is not None}
            if geom.get("type") != "LineString":
                skipped += 1
                continue
            highway = props.get("highway", "")
            if highway not in SUPPORTED_OSM_HIGHWAY_TYPES:
                skipped += 1
                continue
            coords = geom.get("coordinates") or []
            if len(coords) < 2:
                skipped += 1
                continue
            wid = int(props.get("osm_way_id") or props.get("osm_id") or feat.get("id") or (700_000_000 + idx))
            refs: list[int] = []
            node_ids_prop = (feat.get("properties") or {}).get("osm_node_ids")
            for c_idx, pt in enumerate(coords):
                lon, lat = float(pt[0]), float(pt[1])
                if isinstance(node_ids_prop, list) and c_idx < len(node_ids_prop):
                    nid = int(node_ids_prop[c_idx])
                else:
                    key = (round(lat, 7), round(lon, 7))
                    if key not in coord_to_nid:
                        next_synth_nid += 1
                        coord_to_nid[key] = next_synth_nid
                    nid = coord_to_nid[key]
                if nid not in nodes:
                    nodes[nid] = OSMNodeRecord(osm_node_id=nid, lat=lat, lon=lon)
                refs.append(nid)
            ways.append(OSMWayRecord(osm_way_id=wid, node_refs=refs, tags=props))
        return nodes, ways, skipped

    raise OSMIngestionError(
        f"Unsupported JSON schema in '{path.name}'. Expected Overpass OSM JSON ('elements') or GeoJSON ('FeatureCollection')."
    )


# ---------------------------------------------------------------------------
# OSM Ingestion Pipeline
# ---------------------------------------------------------------------------


class OSMIngestionPipeline:
    """Ingests regional OpenStreetMap road extracts into RoadNetwork & SpatialDatabase."""

    def __init__(self, road_network: RoadNetwork, spatial_db: SpatialDatabase) -> None:
        self.road_network = road_network
        self.spatial_db = spatial_db

    @staticmethod
    def detect_format(path: Path) -> str:
        name = path.name.lower()
        if name.endswith(".osm.pbf") or name.endswith(".pbf"):
            return "osm.pbf"
        if name.endswith(".osm") or name.endswith(".xml"):
            return "osm.xml"
        if name.endswith(".geojson"):
            return "geojson"
        if name.endswith(".osm.json") or name.endswith(".json"):
            return "osm.json"
        raise OSMIngestionError(
            f"Unsupported OSM file extension for '{path.name}'. "
            "Supported: .osm.pbf, .osm, .xml, .osm.json, .geojson"
        )

    def ingest_file(
        self,
        file_path: str | Path,
        *,
        region_name: str,
        state_code: str | None = None,
        district_id: str | None = None,
        city_id: str | None = None,
        source_url: str = OSM_SOURCE_URL,
        force_reimport: bool = False,
        enforce_india_bounds: bool = True,
    ) -> OSMImportReport:
        """Validate, parse, split at intersections, and persist an OSM extract."""
        started_at = _utc_now_iso()
        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise OSMIngestionError(f"OSM source file does not exist: '{path}'")
        if path.stat().st_size == 0:
            raise OSMIngestionError(f"OSM source file is empty: '{path}'")

        fmt = self.detect_format(path)
        sha256 = compute_file_sha256(path)

        resolved_state_code = state_code
        if state_code:
            st = find_state(state_code)
            if st is None:
                raise OSMIngestionError(f"Unknown Indian state or UT '{state_code}'.")
            resolved_state_code = st["code"]

        existing = self.spatial_db.find_import_by_sha256(sha256)
        if existing is not None and not force_reimport:
            now = _utc_now_iso()
            bbox_dict = (
                {
                    "min_lon": existing["min_lon"],
                    "min_lat": existing["min_lat"],
                    "max_lon": existing["max_lon"],
                    "max_lat": existing["max_lat"],
                }
                if existing.get("min_lon") is not None
                else None
            )
            return OSMImportReport(
                import_id=existing["import_id"],
                region_name=existing["region_name"],
                state_code=existing.get("state_code"),
                source_path=str(path),
                source_format=fmt,
                source_url=existing.get("source_url") or source_url,
                licence=OSM_LICENCE,
                attribution=OSM_ATTRIBUTION,
                file_sha256=sha256,
                status="skipped_duplicate",
                started_at=started_at,
                completed_at=now,
                imported_nodes=int(existing.get("imported_nodes", 0)),
                imported_roads=int(existing.get("imported_roads", 0)),
                skipped_elements=int(existing.get("skipped_elements", 0)),
                bbox=bbox_dict,
                notes=[
                    f"File with SHA-256 {sha256[:16]}... was already imported in batch '{existing['import_id']}'. "
                    "Pass force_reimport=True to re-import and update existing segments."
                ],
            )

        # Parse raw OSM elements
        if fmt == "osm.pbf":
            raw_nodes, raw_ways, skipped = _parse_pbf_file(path)
        elif fmt == "osm.xml":
            raw_nodes, raw_ways, skipped = _parse_osm_xml(path)
        else:
            raw_nodes, raw_ways, skipped = _parse_osm_json_or_geojson(path)

        if not raw_ways:
            raise OSMIngestionError(f"No valid OSM highway ways found in '{path.name}'.")

        # Count node usage across highway ways to identify topological intersections
        node_usage_count: dict[int, int] = {}
        valid_ways: list[OSMWayRecord] = []
        for way in raw_ways:
            present_refs = [r for r in way.node_refs if r in raw_nodes]
            if len(present_refs) < 2:
                skipped += 1
                continue
            if enforce_india_bounds:
                out_of_india = any(
                    not (
                        INDIA_MIN_LAT <= raw_nodes[r].lat <= INDIA_MAX_LAT
                        and INDIA_MIN_LON <= raw_nodes[r].lon <= INDIA_MAX_LON
                    )
                    for r in present_refs
                )
                if out_of_india:
                    raise OSMIngestionError(
                        f"OSM way {way.osm_way_id} in '{path.name}' contains coordinates outside India bounds."
                    )
            valid_ways.append(OSMWayRecord(osm_way_id=way.osm_way_id, node_refs=present_refs, tags=way.tags))
            for idx, ref in enumerate(present_refs):
                # Start and end nodes of a way are always graph vertices; shared interior nodes are intersections
                if idx == 0 or idx == len(present_refs) - 1:
                    node_usage_count[ref] = node_usage_count.get(ref, 0) + 2
                else:
                    node_usage_count[ref] = node_usage_count.get(ref, 0) + 1

        if not valid_ways:
            raise OSMIngestionError(f"No highway ways with resolvable node coordinates found in '{path.name}'.")

        intersection_osm_ids = {nid for nid, count in node_usage_count.items() if count >= 2}

        # Create RoadNode objects for all topological vertices
        created_nodes: list[RoadNode] = []
        min_lat = 90.0
        max_lat = -90.0
        min_lon = 180.0
        max_lon = -180.0

        for osm_nid in sorted(intersection_osm_ids):
            nrec = raw_nodes[osm_nid]
            min_lat = min(min_lat, nrec.lat)
            max_lat = max(max_lat, nrec.lat)
            min_lon = min(min_lon, nrec.lon)
            max_lon = max(max_lon, nrec.lon)

            admin = self.spatial_db.resolve_administrative_area(nrec.lat, nrec.lon)
            st_code = resolved_state_code or admin["state_code"]
            dist_id = district_id or admin["district_id"]
            ct_id = city_id or admin["city_id"]
            node_name = (
                nrec.tags.get("name")
                or nrec.tags.get("name:en")
                or nrec.tags.get("junction")
                or f"OSM Junction {osm_nid}"
            )
            rnode = RoadNode(
                id=f"osm_n_{osm_nid}",
                name=node_name,
                lat=nrec.lat,
                lon=nrec.lon,
                region=region_name,
                osm_node_id=osm_nid,
                junction_type=nrec.tags.get("highway") or nrec.tags.get("junction") or "intersection",
                state_code=st_code,
                district_id=dist_id,
                city_id=ct_id,
                is_synthetic=False,
                osm_tags=nrec.tags,
            )
            self.road_network.add_node(rnode, allow_upsert=True)
            created_nodes.append(rnode)

        # Split each way at intersection nodes into topological RoadSegments
        created_segments: list[RoadSegment] = []
        for way in valid_ways:
            refs = way.node_refs
            tags = way.tags
            highway = tags.get("highway", "unclassified")
            oneway, bidirectional = parse_oneway(tags, highway)
            lanes = parse_lanes(tags.get("lanes"), highway)
            maxspeed = parse_maxspeed_kmh(tags.get("maxspeed"), highway)
            surface = tags.get("surface", "paved")
            access = tags.get("access", "yes").lower().strip()
            is_bridge = parse_bool_tag(tags.get("bridge"))
            is_tunnel = parse_bool_tag(tags.get("tunnel"))
            way_name = (
                tags.get("name")
                or tags.get("name:en")
                or tags.get("ref")
                or f"{highway.replace('_', ' ').title()} #{way.osm_way_id}"
            )

            # Find split indices where the way passes through intersection nodes
            split_indices = [0]
            for idx in range(1, len(refs) - 1):
                if refs[idx] in intersection_osm_ids:
                    split_indices.append(idx)
            split_indices.append(len(refs) - 1)

            for part_idx, (start_i, end_i) in enumerate(zip(split_indices[:-1], split_indices[1:]), start=1):
                sub_refs = refs[start_i : end_i + 1]
                u_osm = sub_refs[0]
                v_osm = sub_refs[-1]
                if u_osm == v_osm:
                    skipped += 1
                    continue

                poly_coords: list[tuple[float, float]] = []
                poly_dist_km = 0.0
                for r_idx, r_id in enumerate(sub_refs):
                    nr = raw_nodes[r_id]
                    min_lat = min(min_lat, nr.lat)
                    max_lat = max(max_lat, nr.lat)
                    min_lon = min(min_lon, nr.lon)
                    max_lon = max(max_lon, nr.lon)
                    poly_coords.append((nr.lon, nr.lat))
                    if r_idx > 0:
                        prev_nr = raw_nodes[sub_refs[r_idx - 1]]
                        poly_dist_km += haversine_km(
                            GeoPoint(prev_nr.lat, prev_nr.lon),
                            GeoPoint(nr.lat, nr.lon),
                        )

                poly_dist_km = max(round(poly_dist_km, 4), 0.005)
                mid_nr = raw_nodes[sub_refs[len(sub_refs) // 2]]
                admin = self.spatial_db.resolve_administrative_area(mid_nr.lat, mid_nr.lon)
                st_code = resolved_state_code or admin["state_code"]
                dist_id = district_id or admin["district_id"]
                ct_id = city_id or admin["city_id"]

                seg_id = (
                    f"osm_w_{way.osm_way_id}"
                    if len(split_indices) == 2
                    else f"osm_w_{way.osm_way_id}_p{part_idx}"
                )
                rseg = RoadSegment(
                    id=seg_id,
                    name=way_name,
                    source=f"osm_n_{u_osm}",
                    target=f"osm_n_{v_osm}",
                    distance_km=poly_dist_km,
                    lanes=lanes,
                    region=region_name,
                    bidirectional=bidirectional,
                    congestion_level="LOW",
                    congestion_penalty=0.10,
                    closed=access in {"no", "private"},
                    closure_reason=f"OSM access={access}" if access in {"no", "private"} else None,
                    osm_way_id=way.osm_way_id,
                    highway=highway,
                    surface=surface,
                    maxspeed_kmh=maxspeed,
                    oneway=oneway,
                    access=access,
                    is_bridge=is_bridge,
                    is_tunnel=is_tunnel,
                    state_code=st_code,
                    district_id=dist_id,
                    city_id=ct_id,
                    geometry=poly_coords,
                    is_synthetic=False,
                    osm_tags=tags,
                )
                self.road_network.add_segment(rseg, allow_upsert=True)
                created_segments.append(rseg)

        # Persist to SpatialDatabase
        self.spatial_db.sync_from_road_network(self.road_network)

        completed_at = _utc_now_iso()
        import_id = f"osm_imp_{uuid.uuid4().hex[:10]}"
        self.spatial_db.record_import_batch(
            {
                "import_id": import_id,
                "region_name": region_name,
                "state_code": resolved_state_code,
                "source_file": str(path),
                "source_format": fmt,
                "source_url": source_url,
                "file_sha256": sha256,
                "file_size_bytes": path.stat().st_size,
                "status": "completed",
                "imported_nodes": len(created_nodes),
                "imported_roads": len(created_segments),
                "skipped_elements": skipped,
                "min_lon": round(min_lon, 6),
                "min_lat": round(min_lat, 6),
                "max_lon": round(max_lon, 6),
                "max_lat": round(max_lat, 6),
                "licence": OSM_LICENCE,
                "attribution": OSM_ATTRIBUTION,
                "started_at": started_at,
                "completed_at": completed_at,
            }
        )

        return OSMImportReport(
            import_id=import_id,
            region_name=region_name,
            state_code=resolved_state_code,
            source_path=str(path),
            source_format=fmt,
            source_url=source_url,
            licence=OSM_LICENCE,
            attribution=OSM_ATTRIBUTION,
            file_sha256=sha256,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            imported_nodes=len(created_nodes),
            imported_roads=len(created_segments),
            skipped_elements=skipped,
            bbox={
                "min_lon": round(min_lon, 6),
                "min_lat": round(min_lat, 6),
                "max_lon": round(max_lon, 6),
                "max_lat": round(max_lat, 6),
            },
            notes=[
                f"Imported {len(created_nodes)} topological intersection nodes and {len(created_segments)} road segments.",
                f"Attribution: {OSM_ATTRIBUTION} ({OSM_LICENCE}).",
            ],
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="UrbanFlow AI — OpenStreetMap Regional Road Network Ingestion CLI"
    )
    parser.add_argument("file", help="Path to regional .osm.pbf, .osm, .osm.json, or .geojson file")
    parser.add_argument("--region", required=True, help="Region/city label (e.g. 'Bengaluru Central', 'Mumbai South')")
    parser.add_argument("--state", default=None, help="Indian State/UT ISO code or name (e.g. KA, MH, DL)")
    parser.add_argument("--district", default=None, help="Optional district ID (e.g. KA-BLR)")
    parser.add_argument("--city", default=None, help="Optional city ID (e.g. IN-BLR)")
    parser.add_argument("--source-url", default=OSM_SOURCE_URL, help="OSM extract source URL")
    parser.add_argument("--force", action="store_true", help="Force re-import even if SHA-256 matches previous batch")
    args = parser.parse_args(argv)

    from backend.services.vision_engine import get_platform_state

    state = get_platform_state()
    report = state.osm_ingestor.ingest_file(
        args.file,
        region_name=args.region,
        state_code=args.state,
        district_id=args.district,
        city_id=args.city,
        source_url=args.source_url,
        force_reimport=args.force,
    )
    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
