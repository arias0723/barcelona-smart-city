#!/usr/bin/env bash
# =============================================================================
# Smart City — AWS Infrastructure Setup
# =============================================================================
# Creates all AWS resources needed for the Smart City project.
# Safe to re-run: existing resources are skipped with a warning.
#
# Usage:
#   bash aws/setup.sh
#
# Prerequisites:
#   - AWS CLI configured (run: aws configure, or set .env vars)
#   - Python 3.x installed (for Lambda packaging)
#
# What this creates:
#   - S3 bucket          : smart-city-raw-{ACCOUNT_ID}
#   - DynamoDB tables    : BicingStations, TransitStops, ScheduleCache,
#                          AirQualityReadings, WeatherData, NoiseData
#   - IAM roles          : smart-city-lambda-mobility-role
#                          smart-city-lambda-air-quality-role
#   - IAM policies       : (inline, attached to roles above)
#   - EventBridge rules  : bicing-ingest-schedule (every 5 min)
#                          air-quality-ingest-schedule (every 1 hour)
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REGION="${AWS_REGION:-eu-west-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="smart-city-raw-${ACCOUNT_ID}"
POLICIES_DIR="$(dirname "$0")/policies"

echo "============================================"
echo "  Smart City Infrastructure Setup"
echo "  Account : $ACCOUNT_ID"
echo "  Region  : $REGION"
echo "  Bucket  : $BUCKET"
echo "============================================"

# ---------------------------------------------------------------------------
# Helper: create resource only if it doesn't exist
# ---------------------------------------------------------------------------
table_exists() {
  aws dynamodb describe-table --table-name "$1" --region "$REGION" \
    --query 'Table.TableName' --output text 2>/dev/null
}

role_exists() {
  aws iam get-role --role-name "$1" --query 'Role.RoleName' --output text 2>/dev/null
}

wait_for_table() {
  local name="$1"
  echo -n "      WAIT  $name becoming ACTIVE"
  for i in $(seq 1 30); do
    STATUS=$(aws dynamodb describe-table --table-name "$name" --region "$REGION" \
      --query 'Table.TableStatus' --output text 2>/dev/null || echo "CREATING")
    if [ "$STATUS" = "ACTIVE" ]; then
      echo " → ACTIVE"
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo " → TIMEOUT (table may still be creating)"
  return 1
}

enable_ttl() {
  local name="$1"
  local attr="$2"
  aws dynamodb update-time-to-live \
    --table-name "$name" \
    --time-to-live-specification "Enabled=true,AttributeName=${attr}" \
    --region "$REGION" > /dev/null 2>&1 || true
}

# ---------------------------------------------------------------------------
# 1. S3 Bucket
# ---------------------------------------------------------------------------
echo ""
echo "[1/5] S3 bucket..."
if aws s3 ls "s3://${BUCKET}" 2>/dev/null; then
  echo "      SKIP  s3://${BUCKET} already exists"
else
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
  # Block all public access
  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
  echo "      OK    s3://${BUCKET} created"
fi

# ---------------------------------------------------------------------------
# 2. DynamoDB Tables
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] DynamoDB tables..."

# -- BicingStations --
if table_exists BicingStations > /dev/null 2>&1; then
  echo "      SKIP  BicingStations already exists"
else
  aws dynamodb create-table \
    --table-name BicingStations \
    --attribute-definitions \
      AttributeName=station_id,AttributeType=S \
      AttributeName=updated_at,AttributeType=N \
      AttributeName=lat_bucket,AttributeType=S \
      AttributeName=lon,AttributeType=N \
      AttributeName=is_renting,AttributeType=N \
      AttributeName=num_bikes_available,AttributeType=N \
    --key-schema \
      AttributeName=station_id,KeyType=HASH \
      AttributeName=updated_at,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
      {
        "IndexName": "LatIndex",
        "KeySchema": [
          {"AttributeName": "lat_bucket", "KeyType": "HASH"},
          {"AttributeName": "lon",        "KeyType": "RANGE"}
        ],
        "Projection": {"ProjectionType": "ALL"}
      },
      {
        "IndexName": "StatusIndex",
        "KeySchema": [
          {"AttributeName": "is_renting",          "KeyType": "HASH"},
          {"AttributeName": "num_bikes_available",  "KeyType": "RANGE"}
        ],
        "Projection": {
          "ProjectionType": "INCLUDE",
          "NonKeyAttributes": ["name", "lat", "lon", "station_id", "lat_bucket"]
        }
      }
    ]' \
    --region "$REGION" > /dev/null
  wait_for_table BicingStations
  enable_ttl BicingStations ttl
  echo "      OK    BicingStations created"
fi

# -- TransitStops --
if table_exists TransitStops > /dev/null 2>&1; then
  echo "      SKIP  TransitStops already exists"
else
  aws dynamodb create-table \
    --table-name TransitStops \
    --attribute-definitions \
      AttributeName=stop_id,AttributeType=S \
      AttributeName=feed_ver,AttributeType=S \
      AttributeName=lat_bucket,AttributeType=S \
      AttributeName=stop_lon,AttributeType=N \
    --key-schema \
      AttributeName=stop_id,KeyType=HASH \
      AttributeName=feed_ver,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
      {
        "IndexName": "LatBucketIndex",
        "KeySchema": [
          {"AttributeName": "lat_bucket", "KeyType": "HASH"},
          {"AttributeName": "stop_lon",   "KeyType": "RANGE"}
        ],
        "Projection": {"ProjectionType": "ALL"}
      }
    ]' \
    --region "$REGION" > /dev/null
  wait_for_table TransitStops
  enable_ttl TransitStops ttl
  echo "      OK    TransitStops created"
fi

# -- ScheduleCache --
if table_exists ScheduleCache > /dev/null 2>&1; then
  echo "      SKIP  ScheduleCache already exists"
else
  aws dynamodb create-table \
    --table-name ScheduleCache \
    --attribute-definitions \
      AttributeName=stop_id,AttributeType=S \
      AttributeName=day_hour,AttributeType=S \
    --key-schema \
      AttributeName=stop_id,KeyType=HASH \
      AttributeName=day_hour,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" > /dev/null
  wait_for_table ScheduleCache
  enable_ttl ScheduleCache ttl
  echo "      OK    ScheduleCache created"
fi

# -- AirQualityReadings --
if table_exists AirQualityReadings > /dev/null 2>&1; then
  echo "      SKIP  AirQualityReadings already exists"
else
  aws dynamodb create-table \
    --table-name AirQualityReadings \
    --attribute-definitions \
      AttributeName=station_pollutant,AttributeType=S \
      AttributeName=hour_ts,AttributeType=S \
      AttributeName=lat_bucket,AttributeType=S \
    --key-schema \
      AttributeName=station_pollutant,KeyType=HASH \
      AttributeName=hour_ts,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes '[
      {
        "IndexName": "LatBucketIndex",
        "KeySchema": [
          {"AttributeName": "lat_bucket", "KeyType": "HASH"},
          {"AttributeName": "hour_ts",    "KeyType": "RANGE"}
        ],
        "Projection": {"ProjectionType": "ALL"}
      }
    ]' \
    --region "$REGION" > /dev/null
  wait_for_table AirQualityReadings
  enable_ttl AirQualityReadings ttl
  echo "      OK    AirQualityReadings created"
fi

# -- WeatherData (placeholder for Jia) --
if table_exists WeatherData > /dev/null 2>&1; then
  echo "      SKIP  WeatherData already exists"
else
  aws dynamodb create-table \
    --table-name WeatherData \
    --attribute-definitions \
      AttributeName=station_id,AttributeType=S \
      AttributeName=timestamp,AttributeType=N \
    --key-schema \
      AttributeName=station_id,KeyType=HASH \
      AttributeName=timestamp,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" > /dev/null
  wait_for_table WeatherData
  enable_ttl WeatherData ttl
  echo "      OK    WeatherData created (placeholder — Jia's vertical)"
fi

# -- NoiseData (placeholder for Jose) --
if table_exists NoiseData > /dev/null 2>&1; then
  echo "      SKIP  NoiseData already exists"
else
  aws dynamodb create-table \
    --table-name NoiseData \
    --attribute-definitions \
      AttributeName=sensor_id,AttributeType=S \
      AttributeName=timestamp,AttributeType=N \
    --key-schema \
      AttributeName=sensor_id,KeyType=HASH \
      AttributeName=timestamp,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$REGION" > /dev/null
  wait_for_table NoiseData
  enable_ttl NoiseData ttl
  echo "      OK    NoiseData created (placeholder — Jose's vertical)"
fi

# ---------------------------------------------------------------------------
# 3. IAM Roles
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] IAM roles..."

# -- Mobility role --
if role_exists smart-city-lambda-mobility-role > /dev/null 2>&1; then
  echo "      SKIP  smart-city-lambda-mobility-role already exists"
else
  aws iam create-role \
    --role-name smart-city-lambda-mobility-role \
    --assume-role-policy-document "file://${POLICIES_DIR}/lambda_trust_policy.json" \
    --description "Lambda execution role for mobility vertical (Bicing + Transit)" \
    > /dev/null
  aws iam put-role-policy \
    --role-name smart-city-lambda-mobility-role \
    --policy-name smart-city-mobility-inline \
    --policy-document "file://${POLICIES_DIR}/lambda_mobility_policy.json"
  echo "      OK    smart-city-lambda-mobility-role created"
fi

# -- Air quality role --
if role_exists smart-city-lambda-air-quality-role > /dev/null 2>&1; then
  echo "      SKIP  smart-city-lambda-air-quality-role already exists"
else
  aws iam create-role \
    --role-name smart-city-lambda-air-quality-role \
    --assume-role-policy-document "file://${POLICIES_DIR}/lambda_trust_policy.json" \
    --description "Lambda execution role for air quality vertical (XVPCA / Open Data BCN)" \
    > /dev/null
  aws iam put-role-policy \
    --role-name smart-city-lambda-air-quality-role \
    --policy-name smart-city-air-quality-inline \
    --policy-document "file://${POLICIES_DIR}/lambda_air_quality_policy.json"
  echo "      OK    smart-city-lambda-air-quality-role created"
fi

# ---------------------------------------------------------------------------
# 4. Wait for tables to become ACTIVE
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Waiting for tables to become ACTIVE..."
for TABLE in BicingStations TransitStops ScheduleCache AirQualityReadings WeatherData NoiseData; do
  STATUS=$(aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" \
    --query 'Table.TableStatus' --output text 2>/dev/null || echo "MISSING")
  if [ "$STATUS" = "ACTIVE" ]; then
    echo "      OK    $TABLE is ACTIVE"
  else
    echo "      WAIT  $TABLE status: $STATUS (may take ~15s, re-run if needed)"
  fi
done

# ---------------------------------------------------------------------------
# 5. Summary
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Setup complete. Summary:"
echo ""
echo "  S3 bucket    : s3://${BUCKET}"
echo "  DynamoDB     : BicingStations, TransitStops, ScheduleCache"
echo "                 AirQualityReadings, WeatherData, NoiseData"
echo "  IAM roles    : smart-city-lambda-mobility-role"
echo "                 smart-city-lambda-air-quality-role"
echo ""
echo "  Next steps:"
echo "    1. Deploy Lambda functions:  bash aws/deploy.sh"
echo "    2. Load GTFS stop data:      python3 aws/scripts/load_gtfs.py"
echo "    3. Verify data is flowing:   python3 aws/scripts/verify_data.py"
echo ""
