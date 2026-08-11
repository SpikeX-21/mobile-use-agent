# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from types import SimpleNamespace
import unittest

from mobile_agent.agent.mobile.result import DeviceBackendError, DeviceErrorKind
from mobile_agent.agent.tools.mcp import MCPHub


class ErrorSession:
    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            isError=True,
            content=[
                SimpleNamespace(
                    type="text",
                    text=(
                        "rpc error: code = DeadlineExceeded desc = "
                        "context deadline exceeded"
                    ),
                )
            ],
        )


class OutcomeUnknownSession:
    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            isError=True,
            content=[
                SimpleNamespace(
                    type="text",
                    text=(
                        '{"code":"ACEP_COMMAND_OUTCOME_UNKNOWN",'
                        '"message":"command outcome is unknown"}'
                    ),
                )
            ],
        )


class McpErrorClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_deadline_error_payload_becomes_typed_timeout(self):
        hub = MCPHub()
        hub.sessions["mobile"] = ErrorSession()

        with self.assertRaises(DeviceBackendError) as raised:
            await hub.call_tool("mobile", "tap", {"x": 1, "y": 2})

        self.assertEqual(raised.exception.kind, DeviceErrorKind.TIMEOUT)

    async def test_structured_outcome_unknown_payload_becomes_typed_timeout(self):
        hub = MCPHub()
        hub.sessions["mobile"] = OutcomeUnknownSession()

        with self.assertRaises(DeviceBackendError) as raised:
            await hub.call_tool("mobile", "tap", {"x": 1, "y": 2})

        self.assertEqual(raised.exception.kind, DeviceErrorKind.TIMEOUT)


if __name__ == "__main__":
    unittest.main()
