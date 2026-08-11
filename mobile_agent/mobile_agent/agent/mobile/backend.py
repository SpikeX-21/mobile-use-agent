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

from typing import Any, Protocol

from mobile_agent.agent.actions import CanonicalAction
from mobile_agent.agent.actions.mcp_adapter import canonical_action_to_mcp_tool_call
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.mobile.client import Mobile
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

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> Any: ...

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall: ...

    async def close(self) -> None: ...


class McpDeviceBackend:
    name = "mcp"

    def __init__(
        self,
        mcp_hub: MCPHub | None = None,
        tools: Tools | Any | None = None,
    ):
        self._mcp_hub = mcp_hub or MCPHub()
        self._mobile = Mobile(self._mcp_hub)
        self._tools = tools

    async def initialize(self, **connection: str) -> None:
        await self._mobile.initialize(**connection)
        if self._tools is None:
            self._tools = await Tools.from_mcp(self._mcp_hub)

    async def take_screenshot(self) -> dict[str, Any]:
        return await self._mobile.take_screenshot()

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> Any:
        if self._tools is None:
            raise RuntimeError("MCP device backend is not initialized")
        tool_call = self.to_tool_call(action, screenshot_dimensions)
        return await self._tools.exec(tool_call)

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall:
        return canonical_action_to_mcp_tool_call(action, screenshot_dimensions)

    async def close(self) -> None:
        await self._mcp_hub.aclose()


def create_device_backend(provider_name: str, **dependencies: Any) -> DeviceBackend:
    normalized_name = provider_name.strip().lower()
    if normalized_name == "mcp":
        return McpDeviceBackend(**dependencies)
    if normalized_name == "adb":
        raise ProviderNotImplementedError(
            "Device provider 'adb' is not implemented; complete issue #3 first"
        )
    if normalized_name == "vendor_mcp":
        raise ProviderNotImplementedError(
            "Device provider 'vendor_mcp' is not implemented"
        )
    raise UnknownProviderError(f"Unknown device provider: {provider_name!r}")
