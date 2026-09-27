"""State/UT + city reference tables and boundary GeoJSON (36 units, ISO 3166-2:IN, 2020+ codes)."""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from src.data.cache import RAW, fetch

# code, name, is_ut, zone (Zonal-Council style; Central split out of North), coastal
STATES: list[tuple[str, str, bool, str, bool]] = [
    ("IN-AP", "Andhra Pradesh", False, "South", True),
    ("IN-AR", "Arunachal Pradesh", False, "Northeast", False),
    ("IN-AS", "Assam", False, "Northeast", False),
    ("IN-BR", "Bihar", False, "East", False),
    ("IN-CG", "Chhattisgarh", False, "Central", False),
    ("IN-GA", "Goa", False, "West", True),
    ("IN-GJ", "Gujarat", False, "West", True),
    ("IN-HR", "Haryana", False, "North", False),
    ("IN-HP", "Himachal Pradesh", False, "North", False),
    ("IN-JH", "Jharkhand", False, "East", False),
    ("IN-KA", "Karnataka", False, "South", True),
    ("IN-KL", "Kerala", False, "South", True),
    ("IN-MP", "Madhya Pradesh", False, "Central", False),
    ("IN-MH", "Maharashtra", False, "West", True),
    ("IN-MN", "Manipur", False, "Northeast", False),
    ("IN-ML", "Meghalaya", False, "Northeast", False),
    ("IN-MZ", "Mizoram", False, "Northeast", False),
    ("IN-NL", "Nagaland", False, "Northeast", False),
    ("IN-OD", "Odisha", False, "East", True),
    ("IN-PB", "Punjab", False, "North", False),
    ("IN-RJ", "Rajasthan", False, "North", False),
    ("IN-SK", "Sikkim", False, "Northeast", False),
    ("IN-TN", "Tamil Nadu", False, "South", True),
    ("IN-TS", "Telangana", False, "South", False),
    ("IN-TR", "Tripura", False, "Northeast", False),
    ("IN-UP", "Uttar Pradesh", False, "Central", False),
    ("IN-UK", "Uttarakhand", False, "Central", False),
    ("IN-WB", "West Bengal", False, "East", True),
    ("IN-AN", "Andaman and Nicobar Islands", True, "East", True),
    ("IN-CH", "Chandigarh", True, "North", False),
    ("IN-DH", "Dadra and Nagar Haveli and Daman and Diu", True, "West", True),
    ("IN-DL", "Delhi", True, "North", False),
    ("IN-JK", "Jammu and Kashmir", True, "North", False),
    ("IN-LA", "Ladakh", True, "North", False),
    ("IN-LD", "Lakshadweep", True, "South", True),
    ("IN-PY", "Puducherry", True, "South", True),
]
STATE_CODES = [s[0] for s in STATES]
assert len(STATE_CODES) == 36 and len(set(STATE_CODES)) == 36


def states_df() -> pd.DataFrame:
    return pd.DataFrame(STATES, columns=["code", "name", "is_ut", "region", "coastal"])


# Name aliases seen across sources (upper-cased, '&'->'AND', non-alnum stripped) -> code.
_ALIASES = {
    "ANDAMANNICOBAR": "IN-AN", "ANDAMANNICOBARISLANDS": "IN-AN", "ANDAMANANDNICOBARISLANDS": "IN-AN",
    "ANDAMANANDNICOBAR": "IN-AN", "ANDAMANANDNICOBARISLAND": "IN-AN", "ARUNANCHALPRADESH": "IN-AR",
    "DADRANAGARHAVELI": "IN-DH", "DADRAANDNAGARHAVELI": "IN-DH", "DAMANDIU": "IN-DH", "DAMANANDDIU": "IN-DH",
    "DADRAANDNAGARHAVELIANDDAMANANDDIU": "IN-DH", "DNHDD": "IN-DH",
    "NCTOFDELHI": "IN-DL", "DELHI": "IN-DL", "NCTDELHI": "IN-DL",
    "JAMMUKASHMIR": "IN-JK", "JAMMUANDKASHMIR": "IN-JK", "ORISSA": "IN-OD", "PONDICHERRY": "IN-PY",
    "UTTARANCHAL": "IN-UK", "CHHATISGARH": "IN-CG", "TAMILNADU": "IN-TN", "JANDK": "IN-JK",
}


def _key(name: str) -> str:
    return "".join(ch for ch in str(name).upper().replace("&", "AND") if ch.isalnum())


def name_to_code(name: str) -> str | None:
    k = _key(name)
    for code, nm, *_ in STATES:
        if _key(nm) == k:
            return code
    return _ALIASES.get(k) or _ALIASES.get(k.replace("AND", ""))


# Hindi names (Devanagari) for bilingual UI/insights.
NAME_HI = {
    "IN-AP": "आंध्र प्रदेश", "IN-AR": "अरुणाचल प्रदेश", "IN-AS": "असम", "IN-BR": "बिहार", "IN-CG": "छत्तीसगढ़",
    "IN-GA": "गोवा", "IN-GJ": "गुजरात", "IN-HR": "हरियाणा", "IN-HP": "हिमाचल प्रदेश", "IN-JH": "झारखंड",
    "IN-KA": "कर्नाटक", "IN-KL": "केरल", "IN-MP": "मध्य प्रदेश", "IN-MH": "महाराष्ट्र", "IN-MN": "मणिपुर",
    "IN-ML": "मेघालय", "IN-MZ": "मिज़ोरम", "IN-NL": "नागालैंड", "IN-OD": "ओडिशा", "IN-PB": "पंजाब",
    "IN-RJ": "राजस्थान", "IN-SK": "सिक्किम", "IN-TN": "तमिलनाडु", "IN-TS": "तेलंगाना", "IN-TR": "त्रिपुरा",
    "IN-UP": "उत्तर प्रदेश", "IN-UK": "उत्तराखंड", "IN-WB": "पश्चिम बंगाल", "IN-AN": "अंडमान और निकोबार द्वीपसमूह",
    "IN-CH": "चंडीगढ़", "IN-DH": "दादरा और नगर हवेली और दमन और दीव", "IN-DL": "दिल्ली", "IN-JK": "जम्मू और कश्मीर",
    "IN-LA": "लद्दाख", "IN-LD": "लक्षद्वीप", "IN-PY": "पुडुचेरी",
}


# ---- boundaries --------------------------------------------------------------
BOUNDARY_SOURCES = [
    # 37 polygons incl. Ladakh; DNH and DD separate -> dissolved into IN-DH
    ("datta07/INDIAN-SHAPEFILES", "https://raw.githubusercontent.com/datta07/INDIAN-SHAPEFILES/master/INDIA/INDIA_STATES.geojson", "STNAME"),
    # district-level mirror (post-2020 states incl. Ladakh) -> dissolved by st_nm
    ("udit-001/india-maps-data", "https://raw.githubusercontent.com/udit-001/india-maps-data/main/geojson/india.geojson", "st_nm"),
]


def load_boundaries() -> gpd.GeoDataFrame:
    """36 state/UT polygons in EPSG:4326 with `code` and `boundary_source`. Tries mirrors in order."""
    last_err: Exception | None = None
    for label, url, col in BOUNDARY_SOURCES:
        try:
            path = fetch(url, RAW / "boundaries" / f"{label.replace('/', '_')}.geojson")
            g = gpd.read_file(path)
            g = g.set_crs(4326) if g.crs is None else g.to_crs(4326)
            g["code"] = g[col].map(name_to_code)
            g = g.dropna(subset=["code"])
            g["geometry"] = g.geometry.make_valid()
            g = g[["code", "geometry"]].dissolve(by="code").reset_index()
            validate_codes(g["code"])
            g["boundary_source"] = label
            return g.merge(states_df(), on="code")
        except Exception as e:  # noqa: BLE001 — fall through to next mirror
            last_err = e
    raise RuntimeError(f"all boundary sources failed: {last_err}")


def validate_codes(codes) -> None:
    got = set(codes)
    missing, extra = set(STATE_CODES) - got, got - set(STATE_CODES)
    if missing or extra or len(list(codes)) != 36:
        raise ValueError(f"boundary validation failed: missing={sorted(missing)} extra={sorted(extra)}")


# ---- cities -----------------------------------------------------------------
# All state/UT capitals + metros + million-plus UAs (Census 2011). lat/lon = city centre.
# tier: 'metro' (Census 2011 UA > 4M) uses a 25 km buffer; others 12 km.
CITIES: list[tuple[str, str, float, float, bool]] = [
    ("Delhi", "IN-DL", 28.6139, 77.2090, True), ("Mumbai", "IN-MH", 19.0760, 72.8777, True),
    ("Kolkata", "IN-WB", 22.5726, 88.3639, True), ("Chennai", "IN-TN", 13.0827, 80.2707, True),
    ("Bengaluru", "IN-KA", 12.9716, 77.5946, True), ("Hyderabad", "IN-TS", 17.3850, 78.4867, True),
    ("Ahmedabad", "IN-GJ", 23.0225, 72.5714, True), ("Pune", "IN-MH", 18.5204, 73.8567, True),
    ("Surat", "IN-GJ", 21.1702, 72.8311, True), ("Jaipur", "IN-RJ", 26.9124, 75.7873, False),
    ("Lucknow", "IN-UP", 26.8467, 80.9462, False), ("Kanpur", "IN-UP", 26.4499, 80.3319, False),
    ("Nagpur", "IN-MH", 21.1458, 79.0882, False), ("Indore", "IN-MP", 22.7196, 75.8577, False),
    ("Bhopal", "IN-MP", 23.2599, 77.4126, False), ("Patna", "IN-BR", 25.5941, 85.1376, False),
    ("Vadodara", "IN-GJ", 22.3072, 73.1812, False), ("Ludhiana", "IN-PB", 30.9010, 75.8573, False),
    ("Agra", "IN-UP", 27.1767, 78.0081, False), ("Nashik", "IN-MH", 19.9975, 73.7898, False),
    ("Visakhapatnam", "IN-AP", 17.6868, 83.2185, False), ("Coimbatore", "IN-TN", 11.0168, 76.9558, False),
    ("Kochi", "IN-KL", 9.9312, 76.2673, False), ("Madurai", "IN-TN", 9.9252, 78.1198, False),
    ("Varanasi", "IN-UP", 25.3176, 82.9739, False), ("Meerut", "IN-UP", 28.9845, 77.7064, False),
    ("Rajkot", "IN-GJ", 22.3039, 70.8022, False), ("Jamshedpur", "IN-JH", 22.8046, 86.2029, False),
    ("Asansol", "IN-WB", 23.6739, 86.9524, False), ("Dhanbad", "IN-JH", 23.7957, 86.4304, False),
    ("Aurangabad", "IN-MH", 19.8762, 75.3433, False), ("Allahabad", "IN-UP", 25.4358, 81.8463, False),
    ("Amritsar", "IN-PB", 31.6340, 74.8723, False), ("Vijayawada", "IN-AP", 16.5062, 80.6480, False),
    ("Raipur", "IN-CG", 21.2514, 81.6296, False), ("Gwalior", "IN-MP", 26.2183, 78.1828, False),
    ("Jabalpur", "IN-MP", 23.1815, 79.9864, False), ("Jodhpur", "IN-RJ", 26.2389, 73.0243, False),
    ("Kota", "IN-RJ", 25.2138, 75.8648, False), ("Ranchi", "IN-JH", 23.3441, 85.3096, False),
    ("Thiruvananthapuram", "IN-KL", 8.5241, 76.9366, False), ("Chandigarh", "IN-CH", 30.7333, 76.7794, False),
    ("Guwahati", "IN-AS", 26.1445, 91.7362, False), ("Bhubaneswar", "IN-OD", 20.2961, 85.8245, False),
    ("Dehradun", "IN-UK", 30.3165, 78.0322, False), ("Srinagar", "IN-JK", 34.0837, 74.7973, False),
    ("Shimla", "IN-HP", 31.1048, 77.1734, False), ("Panaji", "IN-GA", 15.4909, 73.8278, False),
    ("Gandhinagar", "IN-GJ", 23.2156, 72.6369, False), ("Imphal", "IN-MN", 24.8170, 93.9368, False),
    ("Shillong", "IN-ML", 25.5788, 91.8933, False), ("Aizawl", "IN-MZ", 23.7271, 92.7176, False),
    ("Kohima", "IN-NL", 25.6751, 94.1086, False), ("Agartala", "IN-TR", 23.8315, 91.2868, False),
    ("Gangtok", "IN-SK", 27.3389, 88.6065, False), ("Itanagar", "IN-AR", 27.0844, 93.6053, False),
    ("Puducherry", "IN-PY", 11.9416, 79.8083, False), ("Port Blair", "IN-AN", 11.6234, 92.7265, False),
    ("Leh", "IN-LA", 34.1526, 77.5771, False), ("Kavaratti", "IN-LD", 10.5669, 72.6420, False),
    ("Silvassa", "IN-DH", 20.2766, 73.0169, False), ("Faridabad", "IN-HR", 28.4089, 77.3178, False),
    ("Ghaziabad", "IN-UP", 28.6692, 77.4538, False), ("Amaravati", "IN-AP", 16.5131, 80.5165, False),
]


def cities_df() -> pd.DataFrame:
    df = pd.DataFrame(CITIES, columns=["name", "state_code", "lat", "lon", "is_metro"])
    df.insert(0, "id", range(1, len(df) + 1))
    df["buffer_km"] = df.is_metro.map({True: 25.0, False: 12.0})
    df["estimation_method"] = "EDGAR-grid-buffer"
    # 0.1° EDGAR cells (~11 km) resolve metros reasonably; small cities are dominated by 1-4 cells.
    df["confidence_tier"] = df.is_metro.map({True: "B", False: "C"})
    return df
