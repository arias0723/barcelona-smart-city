# TMB API — Live Exploration Findings

**Explored:** 2026-04-23  
**Credentials:** app_id `74309501`, app_key `c7234d6f7249b444f6158f41a0ad4fce`  
**Base URL:** `https://api.tmb.cat/v1/`  
**Script:** `tmb_api_exploration.py` (run output captured below)

---

## 1. Endpoints — What Works on the Free Tier

| Endpoint | HTTP | Result |
|---|---|---|
| `GET /transit/linies/metro` | 200 | 11 metro lines, full static metadata |
| `GET /transit/linies/bus` | 200 | 113 bus lines, full static metadata |
| `GET /transit/parades` | 200 | 2,721 bus stops, full dataset in one call |
| `GET /transit/estacions` | 200 | 140 metro station nodes (unique physical stations) |
| `GET /transit/linies/metro/{CODI}/estacions` | 200 | Ordered stations per metro line with rich metadata |
| `GET /ibus/stops/{CODI_PARADA}` | 200 | **Live** next-bus arrivals (real-time) |
| `GET /planner/trip` | 403 | Forbidden — requires higher-tier subscription |
| `GET /transit/linies/metro/{ID}/parades` | 404 | Wrong URL pattern — endpoint does not exist |
| `GET /transit/linies/bus/{ID}/parades` | 200 | Returns empty array — data not populated |

**Key gotcha:** The per-line metro stations endpoint URL uses `CODI_LINIA` (the
numeric route code like `1`, `2`, `94`) **not** `ID_LINIA` (the internal DB
primary key like `4`, `6`, `10`). These differ for L9N, L9S, L10N, L10S.

---

## 2. Full Field Inventory

### `/transit/linies/metro` and `/transit/linies/bus` — Line objects

Both share the same GeoJSON FeatureCollection envelope. Each Feature's
`properties` object contains:

| Field | Type | Notes |
|---|---|---|
| `ID_LINIA` | int | Internal primary key (used in DB joins) |
| `CODI_LINIA` | int | Route code used in per-line URL paths |
| `NOM_LINIA` | str | Display name: "L1", "H4", "V11", etc. |
| `DESC_LINIA` | str | Full description: "Hospital de Bellvitge - Fondo" |
| `ORIGEN_LINIA` | str | Origin terminus name |
| `DESTI_LINIA` | str | Destination terminus name |
| `NUM_PAQUETS` | int | Number of service variants |
| `ID_OPERADOR` | int | Operator ID |
| `CODI_OPERADOR` | str | Operator code (bus only) |
| `NOM_OPERADOR` | str | Operator name |
| `ID_TIPUS_TRANSPORT` | int | Transport type ID (bus only) |
| `NOM_TIPUS_TRANSPORT` | str | "BUS" (bus only) |
| `ID_FAMILIA` | int | Family ID (bus only) |
| `CODI_FAMILIA` | str | Family code (bus only) |
| `NOM_FAMILIA` | str | "Metro", "Bus", "Metro-Funicular" |
| `ORDRE_FAMILIA` | int | Sort order within family |
| `ORDRE_LINIA` | int | Sort order within network |
| `CODI_TIPUS_CALENDARI` | str | Calendar type code |
| `NOM_TIPUS_CALENDARI` | str | Calendar description |
| `DATA` | str | Data update date (ISO "2026-04-22Z") |
| `COLOR_LINIA` | str | Hex colour without `#` (e.g. "CE1126") |
| `COLOR_AUX_LINIA` | str | Auxiliary colour |
| `COLOR_TEXT_LINIA` | str | Text-on-background colour |

Geometry is `MultiLineString` (the full route polyline on the map).

### `/transit/parades` — Bus stop objects

Each Feature's `properties`:

| Field | Type | Notes |
|---|---|---|
| `ID_PARADA` | int | Internal primary key |
| `CODI_PARADA` | int | Stop code — used in iBus real-time URL |
| `NOM_PARADA` | str | Display name: "Sagrada Família", "Mallorca - Marina" |
| `DESC_PARADA` | str | Cross-street description |
| `CODI_INTERC` | int | Interchange code (0 = no interchange) |
| `NOM_INTERC` | str | Interchange name (null if none) |
| `NOM_TIPUS_PARADA` | str | Physical shelter type code |
| `NOM_TIPUS_SIMPLE_PARADA` | str | Human-readable shelter type: "Pal", "Marquesina", "Monolit" |
| `DESC_TIPUS_PARADA` | str | Full shelter type description |
| `TIPIFICACIO_PARADA` | str | Classification code |
| `ADRECA` | str | Street address |
| `ID_POBLACIO` | int | Municipality ID |
| `NOM_POBLACIO` | str | Municipality name |
| `ID_DISTRICTE` | int | District ID |
| `NOM_DISTRICTE` | str | District name |
| `DATA` | str | Data update date |
| `NOM_VIA` | str | Street name |
| `NOM_PROPERA_VIA` | str | Nearest cross-street |
| `PUNTS_PARADA` | int | Stop points count |

Geometry is `Point` [lon, lat].  
**No field indicates which bus lines serve this stop** — that join requires GTFS.

### `/transit/estacions` — Metro station nodes

| Field | Type | Notes |
|---|---|---|
| `ID_ESTACIO` | int | Internal station ID |
| `CODI_GRUP_ESTACIO` | int | Station group code (for interchange stations) |
| `NOM_ESTACIO` | str | Station name |
| `PICTO` | str | Line pictogram — "L1", "L2L3L4" for interchanges |
| `DATA` | str | Data update date |

Geometry is `Point`. Only 5 fields. Use `/transit/linies/metro/{CODI}/estacions`
for the rich per-line version.

### `/transit/linies/metro/{CODI}/estacions` — Ordered metro stations per line

| Field | Type | Notes |
|---|---|---|
| `ID_ESTACIO_LINIA` | int | Line-specific station entry ID |
| `CODI_ESTACIO_LINIA` | int | Station code on this line |
| `ID_GRUP_ESTACIO` | int | Station group ID (interchange linking) |
| `CODI_GRUP_ESTACIO` | int | Station group code |
| `ID_ESTACIO` | int | Physical station ID |
| `CODI_ESTACIO` | int | Physical station code |
| `NOM_ESTACIO` | str | Station name |
| `ORDRE_ESTACIO` | int | Position on line (1 = first terminus) |
| `ID_LINIA` | int | Line ID |
| `CODI_LINIA` | int | Line code |
| `NOM_LINIA` | str | Line name |
| `ORDRE_LINIA` | int | Line sort order |
| `ID_TIPUS_SERVEI` | int | Service type ID |
| `DESC_SERVEI` | str | Service description "La Pau - Trinitat Nova" |
| `ORIGEN_SERVEI` | str | Service origin |
| `DESTI_SERVEI` | str | Service destination |
| `ID_TIPUS_ACCESSIBILITAT` | int | 1=Accessible, 3=Not accessible |
| `NOM_TIPUS_ACCESSIBILITAT` | str | "Accessible" or "No accessible" |
| `ID_TIPUS_ESTAT` | int | Status (1 = operational) |
| `NOM_TIPUS_ESTAT` | str | "Operatiu" |
| `DATA_INAUGURACIO` | str | Opening date (ISO) |
| `DATA` | str | Data update date |
| `COLOR_LINIA` | str | Hex colour |
| `PICTO` | str | Line pictogram |
| `PICTO_GRUP` | str | Combined pictogram for interchange stations |

### `/ibus/stops/{CODI_PARADA}` — Real-time bus arrivals

Response envelope: `{ "status": "success", "data": { "ibus": [...] } }`

Each arrival object:

| Field | Type | Notes |
|---|---|---|
| `destination` | str | Route terminus: "Pl. Espanya" |
| `line` | str | Line code: "150", "H4", "V11" |
| `routeId` | str | Internal route variant ID |
| `t-in-min` | int | Minutes until arrival |
| `t-in-s` | int | Seconds until arrival (more precise) |
| `text-ca` | str | Human-readable in Catalan: "16 min" |

Returns empty array when no buses are expected (night service, terminus stop).

---

## 3. Network Statistics (live, 2026-04-23)

| Metric | Count |
|---|---|
| Metro lines | 11 (L1–L5, L9N, L9S, L10N, L10S, L11, FM) |
| Bus lines | 113 |
| Bus stops (`/parades`) | 2,721 |
| Metro station nodes (`/estacions`) | 140 unique physical stations |
| Metro station-line entries (with duplicates for interchanges) | 171 |

Metro line station counts:

| Line | Stations | Termini |
|---|---|---|
| L1 | 30 | Hospital de Bellvitge — Fondo |
| L2 | 18 | Paral·lel — Badalona Pompeu Fabra |
| L3 | 26 | Zona Universitària — Trinitat Nova |
| L4 | 22 | La Pau — Trinitat Nova |
| L5 | 27 | Cornellà Centre — Vall d'Hebron |
| L9N | 9 | La Sagrera — Can Zam |
| L9S | 15 | Aeroport T1 — Zona Universitària |
| L10N | 6 | La Sagrera — Gorg |
| L10S | 11 | ZAL/Riu Vell — Collblanc |
| L11 | 5 | Trinitat Nova — Can Cuiàs |
| FM | 2 | Paral·lel — Parc de Montjuïc |

GTFS (for comparison): 3,453 stop entries (includes parent stations and
platform-level entrances), 117 routes, 55,924 trips, 1,287,552 stop-time records.

---

## 4. Real-Time Data — What Is and Is Not Available

### Available on free tier

**`GET /ibus/stops/{CODI_PARADA}`** — Live next-bus arrivals  
- Returns all buses approaching a specific bus stop  
- Fields: line code, destination, minutes to arrival, seconds to arrival  
- No authentication tier difference observed  
- Tested live: stop 2326 returned line 150 "Pl. Espanya" in 16 min  

### Not available on free tier

| Feature | Reason |
|---|---|
| Trip planner (`/planner/trip`) | 403 Forbidden |
| Metro real-time arrivals | No endpoint exists in the API |
| Bus occupancy / crowding | No endpoint exists in the API |
| Service disruptions / alerts | No endpoint exists in the API |
| Vehicle GPS positions | No endpoint exists in the API |

Metro next-train information is not exposed through any TMB API endpoint at any
tier visible from the documentation. Metro frequency data is only available via
GTFS `stop_times.txt` (scheduled, not live).

---

## 5. API vs GTFS — Comparison

| Capability | TMB REST API | GTFS |
|---|---|---|
| Bus stop locations | Yes — `/transit/parades` | Yes — `stops.txt` |
| Metro station locations | Yes — `/transit/estacions` | Yes — `stops.txt` |
| Line colours / pictograms | **Yes — per line in API** | Yes — `routes.txt` |
| Ordered station sequence per line | **Yes — `ORDRE_ESTACIO` field** | Derivable from `stop_times.txt` but requires trip reconstruction |
| Accessibility per station | **Yes — `NOM_TIPUS_ACCESSIBILITAT`** | `wheelchair_boarding` in `stops.txt` |
| Opening date per station | **Yes — `DATA_INAUGURACIO`** | No |
| Which lines serve each stop | **No — API has no stop→lines mapping** | **Yes — via `stop_times` join** |
| Scheduled departure times | No | **Yes — `stop_times.txt` (1.28M rows)** |
| Service calendar | No | **Yes — `calendar.txt`, `calendar_dates.txt`** |
| Trip frequency / headway | No | **Yes — `frequencies.txt`** |
| Station entrance / pathway geometry | No | **Yes — `pathways.txt`** |
| Real-time bus arrivals | **Yes — `/ibus/stops/{id}`** | No |
| Offline / no-network use | No | **Yes — download once, query locally** |
| Bulk geospatial queries | Via GeoJSON geometry | Requires local processing |

**Summary:** The API excels at real-time bus arrivals and provides richer
per-station metadata (accessibility, colour, opening date, order). GTFS is
essential for schedule data, knowing which lines serve a stop, and offline use.
The two sources are complementary, not substitutes.

---

## 6. Pagination

`/transit/parades` returns all 2,721 stops in a single response (no pagination
needed). The GeoJSON envelope includes `totalFeatures`, `numberMatched`, and
`numberReturned` fields — all equal, confirming the full dataset arrives at once.
Response size is approximately 1.8 MB.

No rate-limit headers were observed in any response. The API documentation does
not publicly specify rate limits for the free tier.

---

## 7. Recommendation for `get_transit()` MCP Tool

**Use a hybrid approach: TMB REST API for real-time bus arrivals + local GTFS
for stop-to-line mapping and schedule context.**

Rationale:

1. The API's `/transit/parades` gives bus stop coordinates. The iBus endpoint
   gives live arrivals. Together they answer "next bus at nearest stop" without
   GTFS.

2. The API does **not** tell you which lines serve a given stop. To answer
   "what transit options do I have here?", you need the GTFS stop→route join.
   Pre-compute this at server startup: `stop_id → [route names]`.

3. Metro: use `/transit/estacions` (with coordinates) for proximity search.
   There is no real-time metro data — report scheduled frequency from GTFS or
   state "Metro: next train typically every N min (see timetable)".

4. For the MCP tool's return shape, the most useful format for an LLM is:

```json
{
  "bus_stops": [
    {
      "codi_parada": 1297,
      "name": "Mallorca - Marina",
      "address": "Carrer de Mallorca, 352",
      "distance_m": 134,
      "lines": ["19", "33", "B20"],
      "next_arrivals": [
        {"line": "19", "destination": "Pl. Catalunya", "t_min": 3, "t_s": 187},
        {"line": "33", "destination": "Zona Universitaria", "t_min": 8, "t_s": 491}
      ]
    }
  ],
  "metro_stations": [
    {
      "nom_estacio": "Sagrada Família",
      "lines": ["L2", "L5"],
      "distance_m": 95,
      "accessible": true
    }
  ],
  "data_timestamp": "2026-04-23T17:08:03Z"
}
```

The `lines` field on bus stops must come from GTFS (API has no stop→lines join).
The `next_arrivals` field comes from `/ibus/stops/{codi}`.
Metro accessibility comes from `NOM_TIPUS_ACCESSIBILITAT` in the API.
