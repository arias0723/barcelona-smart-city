# Air Quality Vertical — Mark Welf Atzberger

## Status: Lambda deployed, data flowing ✅

Your Lambda (`smart-city-air-quality-ingest`) is already running every hour.
Data is already in `AirQualityReadings`. Your job this week: write the MCP tool.

---

## Data source

**Open Data BCN — Air Quality Readings**
- URL: https://opendata-ajuntament.barcelona.cat/data/en/dataset/qualitat-aire-detall-bcn
- API: CKAN datastore (JSON, no key needed)
- Resource ID: `c2032e7c-10ee-4c69-84d3-9e8caf9ca97a`
- Update frequency: hourly
- Coverage: 4 stations in Barcelona (Poblenou, Sants, Eixample, Gràcia)
- Pollutants: NO2, PM10, O3, CO, SO2, NOX (not all stations measure all)

## Monitoring stations

| Station ID | Name | Lat | Lon | District |
|---|---|---|---|---|
| 4 | Poblenou | 41.4039 | 2.2045 | Sant Martí |
| 42 | Sants | 41.3788 | 2.1331 | Sants-Montjuïc |
| 43 | Eixample | 41.3853 | 2.1538 | Eixample |
| 44 | Gràcia | 41.3987 | 2.1534 | Gràcia |

## WHO air quality thresholds (for context in MCP tool responses)

| Pollutant | Safe (24h avg) | Unit |
|---|---|---|
| NO2 | < 25 µg/m³ | µg/m³ |
| PM10 | < 45 µg/m³ | µg/m³ |
| O3 | < 100 µg/m³ | µg/m³ |
| CO | < 4 mg/m³ | mg/m³ |

---

## DynamoDB table: AirQualityReadings

```
PK: station_pollutant (S)  — "43_NO2"
SK: hour_ts (S)            — "2026042714"  (YYYYMMDDHH)
TTL: ttl                   — 48 hours

Fields per item:
  station_id (N)         4, 42, 43, or 44
  station_name (S)       "Eixample"
  district (S)           "Eixample"
  lat, lon (N)           41.3853, 2.1538
  lat_bucket (S)         "41.39"
  pollutant_name (S)     "NO2"
  pollutant_code (N)     8
  unit (S)               "µg/m³"
  value (N)              e.g. 18.4
  validated (BOOL)       true if V flag = 'V'
  recorded_at (N)        Unix timestamp

GSI: LatBucketIndex
  lat_bucket (S) + hour_ts (S)
  → use to find all readings near a given lat/lon
```

### Sample query — latest NO2 at Eixample
```python
import boto3
from boto3.dynamodb.conditions import Key

table = boto3.resource("dynamodb", region_name="eu-west-1").Table("AirQualityReadings")
result = table.query(
    KeyConditionExpression=Key("station_pollutant").eq("43_NO2"),
    ScanIndexForward=False,
    Limit=1,
)
latest = result["Items"][0] if result["Items"] else None
```

---

## Your task: write the MCP tool

Create `aws/lambdas/air_quality_mcp/lambda_function.py` with this tool signature:

```python
def get_air_quality(lat: float, lon: float, pollutants: list[str] = None) -> dict:
    """
    Returns the latest validated air quality readings from the nearest
    monitoring station(s) to the given coordinates.

    Args:
        lat, lon: WGS-84 coordinates of the point of interest
        pollutants: list of pollutant names to include (default: all)
                    options: ["NO2", "PM10", "O3", "CO", "SO2", "NOX"]

    Returns:
        {
          "nearest_station": "Eixample",
          "distance_m": 450,
          "readings": [
            {"pollutant": "NO2", "value": 18.4, "unit": "µg/m³",
             "hour": "2026042714", "status": "good"},
            ...
          ],
          "health_note": "Air quality is good. Safe for outdoor activity."
        }
    """
```

Steps:
1. Find the nearest station using haversine distance (they're hardcoded, no DB query needed)
2. Query `AirQualityReadings` for `station_id_{pollutant}` sorted by `hour_ts` desc, limit 1
3. Add WHO-based health labels: "good" / "moderate" / "poor" / "very poor"
4. Return structured dict

The health label logic makes the MCP tool useful for the demo's health-aware routing feature.
