"""The single public access point: ``Gateway`` and the module-level ``ask()``."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from . import transport
from .config import GatewayConfig, ProviderConfig
from .limits import RateLimitTracker
from .models import (
    ChatMessage,
    GatewayResponse,
    ImagePart,
    ProviderStatus,
    image_part,
    messages_require_vision,
)
from .router import Router


class Gateway:
    """Free-tier LLM gateway with automatic provider failover.

    Usage::

        gw = Gateway()                       # env keys + optional TOML overlay
        resp = gw.ask("Explain RAG briefly")
        print(resp.text, resp.provider)
    """

    def __init__(
        self,
        config: GatewayConfig | None = None,
        config_file: Path | str | None = None,
    ):
        if config is not None and config_file is not None:
            raise ValueError("Pass either config or config_file, not both")
        self.config = config or GatewayConfig.load(config_file)
        self._client = httpx.Client()
        self._tracker = RateLimitTracker(self.config.state_path)
        self._router = Router(self._tracker, self._call)

    def _call(
        self,
        provider: ProviderConfig,
        api_key: str,
        messages: list[dict[str, Any]],
        params: dict[str, Any],
    ) -> transport.CallResult:
        return transport.call_chat(
            self._client, provider, api_key, messages, params, self.config.request_timeout
        )

    def chat(
        self,
        messages: list[ChatMessage] | list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **params: Any,
    ) -> GatewayResponse:
        """Send a chat conversation; fail over across providers automatically.

        Messages containing image parts are detected automatically and routed
        only to vision-capable providers.

        Raises:
            NoProvidersConfiguredError: no enabled provider has an API key.
            NoCapableProviderError: the query has an image but no vision-capable
                provider is configured.
            AllProvidersExhaustedError: every provider is limited/unavailable;
                the error message includes the earliest recovery time.
        """
        wire = [
            m.model_dump() if isinstance(m, ChatMessage) else dict(m)  # type: ignore[arg-type]
            for m in messages
        ]
        merged: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
            **params,
        }
        return self._router.complete(
            self.config.active_providers(),
            wire,
            merged,
            needs_vision=messages_require_vision(wire),
        )

    def ask(
        self,
        prompt: str,
        *,
        system: str | None = None,
        images: Sequence[str | Path | bytes | ImagePart] = (),
        **params: Any,
    ) -> GatewayResponse:
        """One-shot question — the convenience form of :meth:`chat`.

        Pass ``images=`` (file paths, raw bytes, or http(s) URLs) to attach
        images; the query is then routed to a vision-capable provider.
        """
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for img in images:
                part = img if isinstance(img, ImagePart) else image_part(img)
                parts.append(part.model_dump())
            messages.append({"role": "user", "content": parts})
        else:
            messages.append({"role": "user", "content": prompt})
        return self.chat(messages, **params)

    def status(self) -> list[ProviderStatus]:
        """Quota/cooldown snapshot for every registered provider."""
        return self._tracker.snapshot(self.config.providers)

    def reset_state(self, provider: str | None = None) -> None:
        """Clear local counters and cooldowns (all providers, or one)."""
        self._tracker.clear(provider)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Gateway:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


_default_gateway: Gateway | None = None
_default_lock = threading.Lock()


def ask(
    prompt: str,
    *,
    system: str | None = None,
    images: Sequence[str | Path | bytes | ImagePart] = (),
    **params: Any,
) -> GatewayResponse:
    """Module-level one-liner using a lazily created shared :class:`Gateway`."""
    global _default_gateway
    if _default_gateway is None:
        with _default_lock:
            if _default_gateway is None:
                _default_gateway = Gateway()
    return _default_gateway.ask(prompt, system=system, images=images, **params)
