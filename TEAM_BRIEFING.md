# Barcelona Smart City — Team Briefing
**UPC CCBDA · Team 11 · Progress presentation: 2026-05-15**

This document is the single source of truth for tomorrow. Read it top to bottom (~15 min) and you will be fully up to speed.

---

## What we built

A live Barcelona city data platform exposed as an **MCP (Model Context Protocol) server** deployed on AWS. It turns any compatible AI (Claude, ChatGPT, etc.) into a city-aware assistant that can answer real-time questions about bikes, transport, weather, air quality, UV, and pollen — data updated every 5 minutes to hourly.

Anyone can connect right now:
```
https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp
```
Go to **claude.ai → Settings → Integrations → Add custom connector** and paste the URL.

---

## Architecture

### Data collection layer (always running on AWS)

```
Open APIs (no keys needed)          AWS eu-west-1
─────────────────────────           ─────────────────────────────────────────

Bicing GBFS ──────────────► Lambda: bicing_ingest    (every 5 min) ──► BicingStations
TMB GTFS (static) ────────► Script: load_gtfs.py     (one-time)    ──► TransitStops
Open Data BCN XVPCA ──────► Lambda: air_quality_ingest (every 1 hr) ──► AirQualityReadings
Open-Meteo ───────────────► Lambda: weather_ingest    (every 1 hr) ──► WeatherData
currentuvindex.com ───────► Lambda: uv_ingest         (every 1 hr) ──► UVData
Open-Meteo CAMS ──────────► Lambda: pollen_ingest     (every 1 hr) ──► PollenData

All schedules triggered by EventBridge. All tables: pay-per-request DynamoDB, 30-day TTL.
```

### Serving layer (MCP server)

```
User prompt
    │
    ▼
LLM (Claude / ChatGPT / ...)
    │  decides which tool to call
    ▼
MCP Client (claude.ai, Claude Desktop, VS Code...)
    │  JSON-RPC 2.0 over HTTPS
    ▼
AWS API Gateway  ──►  Lambda: mcp_server  ──►  DynamoDB (reads)
                                          ──►  Live APIs (Transitous routing, UV, pollen)
    │
    ▼
Tool result returned to LLM → answer to user
```

### Demo web app (local)

```
Browser
    │
    ▼
FastAPI app (demo/app.py, localhost:8765)
    ├── Leaflet map  ──► DynamoDB (air quality stations, transit stops, Bicing)
    ├── Route planner ──► Transitous open router (live)
    └── AI chat  ──► AWS Bedrock (Claude Haiku, eu-north-1) + tool dispatch → DynamoDB
```

---

## 11 MCP Tools

| Tool | Vertical | Data | Update |
|------|----------|------|--------|
| `get_bicing` | Mobility | Bicing GBFS live | every 5 min |
| `get_bicing_history` | Mobility | DynamoDB BicingStations | every 5 min |
| `get_transit_nearby` | Mobility | DynamoDB TransitStops (3 453 stops) | static GTFS |
| `get_transit_route` | Mobility | Transitous live router | per request |
| `get_air_quality` | Air Quality | DynamoDB AirQualityReadings | hourly |
| `get_air_quality_history` | Air Quality | DynamoDB AirQualityReadings | hourly |
| `get_weather` | Weather | DynamoDB WeatherData | hourly |
| `get_uv_index` | UV | currentuvindex.com (live) | per request |
| `get_uv_history` | UV | DynamoDB UVData | hourly |
| `get_pollen` | Pollen | Open-Meteo CAMS (live) | per request |
| `get_pollen_history` | Pollen | DynamoDB PollenData | hourly |

---

## AWS Infrastructure

| Resource | Name | Purpose |
|----------|------|---------|
| DynamoDB | BicingStations | Bicing snapshots every 5 min |
| DynamoDB | TransitStops | 3 453 TMB GTFS stops (static) |
| DynamoDB | ScheduleCache | Transit schedule cache |
| DynamoDB | AirQualityReadings | Hourly pollution readings |
| DynamoDB | WeatherData | Hourly weather data |
| DynamoDB | UVData | Hourly UV index |
| DynamoDB | PollenData | Hourly pollen levels |
| Lambda ×5 | smart-city-*-ingest | Data collectors, EventBridge triggered |
| Lambda ×1 | smart-city-mcp | MCP server handler |
| API Gateway | — | HTTPS endpoint for MCP |
| S3 | smart-city-raw-* | Lambda deployment packages |
| IAM | smart-city-lambda-*-role | Per-Lambda least-privilege roles |
| EventBridge | bicing-ingest-schedule | Triggers Bicing Lambda every 5 min |
| EventBridge | *-ingest-schedule ×4 | Triggers other Lambdas every 1 hr |

**Account:** 539592518821 · **Region:** eu-west-1

---

## Codebase map

```
barcelona-smart-city/
│
├── mcp_server.py              # MCP server — all 11 tools, Lambda handler
├── transit_route_tool.py      # Transitous routing helper (used by MCP + demo)
├── bicing_exploration.py      # Scratch/exploration file
│
├── aws/
│   ├── setup.sh               # Creates all DynamoDB tables + IAM roles (idempotent)
│   ├── deploy.sh              # Packages + deploys all Lambdas + API Gateway
│   ├── pause.sh               # Pauses EventBridge schedules (cost saving)
│   ├── teardown.sh            # Deletes all AWS resources
│   ├── lambdas/
│   │   ├── bicing_ingest/     # → BicingStations
│   │   ├── air_quality_ingest/# → AirQualityReadings
│   │   ├── weather_ingest/    # → WeatherData
│   │   ├── uv_ingest/         # → UVData
│   │   └── pollen_ingest/     # → PollenData
│   ├── scripts/
│   │   ├── load_gtfs.py       # One-time GTFS load (3 453 stops)
│   │   └── verify_data.py     # Checks all tables have data
│   └── policies/              # IAM policy JSON files
│
├── demo/
│   ├── app.py                 # FastAPI: Bedrock chat + tool dispatch + map APIs
│   ├── index.html             # UI: Leaflet map + AI chat + city layers
│   ├── run.sh                 # Start script
│   ├── DEMO_SLIDES.html       # Reveal.js presentation (open in browser)
│   ├── PRESENTER_NOTES.md     # Demo script + Q&A prep
│   └── data_charts.html       # UV + pollen accumulation charts
│
└── docs/
    ├── AWS_SETUP.md           # Full AWS setup guide + DynamoDB schemas
    ├── MARK_AIR_QUALITY.md    # Air quality vertical details
    ├── JIA_WEATHER.md         # Weather vertical details
    └── JOSE_NOISE.md          # Original noise spec (pivoted to UV+Pollen)
```

---

## Who did what

### Jakub — Mobility vertical + MCP server + Infrastructure

- All deployment scripts: `setup.sh`, `deploy.sh`, `pause.sh`, `teardown.sh`
- **Bicing + Transit vertical**: `bicing_ingest` Lambda, GTFS loader (3 453 stops), `get_bicing`, `get_bicing_history`, `get_transit_nearby`, `get_transit_route` MCP tools
- **MCP server** (`mcp_server.py`): all 11 tools, FastMCP, deployed as Lambda behind API Gateway
- **Demo web app** (`demo/app.py`, `demo/index.html`): FastAPI backend, Bedrock/Claude Haiku integration, Leaflet map, route planner, AI chat
- Research presentation: **live demo** (connected MCP to claude.ai, showed real tool calls live)

### Mark — Air Quality vertical + AWS architecture + MCP research

- Designed the full AWS architecture: DynamoDB schema, IAM roles, EventBridge schedules, API Gateway
- **Air quality vertical**: found Open Data BCN XVPCA API (4 Barcelona monitoring stations), wrote `air_quality_ingest` Lambda, designed `AirQualityReadings` DynamoDB schema
- `get_air_quality` + `get_air_quality_history` MCP tools, with WHO threshold labelling (good / moderate / unhealthy)
- Research presentation: **MCP section** — explained the protocol, JSON-RPC handshake, tool primitives

### Jia — Weather vertical + research coordination

- **Weather vertical**: wrote `weather_ingest` Lambda (Open-Meteo, no API key), `WeatherData` DynamoDB table, `get_weather` MCP tool returning temperature, wind, precipitation, WMO condition codes
- Coordinated the research presentation: structured the agenda (Bedrock → MCP → demo), managed slide contributions from teammates
- Research presentation: **project overview + coordination**

### José — UV + Pollen verticals + Bedrock research

- **UV vertical**: wrote `uv_ingest` Lambda (currentuvindex.com CAMS model), `UVData` DynamoDB table, `get_uv_index` (live, with burn-time formula and SPF recommendation) + `get_uv_history` MCP tools
- **Pollen vertical**: wrote `pollen_ingest` Lambda (Open-Meteo CAMS air quality), `PollenData` DynamoDB table, `get_pollen` + `get_pollen_history` MCP tools covering grass, birch, olive, mugwort, ragweed
- Navigated a dead data source (Sentilo noise sensors — all return no data) and successfully pivoted to working alternatives
- Research presentation: **Amazon Bedrock section** — platform overview, Bedrock Agents, Foundation Models, AgentCore

---

## 3 questions for tomorrow

### Jakub
**What did you do?**
Designed and built the full data infrastructure: 7 DynamoDB tables, 5 ingest Lambdas, EventBridge schedules, IAM roles, API Gateway, and the MCP server exposing 11 tools. Also built the Bicing + Transit vertical and the demo web app using Bedrock.

**What would you have done differently?**
Verify every data source returns actual live data before writing a Lambda. Two verticals (noise, beach water quality) were built against APIs that turned out to have no live data — had to be scrapped. Would also spec the Bedrock application first, then design data schemas to match it, rather than the other way around.

**What do you plan to do next?**
Build the Bedrock Agents application: create a Bedrock Agent that uses the MCP server as its tool provider, add a proper persistent web interface, and deploy it publicly rather than locally.

---

### Mark
**What did you do?**
Built the air quality vertical end-to-end: identified the Open Data BCN XVPCA sensor network, wrote the ingest Lambda, designed the DynamoDB schema (partition by station+pollutant, sort by hour), and implemented the MCP tools with WHO air quality threshold labelling.

**What would you have done differently?**
The current station lookup is a hardcoded haversine over 4 stations. Would query all available stations dynamically so any neighbourhood in Barcelona is covered, not just Poblenou, Sants, Eixample, Gràcia.

**What do you plan to do next?**
Integrate proactive air quality alerts into the Bedrock app — the agent should warn users when readings cross WHO thresholds without being asked.

---

### Jia
**What did you do?**
Built the weather vertical (Open-Meteo → DynamoDB → MCP tool) and coordinated the research presentation — structured the agenda, distributed sections to teammates, and ensured the final slides cohered.

**What would you have done differently?**
Store hourly forecasts (next 24h) in DynamoDB alongside current conditions, not just the current snapshot. That would make trend queries much richer and enable "will tomorrow morning be good for a run?" without hitting the live API.

**What do you plan to do next?**
Contribute to the Bedrock app frontend and help integrate weather into composite queries ("is today a good day to be outside?") that orchestrate multiple tools in one agent turn.

---

### José
**What did you do?**
Built the UV and pollen verticals (2 ingest Lambdas, 2 DynamoDB tables, 4 MCP tools). The UV tool includes the Diffey burn-time formula and SPF recommendations; the pollen tool covers 5 species with level classifications. Also handled the Bedrock section of the research presentation.

**What would you have done differently?**
When the original noise data source (Sentilo) turned out to be dead, it took time to diagnose — the API returns HTTP 200 with `"found": false` rather than an error. Would validate data sources with a quick scan query before committing to building around them.

**What do you plan to do next?**
Own a component of the Bedrock Agents application — likely the agent orchestration configuration or the action group wiring that connects Bedrock to the MCP tools.

---

## What's left to do (deadline May 29)

The MCP server is the **data layer** — complete and live. The professors expect a full **Bedrock Agents application** on top of it:

1. **Bedrock Agent** — create an agent in the AWS console, define an action group backed by the MCP Lambda (or thin Lambda wrappers per tool), write the agent instruction prompt
2. **Knowledge base** (optional but strong) — RAG over static Barcelona city info (neighbourhoods, points of interest) stored in S3, indexed by Bedrock's managed OpenSearch
3. **Public web UI** — repoint `demo/app.py` to call the Bedrock Agents `invoke_agent` API instead of raw `bedrock-runtime`; deploy on EC2 or ECS so it's accessible without running locally
4. **Guardrails** (optional) — add a Bedrock Guardrail to block off-topic queries and PII

---

## How to run the demo locally

```bash
git clone https://github.com/kubadusza/barcelona-smart-city.git
cd barcelona-smart-city
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Ask Jakub for AWS credentials, then:
bash demo/run.sh
# Open: http://localhost:8765
```

**To connect your own Claude to the live MCP server:**
1. Open `tinyurl.com/mwn6jzdt` in a browser — copy the full AWS URL shown
2. Go to **claude.ai → Settings → Integrations**
3. Add custom connector → paste URL → Save → start a new chat

**Demo prompts to try:**
- *"I'm going for a run in Barcelona tomorrow morning. Will the air quality and pollen be okay?"*
- *"I want to take my kids to Barceloneta this afternoon — is the UV too strong? What SPF do we need?"*
- *"Are there Bicing bikes near Sagrada Família right now?"*
- *"Is today a good day to be outside in Barcelona? Weather, UV, air quality, pollen — give me a summary."*

---

## Key technical facts to know

| Topic | Detail |
|-------|--------|
| MCP protocol | JSON-RPC 2.0 over HTTPS. Three steps: initialize handshake → `tools/list` → `tools/call` |
| Why MCP matters | Build the server once; any compatible AI client gets city awareness — no bespoke integration per client |
| AWS Bedrock | Managed API for foundation models (Claude, Llama, Nova, Titan). No model training or hosting. Used in demo via `bedrock-runtime` with Claude Haiku |
| Bedrock Agents | Orchestration loop inside Bedrock: agent decides which tool to call, calls it, incorporates result, continues until it can answer. What we need to build next |
| DynamoDB TTL | All tables have 30-day TTL on raw records — data auto-expires, no cleanup needed |
| No API keys | All external data sources (Bicing, Open-Meteo, Open Data BCN, Transitous) are free with no auth |
| Dead data sources | Sentilo (noise/traffic), CKAN beach water quality — endpoints exist but return no live data |
