"""
Lambda: smart-city-pollen-ingest
==================================
Fetches the current-hour pollen forecast for Barcelona from Open-Meteo's
CAMS Air Quality model and writes one record per species per hour to DynamoDB.
Triggered by EventBridge every hour.

DynamoDB table: PollenData
  PK: location_species  (S)  — e.g. "barcelona_grass_pollen"
  SK: hour_ts           (S)  — e.g. "2026051214"  (YYYYMMDDHH local Europe/Madrid)
  TTL: ttl              (N)  — 30 days

Environment variables:
  TABLE_NAME    — DynamoDB table (default: PollenData)
  DYNAMO_REGION — AWS region    (default: eu-west-1)
"""

import json
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "PollenData")
REGION     = os.environ.get("DYNAMO_REGION", os.environ.get("AWS_REGION", "eu-west-1"))

SPECIES = [
    "grass_pollen",
    "olive_pollen",
    "birch_pollen",
    "ragweed_pollen",
    "alder_pollen",
    "mugwort_pollen",
]

POLLEN_URL = (
    "https://air-quality-api.open-meteo.com/v1/air-quality"
    "?latitude=41.3851&longitude=2.1734"
    f"&hourly={','.join(SPECIES)}"
    "&forecast_days=1"
    "&timezone=Europe%2FMadrid"
)

_POLLEN_THRESHOLDS = {
    "grass_pollen":   {"low": 10,  "moderate": 50,  "high": 200},
    "olive_pollen":   {"low": 10,  "moderate": 100, "high": 400},
    "birch_pollen":   {"low": 10,  "moderate": 50,  "high": 200},
    "ragweed_pollen": {"low": 10,  "moderate": 100, "high": 400},
    "alder_pollen":   {"low": 10,  "moderate": 50,  "high": 200},
    "mugwort_pollen": {"low": 10,  "moderate": 50,  "high": 200},
}

dynamodb = boto3.resource("dynamodb", region_name=REGION)


def _pollen_level(species: str, value: float) -> str:
    t = _POLLEN_THRESHOLDS.get(species, {"low": 10, "moderate": 50, "high": 200})
    if value < t["low"]:      return "low"
    if value < t["moderate"]: return "moderate"
    if value < t["high"]:     return "high"
    return "very high"


def _d(v) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "smart-city-ingest/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return None


def lambda_handler(event, context):
    now     = datetime.now(timezone.utc)
    ts_unix = int(now.timestamp())
    ttl     = ts_unix + 30 * 24 * 3600

    # hour_ts in local Barcelona time (UTC+2 summer / UTC+1 winter)
    # Open-Meteo returns times in Europe/Madrid local — match that for consistency
    local_offset = 2 if (3 < now.month < 11) else 1  # rough DST approximation
    local_now    = now + timedelta(hours=local_offset)
    hour_ts      = local_now.strftime("%Y%m%d%H")

    print(f"Fetching pollen for {hour_ts} …")

    data = _fetch_json(POLLEN_URL)
    if data is None or "hourly" not in data:
        print("Open-Meteo pollen API unavailable")
        return {"statusCode": 200, "body": json.dumps({"written": 0, "note": "api_unavailable"})}

    hourly = data["hourly"]
    times  = hourly.get("time", [])

    # Find the index for the current local hour
    cur_hour_str = local_now.strftime("%Y-%m-%dT%H:00")
    try:
        idx = times.index(cur_hour_str)
    except ValueError:
        # Fall back to closest earlier entry
        idx = max(
            (i for i, t in enumerate(times) if t <= cur_hour_str),
            default=0
        )

    table   = dynamodb.Table(TABLE_NAME)
    written = 0

    for sp in SPECIES:
        vals = hourly.get(sp, [])
        v    = vals[idx] if idx < len(vals) else None
        if v is None:
            continue

        level = _pollen_level(sp, float(v))
        table.put_item(Item={
            "location_species": f"barcelona_{sp}",
            "hour_ts":          hour_ts,
            "species":          sp,
            "value_grains_m3":  _d(v),
            "level":            level,
            "lat":              _d(41.3851),
            "lon":              _d(2.1734),
            "recorded_at":      ts_unix,
            "ttl":              ttl,
        })
        written += 1

    result = {"hour_ts": hour_ts, "written": written, "table": TABLE_NAME}
    print(f"Done: {result}")
    return {"statusCode": 200, "body": json.dumps(result)}
