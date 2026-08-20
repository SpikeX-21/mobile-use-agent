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

from typing import TYPE_CHECKING, Dict, Literal, Optional
import asyncio
from mobile_agent.agent.cost.calculator import CostCalculator
from mobile_agent.agent.memory.context_manager import ContextManager

if TYPE_CHECKING:
    from mobile_agent.agent.experiments.records import ExperimentRun
    from mobile_agent.agent.llm.provider import ModelProvider
    from mobile_agent.agent.mobile.backend import DeviceBackend
    from mobile_agent.agent.run_result import AgentRunState


class AgentObjectManager:
    """管理与thread_id相关的不可序列化对象"""

    def __init__(self):
        self._contexts: Dict[str, Dict] = {}

    def create_context(
        self,
        thread_id: str,
        model_provider: "ModelProvider",
        device_backend: "DeviceBackend",
        sse_connection: asyncio.Event,
        cost_calculator: CostCalculator,
        experiment_run: "ExperimentRun",
        run_state: "AgentRunState | None" = None,
    ):
        """为特定thread_id创建上下文"""
        self._contexts[thread_id] = {
            "model_provider": model_provider,
            "device_backend": device_backend,
            "sse_connection": sse_connection,
            "cost_calculator": cost_calculator,
            "experiment_run": experiment_run,
            "run_state": run_state,
        }

    def add_context_object(
        self, thread_id: str, key: Literal["context_manager"], value: ContextManager
    ):
        if not self.has_context(thread_id):
            return
        if key in self._contexts[thread_id]:
            return
        self._contexts[thread_id][key] = value

    def get_context_manager(self, thread_id: str) -> Optional[ContextManager]:
        return self._contexts.get(thread_id, {}).get("context_manager")

    def get_model_provider(self, thread_id: str) -> Optional["ModelProvider"]:
        return self._contexts.get(thread_id, {}).get("model_provider")

    def get_device_backend(self, thread_id: str) -> Optional["DeviceBackend"]:
        return self._contexts.get(thread_id, {}).get("device_backend")

    def get_sse_connection(self, thread_id: str) -> Optional[asyncio.Event]:
        return self._contexts.get(thread_id, {}).get("sse_connection")

    def get_cost_calculator(self, thread_id: str) -> Optional[CostCalculator]:
        return self._contexts.get(thread_id, {}).get("cost_calculator")

    def get_experiment_run(self, thread_id: str) -> Optional["ExperimentRun"]:
        return self._contexts.get(thread_id, {}).get("experiment_run")

    def get_run_state(self, thread_id: str) -> Optional["AgentRunState"]:
        return self._contexts.get(thread_id, {}).get("run_state")

    def destroy_context(self, thread_id: str):
        """清理特定thread_id的上下文"""
        if thread_id in self._contexts:
            self._contexts.pop(thread_id)
            # 暂时没有需要清理的 object

    def has_context(self, thread_id: str) -> bool:
        return thread_id in self._contexts


# 全局实例
agent_object_manager = AgentObjectManager()
