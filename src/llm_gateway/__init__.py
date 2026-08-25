"""llm-gateway: free-tier LLM gateway with automatic provider failover.

Public API — everything importable from this module is the stability contract;
internals may change between versions.
"""

from .client import Gateway, ask
from .config import GatewayConfig, Limits, ProviderConfig
from .errors import (
    AllProvidersExhaustedError,
    ConfigError,
    GatewayError,
    NoCapableProviderError,
    NoProvidersConfiguredError,
)
from .models import (
    Attempt,
    ChatMessage,
    GatewayResponse,
    ImagePart,
    ProviderStatus,
    TextPart,
    Usage,
    image_part,
)

__version__ = "0.2.0"

__all__ = [
    "AllProvidersExhaustedError",
    "Attempt",
    "ChatMessage",
    "ConfigError",
    "Gateway",
    "GatewayConfig",
    "GatewayError",
    "GatewayResponse",
    "ImagePart",
    "Limits",
    "NoCapableProviderError",
    "NoProvidersConfiguredError",
    "ProviderConfig",
    "ProviderStatus",
    "TextPart",
    "Usage",
    "ask",
    "image_part",
]
