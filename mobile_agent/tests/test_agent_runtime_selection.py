# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     https://www.volcengine.com/docs/82379/1433703
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import asyncio
import unittest
import uuid

from mobile_agent.agent.actions import FailAction, FinishAction, WaitAction
from mobile_agent.agent.actions.mcp_adapter import canonical_action_to_mcp_tool_call
from mobile_agent.agent.graph.context import agent_object_manager
from mobile_agent.agent.llm.provider import DoubaoModelProvider
from mobile_agent.agent.mobile_use_agent import MobileUseAgent


class FakeModelProvider:
    name = "fake-model"
    prompt = "fake prompt"


class FakeDeviceBackend:
    name = "fake-device"

    def __init__(self):
        self.connection = None
        self.closed = False
        self.prepared_tasks = []

    async def initialize(self, **connection):
        self.connection = connection

    async def close(self):
        self.closed = True

    async def prepare_task(self, user_prompt):
        self.prepared_tasks.append(user_prompt)


class RecordingGraph:
    def __init__(self):
        self.context = None

    async def astream(self, input, config, stream_mode):
        thread_id = input["thread_id"]
        self.context = {
            "model": agent_object_manager.get_model_provider(thread_id),
            "device": agent_object_manager.get_device_backend(thread_id),
        }
        yield ("custom", "graph-output")


class SequenceLlm:
    def __init__(self):
        self.responses = [
            (
                "chunk-1",
                "Summary: 点击地图\nAction: click(...) ",
                "点击地图",
                "click(start_box='<bbox>400 300 600 700</bbox>')",
            ),
            (
                "chunk-2",
                "Summary: 已完成\nAction: finished(content='已完成')",
                "已完成",
                "finished(content='已完成')",
            ),
        ]

    async def async_chat(self, messages):
        return self.responses.pop(0)


class FakeMcpBackend(FakeDeviceBackend):
    def __init__(self):
        super().__init__()
        self.executed = []

    async def take_screenshot(self):
        return {
            "screenshot": "https://example.invalid/screenshot.png",
            "screenshot_dimensions": (1080, 2278),
        }

    def to_tool_call(self, action, screenshot_dimensions):
        return canonical_action_to_mcp_tool_call(action, screenshot_dimensions)

    async def execute(self, action, screenshot_dimensions):
        self.executed.append((action, screenshot_dimensions))
        return "ok"


class CanonicalSequenceProvider:
    name = "fake-canonical"
    prompt = "fake prompt"

    def __init__(self):
        self.actions = [WaitAction(duration_ms=1), FailAction(reason="请登录")]

    async def async_chat(self, messages):
        action = self.actions[0]
        return (
            f"chunk-{len(self.actions)}",
            f"action={action.type}",
            action.type,
            action.type,
        )

    def parse_action(self, action_call):
        return self.actions.pop(0)


class RepeatedFinishProvider:
    name = "repeated-finish"
    prompt = "fake prompt"
    supports_streaming = False

    def __init__(self):
        self.calls = 0

    async def async_chat(self, messages):
        self.calls += 1
        return (f"finish-{self.calls}", "finish", "finish", "finish")

    def parse_action(self, action_call):
        return FinishAction(summary="model says complete")


class RejectingCompletionBackend(FakeMcpBackend):
    def __init__(self):
        super().__init__()
        self.oracle_calls = 0

    async def verify_completion(self, action):
        self.oracle_calls += 1
        return False


class AgentRuntimeSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_run_uses_selected_adapters_and_cleans_up_context(self):
        device = FakeDeviceBackend()
        model = FakeModelProvider()
        graph = RecordingGraph()
        selected = {}

        def device_factory(name):
            selected["device"] = name
            return device

        def model_factory(name, *, thread_id, is_stream):
            selected["model"] = (name, thread_id, is_stream)
            return model

        agent = MobileUseAgent(
            model_provider_name="doubao",
            device_provider_name="mcp",
            model_provider_factory=model_factory,
            device_backend_factory=device_factory,
            agent_graph=graph,
        )
        await agent.initialize(
            pod_id="pod-1",
            auth_token="token",
            product_id="product-1",
            tos_bucket="bucket",
            tos_region="region",
            tos_endpoint="endpoint",
        )

        chunks = [
            chunk
            async for chunk in agent.run(
                "打开高德地图",
                is_stream=False,
                task_id="task-1",
                session_id="session-1",
                thread_id="chat-1",
                sse_connection=asyncio.Event(),
                phone_width=1080,
                phone_height=2278,
            )
        ]

        self.assertEqual(chunks, [("custom", "graph-output")])
        self.assertEqual(selected["device"], "mcp")
        self.assertEqual(selected["model"], ("doubao", "chat-1", False))
        self.assertIs(graph.context["model"], model)
        self.assertIs(graph.context["device"], device)
        self.assertFalse(agent_object_manager.has_context("chat-1"))
        self.assertEqual(device.prepared_tasks, ["打开高德地图"])
        self.assertEqual(
            device.connection,
            {
                "pod_id": "pod-1",
                "auth_token": "token",
                "product_id": "product-1",
                "tos_bucket": "bucket",
                "tos_region": "region",
                "tos_endpoint": "endpoint",
            },
        )

    async def test_doubao_mcp_path_preserves_agent_loop_and_sse_tool_names(self):
        backend = FakeMcpBackend()
        llm = SequenceLlm()

        def model_factory(name, *, thread_id, is_stream):
            return DoubaoModelProvider(
                thread_id=thread_id, is_stream=is_stream, llm=llm
            )

        agent = MobileUseAgent(
            model_provider_name="doubao",
            device_provider_name="mcp",
            model_provider_factory=model_factory,
            device_backend_factory=lambda name: backend,
        )
        agent.step_interval = 0
        await agent.initialize(
            pod_id="pod-1",
            auth_token="token",
            product_id="product-1",
            tos_bucket="bucket",
            tos_region="region",
            tos_endpoint="endpoint",
        )

        chunks = [
            chunk
            async for chunk in agent.run(
                "打开高德地图",
                is_stream=False,
                task_id="task-2",
                session_id="session-2",
                thread_id=f"chat-{uuid.uuid4()}",
                sse_connection=asyncio.Event(),
                phone_width=1080,
                phone_height=2278,
            )
        ]
        custom_output = "\n".join(
            chunk[1]
            for chunk in chunks
            if isinstance(chunk, tuple)
            and chunk[0] == "custom"
            and isinstance(chunk[1], str)
        )

        self.assertEqual(len(backend.executed), 1)
        self.assertEqual(backend.executed[0][1], (1080, 2278))
        self.assertIn('"tool_name": "mobile:tap"', custom_output)
        self.assertIn('"type": "summary"', custom_output)
        self.assertIn('"content": "已完成"', custom_output)

    async def test_wait_and_fail_keep_their_existing_sse_behavior(self):
        backend = FakeMcpBackend()
        provider = CanonicalSequenceProvider()
        agent = MobileUseAgent(
            model_provider_name="doubao",
            device_provider_name="mcp",
            model_provider_factory=lambda *args, **kwargs: provider,
            device_backend_factory=lambda name: backend,
        )
        agent.step_interval = 0
        await agent.initialize(
            pod_id="pod-1",
            auth_token="token",
            product_id="product-1",
            tos_bucket="bucket",
            tos_region="region",
            tos_endpoint="endpoint",
        )

        chunks = [
            chunk
            async for chunk in agent.run(
                "等待后请求登录",
                is_stream=False,
                task_id="task-3",
                session_id="session-3",
                thread_id=f"chat-{uuid.uuid4()}",
                sse_connection=asyncio.Event(),
                phone_width=1080,
                phone_height=2278,
            )
        ]
        custom_output = "\n".join(
            chunk[1]
            for chunk in chunks
            if isinstance(chunk, tuple)
            and chunk[0] == "custom"
            and isinstance(chunk[1], str)
        )

        self.assertEqual(len(backend.executed), 1)
        self.assertEqual(backend.executed[0][0], WaitAction(duration_ms=1))
        self.assertIn('"tool_name": "wait"', custom_output)
        self.assertIn('"type": "user_interrupt"', custom_output)
        self.assertIn('"content": "请登录"', custom_output)

    async def test_repeated_oracle_failure_stops_after_two_checks(self):
        backend = RejectingCompletionBackend()
        provider = RepeatedFinishProvider()
        agent = MobileUseAgent(
            model_provider_name="kimi",
            device_provider_name="adb",
            model_provider_factory=lambda *args, **kwargs: provider,
            device_backend_factory=lambda name: backend,
        )
        agent.step_interval = 0
        await agent.initialize("", "", "", "", "", "")

        chunks = [
            chunk
            async for chunk in agent.run(
                "打开高德地图",
                is_stream=False,
                task_id="task-oracle-failure",
                session_id="session-oracle-failure",
                thread_id=f"chat-{uuid.uuid4()}",
                sse_connection=asyncio.Event(),
                phone_width=1080,
                phone_height=2278,
            )
        ]
        custom_output = "\n".join(
            chunk[1]
            for chunk in chunks
            if isinstance(chunk, tuple)
            and chunk[0] == "custom"
            and isinstance(chunk[1], str)
        )

        self.assertEqual(provider.calls, 2)
        self.assertEqual(backend.oracle_calls, 2)
        self.assertIn("ADB 独立 Oracle 连续两次未满足完成条件", custom_output)


if __name__ == "__main__":
    unittest.main()
