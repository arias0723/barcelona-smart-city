"""
Barcelona Smart City — MCP Demo
FastAPI backend: serves the UI, exposes tool endpoints, runs Claude chat with tool use.
"""
from __future__ import annotations
import json
import os
import sys
import time
from decimal import Decimal
from typing import Any, AsyncGenerator

import polyline as pl
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from transit_route_tool import get_transit_route, MCP_TOOL_GET_TRANSIT_ROUTE

# ---------------------------------------------------------------------------
# Bedrock / Anthropic client
# ---------------------------------------------------------------------------
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.config import Config

BEDROCK_REGION = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION") or "eu-north-1"
DYNAMO_REGION  = os.environ.get("DYNAMO_REGION") or "eu-west-1"   # tables live here
MODEL_ID       = os.environ.get("BEDROCK_MODEL_ID") or "eu.anthropic.claude-haiku-4-5-20251001-v1:0"

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=BEDROCK_REGION,
    config=Config(
        read_timeout=120,
        connect_timeout=10,
        retries={"max_attempts": 2},
    ),
)

# ---------------------------------------------------------------------------
# Also expose Bicing and nearby-transit as tools for the chatbot
# ---------------------------------------------------------------------------
TOOL_GET_BICING = {
    "name": "get_bicing",
    "description": (
        "Returns real-time Bicing bike-share station availability near a coordinate "
        "in Barcelona. Use when the user asks about renting a bike, finding a Bicing "
        "station, checking bike or dock availability. Includes mechanical and electric "
        "bike counts, distance, and data freshness."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lat":          {"type": "number", "description": "Latitude (WGS-84)."},
            "lon":          {"type": "number", "description": "Longitude (WGS-84)."},
            "max_results":  {"type": "integer", "description": "Max stations to return. Default 5.", "default": 5},
            "max_radius_m": {"type": "integer", "description": "Hard distance cap in metres. Default 1500.", "default": 1500},
        },
        "required": ["lat", "lon"],
    },
}

TOOL_GET_TRANSIT_NEARBY = {
    "name": "get_transit_nearby",
    "description": (
        "Returns nearby TMB metro and bus stops near a coordinate in Barcelona, "
        "with route names and live bus arrivals. Use when the user asks what "
        "transport options are near a location, or wants to know which lines "
        "serve an area."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lat":          {"type": "number", "description": "Latitude (WGS-84)."},
            "lon":          {"type": "number", "description": "Longitude (WGS-84)."},
            "max_results":  {"type": "integer", "description": "Max stops to return. Default 5.", "default": 5},
            "max_radius_m": {"type": "integer", "description": "Hard distance cap in metres. Default 1500.", "default": 1500},
        },
        "required": ["lat", "lon"],
    },
}

TOOL_GET_AIR_QUALITY = {
    "name": "get_air_quality",
    "description": (
        "Returns the latest air quality readings (NO2, PM10, O3, CO) from the nearest "
        "Barcelona XVPCA monitoring station. Data is live from AWS DynamoDB, updated every hour. "
        "Use when the user asks about air quality, pollution levels, whether it is safe to run "
        "or cycle outside, or which areas have the best/worst air quality. "
        "Stations: Poblenou, Sants, Eixample, Gràcia, Ciutadella, Vall Hebron, "
        "Palau Reial, Observatori Fabra, Navas."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {"type": "number", "description": "Latitude of the point of interest (WGS-84)."},
            "lon": {"type": "number", "description": "Longitude of the point of interest (WGS-84)."},
            "max_stations": {"type": "integer", "description": "Number of nearest stations to return. Default 2.", "default": 2},
        },
        "required": ["lat", "lon"],
    },
}

ALL_TOOLS = [MCP_TOOL_GET_TRANSIT_ROUTE, TOOL_GET_BICING, TOOL_GET_TRANSIT_NEARBY, TOOL_GET_AIR_QUALITY]

# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

TMB_APP_ID     = "74309501"
TMB_APP_KEY    = "c7234d6f7249b444f6158f41a0ad4fce"
CITYBIKES_URL  = "https://api.citybik.es/v2/networks/bicing"  # BSM API blocked as of May 2026
TMB_BASE       = "https://api.tmb.cat/v1"


def run_tool(name: str, inputs: dict) -> Any:
    if name == "get_transit_route":
        return get_transit_route(**inputs)

    if name == "get_bicing":
        lat          = inputs["lat"]
        lon          = inputs["lon"]
        max_results  = inputs.get("max_results", 5)
        max_radius_m = inputs.get("max_radius_m", 1500)
        try:
            r = requests.get(CITYBIKES_URL, timeout=10)
            if not r.ok:
                return {"error": f"citybik.es returned {r.status_code}", "stations": []}
            stations = r.json().get("network", {}).get("stations", [])
            results = []
            for s in stations:
                extra = s.get("extra", {})
                slat  = s.get("latitude", 0)
                slon  = s.get("longitude", 0)
                dist  = _haversine(lat, lon, slat, slon)
                if dist > max_radius_m:
                    continue
                results.append({
                    "station_id":    str(extra.get("uid", s.get("id", "?"))),
                    "name":          s.get("name", "?").strip(),
                    "distance_m":    round(dist),
                    "lat":           slat,
                    "lon":           slon,
                    "bikes_available": int(s.get("free_bikes", 0)),
                    "ebikes":          int(extra.get("ebikes", 0)),
                    "mechanical":      int(extra.get("normal_bikes", 0)),
                    "docks_available": int(s.get("empty_slots", 0)),
                    "is_renting":      bool(extra.get("online", False)),
                    "last_reported":   s.get("timestamp", ""),
                })
            results.sort(key=lambda x: x["distance_m"])
            return {
                "fetched_at":    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stations_found": len(results[:max_results]),
                "stations":       results[:max_results],
            }
        except Exception as e:
            return {"error": str(e), "stations": []}

    if name == "get_transit_nearby":
        lat  = inputs["lat"]
        lon  = inputs["lon"]
        max_results  = inputs.get("max_results", 5)
        max_radius_m = inputs.get("max_radius_m", 1500)
        try:
            r = requests.get(
                f"{TMB_BASE}/transit/parades",
                params={"app_id": TMB_APP_ID, "app_key": TMB_APP_KEY},
                timeout=10,
            )
            if not r.ok:
                return {"error": f"TMB API {r.status_code}", "stops": []}
            features = r.json().get("features", [])
            stops = []
            for f in features:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [0, 0])
                slon, slat = coords[0], coords[1]
                dist = _haversine(lat, lon, slat, slon)
                if dist > max_radius_m:
                    continue
                stops.append({
                    "stop_id": props.get("CODI_PARADA"),
                    "name": props.get("NOM_PARADA", "?"),
                    "address": props.get("ADRECA", ""),
                    "distance_m": round(dist),
                    "lat": slat, "lon": slon,
                })
            stops.sort(key=lambda x: x["distance_m"])
            # enrich bus stops with live arrivals (top 3 only)
            for stop in stops[:3]:
                codi = stop["stop_id"]
                try:
                    ar = requests.get(
                        f"{TMB_BASE}/ibus/stops/{codi}",
                        params={"app_id": TMB_APP_ID, "app_key": TMB_APP_KEY},
                        timeout=5,
                    )
                    if ar.ok:
                        arrivals = ar.json().get("data", {}).get("ibus", [])
                        stop["next_arrivals"] = [
                            {"line": a.get("line"), "destination": a.get("destination"),
                             "minutes": a.get("t-in-min")}
                            for a in arrivals[:3]
                        ]
                except Exception:
                    pass
            return {
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "stops_found": len(stops[:max_results]),
                "stops": stops[:max_results],
            }
        except Exception as e:
            return {"error": str(e), "stops": []}

    if name == "get_air_quality":
        lat          = inputs["lat"]
        lon          = inputs["lon"]
        max_stations = inputs.get("max_stations", 2)

        stations = {
            4:  {"name": "Poblenou",          "lat": 41.4039,  "lon": 2.2045,  "district": "Sant Martí"},
            42: {"name": "Sants",             "lat": 41.3788,  "lon": 2.1331,  "district": "Sants-Montjuïc"},
            43: {"name": "Eixample",          "lat": 41.3853,  "lon": 2.1538,  "district": "Eixample"},
            44: {"name": "Gràcia",            "lat": 41.3987,  "lon": 2.1534,  "district": "Gràcia"},
            50: {"name": "Ciutadella",        "lat": 41.3864,  "lon": 2.1874,  "district": "Sant Martí"},
            54: {"name": "Vall Hebron",       "lat": 41.4261,  "lon": 2.1480,  "district": "Horta-Guinardó"},
            57: {"name": "Palau Reial",       "lat": 41.3875,  "lon": 2.1151,  "district": "Les Corts"},
            58: {"name": "Observatori Fabra", "lat": 41.41843, "lon": 2.12390, "district": "Sarrià-Sant Gervasi"},
            60: {"name": "Navas",             "lat": 41.4159,  "lon": 2.1871,  "district": "Sant Andreu"},
        }
        who_limits = {
            "NO2":  {"good": 25,  "moderate": 50,  "poor": 100},
            "PM10": {"good": 45,  "moderate": 90,  "poor": 150},
            "O3":   {"good": 100, "moderate": 160, "poor": 240},
            "CO":   {"good": 4,   "moderate": 8,   "poor": 15},
        }

        # Sort by distance, take nearest N
        ranked = sorted(
            stations.items(),
            key=lambda kv: _haversine(lat, lon, kv[1]["lat"], kv[1]["lon"])
        )[:max_stations]

        try:
            table = _dynamodb_res.Table("AirQualityReadings")
            results = []
            for sid, sinfo in ranked:
                dist = round(_haversine(lat, lon, sinfo["lat"], sinfo["lon"]))
                readings = []
                for p in ["NO2", "PM10", "O3", "CO"]:
                    resp = table.query(
                        KeyConditionExpression=Key("station_pollutant").eq(f"{sid}_{p}"),
                        ScanIndexForward=False,
                        Limit=1,
                    )
                    if resp["Items"]:
                        item = resp["Items"][0]
                        val  = float(item["value"])
                        unit = item.get("unit", "µg/m³")
                        hour_ts = str(item.get("hour_ts", ""))
                        hour_fmt = f"{hour_ts[8:10]}:00 UTC" if len(hour_ts) >= 10 else "?"
                        limits = who_limits.get(p, {})
                        if val <= limits.get("good", 999):
                            status = "good"
                        elif val <= limits.get("moderate", 999):
                            status = "moderate"
                        elif val <= limits.get("poor", 999):
                            status = "poor"
                        else:
                            status = "very poor"
                        readings.append({
                            "pollutant": p, "value": round(val, 1), "unit": unit,
                            "status": status, "recorded_at": hour_fmt,
                            "who_limit_good": limits.get("good"),
                        })
                results.append({
                    "station_id": sid,
                    "station_name": sinfo["name"],
                    "district": sinfo["district"],
                    "distance_m": dist,
                    "lat": sinfo["lat"], "lon": sinfo["lon"],
                    "readings": readings,
                    "overall_status": max(
                        (r["status"] for r in readings),
                        key=lambda s: {"good": 0, "moderate": 1, "poor": 2, "very poor": 3}.get(s, 0),
                        default="unknown"
                    ),
                })
            return {
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": "AWS DynamoDB · AirQualityReadings · XVPCA network",
                "stations": results,
            }
        except Exception as e:
            return {"error": str(e), "stations": []}

    return {"error": f"Unknown tool: {name}"}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Barcelona Smart City Demo")

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []
    user_location: dict | None = None  # {lat, lon} if browser granted geolocation


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(os.path.dirname(__file__), "index.html")) as f:
        return f.read()


@app.post("/api/route")
async def api_route(body: dict):
    """Direct tool call endpoint — returns route + decoded polylines for the map."""
    result = get_transit_route(
        origin_lat=body["origin_lat"],
        origin_lon=body["origin_lon"],
        dest_lat=body["dest_lat"],
        dest_lon=body["dest_lon"],
        max_results=body.get("max_results", 3),
    )
    # Decode polylines for Leaflet
    _decode_polylines(result)
    return result


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """
    Streaming chat endpoint. Claude uses tool_use to call our tools.
    Response is newline-delimited JSON events:
      {"type": "text",      "content": "..."}
      {"type": "tool_call", "tool": "...", "input": {...}}
      {"type": "tool_result","tool": "...", "result": {...}, "map_data": {...}}
      {"type": "done"}
    """
    return StreamingResponse(
        _chat_stream(req.message, req.history, req.user_location),
        media_type="application/x-ndjson",
    )


async def _chat_stream(user_message: str, history: list[dict], user_location: dict | None = None) -> AsyncGenerator[str, None]:
    loc_line = ""
    if user_location:
        loc_line = (
            f"\nUSER'S CURRENT LOCATION: lat={user_location['lat']:.5f}, lon={user_location['lon']:.5f} "
            f"(GPS from browser). Use these coordinates as origin when the user says 'my location', "
            f"'I am here', 'from here', or similar.\n"
        )

    system = (
        "You are a Barcelona mobility assistant integrated into a smart city platform. "
        "You have access to real-time tools for transit routing, Bicing bike-share, and nearby transit stops.\n"
        + loc_line +
        "\nKEY LOCATIONS (use these coordinates when user mentions these places):\n"
        "- El Raval / Carrer del Carme: 41.3807, 2.1677\n"
        "- UPC Campus Nord (Diagonal): 41.3887, 2.1125\n"
        "- UPC Campus Sud / ETSEIB: 41.3845, 2.1133\n"
        "- Sagrada Família: 41.4036, 2.1744\n"
        "- Barceloneta beach: 41.3807, 2.1897\n"
        "- Gràcia: 41.4025, 2.1567\n"
        "- Plaça Catalunya: 41.3869, 2.1699\n"
        "- Sants station: 41.3794, 2.1405\n"
        "- Eixample centre: 41.3918, 2.1596\n"
        "- Passeig de Gràcia: 41.3927, 2.1649\n"
        "- Born / El Born: 41.3851, 2.1820\n"
        "- Poble Sec: 41.3733, 2.1599\n\n"
        "When the user mentions a street, neighbourhood, or landmark, look it up in the list above or infer "
        "approximate Barcelona coordinates and call the tools directly — do not ask for coordinates. "
        "When you call get_transit_route, present results briefly in text (the UI renders route cards automatically). "
        "Be concise. Respond in the same language the user writes in."
    )

    messages = history + [{"role": "user", "content": user_message}]

    # Agentic loop — keep going until no more tool calls
    while True:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "system": system,
            "tools": ALL_TOOLS,
            "messages": messages,
        }

        response = bedrock.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json",
        )
        resp = json.loads(response["body"].read())
        stop_reason = resp.get("stop_reason")
        content     = resp.get("content", [])

        # Stream text blocks
        for block in content:
            if block["type"] == "text":
                yield json.dumps({"type": "text", "content": block["text"]}) + "\n"

        if stop_reason != "tool_use":
            break

        # Process tool calls
        tool_results = []
        for block in content:
            if block["type"] != "tool_use":
                continue

            tool_name   = block["name"]
            tool_input  = block["input"]
            tool_use_id = block["id"]

            # Notify client about the tool call
            yield json.dumps({
                "type": "tool_call",
                "tool": tool_name,
                "input": tool_input,
            }) + "\n"

            # Execute
            result = run_tool(tool_name, tool_input)

            # Decode polylines for map rendering
            map_data = None
            if tool_name == "get_transit_route" and "routes" in result:
                import copy
                map_data = copy.deepcopy(result)
                _decode_polylines(map_data)

            # Send result to client
            yield json.dumps({
                "type": "tool_result",
                "tool": tool_name,
                "result": result,
                "map_data": map_data,
            }) + "\n"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": json.dumps(result),
            })

        # Add assistant turn + tool results to message history
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user",      "content": tool_results})

    yield json.dumps({"type": "done"}) + "\n"


# ---------------------------------------------------------------------------
# City layer data (AQ, transit stops, infra stats)
# ---------------------------------------------------------------------------
_dynamodb_res = boto3.resource("dynamodb", region_name=DYNAMO_REGION)

_AQ_THRESHOLDS = {
    "NO2":  [(25, "good", "#22c55e"), (50, "moderate", "#eab308"), (100, "poor", "#f97316"), (999, "very poor", "#ef4444")],
    "PM10": [(45, "good", "#22c55e"), (90, "moderate", "#eab308"), (150, "poor", "#f97316"), (999, "very poor", "#ef4444")],
    "O3":   [(100, "good", "#22c55e"), (160, "moderate", "#eab308"), (240, "poor", "#f97316"), (999, "very poor", "#ef4444")],
    "CO":   [(4,  "good", "#22c55e"), (8,   "moderate", "#eab308"), (15,  "poor", "#f97316"), (999, "very poor", "#ef4444")],
}
_AQ_STATIONS = {
    4:  {"name": "Poblenou",          "lat": 41.4039,  "lon": 2.2045},
    42: {"name": "Sants",             "lat": 41.3788,  "lon": 2.1331},
    43: {"name": "Eixample",          "lat": 41.3853,  "lon": 2.1538},
    44: {"name": "Gràcia",            "lat": 41.3987,  "lon": 2.1534},
    50: {"name": "Ciutadella",        "lat": 41.3864,  "lon": 2.1874},
    54: {"name": "Vall Hebron",       "lat": 41.4261,  "lon": 2.1480},
    57: {"name": "Palau Reial",       "lat": 41.3875,  "lon": 2.1151},
    58: {"name": "Observatori Fabra", "lat": 41.41843, "lon": 2.12390},
    60: {"name": "Navas",             "lat": 41.4159,  "lon": 2.1871},
}


def _aq_status(pollutant: str, value: float) -> tuple[str, str]:
    for threshold, label, color in _AQ_THRESHOLDS.get(pollutant, [(999, "ok", "#22c55e")]):
        if value <= threshold:
            return label, color
    return "very poor", "#ef4444"


def _fetch_air_quality() -> list[dict]:
    table = _dynamodb_res.Table("AirQualityReadings")
    priority = {"very poor": 3, "poor": 2, "moderate": 1, "good": 0, "ok": 0}
    results = []
    for sid, sinfo in _AQ_STATIONS.items():
        readings = []
        for p in ["NO2", "PM10", "O3", "CO"]:
            resp = table.query(
                KeyConditionExpression=Key("station_pollutant").eq(f"{sid}_{p}"),
                ScanIndexForward=False,
                Limit=1,
            )
            if resp["Items"]:
                item = resp["Items"][0]
                val = float(item["value"])
                label, color = _aq_status(p, val)
                hour_ts = str(item.get("hour_ts", ""))
                readings.append({
                    "pollutant": p, "value": round(val, 1),
                    "unit": item.get("unit", "µg/m³"),
                    "status": label, "color": color,
                    "hour": f"{hour_ts[8:10]}:00" if len(hour_ts) >= 10 else "?",
                })
        worst_label, worst_color = "good", "#22c55e"
        for r in readings:
            if priority.get(r["status"], 0) > priority.get(worst_label, 0):
                worst_label, worst_color = r["status"], r["color"]
        results.append({
            **sinfo, "station_id": sid,
            "readings": readings,
            "overall_status": worst_label,
            "overall_color": worst_color,
        })
    return results


def _fetch_transit_stops(limit_metro: int = 300, limit_bus: int = 150) -> tuple[list, list]:
    table = _dynamodb_res.Table("TransitStops")
    metro_stops, bus_stops = [], []
    last_key = None
    while len(metro_stops) < limit_metro:
        kwargs: dict = {"FilterExpression": Attr("primary_mode").eq("metro")}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            metro_stops.append({
                "stop_id": item["stop_id"],
                "name": item.get("stop_name", ""),
                "lat": float(item["stop_lat"]),
                "lon": float(item["stop_lon"]),
                "routes": sorted(list(item.get("route_names", [])))[:6],
            })
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    last_key = None
    while len(bus_stops) < limit_bus:
        kwargs = {
            "FilterExpression": (
                Attr("primary_mode").eq("bus") &
                Attr("stop_lon").between(Decimal("2.09"), Decimal("2.23")) &
                Attr("stop_lat").between(Decimal("41.33"), Decimal("41.47"))
            )
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            bus_stops.append({
                "stop_id": item["stop_id"],
                "name": item.get("stop_name", ""),
                "lat": float(item["stop_lat"]),
                "lon": float(item["stop_lon"]),
                "routes": sorted(list(item.get("route_names", [])))[:5],
            })
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return metro_stops, bus_stops


def _fetch_table_stats() -> dict:
    client = boto3.client("dynamodb", region_name=DYNAMO_REGION)
    stats: dict = {}
    for name in ["BicingStations", "TransitStops", "ScheduleCache",
                 "AirQualityReadings", "WeatherData", "NoiseData"]:
        try:
            meta = client.describe_table(TableName=name)["Table"]
            stats[name] = {"status": meta["TableStatus"], "items": meta.get("ItemCount", 0)}
        except Exception:
            stats[name] = {"status": "NOT_FOUND", "items": 0}
    return stats


@app.get("/api/layers")
async def api_layers():
    """Live DynamoDB data for map layer overlays (AQ, metro, bus, infra stats)."""
    aq = _fetch_air_quality()
    metro, bus = _fetch_transit_stops()
    stats = _fetch_table_stats()
    return JSONResponse({"aq": aq, "metro": metro, "bus": bus, "stats": stats})


def _decode_polylines(result: dict) -> None:
    """Decode Transitous encoded polylines in-place for Leaflet consumption."""
    for route in result.get("routes", []):
        for leg in route.get("legs", []):
            enc = leg.get("_polyline")
            if enc:
                try:
                    leg["latlngs"] = pl.decode(enc, 6)  # Transitous uses precision=6
                except Exception:
                    pass
