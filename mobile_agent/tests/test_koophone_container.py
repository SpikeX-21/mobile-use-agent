# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

from __future__ import annotations

import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.koophone_container_cli import (
    configure_private_runtime_logging,
    main as container_main,
    validate_container_runtime,
)


class KooPhoneContainerRuntimeTests(unittest.TestCase):
    def test_acceptance_subcommand_keeps_container_preflight(self):
        settings = unittest.mock.Mock()
        with (
            patch(
                "mobile_agent.koophone_container_cli.validate_container_runtime"
            ) as validate,
            patch(
                "mobile_agent.koophone_container_cli.get_settings",
                return_value=settings,
            ),
            patch(
                "mobile_agent.koophone_container_cli.acceptance_main",
                return_value=0,
            ) as acceptance,
        ):
            result = container_main(
                [
                    "acceptance",
                    "--output-dir",
                    "/output",
                    "--attest-no-manual-intervention",
                ]
            )

        validate.assert_called_once()
        settings.get_kimi_config.assert_called_once_with()
        settings.get_koophone_config.assert_called_once_with()
        acceptance.assert_called_once_with(
            ["--output-dir", "/output", "--attest-no-manual-intervention"]
        )
        self.assertEqual(result, 0)

    def test_container_suppresses_credential_adjacent_network_endpoints(self):
        logger_names = ("httpx", "httpcore", "mcp.client.streamable_http")
        previous_levels = {
            name: logging.getLogger(name).level for name in logger_names
        }
        try:
            configure_private_runtime_logging()
            self.assertTrue(
                all(
                    logging.getLogger(name).level == logging.WARNING
                    for name in logger_names
                )
            )
        finally:
            for name, level in previous_levels.items():
                logging.getLogger(name).setLevel(level)

    def test_runtime_validation_accepts_read_only_private_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "koophone.jks"
            key_path.write_bytes(b"test-only-key-material")
            key_path.chmod(0o400)

            with patch.dict(
                os.environ,
                {
                    "ENV": "poc",
                    "KOOPHONE_JKS_PATH": str(key_path),
                },
                clear=False,
            ):
                validate_container_runtime(key_path=key_path)

    def test_runtime_validation_rejects_missing_or_overexposed_key_file(self):
        missing = Path("/tmp/definitely-missing-koophone-poc-key.jks")
        with self.assertRaisesRegex(ProviderConfigurationError, "not available"):
            validate_container_runtime(key_path=missing)

        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "koophone.jks"
            key_path.write_bytes(b"test-only-key-material")
            key_path.chmod(0o440)
            with self.assertRaisesRegex(ProviderConfigurationError, "owner-readable only"):
                validate_container_runtime(key_path=key_path)


class KooPhoneContainerDefinitionTests(unittest.TestCase):
    def test_build_context_and_image_contract_are_explicit(self):
        component_root = Path(__file__).resolve().parents[1]
        dockerignore = (component_root / ".dockerignore").read_text()
        dockerfile = (component_root / "Dockerfile.koophone-poc").read_text()

        self.assertIn("*", dockerignore.splitlines())
        self.assertIn("!config.toml", dockerignore.splitlines())
        self.assertIn("!jwt.jks", dockerignore.splitlines())
        self.assertIn("!mobile_agent/**/*.py", dockerignore.splitlines())
        self.assertNotIn("!mobile_agent/**", dockerignore.splitlines())
        self.assertNotIn("!.env", dockerignore.splitlines())
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn("--chmod=0400", dockerfile)
        self.assertIn("KOOPHONE_JKS_PATH=/opt/mobile-agent/secrets/koophone.jks", dockerfile)
        self.assertIn("MOBILE_CONFIG_PATH=/opt/mobile-agent/config.toml", dockerfile)
        self.assertIn("mobile_agent.koophone_container_cli", dockerfile)
        self.assertIn("secret-bearing", dockerfile)
        self.assertIn(
            "find mobile_agent -type f ! -name '*.py' -delete", dockerfile
        )


if __name__ == "__main__":
    unittest.main()
