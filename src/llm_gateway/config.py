"""Configuration: provider definitions, limits, TOML overlay, and .env loading.

Built-in provider facts live in ``registry.py``. Users never edit package code:
overrides (priority, enabling/disabling, demo limits, state path) come from an
optional TOML file passed via ``--config`` or ``$LLM_GATEWAY_CONFIG``.

API keys come from environment variables, which may be populated from ``.env``
files (searched at ``$LLM_GATEWAY_ENV``, ``./.env``, then ``~/.llm_gateway/.env``)
so keys are set once, not exported per shell session. Real environment variables
always win over file values.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from .errors import ConfigError

DailyReset = Literal["midnight_pt", "rolling_24h"]

ENV_CONFIG_VAR = "LLM_GATEWAY_CONFIG"
ENV_FILE_VAR = "LLM_GATEWAY_ENV"
DEFAULT_STATE_PATH = Path.home() / ".llm_gateway" / "usage.db"
GLOBAL_ENV_FILE = Path.home() / ".llm_gateway" / ".env"


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; '#' comments and blank lines ignored, quotes stripped."""
    entries: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            entries[key] = value
    return entries


def load_env_files() -> list[Path]:
    """Populate os.environ from .env files; returns the files that were loaded.

    Search order: ``$LLM_GATEWAY_ENV`` (explicit path), ``./.env`` (project),
    ``~/.llm_gateway/.env`` (global). All existing files load, earlier files win
    for duplicate keys, and variables already present in the real environment
    are never overridden.
    """
    candidates: list[Path] = []
    explicit = os.environ.get(ENV_FILE_VAR, "").strip()
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if not explicit_path.is_file():
            raise ConfigError(f"$LLM_GATEWAY_ENV points to a missing file: {explicit_path}")
        candidates.append(explicit_path)
    candidates.append(Path.cwd() / ".env")
    candidates.append(GLOBAL_ENV_FILE)

    loaded: list[Path] = []
    for path in candidates:
        if not path.is_file():
            continue
        for key, value in _parse_env_file(path).items():
            if key not in os.environ:  # real env and earlier files win
                os.environ[key] = value
        loaded.append(path)
    return loaded


class Limits(BaseModel):
    """Free-tier limits. ``None`` means "not enforced locally" for that axis."""

    rpm: int | None = None  # requests per minute (sliding 60s window)
    rpd: int | None = None  # requests per day (reset semantics per provider)
    tpm: int | None = None  # tokens per minute
    tpd: int | None = None  # tokens per day


class ProviderConfig(BaseModel):
    name: str
    base_url: str  # OpenAI-compatible root, e.g. https://api.groq.com/openai/v1
    api_key_env: str  # env var holding the key, e.g. GROQ_API_KEY
    model: str  # default model served by this entry
    limits: Limits = Field(default_factory=Limits)
    daily_reset: DailyReset = "rolling_24h"
    priority: int = 100  # lower = tried first
    enabled: bool = True
    supports_vision: bool = False  # can this entry accept image input?
    max_context: int | None = None  # tokens; e.g. 8192 on Cerebras free tier
    extra_headers: dict[str, str] = Field(default_factory=dict)
    notes: str = ""  # shown by `llm-gateway providers` (signup quirks etc.)

    def resolve_api_key(self) -> str | None:
        key = os.environ.get(self.api_key_env, "").strip()
        return key or None


class GatewayConfig(BaseModel):
    providers: list[ProviderConfig]
    state_path: Path = DEFAULT_STATE_PATH
    request_timeout: float = 60.0

    @classmethod
    def load(cls, config_file: Path | str | None = None) -> GatewayConfig:
        """Build config from the built-in registry plus an optional TOML overlay.

        Overlay resolution order: explicit ``config_file`` argument, then
        ``$LLM_GATEWAY_CONFIG``, else built-ins only. Also loads API keys from
        ``.env`` files (see :func:`load_env_files`).
        """
        from .registry import BUILTIN_PROVIDERS

        load_env_files()

        providers = {p.name: p.model_copy(deep=True) for p in BUILTIN_PROVIDERS}
        state_path = DEFAULT_STATE_PATH
        request_timeout = 60.0

        path_str = str(config_file) if config_file else os.environ.get(ENV_CONFIG_VAR, "")
        if path_str:
            path = Path(path_str).expanduser()
            if not path.is_file():
                raise ConfigError(f"Config overlay not found: {path}")
            try:
                overlay = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

            if "state_path" in overlay:
                state_path = Path(str(overlay["state_path"])).expanduser()
            if "request_timeout" in overlay:
                request_timeout = float(overlay["request_timeout"])

            for name, fields in overlay.get("providers", {}).items():
                if not isinstance(fields, dict):
                    raise ConfigError(
                        f"[providers.{name}] must be a table, got {type(fields).__name__}"
                    )
                try:
                    if name in providers:
                        base = providers[name]
                        merged = base.model_dump()
                        limits_patch = fields.pop("limits", None)
                        merged.update(fields)
                        if limits_patch is not None:
                            merged["limits"] = {**base.limits.model_dump(), **limits_patch}
                        providers[name] = ProviderConfig(**merged)
                    else:
                        # A provider defined entirely in the overlay must be complete.
                        providers[name] = ProviderConfig(name=name, **fields)
                except ValidationError as exc:
                    raise ConfigError(f"Invalid config for provider '{name}': {exc}") from exc

        ordered = sorted(providers.values(), key=lambda p: p.priority)
        return cls(providers=ordered, state_path=state_path, request_timeout=request_timeout)

    def active_providers(self) -> list[ProviderConfig]:
        """Enabled providers that have an API key, in priority order."""
        return [p for p in self.providers if p.enabled and p.resolve_api_key() is not None]
