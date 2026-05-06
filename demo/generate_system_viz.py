"""
generate_system_viz.py
======================
Queries live DynamoDB data and generates a standalone HTML visualization.
Run: python3 demo/generate_system_viz.py
Opens: demo/system_status.html in your browser
"""

import json
import os
import sys
import webbrowser
from decimal import Decimal
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

REGION   = os.environ.get("AWS_REGION", "eu-west-1")
OUT_FILE = os.path.join(os.path.dirname(__file__), "system_status.html")

dynamodb = boto3.resource("dynamodb", region_name=REGION)

# WHO thresholds for NO2 (µg/m³)
def aq_status(pollutant: str, value: float) -> tuple[str, str]:
    thresholds = {
        "NO2":  [(25, "good", "#22c55e"), (50, "moderate", "#eab308"), (100, "poor", "#f97316"), (999, "very poor", "#ef4444")],
        "PM10": [(45, "good", "#22c55e"), (90, "moderate", "#eab308"), (150, "poor", "#f97316"), (999, "very poor", "#ef4444")],
        "O3":   [(100, "good", "#22c55e"), (160, "moderate", "#eab308"), (240, "poor", "#f97316"), (999, "very poor", "#ef4444")],
        "CO":   [(4,  "good", "#22c55e"), (8,   "moderate", "#eab308"), (15,  "poor", "#f97316"), (999, "very poor", "#ef4444")],
    }
    levels = thresholds.get(pollutant, [(999, "ok", "#22c55e")])
    for threshold, label, color in levels:
        if value <= threshold:
            return label, color
    return "very poor", "#ef4444"


def fetch_air_quality() -> list[dict]:
    table = dynamodb.Table("AirQualityReadings")
    stations = {
        4:  {"name": "Poblenou",         "lat": 41.4039,  "lon": 2.2045},
        42: {"name": "Sants",            "lat": 41.3788,  "lon": 2.1331},
        43: {"name": "Eixample",         "lat": 41.3853,  "lon": 2.1538},
        44: {"name": "Gràcia",           "lat": 41.3987,  "lon": 2.1534},
        50: {"name": "Ciutadella",       "lat": 41.3864,  "lon": 2.1874},
        54: {"name": "Vall Hebron",      "lat": 41.4261,  "lon": 2.1480},
        57: {"name": "Palau Reial",      "lat": 41.3875,  "lon": 2.1151},
        58: {"name": "Observatori Fabra","lat": 41.41843, "lon": 2.12390},
        60: {"name": "Navas",            "lat": 41.4159,  "lon": 2.1871},
    }
    pollutants = ["NO2", "PM10", "O3", "CO"]
    results = []

    for sid, sinfo in stations.items():
        readings = []
        for p in pollutants:
            pk = f"{sid}_{p}"
            resp = table.query(
                KeyConditionExpression=Key("station_pollutant").eq(pk),
                ScanIndexForward=False,
                Limit=1,
            )
            if resp["Items"]:
                item = resp["Items"][0]
                val = float(item["value"])
                unit = item.get("unit", "µg/m³")
                label, color = aq_status(p, val)
                hour_ts = str(item.get("hour_ts", ""))
                hour_fmt = f"{hour_ts[8:10]}:00" if len(hour_ts) >= 10 else "?"
                readings.append({
                    "pollutant": p,
                    "value": round(val, 1),
                    "unit": unit,
                    "status": label,
                    "color": color,
                    "hour": hour_fmt,
                })

        # Overall status = worst reading
        worst_color = "#22c55e"
        worst_label = "good"
        priority = {"very poor": 3, "poor": 2, "moderate": 1, "good": 0, "ok": 0}
        for r in readings:
            if priority.get(r["status"], 0) > priority.get(worst_label, 0):
                worst_label = r["status"]
                worst_color = r["color"]

        results.append({
            **sinfo,
            "station_id": sid,
            "readings": readings,
            "overall_status": worst_label,
            "overall_color": worst_color,
        })

    return results


def fetch_transit_stops(limit_metro=100, limit_bus=60) -> list[dict]:
    from boto3.dynamodb.conditions import Attr
    table      = dynamodb.Table("TransitStops")
    metro_stops = []
    bus_stops   = []

    # Scan full table for metro stops (3,453 items, no cost concern)
    last_key = None
    while len(metro_stops) < limit_metro:
        kwargs = {"FilterExpression": Attr("primary_mode").eq("metro")}
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp     = table.scan(**kwargs)
        for item in resp.get("Items", []):
            metro_stops.append({
                "stop_id": item["stop_id"],
                "name":    item.get("stop_name", ""),
                "lat":     float(item["stop_lat"]),
                "lon":     float(item["stop_lon"]),
                "modes":   list(item.get("modes", set())),
                "routes":  sorted(list(item.get("route_names", [])))[:5],
            })
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    # Bus stops — scan with lon range filter to get city-wide coverage
    from boto3.dynamodb.conditions import Attr
    last_key = None
    while len(bus_stops) < limit_bus:
        kwargs = {
            "FilterExpression": (
                Attr("primary_mode").eq("bus") &
                Attr("stop_lon").between(Decimal("2.09"), Decimal("2.23")) &
                Attr("stop_lat").between(Decimal("41.33"), Decimal("41.47"))
            )
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.scan(**kwargs)
        for item in resp.get("Items", []):
            modes = list(item.get("modes", set()))
            bus_stops.append({
                "stop_id": item["stop_id"],
                "name":    item.get("stop_name", ""),
                "lat":     float(item["stop_lat"]),
                "lon":     float(item["stop_lon"]),
                "modes":   modes,
                "routes":  sorted(list(item.get("route_names", [])))[:5],
            })
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    return metro_stops, bus_stops


def fetch_table_stats() -> dict:
    client = boto3.client("dynamodb", region_name=REGION)
    stats = {}
    for name in ["BicingStations", "TransitStops", "ScheduleCache",
                  "AirQualityReadings", "WeatherData", "NoiseData"]:
        try:
            meta = client.describe_table(TableName=name)["Table"]
            stats[name] = {
                "status": meta["TableStatus"],
                "items": meta.get("ItemCount", 0),
            }
        except Exception:
            stats[name] = {"status": "NOT_FOUND", "items": 0}
    return stats


def generate_html(aq_data, metro_stops, bus_stops, table_stats) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Serialize for JS
    aq_js      = json.dumps(aq_data,     default=str)
    metro_js   = json.dumps(metro_stops, default=str)
    bus_js     = json.dumps(bus_stops,   default=str)

    # Table stats rows
    status_rows = ""
    table_labels = {
        "BicingStations":    ("🚲", "Bicing Stations",   "Jakub", "Every 5 min"),
        "TransitStops":      ("🚇", "Transit Stops",     "Jakub", "On GTFS update"),
        "ScheduleCache":     ("📅", "Schedule Cache",    "Jakub", "On GTFS update"),
        "AirQualityReadings":("💨", "Air Quality",       "Mark",  "Every 1 hr"),
        "WeatherData":       ("⛅", "Weather",           "Jia",   "Pending"),
        "NoiseData":         ("🔊", "Noise",             "Jose",  "Pending"),
    }
    for tname, (icon, label, owner, cadence) in table_labels.items():
        s = table_stats.get(tname, {})
        ok = s.get("status") == "ACTIVE"
        dot_color = "#22c55e" if ok else "#ef4444"
        items = s.get("items", 0)
        pending = cadence == "Pending"
        row_style = "opacity:0.5;" if pending else ""
        status_rows += f"""
        <tr style="{row_style}">
          <td><span style="color:{dot_color};font-size:10px;">●</span> {icon} {label}</td>
          <td style="color:#94a3b8;">{owner}</td>
          <td style="text-align:right;font-family:monospace;">{items:,}</td>
          <td style="color:#94a3b8;">{cadence}</td>
        </tr>"""

    # Air quality summary cards
    aq_cards = ""
    for s in aq_data:
        readings_html = ""
        for r in s["readings"]:
            readings_html += f"""
            <div class="aq-row">
              <span class="aq-label">{r['pollutant']}</span>
              <span class="aq-val">{r['value']}<span style="color:#475569;font-size:9px;"> {r['unit']}</span></span>
              <span style="color:{r['color']};font-size:10px;">{r['status']}</span>
            </div>"""
        aq_cards += f"""
        <div class="aq-card" style="border-left-color:{s['overall_color']};">
          <div class="aq-card-title">
            <span><span style="color:{s['overall_color']};">●</span> {s['name']}</span>
            <span style="font-size:10px;font-weight:400;color:{s['overall_color']};">{s['overall_status']}</span>
          </div>
          {readings_html}
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smart City BCN — System Status</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #0f172a; color: #e2e8f0; height: 100vh; display: flex; flex-direction: column; }}
  header {{ background: #1e293b; padding: 12px 20px; border-bottom: 1px solid #334155;
            display: flex; align-items: center; gap: 12px; flex-shrink: 0; }}
  header h1 {{ font-size: 15px; font-weight: 700; color: #f8fafc; }}
  .badge {{ background: #0ea5e9; color: white; font-size: 11px; padding: 2px 8px;
             border-radius: 999px; font-weight: 600; }}
  .ts {{ font-size: 11px; color: #64748b; margin-left: auto; }}
  .main {{ display: flex; flex: 1; overflow: hidden; }}
  #map {{ flex: 1; }}
  .sidebar {{ width: 300px; background: #0f172a; overflow-y: auto; border-left: 1px solid #1e293b;
              flex-shrink: 0; }}

  /* Layer section */
  .layer-section {{ border-bottom: 1px solid #1e293b; }}
  .layer-header {{
    display: flex; align-items: center; gap: 8px;
    padding: 10px 14px; cursor: pointer; user-select: none;
    background: #0f172a; transition: background .15s;
  }}
  .layer-header:hover {{ background: #1a2540; }}
  .layer-icon {{ font-size: 14px; width: 18px; text-align: center; }}
  .layer-title {{ font-size: 12px; font-weight: 600; flex: 1; }}
  .layer-count {{ font-size: 10px; color: #475569; margin-right: 4px; }}
  .chevron {{ font-size: 10px; color: #475569; transition: transform .2s; margin-right: 4px; }}
  .layer-section.collapsed .chevron {{ transform: rotate(-90deg); }}

  /* Toggle switch */
  .toggle {{ position: relative; width: 32px; height: 18px; flex-shrink: 0; }}
  .toggle input {{ opacity: 0; width: 0; height: 0; }}
  .toggle-track {{
    position: absolute; inset: 0; border-radius: 999px;
    background: #334155; transition: background .2s; cursor: pointer;
  }}
  .toggle-track::after {{
    content: ''; position: absolute; top: 2px; left: 2px;
    width: 14px; height: 14px; border-radius: 50%;
    background: #64748b; transition: transform .2s, background .2s;
  }}
  .toggle input:checked + .toggle-track {{ background: #0ea5e9; }}
  .toggle input:checked + .toggle-track::after {{ transform: translateX(14px); background: #fff; }}

  /* Layer body */
  .layer-body {{ padding: 0 14px 12px; overflow: hidden; }}
  .layer-section.collapsed .layer-body {{ display: none; }}

  /* AQ cards */
  .aq-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px; padding-top: 4px; }}
  .aq-card {{ background: #1e293b; border-radius: 7px; padding: 9px 10px; border-left: 3px solid #334155; }}
  .aq-card-title {{ font-size: 11px; font-weight: 700; margin-bottom: 5px;
                    display: flex; justify-content: space-between; align-items: center; }}
  .aq-row {{ display: flex; justify-content: space-between; padding: 1px 0;
              border-bottom: 1px solid #0f172a; font-size: 11px; }}
  .aq-label {{ color: #64748b; }}
  .aq-val {{ font-family: monospace; }}

  /* Infra table */
  .infra-table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-top: 4px; }}
  .infra-table td {{ padding: 4px 3px; border-bottom: 1px solid #1e293b; }}
  .infra-note {{ font-size: 10px; color: #475569; margin-top: 5px; }}

  /* Leaflet popups */
  .leaflet-popup-content-wrapper {{ background: #1e293b; color: #e2e8f0; border: 1px solid #334155; border-radius: 8px !important; }}
  .leaflet-popup-tip {{ background: #1e293b; }}
  .popup-title {{ font-weight: 700; margin-bottom: 6px; font-size: 13px; }}
  .popup-row {{ display: flex; justify-content: space-between; font-size: 11px;
                 padding: 2px 0; border-bottom: 1px solid #334155; gap: 12px; }}
</style>
</head>
<body>

<header>
  <h1>🏙️ Smart City Barcelona</h1>
  <span class="badge">LIVE</span>
  <span class="ts">Generated: {now_str}</span>
</header>

<div class="main">
  <div id="map"></div>

  <div class="sidebar">

    <!-- AIR QUALITY LAYER -->
    <div class="layer-section" id="sec-aq">
      <div class="layer-header" onclick="toggleSection('aq')">
        <span class="layer-icon">💨</span>
        <span class="layer-title">Air Quality</span>
        <span class="layer-count" id="count-aq">9 stations</span>
        <span class="chevron" id="chev-aq">▼</span>
        <label class="toggle" onclick="event.stopPropagation()">
          <input type="checkbox" id="tog-aq" checked onchange="toggleLayer('aq', this.checked)">
          <span class="toggle-track"></span>
        </label>
      </div>
      <div class="layer-body" id="body-aq">
        <div class="aq-grid">
          {aq_cards}
        </div>
      </div>
    </div>

    <!-- METRO LAYER -->
    <div class="layer-section" id="sec-metro">
      <div class="layer-header" onclick="toggleSection('metro')">
        <span class="layer-icon">🚇</span>
        <span class="layer-title">Metro Stops</span>
        <span class="layer-count" id="count-metro">{len(metro_stops)} stops</span>
        <span class="chevron" id="chev-metro">▼</span>
        <label class="toggle" onclick="event.stopPropagation()">
          <input type="checkbox" id="tog-metro" checked onchange="toggleLayer('metro', this.checked)">
          <span class="toggle-track"></span>
        </label>
      </div>
      <div class="layer-body" id="body-metro">
        <div style="font-size:11px;color:#64748b;padding-top:4px;">
          All TMB metro stations (L1–L10, L11).<br>
          GTFS feed valid to 2026-12-16.
        </div>
      </div>
    </div>

    <!-- BUS LAYER -->
    <div class="layer-section" id="sec-bus">
      <div class="layer-header" onclick="toggleSection('bus')">
        <span class="layer-icon">🚌</span>
        <span class="layer-title">Bus Stops</span>
        <span class="layer-count" id="count-bus">{len(bus_stops)} stops</span>
        <span class="chevron" id="chev-bus">▼</span>
        <label class="toggle" onclick="event.stopPropagation()">
          <input type="checkbox" id="tog-bus" checked onchange="toggleLayer('bus', this.checked)">
          <span class="toggle-track"></span>
        </label>
      </div>
      <div class="layer-body" id="body-bus">
        <div style="font-size:11px;color:#64748b;padding-top:4px;">
          TMB bus network across Barcelona city.<br>
          106 bus routes · GTFS static feed.
        </div>
      </div>
    </div>

    <!-- INFRASTRUCTURE LAYER -->
    <div class="layer-section" id="sec-infra">
      <div class="layer-header" onclick="toggleSection('infra')">
        <span class="layer-icon">☁️</span>
        <span class="layer-title">Infrastructure</span>
        <span class="layer-count">AWS · eu-west-1</span>
        <span class="chevron" id="chev-infra">▼</span>
      </div>
      <div class="layer-body" id="body-infra">
        <table class="infra-table">
          <tr style="color:#475569;">
            <th style="text-align:left;">Table</th>
            <th style="text-align:left;">Owner</th>
            <th style="text-align:right;">Items*</th>
            <th style="text-align:left;padding-left:6px;">Cadence</th>
          </tr>
          {status_rows}
        </table>
        <div class="infra-note">* DynamoDB item count lags ~6h</div>
      </div>
    </div>

  </div>
</div>

<script>
const aqData     = {aq_js};
const metroStops = {metro_js};
const busStops   = {bus_js};

// ── Map ──────────────────────────────────────────────────────────
const map = L.map('map', {{ zoomControl: true }}).setView([41.3903, 2.1547], 13);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '© OpenStreetMap contributors © CARTO', maxZoom: 19
}}).addTo(map);

// ── Layer groups ──────────────────────────────────────────────────
const layers = {{
  aq:    L.layerGroup().addTo(map),
  metro: L.layerGroup().addTo(map),
  bus:   L.layerGroup().addTo(map),
}};

// ── Bus stops ─────────────────────────────────────────────────────
busStops.forEach(s => {{
  L.circleMarker([s.lat, s.lon], {{
    radius: 3, color: '#64748b', fillColor: '#64748b', fillOpacity: 0.7, weight: 1
  }})
  .bindPopup(`<div class="popup-title">🚌 ${{s.name}}</div>
    <div class="popup-row"><span>Routes</span><span>${{s.routes.join(', ') || '—'}}</span></div>`)
  .addTo(layers.bus);
}});

// ── Metro stops ───────────────────────────────────────────────────
metroStops.forEach(s => {{
  L.circleMarker([s.lat, s.lon], {{
    radius: 5, color: '#6366f1', fillColor: '#818cf8', fillOpacity: 0.9, weight: 1
  }})
  .bindPopup(`<div class="popup-title">🚇 ${{s.name}}</div>
    <div class="popup-row"><span>Lines</span><span>${{s.routes.join(', ') || '—'}}</span></div>`)
  .addTo(layers.metro);
}});

// ── Air quality stations ──────────────────────────────────────────
aqData.forEach(s => {{
  const readings = s.readings.map(r =>
    `<div class="popup-row"><span>${{r.pollutant}}</span>
     <span>${{r.value}} ${{r.unit}} &nbsp;<span style="color:${{r.color}}">(${{r.status}})</span></span></div>`
  ).join('');
  const popup = `<div class="popup-title" style="color:${{s.overall_color}};">💨 ${{s.name}}</div>
    ${{readings}}
    <div style="font-size:10px;color:#64748b;margin-top:4px;">Station ID: ${{s.station_id}}</div>`;

  L.circleMarker([s.lat, s.lon], {{
    radius: 18, color: s.overall_color, fillColor: s.overall_color, fillOpacity: 0.2, weight: 2.5
  }}).bindPopup(popup).addTo(layers.aq);

  L.circleMarker([s.lat, s.lon], {{
    radius: 6, color: s.overall_color, fillColor: s.overall_color, fillOpacity: 1, weight: 2
  }}).bindPopup(popup).addTo(layers.aq);
}});

// ── Toggle layer on/off ───────────────────────────────────────────
function toggleLayer(id, visible) {{
  if (visible) {{
    map.addLayer(layers[id]);
  }} else {{
    map.removeLayer(layers[id]);
  }}
}}

// ── Collapse/expand sidebar section ──────────────────────────────
function toggleSection(id) {{
  const sec  = document.getElementById('sec-' + id);
  const chev = document.getElementById('chev-' + id);
  const tog  = document.getElementById('tog-' + id);
  if (!sec) return;
  const collapsed = sec.classList.toggle('collapsed');
  // If collapsing while layer is on → turn off toggle visually but keep layer
  // (collapse = hide sidebar content only; toggle = hide map layer)
}}
</script>
</body>
</html>"""


def main():
    print("Querying DynamoDB...")
    print("  → Air quality readings...")
    aq_data = fetch_air_quality()
    print(f"    {len(aq_data)} stations, {sum(len(s['readings']) for s in aq_data)} readings")

    print("  → Transit stops...")
    metro_stops, bus_stops = fetch_transit_stops()
    print(f"    {len(metro_stops)} metro stops, {len(bus_stops)} bus stops")

    print("  → Table stats...")
    table_stats = fetch_table_stats()

    print("Generating HTML...")
    html = generate_html(aq_data, metro_stops, bus_stops, table_stats)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Opening: {OUT_FILE}")
    webbrowser.open(f"file://{OUT_FILE}")


if __name__ == "__main__":
    main()
