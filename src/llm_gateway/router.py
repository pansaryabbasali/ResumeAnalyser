"""Failover router: one pass through the provider chain, first success wins.

The cooldown *decisions* are pure functions of the classified ``CallResult``,
keeping the IO loop thin and the logic unit-testable without HTTP. A future
``AsyncGateway`` reuses everything here except the ~30-line loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from .config import ProviderConfig
from .errors import (
    AllProvidersExhaustedError,
    NoCapableProviderError,
    NoProvidersConfiguredError,
)
from .limits import RateLimitTracker, _next_midnight_pacific
from .models import Attempt, GatewayResponse, Usage
from .transport import CallResult

# transport-compatible callable, injectable for tests
TransportFn = Callable[[ProviderConfig, str, list[dict[str, Any]], dict[str, Any]], CallResult]

_SERVER_ERROR_COOLDOWN_S = 30.0
_RPM_BREACH_COOLDOWN_S = 60.0


def cooldown_for_rate_limit(provider: ProviderConfig, result: CallResult, now: float) -> float:
    """Seconds to cool a provider that returned 429 (pure function).

    Honor the server's retry hint when present. Otherwise: a short cooldown for
    minute-window breaches, or until the daily reset when the provider defines
    a daily quota (we can't tell which limit tripped, so if the server gave no
    hint and a daily limit exists, assume the worse case only when the minute
    window can't be the cause — i.e. no RPM/TPM configured).
    """
    if result.retry_after_s is not None:
        return max(1.0, result.retry_after_s)
    has_minute_limit = provider.limits.rpm is not None or provider.limits.tpm is not None
    if has_minute_limit:
        return _RPM_BREACH_COOLDOWN_S
    if provider.daily_reset == "midnight_pt":
        return max(60.0, _next_midnight_pacific(now) - now)
    return _RPM_BREACH_COOLDOWN_S


class Router:
    def __init__(
        self,
        tracker: RateLimitTracker,
        transport_fn: TransportFn,
        clock: Callable[[], float] = time.time,
    ):
        self._tracker = tracker
        self._transport = transport_fn
        self._clock = clock
        self._session_disabled: dict[str, str] = {}  # provider -> reason (auth errors)

    def complete(
        self,
        providers: list[ProviderConfig],
        messages: list[dict[str, Any]],
        params: dict[str, Any],
        needs_vision: bool = False,
    ) -> GatewayResponse:
        """Try providers in priority order; return the first success.

        Image queries (needs_vision=True) are routed only to vision-capable
        providers. Single pass, no second lap: bounded worst-case latency, and
        the all-exhausted error tells the caller exactly when to come back.
        """
        if not providers:
            from .registry import BUILTIN_PROVIDERS

            raise NoProvidersConfiguredError([p.api_key_env for p in BUILTIN_PROVIDERS])

        if needs_vision:
            capable = [p for p in providers if p.supports_vision]
            if not capable:
                from .registry import BUILTIN_PROVIDERS

                raise NoCapableProviderError(
                    sorted({p.api_key_env for p in BUILTIN_PROVIDERS if p.supports_vision})
                )
            providers = capable

        attempts: list[Attempt] = []
        for p in providers:
            if p.name in self._session_disabled:
                attempts.append(
                    Attempt(
                        provider=p.name,
                        model=p.model,
                        outcome="auth_error",
                        detail=f"disabled this session: {self._session_disabled[p.name]}",
                    )
                )
                continue

            next_available = self._tracker.availability(p)
            if next_available is not None:
                attempts.append(
                    Attempt(
                        provider=p.name,
                        model=p.model,
                        outcome="skipped_local_limit",
                        detail=f"local limit until {next_available.astimezone():%H:%M:%S}",
                    )
                )
                continue

            api_key = p.resolve_api_key()
            assert api_key is not None  # active_providers() guarantees this
            result = self._transport(p, api_key, messages, params)

            if result.outcome == "success":
                return self._success(p, result, attempts)

            attempts.append(
                Attempt(
                    provider=p.name,
                    model=p.model,
                    outcome=result.outcome,
                    latency_ms=result.latency_ms,
                    detail=result.detail,
                )
            )
            now = self._clock()
            if result.outcome == "rate_limited":
                cool = cooldown_for_rate_limit(p, result, now)
                self._tracker.set_cooldown(p.name, now + cool, "429")
            elif result.outcome in ("server_error", "timeout"):
                self._tracker.set_cooldown(p.name, now + _SERVER_ERROR_COOLDOWN_S, result.outcome)
            elif result.outcome == "auth_error":
                self._session_disabled[p.name] = result.detail or "invalid API key"
            # bad_request (e.g. prompt exceeds a provider's context cap): no
            # cooldown — the provider is healthy, this request just didn't fit.

        raise AllProvidersExhaustedError(
            recovery={p.name: self._tracker.availability(p) for p in providers},
            attempts=[a.model_dump() for a in attempts],
        )

    def _success(
        self, p: ProviderConfig, result: CallResult, attempts: list[Attempt]
    ) -> GatewayResponse:
        payload = result.payload or {}
        text = payload["choices"][0]["message"]["content"]
        usage_raw = payload.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens"),
            completion_tokens=usage_raw.get("completion_tokens"),
            total_tokens=usage_raw.get("total_tokens"),
        )
        self._tracker.record_success(p.name, p.model, usage.total_tokens)
        attempts = attempts + [
            Attempt(
                provider=p.name, model=p.model, outcome="success", latency_ms=result.latency_ms
            )
        ]
        return GatewayResponse(
            text=text,
            provider=p.name,
            model=payload.get("model", p.model),
            latency_ms=result.latency_ms,
            usage=usage,
            attempts=attempts,
            raw=payload,
        )
