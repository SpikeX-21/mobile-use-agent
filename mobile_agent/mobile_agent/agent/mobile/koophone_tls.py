from __future__ import annotations

import ssl

from mobile_agent.config.settings import KooPhoneConfig


def build_tls_verification(config: KooPhoneConfig) -> bool | ssl.SSLContext:
    """Build the single TLS policy shared by IAM and MCP transports."""

    if config.ca_bundle_path is not None:
        return ssl.create_default_context(cafile=str(config.ca_bundle_path))
    return config.tls_verify
