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
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mobile_agent.agent.llm.provider import (
    DoubaoModelProvider,
    UnknownProviderError,
    create_model_provider,
)
from mobile_agent.agent.provider import ProviderConfigurationError, ProviderNotImplementedError
from mobile_agent.agent.mobile.backend import McpDeviceBackend, create_device_backend
from mobile_agent.agent.mobile.koophone import KooPhoneDeviceBackend
from mobile_agent.config.settings import AdbConfig, KimiConfig, KooPhoneConfig, Settings
from pydantic import ValidationError
from tests.test_koophone_auth import koophone_config


class ProviderSelectionTests(unittest.TestCase):
    def test_reads_complete_koophone_configuration_without_exposing_secrets(self):
        environment = {
            "ENV": "poc",
            "KOOPHONE_MCP_URL": "https://mcp.example.test/mcp",
            "KOOPHONE_INSTANCE_ID": "instance-test-1",
            "KOOPHONE_INPUT_WIDTH": "1080",
            "KOOPHONE_INPUT_HEIGHT": "1920",
            "KOOPHONE_TLS_VERIFY": "false",
            "KOOPHONE_IAM_AUTH_URL": "https://iam.example.test/v3/auth/tokens",
            "KOOPHONE_IAM_DOMAIN": "domain-test",
            "KOOPHONE_IAM_USERNAME": "user-test",
            "KOOPHONE_IAM_PASSWORD": "iam-secret-value",
            "KOOPHONE_IAM_PROJECT": "region-test",
            "KOOPHONE_JKS_PATH": "/tmp/test-koophone.jks",
            "KOOPHONE_JKS_STORE_PASSWORD": "store-secret-value",
            "KOOPHONE_JKS_KEY_PASSWORD": "key-secret-value",
            "KOOPHONE_JKS_ALIAS": "koophone",
            "KOOPHONE_JWT_TTL_MINUTES": "1440",
        }

        with patch.dict(os.environ, environment, clear=True):
            config = Settings().get_koophone_config()

        self.assertEqual(str(config.mcp_url), "https://mcp.example.test/mcp")
        self.assertEqual(config.instance_id, "instance-test-1")
        self.assertEqual((config.input_width, config.input_height), (1080, 1920))
        self.assertFalse(config.tls_verify)
        self.assertEqual(config.jwt_ttl_minutes, 1440)
        self.assertNotIn("iam-secret-value", repr(config))
        self.assertNotIn("store-secret-value", repr(config))
        self.assertNotIn("key-secret-value", repr(config))

    def test_koophone_configuration_reports_missing_names_not_secret_values(self):
        with patch.dict(os.environ, {"ENV": "poc"}, clear=True):
            settings = Settings(device_provider="koophone_mcp")

        with self.assertRaises(ProviderConfigurationError) as raised:
            settings.get_koophone_config()

        message = str(raised.exception)
        self.assertIn("KOOPHONE_MCP_URL", message)
        self.assertIn("KOOPHONE_IAM_PASSWORD", message)
        self.assertNotIn("iam-secret-value", message)
        self.assertNotIn("store-secret-value", message)
        self.assertNotIn("key-secret-value", message)

    def test_koophone_insecure_tls_is_rejected_outside_poc(self):
        environment = {
            "ENV": "production",
            "KOOPHONE_MCP_URL": "https://mcp.example.test/mcp",
            "KOOPHONE_INSTANCE_ID": "instance-test-1",
            "KOOPHONE_INPUT_WIDTH": "1080",
            "KOOPHONE_INPUT_HEIGHT": "1920",
            "KOOPHONE_TLS_VERIFY": "false",
            "KOOPHONE_IAM_AUTH_URL": "https://iam.example.test/v3/auth/tokens",
            "KOOPHONE_IAM_DOMAIN": "domain-test",
            "KOOPHONE_IAM_USERNAME": "user-test",
            "KOOPHONE_IAM_PASSWORD": "iam-secret-value",
            "KOOPHONE_IAM_PROJECT": "region-test",
            "KOOPHONE_JKS_PATH": "/tmp/test-koophone.jks",
            "KOOPHONE_JKS_STORE_PASSWORD": "store-secret-value",
            "KOOPHONE_JKS_KEY_PASSWORD": "key-secret-value",
        }

        with patch.dict(os.environ, environment, clear=True):
            settings = Settings(device_provider="koophone_mcp")

        with self.assertRaisesRegex(
            ProviderConfigurationError,
            "KOOPHONE_TLS_VERIFY=false.*ENV=poc",
        ):
            settings.get_koophone_config()

    def test_koophone_config_cannot_bypass_tls_gate_when_built_directly(self):
        with self.assertRaisesRegex(ValidationError, "ENV=poc"):
            koophone_config(environment="production", tls_verify=False)

    def test_file_configuration_cannot_supply_koophone_secrets(self):
        settings = Settings(
            kimi_api_key="env-kimi-secret",
            adb_vendor_keys="env-adb-key-path",
            koophone_iam_password="env-iam-secret",
            koophone_jks_store_password="env-store-secret",
            koophone_jks_key_password="env-key-secret",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                '{"kimi_api_key":"file-kimi-secret",'
                '"adb_vendor_keys":"file-adb-key-path",'
                '"koophone_iam_password":"file-iam-secret",'
                '"koophone_jks_store_password":"file-store-secret",'
                '"koophone_jks_key_password":"file-key-secret"}',
                encoding="utf-8",
            )
            settings.load_from_file(str(path))

        self.assertEqual(
            settings.kimi_api_key.get_secret_value(), "env-kimi-secret"
        )
        self.assertEqual(
            settings.adb_vendor_keys.get_secret_value(), "env-adb-key-path"
        )
        self.assertEqual(
            settings.koophone_iam_password.get_secret_value(), "env-iam-secret"
        )
        self.assertEqual(
            settings.koophone_jks_store_password.get_secret_value(),
            "env-store-secret",
        )
        self.assertEqual(
            settings.koophone_jks_key_password.get_secret_value(), "env-key-secret"
        )

    def test_file_string_false_cannot_disable_tls_in_production(self):
        settings = Settings(env="production")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                '{"koophone_tls_verify":"false"}', encoding="utf-8"
            )
            settings.load_from_file(str(path))

        values = koophone_config().model_dump()
        values.update(
            environment=settings.env,
            tls_verify=settings.koophone_tls_verify,
        )
        with self.assertRaisesRegex(ValidationError, "ENV=poc"):
            KooPhoneConfig(**values)

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

    def test_kimi_and_adb_factories_accept_explicit_test_dependencies(self):
        kimi = create_model_provider(
            "kimi",
            thread_id="thread-1",
            is_stream=True,
            config=KimiConfig(api_key="fake-key"),
            client=object(),
        )
        adb = create_device_backend(
            "adb",
            config=AdbConfig(serial="device-1"),
            runner=object(),
        )

        self.assertEqual(kimi.name, "kimi")
        self.assertEqual(adb.name, "adb")

    def test_koophone_factory_accepts_explicit_boundary_dependencies(self):
        backend = create_device_backend(
            "koophone_mcp",
            config=koophone_config(),
            authenticator=object(),
            transport=object(),
        )

        self.assertIsInstance(backend, KooPhoneDeviceBackend)
        self.assertEqual(backend.name, "koophone_mcp")

    def test_selected_provider_errors_name_missing_env_without_secret_values(self):
        with patch.dict(os.environ, {}, clear=True):
            selected = Settings(model_provider="kimi", device_provider="adb")

        with self.assertRaisesRegex(ProviderConfigurationError, "KIMI_API_KEY"):
            selected.get_kimi_config()
        with self.assertRaisesRegex(ProviderConfigurationError, "ADB_SERIAL"):
            selected.get_adb_config()

    def test_unknown_providers_do_not_silently_fall_back(self):
        with self.assertRaises(UnknownProviderError):
            create_model_provider("unknown", thread_id="x", is_stream=False)
        with self.assertRaises(UnknownProviderError):
            create_device_backend("unknown")


if __name__ == "__main__":
    unittest.main()
