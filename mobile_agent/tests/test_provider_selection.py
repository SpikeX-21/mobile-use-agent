# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     https://www.volcengine.com/docs/82379/1433703
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mobile_agent.agent.llm.provider import (
    DoubaoModelProvider,
    ProviderNotImplementedError,
    UnknownProviderError,
    create_model_provider,
)
from mobile_agent.agent.mobile.backend import McpDeviceBackend, create_device_backend
from mobile_agent.config.settings import Settings


class ProviderSelectionTests(unittest.TestCase):
    def test_defaults_preserve_the_doubao_mcp_runtime(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        self.assertEqual(settings.model_provider, "doubao")
        self.assertEqual(settings.device_provider, "mcp")

    def test_reads_server_side_provider_selection(self):
        with patch.dict(
            os.environ,
            {"MODEL_PROVIDER": "kimi", "DEVICE_PROVIDER": "adb"},
            clear=True,
        ):
            settings = Settings()

        self.assertEqual(settings.model_provider, "kimi")
        self.assertEqual(settings.device_provider, "adb")

    def test_creates_the_existing_doubao_and_mcp_adapters(self):
        model_provider = create_model_provider(
            "doubao", thread_id="thread-1", is_stream=False, llm=object()
        )
        device_backend = create_device_backend("mcp", tools=object())

        self.assertIsInstance(model_provider, DoubaoModelProvider)
        self.assertIsInstance(device_backend, McpDeviceBackend)

    def test_vendor_mcp_is_explicitly_not_implemented(self):
        with self.assertRaisesRegex(
            ProviderNotImplementedError, "vendor_mcp.*not implemented"
        ):
            create_device_backend("vendor_mcp")

    def test_unknown_providers_do_not_silently_fall_back(self):
        with self.assertRaises(UnknownProviderError):
            create_model_provider("unknown", thread_id="x", is_stream=False)
        with self.assertRaises(UnknownProviderError):
            create_device_backend("unknown")


if __name__ == "__main__":
    unittest.main()
