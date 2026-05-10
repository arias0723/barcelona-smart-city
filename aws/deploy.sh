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
POLICIES_DIR="$(dirname "$0")/policies"
TARGET="${1:-all}"

MOBILITY_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/smart-city-lambda-mobility-role"
AIR_QUALITY_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/smart-city-lambda-air-quality-role"
WEATHER_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/smart-city-lambda-weather-role"
MCP_ROLE="arn:aws:iam::${ACCOUNT_ID}:role/smart-city-lambda-mcp-role"

echo "============================================"
echo "  Smart City Lambda Deployment"
echo "  Account : $ACCOUNT_ID"
echo "  Region  : $REGION"
echo "  Target  : $TARGET"
echo "============================================"

# ---------------------------------------------------------------------------
# Helper: ensure IAM role exists, create if not
# ---------------------------------------------------------------------------
ensure_role() {
  local role_name="$1"
  local trust_policy_file="$2"
  local inline_policy_file="$3"
  local inline_policy_name="$4"

  if aws iam get-role --role-name "$role_name" \
      --query 'Role.RoleName' --output text 2>/dev/null | grep -q "$role_name"; then
    echo "    SKIP  IAM role $role_name already exists"
  else
    echo "    CREATE IAM role $role_name"
    aws iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://${POLICIES_DIR}/${trust_policy_file}" \
      > /dev/null
    aws iam put-role-policy \
      --role-name "$role_name" \
      --policy-name "$inline_policy_name" \
      --policy-document "file://${POLICIES_DIR}/${inline_policy_file}" \
      > /dev/null
    echo "    OK    $role_name created"
    sleep 10  # IAM propagation delay
  fi
}

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
# Deploy Weather ingest
# ---------------------------------------------------------------------------
deploy_weather() {
  echo ""
  echo "[Weather Ingest]"
  ensure_role \
    "smart-city-lambda-weather-role" \
    "lambda_trust_policy.json" \
    "lambda_weather_policy.json" \
    "smart-city-weather-inline"

  ZIP=$(package_lambda weather_ingest)
  deploy_function \
    "smart-city-weather-ingest" \
    "$ZIP" \
    "$WEATHER_ROLE" \
    "lambda_function.lambda_handler" \
    "TABLE_NAME=WeatherData,DYNAMO_REGION=${REGION}" \
    "Fetches Barcelona weather from Open-Meteo every hour"

  create_schedule "smart-city-weather-schedule" "rate(1 hour)" "smart-city-weather-ingest"
}

# ---------------------------------------------------------------------------
# Deploy MCP server Lambda + API Gateway HTTP API
# ---------------------------------------------------------------------------
deploy_mcp() {
  echo ""
  echo "[MCP Server Lambda + API Gateway]"

  ensure_role \
    "smart-city-lambda-mcp-role" \
    "lambda_trust_policy.json" \
    "lambda_mcp_policy.json" \
    "smart-city-mcp-inline"

  # Package: include mcp and mangum from venv
  echo ""
  echo "  Packaging mcp_server …"
  MCP_ZIP="/tmp/smart-city-mcp-server.zip"
  rm -f "$MCP_ZIP"

  # Build a clean package dir
  PKG_DIR="/tmp/smart-city-mcp-pkg"
  rm -rf "$PKG_DIR" && mkdir -p "$PKG_DIR"

  # Install all dependencies for Linux x86_64 (Lambda runtime)
  pip install \
    "mcp[cli]" \
    "requests" \
    "boto3" \
    --target "$PKG_DIR" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all: \
    --quiet

  # Copy our Lambda handler
  cp "$(dirname "$0")/../mcp_server.py" "$PKG_DIR/lambda_function.py"
  # Copy transit route tool (imported by mcp_server)
  cp "$(dirname "$0")/../transit_route_tool.py" "$PKG_DIR/transit_route_tool.py"

  (cd "$PKG_DIR" && zip -q -r "$MCP_ZIP" .)
  echo "    ZIP: $MCP_ZIP ($(du -sh "$MCP_ZIP" | cut -f1))"

  # Deploy Lambda (512MB, 30s timeout for cold starts with mcp package)
  FUNC_NAME="smart-city-mcp-server"
  if aws lambda get-function --function-name "$FUNC_NAME" --region "$REGION" \
      --query 'Configuration.FunctionName' --output text 2>/dev/null; then
    echo "    UPDATE $FUNC_NAME"
    aws lambda update-function-code \
      --function-name "$FUNC_NAME" \
      --zip-file "fileb://${MCP_ZIP}" \
      --region "$REGION" > /dev/null
  else
    echo "    CREATE $FUNC_NAME"
    aws lambda create-function \
      --function-name "$FUNC_NAME" \
      --runtime python3.12 \
      --handler "lambda_function.handler" \
      --role "$MCP_ROLE" \
      --zip-file "fileb://${MCP_ZIP}" \
      --timeout 30 \
      --memory-size 512 \
      --description "Barcelona Smart City MCP server — exposed via API Gateway" \
      --environment "Variables={DYNAMO_REGION=${REGION}}" \
      --region "$REGION" > /dev/null
  fi
  echo "    OK    $FUNC_NAME deployed"

  # API Gateway HTTP API
  API_NAME="smart-city-mcp-api"
  EXISTING_API=$(aws apigatewayv2 get-apis --region "$REGION" \
    --query "Items[?Name=='${API_NAME}'].ApiId" --output text 2>/dev/null || true)

  if [ -n "$EXISTING_API" ]; then
    echo "    SKIP  API Gateway $API_NAME already exists (ID: $EXISTING_API)"
    API_ID="$EXISTING_API"
  else
    echo "    CREATE API Gateway HTTP API: $API_NAME"
    API_ID=$(aws apigatewayv2 create-api \
      --name "$API_NAME" \
      --protocol-type HTTP \
      --description "Barcelona Smart City MCP server endpoint" \
      --cors-configuration \
        AllowOrigins='["*"]',AllowMethods='["POST","GET","OPTIONS"]',AllowHeaders='["*"]',MaxAge=300 \
      --region "$REGION" \
      --query 'ApiId' --output text)
    echo "    OK    API created: $API_ID"
  fi

  LAMBDA_ARN=$(aws lambda get-function \
    --function-name "$FUNC_NAME" \
    --region "$REGION" \
    --query 'Configuration.FunctionArn' --output text)

  # Lambda integration (AWS_PROXY)
  INTEGRATION_ID=$(aws apigatewayv2 get-integrations \
    --api-id "$API_ID" --region "$REGION" \
    --query 'Items[0].IntegrationId' --output text 2>/dev/null || true)

  if [ -z "$INTEGRATION_ID" ] || [ "$INTEGRATION_ID" = "None" ]; then
    echo "    CREATE Lambda integration"
    INTEGRATION_ID=$(aws apigatewayv2 create-integration \
      --api-id "$API_ID" \
      --integration-type AWS_PROXY \
      --integration-uri "$LAMBDA_ARN" \
      --payload-format-version "2.0" \
      --region "$REGION" \
      --query 'IntegrationId' --output text)
    echo "    OK    Integration: $INTEGRATION_ID"
  else
    echo "    SKIP  Integration already exists: $INTEGRATION_ID"
  fi

  # Route: ANY /{proxy+}
  ROUTE_EXISTS=$(aws apigatewayv2 get-routes \
    --api-id "$API_ID" --region "$REGION" \
    --query "Items[?RouteKey=='\$default'].RouteId" --output text 2>/dev/null || true)

  if [ -z "$ROUTE_EXISTS" ] || [ "$ROUTE_EXISTS" = "None" ]; then
    echo "    CREATE default route"
    aws apigatewayv2 create-route \
      --api-id "$API_ID" \
      --route-key '$default' \
      --target "integrations/${INTEGRATION_ID}" \
      --region "$REGION" > /dev/null
    echo "    OK    Route created"
  else
    echo "    SKIP  Default route already exists"
  fi

  # Auto-deploy stage
  STAGE_EXISTS=$(aws apigatewayv2 get-stages \
    --api-id "$API_ID" --region "$REGION" \
    --query "Items[?StageName=='\$default'].StageName" --output text 2>/dev/null || true)

  if [ -z "$STAGE_EXISTS" ] || [ "$STAGE_EXISTS" = "None" ]; then
    echo "    CREATE auto-deploy stage"
    aws apigatewayv2 create-stage \
      --api-id "$API_ID" \
      --stage-name '$default' \
      --auto-deploy \
      --region "$REGION" > /dev/null
    echo "    OK    Stage created"
  else
    echo "    SKIP  Default stage already exists"
  fi

  # Grant API Gateway permission to invoke Lambda
  aws lambda add-permission \
    --function-name "$FUNC_NAME" \
    --statement-id "apigateway-invoke" \
    --action "lambda:InvokeFunction" \
    --principal "apigateway.amazonaws.com" \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*" \
    --region "$REGION" > /dev/null 2>&1 || true

  API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com/mcp"
  echo ""
  echo "  ============================================"
  echo "  MCP server endpoint:"
  echo "  $API_URL"
  echo ""
  echo "  Add to Claude Desktop (~/.config/claude/claude_desktop_config.json):"
  echo "  {"
  echo "    \"mcpServers\": {"
  echo "      \"barcelona-smart-city\": {"
  echo "        \"url\": \"${API_URL}\""
  echo "      }"
  echo "    }"
  echo "  }"
  echo "  ============================================"
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
case "$TARGET" in
  bicing)       deploy_bicing ;;
  air_quality)  deploy_air_quality ;;
  weather)      deploy_weather ;;
  mcp)          deploy_mcp ;;
  all)          deploy_bicing; deploy_air_quality; deploy_weather; deploy_mcp ;;
  *)
    echo "ERROR: unknown target '$TARGET'. Use: bicing | air_quality | weather | mcp | all"
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
