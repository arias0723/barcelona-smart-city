#!/bin/bash
# Starts the Barcelona Smart City demo server.
# AWS credentials are picked up from ~/.aws/credentials / IAM role / env vars
# (standard boto3 credential chain — no manual env setup needed).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"
source venv/bin/activate

# Defaults — override by setting env vars before running this script
: "${BEDROCK_REGION:=eu-north-1}"
: "${DYNAMO_REGION:=eu-west-1}"
: "${BEDROCK_MODEL_ID:=eu.anthropic.claude-haiku-4-5-20251001-v1:0}"

export BEDROCK_REGION DYNAMO_REGION BEDROCK_MODEL_ID

echo "Starting Barcelona Smart City Demo..."
echo "  Bedrock  : $BEDROCK_REGION  ($BEDROCK_MODEL_ID)"
echo "  DynamoDB : $DYNAMO_REGION"
echo "  URL      : http://localhost:8765"
echo ""

python3 -m uvicorn demo.app:app --port 8765 --reload
