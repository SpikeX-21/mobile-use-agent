"""Contracts for the private AgentArts POC deployment workflow."""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from mobile_agent.agentarts_deployment import (
    AGENT_NAME,
    DEPENDENCY_FILE,
    ENDPOINT_NAME,
    ENTRYPOINT,
    REGION,
    DeploymentError,
    RuntimeRelease,
    build_endpoint_payload,
    build_runtime_payload,
    default_swr_organization,
    default_swr_repository,
    load_huawei_credentials,
    load_or_create_inbound_api_key,
    load_runtime_environment,
    logs_configuration_from_state,
    make_image_tag,
    create_or_update_runtime,
    pin_dev_endpoint,
    public_evidence,
    validate_execution_agency,
    validate_inbound_key_state,
    validate_log_enabled_successor,
    validate_private_repository,
)
from mobile_agent import agentarts_deploy_cli


class AgentArtsDeploymentTests(unittest.TestCase):
    def test_defaults_match_the_approved_internal_poc(self):
        self.assertEqual(AGENT_NAME, "mobile-use-koophone-poc-test1")
        self.assertEqual(ENTRYPOINT, "app:app")
        self.assertEqual(REGION, "cn-southwest-2")
        self.assertEqual(DEPENDENCY_FILE, "requirements.txt")
        self.assertEqual(ENDPOINT_NAME, "dev")
        self.assertEqual(
            default_swr_repository(AGENT_NAME),
            "agent_mobile-use-koophone-poc-test1",
        )
        self.assertEqual(
            agentarts_deploy_cli.STATE_DIRECTORY,
            agentarts_deploy_cli.COMPONENT_ROOT
            / ".agentarts"
            / "mobile-use-koophone-poc-test1",
        )
        self.assertRegex(
            default_swr_organization("test-access-key"),
            r"^agentarts-cnso2-[0-9a-f]{8}-org$",
        )

    def test_release_tag_is_unique_explicit_and_reproducibly_formatted(self):
        tag = make_image_tag(
            "249296d87e",
            datetime(2026, 8, 21, 12, 34, 56, tzinfo=timezone.utc),
        )
        self.assertEqual(tag, "issue25-249296d-20260821t123456z")
        self.assertNotEqual(tag, "latest")

    def test_inbound_api_key_is_created_once_in_a_private_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "inbound-api-key")

            first = load_or_create_inbound_api_key(path)
            second = load_or_create_inbound_api_key(path)

            self.assertEqual(first, second)
            self.assertRegex(first, r"^[A-Za-z0-9_-]{32,512}$")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_credentials_require_the_expected_schema_and_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "credentials.csv")
            path.write_text(
                "User Name,Access Key Id,Secret Access Key\n"
                "operator,example-ak,example-sk\n",
                encoding="utf-8",
            )
            path.chmod(0o600)

            credentials = load_huawei_credentials(path)

            self.assertEqual(credentials.access_key, "example-ak")
            self.assertEqual(credentials.secret_key, "example-sk")
            self.assertNotIn("example-ak", repr(credentials))
            self.assertNotIn("example-sk", repr(credentials))

            path.chmod(0o644)
            with self.assertRaisesRegex(DeploymentError, "credentials.csv mode"):
                load_huawei_credentials(path)

    def test_runtime_environment_is_allowlisted_and_complete(self):
        required = {
            "ENV": "poc",
            "MODEL_PROVIDER": "kimi",
            "DEVICE_PROVIDER": "koophone_mcp",
            "KIMI_API_KEY": "model-secret",
            "KIMI_MODEL": "kimi-k2.6",
            "KIMI_BASE_URL": "https://api.moonshot.cn/v1",
            "KIMI_THINKING_MODE": "disabled",
            "KOOPHONE_MCP_URL": "https://example.invalid/mcp",
            "KOOPHONE_INSTANCE_ID": "private-eid",
            "KOOPHONE_INPUT_WIDTH": "1080",
            "KOOPHONE_INPUT_HEIGHT": "1920",
            "KOOPHONE_TLS_VERIFY": "false",
            "KOOPHONE_IAM_AUTH_URL": "https://iam.example.invalid/v3/auth/tokens",
            "KOOPHONE_IAM_DOMAIN": "domain",
            "KOOPHONE_IAM_USERNAME": "user",
            "KOOPHONE_IAM_PASSWORD": "iam-secret",
            "KOOPHONE_IAM_PROJECT": "project",
            "KOOPHONE_JKS_STORE_PASSWORD": "jks-store-secret",
            "KOOPHONE_JKS_KEY_PASSWORD": "jks-key-secret",
            "KOOPHONE_JKS_ALIAS": "koophone",
            "KOOPHONE_JWT_TTL_MINUTES": "1440",
            "AGENT_TASK_TIMEOUT_SECONDS": "300",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, ".env")
            path.write_text(
                "\n".join(f"{key}={value}" for key, value in required.items())
                + "\nUNRELATED_SECRET=must-not-be-uploaded\n",
                encoding="utf-8",
            )
            path.chmod(0o600)

            loaded = load_runtime_environment(path)

        self.assertEqual(loaded, required)
        self.assertNotIn("UNRELATED_SECRET", loaded)

    def test_runtime_environment_explicitly_sets_normal_timeout_default(self):
        required = {
            "ENV": "poc",
            "MODEL_PROVIDER": "kimi",
            "DEVICE_PROVIDER": "koophone_mcp",
            "KIMI_API_KEY": "model-secret",
            "KIMI_MODEL": "kimi-k2.6",
            "KIMI_BASE_URL": "https://api.moonshot.cn/v1",
            "KIMI_THINKING_MODE": "disabled",
            "KOOPHONE_MCP_URL": "https://example.invalid/mcp",
            "KOOPHONE_INSTANCE_ID": "private-eid",
            "KOOPHONE_INPUT_WIDTH": "1080",
            "KOOPHONE_INPUT_HEIGHT": "1920",
            "KOOPHONE_TLS_VERIFY": "false",
            "KOOPHONE_IAM_AUTH_URL": "https://iam.example.invalid/v3/auth/tokens",
            "KOOPHONE_IAM_DOMAIN": "domain",
            "KOOPHONE_IAM_USERNAME": "user",
            "KOOPHONE_IAM_PASSWORD": "iam-secret",
            "KOOPHONE_IAM_PROJECT": "project",
            "KOOPHONE_JKS_STORE_PASSWORD": "jks-store-secret",
            "KOOPHONE_JKS_KEY_PASSWORD": "jks-key-secret",
            "KOOPHONE_JKS_ALIAS": "koophone",
            "KOOPHONE_JWT_TTL_MINUTES": "1440",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, ".env")
            path.write_text(
                "\n".join(f"{key}={value}" for key, value in required.items()),
                encoding="utf-8",
            )
            path.chmod(0o600)

            loaded = load_runtime_environment(path)

        self.assertEqual(loaded["AGENT_TASK_TIMEOUT_SECONDS"], "900")

    def test_runtime_payload_is_private_strict_and_secret_bearing_only_in_memory(self):
        runtime_env = {
            "ENV": "poc",
            "MODEL_PROVIDER": "kimi",
            "DEVICE_PROVIDER": "koophone_mcp",
            "KIMI_API_KEY": "model-secret",
            "KIMI_MODEL": "kimi-k2.6",
            "KIMI_BASE_URL": "https://api.moonshot.cn/v1",
            "KIMI_THINKING_MODE": "disabled",
            "KOOPHONE_MCP_URL": "https://example.invalid/mcp",
            "KOOPHONE_INSTANCE_ID": "private-eid",
            "KOOPHONE_INPUT_WIDTH": "1080",
            "KOOPHONE_INPUT_HEIGHT": "1920",
            "KOOPHONE_TLS_VERIFY": "false",
            "KOOPHONE_IAM_AUTH_URL": "https://iam.example.invalid/v3/auth/tokens",
            "KOOPHONE_IAM_DOMAIN": "domain",
            "KOOPHONE_IAM_USERNAME": "user",
            "KOOPHONE_IAM_PASSWORD": "iam-secret",
            "KOOPHONE_IAM_PROJECT": "project",
            "KOOPHONE_JKS_STORE_PASSWORD": "jks-store-secret",
            "KOOPHONE_JKS_KEY_PASSWORD": "jks-key-secret",
            "KOOPHONE_JKS_ALIAS": "koophone",
            "KOOPHONE_JWT_TTL_MINUTES": "1440",
            "AGENT_TASK_TIMEOUT_SECONDS": "300",
        }
        payload = build_runtime_payload(
            image_ref="swr.cn-southwest-2.myhuaweicloud.com/org/repo:release-1",
            runtime_environment=runtime_env,
            inbound_api_key="inbound-secret-0123456789abcdef01",
            logs_configuration={
                "enabled": True,
                "project_id": "project-id",
                "group_id": "group-id",
                "stream_id": "stream-id",
            },
        )

        self.assertEqual(payload["name"], AGENT_NAME)
        self.assertEqual(payload["arch"], "arm64")
        self.assertEqual(payload["execution_agency_name"], "DefaultAgentArtsRuntimeAgency")
        self.assertEqual(payload["network_config"], {"network_mode": "PUBLIC"})
        self.assertEqual(
            payload["invoke_config"],
            {
                "protocol": "HTTP",
                "port": 8080,
                "file_transfer_config": {"enabled": False},
                "url_match_type": "ACCURATE_MATCH",
            },
        )
        self.assertEqual(payload["storage_config"], {})
        self.assertEqual(
            payload["observability"],
            {
                "logs": {
                    "enabled": True,
                    "project_id": "project-id",
                    "group_id": "group-id",
                    "stream_id": "stream-id",
                },
                "metrics": {"enabled": False},
                "tracing": {"enabled": False},
            },
        )
        identity = payload["identity_config"]
        self.assertEqual(identity["authorizer_type"], "API_KEY")
        self.assertEqual(
            identity["authorizer_configuration"]["key_auth"]["api_keys"],
            [
                {
                    "api_key": "inbound-secret-0123456789abcdef01",
                    "api_key_name": "internal-poc",
                }
            ],
        )
        uploaded_env = {item["key"]: item["value"] for item in payload["env_vars"]}
        self.assertNotIn("AGENTARTS_RUNTIME_API_KEY", uploaded_env)
        self.assertEqual(uploaded_env["KIMI_API_KEY"], "model-secret")

        default_payload = build_runtime_payload(
            image_ref="swr.cn-southwest-2.myhuaweicloud.com/org/repo:release-2",
            runtime_environment=runtime_env,
            inbound_api_key="inbound-secret-0123456789abcdef01",
        )
        self.assertEqual(
            default_payload["observability"]["logs"],
            {"enabled": False},
        )

    def test_log_configuration_round_trips_from_safe_deployment_state(self):
        state = {
            "logs": True,
            "log_project_id": "project-id",
            "log_group_id": "group-id",
            "log_stream_id": "stream-id",
        }

        self.assertEqual(
            logs_configuration_from_state(state),
            {
                "enabled": True,
                "project_id": "project-id",
                "group_id": "group-id",
                "stream_id": "stream-id",
            },
        )
        self.assertEqual(logs_configuration_from_state({"logs": False}), {"enabled": False})
        with self.assertRaisesRegex(DeploymentError, "log configuration"):
            logs_configuration_from_state({"logs": True, "log_project_id": "project-id"})

    def test_log_enabled_successor_must_only_change_observability(self):
        state = {
            "runtime_id": "runtime-id",
            "runtime_version": "v2",
            "swr_organization": "org",
            "swr_repository": "repo",
            "image_tag": "release-tag",
            "image_digest": "sha256:" + "a" * 64,
            "access_domain": "defaultgw.example",
        }
        detail = {
            "version": "v3",
            "artifact_source": {
                "url": "swr.cn-southwest-2.myhuaweicloud.com/org/repo:release-tag",
                "commands": [],
            },
            "environment_variables": [
                {"key": "ENV", "value": "poc"},
                {"key": "MODEL_PROVIDER", "value": "kimi"},
            ],
            "execution_agency_name": "DefaultAgentArtsRuntimeAgency",
            "invoke_config": {
                "protocol": "HTTP",
                "port": 8080,
                "url_match_type": "ACCURATE_MATCH",
                "access_endpoint": "defaultgw.example",
                "file_transfer_config": {"enabled": False},
            },
            "network_config": {"network_mode": "PUBLIC"},
            "storage_config": {"sfs_turbo": []},
            "observability": {
                "logs": {
                    "enabled": True,
                    "project_id": "project-id",
                    "group_id": "group-id",
                    "stream_id": "stream-id",
                },
                "metrics": {"enabled": False},
                "tracing": {"enabled": False},
            },
        }
        runtime = {
            "id": "runtime-id",
            "name": AGENT_NAME,
            "status": "READY",
            "latest_version": "v3",
            "version_detail": detail,
        }

        version, logs = validate_log_enabled_successor(
            runtime,
            state,
            {"ENV", "MODEL_PROVIDER"},
        )

        self.assertEqual(version, "v3")
        self.assertTrue(logs["enabled"])

        changed_artifact = json.loads(json.dumps(runtime))
        changed_artifact["version_detail"]["artifact_source"]["url"] = (
            "swr.cn-southwest-2.myhuaweicloud.com/org/repo:other-tag"
        )
        with self.assertRaisesRegex(DeploymentError, "artifact"):
            validate_log_enabled_successor(
                changed_artifact,
                state,
                {"ENV", "MODEL_PROVIDER"},
            )

        changed_registry = json.loads(json.dumps(runtime))
        changed_registry["version_detail"]["artifact_source"]["url"] = (
            "evil.example/org/repo:release-tag"
        )
        with self.assertRaisesRegex(DeploymentError, "artifact"):
            validate_log_enabled_successor(
                changed_registry,
                state,
                {"ENV", "MODEL_PROVIDER"},
            )

        enabled_file_transfer = json.loads(json.dumps(runtime))
        enabled_file_transfer["version_detail"]["invoke_config"][
            "file_transfer_config"
        ] = {"enabled": True}
        with self.assertRaisesRegex(DeploymentError, "file transfer"):
            validate_log_enabled_successor(
                enabled_file_transfer,
                state,
                {"ENV", "MODEL_PROVIDER"},
            )

        changed_environment = json.loads(json.dumps(runtime))
        changed_environment["version_detail"]["environment_variables"].append(
            {"key": "UNEXPECTED_SECRET", "value": "nope"}
        )
        with self.assertRaisesRegex(DeploymentError, "environment"):
            validate_log_enabled_successor(
                changed_environment,
                state,
                {"ENV", "MODEL_PROVIDER"},
            )

    def test_dev_endpoint_is_pinned_to_an_explicit_version(self):
        self.assertEqual(
            build_endpoint_payload("v7"),
            {
                "name": "dev",
                "target_version_name": "v7",
                "description": "Internal POC pinned endpoint",
            },
        )
        with self.assertRaises(DeploymentError):
            build_endpoint_payload("Latest")

    def test_repository_must_be_private(self):
        validate_private_repository({"is_public": False})
        with self.assertRaisesRegex(DeploymentError, "private"):
            validate_private_repository({"is_public": True})
        with self.assertRaisesRegex(DeploymentError, "visibility"):
            validate_private_repository({})

    def test_runtime_create_refuses_an_unowned_existing_name(self):
        class Client:
            def find_agent_by_name(self, name):
                return {"id": "existing-runtime"}

        with self.assertRaisesRegex(DeploymentError, "already exists"):
            create_or_update_runtime(Client(), {"name": AGENT_NAME}, None)

    def test_runtime_update_preserves_immutable_identity_and_creates_a_version(self):
        calls = []

        class Client:
            def find_agent_by_name(self, name):
                return {"id": "owned-runtime"}

            def update_agent(self, **kwargs):
                calls.append(kwargs)
                return {
                    "id": "owned-runtime",
                    "latest_version": "v2",
                    "agent_gateway_id": "gateway-id",
                }

        result = create_or_update_runtime(
            Client(),
            {
                "name": AGENT_NAME,
                "identity_config": {"api_key": "must-not-be-updated"},
                "artifact_source_config": {"url": "image"},
            },
            "owned-runtime",
        )

        self.assertEqual(result["latest_version"], "v2")
        self.assertEqual(calls[0]["agent_id"], "owned-runtime")
        self.assertNotIn("name", calls[0])
        self.assertNotIn("identity_config", calls[0])

    def test_existing_runtime_rejects_a_lost_or_rotated_inbound_key(self):
        original_key = "original-inbound-key-0123456789abcdef"
        replacement_key = "replacement-inbound-key-0123456789abcd"
        state = {
            "agent_name": AGENT_NAME,
            "runtime_id": "owned-runtime",
            "inbound_key_sha256": __import__("hashlib").sha256(
                original_key.encode("ascii")
            ).hexdigest(),
        }

        with self.assertRaisesRegex(DeploymentError, "rotation"):
            validate_inbound_key_state(state, replacement_key)

        self.assertEqual(
            validate_inbound_key_state(state, original_key),
            state["inbound_key_sha256"],
        )

    def test_execution_agency_requires_exact_trust_and_policy_allowlists(self):
        trust = {
            "Version": "5.0",
            "Statement": [
                {
                    "Action": ["sts:agencies:assume"],
                    "Effect": "Allow",
                    "Principal": {
                        "Service": ["service.WorkloadSandboxMetadata"]
                    },
                }
            ],
        }
        allowed = [
            "AgentArtsCoreRunRuntimeIdentityAgencyPolicy",
            "AgentArtsCoreRunRuntimeOpsAgencyPolicy",
        ]

        validate_execution_agency(trust, allowed)

        extra_principal = json.loads(json.dumps(trust))
        extra_principal["Statement"][0]["Principal"]["Service"].append(
            "service.Other"
        )
        with self.assertRaisesRegex(DeploymentError, "trust policy"):
            validate_execution_agency(extra_principal, allowed)
        with self.assertRaisesRegex(DeploymentError, "attached policies"):
            validate_execution_agency(trust, allowed + ["AdministratorAccess"])

    def test_subprocesses_never_inherit_huawei_control_plane_credentials(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured.update(kwargs)
            return __import__("subprocess").CompletedProcess(command, 0, "", "")

        environment = {
            "PATH": "/usr/bin",
            "HUAWEICLOUD_SDK_AK": "secret-ak",
            "HUAWEICLOUD_SDK_SK": "secret-sk",
            "HUAWEICLOUD_SDK_REGION": REGION,
        }
        with patch.dict(agentarts_deploy_cli.os.environ, environment, clear=True):
            with patch.object(agentarts_deploy_cli.subprocess, "run", fake_run):
                agentarts_deploy_cli._safe_run(["git", "status"])

        child_environment = captured["env"]
        self.assertEqual(child_environment["PATH"], "/usr/bin")
        self.assertNotIn("HUAWEICLOUD_SDK_AK", child_environment)
        self.assertNotIn("HUAWEICLOUD_SDK_SK", child_environment)
        self.assertNotIn("HUAWEICLOUD_SDK_REGION", child_environment)

    def test_huawei_environment_is_restored_after_sdk_use(self):
        original = {
            "HUAWEICLOUD_SDK_AK": "caller-ak",
            "HUAWEICLOUD_SDK_SK": "caller-sk",
            "HUAWEICLOUD_SDK_REGION": "caller-region",
        }
        with patch.dict(agentarts_deploy_cli.os.environ, original, clear=True):
            with agentarts_deploy_cli._huawei_environment("deploy-ak", "deploy-sk"):
                self.assertEqual(
                    agentarts_deploy_cli.os.environ["HUAWEICLOUD_SDK_AK"],
                    "deploy-ak",
                )
                self.assertEqual(
                    agentarts_deploy_cli.os.environ["HUAWEICLOUD_SDK_SK"],
                    "deploy-sk",
                )
                self.assertEqual(
                    agentarts_deploy_cli.os.environ["HUAWEICLOUD_SDK_REGION"],
                    REGION,
                )
            self.assertEqual(
                {
                    key: agentarts_deploy_cli.os.environ[key]
                    for key in original
                },
                original,
            )

    def test_deployment_log_suppression_restores_caller_state(self):
        previous = logging.root.manager.disable
        logging.disable(logging.WARNING)
        try:
            with agentarts_deploy_cli._deployment_logging_disabled():
                self.assertEqual(logging.root.manager.disable, logging.CRITICAL)
            self.assertEqual(logging.root.manager.disable, logging.WARNING)
        finally:
            logging.disable(previous)

    def test_swr_login_uses_an_ephemeral_docker_config(self):
        environments = []

        class TagResponse:
            digest = "sha256:" + "a" * 64

        class RawClient:
            def show_repo_tag(self, request):
                return TagResponse()

        class Client:
            def create_swr_secret(self):
                return "swr.example", "user", "temporary-password"

            def get_full_image_name(self, organization, repository, tag):
                return f"swr.example/{organization}/{repository}:{tag}"

            def _get_client(self):
                return RawClient()

        def fake_command(command, **kwargs):
            environment = kwargs.get("environment")
            self.assertIsNotNone(environment)
            docker_config = Path(environment["DOCKER_CONFIG"])
            self.assertTrue(docker_config.is_dir())
            environments.append(docker_config)
            return ""

        with patch.object(agentarts_deploy_cli, "_tag_exists", return_value=False):
            with patch.object(
                agentarts_deploy_cli,
                "_require_command_success",
                side_effect=fake_command,
            ):
                agentarts_deploy_cli._publish_image(
                    Client(),
                    local_image="local:image",
                    organization="org",
                    repository="repo",
                    tag="unique",
                )

        self.assertGreaterEqual(len(environments), 4)
        self.assertEqual(len(set(environments)), 1)
        self.assertFalse(environments[0].exists())

    def test_pending_release_never_overwrites_last_known_good_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / "deployment-state.json"
            pending_path = root / "deployment-pending.json"
            current = {
                "agent_name": AGENT_NAME,
                "runtime_id": "runtime-v1",
                "runtime_version": "v1",
            }
            pending = {
                "agent_name": AGENT_NAME,
                "expected_runtime_id": "runtime-v1",
                "image_tag": "issue25-next",
            }
            with patch.object(agentarts_deploy_cli, "STATE_DIRECTORY", root):
                with patch.object(agentarts_deploy_cli, "STATE_PATH", state_path):
                    with patch.object(
                        agentarts_deploy_cli,
                        "PENDING_STATE_PATH",
                        pending_path,
                    ):
                        agentarts_deploy_cli._write_state(current)
                        agentarts_deploy_cli._write_pending_state(pending)

                        self.assertEqual(agentarts_deploy_cli._read_state(), current)
                        self.assertEqual(
                            agentarts_deploy_cli._read_pending_state(), pending
                        )
                        self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)
                        self.assertEqual(stat.S_IMODE(pending_path.stat().st_mode), 0o600)
                        agentarts_deploy_cli._clear_pending_state()
                        self.assertIsNone(agentarts_deploy_cli._read_pending_state())

    def test_unfinished_release_fails_before_any_new_image_or_cloud_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending_path = root / "deployment-pending.json"
            pending_path.write_text(
                json.dumps(
                    {
                        "agent_name": AGENT_NAME,
                        "image_tag": "issue25-interrupted",
                    }
                ),
                encoding="utf-8",
            )
            pending_path.chmod(0o600)

            with patch.object(
                agentarts_deploy_cli,
                "PENDING_STATE_PATH",
                pending_path,
            ):
                with patch.object(
                    agentarts_deploy_cli,
                    "_validate_local_image",
                ) as validate_image:
                    with self.assertRaisesRegex(DeploymentError, "reconciliation"):
                        agentarts_deploy_cli._deploy_authenticated(
                            object(),
                            {},
                            "inbound-secret-0123456789abcdef01",
                        )
            validate_image.assert_not_called()

    def test_logs_promotion_journals_before_endpoint_and_commits_after(self):
        events = []
        state = {
            "agent_name": AGENT_NAME,
            "swr_organization": "org",
            "swr_repository": "repo",
            "image_tag": "release-tag",
            "image_digest": "sha256:" + "a" * 64,
            "runtime_id": "runtime-id",
            "runtime_version": "v2",
            "gateway_id": "gateway-id",
            "access_domain": "defaultgw.example",
            "inbound_key_sha256": "b" * 64,
            "agency": {"name": "DefaultAgentArtsRuntimeAgency"},
        }
        logs = {
            "enabled": True,
            "project_id": "project-id",
            "group_id": "group-id",
            "stream_id": "stream-id",
        }
        runtime_client = MagicMock()
        runtime_client.find_agent_by_id.return_value = {"id": "runtime-id"}

        def record_pending(intent):
            events.append(("pending", intent))

        def record_pin(client, runtime_id, version):
            events.append(("pin", version))
            return {"id": "endpoint-id", "name": "dev", "target_version_name": version}

        def record_state(new_state):
            events.append(("state", new_state["runtime_version"]))

        def record_clear():
            events.append(("clear", None))

        patches = (
            patch.object(agentarts_deploy_cli, "_read_pending_state", return_value=None),
            patch.object(agentarts_deploy_cli, "_read_state", return_value=state),
            patch.object(
                agentarts_deploy_cli,
                "load_huawei_credentials",
                return_value=SimpleNamespace(access_key="ak", secret_key="sk"),
            ),
            patch.object(
                agentarts_deploy_cli,
                "load_runtime_environment",
                return_value={"ENV": "poc"},
            ),
            patch.object(
                agentarts_deploy_cli,
                "load_or_create_inbound_api_key",
                return_value="inbound-secret-0123456789abcdef01",
            ),
            patch.object(agentarts_deploy_cli, "validate_inbound_key_state"),
            patch.object(
                agentarts_deploy_cli,
                "_huawei_environment",
                return_value=contextlib.nullcontext(),
            ),
            patch.object(
                agentarts_deploy_cli,
                "_audit_execution_agency",
                return_value={"name": "DefaultAgentArtsRuntimeAgency"},
            ),
            patch.object(agentarts_deploy_cli, "RuntimeClient", return_value=runtime_client),
            patch.object(agentarts_deploy_cli, "SWRClient", return_value=MagicMock()),
            patch.object(
                agentarts_deploy_cli,
                "validate_log_enabled_successor",
                return_value=("v3", logs),
            ),
            patch.object(
                agentarts_deploy_cli,
                "_query_swr_digest",
                return_value=state["image_digest"],
            ),
            patch.object(
                agentarts_deploy_cli,
                "_write_pending_state",
                side_effect=record_pending,
            ),
            patch.object(
                agentarts_deploy_cli,
                "pin_dev_endpoint",
                side_effect=record_pin,
            ),
            patch.object(
                agentarts_deploy_cli,
                "_write_state",
                side_effect=record_state,
            ),
            patch.object(
                agentarts_deploy_cli,
                "_clear_pending_state",
                side_effect=record_clear,
            ),
        )
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            release = agentarts_deploy_cli.promote_logs_version()

        self.assertEqual(release.runtime_version, "v3")
        self.assertEqual([event[0] for event in events], ["pending", "pin", "state", "clear"])
        self.assertEqual(events[0][1]["source_version"], "v2")
        self.assertEqual(events[0][1]["target_version"], "v3")

    def test_dev_endpoint_uses_the_documented_wire_payload_and_updates_by_id(self):
        calls = []

        class Result:
            def __init__(self, *, success=True, status_code=200, data=None):
                self.success = success
                self.status_code = status_code
                self.data = data or {}

        class Client:
            def _control(self, method, path, **kwargs):
                calls.append((method, path, kwargs))
                if method == "GET":
                    return Result(
                        data={
                            "items": [
                                {
                                    "id": "endpoint-id",
                                    "name": "dev",
                                    "target_version_name": "v1",
                                }
                            ]
                        }
                    )
                return Result(
                    data={
                        "id": "endpoint-id",
                        "name": "dev",
                        "target_version_name": "v2",
                    }
                )

        result = pin_dev_endpoint(Client(), "runtime-id", "v2")

        self.assertEqual(result["target_version_name"], "v2")
        self.assertEqual(calls[1][0], "PUT")
        self.assertEqual(
            calls[1][1],
            "/v1/core/runtimes/runtime-id/endpoints/endpoint-id",
        )
        self.assertEqual(calls[1][2]["json"]["target_version_name"], "v2")
        self.assertNotIn("endpoint_name", calls[1][2]["json"])

    def test_public_evidence_never_contains_runtime_secrets_or_eid(self):
        release = RuntimeRelease(
            region=REGION,
            agent_name=AGENT_NAME,
            swr_organization="org",
            swr_repository="repo",
            image_tag="issue25-abc1234-20260821t120000z",
            image_digest="sha256:" + "a" * 64,
            runtime_id="00000000-0000-0000-0000-000000000001",
            runtime_version="v1",
            endpoint_id="00000000-0000-0000-0000-000000000002",
            endpoint_name="dev",
            gateway_id="00000000-0000-0000-0000-000000000003",
            access_domain="defaultgw.example.invalid",
            logs_enabled=True,
            log_project_id="project-id",
            log_group_id="group-id",
            log_stream_id="stream-id",
        )
        evidence = public_evidence(release)
        serialized = json.dumps(evidence, sort_keys=True)

        self.assertEqual(evidence["endpoint_name"], "dev")
        self.assertEqual(evidence["runtime_version"], "v1")
        self.assertEqual(evidence["inbound_auth"], "API_KEY")
        self.assertTrue(evidence["logs"])
        self.assertEqual(evidence["log_project_id"], "project-id")
        self.assertEqual(evidence["log_group_id"], "group-id")
        self.assertEqual(evidence["log_stream_id"], "stream-id")
        self.assertNotIn("inbound-secret", serialized.lower())
        self.assertNotIn("instance", serialized.lower())
        self.assertNotIn("environment", serialized.lower())


if __name__ == "__main__":
    unittest.main()
