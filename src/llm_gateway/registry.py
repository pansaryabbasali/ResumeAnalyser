"""Built-in provider catalog — the ONLY file to touch when adding a provider.

All entries speak the OpenAI chat-completions protocol, so there is no
per-provider code. Limits reflect published free-tier numbers (August 2026);
they are advisory — a live 429 always overrides them. Users can patch any
field via a TOML overlay without editing this file.
"""

from __future__ import annotations

from .config import Limits, ProviderConfig

BUILTIN_PROVIDERS: tuple[ProviderConfig, ...] = (
    ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        model="llama-3.3-70b-versatile",
        limits=Limits(rpm=30, rpd=1000, tpm=12000, tpd=100000),
        daily_reset="rolling_24h",
        priority=1,
        notes="Fastest inference (LPU). Text-only — Groq removed its vision models "
        "(Aug 2026). Key: console.groq.com — email signup, no card.",
    ),
    ProviderConfig(
        name="gemini-flash-lite",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        model="gemini-flash-lite-latest",  # alias tracks Google's newest flash-lite
        limits=Limits(rpm=15, rpd=1000),
        daily_reset="midnight_pt",
        priority=3,
        supports_vision=True,
        notes="Google AI Studio key: aistudio.google.com — no card. RPD resets midnight PT.",
    ),
    ProviderConfig(
        name="gemini-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        model="gemini-flash-latest",  # alias tracks Google's newest flash
        limits=Limits(rpm=10, rpd=250),
        daily_reset="midnight_pt",
        priority=4,
        supports_vision=True,
        notes="Same AI Studio key as gemini-flash-lite; stronger model, smaller quota.",
    ),
    ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        model="nvidia/nemotron-3-super-120b-a12b:free",
        limits=Limits(rpm=20, rpd=50),
        daily_reset="rolling_24h",
        priority=5,
        notes="One key, rotating ':free' models. Only 50 req/day without credits — tried late.",
    ),
    ProviderConfig(
        name="openrouter-vision",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        model="nvidia/nemotron-nano-12b-v2-vl:free",
        limits=Limits(rpm=20, rpd=50),
        daily_reset="rolling_24h",
        priority=9,
        supports_vision=True,
        notes="Vision fallback after Gemini. Same OpenRouter key/quota as the text entry.",
    ),
    # --- Disabled by default (signup friction, tiny caps, or service changes).
    # --- Enable via TOML overlay if your account still has access.
    ProviderConfig(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        model="zai-glm-4.7",
        limits=Limits(rpm=30, tpm=60000, tpd=1_000_000),
        daily_reset="rolling_24h",
        priority=2,
        enabled=False,
        max_context=8192,
        notes="Free tier appears retired — all models return 402 payment_required "
        "(verified Aug 2026). Enable via overlay if your account has free access.",
    ),
    ProviderConfig(
        name="github-models",
        base_url="https://models.github.ai/inference",
        api_key_env="GITHUB_TOKEN",
        model="openai/gpt-4o-mini",
        limits=Limits(rpm=15, rpd=150),
        daily_reset="rolling_24h",
        priority=6,
        enabled=False,
        notes="Service being retired — HTTP 410 scheduled-retirement brownouts "
        "(verified Aug 2026).",
    ),
    # --- Disabled by default (signup friction / tiny caps). Enable via TOML overlay. ---
    ProviderConfig(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        model="mistral-small-latest",
        limits=Limits(rpm=1),
        daily_reset="rolling_24h",
        priority=7,
        enabled=False,
        notes="Free 'Experiment' tier (1B tokens/month) but requires phone verification.",
    ),
    ProviderConfig(
        name="cohere",
        base_url="https://api.cohere.ai/compatibility/v1",
        api_key_env="COHERE_API_KEY",
        model="command-r",
        limits=Limits(rpm=20, rpd=30),  # trial cap is 1,000/month; ~30/day keeps within it
        daily_reset="rolling_24h",
        priority=8,
        enabled=False,
        notes="Trial key: 1,000 requests/month total — kept off by default to save it.",
    ),
)
