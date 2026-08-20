# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Business results for one MobileUseAgent task.

The result in this module is deliberately independent from experiment
telemetry.  JSONL is useful for redacted diagnostics, but it is local and
best-effort; callers need an in-memory business outcome for deciding whether
an invocation really completed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import time
from typing import Literal

from mobile_agent.agent.experiments.records import (
    contains_sensitive_text,
    safe_identifier,
)


RunStatus = Literal["completed", "failed", "cancelled"]

_MAX_PUBLIC_SUMMARY_LENGTH = 500
_COORDINATE_PATTERN = re.compile(
    r"(?:"
    r"[\"']?(?:x|y|start_x|start_y|end_x|end_y)[\"']?\s*[:=]\s*\d+\b|"
    r"(?:坐标|coordinate)[^0-9]{0,12}\d{1,5}\s*[,，]\s*\d{1,5}|"
    r"[\[\(]\s*\d{1,5}\s*[,，]\s*\d{1,5}\s*[\]\)]|"
    r"\b\d{1,5}\s*[,，]\s*\d{1,5}\b)",
    re.IGNORECASE,
)
_HIDDEN_REASONING_PATTERN = re.compile(
    r"(?:chain[-_ ]of[-_ ]thought|hidden[-_ ](?:thinking|reasoning)|"
    r"(?:analysis|reasoning|thought)\s*[:：]|思考过程|推理过程|内部思考|隐藏推理)",
    re.IGNORECASE,
)


def safe_public_summary(value: object) -> str | None:
    """Keep only a short, user-facing summary safe for a Runtime response."""

    if not isinstance(value, str):
        return None
    summary = " ".join(value.split())
    if not summary or len(summary) > _MAX_PUBLIC_SUMMARY_LENGTH:
        return None
    if (
        contains_sensitive_text(summary)
        or _COORDINATE_PATTERN.search(summary)
        or _HIDDEN_REASONING_PATTERN.search(summary)
    ):
        return None
    return summary


def _public_identifier(value: object, fallback: str) -> str:
    return safe_identifier(value, fallback=fallback)


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    """Stable, JSON-safe business outcome of one independent task."""

    status: RunStatus
    task_id: str
    thread_id: str
    session_id: str
    result: str | None
    rounds: int
    elapsed_ms: int
    terminal_reason: str

    def __post_init__(self) -> None:
        if self.status not in ("completed", "failed", "cancelled"):
            raise ValueError("status must be completed, failed or cancelled")
        if self.status == "completed" and self.terminal_reason != "completed":
            raise ValueError("completed results must have terminal_reason=completed")
        if self.status != "completed" and self.terminal_reason == "completed":
            raise ValueError(
                "non-completed results cannot have terminal_reason=completed"
            )
        object.__setattr__(
            self,
            "task_id",
            _public_identifier(self.task_id, "task-unknown"),
        )
        object.__setattr__(
            self, "thread_id", _public_identifier(self.thread_id, "thread-unknown")
        )
        object.__setattr__(
            self,
            "session_id",
            _public_identifier(self.session_id, "session-unknown"),
        )
        object.__setattr__(
            self,
            "terminal_reason",
            _public_identifier(self.terminal_reason, "runtime_failed"),
        )
        object.__setattr__(self, "rounds", max(0, self.rounds))
        object.__setattr__(self, "elapsed_ms", max(0, self.elapsed_ms))
        safe_result = safe_public_summary(self.result)
        object.__setattr__(
            self,
            "result",
            (safe_result or "任务已完成")
            if self.status == "completed"
            else None,
        )

    @property
    def summary(self) -> str | None:
        """Compatibility alias for callers that call the result a summary."""

        return self.result

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "result": self.result,
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "session_id": self.session_id,
            "rounds": self.rounds,
            "elapsed_ms": self.elapsed_ms,
            "terminal_reason": self.terminal_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

@dataclass(slots=True)
class AgentRunState:
    """Mutable business state shared by graph nodes during one task."""

    task_id: str
    thread_id: str
    session_id: str
    started_at: float = field(default_factory=time.perf_counter)
    rounds: int = 0
    terminal_reason: str | None = None
    result: str | None = None

    def observe_round(self, round_number: int) -> None:
        self.rounds = max(self.rounds, round_number)

    def complete(self, summary: object) -> None:
        if self.terminal_reason is None:
            self.terminal_reason = "completed"
            self.result = safe_public_summary(summary) or "任务已完成"

    def fail(self, reason: str) -> None:
        if self.terminal_reason is None:
            self.terminal_reason = _public_identifier(reason, "runtime_failed")
            self.result = None

    def to_result(self, *, elapsed_ms: int | None = None) -> AgentRunResult:
        reason = self.terminal_reason or "runtime_failed"
        status: RunStatus = (
            "completed"
            if reason == "completed"
            else "cancelled"
            if reason == "cancelled"
            else "failed"
        )
        measured_elapsed = (
            max(0, round((time.perf_counter() - self.started_at) * 1000))
            if elapsed_ms is None
            else max(0, elapsed_ms)
        )
        return AgentRunResult(
            status=status,
            task_id=_public_identifier(self.task_id, "task-unknown"),
            thread_id=_public_identifier(self.thread_id, "thread-unknown"),
            session_id=_public_identifier(self.session_id, "session-unknown"),
            result=self.result if status == "completed" else None,
            rounds=max(0, self.rounds),
            elapsed_ms=measured_elapsed,
            terminal_reason=_public_identifier(reason, "runtime_failed"),
        )
