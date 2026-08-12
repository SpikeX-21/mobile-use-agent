# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import fcntl
from dataclasses import dataclass
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from mobile_agent.agent.actions import (
    CanonicalAction,
    FailAction,
    FinishAction,
    TextInputAction,
)


_REDACTED = "[REDACTED]"
logger = logging.getLogger(__name__)
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "authorization",
    "auth_header",
    "bearer",
    "token",
    "private_key",
    "vendor_keys",
    "adbkey",
    "screenshot",
    "image_base64",
    "chain_of_thought",
    "hidden_thinking",
    "hidden_reasoning",
)
_SENSITIVE_KEYS = {"ak", "sk", "acep_ak", "acep_sk"}
_SIGNED_QUERY_KEYS = {
    "signature",
    "sig",
    "x-tos-signature",
    "x-amz-signature",
    "x-tos-security-token",
    "x-amz-security-token",
    "accesskeyid",
}
_SECRET_VALUE_PATTERNS = (
    re.compile(r"^Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bark-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKLT[A-Za-z0-9]{12,}\b"),
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        part in normalized for part in _SENSITIVE_KEY_PARTS
    )


def _is_signed_url(value: str) -> bool:
    if not value.lower().startswith(("http://", "https://")):
        return False
    query_keys = {key.lower() for key, _ in parse_qsl(urlsplit(value).query)}
    return bool(query_keys & _SIGNED_QUERY_KEYS)


def contains_sensitive_text(value: str) -> bool:
    """Return whether free text contains a credential or private observation."""

    lowered = value.lower()
    if any(
        marker in lowered
        for marker in (
            "data:image/",
            "hidden_thinking",
            "hidden_reasoning",
            "chain_of_thought",
        )
    ):
        return True
    if re.search(r"(?im)^\s*(?:proxy-)?authorization\s*[:=]", value):
        return True
    if any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS):
        return True
    return any(
        _is_signed_url(candidate)
        for candidate in re.findall(r"https?://[^\s\"'<>]+", value)
    )


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        if contains_sensitive_text(value):
            return _REDACTED
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def redact_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe mapping with credentials and observations removed."""

    return {
        str(key): _REDACTED if _is_sensitive_key(key) else _redact_value(value)
        for key, value in values.items()
    }


class TextFingerprint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    length: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SafeActionArguments(BaseModel):
    """Allowlisted action data; arbitrary model text cannot be represented."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    x: int | None = Field(default=None, ge=0, le=1000)
    y: int | None = Field(default=None, ge=0, le=1000)
    start_x: int | None = Field(default=None, ge=0, le=1000)
    start_y: int | None = Field(default=None, ge=0, le=1000)
    end_x: int | None = Field(default=None, ge=0, le=1000)
    end_y: int | None = Field(default=None, ge=0, le=1000)
    duration_ms: int | None = Field(default=None, ge=1, le=10_000)
    package_name: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$",
    )
    ignore_system_apps: bool | None = None
    text: TextFingerprint | None = None


def redact_action_arguments(action: CanonicalAction) -> SafeActionArguments:
    """Serialize model action arguments without retaining private free text."""

    if isinstance(action, TextInputAction):
        encoded = action.text.encode("utf-8")
        return SafeActionArguments(
            text=TextFingerprint(
                length=len(action.text),
                sha256=hashlib.sha256(encoded).hexdigest(),
            )
        )
    if isinstance(action, (FinishAction, FailAction)):
        return SafeActionArguments()
    return SafeActionArguments.model_validate(action.model_dump(exclude={"type"}))


ActionType = Literal[
    "tap",
    "swipe",
    "text_input",
    "clear_text",
    "home",
    "back",
    "menu",
    "launch_app",
    "close_app",
    "list_apps",
    "wait",
    "finish",
    "fail",
    "prepare",
    "observation",
    "model_call",
    "invalid_action",
    "runtime",
]
ActionStatus = Literal[
    "success",
    "failed",
    "ambiguous",
    "rejected",
    "unsupported",
    "not_executed",
]
SchemaStatus = Literal["valid", "invalid", "not_evaluated"]
TerminalReason = Literal[
    "completed",
    "model_failed",
    "device_offline",
    "step_limit",
    "schema_error_limit",
    "oracle_rejected",
    "device_observation_failed",
    "model_call_failed",
    "prepare_failed",
    "cancelled",
    "client_disconnected",
    "runtime_failed",
    "runtime_ended",
]
SafeIdentifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]


def safe_identifier(value: object, *, fallback: str = "unknown") -> str:
    """Return a bounded identifier without ever retaining credential-like values."""

    if not isinstance(value, str):
        return fallback
    normalized = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", normalized):
        return fallback
    if any(pattern.search(normalized) for pattern in _SECRET_VALUE_PATTERNS):
        return fallback
    return normalized


@dataclass(frozen=True)
class StepOutcome:
    """A business step result mapped to the stable experiment schema."""

    action: CanonicalAction | None = None
    action_type: ActionType | None = None
    action_status: ActionStatus = "not_executed"
    device_latency_ms: int | None = None
    device_error_kind: str | None = None
    schema_status: SchemaStatus = "not_evaluated"
    terminal_reason: TerminalReason | None = None
    oracle_result: bool | None = None


class RunRecord(BaseModel):
    """One comparable, privacy-safe decision step in an Agent run."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    run_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    scenario_id: str = Field(pattern=r"^scenario-[0-9a-f]{16}$")
    provider: SafeIdentifier
    model: SafeIdentifier
    step_number: int = Field(ge=1)
    action_type: ActionType
    action_arguments: SafeActionArguments
    model_latency_ms: int = Field(ge=0)
    device_latency_ms: int | None = Field(default=None, ge=0)
    action_status: ActionStatus
    device_error_kind: Literal[
        "timeout",
        "offline",
        "command_failed",
        "invalid_observation",
    ] | None = None
    schema_status: SchemaStatus
    terminal_reason: TerminalReason | None = None
    oracle_result: bool | None = None
    observation_strategy: Literal["fixed_recent", "dynamic_recent"]
    observation_window_size: int = Field(ge=1)
    observation_images_used: int = Field(ge=0)
    device_provider: SafeIdentifier
    observation_policy_version: Literal[1] = 1

    @field_validator("provider", "model", "device_provider")
    @classmethod
    def reject_credential_identifiers(cls, value: str) -> str:
        if safe_identifier(value) != value:
            raise ValueError("identifier must not contain credential-like content")
        return value

    @field_serializer("action_arguments")
    def serialize_action_arguments(
        self, value: SafeActionArguments
    ) -> dict[str, Any]:
        return value.model_dump(mode="json", exclude_none=True)


_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.Lock())


class JsonlExperimentRecorder:
    """Append validated run records as one JSON object per line."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._lock = _path_lock(self.path)

    def write(self, record: RunRecord) -> None:
        payload = record.model_dump(mode="json")
        line = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self.path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY | os.O_CLOEXEC,
                0o600,
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                os.fchmod(descriptor, 0o600)
                remaining = memoryview((line + "\n").encode("utf-8"))
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("experiment record write made no progress")
                    remaining = remaining[written:]
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)


class ExperimentRun:
    """Run-scoped metadata and the only entry point used by the Agent graph."""

    OBSERVATION_STRATEGY = "fixed_recent"
    OBSERVATION_WINDOW_SIZE = 5

    def __init__(
        self,
        *,
        recorder: JsonlExperimentRecorder,
        query: str,
        provider: str,
        model: str,
        device_provider: str,
        run_id: str | None = None,
    ):
        normalized_query = " ".join(query.split())
        scenario_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()
        self.recorder = recorder
        self.run_id = run_id or str(uuid.uuid4())
        self.scenario_id = f"scenario-{scenario_hash[:16]}"
        self.provider = safe_identifier(provider)
        self.model = safe_identifier(model)
        self.device_provider = safe_identifier(device_provider)
        self._record_lock = threading.Lock()
        self._last_step_number = 0
        self._last_observation_images_used = 0
        self._terminal_recorded = False

    def note_observation_images_used(self, count: int) -> None:
        """Track the model payload size for run-level cancellation records."""

        with self._record_lock:
            self._last_observation_images_used = min(
                max(0, count), self.OBSERVATION_WINDOW_SIZE
            )

    def record_step(
        self,
        *,
        step_number: int,
        action: CanonicalAction | None,
        action_type: ActionType | None = None,
        model_latency_ms: int,
        device_latency_ms: int | None,
        action_status: ActionStatus,
        device_error_kind: str | None = None,
        schema_status: SchemaStatus,
        terminal_reason: TerminalReason | None = None,
        oracle_result: bool | None = None,
        observation_images_used: int,
    ) -> None:
        resolved_action_type = action.type if action is not None else action_type
        if not resolved_action_type:
            raise ValueError("action_type is required when action is absent")
        images_used = min(
            max(0, observation_images_used), self.OBSERVATION_WINDOW_SIZE
        )
        with self._record_lock:
            self.recorder.write(
                RunRecord(
                    run_id=self.run_id,
                    scenario_id=self.scenario_id,
                    provider=self.provider,
                    model=self.model,
                    step_number=max(1, step_number),
                    action_type=resolved_action_type,
                    action_arguments=(
                        redact_action_arguments(action)
                        if action is not None
                        else SafeActionArguments()
                    ),
                    model_latency_ms=max(0, model_latency_ms),
                    device_latency_ms=(
                        max(0, device_latency_ms)
                        if device_latency_ms is not None
                        else None
                    ),
                    action_status=action_status,
                    device_error_kind=device_error_kind,
                    schema_status=schema_status,
                    terminal_reason=terminal_reason,
                    oracle_result=oracle_result,
                    observation_strategy=self.OBSERVATION_STRATEGY,
                    observation_window_size=self.OBSERVATION_WINDOW_SIZE,
                    observation_images_used=images_used,
                    device_provider=self.device_provider,
                )
            )
            self._last_step_number = max(self._last_step_number, step_number)
            self._last_observation_images_used = images_used
            if terminal_reason is not None:
                self._terminal_recorded = True

    def try_record_step(self, **kwargs: Any) -> bool:
        """Best-effort telemetry that can never alter Agent execution."""

        try:
            self.record_step(**kwargs)
        except Exception:
            logger.exception("Failed to write redacted experiment record")
            return False
        return True

    def try_record_outcome(
        self,
        *,
        step_number: int,
        model_latency_ms: int,
        observation_images_used: int,
        outcome: StepOutcome,
    ) -> bool:
        """Map one domain outcome to a record without affecting Agent behavior."""

        return self.try_record_step(
            step_number=step_number,
            action=outcome.action,
            action_type=outcome.action_type,
            model_latency_ms=model_latency_ms,
            device_latency_ms=outcome.device_latency_ms,
            action_status=outcome.action_status,
            device_error_kind=outcome.device_error_kind,
            schema_status=outcome.schema_status,
            terminal_reason=outcome.terminal_reason,
            oracle_result=outcome.oracle_result,
            observation_images_used=observation_images_used,
        )

    def record_terminal_once(self, terminal_reason: TerminalReason) -> bool:
        """Append one run-level terminal marker when no step already terminated."""

        with self._record_lock:
            if self._terminal_recorded:
                return False
            self.recorder.write(
                RunRecord(
                    run_id=self.run_id,
                    scenario_id=self.scenario_id,
                    provider=self.provider,
                    model=self.model,
                    step_number=max(1, self._last_step_number + 1),
                    action_type="runtime",
                    action_arguments=SafeActionArguments(),
                    model_latency_ms=0,
                    device_latency_ms=None,
                    action_status="not_executed",
                    device_error_kind=None,
                    schema_status="not_evaluated",
                    terminal_reason=terminal_reason,
                    oracle_result=None,
                    observation_strategy=self.OBSERVATION_STRATEGY,
                    observation_window_size=self.OBSERVATION_WINDOW_SIZE,
                    observation_images_used=self._last_observation_images_used,
                    device_provider=self.device_provider,
                )
            )
            self._terminal_recorded = True
            return True

    def try_record_terminal_once(self, terminal_reason: TerminalReason) -> bool:
        try:
            return self.record_terminal_once(terminal_reason)
        except Exception:
            logger.exception("Failed to write redacted terminal experiment record")
            return False
