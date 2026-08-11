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

from mobile_agent.agent.infra.message_web import SummaryMessageData
from mobile_agent.agent.tools.tool.abc import SpecialTool


class FinishedTool(SpecialTool):
    def __init__(self):
        super().__init__(
            name="finished",
            description="If the task is completed, call this action. You must summary the task result in content.",
            parameters={
                "content": {
                    "type": "string",
                    "description": "The content to summary the task result",
                }
            },
        )

    async def handler(self, args: dict):
        return args.get("content")

    def special_message(self, content: str, args: dict):
        return SummaryMessageData(
            id=args.get("chunk_id"),
            task_id=args.get("task_id"),
            role="assistant",
            type="summary",
            content=content,
        )

    def special_memory(self):
        return "上一轮任务已经完成，更多的根据用户新的输入完成任务"
