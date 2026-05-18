# Barcelona Smart City — Final Presentation Plan
**UPC CCBDA · Team 11 · Deadline: 2026-05-29**

---

## The story we're telling

> **"We built a live Barcelona city data platform and showed that one standard data layer can power multiple real AI applications — a web dashboard where an AI agent controls an interactive map in real time, and a Telegram bot for on-the-go city queries — all running on AWS with zero proprietary lock-in."**

The arc:
1. **Data layer** — 6 live data types (Bicing, transit, air quality, weather, UV, pollen), ingested on AWS, stored in DynamoDB, exposed as an MCP server. Already done and running.
2. **Any AI can use it** — we demonstrated this with claude.ai connecting to our MCP endpoint and answering real questions. The data layer is model-agnostic.
3. **Now we build our own AI applications on top** — using AWS Bedrock. Two real apps:
   - A **web dashboard** where an AI agent has live city data *and* can control the map (show routes, drop pins, overlay data layers)
   - A **Telegram bot** where users can ask city questions and subscribe to air quality / pollen alerts
4. **Why Bedrock?** We're fully inside AWS. Bedrock gives us Claude (or any foundation model) without model hosting, billing, or auth management — and Bedrock AgentCore lets us wire our MCP server as the agent's toolset in a few lines of config.

---

## How Bedrock Agents work (technical briefing)

Bedrock AgentCore (GA October 2025) is the managed orchestration layer:

```
User input
    │
    ▼
Bedrock Agent (instruction prompt + model choice)
    │  decides which tool to call, in a loop
    ▼
AgentCore Gateway ──► our MCP server (HTTPS)
                         └── 11 tools → DynamoDB / live APIs
    │
    ▼
Agent assembles final answer → streamed back to caller
```

**How we invoke it from Python (boto3):**
```python
import boto3
client = boto3.client("bedrock-agent-runtime", region_name="eu-west-1")
response = client.invoke_agent(
    agentId="AGENT_ID",
    agentAliasId="TSTALIASID",
    sessionId="user-session-123",
    inputText="Is the air quality okay for a run in Gràcia today?"
)
for event in response["completion"]:
    print(event["chunk"]["bytes"].decode())
```

**Setup effort: ~1–2 hours** for a working agent. No model training, no GPU, no hosting.

**Model:** Claude Sonnet 4.6 is available in eu-west-1 — use that.

**MCP connection:** AgentCore Gateway can connect directly to our existing MCP endpoint via its "MCP server" integration type. No Lambda wrappers needed — point it at `https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp` and the gateway handles tool discovery and calling.

---

## What we're building

### App 1 — AI Map Dashboard (web app)

A public-facing website where a chatbot has live city data *and can control the map*.

**What makes this different from the current demo:**
The current demo (`demo/app.py`) is a basic Claude chat with tool dispatch — it returns text. The new app has the AI as a **map controller**: it can drop pins, draw routes, toggle data overlays, and generate mini dashboards — all in response to natural language. The user talks; the map responds.

**Architecture:**
```
Browser
  ├── Leaflet map (interactive)
  ├── Chat panel
  └── Dashboard panel (charts)
         │ WebSocket
         ▼
    FastAPI server (AWS EC2 or ECS)
         │ invoke_agent
         ▼
    Bedrock Agent (Claude Sonnet 4.6)
         │ AgentCore Gateway
         ▼
    Our MCP server (11 tools, DynamoDB)
```

**AI map-control tools** (frontend-side, not MCP — the agent calls these to update the UI):
- `place_pin(lat, lon, label, color)` — drop a marker on the map
- `show_route(from_lat, from_lon, to_lat, to_lon)` — draw a route polyline
- `show_data_layer(type)` — toggle air quality / Bicing / transit overlays
- `zoom_to(location_name)` — fly the map to a neighbourhood or landmark
- `show_chart(metric, time_range)` — render a chart in the dashboard panel

When the agent calls `get_bicing` via MCP *and* calls `place_pin` for each station, the user sees the result both as text and visually on the map.

**Example interaction:**
> "Show me Bicing stations near Sagrada Família with available bikes"
→ Agent calls `get_bicing(41.4036, 2.1744)` via MCP, then calls `place_pin` for each result → green pins appear on the map + text summary in chat

**Required:**
- Uses Bedrock Agent (Claude Sonnet 4.6, eu-west-1)
- Uses our MCP server via AgentCore Gateway
- Hosted on AWS (EC2 or ECS, public URL)
- Map shows routes, pins, data overlays driven by AI

**Nice to have:**
- Bedrock Knowledge Base (RAG over static Barcelona neighbourhood info)
- Conversation memory across sessions (Bedrock session state)
- Bedrock Guardrails (block off-topic queries)

---

### App 2 — Telegram Bot (José)

A Telegram bot users can message to ask about Barcelona city conditions, plus an optional alert subscription system.

**Architecture:**
```
Telegram user
      │ message
      ▼
Telegram Bot API (webhook)
      │
      ▼
Lambda: telegram_webhook
      │ invoke_agent
      ▼
Bedrock Agent (same agent as web app, or separate)
      │ AgentCore Gateway → MCP server
      ▼
Response → Telegram message back to user

Alert system (separate):
EventBridge (hourly) → Lambda: alert_checker
      │ reads AirQualityReadings / PollenData
      │ compares against thresholds
      └── if threshold crossed → send Telegram message to subscribers
              └── subscriptions stored in DynamoDB: AlertSubscriptions table
```

**Required:**
- Uses Bedrock Agent + our MCP server
- Users can send messages and get city data answers
- Bot must be deployed (public webhook, not polling locally)
- Must use at least 2 of our MCP data tools

**Nice to have (if time allows):**
- `/subscribe airquality eixample` — user subscribes to threshold alerts for a neighbourhood
- `/subscribe pollen grass` — pollen alert when grass level hits "high"
- `/unsubscribe` and `/status` commands
- Alert system: hourly Lambda checks readings, sends Telegram messages to subscribers
- Formatted responses with emoji / markdown (Telegram supports it)

**For José to decide:**
- Which Bedrock model to use (Haiku for speed/cost, Sonnet for quality)
- Whether to use Bedrock Agents or raw `bedrock-runtime` with manual tool dispatch (simpler to start, agents are better long-term)
- Subscription storage schema (suggest: PK=`chat_id`, SK=`type#location`)

---

## Required vs nice-to-have (summary)

### Hard requirements (presentation must show these)
- [ ] At least one application uses **AWS Bedrock** (model invocation)
- [ ] At least one application uses **Bedrock Agents** or AgentCore (orchestration loop, not just raw API)
- [ ] Both apps connect to **our MCP server** as the data source
- [ ] Both apps are **deployed on AWS** (not running locally during demo)
- [ ] The web app **AI controls the map** (this is the key differentiator vs current demo)
- [ ] The Telegram bot **responds to messages** with real city data

### Strong nice-to-haves (do if time allows)
- [ ] Bedrock Knowledge Base (RAG) for static Barcelona info
- [ ] Telegram alert subscription system
- [ ] Bedrock Guardrails on one app
- [ ] Conversation memory / multi-turn context in Telegram bot
- [ ] Dashboard panel with auto-generated charts in web app

### Skip for now
- Noise data (Sentilo is dead)
- Auth / login on web app
- Mobile app

---

## Task breakdown

### Jakub — Web app + Bedrock Agent setup
1. **Set up Bedrock Agent** in AWS console (eu-west-1, Claude Sonnet 4.6)
   - Write the agent instruction prompt
   - Connect AgentCore Gateway to our MCP server endpoint
   - Test with `invoke_agent` from Python
2. **Rewrite web app** (new `app/` folder, not modifying `demo/`)
   - FastAPI backend: streams Bedrock Agent responses via WebSocket
   - Implement frontend map-control tool schema (the `place_pin`, `show_route` etc. tools)
   - Agent uses both MCP tools (city data) and map-control tools (UI updates)
3. **New Leaflet frontend** with chat panel + map + dashboard panel
4. **Deploy to AWS** (EC2 or ECS, public URL, behind a simple domain or raw IP)

### Mark — Air quality alerts + Bedrock integration polish
1. **DynamoDB AlertSubscriptions table** — schema for storing user subscriptions (chat_id, type, location, threshold)
2. **Alert checker Lambda** — runs hourly (piggyback on existing EventBridge), reads latest AirQualityReadings, compares against WHO thresholds, triggers notifications
3. **Polish air quality MCP tool** — add more stations, ensure descriptions are good for agent reasoning
4. **Help with Bedrock Agent instruction prompt** — the agent needs to know when to recommend staying indoors vs going out

### Jia — Web app dashboard + weather integration
1. **Dashboard panel** in the web app frontend — Chart.js charts rendered when agent calls `show_chart`
2. **Weather integration in web app** — ensure `get_weather` tool is prominent in the agent's reasoning for composite queries
3. **"Is today a good day to be outside?" composite workflow** — test and tune the agent prompt so it naturally calls weather + UV + pollen + air quality together
4. **Deployment support** — help with EC2/ECS setup and public domain

### José — Telegram bot
1. **Set up Telegram bot** via BotFather, get token
2. **Lambda: telegram_webhook** — handles incoming messages, calls Bedrock Agent, sends response back
3. **Connect to Bedrock Agent** — use the same agent Jakub sets up, or a separate lighter one (Haiku)
4. **Deploy webhook** (Lambda + API Gateway) — public HTTPS endpoint for Telegram to POST to
5. **Test with real queries** using our MCP tools
6. *(Nice to have)* Alert subscription commands (`/subscribe`, `/unsubscribe`, `/status`)
7. *(Nice to have)* AlertSubscriptions DynamoDB table + alert-checker Lambda integration

---

## Timeline (2 weeks to May 29)

| Days | Milestone |
|------|-----------|
| 1–2 | Bedrock Agent up, connected to MCP, responding via `invoke_agent` (Jakub) |
| 1–3 | Telegram bot responding to messages via Bedrock (José) |
| 3–5 | Web app: map + chat working, AI can drop pins and show routes (Jakub) |
| 3–5 | Dashboard panel working in web app (Jia) |
| 5–7 | Both apps deployed publicly on AWS |
| 7–10 | Alert system (Mark + José) |
| 10–12 | End-to-end demo rehearsal, edge case fixes |
| 12–14 | Presentation slides updated, final polish |

---

## Demo flow for final presentation

1. **Slide: what we built** — MCP server, 6 data types, live since May 2026
2. **Live: Telegram bot** — send a message live, show instant response with real data
3. **Live: web app** — type "Show me air quality near Eixample and mark it on the map" → pins appear in real time
4. **Live: composite query** — "Is it safe to go cycling in Barcelona this afternoon?" → agent calls weather + UV + air quality + Bicing, responds with map pins and a dashboard chart
5. **Slide: architecture** — data pipeline → Bedrock Agent → two apps
6. **Slide: Bedrock** — why AgentCore, what the orchestration loop does
7. **Q&A**

---

## Shared resources

- **MCP endpoint:** `https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp`
- **AWS account:** 539592518821, region eu-west-1
- **Bedrock model:** `eu.anthropic.claude-sonnet-4-6` (eu-west-1)
- **Repo:** `https://github.com/KubaDusza/barcelona-smart-city`
- **Credentials:** ask Jakub for AWS access keys
