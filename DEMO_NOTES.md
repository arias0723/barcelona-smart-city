# Barcelona Smart City — Demo Notes

**UPC CCBDA · Team 11 · Deadline: 2026-05-29**

---

## What We Built

A **live Barcelona city data platform** surfaced through an MCP (Model Context Protocol) server deployed on AWS. It turns Claude into a city-aware assistant that can answer questions about the real state of Barcelona right now — bikes, transport, pollution, weather, UV, and pollen — with data updated every 5 minutes to hourly.

### Architecture

```
User ──► Claude (claude.ai / Claude Desktop)
              │
              │  MCP (JSON-RPC 2.0 over HTTPS)
              ▼
     AWS API Gateway HTTP API
              │
              ▼
     AWS Lambda — MCP Server (Python, FastMCP)
              │
              ▼
     AWS DynamoDB (7 tables, eu-west-1)
              ▲
              │  hourly / every-5-min ingest
     AWS Lambda × 4 (Bicing, Air Quality, Weather, UV, Pollen)
              ▲
              │  live APIs
     Bicing GBFS · TMB GTFS · Open Data BCN · Open-Meteo
     currentuvindex.com · Transitous router
```

No API keys required for any external source. All infrastructure runs on pay-per-request DynamoDB and Lambda (effectively free at demo scale).

### 11 MCP Tools

| Tool | Data source | Update cadence |
|------|-------------|----------------|
| `get_bicing` | Bicing GBFS live feed | Every 5 min |
| `get_bicing_history` | DynamoDB (BicingStations) | Every 5 min |
| `get_transit_nearby` | DynamoDB (TransitStops, 3 453 stops) | Static GTFS |
| `get_transit_route` | Transitous open router (live) | Per request |
| `get_air_quality` | DynamoDB (AirQualityReadings) | Hourly |
| `get_air_quality_history` | DynamoDB (AirQualityReadings) | Hourly |
| `get_weather` | DynamoDB (WeatherData, Open-Meteo) | Hourly |
| `get_uv_index` | currentuvindex.com (CAMS model) | Per request |
| `get_uv_history` | DynamoDB (UVData) | Hourly |
| `get_pollen` | Open-Meteo CAMS air quality | Per request |
| `get_pollen_history` | DynamoDB (PollenData) | Hourly |

### MCP Server Endpoint

```
https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp
```

Connect from **claude.ai → Settings → Integrations** or Claude Desktop `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "barcelona-smart-city": {
      "url": "https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp"
    }
  }
}
```

---

## Why MCP? The Core Argument

**Ask the same questions to a plain Claude (no tools) and to this one.**

Plain Claude has a knowledge cutoff and no access to live city data. It either refuses, hedges, or hallucinates outdated numbers. This server turns Claude into an agent that fetches real, current data and reasons over it — the difference is immediately visible in the demo.

The point is not just "Claude + API calls". MCP is a **standard protocol** that lets any AI client (Claude Desktop, claude.ai, VS Code extensions, other MCP-compatible agents) consume city data without bespoke integration work. Build the server once; any compatible client gets city awareness for free.

---

## Demo Prompts

The following prompts are designed to show the contrast between plain Claude (fails or guesses) and Claude + this MCP server (calls tools, gets real data, gives specific answers).

### Mobility

> "Are there any Bicing bikes available near Sagrada Família right now?"

Plain Claude: "I don't have access to real-time data…"
With MCP: Shows live bike counts, station names, distance, mechanical vs electric split.

---

> "How do I get from UPC Campus Nord to Barceloneta by public transport?"

Plain Claude: Generic directions, possibly outdated lines, no departure times.
With MCP: Real journey options with legs (walk + metro + walk), line names, duration.

---

> "What metro and bus lines serve Gràcia?"

Plain Claude: Lists lines from training data, possibly wrong.
With MCP: Queries 3 453 loaded GTFS stops, returns actual routes serving the area.

---

> "Show me the Bicing availability history for station 106 over the last 48 hours — when does it run out of bikes?"

Plain Claude: Cannot answer.
With MCP: Plots 48 hours of 5-minute snapshots; identifies dry periods from real data.

---

### Environmental

> "Is the air quality good enough to go for a run in the Eixample today?"

Plain Claude: Generic advice, no Barcelona-specific data.
With MCP: Returns live NO2, PM10, O3 readings from the nearest monitoring station with WHO status labels (good / moderate / unhealthy).

---

> "What's been the worst hour for pollution in Gràcia this week?"

Plain Claude: Cannot answer.
With MCP: Queries AirQualityReadings history, finds the peak hour and value.

---

> "What's the UV index right now in Barcelona and when is the peak today? How long can I stay in the sun without sunscreen?"

Plain Claude: "I don't have real-time UV data…"
With MCP: Current UVI, WHO risk category, today's peak window, burn time for fair skin (Diffey formula), SPF recommendation.

---

> "Is the UV index this week higher or lower than average? Show me the trend."

Plain Claude: Cannot answer.
With MCP: Pulls hourly UVData history, plots the curve, summarises avg and max.

---

> "I'm allergic to grass pollen. How bad is it in Barcelona today and when is the worst window?"

Plain Claude: Generic seasonal advice.
With MCP: Current grains/m³ for grass pollen, level badge, 24-hour peak forecast window.

---

> "Compare grass and olive pollen levels over the last week."

Plain Claude: Cannot answer.
With MCP: Calls `get_pollen_history` for both species, overlays the trend.

---

### Combined / Planning

> "I want to cycle from Plaça Catalunya to the beach. What are current air quality and UV conditions for outdoor exercise?"

Plain Claude: Generic advice.
With MCP: Checks Bicing availability near Plaça Catalunya, air quality near the route, current UV with burn time — gives an actionable composite answer.

---

> "Is today a good day to be outside in Barcelona? Weather, UV, air quality, and pollen — give me a summary."

Plain Claude: Generic seasonal answer.
With MCP: Orchestrates four tool calls, returns a real composite city health snapshot.

---

## Visualization Notes

Tool descriptions embed `PRESENTATION:` instructions that Claude follows when rendering results. This ensures consistent rich output without prompt engineering from the user.

### Pattern: real-time tools
> Display as visual **metric cards**. Add a **'Use case' insight** section with actionable context. Add **2–3 follow-up suggestion buttons** (using `sendPrompt`) that encourage natural next queries.

Applies to: `get_bicing`, `get_transit_nearby`, `get_transit_route`, `get_air_quality`, `get_weather`, `get_uv_index`, `get_pollen`.

### Pattern: history tools
> **Always generate a plot** of the primary metric over time. Display **summary stats** (avg, max, peaks) as metric cards. Add a **'Use case' insight** and **2–3 follow-up buttons**.

Applies to: `get_bicing_history`, `get_air_quality_history`, `get_uv_history`, `get_pollen_history`.

Specific notes per tool:
- **`get_uv_history`** — line chart of UVI, daily peaks highlighted, avg/max cards.
- **`get_pollen_history`** — line chart with colour bands for low / moderate / high / very high levels.
- **`get_bicing_history`** — plot of bikes_available over time.
- **`get_air_quality_history`** — plot of pollutant concentration with WHO threshold bands.

The follow-up buttons are the key UX driver: they keep the user exploring city data without having to know what to ask next.

---

## What Was Hard / What Was Learned

**Fake data sources are a real risk.** Two verticals (beach water quality, noise) were built with CKAN resource IDs that 404'd — the data simply never existed at those endpoints. Lesson: verify each source returns actual data before writing a Lambda around it.

**IAM policy updates don't auto-apply.** `ensure_role` in deploy.sh is create-only. After adding new tables to a policy, you must run `aws iam put-role-policy` explicitly — otherwise the Lambda silently hits `AccessDeniedException` at runtime. This was fixed; setup.sh and deploy.sh now always call `put-role-policy` for new roles.

**Pollen history can only be built forward.** Open-Meteo's pollen API has no history endpoint — it serves forecasts only. The only way to accumulate historical pollen data is to store each hourly ingest as it arrives. The `PollenData` table starts accumulating from deployment day.

**UV nighttime edge case.** `get_uv_index` originally used `time.gmtime()` date to find "today's peak". At night (UTC date already rolled over), there were no forecast entries for that date and the tool returned the 5-day future peak instead. Fixed: "today" is derived from the first non-zero entry in the forecast — the date of the next sunrise, always correct regardless of time of day.

**Sentilo (Barcelona IoT platform) is mostly dead.** `connecta.bcn.cat` lists hundreds of sensors (noise, traffic, parking) but nearly all return `"found": false` on last-observation queries. Only the 199 CESVA noise sensors appear live; the rest are catalog entries from a 2014 pilot with no actual data.

---

## File Map

```
mcp_server.py              # MCP server — all 11 tools, Lambda handler
transit_route_tool.py      # Transitous routing helper
aws/
  setup.sh                 # Creates DynamoDB tables + IAM roles (idempotent)
  deploy.sh                # Packages + deploys all Lambdas + API Gateway
  lambdas/
    bicing_ingest/         # Bicing GBFS → BicingStations
    air_quality_ingest/    # Open Data BCN XVPCA → AirQualityReadings
    weather_ingest/        # Open-Meteo → WeatherData
    uv_ingest/             # currentuvindex.com → UVData
    pollen_ingest/         # Open-Meteo CAMS → PollenData
  policies/
    lambda_trust_policy.json
    lambda_mobility_policy.json
    lambda_air_quality_policy.json
    lambda_weather_policy.json
    lambda_uv_policy.json
    lambda_pollen_policy.json
    lambda_mcp_policy.json # MCP role — read access to all 7 tables
demo/
  app.py                   # Streamlit/Flask web demo UI
  index.html               # Static demo page
```
