#!/bin/bash
# Build a custom docker image from another docker image (typically a dev image).
# Injects proxy env vars and optionally switches the image user.
#
# Usage: ./build_custom_docker_image.sh <custom-image-tag> <dev-image-tag>
# Env vars read: IMAGE_HTTP_PROXY, IMAGE_HTTPS_PROXY, IMAGE_GRPC_PROXY,
#                IMAGE_GRPC_PROXY_EXP, IMAGE_USER (optional)

CUSTOM_IMAGE=$1
BASE_IMAGE=$2

echo "🚀 Setting up custom docker image: $CUSTOM_IMAGE from base image: $BASE_IMAGE..."

# Build the Dockerfile content dynamically to avoid heredoc issues in CI YAML.
DOCKERFILE_CONTENT="FROM ${BASE_IMAGE}
ENV HTTP_PROXY=${IMAGE_HTTP_PROXY}
ENV HTTPS_PROXY=${IMAGE_HTTPS_PROXY}
ENV http_proxy=${IMAGE_HTTP_PROXY}
ENV https_proxy=${IMAGE_HTTPS_PROXY}
ENV grpc_proxy=${IMAGE_GRPC_PROXY}
ENV GRPC_PROXY_EXP=${IMAGE_GRPC_PROXY_EXP}"

# Only set USER if IMAGE_USER is explicitly provided.
if [ -n "${IMAGE_USER:-}" ]; then
  DOCKERFILE_CONTENT="${DOCKERFILE_CONTENT}
USER ${IMAGE_USER}"
fi

echo "$DOCKERFILE_CONTENT" | docker build --load -t "$CUSTOM_IMAGE" -

echo "✅ Custom image built: $CUSTOM_IMAGE from $BASE_IMAGE"
