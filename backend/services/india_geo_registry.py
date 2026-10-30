"""Reference administrative metadata for all 28 Indian States and 8 Union Territories,
representative districts, cities/towns, and official Geofabrik OpenStreetMap regional extracts.

Licence & Attribution:
- Geographic road data imported from OpenStreetMap is licensed under the Open Data Commons
  Open Database License (ODbL 1.0) by the OpenStreetMap Foundation:
  © OpenStreetMap contributors (https://www.openstreetmap.org/copyright).
- Geofabrik regional extract server: https://download.geofabrik.de/asia/india.html
"""

from __future__ import annotations

from typing import Any

OSM_ATTRIBUTION = "© OpenStreetMap contributors (https://www.openstreetmap.org/copyright)"
OSM_LICENCE = "ODbL-1.0 (Open Data Commons Open Database License)"
OSM_LICENCE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
GEOFABRIK_INDIA_INDEX_URL = "https://download.geofabrik.de/asia/india.html"
OSM_SOURCE_URL = GEOFABRIK_INDIA_INDEX_URL

# Geographic bounding envelope of India (WGS84 / SRID 4326)
INDIA_MIN_LAT = 6.0
INDIA_MAX_LAT = 37.5
INDIA_MIN_LON = 68.0
INDIA_MAX_LON = 97.5

GEOFABRIK_ZONES: dict[str, dict[str, str]] = {
    "Southern Zone": {
        "zone_id": "southern-zone",
        "pbf_url": "https://download.geofabrik.de/asia/india/southern-zone-latest.osm.pbf",
        "approx_size_mb": "420 MB",
    },
    "Western Zone": {
        "zone_id": "western-zone",
        "pbf_url": "https://download.geofabrik.de/asia/india/western-zone-latest.osm.pbf",
        "approx_size_mb": "260 MB",
    },
    "Northern Zone": {
        "zone_id": "northern-zone",
        "pbf_url": "https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf",
        "approx_size_mb": "310 MB",
    },
    "Central Zone": {
        "zone_id": "central-zone",
        "pbf_url": "https://download.geofabrik.de/asia/india/central-zone-latest.osm.pbf",
        "approx_size_mb": "240 MB",
    },
    "Eastern Zone": {
        "zone_id": "eastern-zone",
        "pbf_url": "https://download.geofabrik.de/asia/india/eastern-zone-latest.osm.pbf",
        "approx_size_mb": "230 MB",
    },
    "North-Eastern Zone": {
        "zone_id": "north-eastern-zone",
        "pbf_url": "https://download.geofabrik.de/asia/india/north-eastern-zone-latest.osm.pbf",
        "approx_size_mb": "110 MB",
    },
}

# Complete list of all 28 Indian States and 8 Union Territories (36 total)
# Format: (code, name, territory_type, capital, zone, iso_code, center_lat, center_lon, min_lon, min_lat, max_lon, max_lat)
INDIA_STATES_AND_UTS: list[tuple[str, str, str, str, str, str, float, float, float, float, float, float]] = [
    # 28 States
    ("AP", "Andhra Pradesh", "state", "Amaravati", "Southern Zone", "IN-AP", 15.9129, 79.7400, 76.76, 12.62, 84.76, 19.17),
    ("AR", "Arunachal Pradesh", "state", "Itanagar", "North-Eastern Zone", "IN-AR", 28.2180, 94.7278, 91.55, 26.64, 97.40, 29.46),
    ("AS", "Assam", "state", "Dispur", "North-Eastern Zone", "IN-AS", 26.2006, 92.9376, 89.69, 24.13, 96.02, 27.97),
    ("BR", "Bihar", "state", "Patna", "Eastern Zone", "IN-BR", 25.0961, 85.3131, 83.32, 24.28, 88.29, 27.52),
    ("CT", "Chhattisgarh", "state", "Raipur", "Central Zone", "IN-CT", 21.2787, 81.8661, 80.24, 17.78, 84.39, 24.11),
    ("GA", "Goa", "state", "Panaji", "Western Zone", "IN-GA", 15.2993, 74.1240, 73.68, 14.90, 74.34, 15.80),
    ("GJ", "Gujarat", "state", "Gandhinagar", "Western Zone", "IN-GJ", 22.2587, 71.1924, 68.16, 20.12, 74.48, 24.71),
    ("HR", "Haryana", "state", "Chandigarh", "Northern Zone", "IN-HR", 29.0588, 76.0856, 74.46, 27.65, 77.60, 30.93),
    ("HP", "Himachal Pradesh", "state", "Shimla", "Northern Zone", "IN-HP", 31.1048, 77.1734, 75.59, 30.38, 79.01, 33.26),
    ("JH", "Jharkhand", "state", "Ranchi", "Eastern Zone", "IN-JH", 23.6102, 85.2799, 83.32, 21.97, 87.95, 25.35),
    ("KA", "Karnataka", "state", "Bengaluru", "Southern Zone", "IN-KA", 15.3173, 75.7139, 74.05, 11.59, 78.58, 18.45),
    ("KL", "Kerala", "state", "Thiruvananthapuram", "Southern Zone", "IN-KL", 10.8505, 76.2711, 74.86, 8.29, 77.42, 12.79),
    ("MP", "Madhya Pradesh", "state", "Bhopal", "Central Zone", "IN-MP", 22.9734, 78.6569, 74.03, 21.08, 82.81, 26.87),
    ("MH", "Maharashtra", "state", "Mumbai", "Western Zone", "IN-MH", 19.7515, 75.7139, 72.65, 15.60, 80.89, 22.03),
    ("MN", "Manipur", "state", "Imphal", "North-Eastern Zone", "IN-MN", 24.6637, 93.9063, 92.97, 23.83, 94.78, 25.69),
    ("ML", "Meghalaya", "state", "Shillong", "North-Eastern Zone", "IN-ML", 25.4670, 91.3662, 89.82, 25.03, 92.80, 26.12),
    ("MZ", "Mizoram", "state", "Aizawl", "North-Eastern Zone", "IN-MZ", 23.1645, 92.9376, 92.26, 21.94, 93.44, 24.52),
    ("NL", "Nagaland", "state", "Kohima", "North-Eastern Zone", "IN-NL", 26.1584, 94.5624, 93.33, 25.20, 95.24, 27.04),
    ("OR", "Odisha", "state", "Bhubaneswar", "Eastern Zone", "IN-OR", 20.9517, 85.0985, 81.39, 17.78, 87.48, 22.57),
    ("PB", "Punjab", "state", "Chandigarh", "Northern Zone", "IN-PB", 31.1471, 75.3412, 73.88, 29.54, 76.94, 32.51),
    ("RJ", "Rajasthan", "state", "Jaipur", "Northern Zone", "IN-RJ", 27.0238, 74.2179, 69.48, 23.06, 78.27, 30.19),
    ("SK", "Sikkim", "state", "Gangtok", "North-Eastern Zone", "IN-SK", 27.5330, 88.5122, 88.01, 27.08, 88.92, 28.13),
    ("TN", "Tamil Nadu", "state", "Chennai", "Southern Zone", "IN-TN", 11.1271, 78.6569, 76.23, 8.07, 80.35, 13.56),
    ("TG", "Telangana", "state", "Hyderabad", "Southern Zone", "IN-TG", 18.1124, 79.0193, 77.23, 15.83, 81.32, 19.92),
    ("TR", "Tripura", "state", "Agartala", "North-Eastern Zone", "IN-TR", 23.9408, 91.9882, 91.15, 22.94, 92.34, 24.53),
    ("UP", "Uttar Pradesh", "state", "Lucknow", "Central Zone", "IN-UP", 26.8467, 80.9462, 77.09, 23.87, 84.63, 30.41),
    ("UT", "Uttarakhand", "state", "Dehradun", "Central Zone", "IN-UT", 30.0668, 79.0193, 77.57, 28.72, 81.04, 31.46),
    ("WB", "West Bengal", "state", "Kolkata", "Eastern Zone", "IN-WB", 22.9868, 87.8550, 85.82, 21.53, 89.88, 27.22),
    # 8 Union Territories
    ("AN", "Andaman and Nicobar Islands", "union_territory", "Port Blair", "Southern Zone", "IN-AN", 11.7401, 92.6586, 92.19, 6.75, 94.30, 13.68),
    ("CH", "Chandigarh", "union_territory", "Chandigarh", "Northern Zone", "IN-CH", 30.7333, 76.7794, 76.70, 30.66, 76.85, 30.80),
    ("DH", "Dadra and Nagar Haveli and Daman and Diu", "union_territory", "Daman", "Western Zone", "IN-DH", 20.3974, 72.8328, 70.86, 20.06, 73.22, 20.77),
    ("DL", "Delhi", "union_territory", "New Delhi", "Northern Zone", "IN-DL", 28.6139, 77.2090, 76.84, 28.40, 77.35, 28.88),
    ("JK", "Jammu and Kashmir", "union_territory", "Srinagar", "Northern Zone", "IN-JK", 33.7782, 76.5762, 73.76, 32.28, 76.82, 35.09),
    ("LA", "Ladakh", "union_territory", "Leh", "Northern Zone", "IN-LA", 34.1526, 77.5771, 75.30, 32.49, 80.32, 35.85),
    ("LD", "Lakshadweep", "union_territory", "Kavaratti", "Southern Zone", "IN-LD", 10.5667, 72.6417, 71.70, 8.26, 73.68, 12.39),
    ("PY", "Puducherry", "union_territory", "Puducherry", "Southern Zone", "IN-PY", 11.9416, 79.8083, 75.50, 10.76, 82.32, 16.80),
]

# Representative districts across Indian states and UTs
# Format: (id, name, state_code, state_name, headquarters, center_lat, center_lon, min_lon, min_lat, max_lon, max_lat)
INDIA_DISTRICTS: list[tuple[str, str, str, str, str, float, float, float, float, float, float]] = [
    ("KA_BLR_U", "Bengaluru Urban", "KA", "Karnataka", "Bengaluru", 12.9716, 77.5946, 77.40, 12.75, 77.85, 13.18),
    ("KA_BLR_R", "Bengaluru Rural", "KA", "Karnataka", "Devanahalli", 13.2257, 77.5750, 77.20, 13.00, 77.95, 13.50),
    ("KA_MYS", "Mysuru", "KA", "Karnataka", "Mysuru", 12.2958, 76.6394, 75.95, 11.95, 77.15, 12.65),
    ("KA_DK", "Dakshina Kannada", "KA", "Karnataka", "Mangaluru", 12.9141, 74.8560, 74.75, 12.50, 75.65, 13.20),
    ("KA_DWR", "Dharwad", "KA", "Karnataka", "Dharwad", 15.4589, 75.0078, 74.70, 15.15, 75.40, 15.75),
    ("MH_MUM", "Mumbai City", "MH", "Maharashtra", "Mumbai", 18.9388, 72.8354, 72.77, 18.89, 72.99, 19.28),
    ("MH_PUN", "Pune", "MH", "Maharashtra", "Pune", 18.5204, 73.8567, 73.30, 17.90, 75.10, 19.35),
    ("MH_NAG", "Nagpur", "MH", "Maharashtra", "Nagpur", 21.1458, 79.0882, 78.40, 20.60, 79.65, 21.70),
    ("TN_CHN", "Chennai", "TN", "Tamil Nadu", "Chennai", 13.0827, 80.2707, 80.12, 12.90, 80.35, 13.25),
    ("TN_CBE", "Coimbatore", "TN", "Tamil Nadu", "Coimbatore", 11.0168, 76.9558, 76.65, 10.25, 77.30, 11.40),
    ("TG_HYD", "Hyderabad", "TG", "Telangana", "Hyderabad", 17.3850, 78.4867, 78.30, 17.25, 78.65, 17.55),
    ("DL_NDL", "New Delhi", "DL", "Delhi", "New Delhi", 28.6139, 77.2090, 77.05, 28.50, 77.32, 28.72),
    ("WB_KOL", "Kolkata", "WB", "West Bengal", "Kolkata", 22.5726, 88.3639, 88.25, 22.45, 88.45, 22.65),
    ("GJ_AMD", "Ahmedabad", "GJ", "Gujarat", "Ahmedabad", 23.0225, 72.5714, 71.95, 22.10, 72.95, 23.50),
    ("RJ_JAI", "Jaipur", "RJ", "Rajasthan", "Jaipur", 26.9124, 75.7873, 75.00, 26.40, 76.30, 27.80),
    ("UP_LKO", "Lucknow", "UP", "Uttar Pradesh", "Lucknow", 26.8467, 80.9462, 80.50, 26.50, 81.25, 27.20),
    ("KL_TVM", "Thiruvananthapuram", "KL", "Kerala", "Thiruvananthapuram", 8.5241, 76.9366, 76.65, 8.29, 77.28, 8.88),
    ("KL_EKM", "Ernakulam", "KL", "Kerala", "Kakkanad", 9.9816, 76.2999, 76.15, 9.78, 76.85, 10.30),
    ("AP_VSP", "Visakhapatnam", "AP", "Andhra Pradesh", "Visakhapatnam", 17.6868, 83.2185, 82.90, 17.40, 83.50, 18.05),
    ("AS_KMR", "Kamrup Metropolitan", "AS", "Assam", "Guwahati", 26.1445, 91.7362, 91.50, 25.95, 92.10, 26.30),
]

# Representative cities and towns
# Format: (id, name, district_id, district_name, state_code, state_name, place_type, population, lat, lon)
INDIA_CITIES: list[tuple[str, str, str, str, str, str, str, int, float, float]] = [
    ("city_bengaluru", "Bengaluru", "KA_BLR_U", "Bengaluru Urban", "KA", "Karnataka", "metropolis", 12327000, 12.9716, 77.5946),
    ("city_yelahanka", "Yelahanka", "KA_BLR_U", "Bengaluru Urban", "KA", "Karnataka", "town", 300000, 13.1007, 77.5963),
    ("city_electronic_city", "Electronic City", "KA_BLR_U", "Bengaluru Urban", "KA", "Karnataka", "town", 180000, 12.8452, 77.6602),
    ("city_devanahalli", "Devanahalli", "KA_BLR_R", "Bengaluru Rural", "KA", "Karnataka", "town", 45000, 13.2466, 77.7118),
    ("city_mysuru", "Mysuru", "KA_MYS", "Mysuru", "KA", "Karnataka", "city", 1200000, 12.2958, 76.6394),
    ("city_mangaluru", "Mangaluru", "KA_DK", "Dakshina Kannada", "KA", "Karnataka", "city", 720000, 12.9141, 74.8560),
    ("city_hubballi", "Hubballi-Dharwad", "KA_DWR", "Dharwad", "KA", "Karnataka", "city", 1150000, 15.3647, 75.1240),
    ("city_mumbai", "Mumbai", "MH_MUM", "Mumbai City", "MH", "Maharashtra", "metropolis", 20411000, 19.0760, 72.8777),
    ("city_pune", "Pune", "MH_PUN", "Pune", "MH", "Maharashtra", "metropolis", 6987000, 18.5204, 73.8567),
    ("city_nagpur", "Nagpur", "MH_NAG", "Nagpur", "MH", "Maharashtra", "city", 2940000, 21.1458, 79.0882),
    ("city_chennai", "Chennai", "TN_CHN", "Chennai", "TN", "Tamil Nadu", "metropolis", 11503000, 13.0827, 80.2707),
    ("city_coimbatore", "Coimbatore", "TN_CBE", "Coimbatore", "TN", "Tamil Nadu", "city", 2150000, 11.0168, 76.9558),
    ("city_hyderabad", "Hyderabad", "TG_HYD", "Hyderabad", "TG", "Telangana", "metropolis", 10534000, 17.3850, 78.4867),
    ("city_new_delhi", "New Delhi", "DL_NDL", "New Delhi", "DL", "Delhi", "metropolis", 16787941, 28.6139, 77.2090),
    ("city_kolkata", "Kolkata", "WB_KOL", "Kolkata", "WB", "West Bengal", "metropolis", 14850000, 22.5726, 88.3639),
    ("city_ahmedabad", "Ahmedabad", "GJ_AMD", "Ahmedabad", "GJ", "Gujarat", "metropolis", 8450000, 23.0225, 72.5714),
    ("city_jaipur", "Jaipur", "RJ_JAI", "Jaipur", "RJ", "Rajasthan", "city", 4067000, 26.9124, 75.7873),
    ("city_lucknow", "Lucknow", "UP_LKO", "Lucknow", "UP", "Uttar Pradesh", "city", 3790000, 26.8467, 80.9462),
    ("city_kochi", "Kochi", "KL_EKM", "Ernakulam", "KL", "Kerala", "city", 2119000, 9.9312, 76.2673),
    ("city_guwahati", "Guwahati", "AS_KMR", "Kamrup Metropolitan", "AS", "Assam", "city", 1150000, 26.1445, 91.7362),
]


def find_state(query: str) -> dict[str, Any] | None:
    """Resolve an Indian state or UT by 2-letter code, ISO code (IN-XX), or full name."""
    q = query.strip().lower()
    if not q:
        return None
    for row in INDIA_STATES_AND_UTS:
        code, name, ttype, capital, zone, iso_code, clat, clon, min_lon, min_lat, max_lon, max_lat = row
        if q in {code.lower(), iso_code.lower(), name.lower()}:
            return {
                "code": code,
                "name": name,
                "territory_type": ttype,
                "capital": capital,
                "zone": zone,
                "iso_code": iso_code,
                "center_lat": clat,
                "center_lon": clon,
                "bbox": {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                },
            }
    return None

