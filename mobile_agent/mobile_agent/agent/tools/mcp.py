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

import asyncio
from contextlib import AsyncExitStack
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.session import ClientSession
import logging

logger = logging.getLogger(__name__)


class MCPHub:
    def __init__(self, mcp_json: dict = None):
        self.mcp_json = mcp_json or {}
        self.create_client()
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        self.client: MultiServerMCPClient | None = None
        self.sessions: dict[str, ClientSession] = {}

    def update_mcp_json(self, mcp_json: dict):
        self.mcp_json.update(mcp_json)
        self.create_client()

    def add_mcp_json(self, key: str, update_key_content: dict):
        if key in self.mcp_json:
            self.mcp_json[key].update(update_key_content)
        else:
            self.mcp_json[key] = update_key_content

        self.create_client()

    def create_client(self):
        if not self.mcp_json:
            return

        self.client = MultiServerMCPClient(self.mcp_json)

    async def create_all_sessions(self):
        tasks = []
        for key in self.mcp_json:
            task = asyncio.create_task(self.session(key))
            tasks.append(task)
        await asyncio.gather(*tasks)

    async def session(self, key: str):
        if key in self.sessions:
            return self.sessions[key]

        self.sessions[key] = await self.exit_stack.enter_async_context(
            self.client.session(key)
        )

        return self.sessions[key]

    async def aclose(self):
        try:
            await self.exit_stack.aclose()
            self.sessions = {}
            logger.info("MCP session closed")
        except Exception as e:
            logger.error(f"Failed to close MCP sessions: {e}")
            self.sessions = {}

    async def call_tool(self, mcp_server_name: str, name: str, arguments: dict):
        session = await self.session(mcp_server_name)
        if not session:
            raise ValueError("MCP session is not valid")

        response = await session.call_tool(name, arguments)
        if not self.is_valid_mcp_response(response):
            text_content = (
                response.content[0].text
                if response.content[0].text
                else "MCP工具调用失败，未返回错误信息"
            )
            raise Exception(text_content)
        return response

    def is_valid_mcp_response(self, result) -> bool:
        if result.isError:
            return False

        if len(result.content) == 0:
            return False

        # 当前阶段只处理 text 类型的
        if result.content[0].type != "text":
            return False

        text_content = result.content[0].text
        if text_content == "{}" or "Error" in text_content:
            return False

        return True

    async def get_tools(self, mcp_server_name: str | None = None):
        if mcp_server_name:
            tools = await self.client.get_tools(server_name=mcp_server_name)
        else:
            tools = await self.client.get_tools()

        return tools
