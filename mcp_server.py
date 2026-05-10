"""
Barcelona Smart City — MCP Server
===================================
Exposes Barcelona city data as MCP tools, deployable as:
  - AWS Lambda + API Gateway HTTP API  (production, used by deploy.sh)
  - Local HTTP server                  (dev: python mcp_server.py)

Tools exposed:
  get_bicing            — live bike-share availability near a coordinate
  get_bicing_history    — historical snapshots for a station (last N hours)
  get_transit_nearby    — metro/bus stops near a coordinate
  get_transit_route     — A→B transit routing via Transitous
  get_air_quality       — latest air quality readings near a coordinate
  get_air_quality_history — historical readings for a station+pollutant
  get_weather           — current Barcelona weather

Environment variables:
  DYNAMO_REGION   — DynamoDB region (default: eu-west-1)
  PORT            — local HTTP port  (default: 8000)
"""

import base64
import json
import math
import os
import time
from typing import Any, Optional

import boto3
import requests
from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal
from mcp.server.fastmcp import FastMCP

from transit_route_tool import get_transit_route as _get_transit_route

DYNAMO_REGION = os.environ.get("DYNAMO_REGION", "eu-west-1")
CITYBIKES_URL = "https://api.citybik.es/v2/networks/bicing"
TMB_BASE      = "https://api.tmb.cat/v1"
TMB_APP_ID    = "74309501"
TMB_APP_KEY   = "c7234d6f7249b444f6158f41a0ad4fce"

_dynamo = boto3.resource("dynamodb", region_name=DYNAMO_REGION)

mcp = FastMCP(
    "Barcelona Smart City",
    instructions=(
        "You have access to live Barcelona city data: Bicing bike-share stations, "
        "public transit stops and routing, air quality readings, and weather. "
        "Always use coordinates in WGS-84 decimal degrees. "
        "Key Barcelona coordinates: Sagrada Família (41.4036, 2.1744), "
        "Plaça Catalunya (41.3869, 2.1699), Barceloneta (41.3807, 2.1897), "
        "UPC Campus Nord (41.3887, 2.1125), Gràcia (41.4025, 2.1567), "
        "Sants station (41.3794, 2.1405), Eixample (41.3918, 2.1596)."
    ),
)


# ---------------------------------------------------------------------------
# Shared geometry helper
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _float(v: Any) -> float:
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Tool: get_bicing
# ---------------------------------------------------------------------------

@mcp.tool()
def get_bicing(lat: float, lon: float, radius_m: int = 500, max_results: int = 5) -> dict:
    """
    Returns live Bicing bike-share station availability near a coordinate in Barcelona.
    Use when the user asks about renting a bike, finding a Bicing station, or checking
    bike/dock availability. Includes mechanical and electric bike counts.

    Args:
        lat: Latitude of the point of interest (WGS-84 decimal degrees).
        lon: Longitude of the point of interest (WGS-84 decimal degrees).
        radius_m: Search radius in metres. Default 500.
        max_results: Maximum number of stations to return, nearest first. Default 5.
    """
    try:
        r = requests.get(CITYBIKES_URL, timeout=10)
        r.raise_for_status()
        stations = r.json().get("network", {}).get("stations", [])
    except Exception as e:
        return {"error": str(e), "stations": []}

    results = []
    for s in stations:
        extra = s.get("extra", {})
        slat  = s.get("latitude", 0)
        slon  = s.get("longitude", 0)
        dist  = _haversine(lat, lon, slat, slon)
        if dist > radius_m:
            continue
        results.append({
            "station_id":      str(extra.get("uid", s.get("id", "?"))),
            "name":            s.get("name", "?").strip(),
            "distance_m":      round(dist),
            "lat":             slat,
            "lon":             slon,
            "bikes_available": int(s.get("free_bikes", 0)),
            "ebikes":          int(extra.get("ebikes", 0)),
            "mechanical":      int(extra.get("normal_bikes", 0)),
            "docks_available": int(s.get("empty_slots", 0)),
            "is_online":       bool(extra.get("online", False)),
        })
    results.sort(key=lambda x: x["distance_m"])
    return {
        "fetched_at":     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "query":          {"lat": lat, "lon": lon, "radius_m": radius_m},
        "stations_found": len(results[:max_results]),
        "stations":       results[:max_results],
    }


# ---------------------------------------------------------------------------
# Tool: get_bicing_history
# ---------------------------------------------------------------------------

@mcp.tool()
def get_bicing_history(station_id: str, hours_back: int = 24) -> dict:
    """
    Returns historical Bicing availability snapshots for a specific station.
    Useful for understanding usage patterns: when bikes run out, peak hours, etc.
    Data is stored every 5 minutes; up to 30 days of history available.

    Args:
        station_id: BSM station number as string (e.g. "106"). Get from get_bicing.
        hours_back: How many hours of history to return. Default 24, max 168 (7 days).
    """
    hours_back = min(hours_back, 168)
    since_ts   = int(time.time()) - hours_back * 3600

    try:
        table = _dynamo.Table("BicingStations")
        resp  = table.query(
            KeyConditionExpression=(
                Key("station_id").eq(station_id) &
                Key("updated_at").gte(since_ts)
            ),
            ScanIndexForward=True,
        )
        snapshots = [
            {
                "timestamp":       item["updated_at"],
                "time_utc":        time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime(int(item["updated_at"]))),
                "bikes_available": int(item.get("num_bikes_available", 0)),
                "ebikes":          int(item.get("num_ebikes_available", 0)),
                "mechanical":      int(item.get("num_mechanical_available", 0)),
                "docks_available": int(item.get("num_docks_available", 0)),
            }
            for item in resp.get("Items", [])
        ]
        return {
            "station_id":      station_id,
            "hours_back":      hours_back,
            "snapshots_found": len(snapshots),
            "snapshots":       snapshots,
        }
    except Exception as e:
        return {"error": str(e), "station_id": station_id, "snapshots": []}


# ---------------------------------------------------------------------------
# Tool: get_transit_nearby
# ---------------------------------------------------------------------------

@mcp.tool()
def get_transit_nearby(lat: float, lon: float, radius_m: int = 400, max_results: int = 8) -> dict:
    """
    Returns nearby TMB metro and bus stops near a coordinate in Barcelona,
    with route names. Use when the user asks what transport options are near
    a location, or which lines serve an area.

    Args:
        lat: Latitude of the point of interest (WGS-84 decimal degrees).
        lon: Longitude of the point of interest (WGS-84 decimal degrees).
        radius_m: Search radius in metres. Default 400 (~5 min walk).
        max_results: Maximum number of stops to return. Default 8.
    """
    try:
        table    = _dynamo.Table("TransitStops")
        lat_b    = str(round(lat, 2))
        lon_min  = Decimal(str(round(lon - 0.02, 4)))
        lon_max  = Decimal(str(round(lon + 0.02, 4)))

        resp = table.query(
            IndexName="LatBucketIndex",
            KeyConditionExpression=(
                Key("lat_bucket").eq(lat_b) &
                Key("stop_lon").between(lon_min, lon_max)
            ),
        )
        stops = []
        for item in resp.get("Items", []):
            slat = _float(item.get("stop_lat", 0))
            slon = _float(item.get("stop_lon", 0))
            dist = _haversine(lat, lon, slat, slon)
            if dist > radius_m:
                continue
            stops.append({
                "stop_id":   item.get("stop_id", "?"),
                "name":      item.get("stop_name", "?"),
                "mode":      item.get("primary_mode", "?"),
                "routes":    sorted(list(item.get("route_names", [])))[:6],
                "distance_m": round(dist),
                "lat":       slat,
                "lon":       slon,
            })
        stops.sort(key=lambda x: x["distance_m"])
        return {
            "fetched_at":   time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "query":        {"lat": lat, "lon": lon, "radius_m": radius_m},
            "stops_found":  len(stops[:max_results]),
            "stops":        stops[:max_results],
        }
    except Exception as e:
        return {"error": str(e), "stops": []}


# ---------------------------------------------------------------------------
# Tool: get_transit_route
# ---------------------------------------------------------------------------

@mcp.tool()
def get_transit_route(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    max_results: int = 3,
    depart_at: Optional[str] = None,
) -> dict:
    """
    Returns up to 3 transit journey options between two points in Barcelona
    using the Transitous open router. Each journey shows legs (walk/metro/bus/tram),
    line names, departure times, and total duration.
    Use when the user asks how to get from A to B by public transport.

    Args:
        origin_lat: Latitude of origin (WGS-84 decimal degrees).
        origin_lon: Longitude of origin (WGS-84 decimal degrees).
        dest_lat: Latitude of destination (WGS-84 decimal degrees).
        dest_lon: Longitude of destination (WGS-84 decimal degrees).
        max_results: Number of route options. Default 3.
        depart_at: ISO 8601 departure time, e.g. '2026-05-10T09:00:00'. Omit for now.
    """
    return _get_transit_route(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        max_results=max_results,
        depart_at=depart_at,
    )


# ---------------------------------------------------------------------------
# Tool: get_air_quality
# ---------------------------------------------------------------------------

_AQ_STATIONS = {
    4:  {"name": "Poblenou",           "lat": 41.4039,  "lon": 2.2045,  "district": "Sant Martí"},
    42: {"name": "Sants",              "lat": 41.3788,  "lon": 2.1331,  "district": "Sants-Montjuïc"},
    43: {"name": "Eixample",           "lat": 41.3853,  "lon": 2.1538,  "district": "Eixample"},
    44: {"name": "Gràcia",             "lat": 41.3987,  "lon": 2.1534,  "district": "Gràcia"},
    50: {"name": "Ciutadella",         "lat": 41.3864,  "lon": 2.1874,  "district": "Sant Martí"},
    54: {"name": "Vall Hebron",        "lat": 41.4261,  "lon": 2.1480,  "district": "Horta-Guinardó"},
    57: {"name": "Palau Reial",        "lat": 41.3875,  "lon": 2.1151,  "district": "Les Corts"},
    58: {"name": "Observatori Fabra",  "lat": 41.41843, "lon": 2.12390, "district": "Sarrià-Sant Gervasi"},
    60: {"name": "Navas",              "lat": 41.4159,  "lon": 2.1871,  "district": "Sant Andreu"},
}

_WHO_LIMITS = {
    "NO2":  {"good": 25,  "moderate": 50,  "poor": 100},
    "PM10": {"good": 45,  "moderate": 90,  "poor": 150},
    "O3":   {"good": 100, "moderate": 160, "poor": 240},
    "CO":   {"good": 4,   "moderate": 8,   "poor": 15},
}


def _aq_status(pollutant: str, value: float) -> str:
    limits = _WHO_LIMITS.get(pollutant, {})
    if value <= limits.get("good", 999):    return "good"
    if value <= limits.get("moderate", 999): return "moderate"
    if value <= limits.get("poor", 999):    return "poor"
    return "very poor"


@mcp.tool()
def get_air_quality(lat: float, lon: float, max_stations: int = 2) -> dict:
    """
    Returns the latest air quality readings (NO2, PM10, O3, CO) from the nearest
    Barcelona XVPCA monitoring stations. Data is live from AWS DynamoDB, updated
    hourly. Use when asked about pollution, whether it's safe to run or cycle outside,
    or which areas have the best/worst air quality.

    Args:
        lat: Latitude of the point of interest (WGS-84 decimal degrees).
        lon: Longitude of the point of interest (WGS-84 decimal degrees).
        max_stations: Number of nearest stations to return. Default 2.
    """
    ranked = sorted(
        _AQ_STATIONS.items(),
        key=lambda kv: _haversine(lat, lon, kv[1]["lat"], kv[1]["lon"])
    )[:max_stations]

    try:
        table   = _dynamo.Table("AirQualityReadings")
        results = []
        for sid, sinfo in ranked:
            dist     = round(_haversine(lat, lon, sinfo["lat"], sinfo["lon"]))
            readings = []
            for p in ["NO2", "PM10", "O3", "CO"]:
                resp = table.query(
                    KeyConditionExpression=Key("station_pollutant").eq(f"{sid}_{p}"),
                    ScanIndexForward=False,
                    Limit=1,
                )
                if resp["Items"]:
                    item = resp["Items"][0]
                    val  = _float(item["value"])
                    readings.append({
                        "pollutant":       p,
                        "value":           round(val, 1),
                        "unit":            item.get("unit", "µg/m³"),
                        "status":          _aq_status(p, val),
                        "who_limit_good":  _WHO_LIMITS.get(p, {}).get("good"),
                        "recorded_at":     item.get("hour_ts", "?"),
                    })
            results.append({
                "station_id":     sid,
                "station_name":   sinfo["name"],
                "district":       sinfo["district"],
                "distance_m":     dist,
                "readings":       readings,
                "overall_status": max(
                    (r["status"] for r in readings),
                    key=lambda s: {"good": 0, "moderate": 1, "poor": 2, "very poor": 3}.get(s, 0),
                    default="unknown",
                ),
            })
        return {
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source":     "XVPCA network via AWS DynamoDB",
            "stations":   results,
        }
    except Exception as e:
        return {"error": str(e), "stations": []}


# ---------------------------------------------------------------------------
# Tool: get_air_quality_history
# ---------------------------------------------------------------------------

@mcp.tool()
def get_air_quality_history(
    station_name: str,
    pollutant: str,
    hours_back: int = 48,
) -> dict:
    """
    Returns historical air quality readings for a specific station and pollutant.
    Useful for spotting trends: worst hours of the day, overnight vs rush-hour
    pollution, weekly patterns. Up to 30 days of hourly data available.

    Args:
        station_name: Station name, e.g. "Eixample", "Gràcia", "Poblenou", "Sants",
                      "Ciutadella", "Vall Hebron", "Palau Reial", "Navas".
        pollutant: One of "NO2", "PM10", "O3", "CO".
        hours_back: How many hours of history. Default 48, max 720 (30 days).
    """
    hours_back = min(hours_back, 720)
    pollutant  = pollutant.upper()

    station_id = next(
        (sid for sid, info in _AQ_STATIONS.items()
         if info["name"].lower() == station_name.lower()),
        None,
    )
    if station_id is None:
        valid = [info["name"] for info in _AQ_STATIONS.values()]
        return {"error": f"Unknown station '{station_name}'. Valid: {valid}"}

    from datetime import datetime, timezone, timedelta
    now       = datetime.now(timezone.utc)
    since_dt  = now - timedelta(hours=hours_back)
    since_key = since_dt.strftime("%Y%m%d%H")

    try:
        table = _dynamo.Table("AirQualityReadings")
        resp  = table.query(
            KeyConditionExpression=(
                Key("station_pollutant").eq(f"{station_id}_{pollutant}") &
                Key("hour_ts").gte(since_key)
            ),
            ScanIndexForward=True,
        )
        readings = [
            {
                "hour_ts": item["hour_ts"],
                "value":   round(_float(item["value"]), 1),
                "unit":    item.get("unit", "µg/m³"),
                "status":  _aq_status(pollutant, _float(item["value"])),
            }
            for item in resp.get("Items", [])
        ]
        return {
            "station":     _AQ_STATIONS[station_id]["name"],
            "pollutant":   pollutant,
            "hours_back":  hours_back,
            "readings_found": len(readings),
            "readings":    readings,
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool: get_weather
# ---------------------------------------------------------------------------

@mcp.tool()
def get_weather() -> dict:
    """
    Returns the current weather in Barcelona city center (temperature, humidity,
    wind, precipitation, weather description). Data is updated every hour from
    Open-Meteo via AWS DynamoDB. Use when asked about weather, temperature, rain,
    wind, or whether conditions are good for outdoor activities.
    """
    try:
        table = _dynamo.Table("WeatherData")
        resp  = table.query(
            KeyConditionExpression=Key("station_id").eq("barcelona_center"),
            ScanIndexForward=False,
            Limit=1,
        )
        if not resp["Items"]:
            return {"error": "No weather data available yet. Lambda may not have run."}
        item = resp["Items"][0]
        return {
            "fetched_at":       time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source":           "Open-Meteo via AWS DynamoDB",
            "location":         "Barcelona city center",
            "temperature_c":    _float(item.get("temperature_c", 0)),
            "feels_like_c":     _float(item.get("feels_like_c", 0)),
            "humidity_pct":     _float(item.get("humidity_pct", 0)),
            "wind_speed_kmh":   _float(item.get("wind_speed_kmh", 0)),
            "wind_direction_deg": _float(item.get("wind_direction_deg", 0)),
            "precipitation_mm": _float(item.get("precipitation_mm", 0)),
            "cloud_cover_pct":  _float(item.get("cloud_cover_pct", 0)),
            "weather_desc":     item.get("weather_desc", "?"),
            "weather_code":     int(item.get("weather_code", 0)),
        }
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tool registry — maps tool name to the actual function
# ---------------------------------------------------------------------------
_TOOL_FN = {
    "get_bicing":               get_bicing,
    "get_bicing_history":       get_bicing_history,
    "get_transit_nearby":       get_transit_nearby,
    "get_transit_route":        get_transit_route,
    "get_air_quality":          get_air_quality,
    "get_air_quality_history":  get_air_quality_history,
    "get_weather":              get_weather,
}


def _build_tool_list() -> list[dict]:
    """Return MCP tools/list response content from FastMCP's registered tools."""
    tools = []
    for t in mcp._tool_manager.list_tools():
        tools.append({
            "name":        t.name,
            "description": t.description,
            "inputSchema": t.parameters,
        })
    return tools


def _handle_jsonrpc(body: dict) -> dict:
    """Process a single JSON-RPC 2.0 MCP request and return a response dict."""
    req_id  = body.get("id")
    method  = body.get("method", "")
    params  = body.get("params", {})

    def ok(result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def err(code, msg):
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}}

    if method == "initialize":
        return ok({
            "protocolVersion": "2025-03-26",
            "capabilities":    {"tools": {}},
            "serverInfo":      {"name": "Barcelona Smart City", "version": "1.0.0"},
            "instructions":    mcp.instructions,
        })

    if method == "notifications/initialized":
        return None  # notification, no response

    if method == "ping":
        return ok({})

    if method == "tools/list":
        return ok({"tools": _build_tool_list()})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        fn = _TOOL_FN.get(tool_name)
        if fn is None:
            return err(-32601, f"Tool not found: {tool_name}")
        try:
            result = fn(**arguments)
            return ok({
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError":  False,
            })
        except Exception as e:
            return ok({
                "content": [{"type": "text", "text": str(e)}],
                "isError":  True,
            })

    return err(-32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# AWS Lambda handler — stateless JSON-RPC over API Gateway HTTP API
# ---------------------------------------------------------------------------

def handler(event, context):
    """
    Lambda entry point. Handles MCP JSON-RPC requests from API Gateway.
    Supports both single requests and batches.
    """
    body_raw = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        body_raw = base64.b64decode(body_raw).decode()
    if not body_raw:
        body_raw = "{}"

    try:
        body = json.loads(body_raw)
    except Exception:
        resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        return {
            "statusCode": 400,
            "headers":    {"Content-Type": "application/json"},
            "body":       json.dumps(resp),
        }

    if isinstance(body, list):
        responses = [r for r in (_handle_jsonrpc(req) for req in body) if r is not None]
        return {
            "statusCode": 200,
            "headers":    {"Content-Type": "application/json"},
            "body":       json.dumps(responses),
        }

    response = _handle_jsonrpc(body)
    if response is None:
        return {"statusCode": 202, "headers": {"Content-Type": "application/json"}, "body": ""}

    return {
        "statusCode": 200,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(response),
    }


# ---------------------------------------------------------------------------
# Local dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting Barcelona Smart City MCP server on http://0.0.0.0:{port}/mcp")
    print("Connect from Claude Desktop / claude.ai with:")
    print(f'  URL: http://localhost:{port}/mcp  (local)')
    print(f'  Production: https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp')
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")
