# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from mobile_agent.runtime.security import (
    RuntimeConfigurationError,
    validate_key_material,
    validate_runtime_configuration,
)


class RuntimeSecurityTests(unittest.TestCase):
    def _valid_settings(self, key_path: Path, ca_path: Path | None = None):
        return SimpleNamespace(
            model_provider="kimi",
            device_provider="koophone_mcp",
            get_kimi_config=lambda: SimpleNamespace(
                model="kimi-k2.6",
                thinking_mode="disabled",
            ),
            get_koophone_config=lambda: SimpleNamespace(
                jks_path=key_path,
                ca_bundle_path=ca_path,
            ),
        )

    def test_runtime_configuration_accepts_private_jks_and_fixed_providers(self):
        with TemporaryDirectory() as directory:
            key_path = Path(directory) / "jwt.jks"
            key_path.write_bytes(b"private-key-material")
            key_path.chmod(0o400)

            validate_runtime_configuration(self._valid_settings(key_path))

    def test_runtime_configuration_reports_only_safe_field_for_invalid_provider(self):
        with TemporaryDirectory() as directory:
            key_path = Path(directory) / "jwt.jks"
            key_path.write_bytes(b"private-key-material")
            key_path.chmod(0o400)
            settings = self._valid_settings(key_path)
            settings.model_provider = "doubao"

            with self.assertRaises(RuntimeConfigurationError) as raised:
                validate_runtime_configuration(settings)

        self.assertEqual(raised.exception.field, "MODEL_PROVIDER")
        self.assertNotIn("doubao", str(raised.exception))

    def test_runtime_configuration_rejects_unapproved_model_or_thinking_mode(self):
        with TemporaryDirectory() as directory:
            key_path = Path(directory) / "jwt.jks"
            key_path.write_bytes(b"private-key-material")
            key_path.chmod(0o400)
            settings = self._valid_settings(key_path)
            settings.get_kimi_config = lambda: SimpleNamespace(
                model="other-model",
                thinking_mode="disabled",
            )

            with self.assertRaises(RuntimeConfigurationError) as model_error:
                validate_runtime_configuration(settings)

            settings.get_kimi_config = lambda: SimpleNamespace(
                model="kimi-k2.6",
                thinking_mode="enabled",
            )
            with self.assertRaises(RuntimeConfigurationError) as thinking_error:
                validate_runtime_configuration(settings)

        self.assertEqual(model_error.exception.field, "KIMI_MODEL")
        self.assertEqual(thinking_error.exception.field, "KIMI_THINKING_MODE")

    def test_runtime_configuration_rejects_missing_or_overexposed_jks(self):
        with TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.jks"
            with self.assertRaises(RuntimeConfigurationError) as missing_error:
                validate_key_material(missing)

            exposed = Path(directory) / "exposed.jks"
            exposed.write_bytes(b"private-key-material")
            exposed.chmod(0o644)
            with self.assertRaises(RuntimeConfigurationError) as exposed_error:
                validate_key_material(exposed)

        self.assertEqual(missing_error.exception.field, "KOOPHONE_JKS_PATH")
        self.assertEqual(exposed_error.exception.field, "KOOPHONE_JKS_PATH")

    def test_runtime_configuration_rejects_empty_ca_bundle_at_startup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "jwt.jks"
            key_path.write_bytes(b"private-key-material")
            key_path.chmod(0o400)
            ca_path = root / "ca.pem"
            ca_path.write_bytes(b"")

            with self.assertRaises(RuntimeConfigurationError) as raised:
                validate_runtime_configuration(self._valid_settings(key_path, ca_path))

        self.assertEqual(raised.exception.field, "KOOPHONE_CA_BUNDLE")

    def test_runtime_configuration_rejects_invalid_ca_bundle_at_startup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            key_path = root / "jwt.jks"
            key_path.write_bytes(b"private-key-material")
            key_path.chmod(0o400)
            ca_path = root / "ca.pem"
            ca_path.write_text("not a PEM certificate", encoding="ascii")

            with self.assertRaises(RuntimeConfigurationError) as raised:
                validate_runtime_configuration(self._valid_settings(key_path, ca_path))

        self.assertEqual(raised.exception.field, "KOOPHONE_CA_BUNDLE")


if __name__ == "__main__":
    unittest.main()
