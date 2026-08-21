# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Security seams for the local AgentArts Runtime boundary."""

from __future__ import annotations

import os
from pathlib import Path
import ssl
import stat
from typing import Any, Awaitable, Callable

from starlette.responses import JSONResponse


# Four thousand Unicode characters can occupy more than four thousand bytes.
# Leave room for UTF-8 expansion and JSON framing while still rejecting large
# bodies before Starlette's JSON parser allocates an unbounded object.
MAX_REQUEST_BODY_BYTES = 32 * 1024
EXPECTED_MODEL_PROVIDER = "kimi"
EXPECTED_MODEL_ID = "kimi-k2.6"
EXPECTED_DEVICE_PROVIDER = "koophone_mcp"


class RuntimeConfigurationError(ValueError):
    """A safe, field-only startup configuration failure."""

    def __init__(self, field: str):
        self.field = field
        super().__init__(field)


class InvocationRequestGuard:
    """Enforce the local JSON and request-body contract before the SDK route."""

    def __init__(
        self,
        app: Callable[..., Awaitable[None]],
        *,
        max_body_bytes: int = MAX_REQUEST_BODY_BYTES,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    @staticmethod
    async def _invalid_request(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await JSONResponse(
            status_code=400,
            content={"error": "invalid_request"},
        )(scope, receive, send)

    @staticmethod
    def _headers(scope: dict[str, Any]) -> dict[str, str]:
        return {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("path") != "/invocations":
            await self.app(scope, receive, send)
            return

        headers = self._headers(scope)
        content_type = headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            await self._invalid_request(scope, receive, send)
            return

        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError):
                await self._invalid_request(scope, receive, send)
                return
            if declared_length < 0 or declared_length > self.max_body_bytes:
                await self._invalid_request(scope, receive, send)
                return

        body = bytearray()
        while True:
            message = await receive()
            message_type = message.get("type")
            if message_type == "http.disconnect":
                return
            if message_type != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > self.max_body_bytes:
                await self._invalid_request(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        delivered = False

        async def replay_body() -> dict[str, Any]:
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {
                "type": "http.request",
                "body": bytes(body),
                "more_body": False,
            }

        await self.app(scope, replay_body, send)


def validate_key_material(path: Path) -> None:
    """Require a regular, non-empty, owner-readable-only JKS file."""

    try:
        file_stat = path.lstat()
    except OSError:
        raise RuntimeConfigurationError("KOOPHONE_JKS_PATH") from None
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size <= 0:
        raise RuntimeConfigurationError("KOOPHONE_JKS_PATH")
    if stat.S_IMODE(file_stat.st_mode) != 0o400:
        raise RuntimeConfigurationError("KOOPHONE_JKS_PATH")
    if not os.access(path, os.R_OK):
        raise RuntimeConfigurationError("KOOPHONE_JKS_PATH")


def validate_runtime_configuration(settings: Any | None = None) -> None:
    """Validate only local Runtime prerequisites; never perform network I/O."""

    if settings is None:
        from mobile_agent.config.settings import get_settings

        settings = get_settings()

    model_provider = getattr(settings, "model_provider", "")
    if (
        not isinstance(model_provider, str)
        or model_provider.strip().lower() != EXPECTED_MODEL_PROVIDER
    ):
        raise RuntimeConfigurationError("MODEL_PROVIDER")
    device_provider = getattr(settings, "device_provider", "")
    if (
        not isinstance(device_provider, str)
        or device_provider.strip().lower() != EXPECTED_DEVICE_PROVIDER
    ):
        raise RuntimeConfigurationError("DEVICE_PROVIDER")

    try:
        kimi = settings.get_kimi_config()
        koophone = settings.get_koophone_config()
    except Exception:
        # ProviderConfigurationError and Pydantic errors are intentionally
        # collapsed to a field-level failure; their text may contain secrets.
        raise RuntimeConfigurationError("provider_configuration") from None

    if kimi.model != EXPECTED_MODEL_ID:
        raise RuntimeConfigurationError("KIMI_MODEL")
    if kimi.thinking_mode != "disabled":
        raise RuntimeConfigurationError("KIMI_THINKING_MODE")

    validate_key_material(koophone.jks_path)
    if koophone.ca_bundle_path is not None:
        try:
            ca_stat = koophone.ca_bundle_path.lstat()
            if (
                not stat.S_ISREG(ca_stat.st_mode)
                or ca_stat.st_size <= 0
                or not os.access(koophone.ca_bundle_path, os.R_OK)
            ):
                raise RuntimeConfigurationError("KOOPHONE_CA_BUNDLE")
            # Parse the bundle while starting so an invalid PEM cannot leave
            # the process healthy and fail only on its first invocation.
            ssl.create_default_context(cafile=str(koophone.ca_bundle_path))
        except RuntimeConfigurationError:
            raise
        except (OSError, ssl.SSLError, ValueError):
            raise RuntimeConfigurationError("KOOPHONE_CA_BUNDLE") from None
