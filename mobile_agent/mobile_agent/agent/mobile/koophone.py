# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

from contextlib import AsyncExitStack
import logging
from typing import Any, Callable, Protocol

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

    async def initialize(self, **connection: str) -> None:
        del connection
        headers = await self._authenticator.create_headers()
        try:
            available_tools = await self._transport.connect(headers)
        except Exception:
            try:
                await self._transport.close()
            except Exception:
                pass
            raise ProviderConfigurationError(
                "KooPhone MCP startup probe failed"
            ) from None
        missing = sorted(KOOPHONE_REQUIRED_TOOLS - available_tools)
        if missing:
            await self._transport.close()
            raise ProviderConfigurationError(
                "KooPhone MCP is missing required tools: " + ", ".join(missing)
            )

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
        await self._transport.close()
