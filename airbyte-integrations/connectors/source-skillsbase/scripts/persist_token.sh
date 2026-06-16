#!/usr/bin/env bash
# Filters a connector's stdout and writes any CONNECTOR_CONFIG control message
# back to config.json, persisting the cached token across cold `docker run`s.
#
# Why: Skills Base caps concurrent active tokens, so a fresh token each run is
# rejected with "Access token allowance exceeded". Production Airbyte persists
# config via the platform; this replays that locally.
#
# Usage: <connector cmd> | scripts/persist_token.sh secrets/config.json

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <path/to/config.json>" >&2
  exit 1
fi

CONFIG_PATH="$1"
LATEST=""

if ! command -v jq >/dev/null 2>&1; then
  echo "⚠️  jq not found on PATH; token will not be persisted across runs." >&2
  cat
  exit 0
fi

while IFS= read -r line; do
  printf '%s\n' "$line"
  new=$(printf '%s' "$line" \
    | jq -c 'select(.type == "CONTROL" and .control.type == "CONNECTOR_CONFIG") | .control.connectorConfig.config' \
      2>/dev/null || true)
  if [ -n "$new" ] && [ "$new" != "null" ]; then
    LATEST="$new"
  fi
done

if [ -n "$LATEST" ]; then
  printf '%s' "$LATEST" | jq '.' > "$CONFIG_PATH.tmp"
  mv "$CONFIG_PATH.tmp" "$CONFIG_PATH"
  echo "🔑 Persisted refreshed Skills Base token to $CONFIG_PATH" >&2
fi
