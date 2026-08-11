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

from typing import List
from langchain_core.messages import BaseMessage
import asyncio
import logging
from mobile_agent.config.settings import get_agent_config, get_model_config
from mobile_agent.agent.memory.messages import AgentMessages
from mobile_agent.agent.prompt.doubao_vision_pro import doubao_system_prompt
from mobile_agent.agent.graph.context import agent_object_manager
from mobile_agent.agent.llm.stream_pipe import stream_pipeline
from langchain_openai import ChatOpenAI
from openai import OpenAI


class DoubaoLLM:
    prompt = doubao_system_prompt

    def __init__(self, thread_id: str, is_stream: bool):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.is_stream = is_stream
        self.thread_id = thread_id

        agent_config = get_agent_config("mobile_use")
        if agent_config.modelKey:
            model_config = get_model_config(agent_config.modelKey)
            self.model_name = model_config.model
            self.base_url = model_config.base_url
            self.api_key = model_config.api_key
            self.temperature = model_config.temperature
            self.max_tokens = model_config.max_tokens

        self.llm = ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model_name,
            streaming=is_stream,
            max_completion_tokens=self.max_tokens,
            temperature=self.temperature,
            stream_usage=True,
        )

    async def async_chat(
        self, messages: List[BaseMessage]
    ) -> tuple[str, str, str, str]:
        """调用模型并处理重试逻辑"""
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                chunk_id, content, summary, tool_call = await self._invoke_model(
                    messages
                )

                return chunk_id, content, summary, tool_call

            except asyncio.CancelledError as e:
                # cancel 不处理，直接向外抛出
                raise e

            except Exception as e:
                retry_count += 1
                self.logger.error(f"模型调用失败，重试第 {retry_count} 次。错误: {e}")

                if retry_count >= max_retries:
                    raise e

                await asyncio.sleep(1)

    async def _invoke_model(self, messages: List[BaseMessage]) -> tuple[str, str, str]:
        if self.is_stream:
            return await self._invoke_stream_model(messages)
        else:
            return await self._invoke_sync_model(messages)

    async def _invoke_stream_model(
        self, messages: List[BaseMessage]
    ) -> tuple[str, str, str]:
        index = 0
        chunk_id = ""
        response = self.llm.astream(messages)
        async for chunk in response:
            if index == 0:
                chunk_id = chunk.id
                stream_pipeline.create(id=chunk_id)
            index += 1
        content, summary, tool_call = stream_pipeline.complete(id=chunk_id)

        return chunk_id, content, summary, tool_call

    async def _invoke_sync_model(
        self, messages: List[BaseMessage]
    ) -> tuple[str, str, str]:
        use_openai_client = True
        # Ark Api 在 Langchain 下拿不到 token usage
        if use_openai_client:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model_name,
                messages=AgentMessages.convert_langchain_to_openai_messages(messages),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            content = response.choices[0].message.content
            output_tokens = response.usage.completion_tokens
            input_tokens = response.usage.prompt_tokens

            cost_calculator = agent_object_manager.get_cost_calculator(self.thread_id)
            if cost_calculator:
                cost_calculator.record_cost(
                    input_tokens=input_tokens, output_tokens=output_tokens
                )

        else:
            response = self.llm.invoke(messages)
            content = response.content
        stream_pipeline.create(id=response.id)
        stream_pipeline.pipe(id=response.id, delta=content)
        content, summary, tool_call = stream_pipeline.complete(id=response.id)

        return response.id, content, summary, tool_call
