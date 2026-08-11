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

from typing import Any, Protocol, Sequence

from langchain_core.messages import BaseMessage
from pydantic import ValidationError

from mobile_agent.agent.actions import CanonicalAction
from mobile_agent.agent.llm.doubao import DoubaoLLM
from mobile_agent.agent.mobile.doubao_action_parser import DoubaoActionSpaceParser
from mobile_agent.agent.prompt.doubao_vision_pro import doubao_system_prompt
from mobile_agent.agent.provider import (
    ProviderNotImplementedError,
    UnknownProviderError,
)


class ActionParseError(ValueError):
    """The model response could not be converted into a canonical action."""


class ModelProvider(Protocol):
    name: str
    prompt: str

    async def async_chat(
        self, messages: Sequence[BaseMessage]
    ) -> tuple[str, str, str, str]: ...

    def parse_action(self, action_call: str) -> CanonicalAction: ...


class DoubaoModelProvider:
    name = "doubao"
    prompt = doubao_system_prompt

    def __init__(
        self,
        thread_id: str,
        is_stream: bool,
        llm: Any | None = None,
        action_parser: DoubaoActionSpaceParser | None = None,
    ):
        self._llm = llm or DoubaoLLM(thread_id=thread_id, is_stream=is_stream)
        self._action_parser = action_parser or DoubaoActionSpaceParser()

    async def async_chat(
        self, messages: Sequence[BaseMessage]
    ) -> tuple[str, str, str, str]:
        return await self._llm.async_chat(list(messages))

    def parse_action(self, action_call: str) -> CanonicalAction:
        try:
            action = self._action_parser.to_canonical_action(action_call)
        except (ValidationError, ValueError) as exc:
            raise ActionParseError(
                "Doubao response contained invalid action arguments"
            ) from exc
        if action is None:
            raise ActionParseError("Doubao response did not contain a valid action")
        return action


def create_model_provider(
    provider_name: str,
    *,
    thread_id: str,
    is_stream: bool,
    **dependencies: Any,
) -> ModelProvider:
    normalized_name = provider_name.strip().lower()
    if normalized_name == "doubao":
        return DoubaoModelProvider(
            thread_id=thread_id,
            is_stream=is_stream,
            **dependencies,
        )
    if normalized_name == "kimi":
        raise ProviderNotImplementedError(
            "Model provider 'kimi' is not implemented; complete issue #3 first"
        )
    raise UnknownProviderError(f"Unknown model provider: {provider_name!r}")
