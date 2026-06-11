#!/bin/bash
# Build a custom docker image from another docker image (typically a dev image).
# With that file, the image for the connector will have proxy settings defined.

# Usage: ./build_custom_docker_image.sh <custom-image-tag> <dev-image-tag>

CUSTOM_IMAGE=$1
BASE_IMAGE=$2
IMAGE_USER=${IMAGE_USER:-root}

echo "🚀 Setting up custom docker image: $CUSTOM_IMAGE from base image: $BASE_IMAGE using user: $IMAGE_USER..."

docker build \
  --build-arg BASE_IMAGE="$BASE_IMAGE" \
  -t "$CUSTOM_IMAGE" \
  - <<EOF
ARG BASE_IMAGE
FROM $BASE_IMAGE
ENV HTTP_PROXY=${IMAGE_HTTP_PROXY}
ENV HTTPS_PROXY=${IMAGE_HTTPS_PROXY}
USER ${IMAGE_USER}
EOF

echo "✅ Custom image built: $CUSTOM_IMAGE from $BASE_IMAGE"
