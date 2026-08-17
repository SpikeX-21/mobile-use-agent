# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import httpx
import jks
import jwt
from cryptography.hazmat.primitives import serialization
from pydantic import SecretStr

from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.config.settings import KooPhoneConfig


@dataclass(frozen=True)
class ExpiringSecret:
    value: SecretStr
    expires_at: datetime


class HuaweiIamTokenProvider:
    """Fetch a scoped Huawei IAM token without retaining the password payload."""

    def __init__(
        self,
        config: KooPhoneConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client

    async def fetch_token(self) -> ExpiringSecret:
        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "domain": {"name": self._config.iam_domain},
                            "name": self._config.iam_username,
                            "password": self._config.iam_password.get_secret_value(),
                        }
                    },
                },
                "scope": {"project": {"name": self._config.iam_project}},
            }
        }

        try:
            if self._client is not None:
                response = await self._client.post(
                    self._config.iam_auth_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
            else:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        self._config.iam_auth_url,
                        json=payload,
                        headers={"Content-Type": "application/json"},
                    )
        except httpx.HTTPError:
            raise ProviderConfigurationError("Huawei IAM request failed") from None

        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderConfigurationError(
                f"Huawei IAM authentication failed with status {response.status_code}"
            )

        token = response.headers.get("X-Subject-Token")
        try:
            expires_at_text = response.json()["token"]["expires_at"]
            expires_at = datetime.fromisoformat(
                str(expires_at_text).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            raise ProviderConfigurationError(
                "Huawei IAM response is missing a valid token expiry"
            ) from None
        if not token:
            raise ProviderConfigurationError(
                "Huawei IAM response is missing X-Subject-Token"
            )
        if expires_at.tzinfo is None:
            raise ProviderConfigurationError(
                "Huawei IAM token expiry must include a timezone"
            )
        return ExpiringSecret(value=SecretStr(token), expires_at=expires_at)


class JksJwtProvider:
    """Issue the short-lived KooPhone JWT from a configured JKS key entry."""

    def __init__(
        self,
        config: KooPhoneConfig,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def issue_token(self) -> ExpiringSecret:
        try:
            keystore = jks.KeyStore.load(
                str(self._config.jks_path),
                self._config.jks_store_password.get_secret_value(),
            )
            entry = keystore.private_keys[self._config.jks_alias.lower()]
            if not entry.is_decrypted():
                entry.decrypt(self._config.jks_key_password.get_secret_value())
            private_key = serialization.load_der_private_key(
                entry.pkey_pkcs8,
                password=None,
            )
        except Exception:
            raise ProviderConfigurationError(
                "Unable to load the configured KooPhone JKS private key"
            ) from None

        issued_at = self._clock()
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        else:
            issued_at = issued_at.astimezone(timezone.utc)
        expires_at = issued_at + timedelta(minutes=self._config.jwt_ttl_minutes)
        claims = {
            "instanceId": self._config.instance_id,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        try:
            token = jwt.encode(claims, private_key, algorithm="RS256")
        except Exception:
            raise ProviderConfigurationError(
                "Unable to sign the configured KooPhone JWT"
            ) from None
        return ExpiringSecret(value=SecretStr(token), expires_at=expires_at)


class IamTokenSource(Protocol):
    async def fetch_token(self) -> ExpiringSecret: ...


class JwtTokenSource(Protocol):
    def issue_token(self) -> ExpiringSecret: ...


class KooPhoneAuthenticator:
    """Create the dual-header credentials required by KooPhone MCP."""

    def __init__(
        self,
        *,
        iam_provider: IamTokenSource,
        jwt_provider: JwtTokenSource,
    ) -> None:
        self._iam_provider = iam_provider
        self._jwt_provider = jwt_provider

    async def create_headers(self) -> dict[str, str]:
        iam_token, jwt_token = await asyncio.gather(
            self._iam_provider.fetch_token(),
            asyncio.to_thread(self._jwt_provider.issue_token),
        )
        return {
            "Authorization": f"Bearer {jwt_token.value.get_secret_value()}",
            "x-auth-token": iam_token.value.get_secret_value(),
        }
