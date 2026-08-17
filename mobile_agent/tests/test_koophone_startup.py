# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import traceback
import unittest

import httpx
from mcp.server.fastmcp import FastMCP

from mobile_agent.agent.mobile.koophone import (
    KOOPHONE_REQUIRED_TOOLS,
    KooPhoneDeviceBackend,
    StreamableHttpKooPhoneTransport,
)
from mobile_agent.agent.provider import ProviderConfigurationError
from tests.test_koophone_auth import koophone_config


class StaticAuthenticator:
    async def create_headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer jwt-token-value",
            "x-auth-token": "iam-token-value",
        }


class RecordingMcpTransport:
    def __init__(self, tools=KOOPHONE_REQUIRED_TOOLS):
        self.tools = set(tools)
        self.headers = None
        self.closed = False

    async def connect(self, headers: dict[str, str]) -> set[str]:
        self.headers = headers
        return self.tools

    async def close(self) -> None:
        self.closed = True


class SecretEchoingMcpTransport(RecordingMcpTransport):
    async def connect(self, headers: dict[str, str]) -> set[str]:
        del headers
        raise RuntimeError("upstream echoed jwt-token-value iam-token-value")


class KooPhoneStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_mcp_initialize_and_tools_list_use_dual_headers(self):
        server = FastMCP("koophone-test", stateless_http=True, json_response=True)

        async def tool_stub() -> str:
            return "ok"

        for tool_name in KOOPHONE_REQUIRED_TOOLS:
            server.add_tool(tool_stub, name=tool_name)
        app = server.streamable_http_app()
        observed_headers = []

        def client_factory(headers=None, timeout=None, auth=None):
            observed_headers.append(dict(headers or {}))
            return httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers=headers,
                timeout=timeout,
                auth=auth,
                follow_redirects=True,
            )

        transport = StreamableHttpKooPhoneTransport(
            koophone_config(
                mcp_url="http://test/mcp",
                tls_verify=True,
            ),
            http_client_factory=client_factory,
        )
        headers = {
            "Authorization": "Bearer jwt-token-value",
            "x-auth-token": "iam-token-value",
        }

        async with app.router.lifespan_context(app):
            tools = await transport.connect(headers)
            await transport.close()

        self.assertEqual(tools, set(KOOPHONE_REQUIRED_TOOLS))
        self.assertEqual(len(observed_headers), 1)
        self.assertEqual(
            {
                name: observed_headers[0][name]
                for name in ("Authorization", "x-auth-token")
            },
            headers,
        )

    async def test_initializes_with_dual_headers_and_required_tools(self):
        transport = RecordingMcpTransport()
        backend = KooPhoneDeviceBackend(
            koophone_config(),
            authenticator=StaticAuthenticator(),
            transport=transport,
        )

        await backend.initialize(pod_id="must-be-ignored")

        self.assertEqual(backend.name, "koophone_mcp")
        self.assertEqual(
            transport.headers,
            {
                "Authorization": "Bearer jwt-token-value",
                "x-auth-token": "iam-token-value",
            },
        )

    async def test_missing_required_tool_fails_startup_and_closes_transport(self):
        transport = RecordingMcpTransport(
            KOOPHONE_REQUIRED_TOOLS - {"get_screenshot"}
        )
        backend = KooPhoneDeviceBackend(
            koophone_config(),
            authenticator=StaticAuthenticator(),
            transport=transport,
        )

        with self.assertRaisesRegex(
            ProviderConfigurationError,
            "missing required tools: get_screenshot",
        ):
            await backend.initialize()

        self.assertTrue(transport.closed)

    async def test_probe_failure_cannot_echo_authentication_headers(self):
        backend = KooPhoneDeviceBackend(
            koophone_config(),
            authenticator=StaticAuthenticator(),
            transport=SecretEchoingMcpTransport(),
        )

        with self.assertRaises(ProviderConfigurationError) as raised:
            await backend.initialize()

        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertIn("KooPhone MCP startup probe failed", rendered)
        self.assertNotIn("jwt-token-value", rendered)
        self.assertNotIn("iam-token-value", rendered)


if __name__ == "__main__":
    unittest.main()
