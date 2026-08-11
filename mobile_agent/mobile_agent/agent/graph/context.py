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

from typing import Dict, Literal, Optional
import asyncio
from mobile_agent.agent.cost.calculator import CostCalculator
from mobile_agent.agent.memory.context_manager import ContextManager
from mobile_agent.agent.mobile.client import Mobile
from mobile_agent.agent.tools.tools import Tools
from mobile_agent.agent.mobile.doubao_action_parser import (
    DoubaoActionSpaceParser,
)


class AgentObjectManager:
    """管理与thread_id相关的不可序列化对象"""

    def __init__(self):
        self._contexts: Dict[str, Dict] = {}

    def create_context(
        self,
        thread_id: str,
        mobile_client: Mobile,
        tools: Tools,
        sse_connection: asyncio.Event,
        action_parser: DoubaoActionSpaceParser,
        cost_calculator: CostCalculator,
    ):
        """为特定thread_id创建上下文"""
        self._contexts[thread_id] = {
            "mobile_client": mobile_client,
            "tools": tools,
            "sse_connection": sse_connection,
            "action_parser": action_parser,
            "cost_calculator": cost_calculator,
        }

    def add_context_object(
        self, thread_id: str, key: Literal["context_manager"], value: ContextManager
    ):
        if not self.has_context(thread_id):
            return
        if key in self._contexts[thread_id]:
            return
        self._contexts[thread_id][key] = value

    def get_context_manager(self, thread_id: str) -> Optional[ContextManager]:
        return self._contexts.get(thread_id, {}).get("context_manager")

    def get_mobile_client(self, thread_id: str) -> Optional[Mobile]:
        return self._contexts.get(thread_id, {}).get("mobile_client")

    def get_tools(self, thread_id: str) -> Optional[Tools]:
        return self._contexts.get(thread_id, {}).get("tools")

    def get_sse_connection(self, thread_id: str) -> Optional[asyncio.Event]:
        return self._contexts.get(thread_id, {}).get("sse_connection")

    def get_action_parser(self, thread_id: str) -> Optional[DoubaoActionSpaceParser]:
        return self._contexts.get(thread_id, {}).get("action_parser")

    def get_cost_calculator(self, thread_id: str) -> Optional[CostCalculator]:
        return self._contexts.get(thread_id, {}).get("cost_calculator")

    def destroy_context(self, thread_id: str):
        """清理特定thread_id的上下文"""
        if thread_id in self._contexts:
            self._contexts.pop(thread_id)
            # 暂时没有需要清理的 object

    def has_context(self, thread_id: str) -> bool:
        return thread_id in self._contexts


# 全局实例
agent_object_manager = AgentObjectManager()
