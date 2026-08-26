"""Frozen data shapes for the screening pipeline (M2).

Three families of models:

- ``ResumeProfile`` — what extraction (M3) must produce from a candidate PDF.
- ``JobSpec``       — what extraction (M4) must produce from a requisition.
- ``Analysis``      — what scoring/reporting (M5/M6) must produce per application.

Two contracts are enforced *by the shapes themselves*, not by convention:

1. **PII quarantine.** Attributes that could reveal age, gender, community or
   family status live only in ``QuarantinedPII``. They are extracted (so parsing
   never breaks on a traditional CV) but ``ResumeProfile.for_scoring()`` — the
   only view scoring and reporting are allowed to consume — excludes them.
   ``languages_known`` stays a normal field because two requisitions list
   languages as a job requirement; the scoring rule (M5) is that it may be used
   only when the JobSpec explicitly requires a language.
2. **No ungrounded claims.** Every strength/gap/red-flag is a ``Finding`` and a
   Finding cannot exist without at least one piece of ``Evidence``. Claims about
   something *missing* cite the JD requirement they are checked against.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

YEAR_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class StrictModel(BaseModel):
    """Base for all shapes: unknown keys are errors, strings arrive stripped."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- shared


class Evidence(StrictModel):
    """A verbatim quote tying a claim back to its source document."""

    source: Literal["resume", "job_description"]
    field: str = Field(description="Where the quote came from, e.g. 'experience[0].bullets[2]'")
    quote: str = Field(min_length=1)


class Finding(StrictModel):
    """A claim (strength / gap / red flag) that must carry evidence."""

    text: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


# --------------------------------------------------------------------------- resume side


class ContactInfo(StrictModel):
    name: str = Field(min_length=1)
    email: str | None = None
    phone: str | None = None
    city: str | None = None


class QuarantinedPII(StrictModel):
    """Extracted but fenced off: never enters scoring or reports.

    Traditional Indian CVs carry personal-details blocks (DOB, marital status,
    photos). Parsing must not choke on them, so they are captured here — and
    ``ResumeProfile.for_scoring()`` is the enforcement point that keeps them out
    of every downstream judgment.
    """

    date_of_birth: str | None = None
    gender: str | None = None
    marital_status: str | None = None
    photo_present: bool = False
    other: list[str] = []


class RoleEntry(StrictModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str | None = None
    start: str | None = Field(default=None, description="Normalized YYYY-MM")
    end: str | None = Field(default=None, description="Normalized YYYY-MM; None = present")
    bullets: list[str] = []

    @field_validator("start", "end")
    @classmethod
    def _year_month(cls, v: str | None) -> str | None:
        if v is not None and not YEAR_MONTH.fullmatch(v):
            raise ValueError(f"dates must be 'YYYY-MM', got {v!r}")
        return v


class EducationEntry(StrictModel):
    degree: str = Field(min_length=1)
    institution: str | None = None
    years: str | None = Field(default=None, description="As written, e.g. '2013 - 2017'")
    grade: str | None = Field(default=None, description="CGPA/percentage as written, if any")


class SkillGroup(StrictModel):
    category: str | None = None
    items: list[str] = []


class ResumeProfile(StrictModel):
    """Everything extraction pulls from one candidate PDF."""

    source_file: str = Field(min_length=1, description="Path as listed in applications_log.csv")
    contact: ContactInfo
    headline: str | None = None
    summary: str | None = None
    skills: list[SkillGroup] = []
    experience: list[RoleEntry] = []
    education: list[EducationEntry] = []
    certifications: list[str] = []
    publications: list[str] = []
    languages_known: list[str] = []
    links: list[str] = []
    notice_period: str | None = None
    expected_ctc: str | None = None
    pii: QuarantinedPII = QuarantinedPII()

    @property
    def flat_skills(self) -> list[str]:
        return [item for group in self.skills for item in group.items]

    def for_scoring(self) -> dict:
        """The only resume view scoring/reporting may consume: PII excluded."""
        return self.model_dump(mode="json", exclude={"pii"})


# --------------------------------------------------------------------------- job side

RequirementKind = Literal[
    "skill", "experience", "education", "domain", "language", "certification", "other"
]


class Requirement(StrictModel):
    text: str = Field(min_length=1)
    kind: RequirementKind = "other"


class JobSpec(StrictModel):
    """Everything extraction pulls from one requisition markdown file."""

    req_id: str = Field(pattern=r"HOY-\d{4}-\d{3}")
    title: str = Field(min_length=1)
    division: str | None = None
    location: str | None = None
    employment_type: str | None = None
    ctc_range: str | None = None
    min_years_experience: float | None = Field(default=None, ge=0)
    must_haves: list[Requirement] = []
    nice_to_haves: list[Requirement] = []
    responsibilities: list[str] = []
    source_file: str | None = None


# --------------------------------------------------------------------------- analysis side


class DimensionScore(StrictModel):
    """One scored comparison dimension (skills / experience / domain)."""

    name: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    evidence: list[Evidence] = []
    commentary: str | None = None


class Analysis(StrictModel):
    """The tool's full judgment for one application against one requisition."""

    application_id: str | None = None
    req_id: str = Field(pattern=r"HOY-\d{4}-\d{3}")
    resume_file: str = Field(min_length=1)
    dimension_scores: list[DimensionScore] = []
    overall_score: float = Field(ge=0, le=100)
    strengths: list[Finding] = []
    gaps: list[Finding] = []
    red_flags: list[Finding] = []
    follow_up_questions: list[str] = []
