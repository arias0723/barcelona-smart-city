# Barcelona Mobility Data — Exploration Context
# For: Jakub (project lead on mobility vertical)
# Goal: explore Bicing and TMB data sources, understand what's available,
#       think about how to make it maximally useful for an AI assistant / end user

---

## Project context

We are building an MCP server that exposes Barcelona's open city data as tools
any AI assistant can call. The mobility vertical covers:

- **Bicing** (bike share) — `get_bicing(lat, lon)` tool
- **TMB** (bus + metro) — `get_transit(area)` tool 

Each tool will eventually:
1. Be called by an AI assistant (Claude, etc.) to answer citizen questions
2. Return structured JSON the LLM can reason over
3. Feed into use cases like health-aware routing, daily briefings, trip planning

The question to keep in mind throughout exploration:
**"What data, in what format, would make this tool maximally useful for an LLM
trying to answer a citizen's question?"**

---

## Data Source 1: Bicing (BSM GBFS)

### What it is
Bicing is Barcelona's municipal bike-share system operated by BSM.
It exposes data in GBFS (General Bikeshare Feed Specification) format —
an open standard used by bike-share systems worldwide.

### Endpoints (no API key needed)

Base: `https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/`

Key feeds:
- `gbfs.json` — index of all available feeds
- `station_information.json` — static: station locations, names, capacity
- `station_status.json` — live: bikes available, docks available, per station
- `system_information.json` — system metadata

Example full URLs:
```
https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/gbfs.json
https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/station_information.json
https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/station_status.json
```

Updates every ~5 minutes.

### What to explore tomorrow

1. Fetch `station_information.json` — how many stations? what fields exist?
   lat/lon, name, capacity, what else?

2. Fetch `station_status.json` — join with station_information on station_id.
   Key fields: `num_bikes_available`, `num_docks_available`, `is_installed`,
   `is_renting`, `last_reported`. Are there e-bike vs mechanical bike splits?

3. Think about: what would the `get_bicing(lat, lon)` MCP tool return?
   Probably: nearest N stations within radius, with bikes available, docks
   available, distance from requested point, last updated timestamp.

4. Think about edge cases: what if a station is installed but not renting?
   What if last_reported is 30 minutes old? The tool should communicate
   data freshness clearly.

5. Visualise station distribution on a map — are there coverage gaps?
   Which neighbourhoods are underserved?

### Useful questions to answer from the data
- How many stations total? How many active right now?
- Average availability across the city at this moment?
- Which station has most bikes? Which is empty?
- What is the geographic spread — do stations cluster anywhere?

---

## Data Source 2: TMB (Transports Metropolitans de Barcelona)

### What it is
TMB operates Barcelona's bus and metro network. They have an open API
(requires free registration and API key).

### API registration
Register at: https://developer.tmb.cat/
Free tier gives access to static schedule data + some real-time feeds.

### Key endpoints

Base: `https://api.tmb.cat/v1/`

Static data (no real-time key needed for these):
- `GET /transit/linies/bus` — all bus lines
- `GET /transit/linies/metro` — all metro lines
- `GET /transit/parades` — all stops (bus + metro) with lat/lon
- `GET /transit/linies/metro/{id}/parades` — stops for a specific metro line

Real-time (requires key):
- `GET /planner/trip` — trip planner (origin → destination)
- Some real-time arrival data depending on tier

GTFS feed (static schedules, standard format):
- Available at: https://developer.tmb.cat/data (look for GTFS download)
- GTFS is the standard transit data format — trips, stops, stop_times,
  routes, calendar. Very well documented.

### What to explore tomorrow

1. Register for API key at developer.tmb.cat if not done already.

2. Fetch `/transit/parades` — how many stops? What fields? lat/lon, name,
   which lines serve it?

3. Fetch metro lines and their stops — can you map the metro network?

4. Download the GTFS feed — explore the structure. Key files:
   - `stops.txt` — all stops with coordinates
   - `routes.txt` — all routes
   - `stop_times.txt` — when each route serves each stop
   - `trips.txt` — trips per route

5. Think about: what would `get_transit(lat, lon)` return?
   Probably: nearest stops within walking distance, which lines serve them,
   next departures if real-time available, walking time from requested point.

6. Real-time availability: assess honestly. Does the free API tier give
   useful real-time data or just static schedules? This affects what the
   MCP tool can promise.

### Useful questions to answer from the data
- How many bus lines? Metro lines? Total stops?
- What is the coverage like — which areas have dense transit vs sparse?
- What real-time data is actually available on the free tier?
- How frequently do buses run on major routes vs minor ones?

---

## Thinking about the MCP tools

After exploring the data, draft (in plain text/pseudocode) what you think
the tool signatures and return formats should look like. Example:

```
get_bicing(lat: float, lon: float, radius_m: int = 500) -> {
  stations: [
    {
      station_id: str,
      name: str,
      distance_m: int,
      bikes_available: int,      # mechanical
      ebikes_available: int,     # electric if available
      docks_available: int,
      is_renting: bool,
      last_updated: str          # ISO timestamp — always include this
    }
  ],
  data_age_seconds: int          # how old is the data overall
}

get_transit(lat: float, lon: float, radius_m: int = 500) -> {
  stops: [
    {
      stop_id: str,
      name: str,
      distance_m: int,
      lines: [str],              # which lines serve this stop
      next_departures: [...]     # if real-time available, else null
    }
  ],
  data_age_seconds: int
}
```

The LLM needs to be able to answer: "Are there bikes nearby?" and
"What transport options do I have from here?" from these responses.

---

## What to produce tomorrow

Not code yet — understanding first. By end of tomorrow you should have:

1. **A short written summary per data source** (can be bullet points):
   - What data is available
   - Update frequency
   - Quality / reliability observations
   - What the MCP tool should return
   - Any surprises or limitations found

2. **At least one working API call per source** — just a script or notebook
   that fetches the data and prints/plots something. Proves the connection
   works and you understand the format.

3. **Your draft tool signatures** — what parameters, what return format.
   These will be reviewed with the team before implementation.

---

## Technical setup for tomorrow

```python
# Quick test — paste this in a notebook or script to verify Bicing works
import requests
import json

# Station information (static)
info = requests.get(
    "https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/station_information.json"
).json()
print(f"Total stations: {len(info['data']['stations'])}")
print(json.dumps(info['data']['stations'][0], indent=2))  # first station

# Station status (live)
status = requests.get(
    "https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/station_status.json"
).json()
print(f"Status records: {len(status['data']['stations'])}")
print(json.dumps(status['data']['stations'][0], indent=2))

# Join them
info_by_id = {s['station_id']: s for s in info['data']['stations']}
for s in status['data']['stations'][:5]:
    station = info_by_id.get(s['station_id'], {})
    print(f"{station.get('name','?')}: {s['num_bikes_available']} bikes, "
          f"{s['num_docks_available']} docks")
```

For TMB: register first, then try:
```python
import requests

API_KEY = "your_key_here"
BASE = "https://api.tmb.cat/v1"

# All metro lines
resp = requests.get(
    f"{BASE}/transit/linies/metro",
    params={"app_id": API_KEY, "app_key": API_KEY}
)
print(resp.json())
```

---

## Context on how this fits the bigger picture

The MCP server will call your tool functions when a user asks something
mobility-related. Examples of queries your tools need to handle:

- "Are there Bicing bikes near Passeig de Gràcia right now?"
- "What public transport can I take from Gràcia to Barceloneta?"
- "Is there a metro station near the air quality monitoring station in Eixample?"
- "Give me a route that combines Bicing to the metro then metro to the beach"

That last one requires combining your tool with the air quality tool and
a routing MCP. The better your tool's return format, the easier the LLM
can combine it with others.

One concrete thing to think about: **proximity search**. Every tool takes
a lat/lon and returns nearby results sorted by distance. Make sure you
understand the haversine formula or find a library that does it, because
you'll need it to filter stations/stops by distance from a requested point.

```python
from math import radians, sin, cos, sqrt, atan2

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in metres
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))
```

Good luck tomorrow. The goal is understanding, not shipping.
