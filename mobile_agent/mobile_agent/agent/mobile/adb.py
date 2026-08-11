# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from mobile_agent.agent.actions import (
    CanonicalAction,
    FailAction,
    FinishAction,
    TapAction,
    WaitAction,
)
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.mobile.result import (
    ActionResult,
    DeviceBackendError,
    DeviceErrorKind,
    classify_device_error,
)
from mobile_agent.config.settings import AdbConfig


class AdbCommandError(DeviceBackendError):
    """An ADB command failed without exposing its environment."""

    def __init__(self, message: str, *, kind: DeviceErrorKind):
        super().__init__(message, kind=kind)


@dataclass(frozen=True)
class AdbCommandResult:
    stdout: bytes = b""
    stderr: bytes = b""
    returncode: int = 0


class AdbRunner(Protocol):
    async def run(self, *arguments: str) -> AdbCommandResult: ...


class SubprocessAdbRunner:
    def __init__(self, config: AdbConfig, executable: str = "adb"):
        self._config = config
        self._executable = executable

    async def run(self, *arguments: str) -> AdbCommandResult:
        allowed_environment = (
            "PATH",
            "HOME",
            "USER",
            "LOGNAME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "ANDROID_HOME",
            "ANDROID_SDK_ROOT",
            "ADB_SERVER_SOCKET",
            "ADB_TRACE",
        )
        environment = {
            name: os.environ[name]
            for name in allowed_environment
            if name in os.environ
        }
        if self._config.vendor_keys is not None:
            environment["ADB_VENDOR_KEYS"] = (
                self._config.vendor_keys.get_secret_value()
            )
        process = await asyncio.create_subprocess_exec(
            self._executable,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._config.command_timeout
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await asyncio.shield(process.wait())
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise AdbCommandError(
                "ADB command timed out", kind=DeviceErrorKind.TIMEOUT
            ) from exc
        result = AdbCommandResult(stdout, stderr, process.returncode or 0)
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise AdbCommandError(
                f"ADB command failed: {detail or 'unknown error'}",
                kind=classify_device_error(detail),
            )
        return result


def _to_pixel(coordinate: int, size: int) -> int:
    if size <= 0:
        raise ValueError("Screenshot dimensions must be positive")
    return min(size - 1, max(0, int(coordinate * size / 1000)))


class AdbDeviceBackend:
    name = "adb"

    def __init__(self, config: AdbConfig, runner: AdbRunner | None = None):
        self.config = config
        self._runner = runner or SubprocessAdbRunner(config)

    async def initialize(self, **connection: str) -> None:
        result = await self._runner.run("-s", self.config.serial, "get-state")
        if result.stdout.decode(errors="replace").strip() != "device":
            raise AdbCommandError(
                "Configured ADB target is not in device state",
                kind=DeviceErrorKind.OFFLINE,
            )

    async def take_screenshot(self) -> dict[str, object]:
        final_error: AdbCommandError | None = None
        for _ in range(2):
            try:
                return await self._take_screenshot_once()
            except AdbCommandError as exc:
                final_error = exc
        assert final_error is not None
        raise final_error

    async def _take_screenshot_once(self) -> dict[str, object]:
        result = await self._runner.run(
            "-s", self.config.serial, "exec-out", "screencap", "-p"
        )
        try:
            with Image.open(io.BytesIO(result.stdout)) as screenshot:
                screenshot.verify()
            with Image.open(io.BytesIO(result.stdout)) as screenshot:
                dimensions = screenshot.size
                image_format = screenshot.format
        except (UnidentifiedImageError, OSError) as exc:
            raise AdbCommandError(
                "ADB screenshot was not a valid image",
                kind=DeviceErrorKind.INVALID_OBSERVATION,
            ) from exc
        if image_format != "PNG":
            raise AdbCommandError(
                "ADB screenshot was not PNG",
                kind=DeviceErrorKind.INVALID_OBSERVATION,
            )
        encoded = base64.b64encode(result.stdout).decode("ascii")
        return {
            "screenshot": f"data:image/png;base64,{encoded}",
            "screenshot_dimensions": dimensions,
        }

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall:
        if isinstance(action, TapAction):
            width, height = screenshot_dimensions
            return {
                "name": "mobile:tap",
                "arguments": {
                    "x": _to_pixel(action.x, width),
                    "y": _to_pixel(action.y, height),
                },
            }
        if isinstance(action, WaitAction):
            return {"name": "wait", "arguments": {"t": action.duration_ms / 1000}}
        if isinstance(action, FinishAction):
            return {"name": "finished", "arguments": {"content": action.summary}}
        if isinstance(action, FailAction):
            return {"name": "call_user", "arguments": {"content": action.reason}}
        raise NotImplementedError(
            f"ADB visual-click demo does not execute {type(action).__name__}"
        )

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ActionResult:
        tool_call = self.to_tool_call(action, screenshot_dimensions)
        arguments = tool_call["arguments"]
        try:
            await self._runner.run(
                "-s",
                self.config.serial,
                "shell",
                "input",
                "tap",
                str(arguments["x"]),
                str(arguments["y"]),
            )
        except AdbCommandError as exc:
            if exc.kind is DeviceErrorKind.TIMEOUT:
                return ActionResult.ambiguous(
                    "ADB tap result is unknown after timeout", exc.kind
                )
            return ActionResult.failed(str(exc), exc.kind)
        return ActionResult.success("ADB tap dispatched")

    async def close(self) -> None:
        return None

    async def verify_completion(self, action: CanonicalAction) -> bool | None:
        if not isinstance(action, FinishAction):
            return None
        oracle = AdbForegroundAppOracle(self.config, runner=self._runner)
        return await oracle.is_foreground()


class AdbForegroundAppOracle:
    """Determines completion from Android state, independently of the model."""

    def __init__(self, config: AdbConfig, runner: AdbRunner | None = None):
        self._config = config
        self._runner = runner or SubprocessAdbRunner(config)

    async def is_foreground(self, package_name: str | None = None) -> bool:
        expected = package_name or self._config.oracle_package
        result = await self._runner.run(
            "-s",
            self._config.serial,
            "shell",
            "dumpsys",
            "window",
        )
        state = result.stdout.decode("utf-8", errors="replace")
        for line in state.splitlines():
            if "mCurrentFocus" not in line:
                continue
            component = re.search(r"\bu\d+\s+([A-Za-z0-9._]+)/", line)
            if component is not None:
                return component.group(1) == expected
        return False
