# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
import inspect
import logging
from typing import Any, Awaitable, Callable, Protocol, TypeVar

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import ValidationError

from mobile_agent.agent.actions import (
    BackAction,
    CanonicalAction,
    ClearTextAction,
    CloseAppAction,
    FailAction,
    FinishAction,
    HomeAction,
    LaunchAppAction,
    ListAppsAction,
    MenuAction,
    SwipeAction,
    TapAction,
    TextInputAction,
    WaitAction,
)
from mobile_agent.agent.infra.model import ToolCall
from mobile_agent.agent.mobile.koophone_auth import (
    HuaweiIamTokenProvider,
    JksJwtProvider,
    KooPhoneAuthenticator,
)
from mobile_agent.agent.mobile.koophone_tls import build_tls_verification
from mobile_agent.agent.mobile.koophone_observation import (
    normalize_koophone_screenshot,
)
from mobile_agent.agent.mobile.result import (
    ActionResult,
    DeviceBackendError,
    DeviceErrorKind,
    classify_device_error,
)
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

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


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

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise ProviderConfigurationError("KooPhone MCP session is not connected")
        return await self._session.call_tool(name, arguments=arguments)


class KooPhoneDeviceBackend:
    name = "koophone_mcp"

    def __init__(
        self,
        config: KooPhoneConfig,
        *,
        authenticator: KooPhoneAuthHeaders | None = None,
        transport: KooPhoneMcpTransport | None = None,
    ) -> None:
        self._config = config
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
        final_error: DeviceBackendError | None = None
        for _ in range(2):
            try:
                response = await self._call_tool(
                    "get_screenshot", {}, retry_safe=True
                )
                return normalize_koophone_screenshot(response)
            except DeviceBackendError as error:
                final_error = error
            except Exception as error:
                final_error = DeviceBackendError(
                    "KooPhone screenshot request failed",
                    kind=classify_device_error(error),
                )
        assert final_error is not None
        raise final_error

    async def prepare_task(self, user_prompt: str) -> None:
        del user_prompt

    async def execute(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ActionResult:
        if isinstance(action, WaitAction):
            await asyncio.sleep(action.duration_ms / 1000)
            return ActionResult.success(
                f"Waited {action.duration_ms / 1000:g}s for the UI to settle"
            )
        if isinstance(action, (FinishAction, FailAction)):
            return ActionResult.success(f"KooPhone {action.type} handled locally")
        if not isinstance(
            action,
            (
                TapAction,
                SwipeAction,
                TextInputAction,
                ClearTextAction,
                HomeAction,
                BackAction,
                MenuAction,
                LaunchAppAction,
                CloseAppAction,
                ListAppsAction,
            ),
        ):
            raise ProviderNotImplementedError(
                "KooPhone action execution is delivered by Issue #15"
            )
        tool_call = self.to_tool_call(action, screenshot_dimensions)
        try:
            response = await self._call_tool(
                tool_call["name"], tool_call["arguments"] or {}, retry_safe=False
            )
            _ensure_koophone_tool_success(response)
        except KooPhoneOperationOutcomeUncertain:
            return ActionResult.ambiguous(
                f"KooPhone {action.type} outcome is uncertain after authentication rejection",
                DeviceErrorKind.COMMAND_FAILED,
            )
        except ValidationError:
            return ActionResult.ambiguous(
                f"KooPhone {action.type} outcome is uncertain after malformed MCP receipt",
                DeviceErrorKind.COMMAND_FAILED,
            )
        except Exception as error:
            error_kind = classify_device_error(error)
            if error_kind is DeviceErrorKind.TIMEOUT:
                return ActionResult.ambiguous(
                    f"KooPhone {action.type} result is unknown after timeout",
                    error_kind,
                )
            return ActionResult.failed(f"KooPhone {action.type} failed", error_kind)
        if isinstance(action, ListAppsAction):
            return ActionResult.success(_list_apps_result_message(response))
        return ActionResult.success(f"KooPhone {action.type} dispatched")

    def to_tool_call(
        self,
        action: CanonicalAction,
        screenshot_dimensions: tuple[int, int],
    ) -> ToolCall:
        if isinstance(action, TapAction):
            width, height = screenshot_dimensions
            return {
                "name": "tap",
                "arguments": {
                    "x": _to_pixel(action.x, width),
                    "y": _to_pixel(action.y, height),
                },
            }
        if isinstance(action, SwipeAction):
            width, height = screenshot_dimensions
            return {
                "name": "swipe",
                "arguments": {
                    "startX": _to_pixel(action.start_x, width),
                    "startY": _to_pixel(action.start_y, height),
                    "endX": _to_pixel(action.end_x, width),
                    "endY": _to_pixel(action.end_y, height),
                    "durationMs": action.duration_ms,
                },
            }
        if isinstance(action, TextInputAction):
            return {"name": "input_text", "arguments": {"text": action.text}}
        if isinstance(action, ClearTextAction):
            return {"name": "clear_text", "arguments": {}}
        if isinstance(action, (HomeAction, BackAction, MenuAction)):
            key = {"home": "HOME", "back": "BACK", "menu": "MENU"}[action.type]
            return {"name": "send_key", "arguments": {"key": key}}
        if isinstance(action, LaunchAppAction):
            return {
                "name": "start_app",
                "arguments": {"packageName": action.package_name},
            }
        if isinstance(action, CloseAppAction):
            return {
                "name": "stop_app",
                "arguments": {"packageName": action.package_name},
            }
        if isinstance(action, ListAppsAction):
            arguments = (
                {}
                if action.ignore_system_apps is None
                else {"ignoreSystemApp": action.ignore_system_apps}
            )
            return {"name": "get_installed_apps", "arguments": arguments}
        if isinstance(action, WaitAction):
            return {"name": "wait", "arguments": {"t": action.duration_ms / 1000}}
        if isinstance(action, FinishAction):
            return {"name": "finished", "arguments": {"content": action.summary}}
        if isinstance(action, FailAction):
            return {"name": "call_user", "arguments": {"content": action.reason}}
        raise ProviderNotImplementedError(
            "KooPhone action mapping is delivered by Issue #15"
        )

    async def _call_tool(
        self, name: str, arguments: dict[str, Any], *, retry_safe: bool
    ) -> Any:
        if name not in KOOPHONE_REQUIRED_TOOLS:
            raise ProviderConfigurationError(
                f"KooPhone tool is not allowlisted: {name}"
            )
        server_arguments = {**arguments, "instanceId": self._config.instance_id}
        return await self.run_authenticated_operation(
            lambda: self._transport.call_tool(name, server_arguments),
            retry_safe=retry_safe,
        )

    async def verify_completion(self, action: CanonicalAction) -> bool | None:
        del action
        return None

    async def close(self) -> None:
        await self._close_transport()


def _to_pixel(coordinate: int, size: int) -> int:
    if size <= 0:
        raise ValueError("Screenshot dimensions must be positive")
    return min(size - 1, max(0, int(coordinate * size / 1000)))


def _ensure_koophone_tool_success(response: Any) -> None:
    if getattr(response, "isError", False) or getattr(response, "is_error", False):
        raise DeviceBackendError(
            "KooPhone MCP reported a tool failure",
            kind=DeviceErrorKind.COMMAND_FAILED,
        )


def _list_apps_result_message(response: Any) -> str:
    content = getattr(response, "content", None)
    if isinstance(content, list) and len(content) == 1:
        text = getattr(content[0], "text", None)
        if isinstance(text, str) and text.strip():
            return f"KooPhone list_apps result: {text.strip()}"
    return "KooPhone list_apps completed"
