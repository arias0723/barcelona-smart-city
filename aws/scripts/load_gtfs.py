"""
scripts/load_gtfs.py
=====================
One-time script: loads TMB GTFS stops + route associations into DynamoDB.
Run this locally after setup.sh to populate the TransitStops table.

Usage:
    python3 aws/scripts/load_gtfs.py

Prerequisites:
    - GTFS files extracted at:  smart_city/gtfs/
    - AWS CLI configured with DynamoDB write access
    - boto3 installed:  pip install boto3

What it writes to TransitStops:
    PK stop_id  + SK feed_ver  (from feed_info.txt)
    All stop metadata + route_ids / route_names / modes sets
    TTL = feed end_date epoch + 7 days

Expected runtime: ~60 seconds (2,810 stops, batched writes)
"""

import csv
import os
import sys
import time
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import boto3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GTFS_DIR   = os.path.join(os.path.dirname(__file__), "..", "..", "gtfs")
TABLE_NAME = "TransitStops"
REGION     = os.environ.get("AWS_REGION", "eu-west-1")
BATCH_SIZE = 25  # DynamoDB BatchWriteItem limit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_csv(filename: str) -> list[dict]:
    path = os.path.join(GTFS_DIR, filename)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def parse_date(s: str) -> datetime:
    return datetime.strptime(s.strip(), "%Y%m%d").replace(tzinfo=timezone.utc)


ROUTE_TYPE_TO_MODE = {
    "0": "tram",
    "1": "metro",
    "2": "rail",
    "3": "bus",
    "4": "ferry",
    "7": "funicular",
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("  GTFS → DynamoDB loader (TransitStops)")
    print("=" * 60)

    # --- 1. Feed version + TTL ---
    print("\n[1/6] Reading feed_info.txt …")
    feed_rows = load_csv("feed_info.txt")
    if not feed_rows:
        sys.exit("ERROR: feed_info.txt is empty")
    feed      = feed_rows[0]
    feed_ver  = feed.get("feed_version", "unknown").strip()
    end_date  = feed.get("feed_end_date", "20261216").strip()
    ttl_epoch = int((parse_date(end_date) + timedelta(days=7)).timestamp())
    print(f"    feed_version : {feed_ver}")
    print(f"    feed_end     : {end_date}  →  TTL epoch {ttl_epoch}")

    # --- 2. Route type lookup ---
    print("\n[2/6] Reading routes.txt …")
    routes_rows = load_csv("routes.txt")
    route_info  = {}  # route_id → {short_name, mode}
    for r in routes_rows:
        rid  = r["route_id"].strip()
        mode = ROUTE_TYPE_TO_MODE.get(r.get("route_type", "3").strip(), "bus")
        route_info[rid] = {
            "short_name": r.get("route_short_name", "").strip(),
            "mode":       mode,
        }
    print(f"    {len(route_info)} routes loaded")

    # --- 3. Trip → route mapping ---
    print("\n[3/6] Reading trips.txt …")
    trips_rows = load_csv("trips.txt")
    trip_route = {r["trip_id"].strip(): r["route_id"].strip() for r in trips_rows}
    print(f"    {len(trip_route)} trips mapped")

    # --- 4. Stop → routes mapping (via stop_times) ---
    print("\n[4/6] Reading stop_times.txt (large file, ~30s) …")
    stop_routes: dict[str, set[str]] = defaultdict(set)
    st_path = os.path.join(GTFS_DIR, "stop_times.txt")
    with open(st_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            stop_id = row["stop_id"].strip()
            trip_id = row["trip_id"].strip()
            route_id = trip_route.get(trip_id)
            if route_id:
                stop_routes[stop_id].add(route_id)
    print(f"    {len(stop_routes)} stops have route associations")

    # --- 5. Load stops ---
    print("\n[5/6] Reading stops.txt …")
    stops_rows = load_csv("stops.txt")
    print(f"    {len(stops_rows)} stops loaded")

    # --- 6. Write to DynamoDB ---
    print("\n[6/6] Writing to DynamoDB TransitStops …")
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table    = dynamodb.Table(TABLE_NAME)

    written  = 0
    skipped  = 0
    batch    = []

    def flush(b: list):
        nonlocal written
        with table.batch_writer() as bw:
            for item in b:
                bw.put_item(Item=item)
        written += len(b)

    for stop in stops_rows:
        stop_id = stop.get("stop_id", "").strip()
        if not stop_id:
            skipped += 1
            continue

        try:
            lat = float(stop.get("stop_lat", 0))
            lon = float(stop.get("stop_lon", 0))
        except ValueError:
            skipped += 1
            continue

        # Build route sets for this stop
        rids   = stop_routes.get(stop_id, set())
        rnames = {route_info[r]["short_name"] for r in rids if r in route_info and route_info[r]["short_name"]}
        modes  = {route_info[r]["mode"]       for r in rids if r in route_info}

        item = {
            "stop_id":       stop_id,
            "feed_ver":      feed_ver,
            "stop_code":     stop.get("stop_code", "").strip(),
            "stop_name":     stop.get("stop_name", "").strip(),
            "stop_lat":      Decimal(str(lat)),
            "stop_lon":      Decimal(str(lon)),
            "lat_bucket":    str(round(lat, 2)),
            "location_type": int(stop.get("location_type", 0) or 0),
            "parent_station":stop.get("parent_station", "").strip(),
            "wheelchair":    int(stop.get("wheelchair_boarding", 0) or 0),
            "ttl":           ttl_epoch,
        }

        # DynamoDB StringSet requires at least 1 element
        if rids:
            item["route_ids"]   = rids
        if rnames:
            item["route_names"] = rnames
        if modes:
            item["modes"]       = modes
            item["primary_mode"] = next(iter(modes))

        batch.append(item)
        if len(batch) >= BATCH_SIZE:
            flush(batch)
            batch = []
            if written % 500 == 0:
                print(f"    … {written} stops written")

    if batch:
        flush(batch)

    print(f"\n    Written : {written}")
    print(f"    Skipped : {skipped}")
    print(f"    Table   : {TABLE_NAME}")
    print("\nGTFS load complete.")


if __name__ == "__main__":
    main()
