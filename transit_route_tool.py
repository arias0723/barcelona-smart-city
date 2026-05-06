"""
transit_route_tool.py
=====================
MCP tool wrapper around the Transitous transit routing API for Barcelona.

Transitous is an open, community-maintained transit router that aggregates
GTFS feeds from across Europe.  No API key required.

Endpoint:
    GET https://api.transitous.org/api/v5/plan
        ?fromPlace={lat},{lon}
        &toPlace={lat},{lon}
        &numItineraries={N}
        [&time={HH:MM:SS}]
        [&date={YYYY-MM-DD}]

Key implementation notes:
  - Transitous returns the same itinerary repeated for multiple departure
    slots (e.g. 8 results for a 3-itinerary request).  We deduplicate by
    computing a "fingerprint" from the sequence of (mode, line) tuples.
  - All timestamps in the Transitous response are Unix milliseconds.
  - Distances are in metres, durations in seconds.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

import requests


# ---------------------------------------------------------------------------
# Shared geometry helper  (mirrored from tool_signatures.py)
# ---------------------------------------------------------------------------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Return the great-circle distance in metres between two WGS-84 coordinates.

    Uses the Haversine formula — accurate to < 0.5% for distances < 100 km.

    Example:
        >>> haversine_m(41.4036, 2.1744, 41.4011, 2.1744)
        278.3   # metres
    """
    R = 6_371_000  # Earth radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# MCP tool definition
# ---------------------------------------------------------------------------

MCP_TOOL_GET_TRANSIT_ROUTE = {
    "name": "get_transit_route",
    "description": (
        "Returns up to 3 deduplicated transit journey options between two "
        "geographic coordinates in Barcelona (and the greater metropolitan area) "
        "using the Transitous open transit router. "
        "Each journey is broken into legs: WALK, SUBWAY (metro), BUS, TRAM, or RAIL. "
        "Each transit leg includes the line name (e.g. 'L4', '19'), the headsign "
        "(destination shown on the vehicle), stop names, duration, and whether "
        "the departure time is real-time or scheduled. "
        "Use this tool when the user asks how to get from A to B by public "
        "transport, wants step-by-step transit directions, needs to know total "
        "journey time, or wants to compare multiple route options. "
        "Do NOT use for walking-only or cycling routes. "
        "Provide coordinates as WGS-84 decimal degrees. "
        "Set max_results=1 when only the fastest route is needed. "
        "Use depart_at (ISO 8601, e.g. '2026-04-23T20:30:00') to plan a "
        "future journey; omit for 'leave now'. "
        "Returns an error dict if the routing API is unreachable."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "origin_lat": {
                "type": "number",
                "description": "Latitude of the origin point (WGS-84 decimal degrees).",
            },
            "origin_lon": {
                "type": "number",
                "description": "Longitude of the origin point (WGS-84 decimal degrees).",
            },
            "dest_lat": {
                "type": "number",
                "description": "Latitude of the destination point (WGS-84 decimal degrees).",
            },
            "dest_lon": {
                "type": "number",
                "description": "Longitude of the destination point (WGS-84 decimal degrees).",
            },
            "max_results": {
                "type": "integer",
                "description": (
                    "Maximum number of distinct route options to return. Default 3. "
                    "The API is asked for more and duplicates are removed, so the "
                    "actual count may be fewer if the router finds limited options."
                ),
                "default": 3,
            },
            "depart_at": {
                "type": "string",
                "description": (
                    "Desired departure time as an ISO 8601 datetime string, "
                    "e.g. '2026-04-23T20:30:00'.  Omit or pass null to use the "
                    "current time ('leave now')."
                ),
            },
        },
        "required": ["origin_lat", "origin_lon", "dest_lat", "dest_lon"],
    },
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TRANSITOUS_BASE = "https://api.transitous.org/api/v5/plan"

# Mode labels as returned by Transitous — normalise to lowercase for output
_MODE_NORM = {
    "WALK":   "walk",
    "SUBWAY": "subway",
    "BUS":    "bus",
    "TRAM":   "tram",
    "RAIL":   "rail",
    "FERRY":  "ferry",
}


def _normalise_iso(ts: str | None) -> str | None:
    """
    Normalise a timestamp to a local ISO 8601 string.

    Transitous returns times as ISO strings (e.g. '2026-04-23T18:15:00Z').
    We parse and reformat with local timezone offset for readability.
    Returns None if the input is None or unparseable.
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().isoformat(timespec="seconds")
    except (ValueError, AttributeError):
        return ts  # return as-is if we cannot parse it


def _seconds_to_min(seconds: int | float) -> int:
    """Round seconds to the nearest minute (minimum 1 if > 0)."""
    minutes = round(seconds / 60)
    return max(minutes, 1) if seconds > 0 else 0


def _transform_leg(leg: dict) -> dict:
    """
    Convert a raw Transitous leg dict to the clean output schema.

    Walk legs include: mode, distance_m, duration_min, to.
    Transit legs include: mode, line, headsign, from, to, duration_min,
                          stops, departs_at, is_realtime.
    """
    mode_raw  = leg.get("mode", "WALK")
    mode      = _MODE_NORM.get(mode_raw, mode_raw.lower())
    duration  = _seconds_to_min(leg.get("duration", 0))
    distance  = round(leg.get("distance", 0))
    to_name   = leg.get("to", {}).get("name", "destination")
    from_name = leg.get("from", {}).get("name", "origin")

    # Store encoded polyline for map rendering (prefixed with _ = internal)
    geometry = leg.get("legGeometry", {}).get("points")

    if mode == "walk":
        out = {
            "mode":        "walk",
            "distance_m":  distance,
            "duration_min": duration,
            "to":          to_name,
        }
        if geometry:
            out["_polyline"] = geometry
        return out

    # Transit leg
    intermediate = leg.get("intermediateStops") or []
    stops_count  = len(intermediate)

    # Transitous v5 uses ISO string fields: startTime / scheduledStartTime
    depart_ts = (
        leg.get("scheduledStartTime")
        or leg.get("startTime")
        or leg.get("scheduledDeparture")
        or leg.get("expectedDeparture")
    )

    out = {
        "mode":         mode,
        "line":         leg.get("routeShortName") or leg.get("route", {}).get("shortName", "?"),
        "headsign":     leg.get("headsign", ""),
        "from":         from_name,
        "to":           to_name,
        "duration_min": duration,
        "stops":        stops_count,
        "departs_at":   _normalise_iso(depart_ts),
        "is_realtime":  bool(leg.get("realTime", False)),
    }
    if geometry:
        out["_polyline"] = geometry
    return out


def _itinerary_fingerprint(itinerary: dict) -> tuple:
    """
    Compute a hashable fingerprint for an itinerary based on its transit legs.

    Two itineraries are considered duplicates if they use the same sequence of
    (mode, line) pairs — i.e. they are the same journey at a different time slot.
    Walk legs are included as a mode-only token to anchor the sequence.
    """
    tokens = []
    for leg in itinerary.get("legs", []):
        mode = leg.get("mode", "WALK")
        if mode == "WALK":
            tokens.append(("WALK",))
        else:
            line = leg.get("routeShortName") or leg.get("route", {}).get("shortName", "?")
            tokens.append((mode, line))
    return tuple(tokens)


def _deduplicate(itineraries: list[dict]) -> list[dict]:
    """
    Return a deduplicated list of itineraries, keeping the first occurrence of
    each unique fingerprint (earliest departure for that route pattern).
    """
    seen: set[tuple] = set()
    unique: list[dict] = []
    for it in itineraries:
        fp = _itinerary_fingerprint(it)
        if fp not in seen:
            seen.add(fp)
            unique.append(it)
    return unique


def _transform_itinerary(it: dict) -> dict:
    """Convert a raw Transitous itinerary to the clean output schema."""
    duration_sec = it.get("duration", 0)
    total_min    = _seconds_to_min(duration_sec)
    transfers    = it.get("transfers", 0)

    legs = [_transform_leg(leg) for leg in it.get("legs", [])]

    return {
        "total_min": total_min,
        "transfers": transfers,
        "legs":      legs,
    }


# ---------------------------------------------------------------------------
# Public API function
# ---------------------------------------------------------------------------

def get_transit_route(
    origin_lat:  float,
    origin_lon:  float,
    dest_lat:    float,
    dest_lon:    float,
    max_results: int = 3,
    depart_at:   str | None = None,
) -> dict[str, Any]:
    """
    Fetch transit route options from Transitous and return a clean structured dict.

    Parameters
    ----------
    origin_lat, origin_lon : float
        WGS-84 coordinates of the journey origin.
    dest_lat, dest_lon : float
        WGS-84 coordinates of the journey destination.
    max_results : int
        Maximum number of deduplicated route options to return (default 3).
    depart_at : str, optional
        ISO 8601 departure time string.  If omitted, departs now.

    Returns
    -------
    dict
        On success:
            {
              "origin": {"lat": ..., "lon": ...},
              "dest":   {"lat": ..., "lon": ...},
              "fetched_at": "ISO timestamp",
              "routes_found": N,
              "routes": [ ... ]
            }
        On failure:
            {"error": "human-readable message", "routes": []}
    """
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")

    # Edge case: origin == destination (or extremely close)
    straight_line_m = haversine_m(origin_lat, origin_lon, dest_lat, dest_lon)
    if straight_line_m < 10:
        return {
            "origin":      {"lat": origin_lat, "lon": origin_lon},
            "dest":        {"lat": dest_lat,   "lon": dest_lon},
            "fetched_at":  fetched_at,
            "routes_found": 0,
            "routes":      [],
            "note":        "Origin and destination are the same point.",
        }

    # Build query parameters
    # Ask for extra itineraries so that after deduplication we have enough
    request_count = max(max_results * 3, 9)

    params: dict[str, Any] = {
        "fromPlace":       f"{origin_lat},{origin_lon}",
        "toPlace":         f"{dest_lat},{dest_lon}",
        "numItineraries":  request_count,
    }

    if depart_at:
        try:
            dt = datetime.fromisoformat(depart_at)
            params["time"] = dt.strftime("%H:%M:%S")
            params["date"] = dt.strftime("%Y-%m-%d")
        except ValueError:
            return {
                "error":  f"Invalid depart_at format: '{depart_at}'. Use ISO 8601, e.g. '2026-04-23T20:30:00'.",
                "routes": [],
            }

    # Call Transitous API
    try:
        response = requests.get(_TRANSITOUS_BASE, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return {
            "error":  "Transitous API timed out after 10 seconds.",
            "routes": [],
        }
    except requests.exceptions.ConnectionError as exc:
        return {
            "error":  f"Could not connect to Transitous API: {exc}",
            "routes": [],
        }
    except requests.exceptions.HTTPError as exc:
        return {
            "error":  f"Transitous API returned HTTP {response.status_code}: {exc}",
            "routes": [],
        }
    except ValueError as exc:
        return {
            "error":  f"Could not parse Transitous response as JSON: {exc}",
            "routes": [],
        }

    # Extract itineraries list.
    # Transitous v5 returns them at the top level; some older versions used plan.itineraries.
    raw_itineraries: list[dict] = (
        data.get("itineraries")
        or data.get("plan", {}).get("itineraries")
        or []
    )

    raw_count = len(raw_itineraries)

    # Deduplicate
    unique_itineraries = _deduplicate(raw_itineraries)

    # Sort by total duration (ascending) and cap at max_results
    unique_itineraries.sort(key=lambda it: it.get("duration", float("inf")))
    unique_itineraries = unique_itineraries[:max_results]

    # Transform to clean output
    routes = [_transform_itinerary(it) for it in unique_itineraries]

    return {
        "origin":       {"lat": origin_lat, "lon": origin_lon},
        "dest":         {"lat": dest_lat,   "lon": dest_lon},
        "fetched_at":   fetched_at,
        "raw_api_count": raw_count,
        "routes_found": len(routes),
        "routes":       routes,
    }


# ---------------------------------------------------------------------------
# Human-readable printer (used by __main__ and test script)
# ---------------------------------------------------------------------------

def _print_route_result(result: dict, label: str = "") -> None:
    """Print a get_transit_route result in a readable format."""
    sep = "=" * 60
    if label:
        print(f"\n{sep}")
        print(f"  {label}")
    print(sep)

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return

    origin = result["origin"]
    dest   = result["dest"]
    print(f"  From : ({origin['lat']}, {origin['lon']})")
    print(f"  To   : ({dest['lat']},   {dest['lon']})")
    print(f"  At   : {result['fetched_at']}")

    raw   = result.get("raw_api_count", "?")
    found = result["routes_found"]
    print(f"  API returned {raw} itineraries → {found} unique after deduplication")

    note = result.get("note")
    if note:
        print(f"  Note : {note}")

    for i, route in enumerate(result["routes"], 1):
        total = route["total_min"]
        xfers = route["transfers"]
        xfer_str = f"{xfers} transfer{'s' if xfers != 1 else ''}"
        print(f"\n  Option {i}: {total} min, {xfer_str}")
        for leg in route["legs"]:
            mode = leg["mode"].upper()
            if mode == "WALK":
                dist = leg["distance_m"]
                dur  = leg["duration_min"]
                to   = leg["to"]
                print(f"    WALK  {dist}m ({dur} min) → {to}")
            else:
                line     = leg.get("line", "?")
                headsign = leg.get("headsign", "")
                frm      = leg.get("from", "?")
                to       = leg.get("to", "?")
                dur      = leg["duration_min"]
                stops    = leg.get("stops", 0)
                rt       = "realtime" if leg.get("is_realtime") else "scheduled"
                dep      = leg.get("departs_at") or "?"
                stops_str = f" | {stops} stops" if stops > 0 else ""
                print(
                    f"    {mode:<6} {line} → {headsign} | "
                    f"{frm} → {to} | {dur} min{stops_str} | dep {dep} [{rt}]"
                )

    if found == 0 and not result.get("note"):
        print("  (No routes found — origin/destination may be outside coverage area.)")

    print(sep)


# ---------------------------------------------------------------------------
# Live test  —  python3 transit_route_tool.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nTransitous MCP Tool — Live Test")
    print("Sagrada Familia → Barceloneta, Barcelona")
    print("(Confirmed working endpoint: api.transitous.org)\n")

    result = get_transit_route(
        origin_lat=41.4036,
        origin_lon=2.1744,
        dest_lat=41.3807,
        dest_lon=2.1897,
        max_results=3,
    )

    _print_route_result(result, label="Sagrada Familia → Barceloneta")

    print("\nDone.")
