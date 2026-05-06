# Weather Vertical — Jia Lyu

## Status: Table ready, Lambda needed ⏳

The `WeatherData` DynamoDB table is already created. Your job this week:
1. Write the Lambda ingestion function
2. Deploy it
3. Verify data is flowing

---

## Recommended data sources

### Option A: Open-Meteo (recommended — no API key needed)
- URL: https://api.open-meteo.com/v1/forecast
- Free, no key, JSON, updated hourly
- Barcelona coordinates: lat=41.3851, lon=2.1734

Example call:
```bash
curl "https://api.open-meteo.com/v1/forecast?latitude=41.3851&longitude=2.1734&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code&hourly=temperature_2m,precipitation_probability&timezone=Europe/Madrid&forecast_days=1"
```

### Option B: Meteocat (official Catalan weather service)
- Requires API key from: https://apidocs.meteocat.gencat.cat/
- More stations in Catalonia, more precise for BCN

---

## DynamoDB table: WeatherData

The table was created with this basic schema. You can extend it:

```
PK: station_id (S)    — e.g. "barcelona_center"  (or lat_lon bucket)
SK: timestamp (N)     — Unix epoch
TTL: ttl (N)          — expires 48 hours after write

Suggested fields to add:
  lat, lon (N)
  temperature_c (N)
  humidity_pct (N)
  wind_speed_ms (N)
  precipitation_mm (N)
  weather_code (N)     — WMO weather code (0=clear, 61=rain, etc.)
  weather_desc (S)     — human-readable: "Sunny", "Light rain"
  source (S)           — "open-meteo" or "meteocat"
  recorded_at (N)
```

---

## Lambda to write

Create: `aws/lambdas/weather_ingest/lambda_function.py`

```python
import json, os, time, urllib.request, boto3
from decimal import Decimal

TABLE_NAME = os.environ.get("TABLE_NAME", "WeatherData")
URL = "https://api.open-meteo.com/v1/forecast?latitude=41.3851&longitude=2.1734&current=temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,weather_code&timezone=Europe/Madrid"

def lambda_handler(event, context):
    with urllib.request.urlopen(URL, timeout=15) as r:
        data = json.loads(r.read())
    current = data["current"]
    now = int(time.time())
    item = {
        "station_id": "barcelona_center",
        "timestamp": now,
        "temperature_c": Decimal(str(current["temperature_2m"])),
        "humidity_pct": Decimal(str(current.get("relative_humidity_2m", 0))),
        "wind_speed_ms": Decimal(str(current.get("wind_speed_10m", 0))),
        "precipitation_mm": Decimal(str(current.get("precipitation", 0))),
        "weather_code": int(current.get("weather_code", 0)),
        "source": "open-meteo",
        "ttl": now + 172800,
    }
    boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"]).Table(TABLE_NAME).put_item(Item=item)
    return {"statusCode": 200, "body": json.dumps({"written": 1})}
```

## Deploy command
```bash
# After writing lambda_function.py to aws/lambdas/weather_ingest/
bash aws/deploy.sh weather
```

You'll need to add `deploy_weather()` to `aws/deploy.sh` following the same pattern as `deploy_bicing()`.

## IAM

Use the existing `smart-city-lambda-mobility-role` or create a new `smart-city-lambda-weather-role`.
To reuse existing: update `aws/policies/lambda_mobility_policy.json` to include `WeatherData` table.

Or create a new one:
```bash
aws iam create-role --role-name smart-city-lambda-weather-role \
  --assume-role-policy-document file://aws/policies/lambda_trust_policy.json
# Then attach a policy allowing DynamoDB PutItem on WeatherData + CloudWatch logs
```
