"""Resume extraction strategies (M3): single-pass vs sectioned, both cached.

Two competing strategies (the M3 bake-off decides the winner on fixture score
plus token cost):

- ``single_pass`` — the whole resume text in one LLM call producing the full
  ``ResumeProfile`` JSON.
- ``sectioned`` — the text is split on recognized section headers into three
  parts (identity / experience / credentials), each extracted by a smaller
  focused call, then merged and validated once.

Either way, a response that fails JSON parsing or pydantic validation gets one
repair round: the model sees its own output plus the validation errors and must
return a corrected object. All calls go through the response cache.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from resume_analyzer.models import ResumeProfile

from . import prompts
from .cache import CachedResponse, ResponseCache


class AsksLLM(Protocol):
    """The one gateway capability extraction needs (satisfied by llm_gateway.Gateway)."""

    def ask(self, prompt: str, *, system: str | None = None, **params: Any) -> Any: ...


# --------------------------------------------------------------------------- sectionizer

_CANONICAL_SECTIONS = {
    "summary": "identity",
    "profile": "identity",
    "personal details": "identity",
    "declaration": "identity",
    "languages known": "identity",
    "languages": "identity",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "skills": "credentials",
    "technical skills": "credentials",
    "education": "credentials",
    "certifications": "credentials",
    "projects": "credentials",
    "publications": "credentials",
    "selected publications": "credentials",
}
# Any unrecognized header ("Talks", "Open source", "Courses"...) also lands in
# credentials: those sections carry qualification-like content.
_FALLBACK_PART = "credentials"

_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z &/-]{1,40}$")


def split_sections(text: str) -> dict[str, str]:
    """Split resume text into three part-buckets by recognized section headers.

    The preamble (name, headline, contact line) always belongs to 'identity'.
    A line counts as a header when it is short, letters-only-ish, and either a
    known section name or written in ALL CAPS (the modern-template style).
    """
    parts: dict[str, list[str]] = {"identity": [], "experience": [], "credentials": []}
    current = "identity"  # preamble
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if _HEADER_RE.fullmatch(stripped) and (
            lowered in _CANONICAL_SECTIONS or (stripped.isupper() and len(stripped) > 2)
        ):
            current = _CANONICAL_SECTIONS.get(lowered, _FALLBACK_PART)
        parts[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in parts.items()}


# --------------------------------------------------------------------------- JSON handling


class LLMOutputError(ValueError):
    """The model's output could not be turned into a valid profile."""


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse a model response into a dict, tolerating fences and stray prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMOutputError(f"no JSON object in response: {cleaned[:120]!r}")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LLMOutputError("response JSON is not an object")
    return parsed


# --------------------------------------------------------------------------- extractor


@dataclass
class ExtractionResult:
    profile: ResumeProfile
    strategy: str
    calls: int = 0
    cache_hits: int = 0
    tokens: int = 0
    repairs: int = 0
    providers: list[str] = field(default_factory=list)


class ResumeExtractor:
    def __init__(self, gateway: AsksLLM, cache: ResponseCache, temperature: float = 0.0):
        self.gateway = gateway
        self.cache = cache
        self.params = {"temperature": temperature}

    # -- one cached LLM call ------------------------------------------------
    def _ask(self, task: str, prompt: str, result: ExtractionResult) -> str:
        key = ResponseCache.make_key(task, prompts.SYSTEM, prompt, self.params)
        cached = self.cache.get(key)
        if cached is not None:
            result.cache_hits += 1
            result.providers.append(f"{cached.provider} (cached)")
            return cached.text
        response = self.gateway.ask(prompt, system=prompts.SYSTEM, **self.params)
        result.calls += 1
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", None) if usage else None
        result.tokens += total or 0
        result.providers.append(response.provider)
        self.cache.put(
            key,
            task,
            CachedResponse(
                text=response.text,
                provider=response.provider,
                model=response.model,
                total_tokens=total,
            ),
        )
        return response.text

    # -- ask + parse + one repair round ------------------------------------
    def _ask_validated(
        self,
        task: str,
        prompt: str,
        result: ExtractionResult,
        validate: Any,
    ) -> Any:
        raw_text = self._ask(task, prompt, result)
        try:
            return validate(parse_json_response(raw_text))
        except (LLMOutputError, ValidationError) as first_error:
            result.repairs += 1
            repair = prompts.repair_prompt(raw_text[:4000], str(first_error)[:2000])
            repaired_text = self._ask(f"{task}:repair", repair, result)
            try:
                return validate(parse_json_response(repaired_text))
            except (LLMOutputError, ValidationError) as second_error:
                raise LLMOutputError(
                    f"{task}: still invalid after repair: {second_error}"
                ) from second_error

    # -- strategies ---------------------------------------------------------
    def extract(
        self, resume_text: str, source_file: str, strategy: str = "single_pass"
    ) -> ExtractionResult:
        if strategy == "single_pass":
            return self._extract_single_pass(resume_text, source_file)
        if strategy == "sectioned":
            return self._extract_sectioned(resume_text, source_file)
        raise ValueError(f"unknown strategy {strategy!r}")

    def _extract_single_pass(self, resume_text: str, source_file: str) -> ExtractionResult:
        result = ExtractionResult(profile=None, strategy="single_pass")  # type: ignore[arg-type]

        def validate(data: dict[str, Any]) -> ResumeProfile:
            data.pop("source_file", None)
            return ResumeProfile(source_file=source_file, **data)

        result.profile = self._ask_validated(
            f"extract:single:{source_file}",
            prompts.single_pass_prompt(resume_text),
            result,
            validate,
        )
        return result

    def _extract_sectioned(self, resume_text: str, source_file: str) -> ExtractionResult:
        result = ExtractionResult(profile=None, strategy="sectioned")  # type: ignore[arg-type]
        sections = split_sections(resume_text)
        plan = [
            ("identity", prompts.IDENTITY_SCHEMA),
            ("experience", prompts.EXPERIENCE_SCHEMA),
            ("credentials", prompts.CREDENTIALS_SCHEMA),
        ]
        merged: dict[str, Any] = {}
        for part_name, part_schema in plan:
            part_text = sections.get(part_name, "")
            if not part_text:
                continue
            fragment = self._ask_validated(
                f"extract:{part_name}:{source_file}",
                prompts.section_prompt(part_name, part_schema, part_text),
                result,
                lambda data: data,  # fragments are parse-checked; validation happens merged
            )
            merged.update(fragment)

        def validate(data: dict[str, Any]) -> ResumeProfile:
            data.pop("source_file", None)
            return ResumeProfile(source_file=source_file, **data)

        try:
            result.profile = validate(dict(merged))
        except ValidationError as error:
            result.repairs += 1
            repair = prompts.repair_prompt(json.dumps(merged)[:4000], str(error)[:2000])
            repaired_text = self._ask(f"extract:merge-repair:{source_file}", repair, result)
            result.profile = validate(parse_json_response(repaired_text))
        return result
