# Smart City — AWS Setup Guide

**Team 11 · UPC CCBDA · Project deadline: 2026-05-29**

---

## What's been set up

All AWS infrastructure was created on account `539592518821` (Jakub's account, region `eu-west-1` — Ireland).
When we move to a shared account, re-run `bash aws/setup.sh` and `bash aws/deploy.sh` — the scripts are fully repeatable.

### AWS Resources (already live)

| Resource | Name | Purpose |
|---|---|---|
| S3 Bucket | `smart-city-raw-539592518821` | Raw data archive |
| DynamoDB | `BicingStations` | Live Bicing station snapshots (every 5 min) |
| DynamoDB | `TransitStops` | TMB GTFS stops + route metadata (**3,453 stops loaded**) |
| DynamoDB | `ScheduleCache` | GTFS hourly departure cache (future use) |
| DynamoDB | `AirQualityReadings` | Barcelona air quality readings (every 1 hour) |
| DynamoDB | `WeatherData` | Placeholder — **Jia's vertical** |
| DynamoDB | `NoiseData` | Placeholder — **Jose's vertical** |
| Lambda | `smart-city-bicing-ingest` | Runs every 5 min → writes to BicingStations |
| Lambda | `smart-city-air-quality-ingest` | Runs every 1 hour → writes to AirQualityReadings |
| IAM Role | `smart-city-lambda-mobility-role` | Jakub's Lambdas (Bicing + Transit) |
| IAM Role | `smart-city-lambda-air-quality-role` | Mark's Lambda (air quality) |
| EventBridge | `smart-city-bicing-schedule` | Triggers bicing Lambda every 5 min |
| EventBridge | `smart-city-air-quality-schedule` | Triggers air quality Lambda every 1 hour |

---

## How to set up on a new account

### 1. Prerequisites
- AWS CLI installed: `aws --version`
- Python 3.9+: `python3 --version`
- AWS credentials configured

### 2. Configure credentials
```bash
# Option A: use environment variables
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
export AWS_REGION=eu-west-1

# Option B: run AWS CLI configure
aws configure
```

### 3. Clone / copy the project
```bash
cd smart_city/
```

### 4. Create all infrastructure (one command)
```bash
bash aws/setup.sh
```
This creates: S3 bucket, 6 DynamoDB tables, 2 IAM roles. Takes ~2 minutes.
Safe to re-run — skips resources that already exist.

### 5. Deploy Lambda functions
```bash
bash aws/deploy.sh
```
This packages and deploys both Lambdas + wires EventBridge schedules. Takes ~30 seconds.

### 6. Load GTFS stop data (one-time, mobility only)
```bash
python3 aws/scripts/load_gtfs.py
```
Loads 3,453 TMB transit stops into `TransitStops`. Takes ~60 seconds.
Only needs to be re-run when a new GTFS feed is published (next one expected Dec 2026).

### 7. Verify everything is working
```bash
python3 aws/scripts/verify_data.py
```

---

## Team: what each person needs to do

### Jakub — Mobility ✅ Done this week
- [x] Bicing ingest Lambda deployed (`smart-city-bicing-ingest`, runs every 5 min)
- [x] GTFS stops loaded into `TransitStops` (3,453 stops)
- [x] Transit routing via `transit_route_tool.py` (calls Transitous API on demand, no Lambda needed)
- [ ] Write MCP tool: `get_bicing_stations(lat, lon, radius_m)` — reads from `BicingStations`
- [ ] Write MCP tool: `get_transit_stops(lat, lon, radius_m)` — reads from `TransitStops`
- ⚠️ Note: Bicing BSM API has been returning 503 (transient outage). Lambda handles this gracefully. Will self-resolve.

### Mark — Air Quality ✅ Done this week
- [x] Air quality ingest Lambda deployed (`smart-city-air-quality-ingest`, runs every 1 hour)
- [x] `AirQualityReadings` table populated (16 readings/hour from 4 Barcelona stations)
- [ ] Write MCP tool: `get_air_quality(lat, lon)` — reads latest reading per pollutant near given point
- See: `docs/MARK_AIR_QUALITY.md` for API details and table schema

### Jia — Weather ⏳ Your turn
- `WeatherData` table is created and ready
- Need to: write Lambda ingestion function → `aws/lambdas/weather_ingest/lambda_function.py`
- Then run `bash aws/deploy.sh weather` to deploy
- Data sources: Meteocat, OpenMeteo
- See table schema suggestions in `docs/JIA_WEATHER.md`

### Jose — Noise ⏳ Your turn
- `NoiseData` table is created and ready
- Need to: write Lambda ingestion function → `aws/lambdas/noise_ingest/lambda_function.py`
- Then run `bash aws/deploy.sh noise` to deploy
- See table schema suggestions in `docs/JOSE_NOISE.md`

---

## DynamoDB Tables — Quick Reference

### BicingStations
```
PK: station_id (String)    e.g. "420"
SK: updated_at (Number)    Unix timestamp
TTL: ttl                   expires 1 hour after write

Key fields:
  name, lat, lon, lat_bucket
  num_bikes_available, num_ebikes_available, num_mechanical_available
  num_docks_available, is_renting, capacity

GSI: LatIndex              lat_bucket (S) + lon (N)  → spatial queries
GSI: StatusIndex           is_renting (N) + num_bikes_available (N) → find bikes
```

### TransitStops
```
PK: stop_id (String)       e.g. "1.304"
SK: feed_ver (String)      e.g. "161721042026002"
TTL: ttl                   expires when GTFS feed expires (2026-12-16 + 7 days)

Key fields:
  stop_name, stop_lat, stop_lon, lat_bucket
  route_ids (StringSet), route_names (StringSet), modes (StringSet)
  primary_mode ("metro" or "bus" or "tram")

GSI: LatBucketIndex        lat_bucket (S) + stop_lon (N) → spatial queries
```

### AirQualityReadings
```
PK: station_pollutant (S)  e.g. "43_NO2"
SK: hour_ts (S)            e.g. "2026042714" (YYYYMMDDHH)
TTL: ttl                   expires 48 hours after write

Key fields:
  station_id, station_name, district
  lat, lon, lat_bucket
  pollutant_name ("NO2", "PM10", "O3", "CO", "SO2", "NOX")
  value, unit, validated

GSI: LatBucketIndex        lat_bucket (S) + hour_ts (S) → spatial queries

Stations covered:
  4  → Poblenou   (41.4039, 2.2045)
  42 → Sants      (41.3788, 2.1331)
  43 → Eixample   (41.3853, 2.1538)
  44 → Gràcia     (41.3987, 2.1534)
```

---

## Useful AWS CLI commands

```bash
# Check Lambda logs (live tail)
aws logs tail /aws/lambda/smart-city-bicing-ingest --follow --region eu-west-1
aws logs tail /aws/lambda/smart-city-air-quality-ingest --follow --region eu-west-1

# Invoke Lambda manually
aws lambda invoke --function-name smart-city-bicing-ingest \
  --payload '{}' /tmp/out.json --region eu-west-1 && cat /tmp/out.json

# Query DynamoDB — scan first 5 items from AirQualityReadings
aws dynamodb scan --table-name AirQualityReadings \
  --limit 5 --region eu-west-1

# Query all Eixample (station 43) air quality readings
aws dynamodb query --table-name AirQualityReadings \
  --key-condition-expression "station_pollutant = :pk" \
  --expression-attribute-values '{":pk": {"S": "43_NO2"}}' \
  --scan-index-forward false --limit 5 --region eu-west-1
```

---

## Architecture overview

```
External APIs                   AWS                          MCP + Demo
─────────────                   ───                          ──────────
Bicing GBFS ─────────────► Lambda (5 min) ──► BicingStations ──►│
TMB GTFS (static) ───────► load_gtfs.py ───► TransitStops ──────►│  MCP Server
Transitous API ──────────────────────────────────────────────────►│  (tools)
Open Data BCN ───────────► Lambda (1 hr) ───► AirQualityReadings ►│
Meteocat/OpenMeteo ──────► Lambda (Jia) ───► WeatherData ─────────►│
BCN Noise sensors ───────► Lambda (Jose) ──► NoiseData ───────────►│
                                                                  ▼
                                                        Bedrock chatbot demo
```

---

## Cost estimate

All usage is within AWS free tier:
- Lambda: 1M requests/month free (always) — project uses ~8,640/month per Lambda
- DynamoDB: 25 GB + 25 WCU/25 RCU free (always) — project uses << 1 GB
- S3: 5 GB free for 12 months — project uses << 100 MB

**Expected monthly cost: $0.00**
