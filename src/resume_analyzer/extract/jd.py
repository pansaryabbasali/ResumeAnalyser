"""Job-description extraction (M4): deterministic markdown -> JobSpec.

Requisitions are published from the bank's own ATS in a fixed markdown shape
(title, a key/value table, `## `-delimited sections with `- ` bullets). Where
structure exists, parse it — an LLM here would add cost, latency and a failure
mode to a solved problem. The LLM budget stays reserved for resumes, which have
no fixed structure. If the ATS format ever changes, these tests break loudly
and THAT is the moment to reconsider.

Only two things are inferred rather than read:
- ``min_years_experience`` — the largest "N+ years" figure in the must-haves
  (the overall bar; smaller figures qualify sub-requirements like "3+ managing").
- ``Requirement.kind`` — a keyword heuristic, ordered most-specific-first.
"""

from __future__ import annotations

import re
from pathlib import Path

from resume_analyzer.models import JobSpec, Requirement, RequirementKind

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)
_YEARS_RE = re.compile(r"(\d+)\+?\s*years?", re.IGNORECASE)

_TABLE_FIELDS = {
    "Requisition": "req_id",
    "Division": "division",
    "Location": "location",
    "Employment type": "employment_type",
    "CTC range": "ctc_range",
}

_SECTION_FIELDS = {
    "what you bring (must-haves)": "must_haves",
    "nice to have": "nice_to_haves",
    "what you'll do": "responsibilities",
}

# Ordered most-specific-first: the first matching bucket wins.
_KIND_RULES: list[tuple[RequirementKind, re.Pattern[str]]] = [
    ("language", re.compile(r"\b(english|kannada|hindi|tamil|language)\b", re.IGNORECASE)),
    ("certification", re.compile(r"\b(certification|certified|CKA|CKS|FRM|CQF|SHRM|CIPD)\b")),
    ("education", re.compile(
        r"\b(M\.?Sc|M\.?Tech|PhD|MSc|degree|discipline|econometrics)\b")),
    ("experience", re.compile(r"\byears?\b|\btrack record\b|\bexperience\b", re.IGNORECASE)),
    ("domain", re.compile(
        r"\b(banking|payments?|regulated|NBFC|RBI|NPCI|FRTB|IRRBB|fintech|insurance|"
        r"fixed-income|derivatives|market conventions)\b", re.IGNORECASE)),
]


def classify_kind(text: str) -> RequirementKind:
    for kind, pattern in _KIND_RULES:
        if pattern.search(text):
            return kind
    return "skill"


def _bullets(section_text: str) -> list[str]:
    """Collect `- ` bullets, joining wrapped continuation lines onto their bullet."""
    items: list[str] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            items.append(stripped[2:].strip())
        elif stripped and items and not stripped.startswith(("#", "|", "*")):
            items[-1] = f"{items[-1]} {stripped}"
    return items


def _sections(text: str) -> dict[str, str]:
    """Map lowercased `## ` header -> body text."""
    result: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                result[current] = "\n".join(lines)
            current = line[3:].strip().lower()
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        result[current] = "\n".join(lines)
    return result


def min_years_from_must_haves(musts: list[str]) -> float | None:
    figures = [int(m.group(1)) for text in musts for m in _YEARS_RE.finditer(text)]
    return float(max(figures)) if figures else None


def parse_jd_markdown(text: str, source_file: str | None = None) -> JobSpec:
    title_match = _TITLE_RE.search(text)
    if not title_match:
        raise ValueError(f"no '# ' title line in {source_file or 'JD text'}")

    fields: dict[str, str] = {}
    for key, value in _TABLE_ROW_RE.findall(text):
        if key in _TABLE_FIELDS:
            fields[_TABLE_FIELDS[key]] = value

    section_bullets: dict[str, list[str]] = {}
    for header, body in _sections(text).items():
        if header in _SECTION_FIELDS:
            section_bullets[_SECTION_FIELDS[header]] = _bullets(body)

    musts = section_bullets.get("must_haves", [])
    nices = section_bullets.get("nice_to_haves", [])
    return JobSpec(
        req_id=fields.get("req_id", ""),
        title=title_match.group(1),
        division=fields.get("division"),
        location=fields.get("location"),
        employment_type=fields.get("employment_type"),
        ctc_range=fields.get("ctc_range"),
        min_years_experience=min_years_from_must_haves(musts),
        must_haves=[Requirement(text=t, kind=classify_kind(t)) for t in musts],
        nice_to_haves=[Requirement(text=t, kind=classify_kind(t)) for t in nices],
        responsibilities=section_bullets.get("responsibilities", []),
        source_file=source_file,
    )


def parse_jd_file(path: str | Path) -> JobSpec:
    path = Path(path)
    return parse_jd_markdown(path.read_text(encoding="utf-8"), source_file=path.name)
