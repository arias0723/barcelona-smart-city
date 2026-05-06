# DynamoDB Schema Design — Barcelona Mobility Vertical

## Design philosophy

DynamoDB is chosen for its sub-millisecond read latency (critical for an MCP
tool that sits in a live AI conversation) and for its ability to scale
horizontally without tuning.  Both mobility datasets have very different update
cadences: Bicing station status refreshes every ~30–60 s; GTFS is a static
snapshot valid for weeks.  The schema reflects this asymmetry.

All monetary costs are minimised by using **on-demand capacity** for both
tables (traffic is bursty around commute peaks, nearly zero overnight).

---

## Table 1: `BicingStations`

### Purpose
Cache the merged output of GBFS `station_information` + `station_status`.
A background Lambda (triggered by EventBridge every 60 s) writes fresh rows.
The MCP tool reads from this table instead of hitting the BSM API directly,
which (a) avoids per-call latency from BSM, and (b) keeps working during BSM
outages by serving slightly-stale data with an explicit `data_age_seconds`.

### Keys

| Attribute     | Type | Role            | Notes                                 |
|---------------|------|-----------------|---------------------------------------|
| `station_id`  | S    | Partition key   | Stable string ID from GBFS, e.g. "1"  |
| `updated_at`  | N    | Sort key        | Unix epoch seconds (float)            |

Using `updated_at` as sort key lets us:
- Keep a short history (last N snapshots) for trend analysis
- Always query the freshest record with `ScanIndexForward=False, Limit=1`

### All Attributes

| Attribute                    | Type | Source               | Example value                    |
|------------------------------|------|----------------------|----------------------------------|
| `station_id`                 | S    | GBFS info            | `"420"`                          |
| `updated_at`                 | N    | Lambda write time    | `1745430000`                     |
| `name`                       | S    | GBFS info            | `"C/ de la Sagrada Família, 10"` |
| `short_name`                 | S    | GBFS info            | `"C420"`                         |
| `lat`                        | N    | GBFS info            | `41.4031`                        |
| `lon`                        | N    | GBFS info            | `2.1747`                         |
| `capacity`                   | N    | GBFS info            | `20`                             |
| `address`                    | S    | GBFS info            | `"Carrer de la Sagrada Família"` |
| `region_id`                  | S    | GBFS info            | `"Eixample"`                     |
| `num_bikes_available`        | N    | GBFS status          | `7`                              |
| `num_ebikes_available`       | N    | GBFS status (types)  | `3`                              |
| `num_mechanical_available`   | N    | GBFS status (types)  | `4`                              |
| `num_docks_available`        | N    | GBFS status          | `12`                             |
| `num_docks_disabled`         | N    | GBFS status          | `1`                              |
| `is_installed`               | N    | GBFS status          | `1`                              |
| `is_renting`                 | N    | GBFS status          | `1`                              |
| `is_returning`               | N    | GBFS status          | `1`                              |
| `last_reported`              | N    | GBFS status          | `1745429955` (BSM device clock)  |
| `ttl`                        | N    | Lambda computed      | `updated_at + 3600` (1 h)        |

### Global Secondary Indexes (GSIs)

**GSI-1: `LatIndex`**
- Partition key: `lat_bucket` (S) — `str(round(lat, 2))` e.g. `"41.40"`
- Sort key: `lon` (N)
- Projects: ALL
- Purpose: bounding-box pre-filter before haversine in Lambda.
  Query `lat_bucket` IN [list of 1–4 nearby buckets], filter on `lon` range.
  A 0.01° bucket is ~1 km; a 500 m radius needs at most 4 bucket values.

**GSI-2: `StatusIndex`**
- Partition key: `is_renting` (N)
- Sort key: `num_bikes_available` (N)
- Projects: KEYS_ONLY + `name`, `lat`, `lon`
- Purpose: city-wide "find any active station with bikes" fast scan.

### TTL Strategy
- `ttl` = `updated_at + 3600` (1 hour)
- We keep at most ~60 snapshots per station (60 s cadence × 60 min)
- TTL deletion is eventual (~48 h lag typical) — acceptable since queries
  always filter by `updated_at DESC LIMIT 1`

### Access Patterns Supported

| Pattern                                     | DynamoDB operation                          |
|---------------------------------------------|---------------------------------------------|
| Get current state of one station            | `GetItem(station_id, updated_at=latest)`    |
| Get all stations in a lat/lon bbox          | `Query GSI-1` with `lat_bucket` + lon range |
| Find stations with bikes available          | `Query GSI-2(is_renting=1)` sorted by bikes |
| Audit history of one station                | `Query(station_id)` sorted by `updated_at`  |
| Lambda writer: upsert current status        | `PutItem` (no condition needed)             |

### Rationale
- Partition key `station_id` gives even distribution (~500 stations, all hot)
- Sort key `updated_at` avoids hot partitions from repeated overwrites
- GSI-1 enables the spatial query without a full table scan
- TTL keeps storage costs near zero (only ~1 h of snapshots retained)

---

## Table 2: `TransitStops`

### Purpose
Store GTFS stop metadata + route associations for proximity queries.  This
table is **write-once** (populated from GTFS at feed ingestion time) and
read-many (every MCP tool invocation).  A new GTFS feed version triggers a
full reload.

### Keys

| Attribute    | Type | Role          | Notes                               |
|--------------|------|---------------|-------------------------------------|
| `stop_id`    | S    | Partition key | GTFS stop_id, e.g. `"1.304"`        |
| `feed_ver`   | S    | Sort key      | Feed version, e.g. `"161721042026"` |

The `feed_ver` sort key lets us load a new GTFS version without deleting the
old one first — enabling blue/green feed transitions.

### All Attributes

| Attribute          | Type | Source          | Example value                          |
|--------------------|------|-----------------|----------------------------------------|
| `stop_id`          | S    | stops.txt       | `"1.304"`                              |
| `feed_ver`         | S    | feed_info.txt   | `"161721042026002"`                    |
| `stop_code`        | S    | stops.txt       | `"304"`                                |
| `stop_name`        | S    | stops.txt       | `"Sagrada Família"`                    |
| `stop_lat`         | N    | stops.txt       | `41.4030`                              |
| `stop_lon`         | N    | stops.txt       | `2.1744`                               |
| `lat_bucket`       | S    | computed        | `"41.40"` (round(lat, 2) as string)    |
| `location_type`    | N    | stops.txt       | `0` (platform/stop)                    |
| `parent_station`   | S    | stops.txt       | `"P.6660304"` (station group)          |
| `wheelchair`       | N    | stops.txt       | `1` (accessible)                       |
| `route_ids`        | SS   | trips+routes    | `{"1.5.1", "1.2.1"}` (string set)     |
| `route_names`      | SS   | routes.txt      | `{"L5", "L2"}` (string set)            |
| `route_types`      | NS   | routes.txt      | `{1}` (number set: metro=1)            |
| `modes`            | SS   | computed        | `{"metro"}` or `{"bus"}` or both       |
| `ttl`              | N    | loader computed | feed end_date as epoch + 7 days buffer |

### Global Secondary Indexes (GSIs)

**GSI-1: `LatBucketIndex`**
- Partition key: `lat_bucket` (S)
- Sort key: `stop_lon` (N)
- Projects: ALL
- Purpose: same bounding-box spatial pre-filter pattern as Bicing GSI-1.

**GSI-2: `ModeIndex`**
- Partition key: first element of `modes` (S, flattened to `primary_mode`)
- Sort key: `stop_lat` (N)
- Projects: KEYS_ONLY + `stop_name`, `route_names`, `stop_lat`, `stop_lon`
- Purpose: "find all metro stops near me" (mode-filtered proximity).

### TTL Strategy
- `ttl` = feed `feed_end_date` parsed to epoch + 7 days grace period
- For the current feed: `2026-12-16 + 7 days` ≈ epoch `1766534400`
- On feed refresh, loader writes new rows (new `feed_ver`); old rows expire
  naturally after the feed end date passes

### Access Patterns Supported

| Pattern                                     | DynamoDB operation                            |
|---------------------------------------------|-----------------------------------------------|
| Get stop metadata by ID                     | `GetItem(stop_id, feed_ver=current)`          |
| Nearby stops in a bbox                      | `Query GSI-1(lat_bucket)` filter lon range    |
| Metro-only stops near a point               | `Query GSI-2(primary_mode="metro")`           |
| All stops for a route                       | `Scan` with FilterExpr on `route_ids` (rare)  |
| Feed ingestion: write all stops             | `BatchWriteItem` (25 items/call)              |
| Retire old feed                             | TTL auto-expires; or `BatchDelete` by feed_ver|

### Rationale
- `stop_id` as PK avoids fan-out: each stop has exactly one canonical record
- `feed_ver` sort key supports safe feed version transitions
- `route_ids` / `route_names` as DynamoDB StringSet avoids a join table
- `lat_bucket` denormalization is cheap and makes spatial queries O(1) in WCU
- TTL tied to feed validity eliminates manual cleanup

---

## Table 3: `ScheduleCache` (optional, for GTFS fallback departures)

When the TMB live API is unavailable, the MCP tool falls back to GTFS static
schedules.  Pre-computing "next X departures from stop Y at time T" at query
time is expensive (1.2M stop_times rows).  Instead, we pre-aggregate by
`(stop_id, service_day, hour)` at feed-load time.

### Keys

| Attribute       | Type | Role          | Notes                                    |
|-----------------|------|---------------|------------------------------------------|
| `stop_id`       | S    | Partition key | Matches TransitStops stop_id             |
| `day_hour`      | S    | Sort key      | `"MON#08"` — weekday + 2-digit hour      |

### All Attributes

| Attribute       | Type | Description                                      |
|-----------------|------|--------------------------------------------------|
| `stop_id`       | S    | Stop identifier                                  |
| `day_hour`      | S    | e.g. `"MON#08"`, `"SAT#22"`                     |
| `departures`    | L    | List of `{route, headsign, minute}` maps         |
| `ttl`           | N    | Feed end date epoch + 7 days                     |

### Access pattern
`GetItem(stop_id, day_hour=current)` returns all scheduled departures for
that stop in the current hour; Lambda filters to `minute >= current_minute`.

---

## Summary

| Table            | PK           | SK           | Size estimate     | Write cadence         |
|------------------|--------------|--------------|-------------------|-----------------------|
| BicingStations   | station_id   | updated_at   | ~500 rows/cycle   | Every 60 s (Lambda)   |
| TransitStops     | stop_id      | feed_ver     | ~2,810 rows       | Per GTFS feed update  |
| ScheduleCache    | stop_id      | day_hour     | ~2,810 × 168 rows | Per GTFS feed update  |

Total steady-state storage: well under 1 GB — effectively free tier.
