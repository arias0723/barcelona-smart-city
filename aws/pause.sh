#!/usr/bin/env bash
# =============================================================================
# Smart City — Pause / Resume Lambda Schedules
# =============================================================================
# Use this to stop Lambda invocations without deleting anything.
# All data stays in DynamoDB. Re-enable when you need fresh data again.
#
# Usage:
#   bash aws/pause.sh           # disable all schedules (stop data ingestion)
#   bash aws/pause.sh resume    # re-enable all schedules
#
# Cost note:
#   Lambda and DynamoDB are within the always-free tier at this project's scale.
#   Pausing schedules is optional but good practice when not actively working.
# =============================================================================

set -euo pipefail

REGION="${AWS_REGION:-eu-west-1}"
ACTION="${1:-pause}"

RULES=(
  "smart-city-bicing-schedule"
  "smart-city-air-quality-schedule"
)

case "$ACTION" in
  pause|disable)
    STATE="DISABLED"
    VERB="Pausing"
    ;;
  resume|enable)
    STATE="ENABLED"
    VERB="Resuming"
    ;;
  *)
    echo "Usage: bash aws/pause.sh [pause|resume]"
    exit 1
    ;;
esac

echo "$VERB Lambda schedules..."
for RULE in "${RULES[@]}"; do
  aws events disable-rule --name "$RULE" --region "$REGION" 2>/dev/null && echo "  DISABLED $RULE" || true
  if [ "$STATE" = "ENABLED" ]; then
    aws events enable-rule --name "$RULE" --region "$REGION" 2>/dev/null && echo "  ENABLED  $RULE" || true
  fi
done

if [ "$STATE" = "DISABLED" ]; then
  echo ""
  echo "Schedules paused. Lambdas will not auto-run."
  echo "To resume: bash aws/pause.sh resume"
else
  echo ""
  echo "Schedules resumed. Lambdas will auto-run on their schedules."
fi
