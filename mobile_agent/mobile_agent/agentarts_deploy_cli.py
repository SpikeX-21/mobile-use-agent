# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Publish the internal KooPhone image and create the AgentArts dev Runtime.

The command intentionally accepts no secret values on the command line. Huawei
credentials, Runtime variables, the baked JKS and the generated inbound bearer
key all remain in ignored, owner-only local files or process memory.
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterator, Mapping

from agentarts.sdk.service.iam_client import IAMClient
from agentarts.sdk.service.runtime_client import RuntimeClient
from agentarts.sdk.service.swr_client import SWRClient
from agentarts.sdk.utils.constant import get_control_plane_endpoint
from huaweicloudsdkcore.exceptions.exceptions import ServiceResponseException
from huaweicloudsdkiam.v5.model import (
    GetAgencyV5Request,
    ListAttachedAgencyPoliciesV5Request,
)
from huaweicloudsdkswr.v2 import ShowRepoTagRequest

from mobile_agent.agentarts_deployment import (
    AGENT_NAME,
    ENDPOINT_NAME,
    EXECUTION_AGENCY_NAME,
    REGION,
    DeploymentError,
    HuaweiCredentials,
    RuntimeRelease,
    build_runtime_payload,
    create_or_update_runtime,
    default_swr_organization,
    default_swr_repository,
    load_huawei_credentials,
    load_or_create_inbound_api_key,
    load_runtime_environment,
    logs_configuration_from_state,
    make_image_tag,
    pin_dev_endpoint,
    public_evidence,
    validate_private_repository,
    validate_execution_agency,
    validate_inbound_key_state,
    validate_log_enabled_successor,
)


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = COMPONENT_ROOT.parent
LOCAL_IMAGE = "mobile-use-agent-agentarts:invocation-operations"
STATE_DIRECTORY = COMPONENT_ROOT / ".agentarts" / AGENT_NAME
STATE_PATH = STATE_DIRECTORY / "deployment-state.json"
PENDING_STATE_PATH = STATE_DIRECTORY / "deployment-pending.json"
INBOUND_KEY_PATH = STATE_DIRECTORY / "inbound-api-key"
CREDENTIALS_PATH = COMPONENT_ROOT / "credentials.csv"
RUNTIME_ENV_PATH = COMPONENT_ROOT / ".env"
IMAGE_CHECK = COMPONENT_ROOT / "scripts" / "check-agentarts-image.sh"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_HUAWEI_ENVIRONMENT_KEYS = (
    "HUAWEICLOUD_SDK_AK",
    "HUAWEICLOUD_SDK_SK",
    "HUAWEICLOUD_SDK_REGION",
)


def _safe_run(
    command: list[str],
    *,
    input_text: str | None = None,
    timeout: float = 900,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a local command while retaining output only for safe parsing."""

    child_environment = os.environ.copy()
    if environment:
        child_environment.update(environment)
    for key in _HUAWEI_ENVIRONMENT_KEYS:
        child_environment.pop(key, None)
    try:
        return subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=child_environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DeploymentError("local deployment command failed") from None


def _require_command_success(
    command: list[str],
    *,
    operation: str,
    input_text: str | None = None,
    timeout: float = 900,
    environment: Mapping[str, str] | None = None,
) -> str:
    result = _safe_run(
        command,
        input_text=input_text,
        timeout=timeout,
        environment=environment,
    )
    if result.returncode != 0:
        raise DeploymentError(f"{operation} failed")
    return result.stdout + result.stderr


def _read_private_state(path: Path, label: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            raise DeploymentError(f"{label} permissions are invalid")
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise DeploymentError(f"{label} could not be read") from None
    if not isinstance(state, dict) or state.get("agent_name") != AGENT_NAME:
        raise DeploymentError(f"{label} is invalid")
    return state


def _read_state() -> dict[str, Any] | None:
    return _read_private_state(STATE_PATH, "deployment state")


def _read_pending_state() -> dict[str, Any] | None:
    return _read_private_state(PENDING_STATE_PATH, "pending deployment state")


def _write_private_state(path: Path, state: dict[str, Any], label: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=True, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise DeploymentError(f"{label} could not be written") from None


def _write_state(state: dict[str, Any]) -> None:
    _write_private_state(STATE_PATH, state, "deployment state")


def _write_pending_state(state: dict[str, Any]) -> None:
    _write_private_state(PENDING_STATE_PATH, state, "pending deployment state")


def _clear_pending_state() -> None:
    try:
        PENDING_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        raise DeploymentError("pending deployment state could not be cleared") from None


@contextlib.contextmanager
def _huawei_environment(access_key: str, secret_key: str) -> Iterator[None]:
    """Expose SDK credentials only while control-plane clients are in use."""

    previous = {key: os.environ.get(key) for key in _HUAWEI_ENVIRONMENT_KEYS}
    os.environ["HUAWEICLOUD_SDK_AK"] = access_key
    os.environ["HUAWEICLOUD_SDK_SK"] = secret_key
    os.environ["HUAWEICLOUD_SDK_REGION"] = REGION
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def _deployment_logging_disabled() -> Iterator[None]:
    """Suppress secret-bearing SDK logs without mutating the caller permanently."""

    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _git_commit() -> str:
    output = _require_command_success(
        ["git", "rev-parse", "HEAD"], operation="git revision lookup", timeout=10
    ).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", output):
        raise DeploymentError("git revision lookup returned an invalid commit")
    return output


def _validate_local_image(image: str) -> None:
    _require_command_success(
        [str(IMAGE_CHECK), image], operation="local ARM64 image validation", timeout=180
    )
    inspect = _require_command_success(
        ["docker", "image", "inspect", image, "--format", "{{.Os}}/{{.Architecture}}"],
        operation="local image inspection",
        timeout=30,
    ).strip()
    if inspect != "linux/arm64":
        raise DeploymentError("local image is not linux/arm64")


def _audit_execution_agency() -> dict[str, object]:
    """Verify the exact trust principal and minimal attached policy set."""

    wrapper = IAMClient()
    client = wrapper._get_iam_client()
    response = wrapper.list_agencies(limit=200)
    agencies = [
        agency
        for agency in (response.agencies or [])
        if agency.agency_name == EXECUTION_AGENCY_NAME
    ]
    if len(agencies) != 1:
        raise DeploymentError("DefaultAgentArtsRuntimeAgency is unavailable or ambiguous")
    agency = agencies[0]
    detail = client.get_agency_v5(GetAgencyV5Request(agency_id=agency.agency_id)).agency
    trust_policy = getattr(detail, "trust_policy", "") or ""
    policy_response = client.list_attached_agency_policies_v5(
        ListAttachedAgencyPoliciesV5Request(agency_id=agency.agency_id, limit=200)
    )
    policies = policy_response.attached_policies or []
    names = sorted(policy.policy_name for policy in policies)
    validate_execution_agency(trust_policy, names)
    return {
        "name": EXECUTION_AGENCY_NAME,
        "id": agency.agency_id,
        "trust": "service.WorkloadSandboxMetadata",
        "attached_policies": names,
    }


def _ensure_swr_repository(
    client: SWRClient,
    organization: str,
    repository: str,
) -> dict[str, Any]:
    """Create the SDK defaults while suppressing its unredacted exception output."""

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        org = client.create_or_get_organization(organization)
        repo = client.create_or_get_repository(
            organization,
            repository,
            is_public=False,
        )
    if org is None:
        raise DeploymentError("default SWR organization could not be created or queried")
    if repo is None:
        raise DeploymentError("default SWR repository could not be created or queried")
    validate_private_repository(repo)
    return repo


def _tag_exists(client: SWRClient, organization: str, repository: str, tag: str) -> bool:
    try:
        client._get_client().show_repo_tag(
            ShowRepoTagRequest(namespace=organization, repository=repository, tag=tag)
        )
    except ServiceResponseException as exc:
        if exc.status_code == 404:
            return False
        raise DeploymentError("SWR tag preflight failed") from None
    except Exception:
        raise DeploymentError("SWR tag preflight failed") from None
    return True


def _query_swr_digest(
    client: SWRClient,
    organization: str,
    repository: str,
    tag: str,
) -> str:
    """Return the live digest for one exact private SWR tag."""

    try:
        response = client._get_client().show_repo_tag(
            ShowRepoTagRequest(
                namespace=organization,
                repository=repository,
                tag=tag,
            )
        )
    except Exception:
        raise DeploymentError("published SWR tag could not be queried") from None
    digest = getattr(response, "digest", "")
    if not isinstance(digest, str) or not _DIGEST_PATTERN.fullmatch(digest):
        raise DeploymentError("published SWR tag digest is invalid")
    return digest


def _publish_image(
    client: SWRClient,
    *,
    local_image: str,
    organization: str,
    repository: str,
    tag: str,
) -> tuple[str, str]:
    if _tag_exists(client, organization, repository, tag):
        raise DeploymentError("SWR image tag already exists and will not be overwritten")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        login_server, username, password = client.create_swr_secret()
    if not username or not password:
        raise DeploymentError("SWR temporary login credential could not be created")
    remote = client.get_full_image_name(organization, repository, tag)
    with tempfile.TemporaryDirectory(prefix="agentarts-docker-") as directory:
        Path(directory).chmod(0o700)
        docker_environment = {"DOCKER_CONFIG": directory}
        _require_command_success(
            ["docker", "login", login_server, "--username", username, "--password-stdin"],
            operation="SWR login",
            input_text=password,
            timeout=60,
            environment=docker_environment,
        )
        _require_command_success(
            ["docker", "tag", local_image, remote],
            operation="SWR image tag",
            environment=docker_environment,
        )
        _require_command_success(
            ["docker", "push", remote],
            operation="SWR image push",
            timeout=1200,
            environment=docker_environment,
        )
        _require_command_success(
            [str(IMAGE_CHECK), remote],
            operation="remote SWR manifest validation",
            timeout=180,
            environment=docker_environment,
        )
    return remote, _query_swr_digest(client, organization, repository, tag)


def _wait_for_runtime(client: RuntimeClient, runtime_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        response = client.find_agent_by_id(runtime_id)
        if isinstance(response, dict) and response.get("status") == "READY":
            return response
        time.sleep(5)
    raise DeploymentError("AgentArts runtime did not reach READY")


def _deploy_authenticated(
    credentials: HuaweiCredentials,
    runtime_environment: Mapping[str, str],
    inbound_api_key: str,
) -> RuntimeRelease:
    """Run deployment while Huawei SDK credentials are scoped by the caller."""

    if _read_pending_state() is not None:
        raise DeploymentError(
            "unfinished deployment requires manual reconciliation before retry"
        )
    state = _read_state()
    inbound_key_sha256 = validate_inbound_key_state(state, inbound_api_key)
    logs_configuration = logs_configuration_from_state(state or {"logs": False})
    expected_runtime_id = state.get("runtime_id") if state else None
    if expected_runtime_id is not None and not isinstance(expected_runtime_id, str):
        raise DeploymentError("deployment state runtime id is invalid")

    local_image = os.environ.get("AGENTARTS_LOCAL_IMAGE", LOCAL_IMAGE)
    _validate_local_image(local_image)
    commit = _git_commit()
    tag = make_image_tag(commit, datetime.now(timezone.utc))
    organization = default_swr_organization(credentials.access_key)
    repository = default_swr_repository()

    agency = _audit_execution_agency()
    swr_client = SWRClient(region=REGION)
    _ensure_swr_repository(swr_client, organization, repository)
    image_ref, image_digest = _publish_image(
        swr_client,
        local_image=local_image,
        organization=organization,
        repository=repository,
        tag=tag,
    )
    _write_pending_state(
        {
            "agent_name": AGENT_NAME,
            "expected_runtime_id": expected_runtime_id,
            "image_tag": tag,
            "image_digest": image_digest,
            "inbound_key_sha256": inbound_key_sha256,
        }
    )

    runtime_client = RuntimeClient(
        control_endpoint=get_control_plane_endpoint(REGION), timeout=60
    )
    payload = build_runtime_payload(
        image_ref=image_ref,
        runtime_environment=runtime_environment,
        inbound_api_key=inbound_api_key,
        logs_configuration=logs_configuration,
    )
    runtime = create_or_update_runtime(runtime_client, payload, expected_runtime_id)
    runtime_id = str(runtime["id"])
    version = str(runtime["latest_version"])
    ready = _wait_for_runtime(runtime_client, runtime_id)
    endpoint = pin_dev_endpoint(runtime_client, runtime_id, version)
    endpoint_id = endpoint.get("id")
    gateway_id = ready.get("agent_gateway_id")
    version_detail = ready.get("version_detail", {})
    invoke_config = (
        version_detail.get("invoke_config", {})
        if isinstance(version_detail, dict)
        else {}
    )
    access_domain = (
        invoke_config.get("access_endpoint", "")
        if isinstance(invoke_config, dict)
        else ""
    )
    if not all(
        isinstance(value, str) and value
        for value in (endpoint_id, gateway_id, access_domain)
    ):
        raise DeploymentError("AgentArts deployment response is missing safe identifiers")

    release = RuntimeRelease(
        region=REGION,
        agent_name=AGENT_NAME,
        swr_organization=organization,
        swr_repository=repository,
        image_tag=tag,
        image_digest=image_digest,
        runtime_id=runtime_id,
        runtime_version=version,
        endpoint_id=endpoint_id,
        endpoint_name=ENDPOINT_NAME,
        gateway_id=gateway_id,
        access_domain=access_domain,
        logs_enabled=logs_configuration["enabled"] is True,
        log_project_id=logs_configuration.get("project_id"),
        log_group_id=logs_configuration.get("group_id"),
        log_stream_id=logs_configuration.get("stream_id"),
    )
    final_state = {
        **public_evidence(release),
        "agent_name": AGENT_NAME,
        "inbound_key_sha256": inbound_key_sha256,
        "agency": agency,
    }
    _write_state(final_state)
    _clear_pending_state()
    return release


def deploy() -> RuntimeRelease:
    credentials = load_huawei_credentials(CREDENTIALS_PATH)
    runtime_environment = load_runtime_environment(RUNTIME_ENV_PATH)
    inbound_api_key = load_or_create_inbound_api_key(INBOUND_KEY_PATH)
    with _deployment_logging_disabled(), _huawei_environment(
        credentials.access_key, credentials.secret_key
    ):
        return _deploy_authenticated(
            credentials,
            runtime_environment,
            inbound_api_key,
        )


def promote_logs_version() -> RuntimeRelease:
    """Pin an already-created logs-only successor after strict reconciliation."""

    pending = _read_pending_state()
    state = _read_state()
    if state is None:
        raise DeploymentError("deployment state is unavailable")
    safe_fields = (
        "swr_organization",
        "swr_repository",
        "image_tag",
        "image_digest",
        "runtime_id",
        "runtime_version",
        "gateway_id",
        "access_domain",
        "inbound_key_sha256",
    )
    if not all(isinstance(state.get(key), str) and state[key] for key in safe_fields):
        raise DeploymentError("deployment state is missing release identifiers")
    credentials = load_huawei_credentials(CREDENTIALS_PATH)
    runtime_environment = load_runtime_environment(RUNTIME_ENV_PATH)
    inbound_api_key = load_or_create_inbound_api_key(INBOUND_KEY_PATH)
    validate_inbound_key_state(state, inbound_api_key)
    with _deployment_logging_disabled(), _huawei_environment(
        credentials.access_key, credentials.secret_key
    ):
        agency = _audit_execution_agency()
        client = RuntimeClient(
            control_endpoint=get_control_plane_endpoint(REGION), timeout=60
        )
        runtime = client.find_agent_by_id(str(state.get("runtime_id", "")))
        if not isinstance(runtime, dict):
            raise DeploymentError("logs-enabled Runtime could not be queried")
        version, logs = validate_log_enabled_successor(
            runtime,
            state,
            set(runtime_environment),
        )
        swr_client = SWRClient(region=REGION)
        live_digest = _query_swr_digest(
            swr_client,
            state["swr_organization"],
            state["swr_repository"],
            state["image_tag"],
        )
        if live_digest != state["image_digest"]:
            raise DeploymentError("logs-enabled Runtime SWR digest changed")
        intent = {
            "agent_name": AGENT_NAME,
            "operation": "promote_logs_version",
            "runtime_id": state["runtime_id"],
            "source_version": state["runtime_version"],
            "target_version": version,
            "image_digest": state["image_digest"],
        }
        if pending is None:
            _write_pending_state(intent)
        elif pending != intent:
            raise DeploymentError(
                "unfinished deployment does not match logs promotion"
            )
        endpoint = pin_dev_endpoint(client, str(state["runtime_id"]), version)

    endpoint_id = endpoint.get("id")
    if not isinstance(endpoint_id, str) or not endpoint_id:
        raise DeploymentError("logs-enabled dev endpoint is missing id")
    release = RuntimeRelease(
        region=REGION,
        agent_name=AGENT_NAME,
        swr_organization=state["swr_organization"],
        swr_repository=state["swr_repository"],
        image_tag=state["image_tag"],
        image_digest=state["image_digest"],
        runtime_id=state["runtime_id"],
        runtime_version=version,
        endpoint_id=endpoint_id,
        endpoint_name=ENDPOINT_NAME,
        gateway_id=state["gateway_id"],
        access_domain=state["access_domain"],
        logs_enabled=True,
        log_project_id=str(logs["project_id"]),
        log_group_id=str(logs["group_id"]),
        log_stream_id=str(logs["stream_id"]),
    )
    _write_state(
        {
            **public_evidence(release),
            "agent_name": AGENT_NAME,
            "inbound_key_sha256": state["inbound_key_sha256"],
            "agency": agency,
        }
    )
    _clear_pending_state()
    return release


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish the private KooPhone POC to AgentArts"
    )
    parser.add_argument(
        "command",
        choices=("deploy", "show", "promote-logs-version"),
        nargs="?",
        default="deploy",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "show":
            state = _read_state()
            if state is None:
                raise DeploymentError("deployment state is unavailable")
            print(json.dumps(state, ensure_ascii=True, sort_keys=True, indent=2))
            return 0
        release = (
            promote_logs_version()
            if args.command == "promote-logs-version"
            else deploy()
        )
        print(json.dumps(public_evidence(release), ensure_ascii=True, sort_keys=True, indent=2))
        return 0
    except DeploymentError as exc:
        print(f"deployment_failed={exc}", file=sys.stderr)
        return 1
    except Exception:
        print("deployment_failed=unexpected control-plane failure", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
