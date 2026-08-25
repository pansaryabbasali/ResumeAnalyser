"""HTTP transport: one OpenAI-compatible chat-completions call + classification.

Every supported provider speaks the OpenAI protocol, so this is the only HTTP
code in the package. The router consumes the classified ``CallResult`` and
never sees httpx.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from .config import ProviderConfig

CallOutcome = Literal[
    "success", "rate_limited", "server_error", "timeout", "auth_error", "bad_request"
]

_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")


@dataclass
class CallResult:
    outcome: CallOutcome
    latency_ms: float
    payload: dict[str, Any] | None = None  # parsed OpenAI response on success
    retry_after_s: float | None = None  # from Retry-After / x-ratelimit-reset-*
    detail: str | None = None


def parse_duration(value: str) -> float | None:
    """Parse '7.66s', '2m59.56s', '1h2m3s', or plain seconds ('120') to seconds."""
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    m = _DURATION_RE.fullmatch(value)
    if not m or not any(m.groups()):
        return None
    hours, minutes, seconds = m.groups()
    return float(hours or 0) * 3600 + float(minutes or 0) * 60 + float(seconds or 0)


def _retry_after_from_headers(headers: httpx.Headers) -> float | None:
    """Best-effort retry delay: Retry-After first, then Groq x-ratelimit-reset-*."""
    ra = headers.get("retry-after")
    if ra:
        parsed = parse_duration(ra)
        if parsed is not None:
            return parsed
    candidates = [
        parse_duration(headers.get(h, ""))
        for h in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens")
    ]
    known = [c for c in candidates if c is not None]
    return min(known) if known else None


def _error_snippet(response: httpx.Response) -> str:
    try:
        body = response.json()
        msg = body.get("error", {}).get("message") or str(body)
    except Exception:
        msg = response.text
    return msg[:200]


def call_chat(
    client: httpx.Client,
    provider: ProviderConfig,
    api_key: str,
    messages: list[dict[str, Any]],
    params: dict[str, Any],
    timeout: float,
) -> CallResult:
    """POST /chat/completions to one provider and classify the outcome."""
    url = provider.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", **provider.extra_headers}
    body: dict[str, Any] = {"model": provider.model, "messages": messages}
    body.update({k: v for k, v in params.items() if v is not None})

    start = time.perf_counter()
    try:
        response = client.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        return CallResult(
            "timeout", (time.perf_counter() - start) * 1000, detail="request timed out"
        )
    except httpx.TransportError as exc:
        return CallResult(
            "server_error",
            (time.perf_counter() - start) * 1000,
            detail=f"transport error: {exc.__class__.__name__}: {exc}"[:200],
        )
    latency_ms = (time.perf_counter() - start) * 1000

    status = response.status_code
    if status == 200:
        try:
            payload = response.json()
            # Validate the shape we depend on before declaring success.
            payload["choices"][0]["message"]["content"]
        except (ValueError, LookupError, TypeError):
            return CallResult(
                "server_error", latency_ms, detail="200 but unparseable chat payload"
            )
        return CallResult("success", latency_ms, payload=payload)
    if status == 429:
        return CallResult(
            "rate_limited",
            latency_ms,
            retry_after_s=_retry_after_from_headers(response.headers),
            detail=_error_snippet(response),
        )
    if status in (401, 402, 403):
        # 402 (payment required): account lacks free access — same handling as a
        # bad key: disable for the session so we don't burn a call every request.
        return CallResult("auth_error", latency_ms, detail=_error_snippet(response))
    if status == 400:
        return CallResult("bad_request", latency_ms, detail=_error_snippet(response))
    return CallResult(
        "server_error", latency_ms, detail=f"HTTP {status}: {_error_snippet(response)}"
    )
