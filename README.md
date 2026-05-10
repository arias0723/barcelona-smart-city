# Barcelona Smart City — Team 11

**UPC CCBDA · Project deadline: 2026-05-29**

An AI-powered smart city dashboard for Barcelona. A Claude-backed chatbot answers questions about transit, Bicing, and air quality using live data from AWS DynamoDB. The web UI shows a real-time map with route planning, a conversational AI assistant, and a city data layer overlay.

---

## Team

| Name | Vertical | Status |
|------|----------|--------|
| Jakub Dusza | Mobility (Bicing + Transit) + MCP server | ✅ Done |
| Mark Welf Atzberger | Air Quality | ✅ Done |
| Jia Lyu | Weather | ✅ Lambda deployed |
| Jose Ricardo Arias Perez | Noise | ⏳ Lambda needed |

---

## Quick Start

### Prerequisites
- Python 3.9+
- AWS account credentials (see [AWS Setup](#aws-setup))
- AWS CLI configured (`aws configure`)

### 1. Clone and install
```bash
git clone https://github.com/kubadusza/barcelona-smart-city.git
cd barcelona-smart-city

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure AWS credentials
```bash
# Option A: AWS CLI (recommended)
aws configure
# Enter: Access Key ID, Secret Access Key, Region (eu-west-1), output format (json)

# Option B: environment variables
export AWS_ACCESS_KEY_ID=your_key
export AWS_SECRET_ACCESS_KEY=your_secret
```

> **Ask Jakub** for the team AWS credentials. **Never commit credentials to git.**

### 3. Run the demo
```bash
bash demo/run.sh
# Open: http://localhost:8765
```

The demo uses AWS Bedrock (eu-north-1) for Claude Haiku and DynamoDB (eu-west-1) for live city data.

**MCP server (live):** `https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp` — connect from claude.ai or Claude Desktop to get Barcelona city tools in any Claude conversation.

---

## Project Structure

```
.
├── demo/
│   ├── app.py              # FastAPI backend: AI chat, tool dispatch, map data APIs
│   ├── index.html          # Single-page UI: Route Planner + AI Assistant + City Layers
│   └── run.sh              # Start script (sets env vars, launches uvicorn)
│
├── aws/
│   ├── setup.sh            # One-time: creates all DynamoDB tables, IAM roles, S3
│   ├── deploy.sh           # Packages and deploys Lambda functions + EventBridge schedules
│   ├── pause.sh            # Disable EventBridge schedules (stop ingestion)
│   ├── teardown.sh         # Delete all AWS resources
│   ├── lambdas/
│   │   ├── air_quality_ingest/   # Runs hourly → AirQualityReadings table
│   │   └── bicing_ingest/        # Runs every 5 min → BicingStations table
│   ├── scripts/
│   │   ├── load_gtfs.py    # One-time: loads 3,453 TMB stops into TransitStops
│   │   └── verify_data.py  # Checks all tables have data
│   └── policies/           # IAM policy JSON files
│
├── docs/
│   ├── AWS_SETUP.md        # Full AWS setup guide + DynamoDB schemas
│   ├── MARK_AIR_QUALITY.md # Air quality vertical details (Mark)
│   ├── JIA_WEATHER.md      # Weather vertical guide (Jia) ← your task
│   └── JOSE_NOISE.md       # Noise vertical guide (Jose) ← your task
│
├── gtfs/                   # Barcelona TMB GTFS feed (static, loaded into DynamoDB)
├── transit_route_tool.py   # Transitous API wrapper (real-time routing)
├── dynamodb_schema.md      # Full DynamoDB schema reference
└── requirements.txt
```

---

## Architecture

```
External APIs                  AWS (eu-west-1)              Demo (localhost)
─────────────                  ───────────────              ────────────────
Bicing GBFS ──────► Lambda (5 min) ──► BicingStations ──►┐
TMB GTFS ─────────► load_gtfs.py ───► TransitStops ───────►│  FastAPI
Transitous API ──────────────────────────────────────────►│  app.py
Open Data BCN ──►  Lambda (1 hr) ───► AirQualityReadings ►│     │
Meteocat ─────────► Lambda (Jia) ───► WeatherData ─────────►│     ▼
BCN Noise ────────► Lambda (Jose) ──► NoiseData ────────────►│  index.html
                                                            │  (Leaflet map +
AWS Bedrock ──────────────────────────────────────────────►│   AI chatbot)
(Claude Haiku, eu-north-1)                                  └────────────────
```

### AI Chatbot tools (live)
The Claude Haiku model has access to these tools, all backed by live AWS data:

| Tool | What it does |
|------|-------------|
| `get_transit_route` | Finds bus/metro routes between two Barcelona points via Transitous |
| `get_bicing` | Returns live Bicing station availability near a coordinate (via citybik.es) |
| `get_bicing_history` | Historical Bicing snapshots for a station (up to 30 days, every 5 min) |
| `get_transit_nearby` | Lists metro/bus stops near a coordinate from DynamoDB |
| `get_air_quality` | Returns latest NO2/PM10/O3/CO readings from the nearest XVPCA station |
| `get_air_quality_history` | Historical hourly air quality for a station + pollutant |
| `get_weather` | Current Barcelona weather (temperature, wind, precipitation) |

---

## AWS Setup

All infrastructure is already deployed on account `539592518821` (eu-west-1).

**MCP server endpoint:** `https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp`

To recreate from scratch on a new account:
```bash
bash aws/setup.sh         # ~2 min — creates tables, roles, S3
bash aws/deploy.sh all    # deploys Bicing + AQ + Weather Lambdas + MCP server + API Gateway
python3 aws/scripts/load_gtfs.py   # one-time GTFS load (~60 sec)
python3 aws/scripts/verify_data.py # confirm everything is working
```

See [`docs/AWS_SETUP.md`](docs/AWS_SETUP.md) for the full guide, DynamoDB schemas, and useful CLI commands.

---

## What each person needs to do

### Mark — Air Quality vertical
See **[`docs/MARK_AIR_QUALITY.md`](docs/MARK_AIR_QUALITY.md)** for the full data source, DynamoDB schema, and API details.

**Status: Lambda deployed + chatbot tool integrated ✅**

- `smart-city-air-quality-ingest` Lambda runs every hour, pulling from [Open Data BCN XVPCA API](https://opendata-ajuntament.barcelona.cat/data/en/dataset/qualitat-aire-detall-bcn)
- Covers 4 stations: Poblenou, Sants, Eixample, Gràcia — pollutants NO2, PM10, O3, CO
- `AirQualityReadings` DynamoDB table is live and populated
- `get_air_quality(lat, lon)` chatbot tool is wired into the demo — the AI uses it automatically when asked about air quality, pollution, or outdoor safety

**If you want to extend it:**
- Add more stations to the haversine lookup table in `demo/app.py` (`XVPCA_STATIONS` dict, around line 210)
- Add SO2/NOX to the pollutants queried in `run_tool()` under `get_air_quality`
- The `AirQualityReadings` table schema is in [`docs/MARK_AIR_QUALITY.md`](docs/MARK_AIR_QUALITY.md)

### Jia — Weather vertical
See **[`docs/JIA_WEATHER.md`](docs/JIA_WEATHER.md)** for step-by-step instructions.

**TL;DR:**
1. Create `aws/lambdas/weather_ingest/lambda_function.py` (template in the doc)
2. Add `deploy_weather()` to `aws/deploy.sh` following the `deploy_bicing()` pattern
3. Run `bash aws/deploy.sh weather`
4. Add a `get_weather(lat, lon)` tool to `demo/app.py` following the `get_air_quality` pattern

The `WeatherData` DynamoDB table is already created and waiting.
Data source: [Open-Meteo API](https://open-meteo.com/) (no key needed).

### Jose — Noise vertical
See **[`docs/JOSE_NOISE.md`](docs/JOSE_NOISE.md)** for step-by-step instructions.

**TL;DR:**
1. Create `aws/lambdas/noise_ingest/lambda_function.py`
2. Add `deploy_noise()` to `aws/deploy.sh`
3. Run `bash aws/deploy.sh noise`
4. Add a `get_noise_level(lat, lon)` tool to `demo/app.py`

The `NoiseData` DynamoDB table is already created and waiting.
Data source: [Open Data BCN acoustic sensors](https://opendata-ajuntament.barcelona.cat) (no key needed).

### Adding a tool to the demo chatbot

To wire up a new vertical as a chatbot tool, add two things in `demo/app.py`:

**1. Tool definition** (alongside the existing tools, ~line 47):
```python
TOOL_GET_WEATHER = {
    "name": "get_weather",
    "description": "Returns current weather in Barcelona near a coordinate. Use when asked about temperature, rain, wind...",
    "input_schema": {
        "type": "object",
        "properties": {
            "lat": {"type": "number"},
            "lon": {"type": "number"},
        },
        "required": ["lat", "lon"],
    },
}
```

**2. Implementation** in `run_tool()` (~line 200):
```python
elif name == "get_weather":
    lat = inp["lat"]; lon = inp["lon"]
    # Query WeatherData DynamoDB table, return structured dict
    table = dynamo.Table("WeatherData")
    # ... your query here ...
    return {"temperature_c": ..., "condition": ..., ...}
```

**3. Register it** in `ALL_TOOLS`:
```python
ALL_TOOLS = [MCP_TOOL_GET_TRANSIT_ROUTE, TOOL_GET_BICING, TOOL_GET_TRANSIT_NEARBY, TOOL_GET_AIR_QUALITY, TOOL_GET_WEATHER]
```

---

## Demo features

**Tab 1 — Route Planner**: Click two points on the Barcelona map → gets a real transit route via the Transitous API, draws it as a polyline with colour-coded metro/bus segments.

**Tab 2 — AI Assistant**: Chat with Claude Haiku. The model can look up transit stops, Bicing availability, and air quality in real time using the tools above.

**Tab 3 — City Layers**: Toggle live data overlays on the map — air quality stations (colour-coded by pollution level), metro stops, and bus stops. Also shows DynamoDB table stats.

---

## Local development tips

```bash
# Run with custom regions
BEDROCK_REGION=eu-north-1 DYNAMO_REGION=eu-west-1 bash demo/run.sh

# Hot reload is on by default (uvicorn --reload)
# Edit app.py or index.html and the server restarts automatically

# Check Lambda logs live
aws logs tail /aws/lambda/smart-city-air-quality-ingest --follow --region eu-west-1

# Query DynamoDB directly
aws dynamodb scan --table-name AirQualityReadings --limit 5 --region eu-west-1
```
