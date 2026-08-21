# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Local synchronous AgentArts Runtime adapter for the KooPhone agent.

The Huawei ``agentarts-sdk`` owns the runtime protocol and route layout.  This
module only validates the local request contract, invokes the existing
``run_koophone_task`` entry point, and maps its structured business result to a
small synchronous JSON API.  It deliberately does not duplicate the
MobileUseAgent graph or expose the outer Gateway ``/runtimes/...`` path.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import logging
import math
import os
import re
import sys
import time
import uuid
from typing import Any

from agentarts.sdk import AgentArtsRuntimeApp, PingStatus, RequestContext
from agentarts.sdk.runtime.model import SESSION_HEADER
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from mobile_agent.agent.experiments.records import (
    contains_sensitive_text,
    safe_identifier,
)
from mobile_agent.agent.run_result import AgentRunResult
from mobile_agent.koophone_task import run_koophone_task
from mobile_agent.runtime.device_lease import (
    DeviceLeaseHandle,
    DeviceLeaseProvider,
    InProcessDeviceLease,
)
from mobile_agent.runtime.security import (
    InvocationRequestGuard,
    MAX_REQUEST_BODY_BYTES,
    RuntimeConfigurationError,
    validate_runtime_configuration,
)


MAX_INPUT_LENGTH = 4_096
DEFAULT_TASK_TIMEOUT_SECONDS = 900.0
FIXED_DEVICE_SLOT = "koophone-fixed-device"
RUNTIME_PROVIDER = "kimi"
RUNTIME_MODEL = "kimi-k2.6"
RUNTIME_DEVICE_PROVIDER = "koophone_mcp"
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PATH_OR_URL_PATTERN = re.compile(
    r"(?:https?://|file://|(?<![A-Za-z0-9])/(?:[A-Za-z0-9_.-]+/)+[^\s]+|"
    r"[A-Za-z]:\\|"
    r"(?:^|[\s(])(?:[A-Za-z0-9_.-]+/)+[^\s]+|"
    r"\.(?:env|jks|jsonl?|key|pem)\b)",
    re.IGNORECASE,
)
_RAW_RESULT_PATTERN = re.compile(
    r"(?:[{}\[\]]|\b(?:action|analysis|chain[-_ ]of[-_ ]thought|"
    r"model[_ -]?output|reasoning|tool[_ -]?call|traceback)\b)",
    re.IGNORECASE,
)
_RUNTIME_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_RUNTIME_TERMINAL_REASONS = frozenset(
    {
        "completed",
        "cancelled",
        "client_disconnected",
        "device_busy",
        "device_offline",
        "device_observation_failed",
        "device_upstream_failed",
        "mcp_error",
        "model_call_failed",
        "model_failed",
        "operation_uncertain",
        "oracle_rejected",
        "prepare_failed",
        "provider_configuration",
        "runtime_ended",
        "runtime_failed",
        "schema_error_limit",
        "step_limit",
        "task_timeout",
        "timeout",
        "unsafe_retry_blocked",
    }
)
_RUNTIME_AUDIT_LOGGER_NAME = "agentarts.runtime.audit"
_RUNTIME_AUDIT_LOGGER = logging.getLogger(_RUNTIME_AUDIT_LOGGER_NAME)
_RUNTIME_SECRET_ENV_NAMES = (
    "KIMI_API_KEY",
    "OPENAI_API_KEY",
    "ARK_API_KEY",
    "ACEP_AK",
    "ACEP_SK",
    "KOOPHONE_IAM_PASSWORD",
    "KOOPHONE_JKS_STORE_PASSWORD",
    "KOOPHONE_JKS_KEY_PASSWORD",
    "KOOPHONE_INSTANCE_ID",
    "KOOPHONE_MCP_URL",
    "KOOPHONE_IAM_AUTH_URL",
    "KOOPHONE_JKS_PATH",
    "MOBILE_USE_MCP_URL",
    "AGENTARTS_RUNTIME_API_KEY",
)

_DEVICE_FAILURE_REASONS = frozenset(
    {
        "device_observation_failed",
        "device_offline",
        "device_upstream_failed",
        "device_backend_error",
        "mcp_error",
        "prepare_failed",
        "timeout",
        "ambiguous",
        "operation_uncertain",
    }
)


class RuntimeHealth:
    """In-memory readiness state used by ``/ping`` without external probes."""

    def __init__(self) -> None:
        self._ready = True
        self._busy = False

    def set_ready(self, ready: bool) -> None:
        self._ready = bool(ready)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)

    def status(self) -> PingStatus:
        if not self._ready:
            return PingStatus.UNHEALTHY
        return PingStatus.HEALTHY_BUSY if self._busy else PingStatus.HEALTHY


runtime_health = RuntimeHealth()
device_lease_provider: DeviceLeaseProvider = InProcessDeviceLease()


class RedactedInvocationErrors:
    """Remove raw SDK 400/500 response bodies from the public route.

    ``AgentArtsRuntimeApp`` is the protocol implementation, but its default
    exception handler includes exception type and message in a JSON response.
    The local contract exposes only stable error codes.  This ASGI middleware
    keeps the SDK routes intact and rewrites only the two default error
    statuses; successful, 422, and 502 responses are passed through unchanged.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/invocations":
            await self.app(scope, receive, send)
            return

        messages: list[dict[str, Any]] = []

        async def capture(message: dict[str, Any]) -> None:
            messages.append(message)

        try:
            await self.app(scope, receive, capture)
        except Exception:
            await JSONResponse(
                status_code=500,
                content={"error": "runtime_failed"},
            )(scope, receive, send)
            return

        status = next(
            (
                message.get("status")
                for message in messages
                if message.get("type") == "http.response.start"
            ),
            500,
        )
        if status in (400, 500):
            await JSONResponse(
                status_code=status,
                content={
                    "error": "invalid_request" if status == 400 else "runtime_failed"
                },
            )(scope, receive, send)
            return

        for message in messages:
            await send(message)


class RedactedRuntimeLogFilter(logging.Filter):
    """Prevent provider exception messages and tracebacks reaching logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name.startswith(_RUNTIME_AUDIT_LOGGER_NAME):
            return True
        # Runtime stdout/stderr is an allowlist: only the audit logger emits
        # informational records. Warnings/errors from dependencies are kept as
        # one safe marker and never carry their original arguments or traceback.
        if record.levelno < logging.WARNING:
            return False
        record.msg = "AgentArts runtime internal error"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


class RuntimeAuditStdoutHandler(logging.StreamHandler):
    """Dedicated stdout sink for the already allowlisted Runtime audit event."""


def _install_runtime_audit_handler() -> None:
    """Keep audit INFO events visible after the AgentArts SDK configures logging."""

    if not any(
        isinstance(handler, RuntimeAuditStdoutHandler)
        for handler in _RUNTIME_AUDIT_LOGGER.handlers
    ):
        handler = RuntimeAuditStdoutHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        _RUNTIME_AUDIT_LOGGER.addHandler(handler)
    _RUNTIME_AUDIT_LOGGER.propagate = False


app = AgentArtsRuntimeApp(
    middleware=[
        Middleware(InvocationRequestGuard),
        Middleware(RedactedInvocationErrors),
    ],
)


def _install_runtime_log_filter(target: Any) -> None:
    if not any(isinstance(item, RedactedRuntimeLogFilter) for item in target.filters):
        target.addFilter(RedactedRuntimeLogFilter())


def configure_runtime_logging() -> None:
    """Redact SDK and provider exceptions before they reach stdout/LTS."""

    _install_runtime_log_filter(app.logger)
    root_logger = logging.getLogger()
    _install_runtime_log_filter(root_logger)

    # Provider libraries can be configured with their own handlers.  Install
    # the same filter on every handler that already exists, including handlers
    # added by an embedding host before ``main`` is called.
    known_loggers: list[logging.Logger] = [root_logger, app.logger]
    for candidate in logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, logging.Logger):
            known_loggers.append(candidate)
    for logger in known_loggers:
        _install_runtime_log_filter(logger)
        for handler in logger.handlers:
            _install_runtime_log_filter(handler)

    # Avoid verbose transport logs that may contain request URLs or headers.
    for logger_name in ("httpx", "httpcore", "mcp.client.streamable_http"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    logging.getLogger().setLevel(logging.WARNING)
    # The SDK may later replace or raise the level of its parent handlers.
    # Give the allowlisted audit event a dedicated stdout sink instead of
    # relying on propagation through that mutable logging hierarchy.
    _install_runtime_audit_handler()
    logging.getLogger("agentarts").propagate = False
    for logger_name in (
        "agentarts.runtime.app",
        "mobile_agent",
        "mcp",
        "openai",
        "langchain",
        "huaweicloud",
        "httpx",
        "httpcore",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    _RUNTIME_AUDIT_LOGGER.setLevel(logging.INFO)


configure_runtime_logging()


def _error(error: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error})


def _session_id(context: RequestContext) -> str:
    value = context.session_id
    if (
        not isinstance(value, str)
        or not _SESSION_ID_PATTERN.fullmatch(value)
        or safe_identifier(value) != value
        or any(value == secret for secret in _runtime_secret_values())
    ):
        raise ValueError("invalid session id")
    return value


def _prompt(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"input"}:
        raise ValueError("input must be an object with only input")
    value = payload.get("input")
    if not isinstance(value, str):
        raise ValueError("input must be a string")
    value = value.strip()
    if not value or len(value) > MAX_INPUT_LENGTH:
        raise ValueError("input length is invalid")
    return value


def _task_timeout_seconds() -> float:
    raw_timeout = os.getenv(
        "AGENT_TASK_TIMEOUT_SECONDS", str(DEFAULT_TASK_TIMEOUT_SECONDS)
    )
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("AGENT_TASK_TIMEOUT_SECONDS must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("AGENT_TASK_TIMEOUT_SECONDS must be greater than zero")
    return timeout


def _runtime_secret_values() -> tuple[str, ...]:
    values: list[str] = []
    for name in _RUNTIME_SECRET_ENV_NAMES:
        value = os.getenv(name)
        if isinstance(value, str) and len(value) >= 4:
            values.append(value)
    return tuple(values)


def _runtime_identifier(value: object, *, fallback: str) -> str:
    """Return only bounded IDs, never a path, URL, or credential-shaped value."""

    if not isinstance(value, str) or not _RUNTIME_IDENTIFIER_PATTERN.fullmatch(value):
        return fallback
    if (
        contains_sensitive_text(value)
        or _PATH_OR_URL_PATTERN.search(value)
        or any(value == secret for secret in _runtime_secret_values())
    ):
        return fallback
    return value


def _runtime_terminal_reason(value: object) -> str:
    if isinstance(value, str) and value in _RUNTIME_TERMINAL_REASONS:
        return value
    return "runtime_failed"


def _safe_runtime_result(result: AgentRunResult, prompt: str) -> AgentRunResult:
    """Keep model summaries from becoming a second secret exfiltration path."""

    summary = result.result
    safe_result = AgentRunResult(
        status=result.status,
        task_id=_runtime_identifier(result.task_id, fallback="task-unknown"),
        thread_id=_runtime_identifier(result.thread_id, fallback="thread-unknown"),
        session_id=_runtime_identifier(result.session_id, fallback="session-unknown"),
        result=summary,
        rounds=result.rounds,
        elapsed_ms=result.elapsed_ms,
        terminal_reason=_runtime_terminal_reason(result.terminal_reason),
    )
    if not safe_result.completed or not isinstance(summary, str):
        return safe_result
    normalized_prompt = " ".join(prompt.split())
    unsafe = (
        (normalized_prompt and normalized_prompt in summary)
        or contains_sensitive_text(summary)
        or _PATH_OR_URL_PATTERN.search(summary) is not None
        or _RAW_RESULT_PATTERN.search(summary) is not None
        or any(secret in summary for secret in _runtime_secret_values())
    )
    if not unsafe:
        return safe_result
    return replace(safe_result, result="任务已完成")


def _emit_runtime_event(
    *,
    status: str,
    task_id: str | None = None,
    thread_id: str | None = None,
    session_id: str | None = None,
    rounds: int = 0,
    elapsed_ms: int = 0,
    terminal_reason: str | None = None,
    error: str | None = None,
) -> None:
    """Write only the allowlisted invocation fields to stdout/LTS."""

    event: dict[str, object] = {
        "event": "runtime_invocation",
        "provider": RUNTIME_PROVIDER,
        "model": RUNTIME_MODEL,
        "device_provider": RUNTIME_DEVICE_PROVIDER,
        "status": status,
        "rounds": max(0, int(rounds)),
        "elapsed_ms": max(0, int(elapsed_ms)),
    }
    for key, value in (
        ("task_id", task_id),
        ("thread_id", thread_id),
        ("session_id", session_id),
        ("terminal_reason", terminal_reason),
        ("error", error),
    ):
        if value is not None:
            event[key] = _runtime_identifier(value, fallback="unknown")
    _RUNTIME_AUDIT_LOGGER.info(
        json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _new_task_ids() -> tuple[str, str]:
    return (
        f"koophone-task-{uuid.uuid4()}",
        f"koophone-thread-{uuid.uuid4()}",
    )


def _failure_code(result: AgentRunResult) -> tuple[str, int]:
    if result.terminal_reason in _DEVICE_FAILURE_REASONS:
        return "device_upstream_failed", 502
    if result.terminal_reason in {"provider_configuration", "runtime_failed"}:
        return "runtime_failed", 500
    return "task_failed", 422


def _failure_payload(result: AgentRunResult, error: str) -> dict[str, object]:
    return {
        "error": error,
        "status": (
            result.status if result.status in ("failed", "cancelled") else "failed"
        ),
        "task_id": _runtime_identifier(result.task_id, fallback="task-unknown"),
        "thread_id": _runtime_identifier(
            result.thread_id, fallback="thread-unknown"
        ),
        "session_id": _runtime_identifier(
            result.session_id, fallback="session-unknown"
        ),
        "rounds": result.rounds,
        "elapsed_ms": result.elapsed_ms,
        "terminal_reason": _runtime_terminal_reason(result.terminal_reason),
    }


def _timeout_result(
    *,
    task_id: str,
    thread_id: str,
    session_id: str,
    elapsed_ms: int,
) -> AgentRunResult:
    return AgentRunResult(
        status="failed",
        task_id=task_id,
        thread_id=thread_id,
        session_id=session_id,
        result=None,
        rounds=0,
        elapsed_ms=elapsed_ms,
        terminal_reason="timeout",
    )


async def _release_device_lease(lease: DeviceLeaseHandle) -> None:
    """Await lease cleanup even when the invocation task is being cancelled."""

    release_task = asyncio.create_task(lease.release())
    try:
        await asyncio.shield(release_task)
    except asyncio.CancelledError:
        try:
            await release_task
        except Exception:
            logging.getLogger(__name__).exception("Device lease release failed")
        raise
    except Exception:
        logging.getLogger(__name__).exception("Device lease release failed")


@app.entrypoint
async def invoke(
    payload: object, context: RequestContext
) -> JSONResponse | dict[str, object]:
    """Validate one request and run one fresh KooPhone task."""

    try:
        prompt = _prompt(payload)
        session_id = _session_id(context)
    except (TypeError, ValueError):
        return _error("invalid_request", status_code=400)

    try:
        task_timeout = _task_timeout_seconds()
    except ValueError:
        _emit_runtime_event(
            status="failed",
            session_id=session_id,
            terminal_reason="runtime_failed",
            error="runtime_failed",
        )
        return _error("runtime_failed", status_code=500)

    task_id, thread_id = _new_task_ids()
    lease: DeviceLeaseHandle | None = None
    try:
        try:
            lease = await device_lease_provider.try_acquire(FIXED_DEVICE_SLOT)
        except asyncio.CancelledError:
            _emit_runtime_event(
                status="cancelled",
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                terminal_reason="cancelled",
            )
            raise
        except Exception:
            _emit_runtime_event(
                status="failed",
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                terminal_reason="runtime_failed",
                error="runtime_failed",
            )
            return _error("runtime_failed", status_code=500)

        if lease is None:
            _emit_runtime_event(
                status="busy",
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                terminal_reason="device_busy",
                error="device_busy",
            )
            return _error("device_busy", status_code=409)

        runtime_health.set_busy(True)
        started_at = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                run_koophone_task(
                    prompt,
                    session_id=session_id,
                    task_id=task_id,
                    thread_id=thread_id,
                    propagate_cancellation=True,
                ),
                timeout=task_timeout,
            )
        except asyncio.TimeoutError:
            timeout_result = _timeout_result(
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                elapsed_ms=round((time.perf_counter() - started_at) * 1000),
            )
            _emit_runtime_event(
                status=timeout_result.status,
                task_id=timeout_result.task_id,
                thread_id=timeout_result.thread_id,
                session_id=timeout_result.session_id,
                rounds=timeout_result.rounds,
                elapsed_ms=timeout_result.elapsed_ms,
                terminal_reason=timeout_result.terminal_reason,
                error="task_timeout",
            )
            return JSONResponse(
                status_code=504,
                content=_failure_payload(timeout_result, "task_timeout"),
            )
        except asyncio.CancelledError:
            _emit_runtime_event(
                status="cancelled",
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                terminal_reason="cancelled",
            )
            raise
        except Exception:
            _emit_runtime_event(
                status="failed",
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                terminal_reason="runtime_failed",
                error="runtime_failed",
            )
            return _error("runtime_failed", status_code=500)

        if not isinstance(result, AgentRunResult):
            _emit_runtime_event(
                status="failed",
                task_id=task_id,
                thread_id=thread_id,
                session_id=session_id,
                terminal_reason="runtime_failed",
                error="runtime_failed",
            )
            return _error("runtime_failed", status_code=500)
        result = _safe_runtime_result(result, prompt)
        if result.completed:
            _emit_runtime_event(
                status=result.status,
                task_id=result.task_id,
                thread_id=result.thread_id,
                session_id=result.session_id,
                rounds=result.rounds,
                elapsed_ms=result.elapsed_ms,
                terminal_reason=result.terminal_reason,
            )
            return JSONResponse(
                status_code=200,
                content=result.to_dict(),
                headers={
                    SESSION_HEADER: _runtime_identifier(
                        session_id, fallback="session-unknown"
                    )
                },
            )

        error, status_code = _failure_code(result)
        _emit_runtime_event(
            status=result.status,
            task_id=result.task_id,
            thread_id=result.thread_id,
            session_id=result.session_id,
            rounds=result.rounds,
            elapsed_ms=result.elapsed_ms,
            terminal_reason=result.terminal_reason,
            error=error,
        )
        return JSONResponse(
            status_code=status_code,
            content=_failure_payload(result, error),
        )
    finally:
        if lease is not None:
            try:
                await _release_device_lease(lease)
            finally:
                runtime_health.set_busy(False)


@app.ping
def ping() -> PingStatus:
    """Return SDK wire-format health without touching model/device services."""

    return runtime_health.status()


def _port_from_environment() -> int:
    raw_port = os.getenv("AGENT_RUN_PORT", "8080")
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("AGENT_RUN_PORT must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("AGENT_RUN_PORT must be between 1 and 65535")
    return port


def main() -> None:
    """Run the SDK app on all interfaces for local/container execution."""

    configure_runtime_logging()
    runtime_health.set_ready(False)
    try:
        validate_runtime_configuration()
    except RuntimeConfigurationError as error:
        _RUNTIME_AUDIT_LOGGER.error(
            json.dumps(
                {
                    "event": "runtime_startup",
                    "status": "failed",
                    "error": "runtime_configuration",
                    "field": safe_identifier(error.field, fallback="unknown"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise SystemExit(2) from None
    except Exception:
        _RUNTIME_AUDIT_LOGGER.error(
            '{"event":"runtime_startup","status":"failed",'
            '"error":"runtime_configuration"}'
        )
        raise SystemExit(2) from None
    try:
        port = _port_from_environment()
    except ValueError:
        _RUNTIME_AUDIT_LOGGER.error(
            '{"event":"runtime_startup","status":"failed",'
            '"error":"runtime_configuration","field":"AGENT_RUN_PORT"}'
        )
        raise SystemExit(2) from None
    runtime_health.set_ready(True)
    # Uvicorn access logs include the request path and query string.  The
    # Runtime boundary has an allowlisted stdout contract, so do not enable
    # the SDK's default access logger.
    app.run(host="0.0.0.0", port=port, access_log=False)


if __name__ == "__main__":  # pragma: no cover - exercised by the runtime
    main()
