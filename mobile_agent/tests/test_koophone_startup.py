# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import base64
import io
import traceback
import unittest
from types import SimpleNamespace

import httpx
from mcp.server.fastmcp import FastMCP
from PIL import Image

from mobile_agent.agent.actions import HomeAction, TapAction
from mobile_agent.agent.mobile.koophone import (
    KOOPHONE_REQUIRED_TOOLS,
    KooPhoneDeviceBackend,
    KooPhoneOperationOutcomeUncertain,
    StreamableHttpKooPhoneTransport,
)
from mobile_agent.agent.provider import ProviderConfigurationError
from tests.test_koophone_auth import koophone_config


def screenshot_base64(width: int = 80, height: int = 60) -> str:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


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


class RotatingAuthenticator:
    def __init__(self):
        self.header_calls = 0
        self.invalidations = 0
        self._version = 1

    async def create_headers(self) -> dict[str, str]:
        self.header_calls += 1
        return {
            "Authorization": f"Bearer jwt-token-{self._version}",
            "x-auth-token": f"iam-token-{self._version}",
        }

    async def invalidate(self) -> None:
        self.invalidations += 1
        self._version += 1


def authentication_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://mcp.example.test/mcp")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("redacted upstream error", request=request, response=response)


class SequenceMcpTransport(RecordingMcpTransport):
    def __init__(self, outcomes):
        super().__init__()
        self._outcomes = list(outcomes)
        self.connect_calls = 0

    async def connect(self, headers: dict[str, str]) -> set[str]:
        self.connect_calls += 1
        self.headers = headers
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class ToolCallingMcpTransport(RecordingMcpTransport):
    def __init__(self, tool_results):
        super().__init__()
        self.tool_results = list(tool_results)
        self.tool_calls = []

    async def call_tool(self, name, arguments):
        self.tool_calls.append((name, arguments))
        return self.tool_results.pop(0)


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

    async def test_first_authentication_rejection_refreshes_and_reconnects_once(self):
        authenticator = RotatingAuthenticator()
        transport = SequenceMcpTransport(
            [authentication_error(401), set(KOOPHONE_REQUIRED_TOOLS)]
        )
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=authenticator, transport=transport
        )

        await backend.initialize()

        self.assertEqual(transport.connect_calls, 2)
        self.assertEqual(authenticator.invalidations, 1)
        self.assertEqual(authenticator.header_calls, 2)
        self.assertEqual(transport.headers["Authorization"], "Bearer jwt-token-2")

    async def test_second_authentication_rejection_fails_without_a_third_connect(self):
        authenticator = RotatingAuthenticator()
        transport = SequenceMcpTransport(
            [authentication_error(401), authentication_error(403)]
        )
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=authenticator, transport=transport
        )

        with self.assertRaisesRegex(ProviderConfigurationError, "startup probe failed"):
            await backend.initialize()

        self.assertEqual(transport.connect_calls, 2)
        self.assertEqual(authenticator.invalidations, 2)
        self.assertEqual(authenticator.header_calls, 2)

    async def test_non_authentication_failure_is_not_retried_or_invalidated(self):
        authenticator = RotatingAuthenticator()
        transport = SequenceMcpTransport([authentication_error(503)])
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=authenticator, transport=transport
        )

        with self.assertRaisesRegex(ProviderConfigurationError, "startup probe failed"):
            await backend.initialize()

        self.assertEqual(transport.connect_calls, 1)
        self.assertEqual(authenticator.invalidations, 0)

    async def test_read_operation_recovers_once_after_authentication_rejection(self):
        authenticator = RotatingAuthenticator()
        transport = SequenceMcpTransport(
            [set(KOOPHONE_REQUIRED_TOOLS), set(KOOPHONE_REQUIRED_TOOLS)]
        )
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=authenticator, transport=transport
        )
        await backend.initialize()
        operation_calls = 0

        async def read_operation() -> str:
            nonlocal operation_calls
            operation_calls += 1
            if operation_calls == 1:
                raise authentication_error(401)
            return "fresh observation"

        result = await backend.run_authenticated_operation(
            read_operation, retry_safe=True
        )

        self.assertEqual(result, "fresh observation")
        self.assertEqual(operation_calls, 2)
        self.assertEqual(transport.connect_calls, 2)
        self.assertEqual(authenticator.invalidations, 1)

    async def test_side_effect_authentication_rejection_is_uncertain_and_not_replayed(self):
        authenticator = RotatingAuthenticator()
        transport = SequenceMcpTransport([set(KOOPHONE_REQUIRED_TOOLS)])
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=authenticator, transport=transport
        )
        await backend.initialize()
        operation_calls = 0

        async def side_effect_operation() -> None:
            nonlocal operation_calls
            operation_calls += 1
            raise authentication_error(403)

        with self.assertRaisesRegex(
            KooPhoneOperationOutcomeUncertain, "outcome is uncertain"
        ):
            await backend.run_authenticated_operation(
                side_effect_operation, retry_safe=False
            )

        self.assertEqual(operation_calls, 1)
        self.assertEqual(transport.connect_calls, 1)
        self.assertEqual(authenticator.invalidations, 1)

    async def test_reconnection_failure_stops_read_operation_without_retrying_it(self):
        authenticator = RotatingAuthenticator()
        transport = SequenceMcpTransport(
            [set(KOOPHONE_REQUIRED_TOOLS), authentication_error(403)]
        )
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=authenticator, transport=transport
        )
        await backend.initialize()
        operation_calls = 0

        async def read_operation() -> None:
            nonlocal operation_calls
            operation_calls += 1
            raise authentication_error(401)

        with self.assertRaisesRegex(ProviderConfigurationError, "startup probe failed"):
            await backend.run_authenticated_operation(read_operation, retry_safe=True)

        self.assertEqual(operation_calls, 1)
        self.assertEqual(transport.connect_calls, 2)
        self.assertEqual(authenticator.invalidations, 2)

    async def test_screenshot_uses_only_get_screenshot_and_injects_instance_id(self):
        encoded = screenshot_base64()
        transport = ToolCallingMcpTransport(
            [SimpleNamespace(content=[SimpleNamespace(text=encoded)])]
        )
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=StaticAuthenticator(), transport=transport
        )
        await backend.initialize()

        observation = await backend.take_screenshot()

        self.assertEqual(observation["screenshot_dimensions"], (80, 60))
        self.assertTrue(observation["screenshot"].startswith("data:image/png;base64,"))
        self.assertEqual(
            transport.tool_calls,
            [("get_screenshot", {"instanceId": "instance-test-1"})],
        )

    async def test_tap_and_home_are_mapped_without_exposing_instance_id_to_agent(self):
        transport = ToolCallingMcpTransport(["tap ok", "home ok"])
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=StaticAuthenticator(), transport=transport
        )
        await backend.initialize()

        tap_call = backend.to_tool_call(TapAction(x=1000, y=500), (80, 60))
        await backend.execute(TapAction(x=1000, y=500), (80, 60))
        await backend.execute(HomeAction(), (80, 60))

        self.assertEqual(tap_call, {"name": "tap", "arguments": {"x": 79, "y": 30}})
        self.assertNotIn("instanceId", tap_call["arguments"])
        self.assertEqual(
            transport.tool_calls,
            [
                ("tap", {"instanceId": "instance-test-1", "x": 79, "y": 30}),
                ("send_key", {"instanceId": "instance-test-1", "key": "HOME"}),
            ],
        )

    async def test_configured_instance_id_cannot_be_overridden_by_tool_arguments(self):
        transport = ToolCallingMcpTransport(["tap ok"])
        backend = KooPhoneDeviceBackend(
            koophone_config(), authenticator=StaticAuthenticator(), transport=transport
        )
        await backend.initialize()

        await backend._call_tool(
            "tap", {"instanceId": "other-instance", "x": 1, "y": 2}, retry_safe=False
        )

        self.assertEqual(
            transport.tool_calls,
            [("tap", {"instanceId": "instance-test-1", "x": 1, "y": 2})],
        )


if __name__ == "__main__":
    unittest.main()
