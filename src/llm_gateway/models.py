"""Public data models: request/response envelope and status snapshots."""

from __future__ import annotations

import base64
import mimetypes
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant"]

AttemptOutcome = Literal[
    "success",
    "skipped_local_limit",
    "rate_limited",
    "server_error",
    "timeout",
    "auth_error",
    "bad_request",
]


class TextPart(BaseModel):
    """A text block inside a multimodal message (OpenAI wire format)."""

    type: Literal["text"] = "text"
    text: str


class ImageUrl(BaseModel):
    url: str  # data: URL (base64) or http(s) URL


class ImagePart(BaseModel):
    """An image block inside a multimodal message (OpenAI wire format)."""

    type: Literal["image_url"] = "image_url"
    image_url: ImageUrl


ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]

# Magic-byte signatures for the image formats the free providers accept.
_MAGIC_MIMES: list[tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP; checked further below
]


def _sniff_mime(data: bytes) -> str | None:
    for magic, mime in _MAGIC_MIMES:
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


def image_part(source: str | Path | bytes, *, mime: str | None = None) -> ImagePart:
    """Build an ImagePart from a file path, raw bytes, or an http(s)/data URL.

    Files and bytes are embedded as base64 data URLs. Raises ValueError when the
    image type can't be determined — providers reject untyped payloads, and it's
    better to fail here than three failovers deep.
    """
    if isinstance(source, str) and source.startswith(("http://", "https://", "data:")):
        return ImagePart(image_url=ImageUrl(url=source))

    if isinstance(source, bytes):
        data = source
        mime = mime or _sniff_mime(data)
    else:
        path = Path(source)
        if not path.is_file():
            raise ValueError(f"Image file not found: {path}")
        data = path.read_bytes()
        mime = mime or mimetypes.guess_type(path.name)[0] or _sniff_mime(data)

    if not mime or not mime.startswith("image/"):
        raise ValueError(
            "Could not determine image type (expected png/jpeg/webp/gif); "
            "pass mime='image/...' explicitly"
        )
    encoded = base64.b64encode(data).decode("ascii")
    return ImagePart(image_url=ImageUrl(url=f"data:{mime};base64,{encoded}"))


def messages_require_vision(wire_messages: Sequence[dict[str, Any]]) -> bool:
    """True if any serialized message carries an image part.

    Operates on the wire-format list so both ChatMessage objects and raw dicts
    passed by callers are detected identically.
    """
    for message in wire_messages:
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in content
        ):
            return True
    return False


class ChatMessage(BaseModel):
    role: Role
    content: str | list[ContentPart]


class Usage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class Attempt(BaseModel):
    """One step in the failover trail — what happened at one provider."""

    provider: str
    model: str
    outcome: AttemptOutcome
    latency_ms: float | None = None
    detail: str | None = None


class GatewayResponse(BaseModel):
    """The envelope returned by every successful gateway call."""

    text: str
    provider: str
    model: str
    latency_ms: float
    usage: Usage | None = None
    attempts: list[Attempt] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def failed_over(self) -> bool:
        """True when at least one provider was tried or skipped before the winner."""
        return len(self.attempts) > 1


class ProviderStatus(BaseModel):
    """Point-in-time quota/cooldown snapshot for one provider."""

    name: str
    enabled: bool
    has_key: bool
    priority: int
    model: str
    rpm_used: int | None = None
    rpm_limit: int | None = None
    rpd_used: int | None = None
    rpd_limit: int | None = None
    tokens_minute_used: int | None = None
    tpm_limit: int | None = None
    tokens_day_used: int | None = None
    tpd_limit: int | None = None
    cooldown_until: datetime | None = None
    cooldown_reason: str | None = None
    next_available: datetime | None = None  # None == available right now
