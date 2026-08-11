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

import logging
from mobile_agent.agent.infra.message_web import SSEThinkMessageData
from mobile_agent.agent.tools.tool.abc import SpecialTool

logger = logging.getLogger(__name__)


class ErrorTool(SpecialTool):
    def __init__(self):
        super().__init__(
            name="error_action",
            description="If the model output is not in the correct format, call this action. You must summary the task result in content.",
            parameters={},
        )

    async def handler(
        self,
        args: dict,
    ):
        content = args.get("content")
        logger.error(f"模型输出解析失败，正在尝试重新生成: {content}")
        return "模型输出解析失败，正在尝试重新生成"

    def special_message(self, content: str, args: dict):
        return SSEThinkMessageData(
            id=args.get("chunk_id"),
            task_id=args.get("task_id"),
            role="assistant",
            type="think",
            content=content,
        )

    def special_memory(self):
        return """模型输出解析失败，请尝试重新按照正确的格式生成
```
Summary: ...
Action: ...
```
注意：
1. 不要输出 ``` ，直接输出 Summary: ...\nAction: ...
2. 遵循系统提示词的 ActionSpace 的Action做输出
"""
