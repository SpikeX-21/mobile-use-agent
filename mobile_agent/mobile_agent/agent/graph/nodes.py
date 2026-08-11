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
from mobile_agent.agent.actions import FailAction, FinishAction
from mobile_agent.agent.llm.provider import ActionParseError
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
    SummaryMessageData,
    UserInterruptMessageData,
)
from mobile_agent.agent.graph.state import MobileUseAgentState
import uuid
from langgraph.config import get_stream_writer
from mobile_agent.agent.graph.context import agent_object_manager
from mobile_agent.agent.mobile.result import (
    ActionResult,
    ActionResultStatus,
    DeviceBackendError,
    DeviceErrorKind,
    classify_device_error,
)

logger = logging.getLogger(__name__)


def _retry_would_exceed_step_limit(state: MobileUseAgentState) -> bool:
    return state.get("iteration_count", 0) >= state.get("max_iterations", 10)


def _set_terminal_failure(
    state: MobileUseAgentState, reason: str, device_backend=None
) -> None:
    failure = FailAction(reason=reason)
    if device_backend is not None:
        try:
            tool_call = device_backend.to_tool_call(
                failure, state.get("screenshot_dimensions") or (1, 1)
            )
        except Exception:
            tool_call = {"name": "call_user", "arguments": {"content": reason}}
    else:
        tool_call = {"name": "call_user", "arguments": {"content": reason}}
    state.update(action=failure, tool_call=tool_call, terminal_reason=reason)
    get_stream_writer()(
        format_sse(
            UserInterruptMessageData(
                id=state.get("chunk_id") or str(uuid.uuid4()),
                task_id=state.get("task_id"),
                role="assistant",
                type="user_interrupt",
                interrupt_type="text",
                content=reason,
            )
        )
    )


async def prepare_node(state: MobileUseAgentState):
    # 初始化上下文管理器
    context_manager = ContextManager(messages=list(state.get("messages", [])))
    thread_id = state.get("thread_id")
    agent_object_manager.add_context_object(
        thread_id, "context_manager", context_manager
    )

    model_provider = agent_object_manager.get_model_provider(thread_id)
    context_manager.add_system_message(model_provider.prompt)

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

    device_backend = agent_object_manager.get_device_backend(state.get("thread_id"))
    model_provider = agent_object_manager.get_model_provider(state.get("thread_id"))
    context_manager = agent_object_manager.get_context_manager(state.get("thread_id"))
    iteration_count = state.get("iteration_count")

    # 获取截图
    try:
        screenshot_state = await device_backend.take_screenshot()
    except DeviceBackendError as exc:
        label = "设备离线" if exc.kind is DeviceErrorKind.OFFLINE else "设备观察失败"
        state.update(terminal_reason=f"{label}：{exc}")
        return state
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

    # 更新步数
    cost_calculator = agent_object_manager.get_cost_calculator(state.get("thread_id"))
    cost_calculator.update_step(iteration_count)

    # 调用模型
    chunk_id, content, summary, tool_call = await model_provider.async_chat(
        context_manager.get_messages()
    )

    logger.info(f"content========: {content}")

    if not state.get("is_stream") or not model_provider.supports_streaming:
        # 请求或模型适配器不支持流式时，直接输出对应 summary。
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
    model_provider = agent_object_manager.get_model_provider(state.get("thread_id"))
    device_backend = agent_object_manager.get_device_backend(state.get("thread_id"))
    if state.get("terminal_reason"):
        _set_terminal_failure(state, state.get("terminal_reason"), device_backend)
        return state
    try:
        action = model_provider.parse_action(tool_call_str)
    except ActionParseError:
        schema_error_count = state.get("schema_error_count", 0) + 1
        if schema_error_count >= 3:
            state.update(schema_error_count=schema_error_count)
            _set_terminal_failure(
                state, "模型动作连续 3 次未通过 Schema 校验", device_backend
            )
            return state
        if _retry_would_exceed_step_limit(state):
            state.update(schema_error_count=schema_error_count)
            _set_terminal_failure(
                state, "任务达到 10 步上限，已安全终止", device_backend
            )
            return state
        state.update(
            action=None,
            schema_error_count=schema_error_count,
            tool_call={"name": "error_action", "arguments": {"content": tool_call_str}},
            tool_output={
                "result": "模型输出解析失败，请尝试重新按照正确的格式生成"
            },
        )
        sse_writer = get_stream_writer()
        sse_writer(
            format_sse(
                SSEThinkMessageData(
                    id=state.get("chunk_id"),
                    task_id=state.get("task_id"),
                    role="assistant",
                    type="think",
                    content="模型输出解析失败，正在尝试重新生成",
                )
            )
        )
        return state

    state.update(schema_error_count=0)
    verify_completion = getattr(device_backend, "verify_completion", None)
    if isinstance(action, FinishAction) and callable(verify_completion):
        if await verify_completion(action) is False:
            oracle_failure_count = state.get("oracle_failure_count", 0) + 1
            if oracle_failure_count >= 2:
                action = FailAction(reason="ADB 独立 Oracle 连续两次未满足完成条件")
                state.update(oracle_failure_count=oracle_failure_count)
            else:
                if _retry_would_exceed_step_limit(state):
                    state.update(oracle_failure_count=oracle_failure_count)
                    _set_terminal_failure(
                        state, "任务达到 10 步上限，已安全终止", device_backend
                    )
                    return state
                state.update(
                    action=None,
                    oracle_failure_count=oracle_failure_count,
                    tool_call={
                        "name": "error_action",
                        "arguments": {"content": "completion oracle not satisfied"},
                    },
                    tool_output={
                        "result": "ADB 独立 Oracle 校验未通过，请根据最新截图继续操作"
                    },
                )
                return state
        else:
            state.update(oracle_failure_count=0)

    try:
        tool_call = device_backend.to_tool_call(
            action, state.get("screenshot_dimensions")
        )
    except (NotImplementedError, TypeError, ValueError) as exc:
        if _retry_would_exceed_step_limit(state):
            _set_terminal_failure(
                state, "任务达到 10 步上限，已安全终止", device_backend
            )
            return state
        state.update(
            action=None,
            tool_call={
                "name": "error_action",
                "arguments": {"content": type(exc).__name__},
            },
            tool_output={
                "result": "当前设备后端不支持该动作，请仅使用已声明的动作重新生成"
            },
        )
        return state
    state.update(action=action, tool_call=tool_call)

    if isinstance(action, FinishAction):
        sse_writer = get_stream_writer()
        sse_writer(
            format_sse(
                SummaryMessageData(
                    id=state.get("chunk_id"),
                    task_id=state.get("task_id"),
                    role="assistant",
                    type="summary",
                    content=action.summary,
                )
            )
        )
        state.update(tool_output="上一轮任务已经完成，更多的根据用户新的输入完成任务")
    elif isinstance(action, FailAction):
        sse_writer = get_stream_writer()
        sse_writer(
            format_sse(
                UserInterruptMessageData(
                    id=state.get("chunk_id"),
                    task_id=state.get("task_id"),
                    role="assistant",
                    type="user_interrupt",
                    interrupt_type="text",
                    content=action.reason,
                )
            )
        )
        state.update(tool_output="根据新提供的信息继续执行任务")

    return state


async def tool_node(state: MobileUseAgentState) -> MobileUseAgentState:
    """工具执行节点，执行工具调用"""
    # 检查 sse 链接是否断开
    if agent_object_manager.get_sse_connection(state.get("thread_id")).is_set():
        logger.info("tool_node start, sse 断开链接")
        raise SSEException()

    tool_call = state.get("tool_call")
    action = state.get("action")
    sse_writer = get_stream_writer()
    # 写工具 input
    sse_writer(get_writer_tool_input(state, tool_call))

    logger.info(f"tool_call========: {tool_call}")
    action_result: ActionResult
    device_backend = agent_object_manager.get_device_backend(state.get("thread_id"))
    try:
        raw_result = await device_backend.execute(
            action, state.get("screenshot_dimensions")
        )
        action_result = (
            raw_result
            if isinstance(raw_result, ActionResult)
            else ActionResult.success(str(raw_result))
        )
    except TimeoutError:
        action_result = ActionResult.ambiguous(
            "设备动作超时，结果不确定", DeviceErrorKind.TIMEOUT
        )
    except Exception as exc:
        logger.error(f"tool_call_client.call error: {exc}")
        error_kind = classify_device_error(exc)
        action_result = ActionResult.failed(str(exc), error_kind)

    output = {
        "status": action_result.status.value,
        "error_kind": (
            action_result.error_kind.value if action_result.error_kind else None
        ),
        "result": action_result.message,
    }
    state.update(tool_output=output)

    if action_result.status is ActionResultStatus.SUCCESS:
        await asyncio.sleep(state.get("step_interval"))
        sse_writer(get_writer_tool_output(state, tool_call, output, status="success"))
    else:
        sse_writer(get_writer_tool_output(state, tool_call, output, status="stop"))

    if action_result.error_kind is DeviceErrorKind.OFFLINE:
        _set_terminal_failure(
            state, f"设备离线：{action_result.message}", device_backend
        )
    elif state.get("iteration_count", 0) >= state.get("max_iterations", 10):
        _set_terminal_failure(
            state, "任务达到 10 步上限，已安全终止", device_backend
        )

    logger.info(f"tool_output========: {state.get('tool_output')}")

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

    if (
        isinstance(state.get("action"), FailAction)
        or iteration_count >= max_iterations
    ):
        return "finish"

    # 否则继续执行
    return "continue"


async def should_tool_exec_continue(state: MobileUseAgentState) -> str:
    """条件边，决定是否继续执行"""
    action = state.get("action")
    # 工具解析失败，重新生成action
    if action is None:
        return "retry"

    if isinstance(action, (FinishAction, FailAction)):
        return "finish"

    # 工具执行成功，继续执行
    return "continue"
