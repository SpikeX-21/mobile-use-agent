# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
import io
import json
import unittest
import uuid
from types import SimpleNamespace

from PIL import Image
from pydantic import SecretStr

from mobile_agent.agent.llm.kimi import KimiModelProvider
from mobile_agent.agent.mobile.adb import AdbCommandResult, AdbDeviceBackend
from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.config.settings import AdbConfig, KimiConfig


def screenshot_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1080, 2278), "white").save(output, format="PNG")
    return output.getvalue()


class SequenceRunner:
    def __init__(self):
        image = screenshot_bytes()
        self.responses = [
            AdbCommandResult(stdout=b"device\n"),
            AdbCommandResult(stdout=image),
            AdbCommandResult(stdout=image),
            AdbCommandResult(),
            AdbCommandResult(stdout=image),
            AdbCommandResult(
                stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
            ),
        ]
        self.calls = []

    async def run(self, *arguments):
        self.calls.append(arguments)
        return self.responses.pop(0)


class SequenceCompletions:
    def __init__(self):
        self.requests = []
        self.responses = [
            {"summary": "尝试按包名打开", "action": {"type": "launch_app", "package_name": "com.autonavi.minimap"}},
            {"summary": "视觉定位并点击高德地图", "action": {"type": "tap", "x": 500, "y": 400}},
            {"summary": "高德地图已打开", "action": {"type": "finish", "summary": "高德地图已打开"}},
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


class KimiAdbAgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_visual_tap_flows_through_real_agent_graph(self):
        runner = SequenceRunner()
        backend = AdbDeviceBackend(AdbConfig(serial="device-1"), runner=runner)
        completions = SequenceCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        def model_factory(name, *, thread_id, is_stream):
            return KimiModelProvider(
                thread_id=thread_id,
                config=KimiConfig(api_key=SecretStr("unit-test-key")),
                client=client,
            )

        agent = MobileUseAgent(
            model_provider_name="kimi",
            device_provider_name="adb",
            model_provider_factory=model_factory,
            device_backend_factory=lambda name: backend,
        )
        agent.step_interval = 0
        await agent.initialize("", "", "", "", "", "")

        chunks = [
            chunk
            async for chunk in agent.run(
                "打开高德地图",
                is_stream=True,
                task_id="task-kimi-adb",
                session_id="session-kimi-adb",
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

        self.assertIn(
            ("-s", "device-1", "shell", "input", "tap", "540", "911"),
            runner.calls,
        )
        self.assertIn(
            ("-s", "device-1", "shell", "dumpsys", "window"), runner.calls
        )
        self.assertNotIn("launch_app", custom_output)
        self.assertIn('"tool_name": "mobile:tap"', custom_output)
        self.assertIn('"content": "高德地图已打开"', custom_output)
        first_request = completions.requests[0]
        self.assertTrue(
            first_request["messages"][-1]["content"][0]["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )
        self.assertEqual(first_request["extra_body"]["thinking"]["type"], "disabled")
        self.assertEqual(len(completions.requests), 3)


if __name__ == "__main__":
    unittest.main()
