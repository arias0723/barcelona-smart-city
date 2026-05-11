"""
Lambda: smart-city-uv-ingest
==============================
Fetches the current UV index for Barcelona from currentuvindex.com and writes
one record per hour to DynamoDB. Triggered by EventBridge every hour.

DynamoDB table: UVData
  PK: location_id  (S)  — "barcelona_center"
  SK: hour_ts      (S)  — "2026051214"  (YYYYMMDDHH UTC)
  TTL: ttl         (N)  — 30 days

Environment variables:
  TABLE_NAME    — DynamoDB table (default: UVData)
  DYNAMO_REGION — AWS region    (default: eu-west-1)
"""

import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "UVData")
REGION     = os.environ.get("DYNAMO_REGION", os.environ.get("AWS_REGION", "eu-west-1"))

UV_URL     = "https://currentuvindex.com/api/v1/uvi?latitude=41.3851&longitude=2.1734"

_UV_CATEGORY = [
    (2,  "low"),
    (5,  "moderate"),
    (7,  "high"),
    (10, "very high"),
    (99, "extreme"),
]

dynamodb = boto3.resource("dynamodb", region_name=REGION)


def _uv_category(uvi: float) -> str:
    for threshold, label in _UV_CATEGORY:
        if uvi <= threshold:
            return label
    return "extreme"


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
    hour_ts = now.strftime("%Y%m%d%H")
    ts_unix = int(now.timestamp())
    ttl     = ts_unix + 30 * 24 * 3600

    print(f"Fetching UV index for {hour_ts} …")

    data = _fetch_json(UV_URL)
    if data is None or not data.get("ok"):
        print("currentuvindex.com unavailable")
        return {"statusCode": 200, "body": json.dumps({"written": 0, "note": "api_unavailable"})}

    uvi      = float(data.get("now", {}).get("uvi") or 0)
    category = _uv_category(uvi)

    table = dynamodb.Table(TABLE_NAME)
    table.put_item(Item={
        "location_id": "barcelona_center",
        "hour_ts":     hour_ts,
        "uvi":         _d(uvi),
        "category":    category,
        "lat":         _d(41.3851),
        "lon":         _d(2.1734),
        "recorded_at": ts_unix,
        "ttl":         ttl,
    })

    result = {"hour_ts": hour_ts, "uvi": uvi, "category": category, "table": TABLE_NAME}
    print(f"Done: {result}")
    return {"statusCode": 200, "body": json.dumps(result)}
