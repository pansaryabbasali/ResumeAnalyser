"""Exception hierarchy for llm-gateway.

This module imports nothing from the rest of the package so it can be
imported from anywhere without cycles.
"""

from __future__ import annotations

from datetime import UTC, datetime


class GatewayError(Exception):
    """Base class for all llm-gateway errors."""


class NoProvidersConfiguredError(GatewayError):
    """Raised when no enabled provider has an API key set."""

    def __init__(self, checked_env_vars: list[str]):
        self.checked_env_vars = checked_env_vars
        super().__init__(
            "No providers are configured. Set at least one of these environment "
            f"variables: {', '.join(checked_env_vars)}. "
            "See the README for where to create each free API key."
        )


class ConfigError(GatewayError):
    """Raised when a config overlay file is invalid."""


class NoCapableProviderError(GatewayError):
    """An image query was made but no vision-capable provider is available."""

    def __init__(self, vision_env_vars: list[str]):
        self.vision_env_vars = vision_env_vars
        super().__init__(
            "This query contains an image, but no vision-capable provider is "
            "configured. Set one of these environment variables: "
            f"{', '.join(vision_env_vars)}."
        )


class AllProvidersExhaustedError(GatewayError):
    """Every provider in the chain is rate-limited, cooling down, or failed.

    Attributes:
        recovery: provider name -> datetime it becomes available again,
            or None when recovery time is unknown (e.g. auth failure).
        attempts: serialized attempt dicts describing what happened per provider.
    """

    def __init__(
        self,
        recovery: dict[str, datetime | None],
        attempts: list[object] | None = None,
    ):
        self.recovery = recovery
        self.attempts = attempts or []
        super().__init__(self._render())

    @property
    def earliest_recovery(self) -> datetime | None:
        known = [t for t in self.recovery.values() if t is not None]
        return min(known) if known else None

    def _render(self) -> str:
        earliest = self.earliest_recovery
        if earliest is None:
            head = "All providers exhausted and no recovery time is known."
        else:
            now = datetime.now(UTC)
            wait_s = max(0, int((earliest - now).total_seconds()))
            local = earliest.astimezone()
            if wait_s >= 3600:
                wait = f"{wait_s // 3600}h {wait_s % 3600 // 60}m"
            elif wait_s >= 60:
                wait = f"{wait_s // 60}m {wait_s % 60}s"
            else:
                wait = f"{wait_s}s"
            head = (
                f"All providers exhausted. Earliest recovery in ~{wait} "
                f"(at {local.strftime('%H:%M:%S')})."
            )
        parts = []
        for name, when in sorted(self.recovery.items(), key=lambda kv: (kv[1] is None, kv[1])):
            if when is None:
                parts.append(f"{name}: unavailable (no recovery time)")
            else:
                parts.append(f"{name}: {when.astimezone().strftime('%H:%M:%S')}")
        return head + " Per provider: " + " | ".join(parts)
