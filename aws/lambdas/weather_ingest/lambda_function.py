"""
Lambda: smart-city-weather-ingest
===================================
Fetches current weather for Barcelona from Open-Meteo (no API key needed)
and writes to DynamoDB. Triggered by EventBridge every hour.

Data source: https://open-meteo.com/
  - Free, no auth, updated hourly
  - WMO weather codes: https://open-meteo.com/en/docs#weathervariables

DynamoDB table: WeatherData
  PK: station_id (S)   — e.g. "barcelona_center"
  SK: timestamp  (N)   — Unix epoch of this write
  TTL: ttl       (N)   — 30 days (enables historical queries)

Environment variables:
  TABLE_NAME   — DynamoDB table (default: WeatherData)
  AWS_REGION   — AWS region    (default: eu-west-1)
"""

import json
import os
import time
import urllib.request
import urllib.error
from decimal import Decimal, InvalidOperation

import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "WeatherData")
REGION     = os.environ.get("DYNAMO_REGION", os.environ.get("AWS_REGION", "eu-west-1"))

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=41.3851&longitude=2.1734"
    "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
    "precipitation,weather_code,wind_speed_10m,wind_direction_10m,"
    "surface_pressure,cloud_cover,visibility"
    "&timezone=Europe%2FMadrid"
)

# WMO weather interpretation codes → human-readable description
WMO_DESCRIPTIONS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Icy fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}

dynamodb = boto3.resource("dynamodb", region_name=REGION)


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
    if v is None:
        return Decimal("0")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return Decimal("0")


def lambda_handler(event, context):
    print("Fetching Barcelona weather from Open-Meteo …")

    data = _fetch(OPEN_METEO_URL)
    if data is None:
        msg = "Open-Meteo API unavailable"
        print(msg)
        return {"statusCode": 503, "body": msg}

    current = data.get("current", {})
    now     = int(time.time())
    ttl     = now + 30 * 24 * 3600  # 30 days

    weather_code = int(current.get("weather_code", 0))
    weather_desc = WMO_DESCRIPTIONS.get(weather_code, f"Code {weather_code}")

    item = {
        "station_id":          "barcelona_center",
        "timestamp":           now,
        "lat":                 _d(41.3851),
        "lon":                 _d(2.1734),
        "temperature_c":       _d(current.get("temperature_2m")),
        "feels_like_c":        _d(current.get("apparent_temperature")),
        "humidity_pct":        _d(current.get("relative_humidity_2m")),
        "wind_speed_kmh":      _d(current.get("wind_speed_10m")),
        "wind_direction_deg":  _d(current.get("wind_direction_10m")),
        "precipitation_mm":    _d(current.get("precipitation")),
        "cloud_cover_pct":     _d(current.get("cloud_cover")),
        "visibility_m":        _d(current.get("visibility")),
        "pressure_hpa":        _d(current.get("surface_pressure")),
        "weather_code":        weather_code,
        "weather_desc":        weather_desc,
        "source":              "open-meteo",
        "ttl":                 ttl,
    }

    table = dynamodb.Table(TABLE_NAME)
    table.put_item(Item=item)

    result = {"written": 1, "timestamp": now, "weather": weather_desc, "table": TABLE_NAME}
    print(f"Done: {result}")
    return {"statusCode": 200, "body": json.dumps(result)}
