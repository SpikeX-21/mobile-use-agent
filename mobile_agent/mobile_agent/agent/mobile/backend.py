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
from typing import Any, Protocol

from mobile_agent.agent.actions import CanonicalAction, ListAppsAction, WaitAction
from mobile_agent.agent.actions.mcp_adapter import canonical_action_to_mcp_tool_call
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.mobile.client import Mobile
from mobile_agent.agent.mobile.result import (
    ActionResult,
    DeviceBackendError,
    DeviceErrorKind,
    classify_device_error,
)
from mobile_agent.agent.provider import (
    ProviderNotImplementedError,
    UnknownProviderError,
)
from mobile_agent.agent.tools.mcp import MCPHub
from mobile_agent.agent.tools.tools import Tools


class DeviceBackend(Protocol):
    name: str

    async def initialize(self, **connection: str) -> None: ...

    async def take_screenshot(self) -> dict[str, Any]: ...

    async def prepare_task(self, user_prompt: str) -> None: ...

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ActionResult: ...

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall: ...

    async def verify_completion(self, action: CanonicalAction) -> bool | None: ...

    async def close(self) -> None: ...


class McpDeviceBackend:
    name = "mcp"

    def __init__(
        self,
        mcp_hub: MCPHub | None = None,
        tools: Tools | Any | None = None,
        mobile: Mobile | Any | None = None,
    ):
        self._mcp_hub = mcp_hub or MCPHub()
        self._mobile = mobile or Mobile(self._mcp_hub)
        self._tools = tools

    async def initialize(self, **connection: str) -> None:
        await self._mobile.initialize(**connection)
        if self._tools is None:
            self._tools = await Tools.from_mcp(self._mcp_hub)

    async def take_screenshot(self) -> dict[str, Any]:
        final_error: Exception | None = None
        for _ in range(2):
            try:
                return await self._mobile.take_screenshot()
            except Exception as exc:
                final_error = exc
        assert final_error is not None
        kind = classify_device_error(final_error)
        raise DeviceBackendError(str(final_error), kind=kind) from final_error

    async def prepare_task(self, user_prompt: str) -> None:
        return None

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ActionResult:
        if self._tools is None:
            raise RuntimeError("MCP device backend is not initialized")
        if isinstance(action, WaitAction):
            await asyncio.sleep(action.duration_ms / 1000)
            return ActionResult.success(
                f"Waited {action.duration_ms / 1000:g}s for the UI to settle"
            )
        tool_call = self.to_tool_call(action, screenshot_dimensions)
        attempts = 2 if isinstance(action, ListAppsAction) else 1
        for attempt in range(attempts):
            try:
                result = await self._tools.exec(tool_call)
                return ActionResult.success(str(result))
            except Exception as exc:
                kind = classify_device_error(exc)
                if kind is DeviceErrorKind.TIMEOUT:
                    if attempt + 1 < attempts:
                        continue
                    if isinstance(action, ListAppsAction):
                        return ActionResult.failed(
                            "MCP read timed out after bounded retry", kind
                        )
                    return ActionResult.ambiguous(
                        "MCP action result is unknown after timeout", kind
                    )
                return ActionResult.failed(str(exc), kind)
        raise AssertionError("MCP action attempt loop did not return")

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall:
        return canonical_action_to_mcp_tool_call(action, screenshot_dimensions)

    async def close(self) -> None:
        await self._mcp_hub.aclose()

    async def verify_completion(self, action: CanonicalAction) -> bool | None:
        return None


def create_device_backend(provider_name: str, **dependencies: Any) -> DeviceBackend:
    normalized_name = provider_name.strip().lower()
    if normalized_name == "mcp":
        return McpDeviceBackend(**dependencies)
    if normalized_name == "adb":
        from mobile_agent.agent.mobile.adb import AdbDeviceBackend
        from mobile_agent.config.settings import get_settings

        if "config" not in dependencies:
            dependencies["config"] = get_settings().get_adb_config()
        return AdbDeviceBackend(**dependencies)
    if normalized_name == "vendor_mcp":
        raise ProviderNotImplementedError(
            "Device provider 'vendor_mcp' is not implemented"
        )
    raise UnknownProviderError(f"Unknown device provider: {provider_name!r}")
