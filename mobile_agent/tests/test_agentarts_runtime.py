# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import json
import logging
import os
from io import StringIO
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import httpx

from agentarts.sdk.runtime.model import SESSION_HEADER

from mobile_agent.agent.run_result import AgentRunResult
from mobile_agent.agentarts_runtime import (
    MAX_INPUT_LENGTH,
    app,
    configure_runtime_logging,
    main,
    runtime_health,
)


def completed_result(*, task_id: str = "task-1", session_id: str = "session-1") -> AgentRunResult:
    return AgentRunResult(
        status="completed",
        task_id=task_id,
        thread_id=f"thread-{task_id}",
        session_id=session_id,
        result="任务已完成",
        rounds=2,
        elapsed_ms=15,
        terminal_reason="completed",
    )


def failed_result(reason: str = "step_limit") -> AgentRunResult:
    return AgentRunResult(
        status="failed",
        task_id="task-failed",
        thread_id="thread-failed",
        session_id="session-failed",
        result=None,
        rounds=3,
        elapsed_ms=27,
        terminal_reason=reason,
    )


class AgentArtsRuntimeTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.transport = httpx.ASGITransport(app=app)
        self.client = httpx.AsyncClient(
            transport=self.transport,
            base_url="http://runtime.test",
        )
        runtime_health.set_ready(True)

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        runtime_health.set_ready(True)

    async def invoke(self, payload: object, *, session_id: str = "session-test") -> httpx.Response:
        return await self.client.post(
            "/invocations",
            headers={SESSION_HEADER: session_id},
            content=json.dumps(payload),
        )

    async def test_ping_uses_sdk_wire_format_without_running_agent(self):
        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            response = await self.client.get("/ping")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Healthy")
        self.assertIn("time_of_last_update", response.json())
        runner.assert_not_awaited()

    async def test_ping_reports_unhealthy_when_runtime_is_not_ready(self):
        runtime_health.set_ready(False)

        response = await self.client.get("/ping")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Unhealthy")

    async def test_invalid_input_is_rejected_before_agent(self):
        invalid_payloads = [
            {},
            {"input": ""},
            {"input": "   "},
            {"input": "x", "extra": "nope"},
            {"input": 123},
            {"input": "x" * (MAX_INPUT_LENGTH + 1)},
            [],
            "not-an-object",
        ]

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            for payload in invalid_payloads:
                response = await self.invoke(payload)
                self.assertEqual(response.status_code, 400, payload)
                self.assertEqual(response.json(), {"error": "invalid_request"})

        runner.assert_not_awaited()

    async def test_missing_or_invalid_session_is_rejected_before_agent(self):
        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            missing = await self.client.post(
                "/invocations",
                content=json.dumps({"input": "打开闹钟"}),
            )
            invalid = await self.client.post(
                "/invocations",
                headers={SESSION_HEADER: "bad session"},
                content=json.dumps({"input": "打开闹钟"}),
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.json(), {"error": "invalid_request"})
        self.assertEqual(invalid.json(), {"error": "invalid_request"})
        runner.assert_not_awaited()

    async def test_valid_request_returns_structured_success_and_forwards_context_session(self):
        result = completed_result(session_id="session-from-runner")
        runner = AsyncMock(return_value=result)

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=runner):
            response = await self.invoke({"input": "根据会议号开启快速会议"}, session_id="session-42")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result.to_dict())
        self.assertEqual(response.headers[SESSION_HEADER], "session-42")
        runner.assert_awaited_once_with(
            "根据会议号开启快速会议",
            session_id="session-42",
        )

    async def test_repeated_session_id_starts_independent_tasks(self):
        results = [
            completed_result(task_id="task-a", session_id="session-shared"),
            completed_result(task_id="task-b", session_id="session-shared"),
        ]
        runner = AsyncMock(side_effect=results)

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=runner):
            first = await self.invoke({"input": "任务一"}, session_id="session-shared")
            second = await self.invoke({"input": "任务二"}, session_id="session-shared")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["task_id"], second.json()["task_id"])
        self.assertNotEqual(first.json()["thread_id"], second.json()["thread_id"])
        self.assertEqual([call.args[0] for call in runner.await_args_list], ["任务一", "任务二"])

    async def test_task_failure_maps_to_safe_local_error(self):
        with patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=AsyncMock(return_value=failed_result("step_limit")),
        ):
            response = await self.invoke({"input": "任务"})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "task_failed")
        self.assertEqual(response.json()["terminal_reason"], "step_limit")
        self.assertNotIn("result", response.json())

    async def test_device_failure_maps_to_502_and_runtime_failure_to_500(self):
        for reason, expected_status, expected_error in (
            ("device_observation_failed", 502, "device_upstream_failed"),
            ("device_offline", 502, "device_upstream_failed"),
            ("prepare_failed", 502, "device_upstream_failed"),
            ("provider_configuration", 500, "runtime_failed"),
        ):
            with patch(
                "mobile_agent.agentarts_runtime.run_koophone_task",
                new=AsyncMock(return_value=failed_result(reason)),
            ):
                response = await self.invoke({"input": "任务"})

            self.assertEqual(response.status_code, expected_status, reason)
            self.assertEqual(response.json()["error"], expected_error, reason)

    async def test_entrypoint_exception_is_redacted(self):
        with patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=AsyncMock(side_effect=RuntimeError("secret-token-from-upstream")),
        ):
            response = await self.invoke({"input": "任务"})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "runtime_failed"})
        self.assertNotIn("secret-token-from-upstream", response.text)

    async def test_invalid_json_is_redacted_by_sdk_adapter(self):
        response = await self.client.post(
            "/invocations",
            headers={SESSION_HEADER: "session-test", "content-type": "application/json"},
            content=b'{"input": "unterminated',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_request"})

    async def test_sdk_exception_log_is_redacted(self):
        original_handler = app.handlers["main"]

        async def exploding_handler(payload, context):
            raise RuntimeError("secret-token-from-sdk")

        stream = StringIO()
        capture = logging.StreamHandler(stream)
        sdk_logger = logging.getLogger("agentarts.runtime.app")
        sdk_logger.addHandler(capture)
        try:
            app.handlers["main"] = exploding_handler
            response = await self.invoke({"input": "任务"})
        finally:
            app.handlers["main"] = original_handler
            sdk_logger.removeHandler(capture)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-token-from-sdk", stream.getvalue())
        self.assertNotIn("Traceback", stream.getvalue())

    async def test_provider_exception_log_is_redacted_at_runtime_boundary(self):
        stream = StringIO()
        capture = logging.StreamHandler(stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(capture)

        async def exploding_runner(prompt, *, session_id):
            logging.getLogger("mobile_agent.agent.mobile.client").error(
                "upstream URL https://device.example/internal?token=secret-token",
                exc_info=RuntimeError("provider-private-details"),
            )
            raise RuntimeError("provider-private-details")

        try:
            configure_runtime_logging()
            with patch(
                "mobile_agent.agentarts_runtime.run_koophone_task",
                new=exploding_runner,
            ):
                response = await self.invoke({"input": "任务"})
        finally:
            root_logger.removeHandler(capture)

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-token", stream.getvalue())
        self.assertNotIn("provider-private-details", stream.getvalue())
        self.assertNotIn("Traceback", stream.getvalue())
        self.assertIn("AgentArts runtime internal error", stream.getvalue())

    async def test_main_binds_all_interfaces_and_reads_port(self):
        with patch.dict(os.environ, {"AGENT_RUN_PORT": "9091"}, clear=False), patch.object(
            app, "run"
        ) as run:
            main()

        run.assert_called_once_with(host="0.0.0.0", port=9091)

    async def test_main_defaults_to_port_8080(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app, "run") as run:
            main()

        run.assert_called_once_with(host="0.0.0.0", port=8080)
