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

import json

from mobile_agent.config.settings import MOBILE_USE_MCP_NAME
from mobile_agent.agent.tools.tool.mcp_tool import McpTool
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.tools.tool import (
    FinishedTool,
    WaitTool,
    CallUserTool,
    ErrorTool,
)
from mobile_agent.agent.tools.mcp import MCPHub
from mobile_agent.agent.tools.tool.abc import Tool, SpecialTool


class Tools:
    def __init__(
        self,
        tools: list[Tool | SpecialTool | McpTool],
    ):
        self.tools = tools

    @classmethod
    async def from_mcp(cls, mcp_hub: MCPHub):
        tools = [
            FinishedTool(),
            WaitTool(),
            CallUserTool(),
            ErrorTool(),
            *list(
                map(
                    lambda tool: McpTool(mcp_hub, MOBILE_USE_MCP_NAME, tool),
                    await mcp_hub.get_tools(MOBILE_USE_MCP_NAME),
                )
            ),
        ]
        return cls(tools)

    def prompt_tools(self):
        return list(map(lambda tool: tool, self.tools))

    def list_tools_schema_for_openai(self):
        tools = list(map(lambda tool: tool.get_tool_schema_for_openai(), self.tools))
        return tools

    def list_tools_prompt_string(self):
        tools = list(map(lambda tool: tool.get_prompt_string(), self.tools))
        return tools

    async def exec(self, tool_call: ToolCall):
        tool = self.get_tool_by_name(tool_call["name"])
        if tool:
            content = await tool.call(tool_call["arguments"])
            return content
        else:
            raise ValueError(f"Tool with name {tool_call['name']} not found")

    def is_special_tool(self, tool_name: str):
        tool = self.get_tool_by_name(tool_name)
        return tool and tool.is_special_tool

    def get_special_message(self, tool_name: str, content: str, args: dict):
        tool = self.get_tool_by_name(tool_name)
        if tool and tool.is_special_tool:
            return tool.special_message(content, args)
        else:
            return None

    def get_special_memory(self, tool_name: str):
        tool = self.get_tool_by_name(tool_name)
        if tool and tool.is_special_tool:
            return tool.special_memory()
        else:
            return None

    def get_tool_by_name(self, tool_name: str) -> Tool | SpecialTool | McpTool | None:
        return next((tool for tool in self.tools if tool.name == tool_name), None)
