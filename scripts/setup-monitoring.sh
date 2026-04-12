#!/usr/bin/env bash
# Set up BetterStack monitoring for the Workflow Automation Engine.
#
# This script outputs the steps needed to configure BetterStack
# monitoring for the production deployment. It reads the monitor
# definition from betterstack.json and provides curl commands
# for the BetterStack API.
#
# Prerequisites:
#   - BetterStack account with API token
#   - Production deployment running at workflows.kingsleyonoh.com
#
# Usage:
#   # Set your BetterStack API token
#   export BETTERSTACK_API_TOKEN="your_token_here"
#
#   # Run the setup script
#   ./scripts/setup-monitoring.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PROJECT_DIR}/betterstack.json"

log() {
    echo "[monitoring] $*"
}

error() {
    echo "[monitoring] ERROR: $*" >&2
    exit 1
}

# Check prerequisites
if [ ! -f "${CONFIG_FILE}" ]; then
    error "betterstack.json not found at ${CONFIG_FILE}"
fi

if [ -z "${BETTERSTACK_API_TOKEN:-}" ]; then
    log ""
    log "BetterStack API token not set."
    log ""
    log "To create a monitor automatically, set BETTERSTACK_API_TOKEN:"
    log "  export BETTERSTACK_API_TOKEN=\"your_token_here\""
    log "  ./scripts/setup-monitoring.sh"
    log ""
    log "To create manually via the BetterStack dashboard:"
    log "  1. Go to https://uptime.betterstack.com"
    log "  2. Click 'Create Monitor'"
    log "  3. Use these settings from betterstack.json:"
    log "     - URL: https://workflows.kingsleyonoh.com/api/health"
    log "     - Check frequency: 60 seconds"
    log "     - Request timeout: 5 seconds"
    log "     - Monitor type: HTTP(S)"
    log "     - HTTP method: GET"
    log "     - Expected status: 200"
    log ""
    exit 0
fi

log "Creating BetterStack monitor from betterstack.json..."

# Read monitor config
MONITOR_URL=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['monitors'][0]['url'])")
MONITOR_NAME=$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['monitors'][0]['monitor_type'])" 2>/dev/null || echo "status")

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST \
    "https://uptime.betterstack.com/api/v2/monitors" \
    -H "Authorization: Bearer ${BETTERSTACK_API_TOKEN}" \
    -H "Content-Type: application/json" \
    -d @"${CONFIG_FILE}" 2>&1) || true

HTTP_CODE=$(echo "${RESPONSE}" | tail -1)
BODY=$(echo "${RESPONSE}" | head -n -1)

if [ "${HTTP_CODE}" = "201" ] || [ "${HTTP_CODE}" = "200" ]; then
    log "Monitor created successfully!"
    log "Response: ${BODY}"
else
    log "API call returned HTTP ${HTTP_CODE}"
    log "Response: ${BODY}"
    log ""
    log "You may need to create the monitor manually at:"
    log "  https://uptime.betterstack.com"
fi

log ""
log "Monitor URL: https://workflows.kingsleyonoh.com/api/health"
log "Check interval: 60 seconds"
log "Timeout: 5 seconds"
