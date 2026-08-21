# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Contract tests for the AgentArts ARM64 runtime image workflow."""

from __future__ import annotations

import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = COMPONENT_ROOT / "Dockerfile.agentarts-koophone"
DOCKERIGNORE = COMPONENT_ROOT / ".dockerignore"
SCRIPTS_ROOT = COMPONENT_ROOT / "scripts"
LOCAL_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class AgentArtsImageDefinitionTests(unittest.TestCase):
    def test_runtime_image_is_a_dedicated_non_cli_arm64_poc(self):
        dockerfile = DOCKERFILE.read_text()

        self.assertIn('com.mobile-use.runtime.kind="agentarts"', dockerfile)
        self.assertIn('com.mobile-use.target.platform="linux/arm64"', dockerfile)
        self.assertIn('com.mobile-use.security.secret-bearing="true"', dockerfile)
        self.assertIn("HOME=/tmp/mobile-agent-home", dockerfile)
        self.assertIn("TMPDIR=/tmp", dockerfile)
        self.assertIn("XDG_CACHE_HOME=/tmp/mobile-agent-cache", dockerfile)
        self.assertIn('ENTRYPOINT ["python", "-m", "mobile_agent.agentarts_runtime"]', dockerfile)
        self.assertNotIn("koophone_acceptance", dockerfile)
        self.assertNotIn("koophone_container_cli", dockerfile)
        self.assertNotIn("koophone_alarm_cli", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("--chmod=0400", dockerfile)
        self.assertIn("EXPOSE 8080", dockerfile)

    def test_build_context_is_a_closed_allowlist(self):
        lines = DOCKERIGNORE.read_text().splitlines()

        self.assertEqual(lines[0], "*")
        self.assertIn("!pyproject.toml", lines)
        self.assertIn("!uv.lock", lines)
        self.assertIn("!README.md", lines)
        self.assertIn("!config.toml", lines)
        self.assertIn("!mobile_agent/", lines)
        self.assertIn("!mobile_agent/**/*.py", lines)
        self.assertIn("!jwt.jks", lines)
        self.assertNotIn("!mobile_agent/**", lines)
        for forbidden in (".env", ".venv", ".jks", "logs", "screenshots"):
            self.assertNotIn(f"!{forbidden}", lines)

    def test_dependency_lock_keeps_audited_agentarts_sdk(self):
        pyproject = (COMPONENT_ROOT / "pyproject.toml").read_text()
        lock = (COMPONENT_ROOT / "uv.lock").read_text()

        self.assertIn('"agentarts-sdk==0.1.5"', pyproject)
        self.assertRegex(lock, r'name = "agentarts-sdk"\nversion = "0\.1\.5"')


class AgentArtsImageWorkflowTests(unittest.TestCase):
    def test_workflow_scripts_exist_are_shell_safe_and_enforce_arm64(self):
        expected = {
            "build-agentarts-runtime.sh",
            "check-agentarts-image.sh",
            "run-agentarts-runtime.sh",
        }
        self.assertEqual(
            {path.name for path in SCRIPTS_ROOT.glob("*.sh")}, expected
        )
        for name in expected:
            path = SCRIPTS_ROOT / name
            content = path.read_text()
            self.assertTrue(content.startswith("#!/usr/bin/env bash"), name)
            self.assertIn("set -euo pipefail", content, name)
            syntax = subprocess.run(
                ["bash", "-n", str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)

        build = (SCRIPTS_ROOT / "build-agentarts-runtime.sh").read_text()
        self.assertIn("TARGET_PLATFORM", build)
        self.assertIn("linux/arm64", build)
        self.assertIn("BUILDKIT_USE_OCI_MEDIA_TYPES=0", build)
        self.assertIn("docker build", build)
        self.assertIn("--provenance=false", build)
        self.assertIn("--sbom=false", build)
        self.assertIn("oci-mediatypes=false", build)
        self.assertIn("docker image inspect", build)
        self.assertIn("agentarts-sdk", build)

        check = (SCRIPTS_ROOT / "check-agentarts-image.sh").read_text()
        self.assertIn("docker image inspect", check)
        self.assertIn("docker manifest inspect --verbose", check)
        self.assertIn("application/vnd.oci.", check)
        self.assertIn("Descriptor.MediaType", check)
        self.assertIn("2>/dev/null", check)
        self.assertIn("docker save", check)
        self.assertIn("non-oci-export", check)
        self.assertIn('"os"', check)

        run = (SCRIPTS_ROOT / "run-agentarts-runtime.sh").read_text()
        for flag in ("--read-only", "--tmpfs", "--cap-drop", "no-new-privileges"):
            self.assertIn(flag, run)
        self.assertIn("--env-file", run)
        self.assertIn("KOOPHONE_JKS_PATH", run)
        self.assertIn("EXPERIMENT_RECORD_PATH", run)

    def test_workflow_scripts_do_not_print_environment_values(self):
        for path in SCRIPTS_ROOT.glob("*.sh"):
            content = path.read_text()
            self.assertNotRegex(content, r"echo\s+\$[A-Z_]+")
            self.assertNotIn("env |", content)
            self.assertNotIn("printenv", content)

    @unittest.skipUnless(
        os.getenv("RUN_DOCKER_CONTRACT") == "1" and shutil.which("docker"),
        "opt-in: requires Docker and a built image",
    )
    def test_built_image_contract_can_be_checked_without_huawei_credentials(self):
        image = os.environ.get("AGENTARTS_TEST_IMAGE", "mobile-use-agent-agentarts:latest")
        result = subprocess.run(
            [str(SCRIPTS_ROOT / "check-agentarts-image.sh"), image],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("linux/arm64", result.stdout)

    @unittest.skipUnless(
        os.getenv("RUN_DOCKER_CONTRACT") == "1" and shutil.which("docker"),
        "opt-in: requires Docker and a built image",
    )
    def test_read_only_container_serves_fake_success_and_failure_invocations(self):
        """Exercise the real 8080 HTTP boundary with test-only task injection."""

        image = os.environ.get("AGENTARTS_TEST_IMAGE", "mobile-use-agent-agentarts:latest")
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            capture_output=True,
        )
        if inspect.returncode != 0:
            self.skipTest("AGENTARTS_TEST_IMAGE is not built")

        fake_module = """
from mobile_agent.agent.run_result import AgentRunResult


async def run_koophone_task(prompt, *, task_id, thread_id, session_id, **kwargs):
    if prompt == "fake-failure":
        return AgentRunResult(
            status="failed", task_id=task_id, thread_id=thread_id,
            session_id=session_id, result=None, rounds=1, elapsed_ms=2,
            terminal_reason="step_limit",
        )
    return AgentRunResult(
        status="completed", task_id=task_id, thread_id=thread_id,
        session_id=session_id, result="fake success", rounds=1, elapsed_ms=2,
        terminal_reason="completed",
    )
"""
        container_name = f"agentarts-image-test-{os.getpid()}"
        with tempfile.TemporaryDirectory() as directory:
            fake_path = Path(directory) / "koophone_task.py"
            fake_path.write_text(fake_module)
            command = [
                "docker",
                "run",
                "--detach",
                "--name",
                container_name,
                "--platform",
                "linux/arm64",
                "--publish",
                "18080:8080",
                "--mount",
                "type=bind,"
                f"src={fake_path},"
                "dst=/opt/mobile-agent/.venv/lib/python3.11/site-packages/"
                "mobile_agent/koophone_task.py,readonly",
                "--env",
                "ENV=production",
                "--env",
                "MODEL_PROVIDER=kimi",
                "--env",
                "DEVICE_PROVIDER=koophone_mcp",
                "--env",
                "KIMI_API_KEY=test-only-kimi-key",
                "--env",
                "KIMI_MODEL=kimi-k2.6",
                "--env",
                "KIMI_THINKING_MODE=disabled",
                "--env",
                "KOOPHONE_MCP_URL=https://test.invalid/mcp",
                "--env",
                "KOOPHONE_INSTANCE_ID=test-instance",
                "--env",
                "KOOPHONE_INPUT_WIDTH=1080",
                "--env",
                "KOOPHONE_INPUT_HEIGHT=1920",
                "--env",
                "KOOPHONE_TLS_VERIFY=true",
                "--env",
                "KOOPHONE_IAM_AUTH_URL=https://test.invalid/auth",
                "--env",
                "KOOPHONE_IAM_DOMAIN=test-domain",
                "--env",
                "KOOPHONE_IAM_USERNAME=test-user",
                "--env",
                "KOOPHONE_IAM_PASSWORD=test-password",
                "--env",
                "KOOPHONE_IAM_PROJECT=cn-north-4",
                "--env",
                "KOOPHONE_JKS_STORE_PASSWORD=test-store-password",
                "--env",
                "KOOPHONE_JKS_KEY_PASSWORD=test-key-password",
                "--env",
                "MOBILE_CONFIG_PATH=/opt/mobile-agent/config.toml",
                "--env",
                "KOOPHONE_JKS_PATH=/opt/mobile-agent/secrets/koophone.jks",
                "--env",
                "EXPERIMENT_RECORD_PATH=/tmp/mobile-agent/experiment-runs.jsonl",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                image,
            ]
            started = subprocess.run(command, check=False, capture_output=True)
            self.assertEqual(started.returncode, 0)
            try:
                request = urllib.request.Request("http://127.0.0.1:18080/ping")
                for _ in range(40):
                    try:
                        with LOCAL_HTTP.open(request, timeout=0.5) as response:
                            if response.status == 200:
                                break
                    except (OSError, urllib.error.HTTPError):
                        time.sleep(0.05)
                else:
                    logs = subprocess.run(
                        ["docker", "logs", container_name],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.fail(
                        "container did not become healthy: "
                        + repr(started.stdout[-1000:])
                        + repr(started.stderr[-1000:])
                        + logs.stdout[-2000:]
                        + logs.stderr[-2000:]
                    )

                def invoke(prompt: str) -> tuple[int, dict[str, object]]:
                    body = json.dumps(
                        {
                            "inputs": {
                                "operation": "chat_completions",
                                "query": prompt,
                            }
                        }
                    ).encode()
                    request = urllib.request.Request(
                        "http://127.0.0.1:18080/invocations",
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "x-hw-agentarts-session-id": "image-test",
                        },
                    )
                    try:
                        with LOCAL_HTTP.open(request, timeout=5) as response:
                            return response.status, json.loads(response.read())
                    except urllib.error.HTTPError as error:
                        return error.code, json.loads(error.read())

                success_status, success = invoke("fake-success")
                failure_status, failure = invoke("fake-failure")
                self.assertEqual(success_status, 200)
                self.assertEqual(success["status"], "completed")
                self.assertEqual(failure_status, 422)
                self.assertEqual(failure["status"], "failed")
            finally:
                subprocess.run(
                    ["docker", "rm", "--force", container_name],
                    check=False,
                    capture_output=True,
                )


if __name__ == "__main__":
    unittest.main()
