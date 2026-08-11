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


def screenshot_bytes(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (1080, 2278), color).save(output, format="PNG")
    return output.getvalue()


def first_result_search_actions():
    return [
        {"summary": "打开高德", "action": {"type": "tap", "x": 500, "y": 450}},
        {"summary": "点搜索框", "action": {"type": "tap", "x": 500, "y": 650}},
        {
            "summary": "输入目标",
            "action": {"type": "text_input", "text": "上海外滩"},
        },
        {"summary": "提交搜索", "action": {"type": "tap", "x": 900, "y": 80}},
    ]


def latest_screenshot_url(request):
    return request["messages"][-1]["content"][0]["image_url"]["url"]


class SequenceRunner:
    def __init__(self):
        image = screenshot_bytes()
        self.responses = [
            AdbCommandResult(stdout=b"device\n"),
            AdbCommandResult(),
            AdbCommandResult(),
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


class SearchScenarioRunner:
    def __init__(self):
        self.image = screenshot_bytes()
        self.calls = []

    async def run(self, *arguments):
        self.calls.append(arguments)
        if arguments[-1] == "get-state":
            return AdbCommandResult(stdout=b"device\n")
        if arguments[-3:] == ("exec-out", "screencap", "-p"):
            return AdbCommandResult(stdout=self.image)
        if arguments[-2:] == ("dumpsys", "window"):
            return AdbCommandResult(
                stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
            )
        if arguments[-4:] == ("uiautomator", "dump", "--compressed", "/dev/tty"):
            return AdbCommandResult(
                stdout=(
                    "<hierarchy><node text='上海外滩' content-desc='search result' />"
                    "</hierarchy>"
                ).encode("utf-8")
            )
        return AdbCommandResult()


SEARCH_RESULTS_XML = (
    "<hierarchy><node content-desc='外滩' clickable='true' />"
    "<node content-desc='路线' clickable='true' /></hierarchy>"
)
DETAIL_PAGE_XML = (
    "<hierarchy><node class='android.view.ViewGroup' content-desc='外滩' "
    "clickable='true' long-clickable='true' />"
    "<node content-desc='收藏按钮未收藏' />"
    "<node text='导航' /><node text='路线' /></hierarchy>"
)


class DetailScenarioRunner:
    def __init__(self, oracle_documents: list[str], screenshot_colors: list[str]):
        self.screenshots = [screenshot_bytes(color) for color in screenshot_colors]
        self.oracle_documents = list(oracle_documents)
        self.calls = []

    async def run(self, *arguments):
        self.calls.append(arguments)
        if arguments[-1] == "get-state":
            return AdbCommandResult(stdout=b"device\n")
        if arguments[-3:] == ("exec-out", "screencap", "-p"):
            return AdbCommandResult(stdout=self.screenshots.pop(0))
        if arguments[-2:] == ("dumpsys", "window"):
            return AdbCommandResult(
                stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
            )
        if arguments[-4:] == ("uiautomator", "dump", "--compressed", "/dev/tty"):
            return AdbCommandResult(
                stdout=self.oracle_documents.pop(0).encode("utf-8")
            )
        return AdbCommandResult()


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


class SearchSequenceCompletions(SequenceCompletions):
    def __init__(self):
        self.requests = []
        self.responses = [
            {"summary": "打开高德地图", "action": {"type": "tap", "x": 500, "y": 450}},
            {"summary": "点击搜索框", "action": {"type": "tap", "x": 500, "y": 120}},
            {"summary": "清空搜索框", "action": {"type": "clear_text"}},
            {
                "summary": "输入上海外滩",
                "action": {"type": "text_input", "text": "上海外滩"},
            },
            {"summary": "提交搜索", "action": {"type": "tap", "x": 900, "y": 120}},
            {"summary": "等待结果稳定", "action": {"type": "wait", "duration_ms": 1}},
            {
                "summary": "搜索已完成",
                "action": {"type": "finish", "summary": "已找到上海外滩"},
            },
        ]


class ScriptedCompletions(SequenceCompletions):
    def __init__(self, responses):
        self.requests = []
        self.responses = list(responses)


class KimiAdbAgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def run_detail_scenario(
        self, responses, oracle_documents, screenshot_colors
    ):
        runner = DetailScenarioRunner(oracle_documents, screenshot_colors)
        backend = AdbDeviceBackend(AdbConfig(serial="device-1"), runner=runner)
        completions = ScriptedCompletions(responses)
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
                "打开高德地图，搜索上海外滩并打开第一个搜索结果",
                is_stream=False,
                task_id="task-kimi-first-result",
                session_id="session-kimi-first-result",
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
        return runner, completions, custom_output

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

    async def test_search_task_flows_through_agent_and_independent_oracle(self):
        runner = SearchScenarioRunner()
        backend = AdbDeviceBackend(AdbConfig(serial="device-1"), runner=runner)
        completions = SearchSequenceCompletions()
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
                "打开高德地图并搜索上海外滩",
                is_stream=False,
                task_id="task-kimi-search",
                session_id="session-kimi-search",
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

        self.assertEqual(len(completions.requests), 7)
        self.assertIn('"tool_name": "mobile:clear_text"', custom_output)
        self.assertIn('"tool_name": "mobile:text_input"', custom_output)
        self.assertIn('"tool_name": "wait"', custom_output)
        self.assertIn('"content": "已找到上海外滩"', custom_output)
        self.assertIn(
            (
                "-s",
                "device-1",
                "shell",
                "am",
                "force-stop",
                "com.autonavi.minimap",
            ),
            runner.calls,
        )
        self.assertIn(
            (
                "-s",
                "device-1",
                "exec-out",
                "uiautomator",
                "dump",
                "--compressed",
                "/dev/tty",
            ),
            runner.calls,
        )
        self.assertFalse(
            any("pm" in call and "clear" in call for call in runner.calls)
        )

    async def test_first_visible_search_result_opens_without_swiping(self):
        responses = [
            *first_result_search_actions(),
            {"summary": "打开首项", "action": {"type": "tap", "x": 400, "y": 300}},
            {"summary": "等待详情", "action": {"type": "wait", "duration_ms": 1}},
            {
                "summary": "详情已打开",
                "action": {"type": "finish", "summary": "已打开外滩详情"},
            },
        ]

        runner, completions, custom_output = await self.run_detail_scenario(
            responses,
            [DETAIL_PAGE_XML],
            ["white", "gray", "yellow", "orange", "green", "blue", "purple"],
        )

        self.assertEqual(len(completions.requests), 7)
        self.assertFalse(any("swipe" in call for call in runner.calls))
        self.assertIn('"content": "已打开外滩详情"', custom_output)

    async def test_offscreen_first_result_can_be_revealed_by_swiping(self):
        responses = [
            *first_result_search_actions(),
            {
                "summary": "向上滑动结果列表",
                "action": {
                    "type": "swipe",
                    "start_x": 500,
                    "start_y": 800,
                    "end_x": 500,
                    "end_y": 250,
                    "duration_ms": 400,
                },
            },
            {"summary": "打开首项", "action": {"type": "tap", "x": 400, "y": 350}},
            {"summary": "等待详情", "action": {"type": "wait", "duration_ms": 1}},
            {
                "summary": "详情已打开",
                "action": {"type": "finish", "summary": "已打开外滩详情"},
            },
        ]

        runner, completions, custom_output = await self.run_detail_scenario(
            responses,
            [DETAIL_PAGE_XML],
            [
                "white",
                "gray",
                "yellow",
                "orange",
                "red",
                "green",
                "blue",
                "purple",
            ],
        )

        self.assertEqual(len(completions.requests), 8)
        self.assertIn(
            (
                "-s",
                "device-1",
                "shell",
                "input",
                "swipe",
                "540",
                "1822",
                "540",
                "569",
                "400",
            ),
            runner.calls,
        )
        self.assertIn('"tool_name": "mobile:swipe"', custom_output)
        self.assertNotEqual(
            latest_screenshot_url(completions.requests[4]),
            latest_screenshot_url(completions.requests[5]),
        )

    async def test_detail_loading_delay_is_reobserved_before_finish(self):
        responses = [
            *first_result_search_actions(),
            {"summary": "打开首项", "action": {"type": "tap", "x": 400, "y": 300}},
            {
                "summary": "误以为已完成",
                "action": {"type": "finish", "summary": "详情已打开"},
            },
            {"summary": "等待详情加载", "action": {"type": "wait", "duration_ms": 1}},
            {
                "summary": "详情稳定",
                "action": {"type": "finish", "summary": "已打开外滩详情"},
            },
        ]

        runner, completions, custom_output = await self.run_detail_scenario(
            responses,
            [SEARCH_RESULTS_XML, DETAIL_PAGE_XML],
            ["white", "gray", "yellow", "orange", "green", "blue", "blue", "purple"],
        )

        self.assertEqual(len(completions.requests), 8)
        self.assertEqual(
            sum(
                call[-4:]
                == ("uiautomator", "dump", "--compressed", "/dev/tty")
                for call in runner.calls
            ),
            2,
        )
        self.assertIn('"tool_name": "wait"', custom_output)
        self.assertIn('"content": "已打开外滩详情"', custom_output)

    async def test_ineffective_swipe_is_not_repeated_at_fixed_coordinates(self):
        responses = [
            *first_result_search_actions(),
            {
                "summary": "尝试滑动",
                "action": {
                    "type": "swipe",
                    "start_x": 500,
                    "start_y": 800,
                    "end_x": 500,
                    "end_y": 250,
                    "duration_ms": 400,
                },
            },
            {
                "summary": "列表没有移动",
                "action": {"type": "fail", "reason": "滑动后列表未发生变化"},
            },
        ]

        runner, completions, custom_output = await self.run_detail_scenario(
            responses,
            [],
            ["white", "gray", "yellow", "orange", "red", "red"],
        )

        swipe_calls = [call for call in runner.calls if "swipe" in call]
        self.assertEqual(len(completions.requests), 6)
        self.assertEqual(len(swipe_calls), 1)
        self.assertEqual(
            latest_screenshot_url(completions.requests[4]),
            latest_screenshot_url(completions.requests[5]),
        )
        self.assertIn("滑动后列表未发生变化", custom_output)


if __name__ == "__main__":
    unittest.main()
