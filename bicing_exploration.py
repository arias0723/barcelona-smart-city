"""
bicing_exploration.py
=====================
Exploratory analysis of Barcelona's Bicing bike-share system via the
BSM GBFS v2 API (no authentication required).

Endpoints used:
  - station_information: static metadata (name, lat/lon, capacity…)
  - station_status     : real-time availability (bikes, docks, e-bikes…)

Run:
    python3 bicing_exploration.py
"""

import math
import time
import json
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    raise SystemExit("Install 'requests': pip install requests")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en"
STATION_INFO_URL = f"{BASE_URL}/station_information.json"
STATION_STATUS_URL = f"{BASE_URL}/station_status.json"

SAGRADA_FAMILIA = (41.4036, 2.1744)  # (lat, lon)
STALE_THRESHOLD_SECONDS = 1800       # 30 minutes


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def fetch_with_retry(url: str, max_attempts: int = 5, base_delay: float = 1.0) -> dict | None:
    """
    GET *url* with exponential back-off on HTTP 503 / connection errors.
    Returns parsed JSON dict on success, None if all attempts fail.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 503:
                wait = base_delay * (2 ** (attempt - 1))
                print(f"  [attempt {attempt}/{max_attempts}] 503 Service Unavailable — retrying in {wait:.0f}s …")
                time.sleep(wait)
            else:
                print(f"  [attempt {attempt}/{max_attempts}] Unexpected HTTP {resp.status_code} — aborting.")
                return None
        except requests.exceptions.ConnectionError as exc:
            wait = base_delay * (2 ** (attempt - 1))
            print(f"  [attempt {attempt}/{max_attempts}] Connection error ({exc}) — retrying in {wait:.0f}s …")
            time.sleep(wait)
        except requests.exceptions.Timeout:
            wait = base_delay * (2 ** (attempt - 1))
            print(f"  [attempt {attempt}/{max_attempts}] Timeout — retrying in {wait:.0f}s …")
            time.sleep(wait)

    print(f"  All {max_attempts} attempts failed for {url}")
    return None


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two (lat, lon) points."""
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------
def median(values: list) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------
def main():
    print("=" * 65)
    print("  BICING GBFS v2 — Live Data Exploration")
    print(f"  Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S local')}")
    print("=" * 65)

    # ------------------------------------------------------------------
    # 1. Fetch data
    # ------------------------------------------------------------------
    print("\n[1/6] Fetching station_information …")
    info_raw = fetch_with_retry(STATION_INFO_URL)

    print("[1/6] Fetching station_status …")
    status_raw = fetch_with_retry(STATION_STATUS_URL)

    if info_raw is None or status_raw is None:
        print("\n*** Bicing API is currently unavailable (503). ***")
        print("    This is a transient service outage on BSM's side.")
        print("    The script implements exponential back-off (5 retries).")
        print("    Field inventory below is derived from GBFS v2 spec + BSM docs.\n")
        print_gbfs_field_reference()
        return

    # ------------------------------------------------------------------
    # 2. Parse + join
    # ------------------------------------------------------------------
    print("\n[2/6] Parsing and joining datasets …")
    info_list   = info_raw["data"]["stations"]
    status_list = status_raw["data"]["stations"]

    # Build lookup: station_id -> status record
    status_map = {s["station_id"]: s for s in status_list}

    # Merge
    stations = []
    for info in info_list:
        sid = info["station_id"]
        st  = status_map.get(sid, {})
        stations.append({**info, **st})

    total = len(stations)
    print(f"    station_information records : {len(info_list)}")
    print(f"    station_status records      : {len(status_list)}")
    print(f"    successfully joined         : {total}")

    # ------------------------------------------------------------------
    # 3. Print field inventory (first joined record)
    # ------------------------------------------------------------------
    print("\n[3/6] Field inventory (all keys from first joined record):")
    if stations:
        for k, v in stations[0].items():
            print(f"    {k:40s} = {repr(v)[:60]}")

    # ------------------------------------------------------------------
    # 4. Availability & activity stats
    # ------------------------------------------------------------------
    print("\n[4/6] Availability statistics …")

    active   = [s for s in stations if s.get("is_installed") == 1 and s.get("is_renting") == 1]
    inactive = [s for s in stations if not (s.get("is_installed") == 1 and s.get("is_renting") == 1)]

    # Inactive breakdown
    not_installed = [s for s in stations if s.get("is_installed") != 1]
    installed_not_renting = [s for s in stations
                             if s.get("is_installed") == 1 and s.get("is_renting") != 1]

    bikes_avail   = [s.get("num_bikes_available", 0) for s in active]
    docks_avail   = [s.get("num_docks_available", 0) for s in active]

    print(f"\n  Station counts")
    print(f"    Total stations              : {total}")
    print(f"    Active (installed + renting): {len(active)}")
    print(f"    Inactive total              : {len(inactive)}")
    print(f"      |- Not installed          : {len(not_installed)}")
    print(f"      |- Installed, not renting : {len(installed_not_renting)}")

    print(f"\n  Bikes available (active stations only)")
    print(f"    Average                     : {mean(bikes_avail):.2f}")
    print(f"    Median                      : {median(bikes_avail):.1f}")
    print(f"    Min                         : {min(bikes_avail, default=0)}")
    print(f"    Max                         : {max(bikes_avail, default=0)}")
    print(f"    Total bikes out there       : {sum(bikes_avail)}")

    print(f"\n  Docks available (active stations only)")
    print(f"    Average                     : {mean(docks_avail):.2f}")
    print(f"    Median                      : {median(docks_avail):.1f}")
    print(f"    Min                         : {min(docks_avail, default=0)}")
    print(f"    Max                         : {max(docks_avail, default=0)}")

    # ------------------------------------------------------------------
    # 5. Top 10 fullest / emptiest
    # ------------------------------------------------------------------
    print("\n[5/6] Top 10 fullest stations (most bikes available):")
    sorted_full = sorted(active, key=lambda s: s.get("num_bikes_available", 0), reverse=True)
    print(f"  {'Name':<40} {'Bikes':>5} {'Docks':>5} {'Cap':>5}")
    print(f"  {'-'*40} {'-'*5} {'-'*5} {'-'*5}")
    for s in sorted_full[:10]:
        print(f"  {s.get('name','?'):<40} "
              f"{s.get('num_bikes_available',0):>5} "
              f"{s.get('num_docks_available',0):>5} "
              f"{s.get('capacity',0):>5}")

    print("\n  Top 10 emptiest stations (fewest bikes available):")
    sorted_empty = sorted(active, key=lambda s: s.get("num_bikes_available", 0))
    print(f"  {'Name':<40} {'Bikes':>5} {'Docks':>5} {'Cap':>5}")
    print(f"  {'-'*40} {'-'*5} {'-'*5} {'-'*5}")
    for s in sorted_empty[:10]:
        print(f"  {s.get('name','?'):<40} "
              f"{s.get('num_bikes_available',0):>5} "
              f"{s.get('num_docks_available',0):>5} "
              f"{s.get('capacity',0):>5}")

    # ------------------------------------------------------------------
    # 6. E-bike vs mechanical split
    # ------------------------------------------------------------------
    print("\n  E-bike vs Mechanical split:")
    # BSM uses either num_bikes_available_types dict or dedicated fields
    total_ebikes = 0
    total_mech   = 0
    has_type_data = False

    for s in active:
        # Try nested types dict first (GBFS 2.x)
        bike_types = s.get("num_bikes_available_types", {})
        if isinstance(bike_types, dict) and bike_types:
            has_type_data = True
            total_ebikes += bike_types.get("ebike", 0)
            total_mech   += bike_types.get("mechanical", 0)
        elif "num_ebikes_available" in s:
            # Some feeds use flat fields
            has_type_data = True
            total_ebikes += s.get("num_ebikes_available", 0)
            total_mech   += s.get("num_bikes_available", 0) - s.get("num_ebikes_available", 0)

    if has_type_data:
        total_typed = total_ebikes + total_mech
        pct_e = 100 * total_ebikes / total_typed if total_typed else 0
        print(f"    Electric bikes              : {total_ebikes} ({pct_e:.1f}%)")
        print(f"    Mechanical bikes            : {total_mech}  ({100-pct_e:.1f}%)")
    else:
        print("    Type breakdown not available in this feed snapshot.")

    # ------------------------------------------------------------------
    # 7. Geographic spread
    # ------------------------------------------------------------------
    print("\n  Geographic spread (all stations):")
    lats = [s["lat"] for s in stations if "lat" in s]
    lons = [s["lon"] for s in stations if "lon" in s]
    if lats:
        print(f"    Latitude  range  : {min(lats):.5f} – {max(lats):.5f}")
        print(f"    Longitude range  : {min(lons):.5f} – {max(lons):.5f}")
        lat_span_km = haversine_m(min(lats), mean(lons), max(lats), mean(lons)) / 1000
        lon_span_km = haversine_m(mean(lats), min(lons), mean(lats), max(lons)) / 1000
        print(f"    N-S span         : {lat_span_km:.1f} km")
        print(f"    E-W span         : {lon_span_km:.1f} km")

    # Grid clustering (0.01 degree ≈ 1 km)
    grid: dict[tuple, int] = {}
    for s in stations:
        lat_g = round(s.get("lat", 0), 2)
        lon_g = round(s.get("lon", 0), 2)
        grid[(lat_g, lon_g)] = grid.get((lat_g, lon_g), 0) + 1

    print(f"\n  Grid clustering (0.01° ≈ ~1 km cells):")
    print(f"    Distinct grid cells         : {len(grid)}")
    top_cells = sorted(grid.items(), key=lambda x: x[1], reverse=True)[:5]
    print("    Top 5 densest cells (lat, lon) : count")
    for cell, count in top_cells:
        print(f"      {cell} : {count} stations")

    # ------------------------------------------------------------------
    # 8. Data freshness
    # ------------------------------------------------------------------
    print("\n  Data freshness (last_reported field):")
    now_ts = time.time()
    ages = []
    stale = []

    for s in stations:
        lr = s.get("last_reported")
        if lr:
            age = now_ts - lr
            ages.append(age)
            if age > STALE_THRESHOLD_SECONDS:
                stale.append(s)

    if ages:
        print(f"    Stations with last_reported : {len(ages)}")
        print(f"    Average age                 : {mean(ages)/60:.1f} min")
        print(f"    Oldest report               : {max(ages)/60:.1f} min ago")
        print(f"    Freshest report             : {min(ages)/60:.1f} min ago")
        print(f"    Stale (>30 min)             : {len(stale)}")
        if stale:
            print("    Stale stations (sample):")
            for s in stale[:5]:
                age_min = (now_ts - s.get("last_reported", now_ts)) / 60
                print(f"      {s.get('name','?'):<40} {age_min:.0f} min old")
    else:
        print("    last_reported field not present in this feed.")

    # ------------------------------------------------------------------
    # 9. Proximity search — Sagrada Família
    # ------------------------------------------------------------------
    print("\n[6/6] Proximity search — 5 nearest stations to Sagrada Família")
    print(f"  Reference point: lat={SAGRADA_FAMILIA[0]}, lon={SAGRADA_FAMILIA[1]}")

    geo_stations = [s for s in stations if "lat" in s and "lon" in s]
    for s in geo_stations:
        s["_dist_m"] = haversine_m(SAGRADA_FAMILIA[0], SAGRADA_FAMILIA[1], s["lat"], s["lon"])

    nearest = sorted(geo_stations, key=lambda s: s["_dist_m"])[:5]
    print(f"\n  {'#':<3} {'Name':<40} {'Dist(m)':>7} {'Bikes':>5} {'Docks':>5} {'Active':>7}")
    print(f"  {'-'*3} {'-'*40} {'-'*7} {'-'*5} {'-'*5} {'-'*7}")
    for i, s in enumerate(nearest, 1):
        active_flag = "YES" if (s.get("is_installed")==1 and s.get("is_renting")==1) else "NO"
        print(f"  {i:<3} {s.get('name','?'):<40} {s['_dist_m']:>7.0f} "
              f"{s.get('num_bikes_available',0):>5} "
              f"{s.get('num_docks_available',0):>5} "
              f"{active_flag:>7}")

    print("\n" + "=" * 65)
    print("  Done.")
    print("=" * 65)


def print_gbfs_field_reference():
    """
    Print the expected field inventory based on GBFS v2.3 spec + BSM documentation.
    Used as fallback when the live API is unavailable.
    """
    print("  GBFS v2 Field Reference (BSM Barcelona)")
    print()
    print("  station_information fields:")
    info_fields = [
        ("station_id",          "string",  "Unique stable identifier, e.g. '1'"),
        ("name",                "string",  "Human-readable station name"),
        ("short_name",          "string",  "Short code, e.g. 'C002'"),
        ("lat",                 "float",   "Latitude (WGS84)"),
        ("lon",                 "float",   "Longitude (WGS84)"),
        ("address",             "string",  "Street address"),
        ("cross_street",        "string",  "Nearest intersection"),
        ("region_id",           "string",  "District / region"),
        ("post_code",           "string",  "Postal code"),
        ("rental_methods",      "array",   "['KEY','CREDITCARD','APP',…]"),
        ("is_virtual_station",  "bool",    "Dockless virtual zone"),
        ("capacity",            "int",     "Total dock slots"),
        ("vehicle_capacity",    "object",  "{mechanical:N, ebike:N}"),
        ("rental_uris",         "object",  "Deep-links into Bicing app"),
    ]
    print(f"    {'Field':<30} {'Type':<10} {'Description'}")
    for f, t, d in info_fields:
        print(f"    {f:<30} {t:<10} {d}")

    print()
    print("  station_status fields:")
    status_fields = [
        ("station_id",                   "string", "Matches station_information.station_id"),
        ("num_bikes_available",          "int",    "Total rideable bikes docked"),
        ("num_bikes_available_types",    "object", "{mechanical:N, ebike:N}"),
        ("num_docks_available",          "int",    "Empty docks ready to accept returns"),
        ("num_docks_disabled",           "int",    "Broken/maintenance docks"),
        ("is_installed",                 "int",    "1=physical station present"),
        ("is_renting",                   "int",    "1=currently lending bikes"),
        ("is_returning",                 "int",    "1=currently accepting returns"),
        ("last_reported",                "int",    "Unix timestamp of last status push"),
        ("vehicle_docks_available",      "array",  "[{vehicle_type_ids, count}]"),
        ("vehicle_types_available",      "array",  "[{vehicle_type_id, count}]"),
    ]
    print(f"    {'Field':<35} {'Type':<10} {'Description'}")
    for f, t, d in status_fields:
        print(f"    {f:<35} {t:<10} {d}")


if __name__ == "__main__":
    main()
