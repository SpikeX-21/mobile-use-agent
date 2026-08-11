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

import json
import uuid
from pydantic import BaseModel

from mobile_agent.agent.infra.message_web import (
    SSEThinkMessageData,
    SSEToolCallMessageData,
)
from mobile_agent.agent.llm.stream_pipe import stream_pipeline
from mobile_agent.agent.graph.state import MobileUseAgentState
from mobile_agent.agent.infra.model import ToolCall


def format_sse(data: dict | BaseModel | None = None, **kwargs) -> str:
    if isinstance(data, BaseModel):
        data = data.model_dump()
    else:
        if not data:
            data = {}
        data.update(kwargs)
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_messages(update, is_stream: bool, task_id: str):
    # 处理字符串类型的消息（GUI代理返回的SSE格式消息）
    if isinstance(update, str) and update.startswith("data: "):
        # 直接返回已经格式化好的SSE消息
        yield update
        return

    eventType = update[0]
    if eventType == "custom":
        yield update[1]
        return
    elif eventType == "messages":
        if not is_stream:
            return
        if isinstance(update, tuple) and len(update) == 2:
            mode, data = update
            message_chunk, metadata = data
            if (
                message_chunk.content
                and metadata.get("langgraph_node") == "model"
                and message_chunk.type == "AIMessageChunk"
            ):
                pipe_result = stream_pipeline.pipe(
                    id=message_chunk.id,
                    delta=message_chunk.content,
                )
                if not pipe_result:
                    return
                (id, delta) = pipe_result
                if not delta:
                    return
                yield format_sse(
                    SSEThinkMessageData(
                        id=id,
                        task_id=task_id,
                        role="assistant",
                        type="think",
                        content=delta,
                    )
                )
        return
    else:
        yield f"Unknown event type: {eventType}"


def get_writer_tool_input(state: MobileUseAgentState, tool_call: ToolCall):
    state.update(current_tool_call_id=str(uuid.uuid4()))
    return format_sse(
        SSEToolCallMessageData(
            id=state.get("chunk_id"),
            task_id=state.get("task_id"),
            tool_id=state.get("current_tool_call_id"),
            type="tool",
            tool_type="tool_input",
            tool_name=tool_call["name"],
            tool_input=json.dumps(tool_call["arguments"], ensure_ascii=False),
            status="start",
        )
    )


def get_writer_tool_output(
    state: MobileUseAgentState, tool_call: ToolCall, output, status
):
    current_tool_call_id = state.get("current_tool_call_id")
    if current_tool_call_id:
        state.update(current_tool_call_id="")

        return format_sse(
            SSEToolCallMessageData(
                id=state.get("chunk_id"),
                task_id=state.get("task_id"),
                tool_id=current_tool_call_id,
                type="tool",
                tool_type="tool_output",
                tool_name=tool_call["name"],
                tool_input=json.dumps(tool_call["arguments"], ensure_ascii=False),
                tool_output=json.dumps(output["result"], ensure_ascii=False),
                status=status,
            )
        )


def get_writer_think(state: MobileUseAgentState, chunk_id: str, summary: str):
    return format_sse(
        SSEThinkMessageData(
            id=chunk_id,
            task_id=state.get("task_id"),
            role="assistant",
            type="think",
            content=summary,
        )
    )
