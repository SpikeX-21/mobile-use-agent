#!/usr/bin/env bash
set -euo pipefail

# Inspect a local image, or a registry manifest, without printing labels,
# environment variables, layers, or any other secret-bearing image metadata.

if [[ $# -ne 1 || -z "${1:-}" ]]; then
  printf 'usage: %s IMAGE[:TAG]\n' "$0" >&2
  exit 2
fi
IMAGE_REF="$1"
if ! command -v docker >/dev/null 2>&1; then
  printf 'docker is required\n' >&2
  exit 2
fi

check_media_types() {
  local manifest_file="$1"
  python3 - "$manifest_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    document = json.load(stream)

media_types = []
def visit(value):
    if isinstance(value, dict):
        media_type = value.get("mediaType")
        if isinstance(media_type, str):
            media_types.append(media_type)
        for child in value.values():
            visit(child)
    elif isinstance(value, list):
        for child in value:
            visit(child)

visit(document)
oci_types = sorted({item for item in media_types if item.startswith("application/vnd.oci.")})
if oci_types:
    print("OCI media types detected: " + ", ".join(oci_types), file=sys.stderr)
    raise SystemExit(1)
print("media_types=non-oci")
PY
}

check_remote_platform() {
  local manifest_file="$1"
  python3 - "$manifest_file" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    document = json.load(stream)

platforms = []
def visit(value):
    if isinstance(value, dict):
        platform = value.get("platform")
        if isinstance(platform, dict):
            platforms.append(platform)
        for child in value.values():
            visit(child)
    elif isinstance(value, list):
        for child in value:
            visit(child)

visit(document)
if not any(
    item.get("os") == "linux" and item.get("architecture") == "arm64"
    for item in platforms
):
    print("registry manifest does not expose linux/arm64", file=sys.stderr)
    raise SystemExit(1)
PY
}

if docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
  platform="$(docker image inspect "$IMAGE_REF" --format '{{.Os}}/{{.Architecture}}')"
  if [[ "$platform" != "linux/arm64" ]]; then
    printf 'image platform is %s, expected linux/arm64\n' "$platform" >&2
    exit 1
  fi

  descriptor_media_type=""
  if ! descriptor_media_type="$(docker image inspect "$IMAGE_REF" \
    --format '{{.Descriptor.MediaType}}' 2>/dev/null)"; then
    descriptor_media_type=""
  fi
  if [[ -z "$descriptor_media_type" ]]; then
    # Docker's classic image store (supported by Docker 27+) may not expose
    # Descriptor.MediaType. The Docker archive exporter is the format used by
    # `docker push` from that store; check its manifest and report the weaker,
    # explicit export evidence instead of rejecting a supported daemon.
    archive="$(mktemp)"
    manifest="$(mktemp)"
    cleanup() {
      rm -f "$archive" "$manifest"
    }
    trap cleanup EXIT
    docker save --output "$archive" "$IMAGE_REF"
    tar -xOf "$archive" manifest.json >"$manifest"
    check_media_types "$manifest"
    printf 'image=%s\nplatform=%s\nmedia_types=non-oci-export\nsource=local\n' \
      "$IMAGE_REF" "$platform"
    exit 0
  fi
  if [[ "$descriptor_media_type" == application/vnd.oci.* ]]; then
    printf 'OCI media type detected: %s\n' "$descriptor_media_type" >&2
    exit 1
  fi
  printf 'image=%s\nplatform=%s\nmedia_types=%s\nsource=local\n' \
    "$IMAGE_REF" "$platform" "$descriptor_media_type"
  exit 0
fi

manifest="$(mktemp)"
cleanup() {
  rm -f "$manifest"
}
trap cleanup EXIT
docker manifest inspect --verbose "$IMAGE_REF" >"$manifest"
check_media_types "$manifest"
check_remote_platform "$manifest"
printf 'image=%s\nsource=registry\n' "$IMAGE_REF"
