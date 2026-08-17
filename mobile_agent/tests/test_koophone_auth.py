# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import ssl
import tempfile
import traceback
import unittest
from unittest.mock import patch

import httpx
import jks
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from mobile_agent.agent.mobile.koophone_auth import (
    ExpiringSecret,
    HuaweiIamTokenProvider,
    JksJwtProvider,
    KooPhoneAuthenticator,
)
from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.config.settings import KooPhoneConfig


def koophone_config(**overrides) -> KooPhoneConfig:
    values = {
        "environment": "poc",
        "mcp_url": "https://mcp.example.test/mcp",
        "instance_id": "instance-test-1",
        "tls_verify": False,
        "iam_auth_url": "https://iam.example.test/v3/auth/tokens",
        "iam_domain": "domain-test",
        "iam_username": "user-test",
        "iam_password": "iam-secret-value",
        "iam_project": "region-test",
        "jks_path": Path("/tmp/test-koophone.jks"),
        "jks_store_password": "store-secret-value",
        "jks_key_password": "key-secret-value",
        "jks_alias": "koophone",
        "jwt_ttl_minutes": 1440,
    }
    values.update(overrides)
    return KooPhoneConfig(**values)


class KooPhoneIamTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_subject_token_and_server_expiry_without_cookie(self):
        captured = {}

        def respond(request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content)
            return httpx.Response(
                201,
                headers={"X-Subject-Token": "iam-token-value"},
                json={"token": {"expires_at": "2030-01-02T03:04:05.000000Z"}},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as client:
            result = await HuaweiIamTokenProvider(
                koophone_config(), client=client
            ).fetch_token()

        self.assertEqual(result.value.get_secret_value(), "iam-token-value")
        self.assertEqual(
            result.expires_at,
            datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        )
        self.assertNotIn("cookie", captured["headers"])
        self.assertEqual(
            captured["json"],
            {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "domain": {"name": "domain-test"},
                                "name": "user-test",
                                "password": "iam-secret-value",
                            }
                        },
                    },
                    "scope": {"project": {"name": "region-test"}},
                }
            },
        )

    async def test_authentication_failure_is_redacted(self):
        def respond(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                text="iam-secret-value jwt-token-value",
                request=request,
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as client:
            with self.assertRaises(ProviderConfigurationError) as raised:
                await HuaweiIamTokenProvider(
                    koophone_config(), client=client
                ).fetch_token()

        message = str(raised.exception)
        self.assertIn("status 401", message)
        self.assertNotIn("iam-secret-value", message)
        self.assertNotIn("jwt-token-value", message)

    async def test_transport_failure_cannot_echo_the_iam_password(self):
        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                "upstream echoed iam-secret-value",
                request=request,
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(fail)
        ) as client:
            with self.assertRaises(ProviderConfigurationError) as raised:
                await HuaweiIamTokenProvider(
                    koophone_config(), client=client
                ).fetch_token()

        message = str(raised.exception)
        self.assertIn("Huawei IAM request failed", message)
        self.assertNotIn("iam-secret-value", message)
        rendered_traceback = "".join(
            traceback.format_exception(raised.exception)
        )
        self.assertNotIn("iam-secret-value", rendered_traceback)

    async def test_iam_client_uses_the_configured_custom_ca_policy(self):
        captured = {}

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return httpx.Response(
                    201,
                    headers={"X-Subject-Token": "iam-token-value"},
                    json={"token": {"expires_at": "2030-01-02T03:04:05Z"}},
                )

        def client_factory(**kwargs):
            captured.update(kwargs)
            return FakeClient()

        with tempfile.NamedTemporaryFile() as ca_file:
            config = koophone_config(
                tls_verify=True,
                ca_bundle_path=Path(ca_file.name),
            )
            with patch(
                "mobile_agent.agent.mobile.koophone_tls.ssl.create_default_context",
                return_value=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            ) as create_context:
                await HuaweiIamTokenProvider(
                    config, client_factory=client_factory
                ).fetch_token()

        create_context.assert_called_once_with(cafile=ca_file.name)
        self.assertIsInstance(captured["verify"], ssl.SSLContext)


class KooPhoneJwtTests(unittest.TestCase):
    def test_signs_rs256_jwt_with_only_instance_and_time_claims(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_der = private_key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        entry = jks.PrivateKeyEntry.new("koophone", [], private_der)
        keystore = jks.KeyStore.new("jks", [entry])
        now = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.jks"
            path.write_bytes(keystore.saves("test-password"))
            provider = JksJwtProvider(
                koophone_config(
                    jks_path=path,
                    jks_store_password="test-password",
                    jks_key_password="test-password",
                ),
                clock=lambda: now,
            )
            result = provider.issue_token()

        claims = jwt.decode(
            result.value.get_secret_value(),
            private_key.public_key(),
            algorithms=["RS256"],
            options={"verify_exp": False, "verify_iat": False},
        )
        self.assertEqual(
            claims,
            {
                "instanceId": "instance-test-1",
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=1440)).timestamp()),
            },
        )
        self.assertEqual(result.expires_at, now + timedelta(minutes=1440))

    def test_invalid_jks_failure_does_not_expose_passwords_or_file_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.jks"
            path.write_bytes(b"private-key-like-test-bytes")
            provider = JksJwtProvider(
                koophone_config(
                    jks_path=path,
                    jks_store_password="store-secret-value",
                    jks_key_password="key-secret-value",
                )
            )

            with self.assertRaises(ProviderConfigurationError) as raised:
                provider.issue_token()

        message = str(raised.exception)
        self.assertIn("KooPhone JKS private key", message)
        self.assertNotIn("store-secret-value", message)
        self.assertNotIn("key-secret-value", message)
        self.assertNotIn("private-key-like-test-bytes", message)


class StaticIamTokenProvider:
    async def fetch_token(self) -> ExpiringSecret:
        return ExpiringSecret(
            value=SecretStr("iam-token-value"),
            expires_at=datetime(2030, 1, 2, tzinfo=timezone.utc),
        )


class StaticJwtProvider:
    def issue_token(self) -> ExpiringSecret:
        return ExpiringSecret(
            value=SecretStr("jwt-token-value"),
            expires_at=datetime(2030, 1, 2, tzinfo=timezone.utc),
        )


class KooPhoneAuthenticatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_builds_both_mcp_authentication_headers(self):
        headers = await KooPhoneAuthenticator(
            iam_provider=StaticIamTokenProvider(),
            jwt_provider=StaticJwtProvider(),
        ).create_headers()

        self.assertEqual(
            headers,
            {
                "Authorization": "Bearer jwt-token-value",
                "x-auth-token": "iam-token-value",
            },
        )
        self.assertNotIn("instanceId", headers)

    async def test_caches_both_tokens_until_the_early_refresh_window(self):
        now = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        class CountingIamTokenProvider:
            calls = 0

            async def fetch_token(self) -> ExpiringSecret:
                self.calls += 1
                return ExpiringSecret(
                    value=SecretStr(f"iam-token-{self.calls}"),
                    expires_at=now + timedelta(minutes=10),
                )

        class CountingJwtTokenProvider:
            calls = 0

            def issue_token(self) -> ExpiringSecret:
                self.calls += 1
                return ExpiringSecret(
                    value=SecretStr(f"jwt-token-{self.calls}"),
                    expires_at=now + timedelta(minutes=10),
                )

        iam_provider = CountingIamTokenProvider()
        jwt_provider = CountingJwtTokenProvider()
        authenticator = KooPhoneAuthenticator(
            iam_provider=iam_provider,
            jwt_provider=jwt_provider,
            clock=lambda: now,
        )

        first_headers = await authenticator.create_headers()
        second_headers = await authenticator.create_headers()

        self.assertEqual(first_headers, second_headers)
        self.assertEqual(iam_provider.calls, 1)
        self.assertEqual(jwt_provider.calls, 1)

    async def test_concurrent_refreshes_are_single_flight(self):
        now = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        class SlowIamTokenProvider:
            calls = 0

            async def fetch_token(self) -> ExpiringSecret:
                self.calls += 1
                await asyncio.sleep(0)
                return ExpiringSecret(
                    value=SecretStr("iam-token-value"),
                    expires_at=now + timedelta(minutes=10),
                )

        class CountingJwtTokenProvider:
            calls = 0

            def issue_token(self) -> ExpiringSecret:
                self.calls += 1
                return ExpiringSecret(
                    value=SecretStr("jwt-token-value"),
                    expires_at=now + timedelta(minutes=10),
                )

        iam_provider = SlowIamTokenProvider()
        jwt_provider = CountingJwtTokenProvider()
        authenticator = KooPhoneAuthenticator(
            iam_provider=iam_provider,
            jwt_provider=jwt_provider,
            clock=lambda: now,
        )

        headers = await asyncio.gather(
            *(authenticator.create_headers() for _ in range(10))
        )

        self.assertEqual(len(headers), 10)
        self.assertTrue(all(header == headers[0] for header in headers))
        self.assertEqual(iam_provider.calls, 1)
        self.assertEqual(jwt_provider.calls, 1)

    async def test_refreshes_tokens_five_minutes_before_expiry_and_after_invalidation(self):
        now = datetime(2030, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        current_time = [now]

        class CountingIamTokenProvider:
            calls = 0

            async def fetch_token(self) -> ExpiringSecret:
                self.calls += 1
                return ExpiringSecret(
                    value=SecretStr(f"iam-token-{self.calls}"),
                    expires_at=current_time[0] + timedelta(minutes=10),
                )

        class CountingJwtTokenProvider:
            calls = 0

            def issue_token(self) -> ExpiringSecret:
                self.calls += 1
                return ExpiringSecret(
                    value=SecretStr(f"jwt-token-{self.calls}"),
                    expires_at=current_time[0] + timedelta(minutes=10),
                )

        iam_provider = CountingIamTokenProvider()
        jwt_provider = CountingJwtTokenProvider()
        authenticator = KooPhoneAuthenticator(
            iam_provider=iam_provider,
            jwt_provider=jwt_provider,
            clock=lambda: current_time[0],
        )

        await authenticator.create_headers()
        current_time[0] += timedelta(minutes=5)
        refreshed_headers = await authenticator.create_headers()
        await authenticator.invalidate()
        invalidated_headers = await authenticator.create_headers()

        self.assertEqual(refreshed_headers["x-auth-token"], "iam-token-2")
        self.assertEqual(refreshed_headers["Authorization"], "Bearer jwt-token-2")
        self.assertEqual(invalidated_headers["x-auth-token"], "iam-token-3")
        self.assertEqual(invalidated_headers["Authorization"], "Bearer jwt-token-3")


if __name__ == "__main__":
    unittest.main()
