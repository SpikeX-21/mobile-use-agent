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

import logging
import os
import re
from typing import Any

from agentarts.sdk import AgentArtsRuntimeApp, PingStatus, RequestContext
from agentarts.sdk.runtime.model import SESSION_HEADER
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from mobile_agent.agent.run_result import AgentRunResult
from mobile_agent.koophone_task import run_koophone_task


MAX_INPUT_LENGTH = 4_096
_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")

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
_SENSITIVE_LOGGER_PREFIXES = (
    "agentarts",
    "mobile_agent.agent",
    "mcp",
    "httpx",
    "httpcore",
    "openai",
    "langchain",
    "huaweicloud",
)


class RuntimeHealth:
    """In-memory readiness state used by ``/ping`` without external probes."""

    def __init__(self) -> None:
        self._ready = True

    def set_ready(self, ready: bool) -> None:
        self._ready = bool(ready)

    def status(self) -> PingStatus:
        return PingStatus.HEALTHY if self._ready else PingStatus.UNHEALTHY


runtime_health = RuntimeHealth()


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
        if (
            record.exc_info is not None
            or record.exc_text is not None
            or (
                record.levelno >= logging.WARNING
                and record.name.startswith(_SENSITIVE_LOGGER_PREFIXES)
            )
        ):
            record.msg = "AgentArts runtime internal error"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


app = AgentArtsRuntimeApp(
    middleware=[Middleware(RedactedInvocationErrors)],
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


configure_runtime_logging()


def _error(error: str, *, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": error})


def _session_id(context: RequestContext) -> str:
    value = context.session_id
    if not isinstance(value, str) or not _SESSION_ID_PATTERN.fullmatch(value):
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


def _failure_code(result: AgentRunResult) -> tuple[str, int]:
    if result.terminal_reason in _DEVICE_FAILURE_REASONS:
        return "device_upstream_failed", 502
    if result.terminal_reason in {"provider_configuration", "runtime_failed"}:
        return "runtime_failed", 500
    return "task_failed", 422


def _failure_payload(result: AgentRunResult, error: str) -> dict[str, object]:
    return {
        "error": error,
        "status": result.status,
        "task_id": result.task_id,
        "thread_id": result.thread_id,
        "session_id": result.session_id,
        "rounds": result.rounds,
        "elapsed_ms": result.elapsed_ms,
        "terminal_reason": result.terminal_reason,
    }


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
        result = await run_koophone_task(prompt, session_id=session_id)
    except Exception:
        # The task runner normally returns a structured result.  Keep this
        # final boundary for unexpected adapter/runtime failures as well.
        return _error("runtime_failed", status_code=500)

    if not isinstance(result, AgentRunResult):
        return _error("runtime_failed", status_code=500)
    if result.completed:
        # Returning a plain mapping lets the SDK add its standard session
        # response header while retaining the stable JSON body.
        return result.to_dict()

    error, status_code = _failure_code(result)
    return JSONResponse(
        status_code=status_code,
        content=_failure_payload(result, error),
    )


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
    app.run(host="0.0.0.0", port=_port_from_environment())


if __name__ == "__main__":  # pragma: no cover - exercised by the runtime
    main()
