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

from typing import Dict, Optional
from pydantic import BaseModel
import re


class StreamPipeMessage(BaseModel):
    id: str
    content: str
    summary: str
    tool_call: str
    summary_collected: bool
    last_summary_length: int = 0


class StreamPipe:
    # Summary: 总结
    # Action:
    pipes: Dict[str, StreamPipeMessage]

    def __init__(self):
        self.pipes = {}

    def create(self, id: str):
        self.pipes[id] = StreamPipeMessage(
            id=id,
            content="",
            summary="",
            tool_call="",
            summary_collected=False,
            last_summary_length=0,
        )

    def pipe(self, id: str, delta: str):
        chat_data = self.pipes[id]
        chat_data.content += delta
        # delta
        # 1. Summ
        # 2. mary:
        # 3. 现在我们
        # 4. bac
        # content 有下面这几种情况:
        # 1. Summ                                            (Summary 关键词正在生成中)
        # 2. Summary:                                        (Summary 关键词已完成但内容为空)
        # 3. Summary: 现在我们需要点击抖音图标                  (Summary 内容部分生成)
        # 4. Summary: 现在我们需要点击抖音图标\n               (Summary 内容已完成，带换行符)
        # 5. Summary: 现在我们需要点击抖音图标\nActi           (Action 关键词正在生成中)
        # 6. Summary: 现在我们需要点击抖音图标\nAction: ba     (Action 内容部分生成)
        # 7. Summary: 现在我们需要点击抖音图标\nAction: press_back() (Action 内容已完成)

        # 检查是否可能是 Action 关键词正在生成中
        is_action_keyword_partial = False
        if not chat_data.summary_collected and "\n" in chat_data.content:
            # 检查最后一行是否可能是 Action 关键词的开始部分
            last_line = chat_data.content.split("\n")[-1]
            # 检查是否以 A, Ac, Act, Acti, Actio, Action 开头，但不是完整的 "Action:"
            action_prefixes = ["A", "Ac", "Act", "Acti", "Actio", "Action"]
            if any(
                last_line.startswith(prefix) for prefix in action_prefixes
            ) and not last_line.startswith("Action:"):
                is_action_keyword_partial = True

        # 检查是否是 Summary 部分的内容
        if "Summary:" in chat_data.content:
            current_summary = ""
            summary_text = chat_data.content.split("Summary:")[1]

            # 如果 Summary 后面还有 Action，只保留 Summary 部分
            if "\nAction:" in summary_text:
                summary_text = summary_text.split("\nAction:")[0]
                chat_data.summary_collected = (
                    True  # 如果已经有完整的 Action 关键词，则 Summary 肯定已完成
                )

            # 处理 Action 关键词不完整的情况
            elif is_action_keyword_partial and "\n" in summary_text:
                # 取最后一个换行符之前的内容作为 summary
                summary_text = summary_text.split("\n")[0]
                chat_data.summary_collected = (
                    True  # 标记 Summary 已完成，因为已经开始生成 Action
                )

            current_summary = summary_text.strip()

            # 如果有 Summary 内容的更新，且有回调函数，则调用回调
            if len(current_summary) > chat_data.last_summary_length:
                # 计算新增的 delta 部分
                summary_delta = current_summary[chat_data.last_summary_length :]
                # 检查新增部分是否包含 \n 后面跟着 A、Ac、Act 等（Action关键词的开始部分）
                if "\n" in summary_delta:
                    # 如果有换行，只保留换行符前面的部分
                    # :\nAction
                    parts = summary_delta.split("\n", 1)
                    summary_delta = parts[0]  # 只保留第一部分，去除换行符及后面内容
                chat_data.last_summary_length = len(current_summary)
                return id, summary_delta

            # 更新 summary 字段（如果尚未收集完成）
            if not chat_data.summary_collected:
                chat_data.summary = current_summary
                # 如果发现有 \n 或 \nAction，则标记为收集完成
                if (delta == "\n" and len(summary_text.strip()) > 0) or (
                    len(summary_text) > 0 and summary_text[-1] == "\n"
                ):
                    chat_data.summary_collected = True

        # 不管 summary 是否已收集，都要检查 Action
        if "Action:" in chat_data.content:
            # 提取 Action 部分
            action_text = chat_data.content.split("Action:")[1].strip()
            chat_data.tool_call = action_text

    def complete(self, id: str):
        if id not in self.pipes:
            # 如果找不到对应的pipe，返回重试
            return self.error_action()

        chat_data = self.pipes[id].model_dump()

        content = chat_data.get("content", "")
        summary = chat_data.get("summary", "")
        tool_call = chat_data.get("tool_call", "")


        # 如果summary 或 tool_call为空，返回重试
        if not summary or not tool_call:
            return self.error_action(id)

        self.pipes.pop(id, None)
        return content, summary, tool_call

    def error_action(self, id: Optional[str] = None) -> tuple[str, str, str]:
        if id and id in self.pipes:
            content = self.pipes[id].content
            self.pipes.pop(id, None)
        else:
            content = ""
        tool_call = "error_action()"
        return content, "解析失败，未找到对应的动作, 请重新遵循格式输出", tool_call


stream_pipeline = StreamPipe()
