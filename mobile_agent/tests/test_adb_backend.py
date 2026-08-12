# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
import base64
import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image
from pydantic import SecretStr

from mobile_agent.agent.actions import (
    BackAction,
    ClearTextAction,
    CloseAppAction,
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
from mobile_agent.agent.mobile.adb import (
    AdbCommandError,
    AdbCommandResult,
    AdbDeviceBackend,
    AdbForegroundAppOracle,
    AdbTaskOracle,
    SubprocessAdbRunner,
)
from mobile_agent.agent.mobile.result import ActionResultStatus, DeviceErrorKind
from mobile_agent.config.settings import AdbConfig


def png_bytes(width: int = 1080, height: int = 2400) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def remaining_adb_actions():
    return (
        HomeAction(),
        BackAction(),
        MenuAction(),
        LaunchAppAction(package_name="com.autonavi.minimap"),
        CloseAppAction(package_name="com.autonavi.minimap"),
        ListAppsAction(),
    )


class RecordingRunner:
    def __init__(self, responses: list[AdbCommandResult]):
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    async def run(self, *arguments: str) -> AdbCommandResult:
        self.calls.append(arguments)
        return self.responses.pop(0)


class AdbDeviceBackendTests(unittest.IsolatedAsyncioTestCase):
    def make_config(self) -> AdbConfig:
        return AdbConfig(serial="device-1", command_timeout=3.0)

    async def test_screenshot_is_validated_and_returned_as_base64_data_url(self):
        raw_png = png_bytes()
        runner = RecordingRunner([AdbCommandResult(stdout=raw_png)])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.take_screenshot()

        self.assertEqual(result["screenshot_dimensions"], (1080, 2400))
        encoded = result["screenshot"].removeprefix("data:image/png;base64,")
        self.assertEqual(base64.b64decode(encoded), raw_png)
        self.assertEqual(
            runner.calls,
            [("-s", "device-1", "exec-out", "screencap", "-p")],
        )

    async def test_invalid_screenshot_bytes_are_rejected(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(stdout=b"not-an-image"),
                AdbCommandResult(stdout=b"still-not-an-image"),
            ]
        )
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        with self.assertRaisesRegex(AdbCommandError, "valid image"):
            await backend.take_screenshot()

    async def test_screenshot_retries_once_then_returns_valid_observation(self):
        class FlakyObservationRunner:
            def __init__(self):
                self.calls = 0

            async def run(self, *arguments):
                self.calls += 1
                if self.calls == 1:
                    raise AdbCommandError(
                        "transient timeout", kind=DeviceErrorKind.TIMEOUT
                    )
                return AdbCommandResult(stdout=png_bytes())

        runner = FlakyObservationRunner()
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.take_screenshot()

        self.assertEqual(result["screenshot_dimensions"], (1080, 2400))
        self.assertEqual(runner.calls, 2)

    async def test_screenshot_exhaustion_preserves_final_error_classification(self):
        class OfflineRunner:
            def __init__(self):
                self.calls = 0

            async def run(self, *arguments):
                self.calls += 1
                raise AdbCommandError(
                    "device offline", kind=DeviceErrorKind.OFFLINE
                )

        runner = OfflineRunner()
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        with self.assertRaises(AdbCommandError) as raised:
            await backend.take_screenshot()

        self.assertEqual(raised.exception.kind, DeviceErrorKind.OFFLINE)
        self.assertEqual(runner.calls, 2)

    async def test_tap_converts_normalized_coordinates_and_clips_edges(self):
        runner = RecordingRunner([AdbCommandResult(stdout=b"")])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)
        action = TapAction(x=1000, y=500)

        tool_call = backend.to_tool_call(action, (1080, 2400))
        await backend.execute(action, (1080, 2400))

        self.assertEqual(
            tool_call,
            {"name": "mobile:tap", "arguments": {"x": 1079, "y": 1200}},
        )
        self.assertEqual(
            runner.calls,
            [("-s", "device-1", "shell", "input", "tap", "1079", "1200")],
        )

    async def test_swipe_converts_all_normalized_coordinates_and_duration(self):
        runner = RecordingRunner([AdbCommandResult()])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)
        action = SwipeAction(
            start_x=500,
            start_y=800,
            end_x=500,
            end_y=200,
            duration_ms=450,
        )

        tool_call = backend.to_tool_call(action, (1080, 2400))
        result = await backend.execute(action, (1080, 2400))

        self.assertEqual(result.status, ActionResultStatus.SUCCESS)
        self.assertEqual(
            tool_call,
            {
                "name": "mobile:swipe",
                "arguments": {
                    "from_x": 540,
                    "from_y": 1920,
                    "to_x": 540,
                    "to_y": 480,
                    "duration_ms": 450,
                },
            },
        )
        self.assertEqual(
            runner.calls,
            [
                (
                    "-s",
                    "device-1",
                    "shell",
                    "input",
                    "swipe",
                    "540",
                    "1920",
                    "540",
                    "480",
                    "450",
                )
            ],
        )

    async def test_side_effect_timeout_is_ambiguous_and_is_not_replayed(self):
        class TimingOutRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        runner = TimingOutRunner()
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.execute(TapAction(x=500, y=500), (1080, 2400))

        self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
        self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(len(runner.calls), 1)

    async def test_swipe_timeout_is_ambiguous_and_is_not_replayed(self):
        class TimingOutRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        runner = TimingOutRunner()
        backend = AdbDeviceBackend(self.make_config(), runner=runner)
        action = SwipeAction(
            start_x=500,
            start_y=800,
            end_x=500,
            end_y=200,
            duration_ms=300,
        )

        result = await backend.execute(action, (1080, 2400))

        self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
        self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(len(runner.calls), 1)

    async def test_chinese_text_uses_parameterized_clipboard_and_paste_key(self):
        runner = RecordingRunner([AdbCommandResult(), AdbCommandResult()])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.execute(
            TextInputAction(text="上海外滩"), (1080, 2400)
        )

        self.assertEqual(result.status, ActionResultStatus.SUCCESS)
        self.assertEqual(
            backend.to_tool_call(TextInputAction(text="上海外滩"), (1080, 2400)),
            {"name": "mobile:text_input", "arguments": {"text": "上海外滩"}},
        )
        self.assertEqual(
            runner.calls,
            [
                (
                    "-s",
                    "device-1",
                    "exec-out",
                    "cmd",
                    "clipboard",
                    "set",
                    "上海外滩",
                ),
                ("-s", "device-1", "shell", "input", "keyevent", "KEYCODE_PASTE"),
            ],
        )

    async def test_safe_ascii_text_uses_adb_input_text_fallback(self):
        runner = RecordingRunner([AdbCommandResult()])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.execute(
            TextInputAction(text="Shanghai123"), (1080, 2400)
        )

        self.assertEqual(result.status, ActionResultStatus.SUCCESS)
        self.assertEqual(
            runner.calls,
            [
                (
                    "-s",
                    "device-1",
                    "shell",
                    "input",
                    "text",
                    "Shanghai123",
                )
            ],
        )

    async def test_special_characters_use_exec_out_without_remote_shell(self):
        runner = RecordingRunner([AdbCommandResult(), AdbCommandResult()])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        await backend.execute(TextInputAction(text="a;b"), (1080, 2400))

        self.assertEqual(
            runner.calls,
            [
                (
                    "-s",
                    "device-1",
                    "exec-out",
                    "cmd",
                    "clipboard",
                    "set",
                    "a;b",
                ),
                ("-s", "device-1", "shell", "input", "keyevent", "KEYCODE_PASTE"),
            ],
        )
        self.assertNotIn("shell", runner.calls[0])
        self.assertNotIn("|", runner.calls[0])
        self.assertNotIn("$(", runner.calls[0])

    async def test_clear_text_selects_all_then_deletes(self):
        runner = RecordingRunner([AdbCommandResult(), AdbCommandResult()])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.execute(ClearTextAction(), (1080, 2400))

        self.assertEqual(result.status, ActionResultStatus.SUCCESS)
        self.assertEqual(
            backend.to_tool_call(ClearTextAction(), (1080, 2400)),
            {"name": "mobile:clear_text", "arguments": {}},
        )
        self.assertEqual(
            runner.calls,
            [
                ("-s", "device-1", "shell", "input", "keycombination", "113", "29"),
                ("-s", "device-1", "shell", "input", "keyevent", "KEYCODE_DEL"),
            ],
        )

    async def test_navigation_keys_execute_on_the_configured_device(self):
        examples = (
            (HomeAction(), "KEYCODE_HOME", "mobile:home"),
            (BackAction(), "KEYCODE_BACK", "mobile:back"),
            (MenuAction(), "KEYCODE_MENU", "mobile:menu"),
        )

        for action, keycode, tool_name in examples:
            with self.subTest(action=action.type):
                runner = RecordingRunner([AdbCommandResult()])
                backend = AdbDeviceBackend(self.make_config(), runner=runner)

                result = await backend.execute(action, (1080, 2400))

                self.assertEqual(result.status, ActionResultStatus.SUCCESS)
                self.assertEqual(
                    backend.to_tool_call(action, (1080, 2400)),
                    {"name": tool_name, "arguments": {}},
                )
                self.assertEqual(
                    runner.calls,
                    [
                        (
                            "-s",
                            "device-1",
                            "shell",
                            "input",
                            "keyevent",
                            keycode,
                        )
                    ],
                )

    async def test_app_lifecycle_actions_use_validated_package_arguments(self):
        examples = (
            (
                LaunchAppAction(package_name="com.autonavi.minimap"),
                "mobile:launch_app",
                [
                    AdbCommandResult(
                        stdout=(
                            b"com.autonavi.minimap/"
                            b"com.autonavi.map.activity.SplashActivity\n"
                        )
                    ),
                    AdbCommandResult(),
                ],
                [
                    (
                        "-s",
                        "device-1",
                        "shell",
                        "cmd",
                        "package",
                        "resolve-activity",
                        "--brief",
                        "-a",
                        "android.intent.action.MAIN",
                        "-c",
                        "android.intent.category.LAUNCHER",
                        "com.autonavi.minimap",
                    ),
                    (
                        "-s",
                        "device-1",
                        "shell",
                        "am",
                        "start",
                        "-n",
                        "com.autonavi.minimap/"
                        "com.autonavi.map.activity.SplashActivity",
                    ),
                ],
            ),
            (
                CloseAppAction(package_name="com.autonavi.minimap"),
                "mobile:close_app",
                [AdbCommandResult()],
                [
                    (
                        "-s",
                        "device-1",
                        "shell",
                        "am",
                        "force-stop",
                        "com.autonavi.minimap",
                    )
                ],
            ),
        )

        for action, tool_name, responses, commands in examples:
            with self.subTest(action=action.type):
                runner = RecordingRunner(responses)
                backend = AdbDeviceBackend(self.make_config(), runner=runner)

                result = await backend.execute(action, (1080, 2400))

                self.assertEqual(result.status, ActionResultStatus.SUCCESS)
                self.assertEqual(
                    backend.to_tool_call(action, (1080, 2400)),
                    {
                        "name": tool_name,
                        "arguments": {
                            "package_name": "com.autonavi.minimap"
                        },
                    },
                )
                self.assertEqual(runner.calls, commands)

    async def test_list_apps_returns_sanitized_packages_from_configured_device(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=(
                        b"package:com.example.zeta\n"
                        b"unexpected output\n"
                        b"package:com.autonavi.minimap\n"
                    )
                )
            ]
        )
        backend = AdbDeviceBackend(self.make_config(), runner=runner)
        action = ListAppsAction(ignore_system_apps=True)

        result = await backend.execute(action, (1080, 2400))

        self.assertEqual(result.status, ActionResultStatus.SUCCESS)
        self.assertEqual(
            result.message,
            "Installed packages (2): com.autonavi.minimap, com.example.zeta",
        )
        self.assertEqual(
            backend.to_tool_call(action, (1080, 2400)),
            {
                "name": "mobile:list_apps",
                "arguments": {"ignore_system_apps": True},
            },
        )
        self.assertEqual(
            runner.calls,
            [
                (
                    "-s",
                    "device-1",
                    "shell",
                    "pm",
                    "list",
                    "packages",
                    "-3",
                )
            ],
        )

    async def test_remaining_actions_classify_nonzero_command_failures(self):
        class NonZeroRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "ADB command failed: exit 1",
                    kind=DeviceErrorKind.COMMAND_FAILED,
                )

        for action in remaining_adb_actions():
            with self.subTest(action=action.type):
                runner = NonZeroRunner()
                backend = AdbDeviceBackend(self.make_config(), runner=runner)

                result = await backend.execute(action, (1080, 2400))

                self.assertEqual(result.status, ActionResultStatus.FAILED)
                self.assertEqual(
                    result.error_kind, DeviceErrorKind.COMMAND_FAILED
                )
                self.assertEqual(len(runner.calls), 1)

    async def test_remaining_actions_classify_device_offline_without_retry(self):
        class OfflineRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "device offline", kind=DeviceErrorKind.OFFLINE
                )

        for action in remaining_adb_actions():
            with self.subTest(action=action.type):
                runner = OfflineRunner()
                backend = AdbDeviceBackend(self.make_config(), runner=runner)

                result = await backend.execute(action, (1080, 2400))

                self.assertEqual(result.status, ActionResultStatus.FAILED)
                self.assertEqual(result.error_kind, DeviceErrorKind.OFFLINE)
                self.assertEqual(len(runner.calls), 1)

    async def test_remaining_side_effect_timeouts_are_ambiguous_without_retry(self):
        side_effect_actions = tuple(
            action
            for action in remaining_adb_actions()[:-1]
            if not isinstance(action, LaunchAppAction)
        )

        class TimingOutRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        for action in side_effect_actions:
            with self.subTest(action=action.type):
                runner = TimingOutRunner()
                backend = AdbDeviceBackend(self.make_config(), runner=runner)

                result = await backend.execute(action, (1080, 2400))

                self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
                self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
                self.assertEqual(len(runner.calls), 1)

    async def test_launch_resolution_timeout_is_failed_before_dispatch(self):
        class ResolutionTimeoutRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        runner = ResolutionTimeoutRunner()
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.execute(
            LaunchAppAction(package_name="com.autonavi.minimap"),
            (1080, 2400),
        )

        self.assertEqual(result.status, ActionResultStatus.FAILED)
        self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(len(runner.calls), 1)

    async def test_launch_dispatch_timeout_is_ambiguous_without_retry(self):
        class DispatchTimeoutRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                if len(self.calls) == 1:
                    return AdbCommandResult(
                        stdout=(
                            b"com.autonavi.minimap/"
                            b"com.autonavi.map.activity.SplashActivity\n"
                        )
                    )
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        runner = DispatchTimeoutRunner()
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        result = await backend.execute(
            LaunchAppAction(package_name="com.autonavi.minimap"),
            (1080, 2400),
        )

        self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
        self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(len(runner.calls), 2)

    async def test_list_apps_timeout_has_one_bounded_retry(self):
        class FlakyListRunner:
            def __init__(self, always_timeout=False):
                self.always_timeout = always_timeout
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                if self.always_timeout or len(self.calls) == 1:
                    raise AdbCommandError(
                        "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                    )
                return AdbCommandResult(stdout=b"package:com.example.app\n")

        recovering_runner = FlakyListRunner()
        recovering_backend = AdbDeviceBackend(
            self.make_config(), runner=recovering_runner
        )

        recovered = await recovering_backend.execute(
            ListAppsAction(), (1080, 2400)
        )

        self.assertEqual(recovered.status, ActionResultStatus.SUCCESS)
        self.assertEqual(len(recovering_runner.calls), 2)

        failing_runner = FlakyListRunner(always_timeout=True)
        failing_backend = AdbDeviceBackend(
            self.make_config(), runner=failing_runner
        )

        failed = await failing_backend.execute(ListAppsAction(), (1080, 2400))

        self.assertEqual(failed.status, ActionResultStatus.FAILED)
        self.assertEqual(failed.error_kind, DeviceErrorKind.TIMEOUT)
        self.assertEqual(len(failing_runner.calls), 2)

    async def test_wait_is_executed_by_adb_backend_without_an_adb_command(self):
        runner = RecordingRunner([])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        with patch(
            "mobile_agent.agent.mobile.adb.asyncio.sleep", AsyncMock()
        ) as sleep:
            result = await backend.execute(WaitAction(duration_ms=750), (1080, 2400))

        self.assertEqual(result.status, ActionResultStatus.SUCCESS)
        sleep.assert_awaited_once_with(0.75)
        self.assertEqual(runner.calls, [])

    async def test_text_and_clear_timeouts_are_ambiguous_without_replay(self):
        class TimingOutRunner:
            def __init__(self):
                self.calls = []

            async def run(self, *arguments):
                self.calls.append(arguments)
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        for action in (TextInputAction(text="safe123"), ClearTextAction()):
            with self.subTest(action=action.type):
                runner = TimingOutRunner()
                backend = AdbDeviceBackend(self.make_config(), runner=runner)

                result = await backend.execute(action, (1080, 2400))

                self.assertEqual(result.status, ActionResultStatus.AMBIGUOUS)
                self.assertEqual(result.error_kind, DeviceErrorKind.TIMEOUT)
                self.assertEqual(len(runner.calls), 1)

    async def test_foreground_oracle_uses_adb_state_not_model_output(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                )
            ]
        )
        oracle = AdbForegroundAppOracle(self.make_config(), runner=runner)

        self.assertTrue(await oracle.is_foreground("com.autonavi.minimap"))
        self.assertEqual(
            runner.calls,
            [("-s", "device-1", "shell", "dumpsys", "window")],
        )

    async def test_foreground_oracle_does_not_accept_package_prefixes(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap.fake/.MapActivity}"
                )
            ]
        )
        oracle = AdbForegroundAppOracle(self.make_config(), runner=runner)

        self.assertFalse(await oracle.is_foreground("com.autonavi.minimap"))

    async def test_task_baseline_force_stops_map_and_returns_home_without_clearing_data(self):
        runner = RecordingRunner([AdbCommandResult(), AdbCommandResult()])
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        await backend.prepare_task("打开高德地图并搜索上海外滩")

        self.assertEqual(
            runner.calls,
            [
                (
                    "-s",
                    "device-1",
                    "shell",
                    "am",
                    "force-stop",
                    "com.autonavi.minimap",
                ),
                (
                    "-s",
                    "device-1",
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_HOME",
                ),
            ],
        )
        self.assertNotIn("pm", (argument for call in runner.calls for argument in call))

    async def test_search_oracle_requires_foreground_package_and_visible_query_text(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<?xml version='1.0' encoding='UTF-8'?>"
                        '<hierarchy><node text="上海外滩" content-desc="" />'
                        "</hierarchy>UI hierchary dumped to: /dev/tty"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertTrue(await oracle.is_complete(required_text="上海外滩"))
        self.assertEqual(
            runner.calls[-1],
            (
                "-s",
                "device-1",
                "exec-out",
                "uiautomator",
                "dump",
                "--compressed",
                "/dev/tty",
            ),
        )

    async def test_search_oracle_rejects_foreground_app_without_visible_query_text(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=b"<hierarchy><node text='nearby' /></hierarchy>"
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertFalse(await oracle.is_complete(required_text="上海外滩"))

    async def test_search_oracle_rejects_target_text_marked_not_visible(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy><node text='上海外滩' "
                        "visible-to-user='false' /></hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertFalse(await oracle.is_complete(required_text="上海外滩"))

    async def test_detail_oracle_requires_target_and_stable_detail_controls(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy>"
                        "<node class='android.view.ViewGroup' content-desc='外滩' "
                        "clickable='true' long-clickable='true' />"
                        "<node content-desc='收藏按钮未收藏' />"
                        "<node text='导航' />"
                        "<node text='路线' />"
                        "</hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertTrue(
            await oracle.is_complete(required_text="外滩", detail_page=True)
        )

    async def test_detail_oracle_accepts_compressed_real_device_evidence(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy>"
                        "<node class='android.view.ViewGroup' content-desc='外滩' "
                        "clickable='true' long-clickable='true' />"
                        "<node class='android.view.ViewGroup' "
                        "content-desc='收藏按钮未收藏' clickable='true' />"
                        "</hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertTrue(
            await oracle.is_complete(required_text="外滩", detail_page=True)
        )

    async def test_detail_oracle_rejects_search_result_list(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy>"
                        "<node content-desc='外滩' clickable='true' />"
                        "<node content-desc='路线' clickable='true' />"
                        "</hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertFalse(
            await oracle.is_complete(required_text="外滩", detail_page=True)
        )

    async def test_detail_oracle_rejects_wrong_poi_with_stale_search_text(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy>"
                        "<node content-desc='搜索框，外滩' />"
                        "<node content-desc='外滩观景平台' />"
                        "<node content-desc='收藏按钮未收藏' />"
                        "<node text='导航' /><node text='路线' />"
                        "</hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertFalse(
            await oracle.is_complete(required_text="外滩", detail_page=True)
        )

    async def test_detail_oracle_rejects_exact_target_text_in_search_box(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy>"
                        "<node class='android.view.View' text='外滩' "
                        "content-desc='搜索框，外滩' clickable='true' />"
                        "<node class='android.view.ViewGroup' "
                        "content-desc='外滩观景平台' clickable='true' "
                        "long-clickable='true' />"
                        "<node content-desc='收藏按钮未收藏' />"
                        "<node text='导航' /><node text='路线' />"
                        "</hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        oracle = AdbTaskOracle(self.make_config(), runner=runner)

        self.assertFalse(
            await oracle.is_complete(required_text="外滩", detail_page=True)
        )

    def test_control_actions_can_pass_through_agent_validation(self):
        backend = AdbDeviceBackend(self.make_config(), runner=RecordingRunner([]))

        self.assertEqual(
            backend.to_tool_call(FinishAction(summary="done"), (1080, 2400))["name"],
            "finished",
        )
        self.assertEqual(
            backend.to_tool_call(WaitAction(duration_ms=500), (1080, 2400)),
            {"name": "wait", "arguments": {"t": 0.5}},
        )

    async def test_finish_is_accepted_only_when_oracle_package_is_foreground(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(),
                AdbCommandResult(),
                AdbCommandResult(stdout=b"mCurrentFocus=com.android.launcher3/.Home"),
            ]
        )
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        await backend.prepare_task("打开高德地图")
        self.assertFalse(
            await backend.verify_completion(FinishAction(summary="done"))
        )

    async def test_search_finish_requires_visible_target_text(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(),
                AdbCommandResult(),
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=b"<hierarchy><node text='other' /></hierarchy>"
                ),
            ]
        )
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

        await backend.prepare_task("打开高德地图并搜索上海外滩")
        self.assertFalse(
            await backend.verify_completion(FinishAction(summary="done"))
        )

    async def test_first_result_finish_requires_detail_page_evidence(self):
        runner = RecordingRunner(
            [
                AdbCommandResult(),
                AdbCommandResult(),
                AdbCommandResult(
                    stdout=b"mCurrentFocus=Window{1 u0 com.autonavi.minimap/.MapActivity}"
                ),
                AdbCommandResult(
                    stdout=(
                        "<hierarchy>"
                        "<node class='android.view.ViewGroup' content-desc='外滩' "
                        "clickable='true' long-clickable='true' />"
                        "<node content-desc='收藏按钮未收藏' />"
                        "<node text='导航' />"
                        "<node text='路线' />"
                        "</hierarchy>"
                    ).encode("utf-8")
                ),
            ]
        )
        backend = AdbDeviceBackend(self.make_config(), runner=runner)
        await backend.prepare_task("搜索上海外滩并打开第一个搜索结果")

        self.assertTrue(
            await backend.verify_completion(FinishAction(summary="done"))
        )
        self.assertIsNotNone(backend.last_completion_evidence)
        self.assertTrue(
            backend.last_completion_evidence.foreground_package_match
        )
        self.assertTrue(backend.last_completion_evidence.detail_title_visible)
        self.assertTrue(
            backend.last_completion_evidence.favorite_control_visible
        )

    async def test_first_result_synonyms_cannot_downgrade_detail_oracle(self):
        for phrase in ("首个搜索结果", "第一条结果"):
            with self.subTest(phrase=phrase):
                runner = RecordingRunner(
                    [
                        AdbCommandResult(),
                        AdbCommandResult(),
                        AdbCommandResult(
                            stdout=(
                                b"mCurrentFocus=Window{1 u0 "
                                b"com.autonavi.minimap/.MapActivity}"
                            )
                        ),
                        AdbCommandResult(
                            stdout=(
                                "<hierarchy><node text='上海外滩' />"
                                "<node content-desc='路线' /></hierarchy>"
                            ).encode("utf-8")
                        ),
                    ]
                )
                backend = AdbDeviceBackend(self.make_config(), runner=runner)
                await backend.prepare_task(f"搜索上海外滩并打开{phrase}")

                self.assertFalse(
                    await backend.verify_completion(FinishAction(summary="done"))
                )

    async def test_completion_oracle_command_error_becomes_bounded_rejection(self):
        class FailingOracleRunner:
            async def run(self, *arguments):
                raise AdbCommandError(
                    "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
                )

        backend = AdbDeviceBackend(
            self.make_config(), runner=FailingOracleRunner()
        )

        self.assertFalse(
            await backend.verify_completion(FinishAction(summary="done"))
        )

    async def test_subprocess_runner_uses_argument_array_and_scoped_key_env(self):
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"device\n", b"")),
            returncode=0,
        )
        create_process = AsyncMock(return_value=process)
        config = AdbConfig(
            serial="device-1",
            vendor_keys=SecretStr("/tmp/fake-adb-key"),
        )

        with patch.dict(os.environ, {"KIMI_API_KEY": "must-not-propagate"}), patch(
            "mobile_agent.agent.mobile.adb.asyncio.create_subprocess_exec",
            create_process,
        ):
            await SubprocessAdbRunner(config).run("-s", "device-1", "get-state")

        arguments = create_process.await_args.args
        keyword_arguments = create_process.await_args.kwargs
        self.assertEqual(arguments, ("adb", "-s", "device-1", "get-state"))
        self.assertEqual(
            keyword_arguments["env"]["ADB_VENDOR_KEYS"], "/tmp/fake-adb-key"
        )
        self.assertNotIn("KIMI_API_KEY", keyword_arguments["env"])
        self.assertEqual(keyword_arguments["env"].get("HOME"), os.environ.get("HOME"))

    async def test_subprocess_runner_reports_stdout_when_failed_command_has_no_stderr(self):
        process = SimpleNamespace(
            communicate=AsyncMock(return_value=(b"remote command rejected\n", b"")),
            returncode=1,
        )
        with patch(
            "mobile_agent.agent.mobile.adb.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            with self.assertRaisesRegex(AdbCommandError, "remote command rejected"):
                await SubprocessAdbRunner(self.make_config()).run("shell", "bad")

    async def test_cancelling_runner_reaps_child_process(self):
        never_finishes = asyncio.Event()

        async def communicate():
            await never_finishes.wait()

        process = SimpleNamespace(
            communicate=communicate,
            returncode=None,
            kill=Mock(),
            wait=AsyncMock(return_value=0),
        )
        with patch(
            "mobile_agent.agent.mobile.adb.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ):
            task = asyncio.create_task(
                SubprocessAdbRunner(self.make_config()).run("get-state")
            )
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        process.kill.assert_called_once_with()
        process.wait.assert_awaited_once_with()

    async def test_timeout_tolerates_process_exit_during_cleanup(self):
        process = SimpleNamespace(
            communicate=Mock(return_value=object()),
            returncode=None,
            kill=Mock(side_effect=ProcessLookupError),
            wait=AsyncMock(return_value=0),
        )
        with patch(
            "mobile_agent.agent.mobile.adb.asyncio.create_subprocess_exec",
            AsyncMock(return_value=process),
        ), patch(
            "mobile_agent.agent.mobile.adb.asyncio.wait_for",
            AsyncMock(side_effect=TimeoutError),
        ):
            with self.assertRaisesRegex(AdbCommandError, "timed out"):
                await SubprocessAdbRunner(self.make_config()).run("get-state")

        process.kill.assert_called_once_with()
        process.wait.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
