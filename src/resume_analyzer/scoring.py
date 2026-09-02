"""Alignment scoring (M5): requirement coverage with evidence, then ranking.

The score is *requirement coverage*: every must-have and nice-to-have in the
JobSpec is scored 0..1 against the resume's evidence pool, and the overall
score is ``100 * (0.75 * mean(musts) + 0.25 * mean(nices))`` — the M4 gate
guaranteed the two lists are cleanly separated, so the weights mean something.

Two scoring rules, by requirement type:

- **Years-gated requirements** ("5+ years of backend engineering on the JVM"):
  the years figure sets a ceiling (`min(1, years/needed)` from merged role
  intervals), and the requirement's *text* match decides how much of that
  ceiling is earned: ``ceiling * (0.5 + 0.5 * text_match)``. A 5-year career
  in the wrong field earns at most half — this is what stops a keyword-stuffed
  CV with years of unrelated work from cashing in on "N+ years" requirements.
- **Everything else**: the matcher's best evidence score, with evidence kept
  only above a noise floor (0.35) so reports never cite junk matches.

Experience arithmetic uses a fixed reference month (the 2026-Q3 hiring round),
not the wall clock — scores are reproducible forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from resume_analyzer.matching import Matcher, MatchResult, PoolItem, build_pool
from resume_analyzer.models import (
    Analysis,
    DimensionScore,
    Evidence,
    JobSpec,
    Requirement,
    ResumeProfile,
)

REFERENCE_MONTH = 2026 * 12 + 8  # August 2026: the hiring-round window
EVIDENCE_FLOOR = 0.35
MUST_WEIGHT, NICE_WEIGHT = 0.75, 0.25

_YEARS_RE = re.compile(r"(\d+)\+?\s*years?", re.IGNORECASE)


# --------------------------------------------------------------------------- experience math


def _month_index(year_month: str) -> int:
    year, month = year_month.split("-")
    return int(year) * 12 + int(month)


def months_of_experience(profile: ResumeProfile, reference: int = REFERENCE_MONTH) -> int:
    """Total months across roles, overlaps merged, open roles ending at reference."""
    intervals: list[tuple[int, int]] = []
    for role in profile.experience:
        if role.start is None:
            continue  # undatable roles cannot be counted
        start = _month_index(role.start)
        end = _month_index(role.end) if role.end else reference
        if end > start:
            intervals.append((min(start, reference), min(end, reference)))
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def years_of_experience(profile: ResumeProfile, reference: int = REFERENCE_MONTH) -> float:
    return round(months_of_experience(profile, reference) / 12, 2)


# --------------------------------------------------------------------------- requirement scoring


@dataclass
class RequirementScore:
    requirement: Requirement
    score: float  # 0..1
    match: MatchResult | None
    note: str


def score_requirement(
    req: Requirement, pool: list[PoolItem], years: float, matcher: Matcher
) -> RequirementScore:
    years_match = _YEARS_RE.search(req.text) if req.kind == "experience" else None
    if years_match:
        needed = max(int(m.group(1)) for m in _YEARS_RE.finditer(req.text))
        ceiling = min(1.0, years / needed) if needed else 1.0
        text = matcher.best_match(req.text, pool)
        score = ceiling * (0.5 + 0.5 * text.score)
        note = f"{years:.1f} yrs vs {needed}+ required; context match {text.score:.2f}"
        return RequirementScore(req, score, text, note)
    match = matcher.best_match(req.text, pool)
    return RequirementScore(req, match.score, match, f"best evidence {match.score:.2f}")


def _mean(scores: list[RequirementScore]) -> float:
    return sum(s.score for s in scores) / len(scores) if scores else 0.0


_DIMENSIONS = {
    "skills & tools": ("skill", "certification"),
    "experience & seniority": ("experience",),
    "domain": ("domain",),
    "education & language": ("education", "language"),
}


def _evidence(scores: list[RequirementScore], limit: int = 3) -> list[Evidence]:
    scored = [
        s for s in scores
        if s.match and s.match.item and s.score >= EVIDENCE_FLOOR
    ]
    scored.sort(key=lambda s: s.score, reverse=True)
    return [
        Evidence(source="resume", field=s.match.item.field, quote=s.match.item.text[:300])
        for s in scored[:limit]
    ]


# --------------------------------------------------------------------------- analysis


def analyze(
    profile: ResumeProfile,
    spec: JobSpec,
    matcher: Matcher,
    application_id: str | None = None,
) -> Analysis:
    pool = build_pool(profile)
    years = years_of_experience(profile)
    musts = [score_requirement(r, pool, years, matcher) for r in spec.must_haves]
    nices = [score_requirement(r, pool, years, matcher) for r in spec.nice_to_haves]
    if nices:
        overall = 100 * (MUST_WEIGHT * _mean(musts) + NICE_WEIGHT * _mean(nices))
    else:
        overall = 100 * _mean(musts)

    everything = musts + nices
    dimensions: list[DimensionScore] = []
    for dim_name, kinds in _DIMENSIONS.items():
        in_dim = [s for s in everything if s.requirement.kind in kinds]
        if not in_dim:
            continue
        dimensions.append(
            DimensionScore(
                name=dim_name,
                score=round(100 * _mean(in_dim), 1),
                weight=round(len(in_dim) / len(everything), 3),
                evidence=_evidence(in_dim),
                commentary="; ".join(s.note for s in in_dim[:3]),
            )
        )
    return Analysis(
        application_id=application_id,
        req_id=spec.req_id,
        resume_file=profile.source_file,
        dimension_scores=dimensions,
        overall_score=round(overall, 1),
    )


def rank(analyses: list[Analysis]) -> list[Analysis]:
    """Triage order for one requisition: highest score first, stable on ties."""
    return sorted(analyses, key=lambda a: a.overall_score, reverse=True)
