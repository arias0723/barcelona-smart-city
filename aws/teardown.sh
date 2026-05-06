#!/usr/bin/env bash
# =============================================================================
# Smart City — Teardown (DELETE all AWS resources)
# =============================================================================
# ⚠️  DESTRUCTIVE — deletes all tables, Lambdas, roles, S3 bucket.
#      All data in DynamoDB will be permanently lost.
#
# Only use when shutting the project down entirely.
# For pausing data ingestion without data loss: use aws/pause.sh instead.
#
# Usage:
#   bash aws/teardown.sh
# =============================================================================

set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
BUCKET="smart-city-raw-${ACCOUNT_ID}"

echo "============================================"
echo "  ⚠️  Smart City Teardown"
echo "  This will DELETE all project AWS resources"
echo "  Account : $ACCOUNT_ID"
echo "  Region  : $REGION"
echo "============================================"
read -p "Type 'yes' to confirm: " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted."
  exit 0
fi

# EventBridge rules
echo ""
echo "[1/5] Removing EventBridge rules..."
for RULE in smart-city-bicing-schedule smart-city-air-quality-schedule; do
  aws events remove-targets --rule "$RULE" --ids 1 --region "$REGION" 2>/dev/null || true
  aws events delete-rule --name "$RULE" --region "$REGION" 2>/dev/null \
    && echo "  Deleted $RULE" || echo "  SKIP $RULE (not found)"
done

# Lambda functions
echo ""
echo "[2/5] Removing Lambda functions..."
for FUNC in smart-city-bicing-ingest smart-city-air-quality-ingest; do
  aws lambda delete-function --function-name "$FUNC" --region "$REGION" 2>/dev/null \
    && echo "  Deleted Lambda: $FUNC" || echo "  SKIP $FUNC (not found)"
done

# DynamoDB tables
echo ""
echo "[3/5] Removing DynamoDB tables..."
for TABLE in BicingStations TransitStops ScheduleCache AirQualityReadings WeatherData NoiseData; do
  aws dynamodb delete-table --table-name "$TABLE" --region "$REGION" 2>/dev/null \
    && echo "  Deleted table: $TABLE" || echo "  SKIP $TABLE (not found)"
done

# IAM roles
echo ""
echo "[4/5] Removing IAM roles..."
for ROLE in smart-city-lambda-mobility-role smart-city-lambda-air-quality-role; do
  # Remove inline policies first
  POLICIES=$(aws iam list-role-policies --role-name "$ROLE" --query PolicyNames --output text 2>/dev/null || echo "")
  for POLICY in $POLICIES; do
    aws iam delete-role-policy --role-name "$ROLE" --policy-name "$POLICY" 2>/dev/null || true
  done
  aws iam delete-role --role-name "$ROLE" 2>/dev/null \
    && echo "  Deleted role: $ROLE" || echo "  SKIP $ROLE (not found)"
done

# S3 bucket
echo ""
echo "[5/5] Removing S3 bucket..."
aws s3 rm "s3://${BUCKET}" --recursive --region "$REGION" 2>/dev/null || true
aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null \
  && echo "  Deleted bucket: $BUCKET" || echo "  SKIP $BUCKET (not found)"

echo ""
echo "Teardown complete. All Smart City AWS resources removed."
