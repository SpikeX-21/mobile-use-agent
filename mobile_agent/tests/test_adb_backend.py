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

from mobile_agent.agent.actions import FinishAction, TapAction, WaitAction
from mobile_agent.agent.mobile.adb import (
    AdbCommandError,
    AdbCommandResult,
    AdbDeviceBackend,
    AdbForegroundAppOracle,
    SubprocessAdbRunner,
)
from mobile_agent.agent.mobile.result import ActionResultStatus, DeviceErrorKind
from mobile_agent.config.settings import AdbConfig


def png_bytes(width: int = 1080, height: int = 2400) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


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
            [AdbCommandResult(stdout=b"mCurrentFocus=com.android.launcher3/.Home")]
        )
        backend = AdbDeviceBackend(self.make_config(), runner=runner)

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
