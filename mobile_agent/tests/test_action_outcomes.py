# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
import unittest
import uuid

from mobile_agent.agent.actions import FinishAction, LaunchAppAction, TapAction
from mobile_agent.agent.actions.mcp_adapter import canonical_action_to_mcp_tool_call
from mobile_agent.agent.llm.provider import ActionParseError
from mobile_agent.agent.mobile.result import (
    ActionResult,
    DeviceBackendError,
    DeviceErrorKind,
)
from mobile_agent.agent.mobile_use_agent import MobileUseAgent


class ScriptedProvider:
    name = "scripted"
    prompt = "test prompt"
    supports_streaming = False

    def __init__(self, actions, events):
        self.actions = list(actions)
        self.events = events
        self.calls = 0
        self.observed_messages = []

    async def async_chat(self, messages):
        self.calls += 1
        self.events.append(f"model:{self.calls}")
        self.observed_messages.append(list(messages))
        action = self.actions[0]
        return (f"chunk-{self.calls}", action.type, action.type, action.type)

    def parse_action(self, action_call):
        return self.actions.pop(0)


class OutcomeBackend:
    name = "outcome-backend"

    def __init__(self, results, events, oracle=True):
        self.results = list(results)
        self.events = events
        self.oracle = oracle
        self.executed = 0
        self.screenshots = 0

    async def initialize(self, **connection):
        return None

    async def close(self):
        return None

    async def take_screenshot(self):
        self.screenshots += 1
        self.events.append(f"screenshot:{self.screenshots}")
        return {
            "screenshot": f"data:image/png;base64,screen-{self.screenshots}",
            "screenshot_dimensions": (1080, 2278),
        }

    def to_tool_call(self, action, screenshot_dimensions):
        return canonical_action_to_mcp_tool_call(action, screenshot_dimensions)

    async def execute(self, action, screenshot_dimensions):
        self.executed += 1
        self.events.append(f"execute:{self.executed}")
        return self.results.pop(0)

    async def verify_completion(self, action):
        return self.oracle


class BrokenSchemaProvider:
    name = "broken-schema"
    prompt = "test prompt"
    supports_streaming = False

    def __init__(self):
        self.calls = 0

    async def async_chat(self, messages):
        self.calls += 1
        return (f"bad-{self.calls}", "invalid", "invalid", "invalid")

    def parse_action(self, action_call):
        raise ActionParseError("invalid schema")


class RepeatingTapProvider:
    name = "repeating-tap"
    prompt = "test prompt"
    supports_streaming = False

    def __init__(self):
        self.calls = 0

    async def async_chat(self, messages):
        self.calls += 1
        return (f"tap-{self.calls}", "tap", "tap", "tap")

    def parse_action(self, action_call):
        return TapAction(x=500, y=450)


class SchemaFailureOnTenthProvider(RepeatingTapProvider):
    def parse_action(self, action_call):
        if self.calls == 10:
            raise ActionParseError("invalid schema on final step")
        return super().parse_action(action_call)


class AlwaysSuccessfulBackend(OutcomeBackend):
    def __init__(self, events=None):
        super().__init__([], events if events is not None else [])

    async def execute(self, action, screenshot_dimensions):
        self.executed += 1
        return ActionResult.success("tap dispatched")


class OfflineObservationBackend(AlwaysSuccessfulBackend):
    async def take_screenshot(self):
        raise DeviceBackendError("device offline", kind=DeviceErrorKind.OFFLINE)


class UnsupportedActionProvider(RepeatingTapProvider):
    def parse_action(self, action_call):
        return LaunchAppAction(package_name="com.autonavi.minimap")


class TapOnlyBackend(AlwaysSuccessfulBackend):
    def to_tool_call(self, action, screenshot_dimensions):
        if not isinstance(action, TapAction):
            raise NotImplementedError("tap only")
        return super().to_tool_call(action, screenshot_dimensions)


async def run_agent(provider, backend):
    agent = MobileUseAgent(
        model_provider_name="kimi",
        device_provider_name="adb",
        model_provider_factory=lambda *args, **kwargs: provider,
        device_backend_factory=lambda name: backend,
    )
    agent.step_interval = 0
    await agent.initialize("", "", "", "", "", "")
    return [
        chunk
        async for chunk in agent.run(
            "打开高德地图",
            is_stream=False,
            task_id="task-outcome",
            session_id="session-outcome",
            thread_id=f"chat-{uuid.uuid4()}",
            sse_connection=asyncio.Event(),
            phone_width=1080,
            phone_height=2278,
        )
    ]


def custom_output(chunks):
    return "\n".join(
        chunk[1]
        for chunk in chunks
        if isinstance(chunk, tuple)
        and chunk[0] == "custom"
        and isinstance(chunk[1], str)
    )


class ActionOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_ambiguous_but_effective_action_observes_before_finishing(self):
        events = []
        provider = ScriptedProvider(
            [TapAction(x=500, y=450), FinishAction(summary="opened")], events
        )
        backend = OutcomeBackend(
            [
                ActionResult.ambiguous(
                    "tap timed out", DeviceErrorKind.TIMEOUT
                )
            ],
            events,
        )

        chunks = await run_agent(provider, backend)

        self.assertEqual(backend.executed, 1)
        self.assertEqual(
            events[:5],
            ["screenshot:1", "model:1", "execute:1", "screenshot:2", "model:2"],
        )
        second_observation = provider.observed_messages[1][-1].content
        self.assertIn("ambiguous", str(second_observation))
        output = custom_output(chunks)
        self.assertEqual(output.count('"status": "stop"'), 1)
        self.assertNotIn('"status": "success"', output)

    async def test_ambiguous_ineffective_action_can_be_chosen_again_after_observation(self):
        events = []
        provider = ScriptedProvider(
            [
                TapAction(x=500, y=450),
                TapAction(x=500, y=450),
                FinishAction(summary="opened"),
            ],
            events,
        )
        backend = OutcomeBackend(
            [
                ActionResult.ambiguous("tap timed out", DeviceErrorKind.TIMEOUT),
                ActionResult.success("tap dispatched"),
            ],
            events,
        )

        await run_agent(provider, backend)

        first_execute = events.index("execute:1")
        second_execute = events.index("execute:2")
        self.assertIn("screenshot:2", events[first_execute + 1 : second_execute])
        self.assertEqual(backend.executed, 2)

    async def test_device_offline_stops_with_one_failed_sse_terminal(self):
        events = []
        provider = ScriptedProvider([TapAction(x=500, y=450)], events)
        backend = OutcomeBackend(
            [ActionResult.failed("device offline", DeviceErrorKind.OFFLINE)],
            events,
        )

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(output.count('"status": "stop"'), 1)
        self.assertNotIn('"status": "success"', output)
        self.assertIn("device offline", output)

    async def test_three_consecutive_schema_errors_end_with_explicit_reason(self):
        provider = BrokenSchemaProvider()
        backend = AlwaysSuccessfulBackend()

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 3)
        self.assertIn("连续 3 次", output)
        self.assertIn("Schema", output)

    async def test_agent_has_a_hard_ten_step_limit_with_explicit_reason(self):
        provider = RepeatingTapProvider()
        backend = AlwaysSuccessfulBackend()

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 10)
        self.assertEqual(backend.executed, 10)
        self.assertIn("达到 10 步上限", output)

    async def test_schema_failure_on_tenth_step_does_not_call_model_again(self):
        provider = SchemaFailureOnTenthProvider()
        backend = AlwaysSuccessfulBackend()

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 10)
        self.assertEqual(backend.executed, 9)
        self.assertIn("达到 10 步上限", output)

    async def test_oracle_failure_on_tenth_step_does_not_call_model_again(self):
        events = []
        provider = ScriptedProvider(
            [TapAction(x=500, y=450)] * 9
            + [FinishAction(summary="opened"), FinishAction(summary="opened")],
            events,
        )
        backend = OutcomeBackend(
            [ActionResult.success("tap dispatched")] * 9,
            events,
            oracle=False,
        )

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 10)
        self.assertEqual(backend.executed, 9)
        self.assertIn("达到 10 步上限", output)

    async def test_offline_during_observation_ends_before_model_call(self):
        provider = RepeatingTapProvider()
        backend = OfflineObservationBackend()

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 0)
        self.assertIn("设备离线", output)

    async def test_ten_unsupported_actions_end_explicitly_instead_of_recursing(self):
        provider = UnsupportedActionProvider()
        backend = TapOnlyBackend()

        chunks = await run_agent(provider, backend)

        output = custom_output(chunks)
        self.assertEqual(provider.calls, 10)
        self.assertEqual(backend.executed, 0)
        self.assertIn("达到 10 步上限", output)


if __name__ == "__main__":
    unittest.main()
