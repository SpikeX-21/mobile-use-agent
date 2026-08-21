# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Safe deployment contracts for the private AgentArts KooPhone POC.

This module deliberately separates secret-bearing request construction from
the redacted evidence that may be written to disk or attached to an issue.
It does not import application settings, so loading the deployment helpers can
never accidentally log or validate the local model/device credentials.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Mapping


AGENT_NAME = "mobile-use-koophone-poc-test1"
ENTRYPOINT = "app:app"
REGION = "cn-southwest-2"
DEPENDENCY_FILE = "requirements.txt"
ENDPOINT_NAME = "dev"
EXECUTION_AGENCY_NAME = "DefaultAgentArtsRuntimeAgency"
EXECUTION_AGENCY_PRINCIPAL = "service.WorkloadSandboxMetadata"
EXECUTION_AGENCY_POLICIES = frozenset(
    {
        "AgentArtsCoreRunRuntimeIdentityAgencyPolicy",
        "AgentArtsCoreRunRuntimeOpsAgencyPolicy",
    }
)

_CREDENTIAL_HEADERS = ("User Name", "Access Key Id", "Secret Access Key")
_VERSION_PATTERN = re.compile(r"^v[0-9]+$")

_REQUIRED_RUNTIME_ENV_KEYS = frozenset(
    {
        "ENV",
        "MODEL_PROVIDER",
        "DEVICE_PROVIDER",
        "KIMI_API_KEY",
        "KIMI_MODEL",
        "KIMI_BASE_URL",
        "KIMI_THINKING_MODE",
        "KOOPHONE_MCP_URL",
        "KOOPHONE_INSTANCE_ID",
        "KOOPHONE_INPUT_WIDTH",
        "KOOPHONE_INPUT_HEIGHT",
        "KOOPHONE_TLS_VERIFY",
        "KOOPHONE_IAM_AUTH_URL",
        "KOOPHONE_IAM_DOMAIN",
        "KOOPHONE_IAM_USERNAME",
        "KOOPHONE_IAM_PASSWORD",
        "KOOPHONE_IAM_PROJECT",
        "KOOPHONE_JKS_STORE_PASSWORD",
        "KOOPHONE_JKS_KEY_PASSWORD",
        "KOOPHONE_JKS_ALIAS",
        "KOOPHONE_JWT_TTL_MINUTES",
    }
)
_OPTIONAL_RUNTIME_ENV_KEYS = frozenset(
    {
        "AGENT_TASK_TIMEOUT_SECONDS",
        "KOOPHONE_CA_BUNDLE",
    }
)
_RUNTIME_ENV_KEYS = _REQUIRED_RUNTIME_ENV_KEYS | _OPTIONAL_RUNTIME_ENV_KEYS
_RUNTIME_ENV_DEFAULTS = {"AGENT_TASK_TIMEOUT_SECONDS": "900"}


class DeploymentError(RuntimeError):
    """A field-level deployment failure that never includes secret values."""


@dataclass(frozen=True, repr=False)
class HuaweiCredentials:
    """Huawei control-plane credentials with a permanently redacted repr."""

    username: str
    access_key: str
    secret_key: str

    def __repr__(self) -> str:
        return "HuaweiCredentials(username=<redacted>, access_key=<redacted>, secret_key=<redacted>)"


@dataclass(frozen=True)
class RuntimeRelease:
    """Safe identifiers collected after a successful deployment."""

    region: str
    agent_name: str
    swr_organization: str
    swr_repository: str
    image_tag: str
    image_digest: str
    runtime_id: str
    runtime_version: str
    endpoint_id: str
    endpoint_name: str
    gateway_id: str
    access_domain: str
    logs_enabled: bool = False
    log_project_id: str | None = None
    log_group_id: str | None = None
    log_stream_id: str | None = None


def _require_private_regular_file(path: Path, label: str) -> None:
    try:
        file_stat = path.lstat()
    except OSError:
        raise DeploymentError(f"{label} is unavailable") from None
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size <= 0:
        raise DeploymentError(f"{label} must be a non-empty regular file")
    if stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise DeploymentError(f"{label} mode must not grant group or other access")


def load_huawei_credentials(path: Path) -> HuaweiCredentials:
    """Read exactly one AK/SK row without ever returning printable secrets."""

    _require_private_regular_file(path, "credentials.csv")
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != _CREDENTIAL_HEADERS:
                raise DeploymentError("credentials.csv schema is invalid")
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error):
        raise DeploymentError("credentials.csv could not be read") from None
    if len(rows) != 1:
        raise DeploymentError("credentials.csv must contain exactly one credential row")
    row = rows[0]
    values = tuple((row.get(key) or "").strip() for key in _CREDENTIAL_HEADERS)
    if not all(values):
        raise DeploymentError("credentials.csv contains an empty required field")
    return HuaweiCredentials(
        username=values[0],
        access_key=values[1],
        secret_key=values[2],
    )


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()
    if "=" not in stripped:
        raise DeploymentError("runtime .env contains an invalid assignment")
    key, raw_value = stripped.split("=", 1)
    key = key.strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        raise DeploymentError("runtime .env contains an invalid variable name")
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return key, value


def load_runtime_environment(path: Path) -> dict[str, str]:
    """Load only the allowlisted Runtime variables from a private local file."""

    _require_private_regular_file(path, "runtime .env")
    try:
        assignments = (
            parsed
            for parsed in (_parse_env_line(line) for line in path.read_text().splitlines())
            if parsed is not None
        )
        source = dict(assignments)
    except (OSError, UnicodeError):
        raise DeploymentError("runtime .env could not be read") from None
    missing = sorted(
        key for key in _REQUIRED_RUNTIME_ENV_KEYS if not source.get(key, "").strip()
    )
    if missing:
        raise DeploymentError("runtime .env is missing required variables: " + ", ".join(missing))
    if source["ENV"].strip().lower() != "poc":
        raise DeploymentError("runtime .env ENV must be poc")
    if source["MODEL_PROVIDER"].strip().lower() != "kimi":
        raise DeploymentError("runtime .env MODEL_PROVIDER must be kimi")
    if source["DEVICE_PROVIDER"].strip().lower() != "koophone_mcp":
        raise DeploymentError("runtime .env DEVICE_PROVIDER must be koophone_mcp")
    if source["KIMI_MODEL"].strip() != "kimi-k2.6":
        raise DeploymentError("runtime .env KIMI_MODEL must be kimi-k2.6")
    if source["KIMI_THINKING_MODE"].strip().lower() != "disabled":
        raise DeploymentError("runtime .env KIMI_THINKING_MODE must be disabled")
    runtime_environment = {
        key: source[key] for key in sorted(_RUNTIME_ENV_KEYS) if key in source
    }
    for key, value in _RUNTIME_ENV_DEFAULTS.items():
        runtime_environment.setdefault(key, value)
    return runtime_environment


def default_swr_organization(access_key: str) -> str:
    """Mirror the audited AgentArts CLI's default per-account organization."""

    suffix = hashlib.md5(access_key.encode(), usedforsecurity=False).hexdigest()[:8]
    return f"agentarts-cnso2-{suffix}-org"


def default_swr_repository(agent_name: str = AGENT_NAME) -> str:
    return f"agent_{agent_name}"


def make_image_tag(commit: str, now: datetime | None = None) -> str:
    """Create a unique non-latest tag from a commit and UTC timestamp."""

    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise DeploymentError("git commit is invalid")
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise DeploymentError("release timestamp must be timezone-aware")
    utc = instant.astimezone(timezone.utc)
    return f"issue25-{commit[:7].lower()}-{utc:%Y%m%dt%H%M%Sz}"


def load_or_create_inbound_api_key(path: Path) -> str:
    """Create the local POC bearer secret once, or load the existing value."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        descriptor = None
    except OSError:
        raise DeploymentError("inbound API key file could not be created") from None
    if descriptor is not None:
        value = secrets.token_urlsafe(48)
        try:
            os.write(descriptor, value.encode("ascii"))
            os.fsync(descriptor)
        except OSError:
            try:
                path.unlink()
            except OSError:
                pass
            raise DeploymentError("inbound API key file could not be written") from None
        finally:
            os.close(descriptor)
    _require_private_regular_file(path, "inbound API key file")
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise DeploymentError("inbound API key file could not be read") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", value):
        raise DeploymentError("inbound API key file is invalid")
    return value


def build_runtime_payload(
    *,
    image_ref: str,
    runtime_environment: Mapping[str, str],
    inbound_api_key: str,
    logs_configuration: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Construct the secret-bearing CreateCoreRuntime body in memory only."""

    if not image_ref or image_ref.endswith(":latest") or "@" in image_ref:
        raise DeploymentError("image_ref must use an explicit non-latest tag")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,512}", inbound_api_key):
        raise DeploymentError("inbound API key is invalid")
    missing = sorted(key for key in _REQUIRED_RUNTIME_ENV_KEYS if not runtime_environment.get(key))
    if missing:
        raise DeploymentError("runtime environment is incomplete")
    logs = validate_logs_configuration(logs_configuration or {"enabled": False})
    env_vars = [
        {"key": key, "value": value}
        for key, value in sorted(runtime_environment.items())
        if key in _RUNTIME_ENV_KEYS
    ]
    return {
        "name": AGENT_NAME,
        "description": "Internal fixed-EID KooPhone POC",
        "artifact_source_config": {"url": image_ref, "commands": []},
        "env_vars": env_vars,
        "identity_config": {
            "authorizer_type": "API_KEY",
            "authorizer_configuration": {
                "key_auth": {
                    "api_keys": [
                        {
                            "api_key": inbound_api_key,
                            "api_key_name": "internal-poc",
                        }
                    ]
                }
            },
        },
        "execution_agency_name": EXECUTION_AGENCY_NAME,
        "network_config": {"network_mode": "PUBLIC"},
        "invoke_config": {
            "protocol": "HTTP",
            "port": 8080,
            "file_transfer_config": {"enabled": False},
            "url_match_type": "ACCURATE_MATCH",
        },
        "observability": {
            "logs": logs,
            "metrics": {"enabled": False},
            "tracing": {"enabled": False},
        },
        "storage_config": {},
        "tags_config": [
            {"key": "environment", "value": "internal-poc"},
            {"key": "component", "value": "mobile-use-koophone"},
        ],
        "arch": "arm64",
    }


def build_endpoint_payload(version: str) -> dict[str, str]:
    """Pin the named dev Endpoint to a concrete platform version."""

    if not _VERSION_PATTERN.fullmatch(version):
        raise DeploymentError("runtime endpoint requires an explicit version")
    return {
        "name": ENDPOINT_NAME,
        "target_version_name": version,
        "description": "Internal POC pinned endpoint",
    }


def validate_private_repository(repository: Mapping[str, object]) -> None:
    """Fail closed if SWR does not explicitly report private visibility."""

    if "is_public" not in repository:
        raise DeploymentError("SWR repository visibility was not returned")
    if repository["is_public"] is not False:
        raise DeploymentError("SWR repository must remain private")


def _safe_cloud_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value)
    )


def validate_logs_configuration(
    configuration: Mapping[str, object],
) -> dict[str, object]:
    """Allow only a complete disabled or LTS-backed log configuration."""

    enabled = configuration.get("enabled")
    if enabled is False and set(configuration) == {"enabled"}:
        return {"enabled": False}
    required = {"enabled", "project_id", "group_id", "stream_id"}
    if enabled is not True or set(configuration) != required:
        raise DeploymentError("AgentArts log configuration is incomplete")
    for key in ("project_id", "group_id", "stream_id"):
        if not _safe_cloud_identifier(configuration.get(key)):
            raise DeploymentError("AgentArts log configuration is invalid")
    return {key: configuration[key] for key in ("enabled", "project_id", "group_id", "stream_id")}


def logs_configuration_from_state(state: Mapping[str, object]) -> dict[str, object]:
    """Recover the safe LTS identifiers that future Runtime versions must preserve."""

    if state.get("logs", False) is False:
        return {"enabled": False}
    return validate_logs_configuration(
        {
            "enabled": state.get("logs"),
            "project_id": state.get("log_project_id"),
            "group_id": state.get("log_group_id"),
            "stream_id": state.get("log_stream_id"),
        }
    )


def validate_log_enabled_successor(
    runtime: Mapping[str, object],
    state: Mapping[str, object],
    expected_environment_keys: set[str],
) -> tuple[str, dict[str, object]]:
    """Validate a console-created logs-only successor before pinning ``dev``.

    This deliberately compares only environment key names: control-plane
    responses may mask secret values, and copying them into diagnostics would
    violate the deployment boundary.
    """

    runtime_id = state.get("runtime_id")
    current_version = state.get("runtime_version")
    if (
        runtime.get("id") != runtime_id
        or runtime.get("name") != AGENT_NAME
        or runtime.get("status") != "READY"
    ):
        raise DeploymentError("logs-enabled Runtime identity or status is invalid")
    version = runtime.get("latest_version")
    detail = runtime.get("version_detail")
    if (
        not isinstance(version, str)
        or not _VERSION_PATTERN.fullmatch(version)
        or version == current_version
        or not isinstance(detail, dict)
        or detail.get("version") != version
    ):
        raise DeploymentError("logs-enabled Runtime version is invalid")

    artifact = detail.get("artifact_source")
    organization = state.get("swr_organization")
    repository = state.get("swr_repository")
    image_tag = state.get("image_tag")
    image_digest = state.get("image_digest")
    if not all(
        _safe_cloud_identifier(value)
        for value in (organization, repository, image_tag)
    ) or not isinstance(image_digest, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", image_digest
    ):
        raise DeploymentError("approved Runtime artifact state is invalid")
    expected_url = (
        f"swr.{REGION}.myhuaweicloud.com/{organization}/{repository}:{image_tag}"
    )
    if (
        not isinstance(artifact, dict)
        or not isinstance(artifact.get("url"), str)
        or artifact["url"] != expected_url
        or artifact.get("commands", []) != []
    ):
        raise DeploymentError("logs-enabled Runtime artifact changed")

    environment = detail.get("environment_variables")
    if not isinstance(environment, list):
        raise DeploymentError("logs-enabled Runtime environment is invalid")
    keys = [
        item.get("key")
        for item in environment
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    ]
    if (
        len(keys) != len(environment)
        or len(keys) != len(set(keys))
        or set(keys) != expected_environment_keys
        or "AGENTARTS_RUNTIME_API_KEY" in keys
    ):
        raise DeploymentError("logs-enabled Runtime environment changed")

    invoke = detail.get("invoke_config")
    if not isinstance(invoke, dict) or any(
        invoke.get(key) != value
        for key, value in {
            "protocol": "HTTP",
            "port": 8080,
            "url_match_type": "ACCURATE_MATCH",
        }.items()
    ):
        raise DeploymentError("logs-enabled Runtime invocation contract changed")
    allowed_invoke_fields = {
        "protocol",
        "port",
        "url_match_type",
        "access_endpoint",
        "file_transfer_config",
    }
    if not set(invoke).issubset(allowed_invoke_fields):
        raise DeploymentError("logs-enabled Runtime invocation contract changed")
    if invoke.get("access_endpoint") != state.get("access_domain"):
        raise DeploymentError("logs-enabled Runtime access endpoint changed")
    if invoke.get("file_transfer_config", {"enabled": False}) != {"enabled": False}:
        raise DeploymentError("logs-enabled Runtime file transfer changed")
    if detail.get("network_config") != {"network_mode": "PUBLIC"}:
        raise DeploymentError("logs-enabled Runtime outbound network changed")
    if detail.get("execution_agency_name") != EXECUTION_AGENCY_NAME:
        raise DeploymentError("logs-enabled Runtime execution agency changed")
    if detail.get("storage_config") not in ({}, {"sfs_turbo": []}):
        raise DeploymentError("logs-enabled Runtime storage changed")

    observability = detail.get("observability")
    if (
        not isinstance(observability, dict)
        or observability.get("metrics") != {"enabled": False}
        or observability.get("tracing") != {"enabled": False}
    ):
        raise DeploymentError("logs-enabled Runtime observability changed")
    logs = validate_logs_configuration(observability.get("logs") or {})
    if logs["enabled"] is not True:
        raise DeploymentError("logs-enabled Runtime logs are disabled")
    return version, logs


def validate_inbound_key_state(
    state: Mapping[str, object] | None,
    inbound_api_key: str,
) -> str:
    """Reject implicit key rotation before an immutable Runtime update.

    The AgentArts update API creates a new Runtime version but does not update
    the gateway identity configuration. Losing the ignored local key must
    therefore stop deployment instead of silently publishing an unusable
    version.
    """

    fingerprint = hashlib.sha256(inbound_api_key.encode("ascii")).hexdigest()
    if state is None:
        return fingerprint
    recorded = state.get("inbound_key_sha256")
    if not isinstance(recorded, str) or not re.fullmatch(r"[0-9a-f]{64}", recorded):
        raise DeploymentError("inbound API key state is missing; explicit rotation is required")
    if not secrets.compare_digest(recorded, fingerprint):
        raise DeploymentError("inbound API key rotation requires an explicit recovery workflow")
    return fingerprint


def validate_execution_agency(
    trust_policy: object,
    policy_names: list[str],
) -> None:
    """Require the exact minimal trust principal and attached policy set."""

    if isinstance(trust_policy, str):
        try:
            trust_policy = json.loads(trust_policy)
        except json.JSONDecodeError:
            raise DeploymentError("runtime agency trust policy is invalid") from None
    if not isinstance(trust_policy, dict):
        raise DeploymentError("runtime agency trust policy is invalid")
    if trust_policy.get("Version") != "5.0":
        raise DeploymentError("runtime agency trust policy is invalid")
    statements = trust_policy.get("Statement")
    if not isinstance(statements, list) or len(statements) != 1:
        raise DeploymentError("runtime agency trust policy is not minimal")
    statement = statements[0]
    if not isinstance(statement, dict) or statement.get("Effect") != "Allow":
        raise DeploymentError("runtime agency trust policy is invalid")
    actions = statement.get("Action")
    if isinstance(actions, str):
        actions = [actions]
    if actions != ["sts:agencies:assume"]:
        raise DeploymentError("runtime agency trust policy is invalid")
    principal = statement.get("Principal")
    if not isinstance(principal, dict) or set(principal) != {"Service"}:
        raise DeploymentError("runtime agency trust policy is not minimal")
    services = principal["Service"]
    if isinstance(services, str):
        services = [services]
    if services != [EXECUTION_AGENCY_PRINCIPAL]:
        raise DeploymentError("runtime agency trust policy is not minimal")
    if set(policy_names) != EXECUTION_AGENCY_POLICIES or len(policy_names) != len(
        EXECUTION_AGENCY_POLICIES
    ):
        raise DeploymentError("runtime agency attached policies are not minimal")


def _validate_runtime_response(response: object) -> dict[str, object]:
    if not isinstance(response, dict):
        raise DeploymentError("AgentArts runtime response is invalid")
    runtime_id = response.get("id")
    version = response.get("latest_version")
    if not isinstance(runtime_id, str) or not runtime_id:
        raise DeploymentError("AgentArts runtime response is missing id")
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise DeploymentError("AgentArts runtime response is missing version")
    return response


def create_or_update_runtime(
    client: object,
    payload: Mapping[str, object],
    expected_runtime_id: str | None,
) -> dict[str, object]:
    """Create a Runtime, or add a version only to the locally owned Runtime."""

    name = payload.get("name")
    if name != AGENT_NAME:
        raise DeploymentError("AgentArts runtime name is invalid")
    existing = client.find_agent_by_name(AGENT_NAME)
    if existing is not None:
        existing_id = existing.get("id") if isinstance(existing, dict) else None
        if not expected_runtime_id or existing_id != expected_runtime_id:
            raise DeploymentError("AgentArts runtime name already exists outside local state")
        update_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"name", "identity_config"}
        }
        response = client.update_agent(agent_id=existing_id, **update_payload)
        return _validate_runtime_response(response)
    if expected_runtime_id:
        raise DeploymentError("locally owned AgentArts runtime no longer exists")
    response = client.create_agent(**dict(payload))
    return _validate_runtime_response(response)


def _control_data(result: object, operation: str) -> dict[str, object]:
    if not getattr(result, "success", False):
        status = getattr(result, "status_code", "unknown")
        raise DeploymentError(f"AgentArts {operation} failed with HTTP {status}")
    data = getattr(result, "data", None)
    if not isinstance(data, dict):
        raise DeploymentError(f"AgentArts {operation} returned an invalid response")
    return data


def pin_dev_endpoint(client: object, runtime_id: str, version: str) -> dict[str, object]:
    """Create or update ``dev`` using endpoint IDs and documented wire fields."""

    payload = build_endpoint_payload(version)
    listing = _control_data(
        client._control("GET", f"/v1/core/runtimes/{runtime_id}/endpoints"),
        "endpoint list",
    )
    items = listing.get("items", [])
    if not isinstance(items, list):
        raise DeploymentError("AgentArts endpoint list is invalid")
    dev_items = [
        item
        for item in items
        if isinstance(item, dict) and item.get("name") == ENDPOINT_NAME
    ]
    if len(dev_items) > 1:
        raise DeploymentError("AgentArts returned duplicate dev endpoints")
    if dev_items:
        endpoint_id = dev_items[0].get("id")
        if not isinstance(endpoint_id, str) or not endpoint_id:
            raise DeploymentError("AgentArts dev endpoint is missing id")
        update = {
            "target_version_name": payload["target_version_name"],
            "description": payload["description"],
        }
        result = client._control(
            "PUT",
            f"/v1/core/runtimes/{runtime_id}/endpoints/{endpoint_id}",
            json=update,
        )
    else:
        result = client._control(
            "POST",
            f"/v1/core/runtimes/{runtime_id}/endpoints",
            json=payload,
        )
    response = _control_data(result, "dev endpoint pin")
    if response.get("name") != ENDPOINT_NAME:
        raise DeploymentError("AgentArts dev endpoint response is invalid")
    if response.get("target_version_name") != version:
        raise DeploymentError("AgentArts dev endpoint is not pinned to requested version")
    return response


def public_evidence(release: RuntimeRelease) -> dict[str, object]:
    """Return the only deployment fields allowed in durable evidence."""

    evidence: dict[str, object] = {
        "region": release.region,
        "agent_name": release.agent_name,
        "swr_organization": release.swr_organization,
        "swr_repository": release.swr_repository,
        "image_tag": release.image_tag,
        "image_digest": release.image_digest,
        "runtime_id": release.runtime_id,
        "runtime_version": release.runtime_version,
        "endpoint_id": release.endpoint_id,
        "endpoint_name": release.endpoint_name,
        "gateway_id": release.gateway_id,
        "access_domain": release.access_domain,
        "port": 8080,
        "protocol": "HTTP",
        "url_match_type": "ACCURATE_MATCH",
        "outbound_network": "PUBLIC",
        "inbound_auth": "API_KEY",
        "session_storage": False,
        "file_transfer": False,
        "logs": release.logs_enabled,
        "metrics": False,
        "tracing": False,
        "probe": "platform-default",
    }
    if release.logs_enabled:
        identifiers = {
            "log_project_id": release.log_project_id,
            "log_group_id": release.log_group_id,
            "log_stream_id": release.log_stream_id,
        }
        if not all(_safe_cloud_identifier(value) for value in identifiers.values()):
            raise DeploymentError("AgentArts release log configuration is invalid")
        evidence.update(identifiers)
    return evidence
