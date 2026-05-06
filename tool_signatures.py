"""
tool_signatures.py
==================
MCP tool pseudocode for the Barcelona Smart City mobility vertical.

Three tools are defined:
  - get_bicing(lat, lon, max_results, max_radius_m) — real-time Bicing bike-share availability
  - get_transit(lat, lon, max_results, max_radius_m) — nearby TMB transit stops & live departures
  - get_transit_route(origin_lat, origin_lon, dest_lat, dest_lon, max_transfers) — A→B transit routing

Design principles:
  1. The 'description' field is what the LLM orchestrator reads to decide
     WHEN to call the tool and what to pass as arguments — precision matters.
  2. Return values are dicts that are JSON-serialisable for easy MCP transport.
  3. Haversine filtering happens in-process before hitting DynamoDB, so we
     never pull the whole table to the Lambda.
  4. Errors surface as {"error": "message"} so callers can degrade gracefully.
"""

from __future__ import annotations
import math
import time
from typing import Any


# ---------------------------------------------------------------------------
# Shared geometry helper
# ---------------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Return the great-circle distance in metres between two WGS-84 coordinates.

    Uses the Haversine formula — accurate to < 0.5% for distances < 100 km.

    Example:
        >>> haversine_m(41.4036, 2.1744, 41.4011, 2.1744)
        278.3   # metres
    """
    R = 6_371_000  # Earth radius, metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi   = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Tool 1 — get_bicing
# ---------------------------------------------------------------------------
MCP_TOOL_GET_BICING = {
    "name": "get_bicing",
    "description": (
        "Returns real-time Bicing bike-share station availability near a "
        "geographic coordinate in Barcelona. "
        "Use this tool when the user asks about renting a bike, finding a "
        "Bicing station, checking bike or dock availability, or wants to "
        "compare cycling vs transit options. "
        "Results are sorted by distance ascending. Always includes distance_m "
        "per station so the LLM can judge walkability. "
        "The response includes both mechanical and electric bike counts, "
        "station names, and a freshness timestamp. "
        "Returns an error dict if the Bicing API is unavailable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {
                "type": "number",
                "description": "Latitude of the query point (WGS-84 decimal degrees).",
            },
            "lon": {
                "type": "number",
                "description": "Longitude of the query point (WGS-84 decimal degrees).",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of stations to return, sorted nearest-first. Default 5.",
                "default": 5,
            },
            "max_radius_m": {
                "type": "integer",
                "description": "Hard cap on search radius in metres. Stations beyond this are never returned even if fewer than max_results exist. Default 1500.",
                "default": 1500,
            },
        },
        "required": ["lat", "lon"],
    },
}


def get_bicing(lat: float, lon: float, max_results: int = 5, max_radius_m: int = 1500) -> dict[str, Any]:
    """
    Fetch nearby Bicing stations from DynamoDB cache and return availability.

    Data flow:
      1. Query DynamoDB BicingStations table (GSI: geohash prefix or lat/lon range)
      2. Filter in-process with haversine to exact radius
      3. Sort by distance ascending
      4. Return structured response

    Example return value:
    {
        "query": {"lat": 41.4036, "lon": 2.1744, "radius_m": 500},
        "fetched_at": "2026-04-23T19:00:00Z",
        "data_age_seconds": 45,          # age of the freshest cache record
        "stations_found": 4,
        "stations": [
            {
                "station_id": "420",
                "name": "C/ de la Sagrada Família, 10",
                "distance_m": 87,
                "lat": 41.4031,
                "lon": 2.1747,
                "bikes_available": 7,
                "docks_available": 12,
                "ebikes": 3,
                "mechanical": 4,
                "capacity": 20,
                "is_renting": True,
                "is_returning": True,
                "last_reported": "2026-04-23T18:59:15Z"
            },
            # … up to radius_m worth of stations
        ]
    }

    Error response (API outage / cache miss):
    {
        "error": "Bicing API unavailable",
        "detail": "BSM GBFS endpoint returned 503 after 5 retries",
        "retry_after_seconds": 60
    }
    """
    # --- Pseudocode: production implementation would do this ---

    # Step 1: Query DynamoDB for candidate stations
    # We use a lat/lon bounding-box pre-filter (cheap DynamoDB scan on a GSI)
    # to avoid loading the entire ~500-station table into Lambda memory.
    lat_delta = radius_m / 111_320          # degrees lat per metre
    lon_delta = radius_m / (111_320 * math.cos(math.radians(lat)))

    # dynamodb_client.query(
    #     TableName="BicingStations",
    #     IndexName="LatLonIndex",
    #     FilterExpression="lat BETWEEN :lat_min AND :lat_max "
    #                      "AND lon BETWEEN :lon_min AND :lon_max",
    #     ExpressionAttributeValues={
    #         ":lat_min": lat - lat_delta,
    #         ":lat_max": lat + lat_delta,
    #         ":lon_min": lon - lon_delta,
    #         ":lon_max": lon + lon_delta,
    #     }
    # )

    # Step 2: Haversine exact filter
    candidates = []  # rows from DynamoDB
    results = []
    for station in candidates:
        dist = haversine_m(lat, lon, float(station["lat"]), float(station["lon"]))
        if dist <= radius_m:
            results.append({**station, "distance_m": round(dist)})

    # Step 3: Sort by distance
    results.sort(key=lambda s: s["distance_m"])

    # Step 4: Compute data age (freshness of oldest record returned)
    now_ts = time.time()
    ages = [now_ts - s.get("last_reported_ts", now_ts) for s in results]
    data_age = max(ages, default=0)

    return {
        "query": {"lat": lat, "lon": lon, "radius_m": radius_m},
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data_age_seconds": round(data_age),
        "stations_found": len(results),
        "stations": results,
    }


# ---------------------------------------------------------------------------
# Tool 2 — get_transit
# ---------------------------------------------------------------------------
MCP_TOOL_GET_TRANSIT = {
    "name": "get_transit",
    "description": (
        "Returns nearby TMB (Barcelona Metro & Bus) transit stops, the routes "
        "serving them, and — when the TMB live API key is available — "
        "real-time next departure times. "
        "Use this tool when the user asks about public transport, bus stops, "
        "metro stations, transit directions, or comparing transit vs cycling. "
        "Always provide lat/lon in WGS-84 decimal degrees. "
        "Default radius_m=400 covers comfortable walking distance to a stop. "
        "The response includes stop names, route numbers, mode (metro/bus), "
        "distance from the query point, and live departure times if available. "
        "Metro stops include the line and direction; bus stops include the "
        "line number and destination headsign. "
        "If the live departure API is unavailable, scheduled times from GTFS "
        "are returned with an 'is_realtime: false' flag."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {
                "type": "number",
                "description": "Latitude of the query point (WGS-84 decimal degrees).",
            },
            "lon": {
                "type": "number",
                "description": "Longitude of the query point (WGS-84 decimal degrees).",
            },
            "radius_m": {
                "type": "integer",
                "description": "Search radius in metres. Default 400. Increase to 800 for areas with sparse stops.",
                "default": 400,
            },
        },
        "required": ["lat", "lon"],
    },
}


def get_transit(lat: float, lon: float, radius_m: int = 400) -> dict[str, Any]:
    """
    Return nearby TMB transit stops and live/scheduled next departures.

    Data sources (confirmed from live API exploration 2026-04-23):
    ─────────────────────────────────────────────────────────────────
    Bus stops:
      • Coordinates / names  — TMB REST API: GET /transit/parades
        Returns 2,721 stops in a single GeoJSON call. Key fields:
        CODI_PARADA, NOM_PARADA, DESC_PARADA, ADRECA, NOM_DISTRICTE,
        NOM_VIA, NOM_PROPERA_VIA, geometry (Point [lon, lat])
        NOTE: /parades does NOT include which bus lines serve the stop.
              That mapping must come from GTFS stop_times / routes join.

      • Live next arrivals  — TMB iBus API:
        GET https://api.tmb.cat/v1/ibus/stops/{CODI_PARADA}
            ?app_id={APP_ID}&app_key={APP_KEY}
        Auth: query-string parameters (NOT request headers).
        Response: { "status": "success", "data": { "ibus": [ ... ] } }
        Each ibus element: { destination, line, routeId, t-in-min, t-in-s,
                             text-ca }
        Returns [] when no buses are expected (night hours, terminus).

    Metro stations:
      • Coordinates / accessibility — TMB REST API: GET /transit/estacions
        Returns 140 unique station nodes. Fields: ID_ESTACIO,
        CODI_GRUP_ESTACIO, NOM_ESTACIO, PICTO (e.g. "L2L5"), DATA.
        geometry Point [lon, lat].

      • Ordered stations per line — GET /transit/linies/metro/{CODI}/estacions
        CODI is CODI_LINIA from /transit/linies/metro (NOT ID_LINIA).
        Rich fields per station: ORDRE_ESTACIO, NOM_TIPUS_ACCESSIBILITAT,
        ID_TIPUS_ESTAT, DATA_INAUGURACIO, COLOR_LINIA, PICTO_GRUP.

      • Real-time metro arrivals — NOT available in any API endpoint.
        Metro frequency must be derived from GTFS frequencies.txt.

    Implementation strategy:
      1. At cold start: load /transit/parades and /transit/estacions into
         memory (or DynamoDB). Pre-join /parades with GTFS stop→routes map.
      2. On tool call: haversine-filter both tables to radius_m.
      3. For each bus stop in results: call /ibus/stops/{CODI_PARADA} live.
      4. For metro stations: return line names from PICTO + accessibility flag.
         Report scheduled frequency from GTFS, not real-time (unavailable).

    Example return value:
    {
        "query": {"lat": 41.4036, "lon": 2.1744, "radius_m": 400},
        "fetched_at": "2026-04-23T19:00:00Z",
        "bus_stops": [
            {
                "codi_parada": 1297,
                "nom_parada": "Mallorca - Marina",
                "address": "C/ de Mallorca, 352",
                "distance_m": 134,
                "lat": 41.4026,
                "lon": 2.1758,
                "lines_serving": ["19", "33", "B20"],   # from GTFS join
                "next_arrivals": [
                    {
                        "line": "19",
                        "destination": "Pl. Catalunya",
                        "t_min": 3,
                        "t_s": 187,
                        "is_realtime": True
                    }
                ]
            }
        ],
        "metro_stations": [
            {
                "nom_estacio": "Sagrada Família",
                "codi_grup_estacio": 6660304,
                "lines": ["L2", "L5"],
                "distance_m": 95,
                "lat": 41.4032,
                "lon": 2.1742,
                "accessible": True,           # NOM_TIPUS_ACCESSIBILITAT
                "is_realtime": False,         # metro real-time not available
                "note": "Metro: no live arrivals available via API"
            }
        ]
    }
    """
    # --- Pseudocode: production implementation ---

    lat_delta = radius_m / 111_320
    lon_delta = radius_m / (111_320 * math.cos(math.radians(lat)))

    # Step 1: Load pre-cached bus stops (loaded from /transit/parades at startup)
    # Each row includes: codi_parada, nom_parada, stop_lat, stop_lon, address,
    #                    lines_serving (pre-joined with GTFS)
    bus_stop_cache: list[dict] = []   # filled from DynamoDB / in-memory cache

    nearby_bus: list[dict] = []
    for stop in bus_stop_cache:
        dist = haversine_m(lat, lon, stop["stop_lat"], stop["stop_lon"])
        if dist <= radius_m:
            nearby_bus.append({**stop, "distance_m": round(dist)})
    nearby_bus.sort(key=lambda s: s["distance_m"])

    # Step 2: Load pre-cached metro stations (from /transit/estacions at startup)
    # Each row includes: nom_estacio, codi_grup_estacio, picto (line codes),
    #                    stop_lat, stop_lon, accessible (from /estacions per line)
    metro_station_cache: list[dict] = []   # filled from DynamoDB / in-memory

    nearby_metro: list[dict] = []
    for station in metro_station_cache:
        dist = haversine_m(lat, lon, station["stop_lat"], station["stop_lon"])
        if dist <= radius_m:
            nearby_metro.append({**station, "distance_m": round(dist)})
    nearby_metro.sort(key=lambda s: s["distance_m"])

    # Step 3: Fetch live bus arrivals from iBus API
    # GET https://api.tmb.cat/v1/ibus/stops/{CODI_PARADA}?app_id=...&app_key=...
    # Auth via query-string params, NOT headers.
    for stop in nearby_bus:
        stop["next_arrivals"] = fetch_ibus_arrivals(stop["codi_parada"])

    # Step 4: Metro — mark real-time unavailable
    for station in nearby_metro:
        station["is_realtime"] = False
        station["note"] = "Metro: no live arrivals available via TMB API"

    return {
        "query": {"lat": lat, "lon": lon, "radius_m": radius_m},
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "bus_stops": nearby_bus,
        "metro_stations": nearby_metro,
    }


def fetch_ibus_arrivals(codi_parada: int) -> list[dict]:
    """
    Fetch live next-bus arrivals for a single bus stop from TMB iBus API.

    Endpoint:
        GET https://api.tmb.cat/v1/ibus/stops/{CODI_PARADA}
            ?app_id={APP_ID}&app_key={APP_KEY}

    Auth: query-string parameters app_id and app_key.
    Header-based auth (X-IBM-Client-Id) returns 403 on this endpoint.

    Response structure confirmed live 2026-04-23:
        {
            "status": "success",
            "data": {
                "ibus": [
                    {
                        "destination": "Pl. Espanya",
                        "line": "150",
                        "routeId": "1501",
                        "t-in-min": 16,
                        "t-in-s": 992,
                        "text-ca": "16 min"
                    }
                ]
            }
        }

    Returns [] when no buses are expected (off-service hours, terminus).

    Returns list of:
        {
            "line": "19",
            "destination": "Pl. Catalunya",
            "t_min": 3,
            "t_s": 187,
            "is_realtime": True
        }
    """
    # Pseudocode
    # TMB_APP_ID  = os.environ["TMB_APP_ID"]
    # TMB_APP_KEY = os.environ["TMB_APP_KEY"]
    # BASE = "https://api.tmb.cat/v1"
    #
    # try:
    #     resp = requests.get(
    #         f"{BASE}/ibus/stops/{codi_parada}",
    #         params={"app_id": TMB_APP_ID, "app_key": TMB_APP_KEY},
    #         timeout=5,
    #     )
    #     resp.raise_for_status()
    #     arrivals = resp.json()["data"]["ibus"]
    #     return [
    #         {
    #             "line":        a["line"],
    #             "destination": a["destination"],
    #             "t_min":       a["t-in-min"],
    #             "t_s":         a["t-in-s"],
    #             "is_realtime": True,
    #         }
    #         for a in arrivals
    #     ]
    # except Exception:
    #     return []   # graceful degradation — caller will omit arrivals field
    return []


# ---------------------------------------------------------------------------
# Tool 3 — get_transit_route  (full implementation in transit_route_tool.py)
# ---------------------------------------------------------------------------
# See transit_route_tool.py for full implementation.
from transit_route_tool import get_transit_route, MCP_TOOL_GET_TRANSIT_ROUTE  # noqa: E402, F401


# ---------------------------------------------------------------------------
# Registration helper (for MCP server setup)
# ---------------------------------------------------------------------------
ALL_TOOL_DEFINITIONS = [
    MCP_TOOL_GET_BICING,
    MCP_TOOL_GET_TRANSIT,
    MCP_TOOL_GET_TRANSIT_ROUTE,
]

if __name__ == "__main__":
    import json
    print("Registered MCP tools:")
    for tool in ALL_TOOL_DEFINITIONS:
        print(f"\n  Tool: {tool['name']}")
        print(f"  Description preview: {tool['description'][:120]}…")
        print(f"  Required params: {tool['input_schema']['properties'].keys()}")
