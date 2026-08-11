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

import json
from typing import Any, Sequence

from langchain_core.messages import BaseMessage
from openai import AsyncOpenAI
from pydantic import ValidationError

from mobile_agent.agent.actions import CanonicalAction, validate_canonical_action
from mobile_agent.agent.llm.provider import ActionParseError
from mobile_agent.agent.memory.messages import AgentMessages
from mobile_agent.agent.prompt.kimi_k2_6 import kimi_system_prompt
from mobile_agent.config.settings import KimiConfig


class KimiModelProvider:
    name = "kimi"
    prompt = kimi_system_prompt
    supports_streaming = False

    def __init__(
        self,
        thread_id: str,
        config: KimiConfig,
        client: Any | None = None,
    ):
        self.thread_id = thread_id
        self.config = config
        self._client = client or AsyncOpenAI(
            api_key=config.api_key.get_secret_value(),
            base_url=config.base_url,
        )

    async def async_chat(
        self, messages: Sequence[BaseMessage]
    ) -> tuple[str, str, str, str]:
        response = await self._client.chat.completions.create(
            model=self.config.model,
            messages=AgentMessages.convert_langchain_to_openai_messages(
                list(messages)
            ),
            temperature=0.6,
            stream=False,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": self.config.thinking_mode}},
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ActionParseError("Kimi response content is empty")

        summary = "正在校验模型动作"
        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and isinstance(payload.get("summary"), str):
                summary = payload["summary"]
        except json.JSONDecodeError:
            pass

        return response.id, content, summary, content

    def parse_action(self, action_call: str) -> CanonicalAction:
        try:
            payload = json.loads(action_call)
            action_payload = payload.get("action") if isinstance(payload, dict) else None
            if action_payload is None:
                raise ActionParseError("Kimi response does not contain an action")
            return validate_canonical_action(action_payload)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ActionParseError("Kimi response contains an invalid action") from exc
