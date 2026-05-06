# Noise Vertical — Jose Ricardo Arias Perez

## Status: Table ready, Lambda needed ⏳

The `NoiseData` DynamoDB table is already created. Your job this week:
1. Find a Barcelona noise data source
2. Write the Lambda ingestion function
3. Deploy it

---

## Recommended data sources

### Option A: Open Data BCN — Noise sensors (recommended)
Barcelona has a network of acoustic sensors publishing real-time data.

- Dataset: "Mapa de Soroll de la Xarxa de Vigilància Acústica de la Ciutat de Barcelona"
- Portal: https://opendata-ajuntament.barcelona.cat
- Search: "soroll" or "noise" or "acustic" on the portal
- API: CKAN datastore — same pattern as air quality (JSON, no key)

### Option B: Open Data BCN — Noise immission maps
- Static annual noise maps by district
- Less dynamic but good for showing noise levels by area

### Option C: European Noise Directive data
- BCN submits strategic noise maps to the EU
- Available at: https://noise.eea.europa.eu/

---

## DynamoDB table: NoiseData

The table was created with this basic schema:

```
PK: sensor_id (S)     — unique noise sensor ID
SK: timestamp (N)     — Unix epoch of reading
TTL: ttl (N)          — expires 48 hours after write

Suggested fields to add:
  lat, lon (N)
  lat_bucket (S)       — str(round(lat, 2)) for spatial queries
  district (S)
  laeq_db (N)          — LAeq equivalent continuous noise level (dB)
  lnight_db (N)        — Lnight (22:00–06:00 average, EU standard)
  lden_db (N)          — Lden (day-evening-night, EU standard)
  source (S)           — "bcn_sensors" etc.
  recorded_at (N)
```

---

## Lambda pattern to follow

Look at `aws/lambdas/air_quality_ingest/lambda_function.py` — your Lambda will follow the same structure:
1. Fetch data from Open Data BCN CKAN API
2. Parse the response
3. Write items to `NoiseData` table using `batch_writer()`

## Deploy command
```bash
# After writing lambda_function.py to aws/lambdas/noise_ingest/
bash aws/deploy.sh noise
```

Add a `deploy_noise()` function to `aws/deploy.sh` following the same pattern as `deploy_air_quality()`.

## IAM role
Create `smart-city-lambda-noise-role` or reuse an existing role with access to `NoiseData` table.

---

## MCP tool to write later (week of May 8)

```python
def get_noise_level(lat: float, lon: float) -> dict:
    """
    Returns current noise levels at or near the given coordinates.
    Returns LAeq in dB and a label: quiet / moderate / loud / very loud.
    """
```

WHO noise guidelines for reference:
- < 53 dB: "quiet" (residential daytime)
- 53–65 dB: "moderate"
- > 65 dB: "loud" (health impact threshold)
- > 75 dB: "very loud" (hearing damage risk)
