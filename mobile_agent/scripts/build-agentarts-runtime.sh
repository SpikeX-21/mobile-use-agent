#!/usr/bin/env bash
set -euo pipefail

# Build the dedicated AgentArts runtime image. This script deliberately uses
# BuildKit with Docker's non-OCI media-type compatibility switch: the Huawei
# SWR basic edition accepts Docker v2 media types but not OCI image media types.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CONTEXT_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-mobile-use-agent-agentarts}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/arm64}"
IMAGE_REF="${IMAGE_REPOSITORY}:${IMAGE_TAG}"

if [[ "$TARGET_PLATFORM" != "linux/arm64" ]]; then
  printf 'TARGET_PLATFORM must be linux/arm64\n' >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  printf 'docker is required\n' >&2
  exit 2
fi
if [[ ! -s "$CONTEXT_DIR/jwt.jks" ]]; then
  printf 'jwt.jks is required for this internal POC image\n' >&2
  exit 2
fi

# Docker 27+/SWR compatibility. Keep BuildKit enabled because the Dockerfile
# uses COPY --chmod; this variable changes the exported media types only.
export BUILDKIT_USE_OCI_MEDIA_TYPES=0
export DOCKER_BUILDKIT=1

docker build \
  --platform "$TARGET_PLATFORM" \
  --provenance=false \
  --sbom=false \
  --output "type=image,name=$IMAGE_REF,push=false,oci-mediatypes=false" \
  --file "$CONTEXT_DIR/Dockerfile.agentarts-koophone" \
  --tag "$IMAGE_REF" \
  "$CONTEXT_DIR"

actual_platform="$(docker image inspect "$IMAGE_REF" --format '{{.Os}}/{{.Architecture}}')"
if [[ "$actual_platform" != "$TARGET_PLATFORM" ]]; then
  printf 'built image platform is %s, expected %s\n' "$actual_platform" "$TARGET_PLATFORM" >&2
  exit 1
fi

sdk_version="$(docker run --rm --entrypoint python "$IMAGE_REF" -c \
  'import importlib.metadata; print(importlib.metadata.version("agentarts-sdk"))')"
if [[ "$sdk_version" != "0.1.5" ]]; then
  printf 'agentarts-sdk version is %s, expected 0.1.5\n' "$sdk_version" >&2
  exit 1
fi

"$SCRIPT_DIR/check-agentarts-image.sh" "$IMAGE_REF" >/dev/null

printf 'image=%s\nplatform=%s\nagentarts_sdk=%s\nmedia_types=non-oci\n' \
  "$IMAGE_REF" "$actual_platform" "$sdk_version"
