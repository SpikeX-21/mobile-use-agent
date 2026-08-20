# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import io
import unittest
from unittest.mock import AsyncMock, patch

from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.agent.run_result import AgentRunResult
from mobile_agent.koophone_cli import (
    main as vision_main,
    run_koophone_vision_demo,
)
from mobile_agent.koophone_alarm_cli import (
    ALARM_PROMPT,
    main as alarm_main,
    run_koophone_alarm_demo,
)


class RecordingAgent:
    def __init__(self, **providers):
        self.providers = providers
        self.initialized = False
        self.closed = False
        self.run_prompt = None
        self.last_terminal_reason = "completed"

    async def initialize(self, *connection):
        self.initialized = True

    async def run(self, prompt, **kwargs):
        self.run_prompt = prompt
        yield ("custom", "safe-output")

    def get_last_run_result(self, *, elapsed_ms=None):
        return AgentRunResult(
            status="completed",
            task_id="task-recording",
            thread_id="thread-recording",
            session_id="session-recording",
            result="任务已完成",
            rounds=1,
            elapsed_ms=elapsed_ms or 0,
            terminal_reason="completed",
        )

    async def aclose(self):
        self.closed = True


class KooPhoneCliTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_adapter_uses_the_same_agent_with_fixed_provider_selection(self):
        created = []

        def agent_factory(**providers):
            agent = RecordingAgent(**providers)
            created.append(agent)
            return agent

        chunk_count = await run_koophone_vision_demo(
            "观察后返回主页", agent_factory=agent_factory
        )

        self.assertEqual(chunk_count, 1)
        self.assertEqual(
            created[0].providers,
            {"model_provider_name": "kimi", "device_provider_name": "koophone_mcp"},
        )
        self.assertTrue(created[0].initialized)
        self.assertEqual(created[0].run_prompt, "观察后返回主页")
        self.assertTrue(created[0].closed)

    async def test_alarm_cli_runs_the_same_agent_with_an_idempotent_alarm_prompt(self):
        created = []

        def agent_factory(**providers):
            agent = RecordingAgent(**providers)
            created.append(agent)
            return agent

        chunk_count = await run_koophone_alarm_demo(agent_factory=agent_factory)

        self.assertEqual(chunk_count, 1)
        self.assertEqual(
            created[0].providers,
            {"model_provider_name": "kimi", "device_provider_name": "koophone_mcp"},
        )
        self.assertIn("09:00", created[0].run_prompt)
        self.assertIn("已启用", created[0].run_prompt)
        self.assertIn("最新截图", created[0].run_prompt)
        self.assertIn("com.android.deskclock", created[0].run_prompt)
        self.assertEqual(created[0].run_prompt, ALARM_PROMPT)


class KooPhoneCliMainTests(unittest.TestCase):
    def test_generic_vision_cli_fails_when_agent_terminal_is_not_completed(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch("sys.argv", ["koophone-vision", "--prompt", "测试任务"]),
            patch(
                "mobile_agent.koophone_cli.run_koophone_vision_task",
                new=AsyncMock(
                    return_value=AgentRunResult(
                        status="failed",
                        task_id="task-failure",
                        thread_id="thread-failure",
                        session_id="session-failure",
                        result=None,
                        rounds=3,
                        elapsed_ms=1,
                        terminal_reason="device_observation_failed",
                    )
                ),
            ),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = vision_main()

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            "KOOPHONE_VISION_DEMO=failed "
            "reason=device_observation_failed rounds=3\n",
        )

    def test_generic_vision_cli_reports_finished_only_for_completed_terminal(self):
        stdout = io.StringIO()
        with (
            patch("sys.argv", ["koophone-vision", "--prompt", "测试任务"]),
            patch(
                "mobile_agent.koophone_cli.run_koophone_vision_task",
                new=AsyncMock(
                    return_value=AgentRunResult(
                        status="completed",
                        task_id="task-success",
                        thread_id="thread-success",
                        session_id="session-success",
                        result="已完成",
                        rounds=2,
                        elapsed_ms=1,
                        terminal_reason="completed",
                    )
                ),
            ),
            patch("sys.stdout", stdout),
        ):
            result = vision_main()

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "KOOPHONE_VISION_DEMO=finished rounds=2\n")

    def test_generic_vision_cli_returns_nonzero_for_configuration_failure(self):
        stderr = io.StringIO()
        with (
            patch("sys.argv", ["koophone-vision"]),
            patch(
                "mobile_agent.koophone_cli.run_koophone_vision_task",
                new=AsyncMock(
                    side_effect=ProviderConfigurationError("test-only")
                ),
            ),
            patch("sys.stderr", stderr),
        ):
            result = vision_main()

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue(),
            "KOOPHONE_VISION_DEMO=failed reason=provider_configuration\n",
        )

    def test_generic_vision_cli_uses_structured_rounds_for_real_result(self):
        stdout = io.StringIO()
        structured_result = AgentRunResult(
            status="completed",
            task_id="task-structured",
            thread_id="thread-structured",
            session_id="session-structured",
            result="已完成",
            rounds=4,
            elapsed_ms=12,
            terminal_reason="completed",
        )
        with (
            patch("sys.argv", ["koophone-vision", "--prompt", "测试任务"]),
            patch(
                "mobile_agent.koophone_cli.run_koophone_vision_task",
                new=AsyncMock(return_value=structured_result),
            ),
            patch("sys.stdout", stdout),
        ):
            result = vision_main()

        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue(), "KOOPHONE_VISION_DEMO=finished rounds=4\n")

    def test_generic_vision_cli_returns_two_for_structured_configuration_failure(self):
        stderr = io.StringIO()
        structured_result = AgentRunResult(
            status="failed",
            task_id="task-structured",
            thread_id="thread-structured",
            session_id="session-structured",
            result=None,
            rounds=0,
            elapsed_ms=1,
            terminal_reason="provider_configuration",
        )
        with (
            patch("sys.argv", ["koophone-vision"]),
            patch(
                "mobile_agent.koophone_cli.run_koophone_vision_task",
                new=AsyncMock(return_value=structured_result),
            ),
            patch("sys.stderr", stderr),
        ):
            result = vision_main()

        self.assertEqual(result, 2)
        self.assertIn("reason=provider_configuration", stderr.getvalue())

    def test_authentication_probe_failure_exits_cleanly_before_llm_work(self):
        def fail_authentication(coroutine):
            coroutine.close()
            raise ProviderConfigurationError(
                "KooPhone startup authentication failed"
            )

        stderr = io.StringIO()
        with (
            patch("sys.argv", ["koophone-alarm"]),
            patch(
                "mobile_agent.koophone_alarm_cli.asyncio.run",
                side_effect=fail_authentication,
            ),
            patch("sys.stderr", stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            alarm_main()

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(
            stderr.getvalue(),
            "KOOPHONE_ALARM_DEMO=failed reason="
            "KooPhone startup authentication failed\n",
        )


if __name__ == "__main__":
    unittest.main()
