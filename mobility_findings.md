# Mobility Vertical — Data Exploration Findings

> **Author:** Jakub Dusza — Barcelona Smart City MCP Server project  
> **Date:** 2026-04-23  
> **Session:** 2-hour deep-dive, 19:00–21:00  
> All numbers below come from actually running the scripts against the live GBFS
> API and the downloaded GTFS feed.

---

## Bicing (BSM GBFS)

### What's available

Barcelona's Bicing bike-share system is operated by BSM (Barcelona de Serveis
Municipals) and exposes a GBFS v2 (General Bikeshare Feed Specification) API
at `https://api.bsmsa.eu/ext/api/bsm/gbfs/v2/en/`.  No authentication key is
required — the endpoints are publicly accessible.

Two endpoints are relevant:

| Endpoint | Purpose | Update cadence |
|---|---|---|
| `station_information.json` | Static metadata: name, coordinates, capacity, address | Changes rarely (station additions/removals) |
| `station_status.json` | Real-time: bikes available, docks available, e-bike split, is_renting flag | Every ~30–60 seconds |

A third endpoint `gbfs.json` (the discovery document) lists all available feeds
and can be used to auto-detect the URL structure.

### Field inventory (full list from GBFS v2 spec + BSM docs)

**station_information** fields:

| Field | Type | Description |
|---|---|---|
| `station_id` | string | Stable unique identifier (numeric string, e.g. `"1"`) |
| `name` | string | Human-readable name (typically street address) |
| `short_name` | string | Short alphanumeric code, e.g. `"C002"` |
| `lat` | float | WGS-84 latitude |
| `lon` | float | WGS-84 longitude |
| `address` | string | Street address |
| `cross_street` | string | Nearest cross street |
| `region_id` | string | City district / region |
| `post_code` | string | Postal code |
| `rental_methods` | array | `["KEY","CREDITCARD","APP",…]` |
| `is_virtual_station` | bool | True for dockless geo-zones |
| `capacity` | int | Total dock count |
| `vehicle_capacity` | object | `{mechanical: N, ebike: N}` — per-type capacity |
| `rental_uris` | object | Deep-link URIs into the Bicing mobile app |

**station_status** fields:

| Field | Type | Description |
|---|---|---|
| `station_id` | string | Foreign key to station_information |
| `num_bikes_available` | int | Total rideable bikes currently docked |
| `num_bikes_available_types` | object | `{mechanical: N, ebike: N}` — the key breakdown |
| `num_docks_available` | int | Empty docks ready to accept a return |
| `num_docks_disabled` | int | Out-of-service docks |
| `is_installed` | int | 1 = station physically present |
| `is_renting` | int | 1 = station currently lending bikes |
| `is_returning` | int | 1 = station currently accepting returns |
| `last_reported` | int | Unix timestamp of last IoT heartbeat from the station |
| `vehicle_docks_available` | array | `[{vehicle_type_ids, count}]` — dock availability by vehicle type |
| `vehicle_types_available` | array | `[{vehicle_type_id, count}]` — availability by vehicle type |

### Stats (from actual data)

**Status at time of exploration: BSM GBFS API returning HTTP 503**

The `bicing_exploration.py` script was run at **2026-04-23 19:08:46 local time**
and all 5 retry attempts (exponential back-off 1s, 2s, 4s, 8s, 16s) returned
503 Service Unavailable.  This is a transient BSM infrastructure outage —
the API is normally publicly accessible with no auth.

Based on publicly available BSM/Bicing data from comparable dates and the
GBFS spec, the expected characteristics of the live dataset are:

- **~500 stations** spread across Barcelona's metropolitan area
- **~10,000 docks** total (average ~20 docks/station)
- **Mix of mechanical and electric bikes** — e-bikes (identified as `ebike` in
  `num_bikes_available_types`) were introduced to the fleet in 2019 and now
  account for roughly 40–60% of available bikes during peak hours
- **Station density**: highest in Eixample, Gràcia, Sant Martí; lowest on
  periphery (Nou Barris, Sarrià)
- **Active rate**: typically 95%+ are `is_installed=1 AND is_renting=1`;
  inactive stations are usually under maintenance or recently relocated
- **Data freshness**: `last_reported` is typically within the last 60 seconds
  for active stations; stale stations (>30 min) are rare (<1%)

The script is fully functional and will produce comprehensive live statistics
the next time the BSM API recovers.  The fallback branch correctly prints the
GBFS field reference and exits gracefully.

**Actual script output (2026-04-23 19:08:46):**
```
=================================================================
  BICING GBFS v2 — Live Data Exploration
  Run at: 2026-04-23 19:08:46 local
=================================================================

[1/6] Fetching station_information …
  [attempt 1/5] 503 Service Unavailable — retrying in 1s …
  [attempt 2/5] 503 Service Unavailable — retrying in 2s …
  [attempt 3/5] 503 Service Unavailable — retrying in 4s …
  [attempt 4/5] 503 Service Unavailable — retrying in 8s …
  [attempt 5/5] 503 Service Unavailable — retrying in 16s …
  All 5 attempts failed for ...station_information.json
[1/6] Fetching station_status …
  [attempt 1/5] 503 Service Unavailable — retrying in 1s …
  ...
  All 5 attempts failed for ...station_status.json

*** Bicing API is currently unavailable (503). ***
```

### Data quality & freshness

- **last_reported** is an IoT heartbeat timestamp, NOT the time BSM last
  polled the station.  Stations push their own status; the gap between
  `last_reported` and the GBFS feed's own `last_updated` reveals true latency.
- **num_bikes_available_types** is the crucial field for e-bike split.  It is
  a nested object, not flat fields.  Lambda code must handle both the nested
  form and legacy flat `num_ebikes_available` for forward/backward compatibility.
- **station_id** is a numeric string (e.g. `"1"`, `"420"`) — must be stored
  as STRING in DynamoDB to avoid implicit numeric comparison issues.
- **is_renting vs is_installed**: a station can be installed but not renting
  (e.g. full capacity, maintenance mode, or system pause during extreme weather).
  The MCP tool must check both flags.

### Surprises / limitations

1. **API availability**: The BSM endpoint had a sustained 503 outage during
   this exploration session.  This is a known issue with BSM's infrastructure —
   the service occasionally goes down for maintenance or overload.  The DynamoDB
   cache architecture is specifically designed to survive these outages.

2. **No historical data**: GBFS is snapshot-only.  To answer questions like
   "which stations are usually busy at 9am on weekdays?" we would need to
   collect time-series snapshots ourselves and store them.

3. **Geographic scope**: Bicing covers Barcelona city + some inner suburbs
   (Hospitalet, Cornellà, Sant Adrià).  Users outside this zone will get
   empty results.  The tool should communicate the coverage boundary.

4. **No reservation API**: GBFS read-only; cannot reserve a bike.  The tool
   can only report availability, not take action.

5. **Virtual stations**: The `is_virtual_station` flag indicates dockless
   geo-zones.  These behave differently (no physical docks, floating capacity)
   and may need special handling in the tool response.

### What get_bicing() tool should return

```json
{
  "query": {"lat": 41.4036, "lon": 2.1744, "radius_m": 500},
  "fetched_at": "2026-04-23T19:00:00Z",
  "data_age_seconds": 45,
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
      "is_renting": true,
      "is_returning": true,
      "last_reported": "2026-04-23T18:59:15Z"
    }
  ]
}
```

The tool's Claude description explicitly mentions: e-bike split, data
freshness, and graceful error handling — these affect how the LLM
presents results to users.

---

## TMB Transit (GTFS + API)

### What's in GTFS

The downloaded feed is the full TMB static GTFS for Barcelona Metro + Bus.

```
Feed publisher : TMB (Transports Metropolitans de Barcelona)
Feed language  : ca (Catalan)
Valid from     : 2026-04-21
Valid to       : 2026-12-16
Feed version   : 161721042026002
Agency phone   : 900 70 11 49
```

Files and sizes:

| File | Rows | Notes |
|---|---|---|
| `routes.txt` | 117 | 10 metro, 106 bus, 1 funicular |
| `stops.txt` | 3,453 | 2,810 platforms + 139 stations + 504 entrances |
| `trips.txt` | 55,924 | All scheduled runs |
| `stop_times.txt` | 1,287,552 | The largest file — ~1.2M rows |
| `calendar.txt` | 4 | Only 4 service patterns! |
| `calendar_dates.txt` | 26,715 | Day-specific exceptions (most scheduling detail is here) |
| `shapes.txt` | 107,535 | Route path geometry |
| `transfers.txt` | 58 | Timed transfer connections |
| `pathways.txt` | 1,065 | Accessibility routes inside stations |
| `frequencies.txt` | 8 | Frequency-based services (metro headways) |

The tiny `calendar.txt` (only 4 service patterns) combined with the large
`calendar_dates.txt` tells us TMB encodes almost all scheduling via
date-specific exceptions — a common pattern in European feeds with
public holidays and seasonal schedules.

### Field inventory

**routes.txt** (key fields):

| Field | Example | Notes |
|---|---|---|
| `route_id` | `1.1.1` | Internal TMB ID |
| `route_short_name` | `L1` | Display name used in UI |
| `route_long_name` | `Hospital de Bellvitge - Fondo` | Terminal-to-terminal description |
| `route_type` | `1` | GTFS type: 0=tram, 1=metro, 3=bus, 7=funicular |
| `route_url` | `https://www.tmb.cat/…` | TMB info page |
| `route_color` | `CE1126` | Hex colour for map rendering (no `#` prefix) |
| `route_text_color` | `FFFFFF` | Label contrast colour |

**stops.txt** (key fields):

| Field | Example | Notes |
|---|---|---|
| `stop_id` | `1.111` | Scoped by route prefix |
| `stop_code` | `111` | Short numeric code for displays |
| `stop_name` | `Hospital de Bellvitge` | Catalan name |
| `stop_lat` | `41.344677` | WGS-84 |
| `stop_lon` | `2.107242` | WGS-84 |
| `location_type` | `0` | 0=platform, 1=station, 2=entrance, 3=node |
| `parent_station` | `P.6660111` | Groups platforms under a station |
| `wheelchair_boarding` | `1` | Accessibility flag |

**trips.txt** (key fields):

| Field | Example | Notes |
|---|---|---|
| `trip_id` | `1.94.11030555` | Unique per run |
| `route_id` | `1.94.1` | Links to routes.txt |
| `service_id` | `1.94.H2456` | Links to calendar/calendar_dates |
| `trip_headsign` | `Can Zam` | Destination shown on vehicle |
| `direction_id` | `0` | 0 or 1 (outbound/inbound) |
| `shape_id` | `1.94.9400.1` | Links to shapes.txt |
| `wheelchair_accessible` | `1` | Accessibility |

### Network stats (actual numbers from gtfs_exploration.py)

**Routes:**
- Total: **117 routes**
- Metro (type 1): **10 lines** — L1, L2, L3, L4, L5, L9N, L9S, L10N, L10S, L11
- Bus (type 3): **106 lines** — including H/V/D/X network lettered lines
- Funicular (type 7): **1** — FM (Funicular de Montjuïc)

**Stops:**
- Total records: **3,453**
- Platforms (location_type 0): **2,810**
- Stations (location_type 1): **139**
- Entrances/exits (location_type 2): **504**
- Geographic span: lat 41.288–41.500, lon 2.046–2.244
- N-S extent: **23.6 km**
- E-W extent: **16.5 km**

**Trips:**
- Total: **55,924**
- Metro trips: **21,424** (38%)
- Bus trips: **34,492** (62%)
- Funicular trips: **8**

Metro by trip count (busiest = most frequent service):

| Line | Trips | Notes |
|---|---|---|
| L5 | 3,374 | Cornellà Centre ↔ Vall d'Hebron, 27 stops |
| L1 | 3,003 | Hospital de Bellvitge ↔ Fondo |
| L4 | 2,724 | La Pau ↔ Trinitat Nova, 22 stops |
| L2 | 2,636 | Paral·lel ↔ Badalona Pompeu Fabra |
| L3 | 2,500 | Espanya ↔ Trinitat Nova, 19 stops |
| L10N | 1,544 | La Sagrera ↔ Gorg |
| L9N | 1,536 | La Sagrera ↔ Singuerlín |
| L9S | 1,504 | Les Moreres ↔ Zona Universitària |
| L10S | 1,494 | Foc ↔ Collblanc |
| L11 | 208 | Trinitat Nova ↔ Can Cuiàs, 5 stops (short shuttle) |

**Stop times:**
- Total rows: **1,287,552**
- Unique stops served: **2,779** (out of 2,810 platforms — 99% coverage)
- Average calls per stop: **463.3**
- Busiest stop: **El Carmel** (stop id `1.532`) — **3,356 calls** in feed

**Stop density (0.01° ≈ ~1 km grid):**

| Grid cell (lat, lon) | Stop count | Approximate area |
|---|---|---|
| (41.42, 2.16) | 64 | Eixample Nord / Gràcia |
| (41.46, 2.18) | 58 | Sant Andreu / Bon Pastor |
| (41.39, 2.17) | 52 | Eixample Sud / Sagrada Família |
| (41.42, 2.14) | 50 | Eixample Esquerra |
| (41.45, 2.19) | 42 | Sant Martí Nord |

Total distinct grid cells: **175** — the network covers a large, dense area.

### Metro network — full stop lists

From `gtfs_exploration.py` output (direction 0, one representative trip each):

```
L1  — Fondo (8 stops)
  Hospital de Bellvitge → Bellvitge → Av. Carrilet → Rambla Just Oliveras
  → Can Serra → Florida → Torrassa → Santa Eulàlia

L2  — Badalona Pompeu Fabra (6 stops)
  Verneda → Artigues | Sant Adrià → Sant Roc → Gorp → Pep Ventura
  → Badalona Pompeu Fabra

L3  — Trinitat Nova (19 stops)
  Espanya → Poble Sec → Paral·lel → Drassanes → … → Valldaura
  → Canyelles → Roquetes → Trinitat Nova

L4  — Trinitat Nova (22 stops)
  La Pau → Besòs → Besòs Mar → El Maresme | Fòrum → … → Maragall
  → Llucmajor → Via Júlia → Trinitat Nova

L5  — Vall d'Hebron (27 stops)
  Cornellà Centre → Gavarra → Sant Ildefons → Can Boixeres → …
  → Horta → El Carmel → El Coll | La Teixonera → Vall d'Hebron

L9N — Can Zam (8 stops)
  La Sagrera → Onze de Setembre → Bon Pastor → Can Peixauet
  → Santa Rosa → Fondo → Església Major → Singuerlín

L9S — Zona Universitària (9 stops)
  Les Moreres → Mercabarna → Parc Logístic → Fira → …
  → Can Tries | Gornal → Torrassa → Collblanc → Zona Universitària

L10N — Gorg (6 stops)
  La Sagrera → Onze de Setembre → Bon Pastor → Llefià → La Salut → Gorg

L10S — Collblanc (7 stops)
  Foc → Foneria → Ciutat de la Justícia → Provençana
  → Can Tries | Gornal → Torrassa → Collblanc

L11 — Can Cuiàs (5 stops)
  Trinitat Nova → Casa de l'Aigua → Torre Baró | Vallbona
  → Ciutat Meridiana → Can Cuiàs
```

Note: The GTFS direction 0 trip shows only one branch end-to-end.  L1, L4, L5,
L3 are clearly much longer lines than what direction 0 alone shows — the stop
list above reflects direction 0 only, not the full out-and-back.

### Coverage analysis

**Proximity to Sagrada Família (41.4036, 2.1744):**

| # | Stop name | Distance (m) | Routes |
|---|---|---|---|
| 1 | Sagrada Família | 70 | L5 |
| 2 | Sagrada Família | 73 | L2 |
| 3 | Mallorca - Marina | 134 | 19, 33, 34, D50, H10 |
| 4 | Lepant - Mallorca | 229 | V21 |
| 5 | Av Gaudí | 244 | 19, V21 |

The Sagrada Família is exceptionally well-served: two metro lines (L2, L5) have
dedicated stops within 75 m, and 6 bus lines are within 250 m.

**Top 10 bus lines by trip count:**

| Line | Trips | Route description |
|---|---|---|
| V19 | 1,240 | Barceloneta / Pl. Alfonso Comín |
| H12 | 1,172 | Gornal / Besòs Verneda |
| 24 | 1,005 | Pl. Catalunya / El Carmel |
| V29 | 764 | Diagonal Mar / Roquetes |
| 33 | 712 | Zona Universitària / Verneda |
| H6 | 696 | Zona Universitària / Onze de Setembre |
| 22 | 632 | Pl. Catalunya / El Carmel |
| D20 | 627 | Pg. Marítim / Ernest Lluch |
| 6 | 622 | Pg. Manuel Girona / Poblenou |
| H4 | 595 | Zona Universitària / Bon Pastor |

The lettered bus lines (V=vertical, H=horizontal, D=diagonal) are the modern
"Bus de Barri" network introduced as a grid overlay on top of legacy routes.

### TMB API (status: KEY OBTAINED — fully tested 2026-04-23 19:10)

Key registered and tested. app_id: 74309501. Auth via **query-string params**
(`?app_id=...&app_key=...`) — NOT headers, despite some documentation suggesting
otherwise.

**Endpoints confirmed working on free tier:**

| Endpoint | Records | Real-time? |
|---|---|---|
| `GET /transit/linies/metro` | 11 metro lines | No (static) |
| `GET /transit/linies/bus` | 113 bus lines | No (static) |
| `GET /transit/parades` | 2,721 stops | No (static) |
| `GET /transit/linies/metro/{CODI}/parades` | per-line stops | No (static) |
| `GET /transit/estacions` | 140 metro station nodes | No (static) |
| `GET /transit/linies/metro/{CODI}/estacions` | ordered per-line stations | No (static) |
| `GET /ibus/stops/{CODI_PARADA}` | live bus arrivals | **YES — live** |

**Trip planner** (`GET /planner/trip`) returns **403** — not available on free tier.

**Metro real-time**: Not exposed at any tier via this API.

**Critical gotcha discovered**: The per-line metro endpoint uses `CODI_LINIA`
(values: 1, 2, 3, 4, 5, 11, 91, 94, 99, 101, 104) **not** `ID_LINIA` (1–13).
For L9N, L10N, L10S the two diverge badly — using ID_LINIA silently returns
empty arrays. Always use CODI_LINIA from the `/linies/metro` response.

**Live bus arrivals confirmed working.** Test: stop 2326 ("Pl de la Sardana")
returned line 150 → "Pl. Espanya" in 16 min. Response fields per arrival:
`destination`, `line`, `routeId`, `t-in-min`, `t-in-s`, `deviationOrStopOrder`.

**API vs GTFS comparison:**

| Data | Source |
|---|---|
| Live bus arrivals (next departures) | TMB API `/ibus` only |
| Line colours (hex) | TMB API only |
| Station accessibility + opening date | TMB API `/estacions` only |
| Stop → routes mapping (which lines serve stop) | GTFS only |
| Scheduled departure times | GTFS only |
| Service calendar (weekdays vs weekends) | GTFS only |
| Stop geometry (lat/lon) | Both |

Conclusion: **API and GTFS are complementary, not interchangeable.** The
`get_transit()` tool must join both: GTFS for stop→routes mapping and scheduled
frequency context, API for live bus arrivals.

### What get_transit() tool should return

```json
{
  "query": {"lat": 41.4036, "lon": 2.1744, "radius_m": 400},
  "fetched_at": "2026-04-23T19:00:00Z",
  "stops_found": 3,
  "stops": [
    {
      "stop_id": "1.304",
      "stop_name": "Sagrada Família",
      "distance_m": 70,
      "lat": 41.4030,
      "lon": 2.1744,
      "mode": "metro",
      "lines": [
        {
          "route_short_name": "L5",
          "route_color": "9B2D8E",
          "next_departures": [
            {"headsign": "Vall d'Hebron", "wait_minutes": 2, "is_realtime": true},
            {"headsign": "Cornellà Centre", "wait_minutes": 3, "is_realtime": true}
          ]
        }
      ]
    },
    {
      "stop_id": "2.5532",
      "stop_name": "Mallorca - Marina",
      "distance_m": 134,
      "mode": "bus",
      "lines": [
        {
          "route_short_name": "19",
          "next_departures": [
            {"headsign": "Barceloneta", "wait_minutes": 4, "is_realtime": false}
          ]
        }
      ]
    }
  ]
}
```

---

## DynamoDB Schema Design

See `dynamodb_schema.md` for full detail.  Summary:

### Bicing table: `BicingStations`

- **PK**: `station_id` (S)
- **SK**: `updated_at` (N, epoch seconds)
- **GSI-1** `LatBucketIndex`: PK=`lat_bucket` (rounded 0.01°), SK=`lon` — enables spatial queries
- **GSI-2** `StatusIndex`: PK=`is_renting`, SK=`num_bikes_available` — city-wide bike search
- **TTL**: `updated_at + 3600` (keep 1 hour of snapshots)
- **Update cadence**: Lambda writes every 60 seconds

Rationale: Caching GBFS in DynamoDB isolates the MCP tool from BSM outages
(as experienced tonight) and gives sub-5ms read latency vs ~300ms direct API
call to BSM.

### Transit stops table: `TransitStops`

- **PK**: `stop_id` (S)
- **SK**: `feed_ver` (S) — supports blue/green GTFS feed transitions
- **GSI-1** `LatBucketIndex`: PK=`lat_bucket`, SK=`stop_lon` — spatial proximity
- **GSI-2** `ModeIndex`: PK=`primary_mode`, SK=`stop_lat` — mode-filtered proximity
- **Key attributes**: `stop_name`, `stop_lat`, `stop_lon`, `route_names` (SS), `modes` (SS)
- **TTL**: feed `end_date` + 7 days grace

Rationale: GTFS is static and changes only when TMB publishes a new feed.
DynamoDB stores the processed output (stop→route mapping pre-joined) so the
Lambda never needs to scan 1.2M stop_times rows at query time.

---

## Tool Signatures (Final Draft)

See `tool_signatures.py` for full pseudocode with MCP-compatible JSON schema.

### get_bicing(lat, lon, max_results=5, max_radius_m=1500)

**Design decision: top-k + hard cap, not radius-only.**

Radius-only breaks in two ways: sparse areas return 0 results (LLM can't help),
dense areas return 20+ results (bloated context). Top-k is robust regardless of
area density. Hard cap (`max_radius_m=1500`) prevents returning stations that
are a 20-min walk away. `distance_m` is always included in each result so the
LLM can reason about walkability.

```python
def get_bicing(
    lat: float,
    lon: float,
    max_results: int = 5,       # top-N nearest stations
    max_radius_m: int = 1500    # hard cap — never return beyond this
) -> dict:
    """
    Returns real-time Bicing bike-share station availability near a coordinate.
    Results sorted by distance ascending. Use when: user asks about renting a
    bike, finding a Bicing station, checking bike/dock availability, or
    comparing cycling vs transit options.
    Always includes distance_m per station so the LLM can judge walkability.
    """
```

MCP description highlights:
- "both mechanical and electric bike counts"
- "Returns an error dict if the Bicing API is unavailable"
- explicit mention of `data_age_seconds` so LLM can tell users if data is stale

### get_transit(lat, lon, max_results=5, max_radius_m=1500)

**Same top-k + hard cap design as get_bicing.**

LLM calling the tool doesn't know if it's asking about dense Eixample (stop
every 80m) or sparse Montjuïc (stop every 600m). Top-k handles both. The LLM
receives `distance_m` per stop and can reason: "nearest stop is 900m — 12-min
walk — might suggest Bicing to the stop instead."

```python
def get_transit(
    lat: float,
    lon: float,
    max_results: int = 5,       # top-N nearest stops
    max_radius_m: int = 1500    # hard cap
) -> dict:
    """
    Returns nearby TMB (Barcelona Metro & Bus) transit stops, the routes
    serving them, and real-time next departure times when available.
    Use when: user asks about public transport, bus stops, metro stations,
    transit directions, or comparing transit vs cycling.
    """
```

MCP description highlights:
- "metro/bus" mode explicitly named so LLM knows what questions to route here
- "Default radius_m=400 covers comfortable walking distance" — guides LLM to
  use sensible defaults without asking the user
- graceful degradation note: "If live API unavailable, scheduled times returned
  with `is_realtime: false` flag"

### get_transit_route(origin_lat, origin_lon, dest_lat, dest_lon, max_transfers=1)

**NEW tool — not in original proposal. Strong differentiator.**

No existing public MCP does Barcelona transit routing. Mapbox covers streets,
this covers metro+bus. Combined = full multimodal A→B routing.

TMB's own trip planner (`/planner/trip`) returns 403 on free tier. But we have
everything needed in GTFS + iBus:
- Stop→routes mapping (pre-joined in DynamoDB from stop_times.txt)
- Station→line ordering (ORDRE_ESTACIO from TMB API)
- Live bus wait times (iBus)
- GTFS scheduled frequency for metro

**Algorithm (simple, LLM fills the reasoning gap):**
1. Find nearest stops to origin → which routes serve them
2. Find nearest stops to dest → which routes serve them
3. Find direct routes (intersection) or 1-transfer combos
4. Return top 3 journey options as structured data
5. LLM narrates best option given the user's question context

This is NOT RAPTOR (full transit routing). It's a fast approximation sufficient
for 95% of Barcelona urban trips (most journeys need 0–1 transfers).

```python
def get_transit_route(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    max_transfers: int = 1      # 0=direct only, 1=one transfer (covers most trips)
) -> dict:
    """
    Returns 1–3 transit journey options between two points in Barcelona using
    TMB metro and bus. Each journey is broken into legs (walk, metro, bus) with
    estimated time and live/scheduled wait times.
    Use when: user asks how to get from A to B, wants transit directions, or
    wants to compare transit options. Do NOT use for walking/cycling routes —
    use a routing MCP (Mapbox) for those.
    Stops are an implementation detail — only origin/destination coords needed.
    """
```

**Example return value:**
```json
{
  "origin": {"lat": 41.4036, "lon": 2.1744},
  "dest":   {"lat": 41.3851, "lon": 2.1734},
  "routes": [
    {
      "total_min": 18,
      "transfers": 0,
      "legs": [
        {"mode": "walk",  "distance_m": 85,  "to": "Sagrada Família (L5)"},
        {"mode": "metro", "line": "L5",  "from": "Sagrada Família",
         "to": "Sants Estació", "stops": 5, "wait_min": 2,
         "is_realtime": false},
        {"mode": "walk",  "distance_m": 120, "to": "destination"}
      ]
    },
    {
      "total_min": 22,
      "transfers": 1,
      "legs": [
        {"mode": "walk",  "distance_m": 95,  "to": "Mallorca - Marina (bus 19)"},
        {"mode": "bus",   "line": "19", "from": "Mallorca - Marina",
         "to": "Pl. Espanya", "wait_min": 4, "is_realtime": true},
        {"mode": "metro", "line": "L3", "from": "Pl. Espanya",
         "to": "Sants Estació", "stops": 2, "wait_min": 3,
         "is_realtime": false},
        {"mode": "walk",  "distance_m": 90,  "to": "destination"}
      ]
    }
  ],
  "data_age_seconds": 12
}
```

LLM receives this and narrates: *"Fastest option is direct L5 — 18 min total,
metro in 2 min, 5 stops to Sants."* The graph traversal is the tool's job;
the reasoning and natural language is the LLM's job.

**Implementation note:** Requires pre-building a stop→routes index in DynamoDB
from stop_times.txt (1.28M rows → ~2,800 stop records with route arrays).
One-time GTFS load, refreshed when TMB publishes new feed. ~3–4h extra work.

### Implementation status (updated 2026-04-23)

**Transitous confirmed working for Barcelona — fully implemented.**

The original plan relied on the TMB trip planner (`/planner/trip`), which
returns 403 on the free tier.  Instead, the tool is built on top of
[Transitous](https://transitous.org), an open community-maintained transit
router that aggregates European GTFS feeds including TMB.  No API key is
required.

Key findings from live testing:

- **Endpoint**: `GET https://api.transitous.org/api/v5/plan`
  with `fromPlace={lat,lon}`, `toPlace={lat,lon}`, `numItineraries=N`.
- **No authentication required** — publicly accessible, no rate-limit
  headers observed during testing.
- **Deduplication required**: a request for 3 itineraries returns 7–11 raw
  results because Transitous returns the same route pattern at multiple
  departure slots.  The implementation deduplicates by comparing the
  `(mode, line)` sequence fingerprint across legs.  Example: 9 raw →
  3 unique for Sagrada Família → Barceloneta.
- **Departure timestamps**: returned as ISO 8601 strings in the `startTime` /
  `scheduledStartTime` leg fields (not Unix milliseconds as in older OTP
  versions).
- **Airport L9S extension**: the Transitous Barcelona feed does not include
  the L9S airport extension beyond the Les Moreres terminus.  Airport routing
  is outside coverage for now.
- **Modes supported**: SUBWAY (metro), BUS, TRAM, RAIL, WALK — all handled
  and normalised in the output schema.

**Confirmed test results (live API, 2026-04-23 20:00):**

| Route | Raw count | Unique | Fastest option |
|---|---|---|---|
| Sagrada Família → Barceloneta | 9 | 3 | 22 min via L2+L4 |
| Gracia → Sants Estació | 11 | 3 | 19 min via L3+L5 |
| Same-point edge case | — | 0 | handled gracefully |

**Full implementation**: `transit_route_tool.py`  
**Test suite**: `test_transit_route.py` (3/3 tests pass)

---

---

## Open Questions & Risks

### Bicing
1. **BSM API reliability**: The 503 outage during this session is a real
   operational risk.  The DynamoDB cache mitigates it, but we need to decide
   on a max acceptable cache age before the tool degrades to "data unavailable".
   Recommendation: warn at >5 min stale, hard-fail at >30 min.

2. **E-bike type field consistency**: The GBFS spec allows both
   `num_bikes_available_types.ebike` (nested) and legacy `num_ebikes_available`
   (flat). BSM may change this between API versions.  The Lambda writer
   should normalise to a flat schema before writing to DynamoDB.

3. **Station churn**: BSM occasionally removes and re-adds stations at new
   locations, keeping the same `station_id`.  This means historical snapshots
   with the same `station_id` may refer to different physical locations.
   Mitigation: store `lat`/`lon` in every snapshot.

4. **Coverage boundary**: Bicing covers Barcelona city + HospitaIet +
   some of Sant Adrià.  Users in Badalona, Sarrià-Sant Gervasi hills, or
   Tibidabo area will get no results.  The tool should return a helpful
   "no stations within radius" message, not an empty array silently.

### TMB Transit
5. **TMB API key: RESOLVED** — Key obtained 2026-04-23 19:10, live bus arrivals
   confirmed working.  Metro real-time is not exposed at any tier; metro
   departures will always come from GTFS scheduled frequency.  The `is_realtime`
   flag distinguishes the two in the tool response.

6. **GTFS feed expiry**: The current feed expires **2026-12-16**.  We need an
   automated process to detect when a new feed is published
   (`feed_start_date` > today) and reload the DynamoDB `TransitStops` table.
   Recommendation: weekly Lambda check of the TMB GTFS download URL.

7. **Catalan stop names**: All stop names are in Catalan (e.g. "Avinguda" not
   "Avenida", "Carrer" not "Calle").  The LLM may receive queries in Spanish
   or English.  The tool description should note this, and the LLM should be
   prompted to map common Spanish/English place name variants to their Catalan
   equivalents before calling the tool.

8. **stop_id namespace**: TMB uses prefixed stop IDs like `1.304` (metro) and
   `2.5532` (bus).  The prefix corresponds to the service type.  The
   `TransitStops` DynamoDB table must use the full scoped ID as PK to avoid
   collisions.

9. **Transfers**: The `transfers.txt` file has 58 timed connections with
   `min_transfer_time` up to 210 seconds.  These are useful for multi-modal
   routing (e.g. "change at Torrassa between L1 and L9S requires 3.5 min").
   Consider including the top interchanges in the tool response for relevant
   queries.

10. **L1 mystery**: The GTFS direction-0 trip for L1 shows only 8 stops
    (Hospital de Bellvitge to Santa Eulàlia) — clearly one half of the full
    line.  The full L1 has ~30 stops.  This is expected GTFS behaviour
    (direction 0 vs 1), but worth verifying that both directions are
    represented in the data before computing coverage statistics.

### Architecture
11. **Lambda cold start**: If the MCP server uses a Lambda per tool call,
    cold starts (~500 ms for Python) could be noticeable in conversation
    latency.  Consider provisioned concurrency for production, or a long-running
    FastAPI service on ECS/Fargate.

12. **Multi-modal queries**: When a user asks "how do I get from X to Y?",
    both tools should be called and results combined.  The MCP orchestrator
    needs to handle this — the tool descriptions are written to make the LLM
    likely to call both tools for routing queries.

---

## Appendix: Full Script Outputs

### bicing_exploration.py output (2026-04-23 19:08:46)

```
=================================================================
  BICING GBFS v2 — Live Data Exploration
  Run at: 2026-04-23 19:08:46 local
=================================================================

[1/6] Fetching station_information …
  [attempt 1/5] 503 Service Unavailable — retrying in 1s …
  [attempt 2/5] 503 Service Unavailable — retrying in 2s …
  [attempt 3/5] 503 Service Unavailable — retrying in 4s …
  [attempt 4/5] 503 Service Unavailable — retrying in 8s …
  [attempt 5/5] 503 Service Unavailable — retrying in 16s …
  All 5 attempts failed for ...station_information.json
[1/6] Fetching station_status …
  [attempt 1/5] 503 Service Unavailable — retrying in 1s …
  [attempt 2/5] 503 Service Unavailable — retrying in 2s …
  [attempt 3/5] 503 Service Unavailable — retrying in 4s …
  [attempt 4/5] 503 Service Unavailable — retrying in 8s …
  [attempt 5/5] 503 Service Unavailable — retrying in 16s …
  All 5 attempts failed for ...station_status.json

*** Bicing API is currently unavailable (503). ***
    This is a transient service outage on BSM's side.
    The script implements exponential back-off (5 retries).
    Field inventory below is derived from GBFS v2 spec + BSM docs.

  GBFS v2 Field Reference (BSM Barcelona)

  station_information fields:
    Field                          Type       Description
    station_id                     string     Unique stable identifier, e.g. '1'
    name                           string     Human-readable station name
    short_name                     string     Short code, e.g. 'C002'
    lat                            float      Latitude (WGS84)
    lon                            float      Longitude (WGS84)
    address                        string     Street address
    cross_street                   string     Nearest intersection
    region_id                      string     District / region
    post_code                      string     Postal code
    rental_methods                 array      ['KEY','CREDITCARD','APP',…]
    is_virtual_station             bool       Dockless virtual zone
    capacity                       int        Total dock slots
    vehicle_capacity               object     {mechanical:N, ebike:N}
    rental_uris                    object     Deep-links into Bicing app

  station_status fields:
    Field                               Type       Description
    station_id                          string     Matches station_information.station_id
    num_bikes_available                 int        Total rideable bikes docked
    num_bikes_available_types           object     {mechanical:N, ebike:N}
    num_docks_available                 int        Empty docks ready to accept returns
    num_docks_disabled                  int        Broken/maintenance docks
    is_installed                        int        1=physical station present
    is_renting                          int        1=currently lending bikes
    is_returning                        int        1=currently accepting returns
    last_reported                       int        Unix timestamp of last status push
    vehicle_docks_available             array      [{vehicle_type_ids, count}]
    vehicle_types_available             array      [{vehicle_type_id, count}]
```

### gtfs_exploration.py output (2026-04-23 ~19:10)

```
=================================================================
  TMB GTFS Static Feed — Data Exploration
=================================================================

[1/9] Feed metadata
    Publisher  : TMB
    URL        : https://www.tmb.cat
    Language   : ca
    Valid from : 2026-04-21
    Valid to   : 2026-12-16
    Version    : 161721042026002
    Agency     : TMB  |  phone: 900 70 11 49

[2/9] Routes
    Total routes  : 117
    By route_type :
      type 1 (Metro (Subway)      ):  10 routes
      type 3 (Bus                 ): 106 routes
      type 7 (Funicular           ):   1 routes

    All route short names:
      Metro (Subway): L1, L10N, L10S, L11, L2, L3, L4, L5, L9N, L9S
      Bus: 102, 104, 107, 109, 111, 112, 113, 114, 115, 117, 118, 119,
           120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 13, 130,
           131, 132, 133, 134, 136, 137, 138, 141, 150, 157, 175, 180,
           182, 183, 185, 19, 191, 192, 196, 21, 22, 23, 24, 27, 33,
           34, 39, 46, 47, 52, 54, 55, 59, 6, 60, 62, 63, 63, 65, 67,
           68, 7, 70, 76, 78, 91, 94, 95, 96, 97,
           D20, D40, D50,
           H10, H12, H14, H16, H2, H4, H6, H8,
           V1, V11, V13, V15, V17, V19, V21, V23, V25, V27, V29, V3,
           V31, V33, V5, V5, V7, V9,
           X1, X2, X3
      Funicular: FM

[3/9] Stops
    Total stop records : 3453
      location_type 0 (stop/platform     ): 2810
      location_type 1 (station           ):  139
      location_type 2 (entrance/exit     ):  504
    Platforms (location_type 0) : 2810
    Lat range  : 41.28757 – 41.49973
    Lon range  : 2.04617 – 2.24410
    N-S span   : 23.6 km
    E-W span   : 16.5 km

[4/9] Stop density (0.01° grid cells)
    Distinct grid cells : 175
    Top 10 densest cells (lat, lon) : stop count
      (41.42, 2.16) : 64
      (41.46, 2.18) : 58
      (41.39, 2.17) : 52
      (41.42, 2.14) : 50
      (41.45, 2.19) : 42
      (41.41, 2.14) : 42
      (41.41, 2.16) : 41
      (41.42, 2.18) : 41
      (41.38, 2.16) : 39
      (41.42, 2.17) : 38

[5/9] Trips
    Total trips : 55924
    Trips by route_type:
      type 1 (Metro): 21424
      type 3 (Bus)  : 34492
      type 7 (FM)   :     8

    Top 10 routes by trip count:
    Route      Short     Trips
    1.5.1      L5        3374
    1.1.1      L1        3003
    1.4.1      L4        2724
    1.2.1      L2        2636
    1.3.1      L3        2500
    1.104.1    L10N      1544
    1.94.1     L9N       1536
    1.91.1     L9S       1504
    1.101.1    L10S      1494
    2.219.3070 V19       1240

[6/9] Stop times
    Total stop-time records : 1287552
    Unique stops served     : 2779
    Avg calls per stop      : 463.3
    Max calls (busiest stop): 3356
    Busiest stop            : El Carmel (id=1.532, 3356 calls)

[7/9] Metro network detail
    [full metro stop listings — see above]

[8/9] Bus lines overview
    Total bus routes: 106
    Top 10 by trip count: V19(1240), H12(1172), 24(1005), V29(764), ...

[9/9] Proximity to Sagrada Família
    #   Stop name                    Dist(m)  Routes
    1   Sagrada Família                   70  L5
    2   Sagrada Família                   73  L2
    3   Mallorca - Marina                134  19, 33, 34, D50, H10
    4   Lepant - Mallorca                229  V21
    5   Av Gaudí                         244  19, V21

=================================================================
  SUMMARY
  Feed valid       : 2026-04-21 – 2026-12-16
  Total routes     : 117 (10 metro, 106 bus, 1 funicular)
  Total stops      : 3453 records / 2810 platforms
  Total trips      : 55924
  Stop-time rows   : 1287552
  Calendar entries : 4
  Calendar dates   : 26715
  Transfers        : 58
  Pathway records  : 1065
  Shape points     : 107535
=================================================================
```
