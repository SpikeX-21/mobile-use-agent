# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.koophone_cli import run_koophone_vision_demo
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
