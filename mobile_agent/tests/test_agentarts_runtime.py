# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
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
    MAX_REQUEST_BODY_BYTES,
    MAX_INPUT_LENGTH,
    app,
    configure_runtime_logging,
    FIXED_DEVICE_SLOT,
    main,
    runtime_health,
    RuntimeAuditStdoutHandler,
)
from mobile_agent.runtime.device_lease import InProcessDeviceLease
from mobile_agent.runtime.security import RuntimeConfigurationError


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
        self.lease_provider = InProcessDeviceLease()
        self.lease_patcher = patch(
            "mobile_agent.agentarts_runtime.device_lease_provider",
            new=self.lease_provider,
        )
        self.lease_patcher.start()
        runtime_health.set_ready(True)
        runtime_health.set_busy(False)

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        self.lease_patcher.stop()
        runtime_health.set_ready(True)
        runtime_health.set_busy(False)

    async def invoke(
        self,
        payload: object,
        *,
        session_id: str = "session-test",
        content_type: str = "application/json",
    ) -> httpx.Response:
        return await self.client.post(
            "/invocations",
            headers={SESSION_HEADER: session_id, "content-type": content_type},
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

    async def test_ping_reports_healthy_busy_while_the_fixed_device_is_occupied(self):
        started = asyncio.Event()
        finish = asyncio.Event()

        async def blocking_runner(prompt, **kwargs):
            started.set()
            await finish.wait()
            return completed_result(task_id=kwargs["task_id"])

        with patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=blocking_runner,
        ):
            request = asyncio.create_task(self.invoke({"input": "长任务"}))
            await asyncio.wait_for(started.wait(), timeout=0.2)

            busy_ping = await self.client.get("/ping")
            self.assertEqual(busy_ping.status_code, 200)
            self.assertEqual(busy_ping.json()["status"], "HealthyBusy")

            finish.set()
            response = await request

        self.assertEqual(response.status_code, 200)
        idle_ping = await self.client.get("/ping")
        self.assertEqual(idle_ping.json()["status"], "Healthy")

    async def test_busy_request_is_rejected_before_agent_and_uses_server_fixed_slot(self):
        lease = await self.lease_provider.try_acquire(FIXED_DEVICE_SLOT)
        self.assertIsNotNone(lease)

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            response = await self.invoke({"input": "第二个任务"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"error": "device_busy"})
        runner.assert_not_awaited()
        self.assertTrue(self.lease_provider.busy)
        await lease.release()

    async def test_failed_and_exception_runs_release_slot_for_next_request(self):
        runner = AsyncMock(
            side_effect=[
                failed_result("step_limit"),
                RuntimeError("provider details"),
                completed_result(task_id="task-after-failure"),
            ]
        )

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=runner):
            failed = await self.invoke({"input": "失败任务"})
            errored = await self.invoke({"input": "异常任务"})
            recovered = await self.invoke({"input": "恢复任务"})

        self.assertEqual(failed.status_code, 422)
        self.assertEqual(errored.status_code, 500)
        self.assertEqual(recovered.status_code, 200)
        self.assertFalse(self.lease_provider.busy)

    async def test_timeout_cancels_runner_waits_for_cleanup_and_releases_slot(self):
        cancelled = asyncio.Event()
        calls = 0

        async def timeout_runner(prompt, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
            return completed_result(task_id=kwargs["task_id"])

        with patch.dict(os.environ, {"AGENT_TASK_TIMEOUT_SECONDS": "0.01"}), patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=timeout_runner,
        ):
            timed_out = await self.invoke({"input": "超时任务"})
            recovered = await self.invoke({"input": "超时后任务"})

        self.assertEqual(timed_out.status_code, 504)
        self.assertEqual(timed_out.json()["error"], "task_timeout")
        self.assertEqual(timed_out.json()["terminal_reason"], "timeout")
        self.assertEqual(recovered.status_code, 200)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(self.lease_provider.busy)

    async def test_client_cancellation_releases_slot_for_next_request(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        calls = 0

        async def cancellable_runner(prompt, **kwargs):
            nonlocal calls
            calls += 1
            if calls > 1:
                return completed_result(task_id=kwargs["task_id"])
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=cancellable_runner,
        ):
            request = asyncio.create_task(self.invoke({"input": "取消任务"}))
            await asyncio.wait_for(started.wait(), timeout=0.2)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request

            recovered = await self.invoke({"input": "取消后任务"})

        self.assertTrue(cancelled.is_set())
        self.assertEqual(recovered.status_code, 200)
        self.assertFalse(self.lease_provider.busy)

    async def test_invalid_task_timeout_is_rejected_before_agent(self):
        for raw_timeout in ("not-a-number", "0", "nan", "inf"):
            with self.subTest(raw_timeout=raw_timeout):
                with patch.dict(
                    os.environ,
                    {"AGENT_TASK_TIMEOUT_SECONDS": raw_timeout},
                ), patch(
                    "mobile_agent.agentarts_runtime.run_koophone_task",
                    new=AsyncMock(),
                ) as runner:
                    response = await self.invoke({"input": "任务"})

                self.assertEqual(response.status_code, 500)
                self.assertEqual(response.json(), {"error": "runtime_failed"})
                runner.assert_not_awaited()
                self.assertFalse(self.lease_provider.busy)

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
                headers={"content-type": "application/json"},
                content=json.dumps({"input": "打开闹钟"}),
            )
            invalid = await self.client.post(
                "/invocations",
                headers={
                    SESSION_HEADER: "bad session",
                    "content-type": "application/json",
                },
                content=json.dumps({"input": "打开闹钟"}),
            )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(missing.json(), {"error": "invalid_request"})
        self.assertEqual(invalid.json(), {"error": "invalid_request"})
        runner.assert_not_awaited()

    async def test_session_id_rejects_unsupported_punctuation_and_credential_shapes(self):
        invalid_ids = (
            "session.with.dot",
            "session:with-colon",
            "sk-123456789012345678901234",
            "eyJheader.eyJpayload.signature",
        )

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            for session_id in invalid_ids:
                response = await self.invoke({"input": "任务"}, session_id=session_id)
                self.assertEqual(response.status_code, 400, session_id)
                self.assertEqual(response.json(), {"error": "invalid_request"})

        runner.assert_not_awaited()

    async def test_invocation_requires_json_content_type(self):
        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            response = await self.invoke(
                {"input": "任务"},
                content_type="text/plain",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_request"})
        runner.assert_not_awaited()

    async def test_oversized_body_is_rejected_before_json_or_agent_work(self):
        oversized = b'{"input":"' + b"x" * MAX_REQUEST_BODY_BYTES + b'"}'

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=AsyncMock()) as runner:
            response = await self.client.post(
                "/invocations",
                headers={
                    SESSION_HEADER: "session-test",
                    "content-type": "application/json",
                },
                content=oversized,
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "invalid_request"})
        runner.assert_not_awaited()

    async def test_valid_request_returns_structured_success_and_forwards_context_session(self):
        result = completed_result(session_id="session-from-runner")
        runner = AsyncMock(return_value=result)

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=runner):
            response = await self.invoke({"input": "根据会议号开启快速会议"}, session_id="session-42")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), result.to_dict())
        self.assertEqual(response.headers[SESSION_HEADER], "session-42")
        runner.assert_awaited_once()
        call = runner.await_args
        self.assertEqual(call.args, ("根据会议号开启快速会议",))
        self.assertEqual(call.kwargs["session_id"], "session-42")
        self.assertTrue(call.kwargs["task_id"].startswith("koophone-task-"))
        self.assertTrue(call.kwargs["thread_id"].startswith("koophone-thread-"))
        self.assertTrue(call.kwargs["propagate_cancellation"])

    async def test_inbound_authorization_is_not_forwarded_to_the_agent(self):
        runner = AsyncMock(return_value=completed_result())

        with patch("mobile_agent.agentarts_runtime.run_koophone_task", new=runner):
            response = await self.client.post(
                "/invocations",
                headers={
                    SESSION_HEADER: "session-test",
                    "authorization": "Bearer agentarts-inbound-key",
                    "content-type": "application/json",
                },
                content=json.dumps({"input": "任务"}),
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("agentarts-inbound-key", response.text)
        self.assertNotIn("authorization", runner.await_args.kwargs)
        self.assertNotIn("workload_access_token", runner.await_args.kwargs)

    async def test_runtime_result_does_not_echo_prompt_or_configured_secret(self):
        secret = "instance-secret-eid"
        result = AgentRunResult(
            status="completed",
            task_id="task-safe",
            thread_id="thread-safe",
            session_id=secret,
            result=f"instance={secret}; prompt=打开 {secret}",
            rounds=1,
            elapsed_ms=1,
            terminal_reason="completed",
        )

        with patch.dict(os.environ, {"KOOPHONE_INSTANCE_ID": secret}), patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=AsyncMock(return_value=result),
        ):
            response = await self.invoke(
                {"input": f"打开 {secret}"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "任务已完成")
        self.assertEqual(response.json()["session_id"], "session-unknown")
        self.assertEqual(response.headers[SESSION_HEADER], "session-test")
        self.assertNotIn(secret, response.text)

    async def test_runtime_result_does_not_echo_raw_model_trace_or_untrusted_ids(self):
        result = AgentRunResult(
            status="completed",
            task_id="/home/runtime/private/task.json",
            thread_id="https://internal.example/trace",
            session_id="session-safe",
            result='{"action":{"type":"tap"},"analysis":"private trace"}',
            rounds=1,
            elapsed_ms=1,
            terminal_reason="completed",
        )

        with patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=AsyncMock(return_value=result),
        ):
            response = await self.invoke({"input": "任务"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["result"], "任务已完成")
        self.assertEqual(body["task_id"], "task-unknown")
        self.assertEqual(body["thread_id"], "thread-unknown")
        self.assertNotIn("/home/runtime", response.text)
        self.assertNotIn("internal.example", response.text)
        self.assertNotIn("analysis", response.text)

    async def test_runtime_result_does_not_echo_data_urls_or_bare_base64_images(self):
        result = AgentRunResult(
            status="completed",
            task_id="task-safe",
            thread_id="thread-safe",
            session_id="session-safe",
            result=(
                "data:application/octet-stream;base64,"
                "iVBORw0KGgoAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            ),
            rounds=1,
            elapsed_ms=1,
            terminal_reason="completed",
        )

        with patch(
            "mobile_agent.agentarts_runtime.run_koophone_task",
            new=AsyncMock(return_value=result),
        ):
            response = await self.invoke({"input": "任务"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], "任务已完成")
        self.assertNotIn("iVBORw0KGgo", response.text)

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

        async def exploding_runner(prompt, *, session_id, **kwargs):
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

    async def test_runtime_stdout_event_is_allowlisted_and_does_not_include_prompt(self):
        stream = StringIO()
        capture = logging.StreamHandler(stream)
        audit_logger = logging.getLogger("agentarts.runtime.audit")
        audit_logger.addHandler(capture)
        prompt = "执行任务，不要输出 sk-123456789012345678901234"
        try:
            configure_runtime_logging()
            with patch(
                "mobile_agent.agentarts_runtime.run_koophone_task",
                new=AsyncMock(return_value=completed_result()),
            ):
                response = await self.invoke({"input": prompt})
        finally:
            audit_logger.removeHandler(capture)

        self.assertEqual(response.status_code, 200)
        output = stream.getvalue()
        self.assertIn('"event":"runtime_invocation"', output)
        self.assertIn('"provider":"kimi"', output)
        self.assertIn('"model":"kimi-k2.6"', output)
        self.assertNotIn(prompt, output)
        self.assertNotIn("sk-123456789012345678901234", output)
        self.assertNotIn("instanceId", output)

    def test_runtime_audit_has_one_dedicated_stdout_handler(self):
        configure_runtime_logging()
        configure_runtime_logging()

        audit_logger = logging.getLogger("agentarts.runtime.audit")
        handlers = [
            handler
            for handler in audit_logger.handlers
            if isinstance(handler, RuntimeAuditStdoutHandler)
        ]

        self.assertEqual(len(handlers), 1)
        self.assertEqual(handlers[0].level, logging.INFO)
        self.assertFalse(audit_logger.propagate)

    def test_main_fails_before_serving_when_local_configuration_is_invalid(self):
        with patch(
            "mobile_agent.agentarts_runtime.validate_runtime_configuration",
            side_effect=RuntimeConfigurationError("KOOPHONE_JKS_PATH"),
        ), patch.object(app, "run") as run:
            with self.assertRaises(SystemExit) as raised:
                main()

        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    def test_main_rejects_invalid_runtime_port_without_raw_exception(self):
        with patch.dict(os.environ, {"AGENT_RUN_PORT": "not-a-port"}), patch(
            "mobile_agent.agentarts_runtime.validate_runtime_configuration"
        ), patch.object(app, "run") as run:
            with self.assertRaises(SystemExit) as raised:
                main()

        self.assertEqual(raised.exception.code, 2)
        run.assert_not_called()

    async def test_main_binds_all_interfaces_and_reads_port(self):
        with patch.dict(os.environ, {"AGENT_RUN_PORT": "9091"}, clear=False), patch.object(
            app, "run"
        ) as run, patch(
            "mobile_agent.agentarts_runtime.validate_runtime_configuration"
        ) as validate:
            main()

        run.assert_called_once_with(host="0.0.0.0", port=9091, access_log=False)
        validate.assert_called_once()

    async def test_main_defaults_to_port_8080(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app, "run") as run, patch(
            "mobile_agent.agentarts_runtime.validate_runtime_configuration"
        ):
            main()

        run.assert_called_once_with(host="0.0.0.0", port=8080, access_log=False)
