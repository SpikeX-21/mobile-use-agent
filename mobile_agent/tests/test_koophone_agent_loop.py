# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
import base64
import io
import json
import unittest
import uuid
from types import SimpleNamespace

from PIL import Image
from pydantic import SecretStr

from mobile_agent.agent.llm.kimi import KimiModelProvider
from mobile_agent.agent.mobile.koophone import KOOPHONE_REQUIRED_TOOLS, KooPhoneDeviceBackend
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.config.settings import KimiConfig
from tests.test_koophone_auth import koophone_config


def screenshot_response() -> SimpleNamespace:
    output = io.BytesIO()
    Image.new("RGB", (90, 60), "white").save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return SimpleNamespace(content=[SimpleNamespace(text=encoded)])


class StaticAuthenticator:
    async def create_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer test-jwt",
            "x-auth-token": "test-iam-token",
        }


class KooPhoneLoopTransport:
    def __init__(self):
        self.tool_calls = []

    async def connect(self, headers):
        return set(KOOPHONE_REQUIRED_TOOLS)

    async def close(self):
        return None

    async def call_tool(self, name, arguments):
        self.tool_calls.append((name, arguments))
        if name == "get_screenshot":
            return screenshot_response()
        return "ok"


class KimiCompletions:
    def __init__(self, responses=None):
        self.requests = []
        self.responses = responses or [
            {"summary": "视觉定位后轻触", "action": {"type": "tap", "x": 500, "y": 500}},
            {"summary": "安全点击完成", "action": {"type": "finish", "summary": "已完成视觉点击"}},
        ]

    async def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(
            id=f"kimi-{len(self.requests)}",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.responses.pop(0), ensure_ascii=False)
                    )
                )
            ],
        )


class KooPhoneAgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_agent_seam_sends_koophone_screenshot_to_kimi_then_taps(self):
        transport = KooPhoneLoopTransport()
        backend = KooPhoneDeviceBackend(
            koophone_config(),
            authenticator=StaticAuthenticator(),
            transport=transport,
        )
        completions = KimiCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        def model_factory(name, *, thread_id, is_stream):
            return KimiModelProvider(
                thread_id=thread_id,
                config=KimiConfig(api_key=SecretStr("unit-test-key")),
                client=client,
            )

        agent = MobileUseAgent(
            model_provider_name="kimi",
            device_provider_name="koophone_mcp",
            model_provider_factory=model_factory,
            device_backend_factory=lambda name: backend,
        )
        agent.step_interval = 0
        await agent.initialize("", "", "", "", "", "")

        chunks = [
            chunk
            async for chunk in agent.run(
                "请识别当前界面并执行一次安全点击",
                is_stream=False,
                task_id="task-koophone-vision",
                session_id="session-koophone-vision",
                thread_id=f"chat-{uuid.uuid4()}",
                sse_connection=asyncio.Event(),
                phone_width=90,
                phone_height=60,
            )
        ]
        custom_output = "\n".join(
            chunk[1]
            for chunk in chunks
            if isinstance(chunk, tuple) and chunk[0] == "custom" and isinstance(chunk[1], str)
        )

        first_request = completions.requests[0]
        image_url = first_request["messages"][-1]["content"][0]["image_url"]["url"]
        self.assertTrue(image_url.startswith("data:image/png;base64,"))
        self.assertEqual(first_request["extra_body"]["thinking"]["type"], "disabled")
        self.assertEqual(
            transport.tool_calls,
            [
                ("get_screenshot", {"instanceId": "instance-test-1"}),
                ("tap", {"instanceId": "instance-test-1", "x": 45, "y": 30}),
                ("get_screenshot", {"instanceId": "instance-test-1"}),
            ],
        )
        self.assertIn('"tool_name": "tap"', custom_output)
        self.assertIn("已完成视觉点击", custom_output)

    async def test_simulated_alarm_states_follow_idempotent_action_paths(self):
        cases = {
            "enabled": [
                {"summary": "打开闹钟", "action": {"type": "launch_app", "package_name": "com.android.deskclock"}},
                {"summary": "09:00 已启用", "action": {"type": "finish", "summary": "09:00 已启用"}},
            ],
            "disabled": [
                {"summary": "打开闹钟", "action": {"type": "launch_app", "package_name": "com.android.deskclock"}},
                {"summary": "启用已有闹钟", "action": {"type": "tap", "x": 900, "y": 500}},
                {"summary": "确认启用", "action": {"type": "finish", "summary": "09:00 已启用"}},
            ],
            "missing": [
                {"summary": "打开闹钟", "action": {"type": "launch_app", "package_name": "com.android.deskclock"}},
                {"summary": "新建闹钟", "action": {"type": "tap", "x": 900, "y": 900}},
                {"summary": "设置九点", "action": {"type": "tap", "x": 500, "y": 500}},
                {"summary": "保存默认配置", "action": {"type": "tap", "x": 800, "y": 900}},
                {"summary": "确认新闹钟", "action": {"type": "finish", "summary": "09:00 已启用"}},
            ],
        }
        expected_tools = {
            "enabled": ["start_app"],
            "disabled": ["start_app", "tap"],
            "missing": ["start_app", "tap", "tap", "tap"],
        }

        for state, responses in cases.items():
            with self.subTest(state=state):
                transport = KooPhoneLoopTransport()
                backend = KooPhoneDeviceBackend(
                    koophone_config(), authenticator=StaticAuthenticator(), transport=transport
                )
                completions = KimiCompletions(responses=list(responses))
                client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

                def model_factory(name, *, thread_id, is_stream):
                    return KimiModelProvider(
                        thread_id=thread_id,
                        config=KimiConfig(api_key=SecretStr("unit-test-key")),
                        client=client,
                    )

                agent = MobileUseAgent(
                    model_provider_name="kimi",
                    device_provider_name="koophone_mcp",
                    model_provider_factory=model_factory,
                    device_backend_factory=lambda name: backend,
                )
                agent.step_interval = 0
                await agent.initialize("", "", "", "", "", "")
                async for _ in agent.run(
                    "确保存在已启用的 09:00 闹钟",
                    is_stream=False,
                    task_id=f"alarm-{state}",
                    session_id="alarm-test",
                    thread_id=f"alarm-{state}-{uuid.uuid4()}",
                    sse_connection=asyncio.Event(),
                    phone_width=90,
                    phone_height=60,
                ):
                    pass

                self.assertEqual([name for name, _ in transport.tool_calls if name != "get_screenshot"], expected_tools[state])


if __name__ == "__main__":
    unittest.main()
