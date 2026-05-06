"""
gtfs_exploration.py
===================
Exploratory analysis of Barcelona TMB GTFS static feed.

Feed details (from feed_info.txt):
  Publisher : TMB (Transports Metropolitans de Barcelona)
  Language  : ca (Catalan)
  Valid from: 2026-04-21  to  2026-12-16
  Version   : 161721042026002

GTFS files analysed:
  agency.txt, routes.txt, trips.txt, stop_times.txt,
  stops.txt, calendar.txt, calendar_dates.txt, feed_info.txt,
  frequencies.txt, pathways.txt, transfers.txt, shapes.txt

Run:
    python3 gtfs_exploration.py
"""

import csv
import math
import os
from collections import defaultdict, Counter

GTFS_DIR = "/Users/kubadusza/UPC/CCBDA/smart_city/gtfs"
SAGRADA_FAMILIA = (41.4036, 2.1744)  # reference point for proximity demo

# Route type codes (GTFS standard)
ROUTE_TYPE_NAMES = {
    "0": "Tram / Light Rail",
    "1": "Metro (Subway)",
    "3": "Bus",
    "2": "Rail",
    "4": "Ferry",
    "5": "Cable Car",
    "6": "Gondola",
    "7": "Funicular",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_csv(filename: str) -> list[dict]:
    """Load a GTFS CSV file; return list of row dicts."""
    path = os.path.join(GTFS_DIR, filename)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def mean(values) -> float:
    lst = list(values)
    return sum(lst) / len(lst) if lst else 0.0


def median(values) -> float:
    s = sorted(values)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def fmt_date(d: str) -> str:
    """Format YYYYMMDD string as YYYY-MM-DD."""
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if len(d) == 8 else d


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 65)
    print("  TMB GTFS Static Feed — Data Exploration")
    print("=" * 65)

    # ------------------------------------------------------------------
    # 1. Feed metadata
    # ------------------------------------------------------------------
    print("\n[1/9] Feed metadata")
    feed_info = load_csv("feed_info.txt")
    if feed_info:
        fi = feed_info[0]
        print(f"    Publisher  : {fi.get('feed_publisher_name','?')}")
        print(f"    URL        : {fi.get('feed_publisher_url','?')}")
        print(f"    Language   : {fi.get('feed_lang','?')}")
        print(f"    Valid from : {fmt_date(fi.get('feed_start_date','?'))}")
        print(f"    Valid to   : {fmt_date(fi.get('feed_end_date','?'))}")
        print(f"    Version    : {fi.get('feed_version','?')}")

    agency = load_csv("agency.txt")
    if agency:
        ag = agency[0]
        print(f"    Agency     : {ag.get('agency_name','?')}  |  phone: {ag.get('agency_phone','?')}")

    # ------------------------------------------------------------------
    # 2. Routes
    # ------------------------------------------------------------------
    print("\n[2/9] Routes")
    routes = load_csv("routes.txt")
    print(f"    Total routes  : {len(routes)}")

    by_type: dict[str, list] = defaultdict(list)
    for r in routes:
        by_type[r.get("route_type", "?")].append(r)

    print("    By route_type :")
    for rtype, rlist in sorted(by_type.items()):
        type_name = ROUTE_TYPE_NAMES.get(rtype, f"type {rtype}")
        print(f"      type {rtype} ({type_name:<20}): {len(rlist):3d} routes")

    print("\n    All route short names:")
    for rtype, rlist in sorted(by_type.items()):
        names = sorted(r.get("route_short_name", "?") for r in rlist)
        type_name = ROUTE_TYPE_NAMES.get(rtype, f"type {rtype}")
        print(f"      {type_name}: {', '.join(names)}")

    # ------------------------------------------------------------------
    # 3. Stops
    # ------------------------------------------------------------------
    print("\n[3/9] Stops")
    stops = load_csv("stops.txt")

    # GTFS location_type: 0=stop, 1=station, 2=entrance, 3=node, 4=boarding
    by_loc_type: Counter = Counter()
    for s in stops:
        by_loc_type[s.get("location_type", "0")] += 1

    loc_type_names = {"0": "stop/platform", "1": "station", "2": "entrance/exit",
                      "3": "generic node", "4": "boarding area", "": "stop/platform"}
    print(f"    Total stop records : {len(stops)}")
    for lt, cnt in sorted(by_loc_type.items()):
        print(f"      location_type {lt} ({loc_type_names.get(lt,'?'):<18}): {cnt}")

    # Usable stop-platforms only
    platforms = [s for s in stops if s.get("location_type", "0") in ("0", "")]
    print(f"\n    Platforms (location_type 0) : {len(platforms)}")

    # Geographic extent
    lats = [float(s["stop_lat"]) for s in platforms if s.get("stop_lat")]
    lons = [float(s["stop_lon"]) for s in platforms if s.get("stop_lon")]
    if lats:
        print(f"    Lat range  : {min(lats):.5f} – {max(lats):.5f}")
        print(f"    Lon range  : {min(lons):.5f} – {max(lons):.5f}")
        mlat = mean(lats); mlon = mean(lons)
        ns_km = haversine_m(min(lats), mlon, max(lats), mlon) / 1000
        ew_km = haversine_m(mlat, min(lons), mlat, max(lons)) / 1000
        print(f"    N-S span   : {ns_km:.1f} km")
        print(f"    E-W span   : {ew_km:.1f} km")

    # Stop density grid (0.01° ≈ ~1 km)
    print("\n[4/9] Stop density (0.01° grid cells)")
    grid: Counter = Counter()
    for s in platforms:
        try:
            lat_g = round(float(s["stop_lat"]), 2)
            lon_g = round(float(s["stop_lon"]), 2)
            grid[(lat_g, lon_g)] += 1
        except (ValueError, KeyError):
            pass

    print(f"    Distinct grid cells : {len(grid)}")
    top_cells = grid.most_common(10)
    print("    Top 10 densest cells (lat, lon) : stop count")
    for cell, cnt in top_cells:
        print(f"      {cell} : {cnt}")

    # ------------------------------------------------------------------
    # 5. Trips
    # ------------------------------------------------------------------
    print("\n[5/9] Trips")
    trips = load_csv("trips.txt")
    print(f"    Total trips : {len(trips)}")

    trips_by_route: Counter = Counter(t["route_id"] for t in trips)
    route_id_to_name = {r["route_id"]: r.get("route_short_name","?") for r in routes}

    # Trips per route type
    route_id_to_type = {r["route_id"]: r.get("route_type","?") for r in routes}
    trips_by_type: Counter = Counter()
    for t in trips:
        trips_by_type[route_id_to_type.get(t["route_id"], "?")] += 1

    print("    Trips by route_type:")
    for rtype, cnt in sorted(trips_by_type.items()):
        type_name = ROUTE_TYPE_NAMES.get(rtype, f"type {rtype}")
        print(f"      type {rtype} ({type_name:<20}): {cnt:6d}")

    # Top 10 busiest routes by trip count
    print("\n    Top 10 routes by trip count:")
    print(f"    {'Route':<8} {'Short name':<12} {'Trips':>6}")
    for rid, cnt in trips_by_route.most_common(10):
        print(f"    {rid:<8} {route_id_to_name.get(rid,'?'):<12} {cnt:>6}")

    # ------------------------------------------------------------------
    # 6. Stop times
    # ------------------------------------------------------------------
    print("\n[6/9] Stop times")
    stop_times = load_csv("stop_times.txt")
    print(f"    Total stop-time records : {len(stop_times)}")

    calls_per_stop: Counter = Counter(st["stop_id"] for st in stop_times)
    print(f"    Unique stops served     : {len(calls_per_stop)}")
    print(f"    Avg calls per stop      : {mean(calls_per_stop.values()):.1f}")
    print(f"    Max calls (busiest stop): {max(calls_per_stop.values(), default=0)}")

    busiest_stop_id = calls_per_stop.most_common(1)[0][0] if calls_per_stop else None
    stop_id_to_name = {s["stop_id"]: s.get("stop_name","?") for s in stops}
    if busiest_stop_id:
        print(f"    Busiest stop            : {stop_id_to_name.get(busiest_stop_id,'?')} "
              f"(id={busiest_stop_id}, {calls_per_stop[busiest_stop_id]} calls)")

    # ------------------------------------------------------------------
    # 7. Metro network detail
    # ------------------------------------------------------------------
    print("\n[7/9] Metro network detail")
    metro_routes = [r for r in routes if r.get("route_type") == "1"]
    metro_route_ids = {r["route_id"] for r in metro_routes}

    # For each metro line, find ordered stops of one representative trip (direction 0)
    metro_trips = [t for t in trips if t["route_id"] in metro_route_ids
                   and t.get("direction_id") == "0"]
    # Pick one trip per route
    trip_per_route: dict[str, str] = {}
    for t in metro_trips:
        if t["route_id"] not in trip_per_route:
            trip_per_route[t["route_id"]] = t["trip_id"]

    # Build stop sequence for each chosen trip
    trip_stops: dict[str, list[tuple[int, str]]] = defaultdict(list)
    target_trips = set(trip_per_route.values())
    for st in stop_times:
        if st["trip_id"] in target_trips:
            try:
                seq = int(st["stop_sequence"])
            except ValueError:
                seq = 0
            trip_stops[st["trip_id"]].append((seq, st["stop_id"]))

    # Sort by sequence
    for tid in trip_stops:
        trip_stops[tid].sort()

    print(f"    Metro lines: {len(metro_routes)}")
    for r in sorted(metro_routes, key=lambda x: x.get("route_short_name","")):
        rid = r["route_id"]
        tid = trip_per_route.get(rid)
        stops_seq = trip_stops.get(tid, []) if tid else []
        stop_names = [stop_id_to_name.get(sid, sid) for _, sid in stops_seq]

        headsign = ""
        if tid:
            for t in metro_trips:
                if t["trip_id"] == tid:
                    headsign = t.get("trip_headsign", "")
                    break

        print(f"\n    {r.get('route_short_name','?')} — {headsign}  ({len(stops_seq)} stops)")
        if stop_names:
            # Show first 4, last 4, ellipsis in between if long
            if len(stop_names) <= 8:
                print(f"      {' → '.join(stop_names)}")
            else:
                head = " → ".join(stop_names[:4])
                tail = " → ".join(stop_names[-4:])
                print(f"      {head} → … → {tail}")

    # ------------------------------------------------------------------
    # 8. Bus lines overview
    # ------------------------------------------------------------------
    print("\n[8/9] Bus lines overview")
    bus_routes = [r for r in routes if r.get("route_type") == "3"]
    print(f"    Total bus routes: {len(bus_routes)}")

    # Sample 10 major lines (highest trip count)
    bus_ids = {r["route_id"] for r in bus_routes}
    bus_trip_counts = {rid: trips_by_route[rid] for rid in bus_ids}
    top_bus = sorted(bus_trip_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    print(f"\n    Top 10 bus lines by trip count:")
    route_long_name = {r["route_id"]: r.get("route_long_name","?") for r in routes}
    print(f"    {'Short':<8} {'Trips':>5}  {'Long name'}")
    for rid, cnt in top_bus:
        sname = route_id_to_name.get(rid, rid)
        lname = route_long_name.get(rid, "?")[:55]
        print(f"    {sname:<8} {cnt:>5}  {lname}")

    # ------------------------------------------------------------------
    # 9. Proximity to Sagrada Família
    # ------------------------------------------------------------------
    print("\n[9/9] Proximity search — 5 nearest stops to Sagrada Família")
    print(f"  Reference: lat={SAGRADA_FAMILIA[0]}, lon={SAGRADA_FAMILIA[1]}")

    geo_stops = []
    for s in platforms:
        try:
            lat = float(s["stop_lat"])
            lon = float(s["stop_lon"])
            dist = haversine_m(SAGRADA_FAMILIA[0], SAGRADA_FAMILIA[1], lat, lon)
            geo_stops.append((dist, s))
        except (ValueError, KeyError):
            pass

    geo_stops.sort(key=lambda x: x[0])
    nearest5 = geo_stops[:5]

    # Determine which route(s) serve each stop
    stop_routes: dict[str, set] = defaultdict(set)
    for t in trips:
        rid = t["route_id"]
        # We don't scan all stop_times again for performance; skip route tagging
        pass

    # Faster: build stop->route map from stop_times + trips
    trip_to_route = {t["trip_id"]: route_id_to_name.get(t["route_id"], t["route_id"])
                     for t in trips}
    stop_to_routes: dict[str, set] = defaultdict(set)
    for st in stop_times:
        rname = trip_to_route.get(st["trip_id"])
        if rname:
            stop_to_routes[st["stop_id"]].add(rname)

    print(f"\n  {'#':<3} {'Stop name':<35} {'Dist(m)':>7} {'Routes served'}")
    print(f"  {'-'*3} {'-'*35} {'-'*7} {'-'*30}")
    for i, (dist, s) in enumerate(nearest5, 1):
        name = s.get("stop_name", "?")
        sid  = s["stop_id"]
        routes_here = ", ".join(sorted(stop_to_routes.get(sid, set()))[:6]) or "—"
        print(f"  {i:<3} {name:<35} {dist:>7.0f} {routes_here}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 65)
    print("  SUMMARY")
    print("=" * 65)
    print(f"  Feed valid       : {fmt_date(feed_info[0].get('feed_start_date','?'))} – "
          f"{fmt_date(feed_info[0].get('feed_end_date','?'))}")
    print(f"  Total routes     : {len(routes)}")
    for rtype in sorted(by_type.keys()):
        print(f"    type {rtype} ({ROUTE_TYPE_NAMES.get(rtype,'?'):<20}): {len(by_type[rtype])}")
    print(f"  Total stops      : {len(stops)} records / {len(platforms)} platforms")
    print(f"  Total trips      : {len(trips)}")
    print(f"  Stop-time rows   : {len(stop_times)}")
    print(f"  Calendar entries : {len(load_csv('calendar.txt'))}")
    print(f"  Calendar dates   : {len(load_csv('calendar_dates.txt'))}")
    print(f"  Transfers        : {len(load_csv('transfers.txt'))}")
    print(f"  Pathway records  : {len(load_csv('pathways.txt'))}")
    print(f"  Shape points     : {len(load_csv('shapes.txt'))}")
    print("=" * 65)
    print("  Done.")
    print("=" * 65)


if __name__ == "__main__":
    main()
