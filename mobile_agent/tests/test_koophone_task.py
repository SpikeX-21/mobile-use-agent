# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest

from mobile_agent.agent.actions import FailAction, FinishAction
from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.agent.run_result import AgentRunResult
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.agent.actions.mcp_adapter import canonical_action_to_mcp_tool_call
from mobile_agent.koophone_task import run_koophone_task


class FakeAgent:
    def __init__(self, *, result: AgentRunResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.closed = 0
        self.initialized = 0

    async def initialize(self, *connection):
        self.initialized += 1
        if self.error is not None:
            raise self.error

    async def run(self, prompt, **kwargs):
        yield ("custom", "safe")

    def get_last_run_result(self, *, elapsed_ms=None, fallback_task_id=None, fallback_thread_id=None):
        return self.result

    async def aclose(self):
        self.closed += 1


class OneActionProvider:
    name = "test-provider"
    model = "test-model"
    prompt = "test prompt"
    supports_streaming = False

    def __init__(self, action):
        self.action = action

    async def async_chat(self, messages):
        return ("chunk", "summary", "summary", "action")

    def parse_action(self, action_call):
        return self.action


class OneActionBackend:
    name = "test-device"

    async def initialize(self, **connection):
        return None

    async def close(self):
        return None

    async def take_screenshot(self):
        return {
            "screenshot": "data:image/png;base64,screen",
            "screenshot_dimensions": (100, 100),
        }

    def to_tool_call(self, action, screenshot_dimensions):
        return canonical_action_to_mcp_tool_call(action, screenshot_dimensions)

    async def execute(self, action, screenshot_dimensions):
        return "ok"

    async def verify_completion(self, action):
        return True


class KooPhoneTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_returns_business_result_and_closes_agent_once(self):
        agent = FakeAgent(
            result=AgentRunResult(
                status="completed",
                task_id="task-1",
                thread_id="thread-1",
                session_id="session-1",
                result="已完成，不包含坐标",
                rounds=3,
                elapsed_ms=12,
                terminal_reason="completed",
            )
        )

        result = await run_koophone_task(
            "打开应用",
            agent_factory=lambda **kwargs: agent,
            task_id="task-1",
            thread_id="thread-1",
            session_id="session-1",
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.result, "已完成，不包含坐标")
        self.assertEqual(result.rounds, 3)
        self.assertEqual(result.terminal_reason, "completed")
        self.assertEqual(agent.initialized, 1)
        self.assertEqual(agent.closed, 1)

    async def test_provider_configuration_failure_is_structured_and_does_not_leak(self):
        result = await run_koophone_task(
            "打开应用",
            agent_factory=lambda **kwargs: (_ for _ in ()).throw(
                ProviderConfigurationError("Authorization: Bearer private-token")
            ),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.terminal_reason, "provider_configuration")
        self.assertEqual(result.result, None)
        self.assertNotIn("private-token", result.to_json())

    async def test_initializer_failure_closes_agent_and_returns_failure(self):
        agent = FakeAgent(error=RuntimeError("upstream private details"))

        result = await run_koophone_task(
            "打开应用",
            agent_factory=lambda **kwargs: agent,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.terminal_reason, "runtime_failed")
        self.assertIsNone(result.result)
        self.assertEqual(agent.closed, 1)
        self.assertNotIn("upstream private details", result.to_json())

    async def test_provider_runtime_failure_is_not_misclassified(self):
        def failing_provider(*args, **kwargs):
            raise RuntimeError("provider construction failed")

        with tempfile.TemporaryDirectory() as directory:
            agent = MobileUseAgent(
                model_provider_name="kimi",
                device_provider_name="adb",
                model_provider_factory=failing_provider,
                device_backend_factory=lambda name: OneActionBackend(),
                experiment_record_path=Path(directory) / "runs.jsonl",
            )
            await agent.initialize("", "", "", "", "", "")
            try:
                with self.assertRaisesRegex(RuntimeError, "provider construction failed"):
                    async for _ in agent.run(
                        "打开应用",
                        is_stream=False,
                        task_id="task-provider-runtime-failure",
                        session_id="session-provider-runtime-failure",
                        thread_id="thread-provider-runtime-failure",
                        sse_connection=asyncio.Event(),
                        phone_width=100,
                        phone_height=100,
                    ):
                        pass
                result = agent.get_last_run_result()
            finally:
                await agent.aclose()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.terminal_reason, "runtime_failed")
        self.assertNotIn("provider construction failed", result.to_json())

    async def test_cancelled_task_is_a_structured_cancelled_result_and_closes_agent(self):
        agent = FakeAgent()

        async def cancelled_run(prompt, **kwargs):
            raise asyncio.CancelledError
            yield  # pragma: no cover

        agent.run = cancelled_run
        result = await run_koophone_task(
            "打开应用",
            agent_factory=lambda **kwargs: agent,
        )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.terminal_reason, "cancelled")
        self.assertEqual(agent.closed, 1)

    async def test_propagated_cancellation_still_closes_agent(self):
        agent = FakeAgent()

        async def cancelled_run(prompt, **kwargs):
            raise asyncio.CancelledError
            yield  # pragma: no cover

        agent.run = cancelled_run
        with self.assertRaises(asyncio.CancelledError):
            await run_koophone_task(
                "打开应用",
                agent_factory=lambda **kwargs: agent,
                propagate_cancellation=True,
            )

        self.assertEqual(agent.closed, 1)

    async def test_propagated_cancellation_waits_for_agent_cleanup(self):
        cleanup_finished = asyncio.Event()

        class SlowCloseAgent(FakeAgent):
            async def aclose(self):
                await asyncio.sleep(0.01)
                self.closed += 1
                cleanup_finished.set()

        agent = SlowCloseAgent()

        async def cancelled_run(prompt, **kwargs):
            raise asyncio.CancelledError
            yield  # pragma: no cover

        agent.run = cancelled_run
        with self.assertRaises(asyncio.CancelledError):
            await run_koophone_task(
                "打开应用",
                agent_factory=lambda **kwargs: agent,
                propagate_cancellation=True,
            )

        self.assertTrue(cleanup_finished.is_set())
        self.assertEqual(agent.closed, 1)

    def test_result_redacts_observation_and_coordinate_summary(self):
        for summary in (
            "点击坐标 (123, 456)，截图 data:image/png;base64,secret",
            '动作参数 {"x":123,"y":456}',
            "点击坐标 123, 456",
            "analysis: internal reasoning",
        ):
            with self.subTest(summary=summary):
                result = AgentRunResult(
                    status="completed",
                    task_id="task-safe",
                    thread_id="thread-safe",
                    session_id="session-safe",
                    result=summary,
                    rounds=1,
                    elapsed_ms=1,
                    terminal_reason="completed",
                )

                self.assertEqual(result.result, "任务已完成")
                self.assertNotIn("data:image", result.to_json())
                self.assertNotIn("123", result.to_json())

    def test_result_rejects_inconsistent_status_and_terminal_reason(self):
        with self.assertRaises(ValueError):
            AgentRunResult(
                status="completed",
                task_id="task-invalid",
                thread_id="thread-invalid",
                session_id="session-invalid",
                result="完成",
                rounds=1,
                elapsed_ms=1,
                terminal_reason="runtime_failed",
            )

    async def test_business_success_survives_recorder_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = MobileUseAgent(
                model_provider_name="kimi",
                device_provider_name="adb",
                model_provider_factory=lambda *args, **kwargs: OneActionProvider(
                    FinishAction(summary="已完成任务")
                ),
                device_backend_factory=lambda name: OneActionBackend(),
                experiment_record_path=Path(directory),
            )
            agent.step_interval = 0
            await agent.initialize("", "", "", "", "", "")
            try:
                async for _ in agent.run(
                    "执行任务",
                    is_stream=False,
                    task_id="task-business-success",
                    session_id="session-business-success",
                    thread_id="thread-business-success",
                    sse_connection=asyncio.Event(),
                    phone_width=100,
                    phone_height=100,
                ):
                    pass
                result = agent.get_last_run_result()
            finally:
                await agent.aclose()

        self.assertIsNotNone(result)
        self.assertTrue(result.completed)
        self.assertEqual(result.terminal_reason, "completed")
        self.assertEqual(result.result, "已完成任务")

    async def test_agent_declared_failure_is_not_reported_as_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = MobileUseAgent(
                model_provider_name="kimi",
                device_provider_name="adb",
                model_provider_factory=lambda *args, **kwargs: OneActionProvider(
                    FailAction(reason="无法完成")
                ),
                device_backend_factory=lambda name: OneActionBackend(),
                experiment_record_path=Path(directory) / "runs.jsonl",
            )
            agent.step_interval = 0
            await agent.initialize("", "", "", "", "", "")
            try:
                async for _ in agent.run(
                    "执行任务",
                    is_stream=False,
                    task_id="task-business-failure",
                    session_id="session-business-failure",
                    thread_id="thread-business-failure",
                    sse_connection=asyncio.Event(),
                    phone_width=100,
                    phone_height=100,
                ):
                    pass
                result = agent.get_last_run_result()
            finally:
                await agent.aclose()

        self.assertIsNotNone(result)
        self.assertFalse(result.completed)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.terminal_reason, "model_failed")


if __name__ == "__main__":
    unittest.main()
