# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

from contextlib import AsyncExitStack
import inspect
import logging
from typing import Any, Awaitable, Callable, Protocol, TypeVar

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from mobile_agent.agent.actions import CanonicalAction
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.mobile.koophone_auth import (
    HuaweiIamTokenProvider,
    JksJwtProvider,
    KooPhoneAuthenticator,
)
from mobile_agent.agent.mobile.koophone_tls import build_tls_verification
from mobile_agent.agent.mobile.result import ActionResult
from mobile_agent.agent.provider import (
    ProviderConfigurationError,
    ProviderNotImplementedError,
)
from mobile_agent.config.settings import KooPhoneConfig


logger = logging.getLogger(__name__)

OperationResult = TypeVar("OperationResult")

KOOPHONE_REQUIRED_TOOLS = frozenset(
    {
        "get_screenshot",
        "tap",
        "swipe",
        "input_text",
        "clear_text",
        "send_key",
        "get_installed_apps",
        "start_app",
        "stop_app",
    }
)


class KooPhoneAuthHeaders(Protocol):
    async def create_headers(self) -> dict[str, str]: ...


class KooPhoneMcpTransport(Protocol):
    async def connect(self, headers: dict[str, str]) -> set[str]: ...

    async def close(self) -> None: ...


class KooPhoneOperationOutcomeUncertain(RuntimeError):
    """A side-effect request may have reached KooPhone before auth failed."""


def is_authentication_rejection(error: BaseException) -> bool:
    """Recognize only explicit HTTP authentication rejections for recovery."""

    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code is None:
        status_code = getattr(error, "status_code", None)
    return status_code in {401, 403}


class StreamableHttpKooPhoneTransport:
    """Own the authenticated Streamable HTTP session for KooPhone MCP."""

    def __init__(
        self,
        config: KooPhoneConfig,
        *,
        http_client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        self._config = config
        self._exit_stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._client_factory = http_client_factory or self._http_client_factory

    def _http_client_factory(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout or httpx.Timeout(30.0),
            auth=auth,
            follow_redirects=True,
            verify=build_tls_verification(self._config),
        )

    async def connect(self, headers: dict[str, str]) -> set[str]:
        if not self._config.tls_verify:
            logger.warning(
                "KooPhone MCP TLS certificate verification is disabled for ENV=poc"
            )
        try:
            read, write, _ = await self._exit_stack.enter_async_context(
                streamablehttp_client(
                    self._config.mcp_url,
                    headers=headers,
                    httpx_client_factory=self._client_factory,
                )
            )
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()
            result = await self._session.list_tools()
        except Exception:
            await self.close()
            raise
        return {tool.name for tool in result.tools}

    async def close(self) -> None:
        await self._exit_stack.aclose()
        self._session = None


class KooPhoneDeviceBackend:
    name = "koophone_mcp"

    def __init__(
        self,
        config: KooPhoneConfig,
        *,
        authenticator: KooPhoneAuthHeaders | None = None,
        transport: KooPhoneMcpTransport | None = None,
    ) -> None:
        self._authenticator = authenticator or KooPhoneAuthenticator(
            iam_provider=HuaweiIamTokenProvider(config),
            jwt_provider=JksJwtProvider(config),
        )
        self._transport = transport or StreamableHttpKooPhoneTransport(config)
        self._session_headers: dict[str, str] | None = None

    async def initialize(self, **connection: str) -> None:
        del connection
        await self._connect_with_recovery()

    async def run_authenticated_operation(
        self,
        operation: Callable[[], Awaitable[OperationResult]],
        *,
        retry_safe: bool,
    ) -> OperationResult:
        """Run one MCP operation with bounded auth recovery semantics.

        Read-only operations may reconnect and retry once. A side-effect operation
        that receives 401/403 is never replayed because upstream acceptance is
        unknown.
        """

        await self._connect_with_recovery()
        try:
            return await operation()
        except Exception as error:
            if not is_authentication_rejection(error):
                raise
            await self._close_transport()
            await self._invalidate_credentials()
            if not retry_safe:
                raise KooPhoneOperationOutcomeUncertain(
                    "KooPhone side-effect outcome is uncertain after authentication rejection"
                ) from None

        await self._connect_with_recovery(retry_authentication_rejection=False)
        try:
            return await operation()
        except Exception as error:
            if is_authentication_rejection(error):
                await self._close_transport()
                await self._invalidate_credentials()
                raise ProviderConfigurationError(
                    "KooPhone MCP operation authentication recovery failed"
                ) from None
            raise

    async def _connect_with_recovery(
        self, *, retry_authentication_rejection: bool = True
    ) -> None:
        attempts = 2 if retry_authentication_rejection else 1
        for attempt in range(attempts):
            try:
                await self._ensure_authenticated_session()
            except ProviderConfigurationError:
                raise
            except Exception as error:
                await self._close_transport()
                if is_authentication_rejection(error):
                    await self._invalidate_credentials()
                    if attempt + 1 < attempts:
                        continue
                raise ProviderConfigurationError(
                    "KooPhone MCP startup probe failed"
                ) from None
            return

        raise ProviderConfigurationError("KooPhone MCP startup probe failed")

    async def _ensure_authenticated_session(self) -> None:
        headers = await self._authenticator.create_headers()
        if headers == self._session_headers:
            return
        if self._session_headers is not None:
            await self._close_transport()

        available_tools = await self._transport.connect(headers)
        missing = sorted(KOOPHONE_REQUIRED_TOOLS - available_tools)
        if missing:
            await self._transport.close()
            raise ProviderConfigurationError(
                "KooPhone MCP is missing required tools: " + ", ".join(missing)
            )
        self._session_headers = headers

    async def _invalidate_credentials(self) -> None:
        invalidate = getattr(self._authenticator, "invalidate", None)
        if invalidate is None:
            return
        result = invalidate()
        if inspect.isawaitable(result):
            await result

    async def _close_transport(self) -> None:
        try:
            await self._transport.close()
        except Exception:
            pass
        self._session_headers = None

    async def take_screenshot(self) -> dict[str, Any]:
        raise ProviderNotImplementedError(
            "KooPhone screenshot execution is delivered by Issue #14"
        )

    async def prepare_task(self, user_prompt: str) -> None:
        del user_prompt

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ActionResult:
        del action, screenshot_dimensions
        raise ProviderNotImplementedError(
            "KooPhone action execution is delivered by Issue #15"
        )

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall:
        del action, screenshot_dimensions
        raise ProviderNotImplementedError(
            "KooPhone action mapping is delivered by Issue #15"
        )

    async def verify_completion(self, action: CanonicalAction) -> bool | None:
        del action
        return None

    async def close(self) -> None:
        await self._close_transport()
