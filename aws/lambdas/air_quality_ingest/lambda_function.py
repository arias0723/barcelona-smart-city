"""
Lambda: smart-city-air-quality-ingest
======================================
Fetches Barcelona air quality readings from Open Data BCN (CKAN datastore)
and writes the latest hourly values to DynamoDB.
Triggered by EventBridge every hour.

Source: https://opendata-ajuntament.barcelona.cat/data/en/dataset/qualitat-aire-detall-bcn
Resource ID: c2032e7c-10ee-4c69-84d3-9e8caf9ca97a  (live, hourly-updated CSV)

Data structure: one row = one (station, pollutant, day) with H01–H24 hourly columns
                V01–V24 are validation flags ('V' = valid, 'N' = not valid)

DynamoDB table: AirQualityReadings
  PK: station_pollutant (S)  — e.g. "43_NO2"
  SK: hour_ts           (S)  — e.g. "2026042714"  (YYYYMMDDHH)
  GSI: LatBucketIndex        — lat_bucket (S) + hour_ts (S)
  TTL: ttl (N)               — 48 hours after recording

Environment variables:
  TABLE_NAME   — DynamoDB table (default: AirQualityReadings)
  AWS_REGION   — AWS region    (default: eu-west-1)
"""

import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
TABLE_NAME  = os.environ.get("TABLE_NAME", "AirQualityReadings")
REGION      = os.environ.get("AWS_REGION", "eu-west-1")

CKAN_BASE   = "https://opendata-ajuntament.barcelona.cat/data/api/action/datastore_search"
RESOURCE_ID = "c2032e7c-10ee-4c69-84d3-9e8caf9ca97a"

# Barcelona XVPCA monitoring stations — coordinates from Open Data BCN 2026 stations dataset
STATIONS: dict[int, dict] = {
    4:  {"name": "Poblenou",         "lat": 41.4039,  "lon": 2.2045,  "district": "Sant Martí"},
    42: {"name": "Sants",            "lat": 41.3788,  "lon": 2.1331,  "district": "Sants-Montjuïc"},
    43: {"name": "Eixample",         "lat": 41.3853,  "lon": 2.1538,  "district": "Eixample"},
    44: {"name": "Gràcia",           "lat": 41.3987,  "lon": 2.1534,  "district": "Gràcia"},
    50: {"name": "Ciutadella",       "lat": 41.3864,  "lon": 2.1874,  "district": "Sant Martí"},
    54: {"name": "Vall Hebron",      "lat": 41.4261,  "lon": 2.1480,  "district": "Horta-Guinardó"},
    57: {"name": "Palau Reial",      "lat": 41.3875,  "lon": 2.1151,  "district": "Les Corts"},
    58: {"name": "Observatori Fabra","lat": 41.41843, "lon": 2.12390, "district": "Sarrià-Sant Gervasi"},
    60: {"name": "Navas",            "lat": 41.4159,  "lon": 2.1871,  "district": "Sant Andreu"},
}

# Pollutant code → name/unit (standard Catalan air quality codes)
POLLUTANTS: dict[int, dict] = {
    1:  {"name": "SO2",   "unit": "µg/m³"},
    6:  {"name": "CO",    "unit": "mg/m³"},
    7:  {"name": "NO",    "unit": "µg/m³"},
    8:  {"name": "NO2",   "unit": "µg/m³"},
    9:  {"name": "NOX",   "unit": "µg/m³"},
    10: {"name": "PM10",  "unit": "µg/m³"},
    14: {"name": "O3",    "unit": "µg/m³"},
    35: {"name": "PM2.5", "unit": "µg/m³"},
}

dynamodb = boto3.resource("dynamodb", region_name=REGION)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fetch_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "smart-city-ingest/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
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


def _latest_valid_hour(record: dict, up_to_hour: int) -> tuple[int, float] | None:
    """
    Scan H24..H01 backwards from up_to_hour to find the most recent validated reading.
    Returns (hour_1_to_24, value) or None if no valid reading found.
    """
    # GBFS hours: H01=1:00, H24=midnight(end-of-day)
    # up_to_hour is 0-23 (Python datetime hour)
    # Map 0 → check H24 from yesterday (skip); start from H23 backwards
    max_h = up_to_hour if up_to_hour > 0 else 1

    for h in range(max_h, 0, -1):
        hkey = f"H{h:02d}"
        vkey = f"V{h:02d}"
        raw  = record.get(hkey)
        flag = record.get(vkey, "N")
        if raw is not None and flag == "V":
            try:
                return (h, float(raw))
            except (ValueError, TypeError):
                continue
    return None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    now      = datetime.now(timezone.utc)
    year     = now.year
    month    = now.month
    day      = now.day
    cur_hour = now.hour  # 0-23

    print(f"Fetching air quality for {year}-{month:02d}-{day:02d} (hour {cur_hour}) …")

    # Build CKAN query — filter to today's rows
    filters  = json.dumps({"ANY": str(year), "MES": str(month), "DIA": str(day)})
    url      = (
        f"{CKAN_BASE}"
        f"?resource_id={RESOURCE_ID}"
        f"&limit=500"
        f"&filters={urllib.parse.quote(filters)}"
    )

    data = _fetch_json(url)
    if data is None or not data.get("success"):
        msg = "CKAN API unavailable or returned error"
        print(msg)
        return {"statusCode": 503, "body": msg}

    records  = data["result"]["records"]
    ts_unix  = int(now.timestamp())
    ttl      = ts_unix + 30 * 24 * 3600  # 30 days — enables historical queries

    table    = dynamodb.Table(TABLE_NAME)
    written  = 0
    skipped  = 0

    with table.batch_writer() as batch:
        for rec in records:
            station_id      = int(rec.get("ESTACIO", 0))
            pollutant_code  = int(rec.get("CODI_CONTAMINANT", 0))

            pollutant_info  = POLLUTANTS.get(pollutant_code)
            station_info    = STATIONS.get(station_id)
            if not pollutant_info or not station_info:
                skipped += 1
                continue

            reading = _latest_valid_hour(rec, cur_hour)
            if reading is None:
                skipped += 1
                continue

            valid_hour, value = reading
            hour_ts = f"{year}{month:02d}{day:02d}{valid_hour:02d}"

            item = {
                "station_pollutant": f"{station_id}_{pollutant_info['name']}",
                "hour_ts":           hour_ts,
                "station_id":        station_id,
                "station_name":      station_info["name"],
                "district":          station_info["district"],
                "lat":               _d(station_info["lat"]),
                "lon":               _d(station_info["lon"]),
                "lat_bucket":        str(round(station_info["lat"], 2)),
                "pollutant_code":    pollutant_code,
                "pollutant_name":    pollutant_info["name"],
                "unit":              pollutant_info["unit"],
                "value":             _d(value),
                "validated":         True,
                "recorded_at":       ts_unix,
                "ttl":               ttl,
            }

            try:
                batch.put_item(Item=item)
                written += 1
            except Exception as e:
                print(f"Write error {station_id}/{pollutant_code}: {e}")
                skipped += 1

    result = {
        "date":    f"{year}-{month:02d}-{day:02d}",
        "hour":    cur_hour,
        "records": len(records),
        "written": written,
        "skipped": skipped,
        "table":   TABLE_NAME,
    }
    print(f"Done: {result}")
    return {"statusCode": 200, "body": json.dumps(result)}
