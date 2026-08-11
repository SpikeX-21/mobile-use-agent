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

from langgraph.graph import END, StateGraph

from mobile_agent.agent.graph.state import MobileUseAgentState
from mobile_agent.agent.graph.nodes import (
    model_node,
    should_react_continue,
    should_tool_exec_continue,
    tool_node,
    prepare_node,
    tool_valid_node,
)
from mobile_agent.agent.memory.saver import checkpointer


def create_mobile_agent():
    """创建代理"""
    # 创建状态图
    workflow = StateGraph(MobileUseAgentState)

    workflow.add_node("prepare", prepare_node)
    workflow.set_entry_point("prepare")  # 设置入口节点

    # 添加三个核心节点
    workflow.add_node("model", model_node)  # 大模型节点，计算action和tool
    workflow.add_node("tool_valid", tool_valid_node)  # 工具验证节点
    workflow.add_node("tool", tool_node)  # 工具执行节点

    # 设置节点之间的边
    workflow.add_edge("prepare", "model")
    workflow.add_edge("model", "tool_valid")

    # 设置条件边
    workflow.add_conditional_edges(
        "tool_valid",
        should_tool_exec_continue,
        {
            "continue": "tool",  # 继续下一轮
            "finish": END,  # 任务完成
            "retry": "model",  # 工具解析失败，重新生成action
        },
    )

    workflow.add_conditional_edges(
        "tool",
        should_react_continue,
        {
            "continue": "model",  # 继续下一轮
            "finish": END,  # 任务完成
        },
    )

    # 编译状态图
    return workflow.compile(name="mobile_use_agent", checkpointer=checkpointer)


graph = create_mobile_agent()

if __name__ == "__main__":
    print(graph.get_graph().draw_mermaid())
