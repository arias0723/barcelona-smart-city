"""
scripts/verify_data.py
=======================
Checks that data is flowing into all DynamoDB tables.
Run after deploy.sh and the first Lambda invocations.

Usage:
    python3 aws/scripts/verify_data.py

Output: table-by-table item counts and a sample record per table.
"""

import os
import json
import boto3
from decimal import Decimal

REGION = os.environ.get("AWS_REGION", "eu-west-1")
dynamodb = boto3.resource("dynamodb", region_name=REGION)
client   = boto3.client("dynamodb", region_name=REGION)

TABLES = [
    "BicingStations",
    "TransitStops",
    "ScheduleCache",
    "AirQualityReadings",
    "WeatherData",
    "NoiseData",
]


def default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, set):
        return list(obj)
    raise TypeError(f"Not serializable: {type(obj)}")


def check_table(name: str):
    try:
        meta  = client.describe_table(TableName=name)["Table"]
        count = meta.get("ItemCount", "?")
        status = meta.get("TableStatus", "?")
        print(f"\n  {name}")
        print(f"    Status    : {status}")
        print(f"    Items     : {count}  (may lag ~6 hours for DynamoDB's count)")

        # Grab one item via scan with limit=1
        table = dynamodb.Table(name)
        resp  = table.scan(Limit=1)
        items = resp.get("Items", [])
        if items:
            print(f"    Sample    : {json.dumps(items[0], default=default, ensure_ascii=False)[:200]}…")
        else:
            print(f"    Sample    : (empty — Lambda not yet invoked?)")
    except client.exceptions.ResourceNotFoundException:
        print(f"\n  {name}  →  NOT FOUND (run setup.sh first)")
    except Exception as e:
        print(f"\n  {name}  →  ERROR: {e}")


def main():
    print("=" * 60)
    print("  Smart City — DynamoDB Data Verification")
    print("=" * 60)
    for t in TABLES:
        check_table(t)
    print("\n" + "=" * 60)
    print("  Tip: If BicingStations / AirQualityReadings are empty,")
    print("  invoke the Lambda manually:")
    print("    aws lambda invoke --function-name smart-city-bicing-ingest \\")
    print("      --payload '{}' /tmp/out.json && cat /tmp/out.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
