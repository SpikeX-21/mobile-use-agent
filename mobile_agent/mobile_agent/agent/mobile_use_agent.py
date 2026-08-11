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
from mobile_agent.agent.cost.calculator import CostCalculator
from mobile_agent.agent.mobile.doubao_action_parser import (
    DoubaoActionSpaceParser,
)
from mobile_agent.agent.mobile.client import Mobile
from mobile_agent.agent.tools.tools import Tools
from .infra.logger import AgentLogger
from mobile_agent.config.settings import get_agent_config
from mobile_agent.agent.prompt.doubao_vision_pro import doubao_system_prompt
from mobile_agent.agent.tools.mcp import MCPHub
from mobile_agent.agent.graph.builder import graph
from mobile_agent.agent.graph.context import agent_object_manager


class MobileUseAgent:
    name = "mobile_use"

    def __init__(self):
        self.prompt = doubao_system_prompt
        self.logger = AgentLogger(__name__)

        agent_config = get_agent_config(MobileUseAgent.name)
        self.logger.info(f"agent_config: {agent_config}")

        self.max_steps = agent_config.max_steps
        self.step_interval = agent_config.step_interval
        self.mcp_hub = MCPHub()
        self.mobile_client = Mobile(self.mcp_hub)
        self.cost_calculator = CostCalculator(MobileUseAgent.name)

    async def initialize(
        self,
        pod_id: str,
        auth_token: str,
        product_id: str,
        tos_bucket: str,
        tos_region: str,
        tos_endpoint: str,
    ):
        """异步初始化方法，子类可以覆盖此方法进行异步初始化

        该方法默认返回self，允许链式调用
        """
        self.logger.set_context(pod_id=pod_id)
        await self.mobile_client.initialize(
            pod_id=pod_id,
            product_id=product_id,
            tos_bucket=tos_bucket,
            tos_region=tos_region,
            tos_endpoint=tos_endpoint,
            auth_token=auth_token,
        )
        self.tools = await Tools.from_mcp(self.mcp_hub)

        return self

    async def aclose(self) -> None:
        await self.mcp_hub.aclose()

    async def run(
        self,
        query: str,
        is_stream: bool,
        task_id: str,
        session_id: str,
        thread_id: str,
        sse_connection: asyncio.Event,
        phone_width: int,
        phone_height: int,
    ):
        try:
            self.logger.set_context(thread_id=session_id, chat_thread_id=thread_id)
            self.task_id = task_id
            self.stream = is_stream
            initial_state = {
                "user_prompt": query,
                "iteration_count": 0,
                "task_id": task_id,
                "thread_id": thread_id,
                "is_stream": is_stream,
                "max_iterations": self.max_steps,
                "step_interval": self.step_interval,
            }
            agent_object_manager.create_context(
                thread_id=thread_id,
                mobile_client=self.mobile_client,
                tools=self.tools,
                sse_connection=sse_connection,
                action_parser=DoubaoActionSpaceParser(
                    phone_width=phone_width,
                    phone_height=phone_height,
                ),
                cost_calculator=self.cost_calculator,
            )

            config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": self.max_steps * 3,
            }

            async for chunk in graph.astream(
                input=initial_state,
                config=config,
                stream_mode=["messages", "custom"],
            ):
                yield chunk
        finally:
            if self.stream:
                self.logger.info("stream mode, not support cost calculator")
            else:
                self.cost_calculator.print_cost()
            agent_object_manager.destroy_context(thread_id)
