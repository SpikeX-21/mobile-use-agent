# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from mobile_agent.agent.actions import (
    BackAction,
    CanonicalAction,
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


@dataclass(frozen=True)
class AdbCompletionExpectation:
    required_text: str | None = None
    detail_page: bool = False

    @classmethod
    def from_user_prompt(cls, user_prompt: str) -> "AdbCompletionExpectation":
        detail_page = bool(
            re.search(r"(?:第一个|首个|第一条)(?:搜索)?结果", user_prompt)
        )
        if "上海外滩" not in user_prompt:
            return cls(detail_page=detail_page)
        return cls(
            required_text="外滩" if detail_page else "上海外滩",
            detail_page=detail_page,
        )


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
            detail = (
                result.stderr.decode("utf-8", errors="replace").strip()
                or result.stdout.decode("utf-8", errors="replace").strip()
            )
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
        self._completion_expectation = AdbCompletionExpectation()

    async def initialize(self, **connection: str) -> None:
        result = await self._runner.run("-s", self.config.serial, "get-state")
        if result.stdout.decode(errors="replace").strip() != "device":
            raise AdbCommandError(
                "Configured ADB target is not in device state",
                kind=DeviceErrorKind.OFFLINE,
            )

    async def prepare_task(self, user_prompt: str) -> None:
        self._completion_expectation = AdbCompletionExpectation.from_user_prompt(
            user_prompt
        )
        await self._runner.run(
            "-s",
            self.config.serial,
            "shell",
            "am",
            "force-stop",
            self.config.oracle_package,
        )
        await self._runner.run(
            "-s",
            self.config.serial,
            "shell",
            "input",
            "keyevent",
            "KEYCODE_HOME",
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
        if isinstance(action, SwipeAction):
            width, height = screenshot_dimensions
            return {
                "name": "mobile:swipe",
                "arguments": {
                    "from_x": _to_pixel(action.start_x, width),
                    "from_y": _to_pixel(action.start_y, height),
                    "to_x": _to_pixel(action.end_x, width),
                    "to_y": _to_pixel(action.end_y, height),
                    "duration_ms": action.duration_ms,
                },
            }
        if isinstance(action, TextInputAction):
            return {
                "name": "mobile:text_input",
                "arguments": {"text": action.text},
            }
        if isinstance(action, ClearTextAction):
            return {"name": "mobile:clear_text", "arguments": {}}
        if isinstance(action, HomeAction):
            return {"name": "mobile:home", "arguments": {}}
        if isinstance(action, BackAction):
            return {"name": "mobile:back", "arguments": {}}
        if isinstance(action, MenuAction):
            return {"name": "mobile:menu", "arguments": {}}
        if isinstance(action, LaunchAppAction):
            return {
                "name": "mobile:launch_app",
                "arguments": {"package_name": action.package_name},
            }
        if isinstance(action, CloseAppAction):
            return {
                "name": "mobile:close_app",
                "arguments": {"package_name": action.package_name},
            }
        if isinstance(action, ListAppsAction):
            arguments = (
                {}
                if action.ignore_system_apps is None
                else {"ignore_system_apps": action.ignore_system_apps}
            )
            return {"name": "mobile:list_apps", "arguments": arguments}
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
        if isinstance(action, WaitAction):
            await asyncio.sleep(action.duration_ms / 1000)
            return ActionResult.success(
                f"Waited {action.duration_ms / 1000:g}s for the UI to settle"
            )
        if isinstance(action, ListAppsAction):
            return await self._list_apps(action)
        try:
            if isinstance(action, TapAction):
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "input",
                    "tap",
                    str(arguments["x"]),
                    str(arguments["y"]),
                )
            elif isinstance(action, SwipeAction):
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "input",
                    "swipe",
                    str(arguments["from_x"]),
                    str(arguments["from_y"]),
                    str(arguments["to_x"]),
                    str(arguments["to_y"]),
                    str(arguments["duration_ms"]),
                )
            elif isinstance(action, TextInputAction):
                await self._input_text(action.text)
            elif isinstance(action, ClearTextAction):
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "input",
                    "keycombination",
                    "113",
                    "29",
                )
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "input",
                    "keyevent",
                    "KEYCODE_DEL",
                )
            elif isinstance(action, (HomeAction, BackAction, MenuAction)):
                keycode = {
                    "home": "KEYCODE_HOME",
                    "back": "KEYCODE_BACK",
                    "menu": "KEYCODE_MENU",
                }[action.type]
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "input",
                    "keyevent",
                    keycode,
                )
            elif isinstance(action, LaunchAppAction):
                try:
                    component = await self._resolve_launcher_component(
                        action.package_name
                    )
                except AdbCommandError as exc:
                    return ActionResult.failed(str(exc), exc.kind)
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "am",
                    "start",
                    "-n",
                    component,
                )
            elif isinstance(action, CloseAppAction):
                await self._runner.run(
                    "-s",
                    self.config.serial,
                    "shell",
                    "am",
                    "force-stop",
                    action.package_name,
                )
            else:
                raise NotImplementedError(
                    f"ADB backend cannot execute {type(action).__name__}"
                )
        except AdbCommandError as exc:
            if exc.kind is DeviceErrorKind.TIMEOUT:
                return ActionResult.ambiguous(
                    f"ADB {action.type} result is unknown after timeout", exc.kind
                )
            return ActionResult.failed(str(exc), exc.kind)
        return ActionResult.success(f"ADB {action.type} dispatched")

    async def _list_apps(self, action: ListAppsAction) -> ActionResult:
        command = [
            "-s",
            self.config.serial,
            "shell",
            "pm",
            "list",
            "packages",
        ]
        if action.ignore_system_apps:
            command.append("-3")
        for attempt in range(2):
            try:
                result = await self._runner.run(*command)
                packages = sorted(
                    {
                        package_name
                        for line in result.stdout.decode(
                            "utf-8", errors="replace"
                        ).splitlines()
                        if line.startswith("package:")
                        for package_name in [line.removeprefix("package:")]
                        if re.fullmatch(
                            r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+",
                            package_name,
                        )
                    }
                )
                return ActionResult.success(
                    f"Installed packages ({len(packages)}): "
                    + ", ".join(packages)
                )
            except AdbCommandError as exc:
                if exc.kind is DeviceErrorKind.TIMEOUT and attempt == 0:
                    continue
                return ActionResult.failed(str(exc), exc.kind)
        raise AssertionError("ADB list_apps attempt loop did not return")

    async def _resolve_launcher_component(self, package_name: str) -> str:
        result = await self._runner.run(
            "-s",
            self.config.serial,
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            package_name,
        )
        component_pattern = re.compile(
            rf"{re.escape(package_name)}/[A-Za-z0-9_.$]+"
        )
        for line in reversed(
            result.stdout.decode("utf-8", errors="replace").splitlines()
        ):
            component = line.strip()
            if component_pattern.fullmatch(component):
                return component
        raise AdbCommandError(
            "ADB could not resolve a launcher activity for the package",
            kind=DeviceErrorKind.COMMAND_FAILED,
        )

    async def _input_text(self, text: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9._@+\-]+", text):
            await self._runner.run(
                "-s",
                self.config.serial,
                "shell",
                "input",
                "text",
                text,
            )
            return

        await self._runner.run(
            "-s",
            self.config.serial,
            "exec-out",
            "cmd",
            "clipboard",
            "set",
            text,
        )
        await self._runner.run(
            "-s",
            self.config.serial,
            "shell",
            "input",
            "keyevent",
            "KEYCODE_PASTE",
        )

    async def close(self) -> None:
        return None

    async def verify_completion(self, action: CanonicalAction) -> bool | None:
        if not isinstance(action, FinishAction):
            return None
        oracle = AdbTaskOracle(self.config, runner=self._runner)
        try:
            return await oracle.is_complete(
                required_text=self._completion_expectation.required_text,
                detail_page=self._completion_expectation.detail_page,
            )
        except AdbCommandError:
            return False


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


class AdbTaskOracle:
    """Checks task completion using Android state rather than model claims."""

    def __init__(self, config: AdbConfig, runner: AdbRunner | None = None):
        self._config = config
        self._runner = runner or SubprocessAdbRunner(config)

    async def is_complete(
        self,
        required_text: str | None = None,
        *,
        detail_page: bool = False,
    ) -> bool:
        foreground_oracle = AdbForegroundAppOracle(
            self._config, runner=self._runner
        )
        if not await foreground_oracle.is_foreground():
            return False
        if required_text is None and not detail_page:
            return True

        result = await self._runner.run(
            "-s",
            self._config.serial,
            "exec-out",
            "uiautomator",
            "dump",
            "--compressed",
            "/dev/tty",
        )
        output = result.stdout.decode("utf-8", errors="replace")
        hierarchy_end = output.find("</hierarchy>")
        if hierarchy_end < 0:
            return False
        xml_document = output[: hierarchy_end + len("</hierarchy>")]
        try:
            hierarchy = ET.fromstring(xml_document)
        except ET.ParseError:
            return False
        visible_nodes = [
            node
            for node in hierarchy.iter()
            if node.attrib.get("visible-to-user", "true").lower() != "false"
        ]
        visible_values = [
            node.attrib.get(attribute, "")
            for node in visible_nodes
            for attribute in ("text", "content-desc")
            if node.attrib.get(attribute, "")
        ]
        if required_text is not None:
            target_is_visible = (
                any(
                    node.attrib.get("content-desc") == required_text
                    and node.attrib.get("class") == "android.view.ViewGroup"
                    and node.attrib.get("clickable") == "true"
                    and node.attrib.get("long-clickable") == "true"
                    for node in visible_nodes
                )
                if detail_page
                else any(required_text in value for value in visible_values)
            )
            if not target_is_visible:
                return False
        if not detail_page:
            return True
        # Compressed hierarchies omit non-focusable child labels such as the
        # visible "导航" and "路线" text.  The exact semantic title node plus
        # the detail-only favourite control remains stable device evidence.
        return any(value.startswith("收藏按钮") for value in visible_values)
