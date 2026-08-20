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
from pathlib import Path
import time
from typing import Callable
import uuid
from mobile_agent.agent.cost.calculator import CostCalculator
from mobile_agent.agent.llm.provider import (
    ModelProvider,
    create_model_provider,
)
from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.agent.mobile.backend import (
    DeviceBackend,
    create_device_backend,
)
from .infra.logger import AgentLogger
from mobile_agent.config.settings import get_agent_config, get_settings
from mobile_agent.agent.graph.builder import graph
from mobile_agent.agent.graph.context import agent_object_manager
from mobile_agent.agent.experiments.records import (
    ExperimentRun,
    JsonlExperimentRecorder,
)
from mobile_agent.agent.mobile.result import classify_device_error
from mobile_agent.exception.sse import SSEException
from mobile_agent.agent.run_result import AgentRunResult, AgentRunState


class MobileUseAgent:
    name = "mobile_use"

    def __init__(
        self,
        *,
        model_provider_name: str | None = None,
        device_provider_name: str | None = None,
        model_provider_factory: Callable[..., ModelProvider] = create_model_provider,
        device_backend_factory: Callable[..., DeviceBackend] = create_device_backend,
        agent_graph=graph,
        experiment_record_path: str | Path | None = None,
    ):
        self.logger = AgentLogger(__name__)

        agent_config = get_agent_config(MobileUseAgent.name)
        settings = get_settings()
        self.logger.info(f"agent_config: {agent_config}")

        self.max_steps = min(agent_config.max_steps, 10)
        self.step_interval = agent_config.step_interval
        self.model_provider_name = model_provider_name or settings.model_provider
        self.device_provider_name = device_provider_name or settings.device_provider
        self._model_provider_factory = model_provider_factory
        self.device_backend = device_backend_factory(self.device_provider_name)
        self._graph = agent_graph
        self.experiment_record_path = Path(
            experiment_record_path or settings.experiment_record_path
        )
        self.cost_calculator = CostCalculator(MobileUseAgent.name)
        self.last_terminal_reason: str | None = None
        self.last_run_result: AgentRunResult | None = None

    def get_last_run_result(
        self,
        *,
        elapsed_ms: int | None = None,
    ) -> AgentRunResult | None:
        """Return the public business outcome of the most recent run."""

        if self.last_run_result is not None:
            if elapsed_ms is None:
                return self.last_run_result
            return AgentRunResult(
                status=self.last_run_result.status,
                task_id=self.last_run_result.task_id,
                thread_id=self.last_run_result.thread_id,
                session_id=self.last_run_result.session_id,
                result=self.last_run_result.result,
                rounds=self.last_run_result.rounds,
                elapsed_ms=max(0, elapsed_ms),
                terminal_reason=self.last_run_result.terminal_reason,
            )
        return None

    async def initialize(
        self,
        pod_id: str,
        auth_token: str,
        product_id: str,
        tos_bucket: str,
        tos_region: str,
        tos_endpoint: str,
    ):
        """异步初始化方法，子类可以覆盖此方法进行异步初始化

        该方法默认返回self，允许链式调用
        """
        self.logger.set_context(pod_id=pod_id)
        await self.device_backend.initialize(
            pod_id=pod_id,
            product_id=product_id,
            tos_bucket=tos_bucket,
            tos_region=tos_region,
            tos_endpoint=tos_endpoint,
            auth_token=auth_token,
        )
        return self

    async def aclose(self) -> None:
        await self.device_backend.close()

    async def run(
        self,
        query: str,
        is_stream: bool,
        task_id: str,
        session_id: str,
        thread_id: str,
        sse_connection: asyncio.Event,
        phone_width: int,
        phone_height: int,
    ):
        run_id = str(uuid.uuid4())
        recorder = JsonlExperimentRecorder(self.experiment_record_path)
        experiment_run: ExperimentRun | None = None
        run_state = AgentRunState(
            task_id=task_id,
            thread_id=thread_id,
            session_id=session_id,
        )
        self.last_run_result = None
        self.last_terminal_reason = None
        self.logger.set_context(thread_id=session_id, chat_thread_id=thread_id)
        self.task_id = task_id
        self.stream = is_stream
        try:
            initial_state = {
                "user_prompt": query,
                "iteration_count": 0,
                "task_id": task_id,
                "thread_id": thread_id,
                "is_stream": is_stream,
                "max_iterations": self.max_steps,
                "oracle_failure_count": 0,
                "schema_error_count": 0,
                "terminal_reason": None,
                "experiment_terminal_reason": None,
                "experiment_error_kind": None,
                "experiment_action_type": None,
                "model_latency_ms": 0,
                "observation_images_used": 0,
                "step_interval": self.step_interval,
            }

            def record_provider_failure() -> None:
                fallback_run = ExperimentRun(
                    recorder=recorder,
                    query=query,
                    provider="unknown",
                    model="unknown",
                    device_provider=str(
                        getattr(self.device_backend, "name", "unknown")
                    ),
                    run_id=run_id,
                )
                fallback_run.try_record_terminal_once("runtime_failed")

            try:
                model_provider = self._model_provider_factory(
                    self.model_provider_name,
                    thread_id=thread_id,
                    is_stream=is_stream,
                )
            except ProviderConfigurationError:
                run_state.fail("provider_configuration")
                record_provider_failure()
                raise
            except Exception:
                run_state.fail("runtime_failed")
                record_provider_failure()
                raise
            experiment_run = ExperimentRun(
                recorder=recorder,
                query=query,
                provider=model_provider.name,
                model=str(getattr(model_provider, "model", "unknown")),
                device_provider=self.device_backend.name,
                run_id=run_id,
            )
            agent_object_manager.create_context(
                thread_id=thread_id,
                model_provider=model_provider,
                device_backend=self.device_backend,
                sse_connection=sse_connection,
                cost_calculator=self.cost_calculator,
                experiment_run=experiment_run,
                run_state=run_state,
            )

            prepare_task = getattr(self.device_backend, "prepare_task", None)
            if callable(prepare_task):
                prepare_started = time.perf_counter()
                try:
                    await prepare_task(query)
                except asyncio.CancelledError:
                    run_state.fail("cancelled")
                    raise
                except Exception as exc:
                    run_state.fail("prepare_failed")
                    error_kind = classify_device_error(exc)
                    experiment_run.try_record_step(
                        step_number=1,
                        action=None,
                        action_type="prepare",
                        model_latency_ms=0,
                        device_latency_ms=max(
                            0,
                            round(
                                (time.perf_counter() - prepare_started) * 1000
                            ),
                        ),
                        action_status="failed",
                        device_error_kind=error_kind.value,
                        schema_status="not_evaluated",
                        terminal_reason="prepare_failed",
                        observation_images_used=0,
                    )
                    raise

            config = {
                "configurable": {"thread_id": thread_id},
                # prepare + 每轮 model/tool_valid/tool + 结束路由需要额外余量。
                "recursion_limit": self.max_steps * 3 + 2,
            }

            async for chunk in self._graph.astream(
                input=initial_state,
                config=config,
                stream_mode=["messages", "custom"],
            ):
                yield chunk
        except asyncio.CancelledError:
            run_state.fail("cancelled")
            if experiment_run is not None:
                experiment_run.try_record_terminal_once("cancelled")
            raise
        except SSEException:
            run_state.fail("client_disconnected")
            if experiment_run is not None:
                experiment_run.try_record_terminal_once("client_disconnected")
            raise
        except GeneratorExit:
            run_state.fail("client_disconnected")
            if experiment_run is not None:
                experiment_run.try_record_terminal_once("client_disconnected")
            raise
        except Exception:
            run_state.fail("runtime_failed")
            if experiment_run is not None:
                experiment_run.try_record_terminal_once("runtime_failed")
            raise
        finally:
            if run_state.terminal_reason is None:
                run_state.fail("runtime_failed")
            self.last_run_result = run_state.to_result()
            self.last_terminal_reason = self.last_run_result.terminal_reason
            if experiment_run is not None:
                experiment_run.try_record_terminal_once("runtime_ended")
            if self.stream:
                self.logger.info("stream mode, not support cost calculator")
            else:
                self.cost_calculator.print_cost()
            agent_object_manager.destroy_context(thread_id)
