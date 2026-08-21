#!/usr/bin/env bash
set -euo pipefail

# Run the AgentArts image under the same hardening used by the local contract:
# non-root image user, read-only root filesystem, and a small explicit /tmp.

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
COMPONENT_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)"
IMAGE_REF="${IMAGE_REF:-${IMAGE_REPOSITORY:-mobile-use-agent-agentarts}:${IMAGE_TAG:-latest}}"
ENV_FILE="${ENV_FILE:-$COMPONENT_ROOT/.env}"
CONTAINER_NAME="${CONTAINER_NAME:-mobile-use-agent-agentarts}"
AGENT_RUN_PORT="${AGENT_RUN_PORT:-8080}"
HOST_PORT="${HOST_PORT:-$AGENT_RUN_PORT}"

if ! command -v docker >/dev/null 2>&1; then
  printf 'docker is required\n' >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  printf 'runtime env file is required: %s\n' "$ENV_FILE" >&2
  exit 2
fi
if [[ ! "$AGENT_RUN_PORT" =~ ^[0-9]+$ || "$AGENT_RUN_PORT" -lt 1 || "$AGENT_RUN_PORT" -gt 65535 ]]; then
  printf 'AGENT_RUN_PORT must be between 1 and 65535\n' >&2
  exit 2
fi
if [[ ! "$HOST_PORT" =~ ^[0-9]+$ || "$HOST_PORT" -lt 1 || "$HOST_PORT" -gt 65535 ]]; then
  printf 'HOST_PORT must be between 1 and 65535\n' >&2
  exit 2
fi

exec docker run --rm \
  --name "$CONTAINER_NAME" \
  --publish "$HOST_PORT:$AGENT_RUN_PORT" \
  --env-file "$ENV_FILE" \
  --env "AGENT_RUN_PORT=$AGENT_RUN_PORT" \
  --env "MOBILE_CONFIG_PATH=/opt/mobile-agent/config.toml" \
  --env "KOOPHONE_JKS_PATH=/opt/mobile-agent/secrets/koophone.jks" \
  --env "EXPERIMENT_RECORD_PATH=/tmp/mobile-agent/experiment-runs.jsonl" \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  "$IMAGE_REF"
