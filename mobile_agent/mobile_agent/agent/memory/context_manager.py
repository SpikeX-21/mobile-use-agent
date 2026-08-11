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

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
)
from openai.types.chat.chat_completion_content_part_image_param import ImageURL
from datetime import datetime

from mobile_agent.agent.memory.messages import AgentMessages


class ContextManager:
    def __init__(self, messages: list[BaseMessage]):
        self._messages = AgentMessages(messages)

    def _append(self, message: BaseMessage):
        self._messages.append(message)

    def get_messages(self):
        return self._messages.get_messages()

    def length(self):
        return self._messages.length()

    def add_system_message(self, message: str):
        """系统消息"""
        system_message = SystemMessage(content=message)
        if self._messages.length() > 0 and self._messages.index(0).type == "system":
            self._messages.replace(0, system_message)
        else:
            self._messages.insert(0, system_message)

    def add_user_initial_message(self, message: str, screenshot_url: str):
        """初始消息"""
        user_content = f"当前时间点 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ，用户任务: {message}\n请帮我完成任务"
        self._append(
            ContextManager.get_snapshot_user_prompt(
                url=screenshot_url, user_content=user_content
            )
        )

    def add_user_iteration_message(
        self,
        message: str,
        iteration_count: int,
        tool_output: str,
        screenshot_url: str,
        screenshot_dimensions: tuple,
    ):
        """
        ReAct 迭代中的消息
        """
        user_content = (
            f"当前轮次迭代次数 {iteration_count}\n"
            f"用户任务: {message}\n"
            f"当前轮次工具下发结果: {tool_output}， "
            f"请观察截图， 当前截图分辨率为 {screenshot_dimensions[0]}x{screenshot_dimensions[1]} 并根据截图和工具下发结果 \n"
        )
        self._append(
            ContextManager.get_snapshot_user_prompt(
                url=screenshot_url, user_content=user_content
            )
        )

    def add_ai_message(self, content: str):
        """添加AI消息"""
        self._append(AIMessage(role="assistant", content=content))

    def keep_last_n_images_in_messages(self, keep_n: int):
        """保留最后n张图片URL"""
        # 收集所有图片URL及其信息
        all_image_parts = []
        messages = self._messages.get_messages()
        for msg in messages:
            if msg.type == "human" and isinstance(msg.content, list):
                for i, part in enumerate(msg.content):
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        # 保存消息和图片在消息中的索引
                        all_image_parts.append((msg, part, i))
        # 计算需要保留的图片数量
        total_images = len(all_image_parts)
        # 如果图片总数小于等于keep_n，不需要删除
        if total_images <= keep_n:
            return
        # 计算需要删除的图片数量
        to_remove_count = total_images - keep_n
        # 删除旧的图片URL（从前往后删除）
        for i in range(to_remove_count):
            msg, part, _ = all_image_parts[i]
            if part in msg.content:
                msg.content.remove(part)

        self._messages.replace_all(messages)


    @staticmethod
    def get_snapshot_user_prompt(url: str, user_content: str) -> HumanMessage:
        # 添加截图消息
        snap_content = ChatCompletionContentPartImageParam(
            image_url=ImageURL(url=url), type="image_url"
        )
        #  UserPrompt
        user_message = ChatCompletionContentPartTextParam(
            text=user_content, type="text"
        )
        screenshot_message = HumanMessage(
            role="user", content=[snap_content, user_message]
        )
        return screenshot_message
