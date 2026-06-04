#!/usr/bin/env bash
set -euo pipefail

echo "Installing uv (tool manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo "uv already installed: $(uv --version)"
fi

echo "Installing poethepoet (poe task runner)"
uv tool install --force --upgrade poethepoet

echo "Installing airbyte-cdk[dev] (airbyte-cdk CLI)"
uv tool install --force --upgrade 'airbyte-cdk[dev]'

echo "Installing airbyte-internal-ops (airbyte-ops CLI)"
uv tool install --force --upgrade airbyte-internal-ops

echo "Installing Docker buildx plugin"
if ! docker buildx version >/dev/null 2>&1; then
  echo "buildx not found, installing..."
  docker buildx create --use --name airbyte-builder 2>/dev/null || true

  if ! docker buildx version >/dev/null 2>&1; then
    echo "ERROR: Failed to install buildx. Ensure Docker is running and you have docker CLI." >&2
    exit 1
  fi

fi
echo "Docker buildx available: $(docker buildx version)"

echo "Install complete"
