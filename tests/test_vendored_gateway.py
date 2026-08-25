"""Vendored llm_gateway sanity: importable, expected version, public API intact.

These tests make no network calls. The gateway's full behavioral suite (80
offline tests) lives in its source repository; here we only guard the vendored
copy's integrity — that the package is present, complete, and exposes the API
resume_analyzer will build on (ask/Gateway, message models, the exhaustion
error).
"""

import llm_gateway


def test_gateway_version() -> None:
    assert llm_gateway.__version__ == "0.2.0"


def test_public_api_surface() -> None:
    for name in (
        "ask",
        "Gateway",
        "ChatMessage",
        "GatewayResponse",
        "AllProvidersExhaustedError",
        "image_part",
    ):
        assert hasattr(llm_gateway, name), f"vendored gateway is missing {name}"


def test_registry_has_enabled_providers() -> None:
    from llm_gateway.config import GatewayConfig

    config = GatewayConfig.load()
    enabled = [p for p in config.providers if p.enabled]
    assert enabled, "vendored registry defines no enabled providers"
