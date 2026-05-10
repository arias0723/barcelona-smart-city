# Model Context Protocol (MCP)
## A Tutorial by Team 11 — Barcelona Smart City

**UPC CCBDA · Research Presentation · May 2026**

---

## Table of Contents

1. [The Problem MCP Solves](#1-the-problem-mcp-solves)
2. [What MCP Is](#2-what-mcp-is)
3. [How the Protocol Works](#3-how-the-protocol-works)
4. [MCP vs Alternatives](#4-mcp-vs-alternatives)
5. [Ecosystem and Adoption](#5-ecosystem-and-adoption)
6. [Our Project: Barcelona Smart City](#6-our-project-barcelona-smart-city)
7. [Live Demo: Connect to Our MCP Server](#7-live-demo-connect-to-our-mcp-server)
8. [Lessons Learned](#8-lessons-learned)
9. [Further Reading](#9-further-reading)

---

## 1. The Problem MCP Solves

Language models are impressive on their own — but they become truly useful when they can reach outside themselves: check live data, call APIs, query databases.

Before MCP, every team solved this differently:

```
Team A: Claude + custom tool loop → works only in their app
Team B: GPT + LangChain tools    → works only in LangChain
Team C: Gemini + Vertex AI tools → works only on Google Cloud
```

The result: **if you wanted your tools to work with multiple AI clients, you had to reimplement them for each one.** A Barcelona transit tool built for Claude would not work with ChatGPT or VS Code Copilot without rewriting it.

**OpenAI's function calling (June 2023)** solved half the problem: a standard format for the *LLM to describe which tool it wants to call*. But it only specified the format — not where the tool server lives, how to discover its capabilities, or how any AI client can connect to it.

**OpenAI's plugin system (2023)** tried to solve the server side, but was deprecated within months. Lesson: building a durable ecosystem is hard.

**MCP was Anthropic's answer (November 2024):** a full open protocol for the server side — how tool servers announce their capabilities, how clients connect to them, and how the same server can serve Claude, ChatGPT, VS Code, Cursor, and any future AI client without modification.

---

## 2. What MCP Is

**MCP (Model Context Protocol)** is an open standard protocol for connecting AI models to external tools and data sources.

The one-line description: **"USB-C for AI tools."** Just as USB-C lets any cable work with any device, MCP lets any tool server work with any AI client.

### The three roles

```
┌─────────────────────────────────────────────────────┐
│  MCP Host  (the AI application)                     │
│  e.g. Claude Desktop, claude.ai, VS Code, ChatGPT  │
│                                                     │
│  ┌────────────────────────────────────────────┐    │
│  │  MCP Client  (one connection manager       │    │
│  │               per server)                  │    │
│  └──────────────────┬─────────────────────────┘    │
└─────────────────────│───────────────────────────────┘
                       │  JSON-RPC 2.0
                       ▼
┌─────────────────────────────────────────────────────┐
│  MCP Server  (your code — exposes tools)            │
│  e.g. Barcelona Smart City, GitHub, Sentry, etc.   │
└─────────────────────────────────────────────────────┘
```

- **Host** — the application the user interacts with (Claude Desktop, ChatGPT, etc.)
- **Client** — manages the connection to one server; lives inside the host
- **Server** — your code; declares what tools it has, executes them when called

### The three primitives

MCP servers can expose three types of capabilities:

| Primitive | Who decides when to use it | What it is |
|-----------|---------------------------|------------|
| **Tools** | The LLM | Functions the model can call to take action or fetch data |
| **Resources** | The application | Read-only data the app loads as context |
| **Prompts** | The user | Reusable prompt templates with parameters |

For our project — and for most practical use cases — **Tools** are the key primitive.

---

## 3. How the Protocol Works

MCP uses **JSON-RPC 2.0** as its message format. Every interaction is a structured request/response pair.

### Transport options

| Transport | How it works | Best for |
|-----------|-------------|----------|
| **stdio** | Client spawns server as a subprocess; talks via stdin/stdout | Local dev, desktop apps |
| **HTTP (Streamable HTTP)** | Client sends POST requests to a URL; server responds | Production, remote servers, any user on the internet |

Our server uses **HTTP** — it runs on AWS Lambda + API Gateway, accessible via a public URL.

### The conversation flow

**Step 1 — Handshake:**
```json
// Client → Server
{
  "jsonrpc": "2.0", "id": 1, "method": "initialize",
  "params": {
    "protocolVersion": "2025-03-26",
    "clientInfo": { "name": "Claude Desktop", "version": "1.0" }
  }
}

// Server → Client
{
  "jsonrpc": "2.0", "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": { "tools": {} },
    "serverInfo": { "name": "Barcelona Smart City", "version": "1.0.0" }
  }
}
```

**Step 2 — Tool discovery:**
```json
// Client → Server
{ "jsonrpc": "2.0", "id": 2, "method": "tools/list" }

// Server → Client
{
  "jsonrpc": "2.0", "id": 2,
  "result": {
    "tools": [
      {
        "name": "get_bicing",
        "description": "Returns live Bicing bike-share station availability near a coordinate in Barcelona...",
        "inputSchema": {
          "type": "object",
          "properties": {
            "lat": { "type": "number", "description": "Latitude (WGS-84 decimal degrees)." },
            "lon": { "type": "number", "description": "Longitude (WGS-84 decimal degrees)." },
            "radius_m": { "type": "integer", "description": "Search radius in metres. Default 500." }
          },
          "required": ["lat", "lon"]
        }
      }
      // ... 6 more tools
    ]
  }
}
```

**Step 3 — Tool execution** (triggered by the LLM deciding to call a tool):
```json
// Client → Server
{
  "jsonrpc": "2.0", "id": 3, "method": "tools/call",
  "params": {
    "name": "get_bicing",
    "arguments": { "lat": 41.4036, "lon": 2.1744, "radius_m": 400 }
  }
}

// Server → Client
{
  "jsonrpc": "2.0", "id": 3,
  "result": {
    "content": [{
      "type": "text",
      "text": "{\"stations_found\": 5, \"stations\": [{\"name\": \"C/ SARDENYA, 326\", \"distance_m\": 131, \"bikes_available\": 2, \"ebikes\": 1, ...}]}"
    }],
    "isError": false
  }
}
```

The client passes this result back to the LLM, which then incorporates it into its response to the user.

### The key insight

**MCP and function calling are complementary layers, not alternatives:**

- **Function calling** — tells the LLM *which tool* to call and with what arguments (LLM-side, part of the model API)
- **MCP** — tells the client *where the tool server is*, how to discover its tools, and how to call them (infrastructure-side)

You need both for a complete system.

---

## 4. MCP vs Alternatives

### Before MCP — the fragmented landscape

| Approach | Year | What it did | Limitation |
|----------|------|-------------|------------|
| OpenAI function calling | 2023 | LLM declares which tool to call | Only the LLM-side; no server protocol |
| OpenAI Plugins | 2023 | ChatGPT-specific tool servers via OpenAPI | Deprecated within months; not portable |
| LangChain tools | 2022–present | Tool abstraction within LangChain | Framework-specific; not portable |
| LlamaIndex connectors | 2022–present | Data connectors within LlamaIndex | Framework-specific; not portable |
| AWS Bedrock Agents | 2023–present | Managed agent orchestration on AWS | Cloud-specific; AWS lock-in |

### MCP vs Bedrock Agents

A useful comparison since both relate to our project:

| | MCP | AWS Bedrock Agents |
|---|---|---|
| **What it is** | Open protocol | Managed AWS service |
| **Who runs the loop** | Your code (the host) | AWS infrastructure |
| **Portability** | Any MCP-compatible client | AWS only |
| **Complexity** | Lower (just an API endpoint) | Higher (action groups, OpenAPI schemas, knowledge bases) |
| **Cost** | Pay for your own compute | AWS managed pricing |
| **Best for** | Tools you want to share across AI clients | Fully managed agent workflows on AWS |

Our project deliberately chose MCP because portability was a goal — we wanted the same tools to work in Claude, ChatGPT, and our web demo.

### Is MCP "state of the art"?

**Yes — for the specific problem of open, portable tool integration.** Signals:
- OpenAI adopted MCP for ChatGPT rather than building a competing standard
- Google announced Gemini CLI MCP support
- 85,000+ GitHub stars, 31,000+ repositories tagged MCP (as of May 2026)
- 200+ client applications support it

**Honest caveats:**
- The spec is still evolving (Resources and Prompts are less universally implemented than Tools)
- Security is advisory, not enforced at protocol level — trust what you connect to
- Stateful session management adds complexity for Lambda/serverless deployments (we addressed this by implementing stateless JSON-RPC directly)

---

## 5. Ecosystem and Adoption

### Official MCP servers from major companies

| Company | What they exposed |
|---------|------------------|
| GitHub | Repository operations, issues, PRs |
| Sentry | Error tracking and issue management |
| Anthropic | Filesystem, Brave Search, memory |
| Google | Gemini integration |
| AWS | Amazon Q integration |

### Clients that support MCP

Claude Desktop · Claude Code · claude.ai · ChatGPT · VS Code (Copilot) · Cursor · JetBrains IDEs · Windsurf · Amazon Q · Replit · Vercel v0

### The ecosystem flywheel

```
More clients → more incentive to build servers
More servers → more reason for clients to support MCP
```

This is why OpenAI's adoption was the tipping point: it turned MCP from "an Anthropic protocol" to "the cross-vendor standard."

---

## 6. Our Project: Barcelona Smart City

### Architecture

```
Data Sources               AWS (eu-west-1)              MCP Server          AI Clients
────────────               ───────────────              ──────────          ──────────
citybik.es ──► Lambda ──► BicingStations ──────────►│                   claude.ai
               (5 min)                               │  Lambda            ChatGPT
                                                     │  + API Gateway     Claude Desktop
Open Data BCN ► Lambda ──► AirQualityReadings ──────►│                   VS Code
               (1 hr)                                │  mcp_server.py     Web demo
                                                     │  (7 MCP tools)
Open-Meteo ──► Lambda ──► WeatherData ──────────────►│
               (1 hr)
                                                     │
Transitous API ──────────────────────────────────────►│ (on-demand)
(transit routing)
```

### Data pipeline

Three AWS Lambda functions run on EventBridge schedules:

| Lambda | Schedule | Data source | DynamoDB table |
|--------|----------|-------------|----------------|
| `smart-city-bicing-ingest` | Every 5 min | citybik.es (543 stations) | `BicingStations` |
| `smart-city-air-quality-ingest` | Every 1 hour | Open Data BCN XVPCA network | `AirQualityReadings` |
| `smart-city-weather-ingest` | Every 1 hour | Open-Meteo API | `WeatherData` |

All tables use 30-day TTL, so historical queries go back up to a month.

### The MCP server

`mcp_server.py` exposes 7 tools over HTTP (AWS Lambda + API Gateway):

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Barcelona Smart City")

@mcp.tool()
def get_bicing(lat: float, lon: float, radius_m: int = 500) -> dict:
    """Returns live Bicing bike-share station availability near a coordinate."""
    ...

@mcp.tool()
def get_bicing_history(station_id: str, hours_back: int = 24) -> dict:
    """Returns historical Bicing snapshots — up to 30 days, every 5 minutes."""
    ...

@mcp.tool()
def get_transit_nearby(lat: float, lon: float, radius_m: int = 400) -> dict:
    """Returns nearby TMB metro and bus stops from DynamoDB."""
    ...

@mcp.tool()
def get_transit_route(origin_lat, origin_lon, dest_lat, dest_lon) -> dict:
    """A→B transit routing via Transitous open router."""
    ...

@mcp.tool()
def get_air_quality(lat: float, lon: float) -> dict:
    """Latest NO2/PM10/O3/CO from nearest XVPCA monitoring station."""
    ...

@mcp.tool()
def get_air_quality_history(station_name: str, pollutant: str, hours_back: int = 48) -> dict:
    """Historical hourly air quality — up to 30 days."""
    ...

@mcp.tool()
def get_weather() -> dict:
    """Current Barcelona weather from Open-Meteo via DynamoDB."""
    ...
```

### Tool description quality matters

The `description` field is what the LLM reads to decide *when* and *how* to call a tool. A vague description leads to wrong tool selection. Compare:

```python
# Bad — LLM doesn't know when to use this
description = "Gets bikes"

# Good — LLM knows exactly when and how
description = (
    "Returns live Bicing bike-share station availability near a coordinate in Barcelona. "
    "Use when the user asks about renting a bike, finding a Bicing station, or checking "
    "bike/dock availability. Includes mechanical and electric bike counts."
)
```

This is a key lesson: **tool descriptions are prompts for the orchestrating LLM**, not documentation for humans.

### Lambda + API Gateway: why this works

MCP's streamable HTTP transport is request-response for tool calls — the client sends a POST, the server responds with JSON. Lambda is ideal: zero infrastructure, pay-per-request, automatic HTTPS via API Gateway.

One nuance: FastMCP's built-in `streamable_http_app()` uses a persistent async task group (for streaming support) that Lambda can't host. Our solution: implement the MCP JSON-RPC protocol directly as a stateless handler — no session state needed for pure tool calls.

```python
def handler(event, context):           # Lambda entry point
    body = json.loads(event["body"])
    method = body["method"]

    if method == "initialize":
        return respond({"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, ...})

    if method == "tools/list":
        return respond({"tools": [...]})

    if method == "tools/call":
        result = _TOOL_FN[body["params"]["name"]](**body["params"]["arguments"])
        return respond({"content": [{"type": "text", "text": json.dumps(result)}]})
```

Cost: **$0** (well within AWS free tier — Lambda free tier covers 1M requests/month; we expect ~1000/month).

---

## 7. Live Demo: Connect to Our MCP Server

Our MCP server is running at:

```
https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp
```

### Connect from claude.ai

1. Go to **claude.ai** → Settings → **Integrations**
2. Click **Add integration**
3. Paste the URL above
4. Done — Claude now has access to live Barcelona city data

### Connect from Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "barcelona-smart-city": {
      "url": "https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp"
    }
  }
}
```

Restart Claude Desktop.

### Things to ask Claude after connecting

```
"Are there Bicing bikes near Sagrada Família right now?"
"How do I get from Plaça Catalunya to Barceloneta by metro?"
"What's the air quality like in Eixample today? Is it safe to go for a run?"
"What's the weather in Barcelona right now?"
"Which Barcelona district has the worst NO2 levels?"
"Show me the Bicing availability trend for station 119 over the last 24 hours."
```

### Test the protocol manually

```bash
# Step 1: Initialize
curl -X POST https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# Step 2: List tools
curl -X POST https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Step 3: Call a tool
curl -X POST https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
    "params": {
      "name": "get_bicing",
      "arguments": { "lat": 41.4036, "lon": 2.1744, "radius_m": 400 }
    }
  }'
```

---

## 8. Lessons Learned

**1. Tool descriptions are the hardest part.**
The code is easy. Writing descriptions that reliably guide the LLM to the right tool at the right time — that requires iteration. A description that's too short leads to the wrong tool being called; too long and it gets ignored.

**2. Stateless JSON-RPC works better than Starlette on Lambda.**
FastMCP's default app requires a persistent async task group for streaming. Lambda is request-response. Implementing the MCP wire protocol directly (30 lines of code) was simpler and more reliable than adapting an ASGI framework to Lambda's constraints.

**3. Lambda + API Gateway is the right serverless MCP deployment.**
App Runner (containers) and EC2 are overengineered for a stateless tool server. Lambda scales to zero, costs nothing at our request volumes, and gets automatic HTTPS from API Gateway. Total operational overhead: zero.

**4. `--platform manylinux2014_x86_64` matters.**
Python packages with compiled C extensions (like `pydantic-core`) built on macOS won't run on Linux Lambda. Always cross-compile when building Lambda packages on a non-Linux machine.

**5. Data source reliability is a real concern.**
The original Barcelona Bicing API (BSM) was blocked with error 700700 when we tried to use it. Having a fallback source (citybik.es) was essential. For production systems, always have a plan B for third-party APIs.

**6. MCP's value is portability, not just convenience.**
Our web demo (Claude Haiku via AWS Bedrock) and our MCP server are independent — the tools are implemented once and exposed two ways. Any future AI client can use our data without us writing any new code.

---

## 9. Further Reading

| Resource | What it covers |
|----------|---------------|
| [modelcontextprotocol.io](https://modelcontextprotocol.io) | Official MCP docs, spec, quickstarts |
| [MCP GitHub](https://github.com/modelcontextprotocol) | SDKs (Python, TypeScript, Java, Kotlin, C#), reference servers |
| [FastMCP docs](https://github.com/jlowin/fastmcp) | Python library we used — decorator-based server authorship |
| [Anthropic tool use docs](https://docs.anthropic.com/en/docs/build-with-claude/tool-use) | How Claude's native tool use works (the LLM side) |
| [AWS Lambda + API Gateway](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway.html) | How we deployed the MCP server |

---

*Barcelona Smart City MCP server: `https://9llxtl8mm3.execute-api.eu-west-1.amazonaws.com/mcp`*

*Team 11: Jakub Dusza · Mark Welf Atzberger · Jia Lyu · Jose Ricardo Arias Perez*
