"""
Lambda: smart-city-bicing-ingest
=================================
Fetches live Bicing GBFS data and writes each station snapshot to DynamoDB.
Triggered by EventBridge every 5 minutes.

DynamoDB table: BicingStations
  PK: station_id (S)   — stable BSM station identifier
  SK: updated_at (N)   — Unix epoch of this write
  TTL: ttl (N)         — updated_at + 3600 (1 hour)

Environment variables:
  TABLE_NAME   — DynamoDB table (default: BicingStations)
  AWS_REGION   — AWS region    (default: eu-west-1)
"""

import json
import os
import time
import urllib.request
import urllib.error
from decimal import Decimal, InvalidOperation

import boto3
from boto3.dynamodb.conditions import Key  # noqa: F401 (available if needed)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TABLE_NAME = os.environ.get("TABLE_NAME", "BicingStations")
REGION     = os.environ.get("AWS_REGION", "eu-west-1")

BASE_URL           = "https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en"
STATION_INFO_URL   = f"{BASE_URL}/station_information.json"
STATION_STATUS_URL = f"{BASE_URL}/station_status.json"

dynamodb = boto3.resource("dynamodb", region_name=REGION)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fetch(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "smart-city-ingest/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} fetching {url}")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def _d(v) -> Decimal:
    """Convert a value to Decimal safely (required for DynamoDB numeric types)."""
    if v is None:
        return Decimal("0")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return Decimal("0")


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    print("Fetching Bicing GBFS data …")

    info_raw   = _fetch(STATION_INFO_URL)
    status_raw = _fetch(STATION_STATUS_URL)

    if info_raw is None or status_raw is None:
        msg = "Bicing API unavailable (503 or connection error)"
        print(msg)
        return {"statusCode": 503, "body": msg}

    info_list   = info_raw["data"]["stations"]
    status_list = status_raw["data"]["stations"]
    status_map  = {s["station_id"]: s for s in status_list}

    now = int(time.time())
    ttl = now + 3600  # keep 1 hour of snapshots

    table   = dynamodb.Table(TABLE_NAME)
    written = 0
    skipped = 0

    with table.batch_writer() as batch:
        for info in info_list:
            sid = str(info["station_id"])
            st  = status_map.get(info["station_id"], {})

            lat = info.get("lat", 0)
            lon = info.get("lon", 0)

            # Flatten e-bike / mechanical split (two possible GBFS field layouts)
            bike_types = st.get("num_bikes_available_types", {})
            if isinstance(bike_types, dict) and bike_types:
                num_ebikes = bike_types.get("ebike", 0)
                num_mech   = bike_types.get("mechanical", 0)
            else:
                num_ebikes = st.get("num_ebikes_available", 0)
                num_mech   = st.get("num_mechanical_available",
                                    st.get("num_bikes_available", 0) - num_ebikes)

            item = {
                "station_id":              sid,
                "updated_at":              now,
                "name":                    info.get("name", ""),
                "short_name":              info.get("short_name", ""),
                "lat":                     _d(lat),
                "lon":                     _d(lon),
                "lat_bucket":              str(round(float(lat), 2)),
                "capacity":                int(info.get("capacity", 0)),
                "num_bikes_available":     int(st.get("num_bikes_available", 0)),
                "num_ebikes_available":    int(num_ebikes),
                "num_mechanical_available":int(num_mech),
                "num_docks_available":     int(st.get("num_docks_available", 0)),
                "num_docks_disabled":      int(st.get("num_docks_disabled", 0)),
                "is_installed":            int(st.get("is_installed", 0)),
                "is_renting":              int(st.get("is_renting", 0)),
                "is_returning":            int(st.get("is_returning", 0)),
                "last_reported":           int(st.get("last_reported", 0)),
                "ttl":                     ttl,
            }

            try:
                batch.put_item(Item=item)
                written += 1
            except Exception as e:
                print(f"Write error station {sid}: {e}")
                skipped += 1

    result = {
        "written":   written,
        "skipped":   skipped,
        "timestamp": now,
        "table":     TABLE_NAME,
    }
    print(f"Done: {result}")
    return {"statusCode": 200, "body": json.dumps(result)}
