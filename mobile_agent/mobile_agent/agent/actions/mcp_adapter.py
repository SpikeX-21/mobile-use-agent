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

from mobile_agent.agent.actions.model import (
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
from mobile_agent.config.settings import MOBILE_USE_MCP_NAME


def _to_pixel(coordinate: int, size: int) -> int:
    return min(size - 1, int(coordinate * size / 1000))


def canonical_action_to_mcp_tool_call(
    action: CanonicalAction,
    screenshot_dimensions: tuple[int, int],
) -> ToolCall:
    width, height = screenshot_dimensions
    if width <= 0 or height <= 0:
        raise ValueError("Screenshot dimensions must be positive")

    if isinstance(action, TapAction):
        return {
            "name": f"{MOBILE_USE_MCP_NAME}:tap",
            "arguments": {
                "x": _to_pixel(action.x, width),
                "y": _to_pixel(action.y, height),
            },
        }
    if isinstance(action, SwipeAction):
        return {
            "name": f"{MOBILE_USE_MCP_NAME}:swipe",
            "arguments": {
                "from_x": _to_pixel(action.start_x, width),
                "from_y": _to_pixel(action.start_y, height),
                "to_x": _to_pixel(action.end_x, width),
                "to_y": _to_pixel(action.end_y, height),
            },
        }
    if isinstance(action, TextInputAction):
        return {
            "name": f"{MOBILE_USE_MCP_NAME}:text_input",
            "arguments": {"text": action.text},
        }
    if isinstance(action, ClearTextAction):
        return {"name": f"{MOBILE_USE_MCP_NAME}:clear_text", "arguments": {}}
    if isinstance(action, HomeAction):
        return {"name": f"{MOBILE_USE_MCP_NAME}:home", "arguments": {}}
    if isinstance(action, BackAction):
        return {"name": f"{MOBILE_USE_MCP_NAME}:back", "arguments": {}}
    if isinstance(action, MenuAction):
        return {"name": f"{MOBILE_USE_MCP_NAME}:menu", "arguments": {}}
    if isinstance(action, LaunchAppAction):
        return {
            "name": f"{MOBILE_USE_MCP_NAME}:launch_app",
            "arguments": {"package_name": action.package_name},
        }
    if isinstance(action, CloseAppAction):
        return {
            "name": f"{MOBILE_USE_MCP_NAME}:close_app",
            "arguments": {"package_name": action.package_name},
        }
    if isinstance(action, ListAppsAction):
        return {"name": f"{MOBILE_USE_MCP_NAME}:list_apps", "arguments": {}}
    if isinstance(action, WaitAction):
        return {"name": "wait", "arguments": {"t": action.duration_ms / 1000}}
    if isinstance(action, FinishAction):
        return {"name": "finished", "arguments": {"content": action.summary}}
    if isinstance(action, FailAction):
        return {"name": "call_user", "arguments": {"content": action.reason}}

    raise TypeError(f"Unsupported canonical action: {type(action).__name__}")
