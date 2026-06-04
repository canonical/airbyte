#!/usr/bin/env bash
set -euo pipefail

CONNECTOR_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_CONFIG="$CONNECTOR_DIR/acceptance-test-config.local.yml"
CI_CONFIG="$CONNECTOR_DIR/acceptance-test-config.yml"
BACKUP="$CI_CONFIG.ci-backup"

if [ ! -f "$LOCAL_CONFIG" ]; then
  echo "ERROR: $LOCAL_CONFIG not found" >&2
  exit 1
fi

restore() {
  cp "$BACKUP" "$CI_CONFIG"
  rm -f "$BACKUP"
}
trap restore EXIT

verify_dockerfile() {
  if [[ ! -f build/docker/Dockerfile ]]; then
    echo "ERROR: Connector Dockerfile not found. Run 'make build'." >&2
    exit 1
  fi
}

cp "$CI_CONFIG" "$BACKUP"
cp "$LOCAL_CONFIG" "$CI_CONFIG"

cd "$CONNECTOR_DIR"
poe install-cdk-cli
verify_dockerfile
docker build . --file build/docker/Dockerfile -t airbyte/source-udemy:dev
airbyte-cdk connector test "$CONNECTOR_DIR" --pytest-arg "-k not docker_image_build"

# Acceptance tests docs referenced:
# https://docs.airbyte.com/platform/connector-development/testing-connectors/connector-acceptance-tests-reference 
