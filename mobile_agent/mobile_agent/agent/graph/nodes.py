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

import asyncio
import logging
from mobile_agent.exception.sse import SSEException
from mobile_agent.agent.memory.context_manager import ContextManager
from mobile_agent.agent.graph.sse_output import (
    format_sse,
    get_writer_think,
    get_writer_tool_input,
    get_writer_tool_output,
)
from mobile_agent.agent.infra.message_web import (
    SSEThinkMessageData,
)
from mobile_agent.agent.graph.state import MobileUseAgentState
import uuid
from langgraph.config import get_stream_writer
from mobile_agent.agent.llm.doubao import DoubaoLLM
from mobile_agent.agent.graph.context import agent_object_manager

logger = logging.getLogger(__name__)


async def prepare_node(state: MobileUseAgentState):
    # 初始化上下文管理器
    context_manager = ContextManager(messages=list(state.get("messages", [])))
    thread_id = state.get("thread_id")
    agent_object_manager.add_context_object(
        thread_id, "context_manager", context_manager
    )

    context_manager.add_system_message(DoubaoLLM.prompt)

    # FIXME: 临时给一个深度思考的提示，langchain-openai 没有把豆包的think 吐出来，需要替换为 langchain-deepseek
    sse_writer = get_stream_writer()
    sse_writer(
        format_sse(
            SSEThinkMessageData(
                id=str(uuid.uuid4()),
                task_id=state.get("task_id"),
                role="assistant",
                type="think",
                content="深度思考中...",
            )
        )
    )
    # 更新消息
    state.update(messages=context_manager.get_messages())
    return state


async def model_node(state: MobileUseAgentState) -> MobileUseAgentState:
    """大模型节点，根据当前状态计算行动和工具调用"""

    mobile = agent_object_manager.get_mobile_client(state.get("thread_id"))
    context_manager = agent_object_manager.get_context_manager(state.get("thread_id"))
    iteration_count = state.get("iteration_count")

    # 获取截图
    screenshot_state = await mobile.take_screenshot()
    state.update(screenshot=screenshot_state.get("screenshot"))
    state.update(screenshot_dimensions=screenshot_state.get("screenshot_dimensions"))

    # 准备消息
    if iteration_count == 0:
        context_manager.add_user_initial_message(
            message=state.get("user_prompt"), screenshot_url=state.get("screenshot")
        )
    else:
        context_manager.add_user_iteration_message(
            message=state.get("user_prompt"),
            iteration_count=iteration_count,
            tool_output=state.get("tool_output"),
            screenshot_url=state.get("screenshot"),
            screenshot_dimensions=state.get("screenshot_dimensions"),
        )

    # 保留最后5张图片
    context_manager.keep_last_n_images_in_messages(5)
    state.update(messages=context_manager.get_messages())

    # 调用模型并处理重试
    llm = DoubaoLLM(thread_id=state.get("thread_id"), is_stream=state.get("is_stream"))

    # 更新步数
    cost_calculator = agent_object_manager.get_cost_calculator(state.get("thread_id"))
    cost_calculator.update_step(iteration_count)

    # 调用模型
    chunk_id, content, summary, tool_call = await llm.async_chat(
        context_manager.get_messages()
    )

    logger.info(f"content========: {content}")

    if not state.get("is_stream"):
        # 非流式传输直接突出对应的summary
        sse_writer = get_stream_writer()
        sse_writer(get_writer_think(state, chunk_id, summary))

    # 更新状态
    context_manager.add_ai_message(content)

    state.update(
        tool_call_str=tool_call,
        iteration_count=iteration_count + 1,
        chunk_id=chunk_id,
        messages=context_manager.get_messages(),
    )

    return state


async def tool_valid_node(state: MobileUseAgentState) -> MobileUseAgentState:
    """工具验证节点，验证工具调用是否有效"""
    tool_call_str = state.get("tool_call_str")
    action_parser = agent_object_manager.get_action_parser(state.get("thread_id"))
    action_parser.change_phone_dimensions(
        width=state.get("screenshot_dimensions")[0],
        height=state.get("screenshot_dimensions")[1],
    )
    tool_call = action_parser.to_mcp_tool_call(tool_call_str)
    state.update(tool_call=tool_call)

    tools = agent_object_manager.get_tools(state.get("thread_id"))
    tool_name = tool_call.get("name")

    if tools.is_special_tool(tool_name):
        sse_writer = get_stream_writer()
        content = await tools.exec(tool_call)
        sse_writer(format_sse(tools.get_special_message(tool_name, content, state)))
        state.update(tool_output=tools.get_special_memory(tool_name))
        return state

    return state


async def tool_node(state: MobileUseAgentState) -> MobileUseAgentState:
    """工具执行节点，执行工具调用"""
    # 检查 sse 链接是否断开
    if agent_object_manager.get_sse_connection(state.get("thread_id")).is_set():
        logger.info("tool_node start, sse 断开链接")
        raise SSEException()

    tool_call = state.get("tool_call")
    sse_writer = get_stream_writer()
    # 写工具 input
    sse_writer(get_writer_tool_input(state, tool_call))

    logger.info(f"tool_call========: {tool_call}")
    # 检查特殊工具
    try:
        tools = agent_object_manager.get_tools(state.get("thread_id"))
        result = await tools.exec(tool_call)
        output = {
            "result": f"{tool_call['name']}:({tool_call['arguments']})\n{result}\n操作下发成功"
        }
        state.update(tool_output=output)
        # 等待操作完成
        await asyncio.sleep(state.get("step_interval"))

    except Exception as e:
        logger.error(f"tool_call_client.call error: {e}")
        output = {"result": f"Error: {str(e)}"}
        sse_writer((get_writer_tool_output(state, tool_call, output, status="stop")))
        state.update(tool_output=output)

    logger.info(f"tool_output========: {state.get('tool_output')}")

    # 写工具 output
    sse_writer(get_writer_tool_output(state, tool_call, output, status="success"))

    return state


def handle_parse_failure(state: MobileUseAgentState) -> bool:
    tool_call = state.get("tool_call")

    # 检查是否是解析失败的情况
    if not tool_call or (
        isinstance(tool_call, dict) and tool_call.get("name") == "error_action"
    ):
        iteration_count = state.get("iteration_count", 0)
        max_iterations = state.get("max_iterations")

        # 如果还没达到最大迭代次数，可以重试
        if iteration_count < max_iterations:
            return True

    return False


async def should_react_continue(state: MobileUseAgentState) -> str:
    """条件边，决定是否继续执行"""
    # 检查是否达到最大迭代次数
    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get(
        "max_iterations",
    )

    if iteration_count >= max_iterations:
        return "finish"

    # 否则继续执行
    return "continue"


async def should_tool_exec_continue(state: MobileUseAgentState) -> str:
    """条件边，决定是否继续执行"""
    tool_call = state.get("tool_call")
    # 工具解析失败，重新生成action
    if not tool_call or tool_call.get("name") == "error_action":
        return "retry"

    tools = agent_object_manager.get_tools(state.get("thread_id"))
    if tools.is_special_tool(tool_call.get("name")):
        return "finish"

    # 工具执行成功，继续执行
    return "continue"
