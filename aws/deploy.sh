#!/usr/bin/env bash
# =============================================================================
# Smart City — Lambda Deploy Script
# =============================================================================
# Packages and deploys (or updates) all Lambda functions.
# Safe to re-run: updates function code if the Lambda already exists.
#
# Usage:
#   bash aws/deploy.sh              # deploy all
#   bash aws/deploy.sh bicing       # deploy only bicing
#   bash aws/deploy.sh air_quality  # deploy only air quality
#
# Prerequisites:
#   - setup.sh must have been run first (IAM roles must exist)
#   - Python 3.x + pip installed
# =============================================================================

set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
LAMBDAS_DIR="$(dirname "$0")/lambdas"
TARGET="${1:-all}"

MOBILITY_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/smart-city-lambda-mobility-role"
AIR_QUALITY_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/smart-city-lambda-air-quality-role"

echo "============================================"
echo "  Smart City Lambda Deployment"
echo "  Account : $ACCOUNT_ID"
echo "  Region  : $REGION"
echo "  Target  : $TARGET"
echo "============================================"

# ---------------------------------------------------------------------------
# Helper: zip a Lambda directory into /tmp, return zip path
# ---------------------------------------------------------------------------
package_lambda() {
  local name="$1"
  local src_dir="${LAMBDAS_DIR}/${name}"
  local zip_path="/tmp/smart-city-${name}.zip"

  echo "" >&2
  echo "  Packaging ${name} …" >&2
  rm -f "$zip_path"
  (cd "$src_dir" && zip -q "$zip_path" lambda_function.py)
  echo "    ZIP: $zip_path ($(du -sh "$zip_path" | cut -f1))" >&2
  echo "$zip_path"
}

# ---------------------------------------------------------------------------
# Helper: create or update a Lambda function
# ---------------------------------------------------------------------------
deploy_function() {
  local func_name="$1"
  local zip_path="$2"
  local role_arn="$3"
  local handler="$4"
  local env_vars="$5"
  local description="$6"

  # Check if function exists
  if aws lambda get-function --function-name "$func_name" --region "$REGION" \
      --query 'Configuration.FunctionName' --output text 2>/dev/null; then
    # Update existing
    echo "    UPDATE $func_name"
    aws lambda update-function-code \
      --function-name "$func_name" \
      --zip-file "fileb://${zip_path}" \
      --region "$REGION" > /dev/null
  else
    # Create new
    echo "    CREATE $func_name"
    aws lambda create-function \
      --function-name "$func_name" \
      --runtime python3.12 \
      --handler "$handler" \
      --role "$role_arn" \
      --zip-file "fileb://${zip_path}" \
      --timeout 60 \
      --memory-size 256 \
      --description "$description" \
      --environment "Variables={${env_vars}}" \
      --region "$REGION" > /dev/null
  fi
  echo "    OK    $func_name deployed"
}

# ---------------------------------------------------------------------------
# Helper: create EventBridge schedule if it doesn't exist
# ---------------------------------------------------------------------------
create_schedule() {
  local rule_name="$1"
  local schedule="$2"       # e.g. "rate(5 minutes)"
  local func_name="$3"
  local rule_arn="arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${rule_name}"

  # Fetch the actual Lambda ARN (uses : separator, not /)
  local func_arn
  func_arn=$(aws lambda get-function --function-name "$func_name" --region "$REGION" \
    --query 'Configuration.FunctionArn' --output text)

  # Create or update rule (put-rule is idempotent)
  aws events put-rule \
    --name "$rule_name" \
    --schedule-expression "$schedule" \
    --state ENABLED \
    --description "Smart City: trigger ${func_name}" \
    --region "$REGION" > /dev/null

  # Grant EventBridge permission to invoke Lambda (ignore conflict if already granted)
  aws lambda add-permission \
    --function-name "$func_name" \
    --statement-id "${rule_name}-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "events.amazonaws.com" \
    --source-arn "$rule_arn" \
    --region "$REGION" > /dev/null 2>&1 || true

  # Wire target (put-targets is idempotent)
  aws events put-targets \
    --rule "$rule_name" \
    --targets "[{\"Id\":\"1\",\"Arn\":\"${func_arn}\"}]" \
    --region "$REGION" > /dev/null

  echo "    OK    EventBridge $rule_name → $schedule"
}

# ---------------------------------------------------------------------------
# Deploy Bicing ingest
# ---------------------------------------------------------------------------
deploy_bicing() {
  echo ""
  echo "[Bicing Ingest]"
  ZIP=$(package_lambda bicing_ingest)
  deploy_function \
    "smart-city-bicing-ingest" \
    "$ZIP" \
    "$MOBILITY_ROLE" \
    "lambda_function.lambda_handler" \
    "TABLE_NAME=BicingStations" \
    "Fetches Bicing GBFS station data every 5 minutes"

  # EventBridge: every 5 minutes
  create_schedule "smart-city-bicing-schedule" "rate(5 minutes)" "smart-city-bicing-ingest"
}

# ---------------------------------------------------------------------------
# Deploy Air Quality ingest
# ---------------------------------------------------------------------------
deploy_air_quality() {
  echo ""
  echo "[Air Quality Ingest]"
  ZIP=$(package_lambda air_quality_ingest)
  deploy_function \
    "smart-city-air-quality-ingest" \
    "$ZIP" \
    "$AIR_QUALITY_ROLE" \
    "lambda_function.lambda_handler" \
    "TABLE_NAME=AirQualityReadings" \
    "Fetches Barcelona air quality readings from Open Data BCN every hour"

  # EventBridge: every hour
  create_schedule "smart-city-air-quality-schedule" "rate(1 hour)" "smart-city-air-quality-ingest"
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
case "$TARGET" in
  bicing)       deploy_bicing ;;
  air_quality)  deploy_air_quality ;;
  all)          deploy_bicing; deploy_air_quality ;;
  *)
    echo "ERROR: unknown target '$TARGET'. Use: bicing | air_quality | all"
    exit 1
    ;;
esac

echo ""
echo "============================================"
echo "  Deployment complete."
echo ""
echo "  Invoke manually to test:"
echo "    aws lambda invoke --function-name smart-city-bicing-ingest \\"
echo "      --payload '{}' /tmp/out.json && cat /tmp/out.json"
echo ""
echo "  Check logs:"
echo "    aws logs tail /aws/lambda/smart-city-bicing-ingest --follow"
echo ""
echo "  Verify data in tables:"
echo "    python3 aws/scripts/verify_data.py"
echo "============================================"
