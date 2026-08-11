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

from typing import Literal, Optional
from pydantic import BaseModel


class MessageMeta(BaseModel):
    finish_reason: Optional[str] = None
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class SSEContentMessageData(BaseModel):
    id: str
    task_id: str
    role: str
    content: str
    response_meta: Optional[MessageMeta] = None


class SSEThinkMessageData(SSEContentMessageData):
    type: Literal["think"]


class UserInterruptMessageData(SSEContentMessageData):
    type: Literal["user_interrupt"]
    interrupt_type: Literal["text"]


class SummaryMessageData(SSEContentMessageData):
    type: Literal["summary"]


class SSEToolCallMessageData(BaseModel):
    id: str
    task_id: str
    tool_id: str
    type: Literal["tool"]
    status: Literal["start", "stop", "success"]
    tool_type: Literal["tool_input", "tool_output"]
    tool_name: str
    tool_input: Optional[str] = None
    tool_output: Optional[str] = None
