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

from typing import Optional
from langchain_core.tools import StructuredTool
from mobile_agent.agent.tools.tool.abc import Tool
from mobile_agent.agent.tools.mcp import MCPHub


class McpTool(Tool):
    def __init__(self, mcp_hub: MCPHub, mcp_name: str, mcp_tool: StructuredTool):
        super().__init__(
            name=f"{mcp_name}:{mcp_tool.name}",
            description=mcp_tool.description,
            parameters=mcp_tool.args_schema,
        )
        self.mcp_name = mcp_name
        self.mcp_tool = mcp_tool
        self.mcp_hub = mcp_hub

    async def handler(self, args: Optional[dict] = {}) -> str | None:
        toolResults = await self.mcp_hub.call_tool(
            self.mcp_name, self.mcp_tool.name, args
        )
        contents = list(
            map(
                lambda content: content.text if content.type == "text" else None,
                toolResults.content,
            )
        )
        # 暂时只取第一个
        return contents[0]
