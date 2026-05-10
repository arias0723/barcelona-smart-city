"""
Lambda: smart-city-bicing-ingest
=================================
Fetches live Bicing data from citybik.es (public GBFS mirror) and writes
each station snapshot to DynamoDB.
Triggered by EventBridge every 5 minutes.

Data source: https://api.citybik.es/v2/networks/bicing
  - 543 Barcelona stations, no auth required
  - Fields: id, name, latitude, longitude, free_bikes, empty_slots,
            extra.normal_bikes, extra.ebikes, extra.uid, extra.online

NOTE: Previous source (api.bsmsa.eu) returns HTTP 503 error 700700
"API blocked temporarily" as of May 2026.

DynamoDB table: BicingStations
  PK: station_id (S)   — extra.uid as string (stable BSM station number)
  SK: updated_at (N)   — Unix epoch of this write
  TTL: ttl (N)         — 30 days (enables historical queries)

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

TABLE_NAME    = os.environ.get("TABLE_NAME", "BicingStations")
REGION        = os.environ.get("AWS_REGION", "eu-west-1")
CITYBIKES_URL = "https://api.citybik.es/v2/networks/bicing"

dynamodb = boto3.resource("dynamodb", region_name=REGION)


def _fetch(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "smart-city-ingest/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} fetching {url}")
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def _d(v) -> Decimal:
    if v is None:
        return Decimal("0")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return Decimal("0")


def lambda_handler(event, context):
    print("Fetching Bicing data from citybik.es …")

    data = _fetch(CITYBIKES_URL)
    if data is None:
        msg = "citybik.es Bicing API unavailable"
        print(msg)
        return {"statusCode": 503, "body": msg}

    stations = data.get("network", {}).get("stations", [])
    if not stations:
        msg = "No stations in citybik.es response"
        print(msg)
        return {"statusCode": 500, "body": msg}

    now = int(time.time())
    ttl = now + 30 * 24 * 3600  # 30 days

    table   = dynamodb.Table(TABLE_NAME)
    written = 0
    skipped = 0

    with table.batch_writer() as batch:
        for s in stations:
            extra = s.get("extra", {})
            uid   = extra.get("uid")
            if uid is None:
                skipped += 1
                continue

            lat = s.get("latitude", 0)
            lon = s.get("longitude", 0)
            free_bikes   = int(s.get("free_bikes", 0))
            empty_slots  = int(s.get("empty_slots", 0))
            normal_bikes = int(extra.get("normal_bikes", 0))
            ebikes       = int(extra.get("ebikes", 0))

            item = {
                "station_id":               str(uid),
                "updated_at":               now,
                "name":                     s.get("name", "").strip(),
                "lat":                      _d(lat),
                "lon":                      _d(lon),
                "lat_bucket":               str(round(float(lat), 2)),
                "capacity":                 free_bikes + empty_slots,
                "num_bikes_available":      free_bikes,
                "num_ebikes_available":     ebikes,
                "num_mechanical_available": normal_bikes,
                "num_docks_available":      empty_slots,
                "is_renting":               1 if extra.get("online", False) else 0,
                "is_returning":             1 if extra.get("online", False) else 0,
                "last_reported":            now,
                "ttl":                      ttl,
            }

            try:
                batch.put_item(Item=item)
                written += 1
            except Exception as e:
                print(f"Write error station {uid}: {e}")
                skipped += 1

    result = {"written": written, "skipped": skipped, "timestamp": now, "table": TABLE_NAME}
    print(f"Done: {result}")
    return {"statusCode": 200, "body": json.dumps(result)}
