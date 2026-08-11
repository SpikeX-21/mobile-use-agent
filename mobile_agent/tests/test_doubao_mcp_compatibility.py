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

import unittest

from mobile_agent.agent.actions import (
    BackAction,
    ClearTextAction,
    CloseAppAction,
    FailAction,
    FinishAction,
    HomeAction,
    LaunchAppAction,
    ListAppsAction,
    MenuAction,
    SwipeAction,
    TapAction,
    TextInputAction,
    WaitAction,
)
from mobile_agent.agent.actions.mcp_adapter import (
    canonical_action_to_mcp_tool_call,
)
from mobile_agent.agent.llm.provider import ActionParseError, DoubaoModelProvider
from mobile_agent.agent.mobile.backend import McpDeviceBackend
from mobile_agent.agent.mobile.result import (
    ActionResult,
    ActionResultStatus,
    DeviceBackendError,
    DeviceErrorKind,
)


class RecordingTools:
    def __init__(self):
        self.calls = []

    async def exec(self, tool_call):
        self.calls.append(tool_call)
        return "ok"


class DoubaoMcpCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = DoubaoModelProvider(
            thread_id="thread-1", is_stream=False, llm=object()
        )

    async def test_click_flows_from_doubao_text_to_normalized_action_to_mcp(self):
        action = self.provider.parse_action(
            "click(start_box='<bbox>400 300 600 700</bbox>')"
        )
        tools = RecordingTools()
        backend = McpDeviceBackend(tools=tools)

        result = await backend.execute(action, screenshot_dimensions=(1080, 2278))

        self.assertEqual(action, TapAction(x=500, y=500))
        self.assertEqual(result, ActionResult.success("ok"))
        self.assertEqual(
            tools.calls,
            [
                {
                    "name": "mobile:tap",
                    "arguments": {"x": 540, "y": 1139},
                }
            ],
        )

    async def test_side_effect_timeouts_are_ambiguous_and_never_auto_replayed(self):
        class TimingOutTools:
            def __init__(self):
                self.calls = 0

            async def exec(self, tool_call):
                self.calls += 1
                raise TimeoutError("lost response")

        side_effects = [
            TapAction(x=500, y=500),
            SwipeAction(start_x=100, start_y=100, end_x=900, end_y=900),
            TextInputAction(text="上海外滩"),
            ClearTextAction(),
            HomeAction(),
            BackAction(),
            MenuAction(),
            LaunchAppAction(package_name="com.autonavi.minimap"),
            CloseAppAction(package_name="com.autonavi.minimap"),
        ]

        for action in side_effects:
            with self.subTest(action=action.type):
                tools = TimingOutTools()
                result = await McpDeviceBackend(tools=tools).execute(
                    action, screenshot_dimensions=(1080, 2278)
                )
                self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
                self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
                self.assertEqual(tools.calls, 1)

    async def test_list_apps_timeout_has_one_bounded_retry_and_is_not_ambiguous(self):
        class TimingOutTools:
            def __init__(self):
                self.calls = 0

            async def exec(self, tool_call):
                self.calls += 1
                raise TimeoutError("read timeout")

        tools = TimingOutTools()

        result = await McpDeviceBackend(tools=tools).execute(
            ListAppsAction(), screenshot_dimensions=(1080, 2278)
        )

        self.assertEqual(result.status, ActionResultStatus.FAILED)
        self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(tools.calls, 2)

    async def test_mcp_screenshot_has_one_bounded_retry_and_classified_failure(self):
        class OfflineMobile:
            def __init__(self):
                self.calls = 0

            async def take_screenshot(self):
                self.calls += 1
                raise RuntimeError("device offline")

        mobile = OfflineMobile()
        backend = McpDeviceBackend(tools=object(), mobile=mobile)

        with self.assertRaises(DeviceBackendError) as raised:
            await backend.take_screenshot()

        self.assertEqual(mobile.calls, 2)
        self.assertEqual(raised.exception.kind, DeviceErrorKind.OFFLINE)

    async def test_mcp_screenshot_timeout_preserves_timeout_classification(self):
        class TimingOutMobile:
            def __init__(self):
                self.calls = 0

            async def take_screenshot(self):
                self.calls += 1
                raise TimeoutError("screenshot timed out")

        mobile = TimingOutMobile()
        backend = McpDeviceBackend(tools=object(), mobile=mobile)

        with self.assertRaises(DeviceBackendError) as raised:
            await backend.take_screenshot()

        self.assertEqual(mobile.calls, 2)
        self.assertEqual(raised.exception.kind, DeviceErrorKind.TIMEOUT)

    async def test_typed_mcp_deadline_error_is_ambiguous_for_side_effect(self):
        class DeadlineTools:
            def __init__(self):
                self.calls = 0

            async def exec(self, tool_call):
                self.calls += 1
                raise DeviceBackendError(
                    "rpc error: code = DeadlineExceeded",
                    kind=DeviceErrorKind.TIMEOUT,
                )

        tools = DeadlineTools()

        result = await McpDeviceBackend(tools=tools).execute(
            TapAction(x=500, y=500), screenshot_dimensions=(1080, 2278)
        )

        self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
        self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(tools.calls, 1)

    def test_terminal_doubao_actions_use_canonical_vocabulary(self):
        self.assertEqual(
            self.provider.parse_action("finished(content='完成')"),
            FinishAction(summary="完成"),
        )
        self.assertEqual(
            self.provider.parse_action("call_user(content='请登录')"),
            FailAction(reason="请登录"),
        )

    def test_every_canonical_action_has_a_focused_mcp_mapping(self):
        examples = [
            (
                SwipeAction(
                    start_x=100,
                    start_y=200,
                    end_x=300,
                    end_y=400,
                    duration_ms=500,
                ),
                {
                    "name": "mobile:swipe",
                    "arguments": {
                        "from_x": 100,
                        "from_y": 400,
                        "to_x": 300,
                        "to_y": 800,
                    },
                },
            ),
            (
                TextInputAction(text="上海外滩"),
                {"name": "mobile:text_input", "arguments": {"text": "上海外滩"}},
            ),
            (ClearTextAction(), {"name": "mobile:clear_text", "arguments": {}}),
            (HomeAction(), {"name": "mobile:home", "arguments": {}}),
            (BackAction(), {"name": "mobile:back", "arguments": {}}),
            (MenuAction(), {"name": "mobile:menu", "arguments": {}}),
            (
                LaunchAppAction(package_name="com.autonavi.minimap"),
                {
                    "name": "mobile:launch_app",
                    "arguments": {"package_name": "com.autonavi.minimap"},
                },
            ),
            (
                CloseAppAction(package_name="com.autonavi.minimap"),
                {
                    "name": "mobile:close_app",
                    "arguments": {"package_name": "com.autonavi.minimap"},
                },
            ),
            (ListAppsAction(), {"name": "mobile:list_apps", "arguments": {}}),
            (WaitAction(duration_ms=1500), {"name": "wait", "arguments": {"t": 1.5}}),
            (
                FinishAction(summary="完成"),
                {"name": "finished", "arguments": {"content": "完成"}},
            ),
            (
                FailAction(reason="请登录"),
                {"name": "call_user", "arguments": {"content": "请登录"}},
            ),
        ]

        for action, expected in examples:
            with self.subTest(action=action.type):
                self.assertEqual(
                    canonical_action_to_mcp_tool_call(action, (1000, 2000)),
                    expected,
                )

    def test_invalid_doubao_output_is_rejected_before_device_execution(self):
        invalid_outputs = ["not a valid action", "launch_app()"]
        for output in invalid_outputs:
            with self.subTest(output=output):
                with self.assertRaises(ActionParseError):
                    self.provider.parse_action(output)


if __name__ == "__main__":
    unittest.main()
