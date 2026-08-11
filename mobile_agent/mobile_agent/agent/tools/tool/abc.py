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

from abc import ABC, abstractmethod
import json
from typing import Optional


class Tool(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        is_special_tool: Optional[bool] = False,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.is_special_tool = is_special_tool

    async def call(self, args: Optional[dict] = {}) -> str:
        result = await self.handler(args)
        if result is None:
            return ""
        return result

    @abstractmethod
    async def handler(self, args: Optional[dict] = {}) -> str | None:
        pass

    def get_tool_schema_for_openai(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def get_prompt_string(self):
        json_str = json.dumps(self.parameters)
        return (
            f"name: {self.name}\ndescription: {self.description}\narguments: {json_str}"
        )


class SpecialTool(Tool):
    def __init__(self, name: str, description: str, parameters: dict):
        super().__init__(name, description, parameters, is_special_tool=True)

    def special_message(self, content: str, args: dict) -> str | None:
        pass

    def special_memory(self) -> str | None:
        pass
