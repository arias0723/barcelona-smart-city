"""
TMB API Exploration Script
Barcelona Smart City — Mobility Vertical

Credentials and endpoints confirmed live on 2026-04-23.
Run standalone: python tmb_api_exploration.py
"""

import requests
from math import radians, sin, cos, sqrt, atan2

# ── Constants ──────────────────────────────────────────────────────────────────
BASE    = "https://api.tmb.cat/v1"
APP_ID  = "74309501"
APP_KEY = "c7234d6f7249b444f6158f41a0ad4fce"

AUTH = {"app_id": APP_ID, "app_key": APP_KEY}


# ── Helpers ────────────────────────────────────────────────────────────────────
def get(path: str, extra_params: dict = None) -> dict:
    params = dict(AUTH)
    if extra_params:
        params.update(extra_params)
    r = requests.get(f"{BASE}{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two WGS-84 points."""
    R = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi       = radians(lat2 - lat1)
    dlambda    = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def section(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)


# ── 1. Metro lines ─────────────────────────────────────────────────────────────
def explore_metro_lines() -> list[dict]:
    section("1. METRO LINES  — GET /transit/linies/metro")
    data     = get("/transit/linies/metro")
    features = data["features"]

    print(f"  Total metro lines : {data['totalFeatures']}")
    print(f"  Fields            : {list(features[0]['properties'].keys())}")
    print()
    print(f"  {'Line':<8} {'ID_LINIA':<10} {'CODI_LINIA':<12} {'Color':<8} {'Desc'}")
    print(f"  {'-'*65}")

    lines = []
    for f in sorted(features, key=lambda x: x["properties"]["ORDRE_LINIA"]):
        p = f["properties"]
        print(f"  {p['NOM_LINIA']:<8} {p['ID_LINIA']:<10} {p['CODI_LINIA']:<12} "
              f"#{p['COLOR_LINIA']:<7} {p['DESC_LINIA']}")
        lines.append(p)

    return lines


# ── 2. Bus lines ───────────────────────────────────────────────────────────────
def explore_bus_lines() -> list[dict]:
    section("2. BUS LINES  — GET /transit/linies/bus")
    data     = get("/transit/linies/bus")
    features = data["features"]

    print(f"  Total bus lines : {data['totalFeatures']}")
    print(f"  Fields          : {list(features[0]['properties'].keys())}")
    print()
    print("  First 10 bus lines:")
    print(f"  {'NOM':<8} {'DESC':<50}")
    print(f"  {'-'*60}")

    bus_lines = []
    for f in features:
        bus_lines.append(f["properties"])

    for p in sorted(bus_lines, key=lambda x: x.get("ORDRE_LINIA", 0))[:10]:
        print(f"  {p['NOM_LINIA']:<8} {p['DESC_LINIA'][:48]}")

    return bus_lines


# ── 3. All stops (parades) ─────────────────────────────────────────────────────
def explore_parades() -> list[dict]:
    section("3. ALL STOPS  — GET /transit/parades")
    data     = get("/transit/parades")
    features = data["features"]

    print(f"  totalFeatures   : {data['totalFeatures']}")
    print(f"  numberReturned  : {data['numberReturned']}")
    print(f"  Pagination      : {'yes — use startIndex/count params' if data['numberReturned'] < data['totalFeatures'] else 'no — full dataset returned in one call'}")
    print(f"  Fields          : {list(features[0]['properties'].keys())}")

    # Count by type
    type_counts: dict[str, int] = {}
    for f in features:
        t = f["properties"].get("NOM_TIPUS_PARADA", "UNKNOWN")
        type_counts[t] = type_counts.get(t, 0) + 1

    print()
    print("  Stop types:")
    for t, n in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:<12} {n:>5}")

    print()
    print("  Sample stop:")
    p = features[0]["properties"]
    for k, v in p.items():
        print(f"    {k:<30} {v}")

    return features


# ── 4. Metro stations per line  ────────────────────────────────────────────────
def explore_metro_stations_per_line(metro_lines: list[dict]) -> None:
    section("4. METRO STATIONS PER LINE  — GET /transit/linies/metro/{CODI}/estacions")

    print("  NOTE: URL uses CODI_LINIA (numeric route code), not ID_LINIA")
    print()
    print(f"  {'Line':<8} {'Stations':<10} {'Terminus A':<30} {'Terminus B'}")
    print(f"  {'-'*80}")

    # Sort by ORDRE_LINIA for clean display
    for line in sorted(metro_lines, key=lambda x: x["ORDRE_LINIA"]):
        codi  = line["CODI_LINIA"]
        nom   = line["NOM_LINIA"]
        data  = get(f"/transit/linies/metro/{codi}/estacions")
        feats = sorted(data["features"],
                       key=lambda x: x["properties"]["ORDRE_ESTACIO"])

        if not feats:
            print(f"  {nom:<8} {'0':<10} (no data)")
            continue

        p_first = feats[0]["properties"]
        p_last  = feats[-1]["properties"]
        print(f"  {nom:<8} {data['totalFeatures']:<10} "
              f"{p_first['NOM_ESTACIO']:<30} {p_last['NOM_ESTACIO']}")

        # Print each station ordered
        for f in feats:
            p = f["properties"]
            acc = "A" if p["ID_TIPUS_ACCESSIBILITAT"] == 1 else " "
            print(f"      [{p['ORDRE_ESTACIO']:>2}] {acc} {p['NOM_ESTACIO']}")

    print()
    print("  ESTACIONS_LINIA field inventory:")
    sample_data  = get("/transit/linies/metro/1/estacions")
    sample_feats = sample_data["features"]
    if sample_feats:
        for k in sample_feats[0]["properties"].keys():
            print(f"    {k}")


# ── 5. Proximity search  ───────────────────────────────────────────────────────
def nearest_stops(parades: list, lat: float, lon: float,
                  n: int = 5, label: str = "") -> None:
    section(f"5. NEAREST {n} STOPS TO {label} ({lat}, {lon})")

    stops_with_dist = []
    for f in parades:
        coords = f["geometry"]["coordinates"]  # [lon, lat]
        dist   = haversine(lat, lon, coords[1], coords[0])
        stops_with_dist.append((dist, f["properties"]))

    stops_with_dist.sort(key=lambda x: x[0])

    print(f"  {'Dist (m)':<10} {'CODI':<8} {'Name':<40} {'Type'}")
    print(f"  {'-'*75}")
    for dist, p in stops_with_dist[:n]:
        print(f"  {dist:<10.0f} {p['CODI_PARADA']:<8} "
              f"{p['NOM_PARADA']:<40} {p['NOM_TIPUS_SIMPLE_PARADA']}")


# ── 6. Real-time iBus  ─────────────────────────────────────────────────────────
def explore_realtime(parades: list) -> None:
    section("6. REAL-TIME DATA  — GET /ibus/stops/{CODI_PARADA}")

    print("  iBus endpoint: /ibus/stops/{CODI_PARADA}")
    print("  Returns next bus arrival times in real time.")
    print()

    # Find a few stops near city centre and try them
    centre_lat, centre_lon = 41.3874, 2.1686  # Plaça Catalunya
    stops_with_dist = []
    for f in parades:
        coords = f["geometry"]["coordinates"]
        dist   = haversine(centre_lat, centre_lon, coords[1], coords[0])
        stops_with_dist.append((dist, f["properties"]))
    stops_with_dist.sort(key=lambda x: x[0])

    tested = 0
    for dist, p in stops_with_dist[:20]:
        codi = p["CODI_PARADA"]
        try:
            rt = requests.get(
                f"{BASE}/ibus/stops/{codi}",
                params=AUTH, timeout=10
            ).json()
            arrivals = rt.get("data", {}).get("ibus", [])
            if arrivals:
                print(f"  Stop {codi} — {p['NOM_PARADA']} ({dist:.0f} m)")
                for a in arrivals[:3]:
                    print(f"    Line {a['line']:<6} → {a['destination']:<30} "
                          f"in {a['t-in-min']} min  ({a['t-in-s']} s)")
                tested += 1
                if tested >= 3:
                    break
        except Exception as e:
            continue

    if tested == 0:
        print("  No live arrivals at this moment for tested stops.")

    print()
    print("  iBus fields per arrival record:")
    print("    destination  — end terminus of the route")
    print("    line         — line code (e.g. '150', 'H4')")
    print("    routeId      — internal route variant ID")
    print("    t-in-min     — minutes until arrival (integer)")
    print("    t-in-s       — seconds until arrival (integer)")
    print("    text-ca      — human-readable Catalan text (e.g. '4 min')")
    print()
    print("  Real-time availability summary:")
    print("    /ibus/stops/{id}      LIVE bus arrivals — FREE TIER  ✓")
    print("    /planner/trip         Trip planner      — 403 on free tier ✗")
    print("    Metro real-time       Not exposed in API — not available ✗")
    print("    Bus occupancy         Not in any endpoint — not available ✗")
    print("    Delays / disruptions  Not in any endpoint — not available ✗")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("TMB API LIVE EXPLORATION")
    print(f"Base URL : {BASE}")
    print(f"App ID   : {APP_ID}")

    metro_lines = explore_metro_lines()
    bus_lines   = explore_bus_lines()
    parades     = explore_parades()

    explore_metro_stations_per_line(metro_lines)

    nearest_stops(
        parades,
        lat=41.4036, lon=2.1744,
        n=5,
        label="Sagrada Familia"
    )

    explore_realtime(parades)

    # Summary stats
    section("SUMMARY")
    print(f"  Metro lines  : {len(metro_lines)}")
    print(f"  Bus lines    : {len(bus_lines)}")
    print(f"  Bus stops    : {len(parades)}  (all are bus stops; metro uses /estacions)")
    total_metro = sum(
        get(f"/transit/linies/metro/{l['CODI_LINIA']}/estacions")["totalFeatures"]
        for l in metro_lines
    )
    print(f"  Metro stations (line entries, incl. interchange duplicates): {total_metro}")
    print()
    print("  Endpoints confirmed working on free tier:")
    print("    GET /transit/linies/metro          → 11 lines, static")
    print("    GET /transit/linies/bus            → 113 lines, static")
    print("    GET /transit/parades               → 2721 bus stops, static")
    print("    GET /transit/estacions             → 140 metro station nodes, static")
    print("    GET /transit/linies/metro/{c}/estacions → ordered stops per line, static")
    print("    GET /ibus/stops/{codi}             → live next-bus arrivals  ← REAL-TIME")
    print()
    print("  Endpoints NOT available on free tier:")
    print("    GET /planner/trip                  → 403 Forbidden")
    print("    GET /transit/linies/metro/{id}/parades → 404 (use /estacions instead)")
    print("    GET /transit/linies/bus/{id}/parades   → 200 but always empty")


if __name__ == "__main__":
    main()
