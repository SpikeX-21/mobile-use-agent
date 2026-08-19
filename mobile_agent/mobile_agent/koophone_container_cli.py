# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# Licensed under the 【火山方舟】原型应用软件自用许可协议

"""Guarded entry point for the secret-bearing KooPhone internal POC image."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import stat
import sys

from mobile_agent.agent.provider import ProviderConfigurationError
from mobile_agent.config.settings import get_settings
from mobile_agent.koophone_acceptance import main as acceptance_main
from mobile_agent.koophone_alarm_cli import main as alarm_main


DEFAULT_CONTAINER_JKS_PATH = Path("/opt/mobile-agent/secrets/koophone.jks")


def configure_private_runtime_logging() -> None:
    """Keep credential-adjacent runtime endpoints out of POC container logs."""

    for logger_name in ("httpx", "httpcore", "mcp.client.streamable_http"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def validate_container_runtime(*, key_path: Path) -> None:
    """Validate that the baked or mounted key is private and never needs writes."""

    try:
        file_stat = key_path.stat()
    except OSError:
        raise ProviderConfigurationError(
            "KooPhone JKS key material is not available"
        ) from None
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size <= 0:
        raise ProviderConfigurationError(
            "KooPhone JKS key material is not available"
        )
    if stat.S_IMODE(file_stat.st_mode) != 0o400:
        raise ProviderConfigurationError(
            "KooPhone JKS key material must be owner-readable only (mode 0400)"
        )


def main(argv: list[str] | None = None) -> int:
    configure_private_runtime_logging()
    print(
        "WARNING: secret-bearing internal KooPhone POC image; "
        "do not publish or use in production",
        file=sys.stderr,
    )
    key_path = Path(
        os.environ.get("KOOPHONE_JKS_PATH", str(DEFAULT_CONTAINER_JKS_PATH))
    )
    try:
        validate_container_runtime(key_path=key_path)
        runtime_settings = get_settings()
        runtime_settings.get_kimi_config()
        runtime_settings.get_koophone_config()
    except ProviderConfigurationError as error:
        print(f"KOOPHONE_POC_CONTAINER=failed reason={error}", file=sys.stderr)
        raise SystemExit(2) from None
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "acceptance":
        return acceptance_main(arguments[1:])
    if arguments:
        print(
            "KOOPHONE_POC_CONTAINER=failed reason=unknown_command",
            file=sys.stderr,
        )
        return 2
    alarm_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
