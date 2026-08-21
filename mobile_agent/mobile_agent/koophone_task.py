# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Reusable structured KooPhone task entry point.

This module deliberately contains orchestration only.  The model prompt,
LangGraph loop, canonical actions and KooPhone backend remain owned by
``MobileUseAgent`` and are not duplicated here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import time
import uuid

from mobile_agent.agent.mobile_use_agent import MobileUseAgent
from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.agent.run_result import AgentRunResult


AgentFactory = Callable[..., MobileUseAgent]


def _fallback_result(
    *,
    status: str,
    task_id: str,
    thread_id: str,
    session_id: str,
    terminal_reason: str,
    elapsed_ms: int,
) -> AgentRunResult:
    normalized_status = "cancelled" if status == "cancelled" else "failed"
    return AgentRunResult(
        status=normalized_status,
        task_id=task_id,
        thread_id=thread_id,
        session_id=session_id,
        result=None,
        rounds=0,
        elapsed_ms=max(0, elapsed_ms),
        terminal_reason=terminal_reason,
    )


async def run_koophone_task(
    prompt: str,
    *,
    agent_factory: AgentFactory = MobileUseAgent,
    task_id: str | None = None,
    thread_id: str | None = None,
    session_id: str = "koophone-runtime",
    propagate_cancellation: bool = False,
) -> AgentRunResult:
    """Run one fresh Kimi + KooPhone task and return its business outcome.

    The caller receives a result for configuration, device, model, runtime and
    cancellation failures instead of having to infer state from log output or
    experiment JSONL.  The Agent is always closed once when it was created.
    ``propagate_cancellation`` is reserved for an outer deadline/cancellation
    boundary that must observe ``CancelledError`` while preserving the default
    structured-cancellation behavior for existing callers.
    """

    started_at = time.perf_counter()
    resolved_task_id = task_id or f"koophone-task-{uuid.uuid4()}"
    resolved_thread_id = thread_id or f"koophone-thread-{uuid.uuid4()}"
    agent: MobileUseAgent | None = None
    terminal_reason = "runtime_failed"
    cancelled = False

    try:
        try:
            agent = agent_factory(
                model_provider_name="kimi",
                device_provider_name="koophone_mcp",
            )
        except ProviderConfigurationError:
            terminal_reason = "provider_configuration"
            return _fallback_result(
                status="failed",
                task_id=resolved_task_id,
                thread_id=resolved_thread_id,
                session_id=session_id,
                terminal_reason=terminal_reason,
                elapsed_ms=round((time.perf_counter() - started_at) * 1000),
            )
        except Exception:
            terminal_reason = "runtime_failed"
            return _fallback_result(
                status="failed",
                task_id=resolved_task_id,
                thread_id=resolved_thread_id,
                session_id=session_id,
                terminal_reason=terminal_reason,
                elapsed_ms=round((time.perf_counter() - started_at) * 1000),
            )

        try:
            await agent.initialize("", "", "", "", "", "")
            async for _ in agent.run(
                prompt,
                is_stream=False,
                task_id=resolved_task_id,
                session_id=session_id,
                thread_id=resolved_thread_id,
                sse_connection=asyncio.Event(),
                phone_width=0,
                phone_height=0,
            ):
                pass
        except asyncio.CancelledError:
            cancelled = True
            terminal_reason = "cancelled"
            if propagate_cancellation:
                raise
        except ProviderConfigurationError:
            terminal_reason = "provider_configuration"
        except Exception:
            terminal_reason = "runtime_failed"

        get_result = getattr(agent, "get_last_run_result", None)
        if callable(get_result):
            try:
                result = get_result(
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000),
                )
            except Exception:
                result = None
            if isinstance(result, AgentRunResult):
                return result
        return _fallback_result(
            status="cancelled" if cancelled else "failed",
            task_id=resolved_task_id,
            thread_id=resolved_thread_id,
            session_id=session_id,
            terminal_reason=terminal_reason,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )
    finally:
        if agent is not None:
            try:
                close = getattr(agent, "aclose", None)
                if callable(close):
                    await close()
            except asyncio.CancelledError:
                pass
            except Exception:
                # Cleanup failure is intentionally not allowed to replace the
                # already-established business outcome.
                pass
