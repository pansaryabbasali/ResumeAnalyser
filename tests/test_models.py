"""The frozen shapes enforce their two contracts: PII quarantine, evidence-or-nothing."""

import json

import pytest
from pydantic import ValidationError

from resume_analyzer.models import (
    Analysis,
    ContactInfo,
    Evidence,
    Finding,
    JobSpec,
    QuarantinedPII,
    ResumeProfile,
    RoleEntry,
    SkillGroup,
)


def make_profile(**overrides) -> ResumeProfile:
    base = dict(
        source_file="resumes/HOY-2026-011/example.pdf",
        contact=ContactInfo(name="Test Candidate", email="t@example.com"),
        skills=[SkillGroup(category="Languages", items=["Java", "SQL"])],
        experience=[RoleEntry(title="Engineer", company="Acme", start="2021-03", end=None)],
        pii=QuarantinedPII(date_of_birth="14-06-1991", marital_status="married"),
    )
    base.update(overrides)
    return ResumeProfile(**base)


def test_valid_profile_builds_and_flattens_skills() -> None:
    profile = make_profile()
    assert profile.flat_skills == ["Java", "SQL"]
    assert profile.experience[0].end is None  # None means "present"


def test_dates_must_be_normalized_year_month() -> None:
    with pytest.raises(ValidationError, match="YYYY-MM"):
        RoleEntry(title="Engineer", company="Acme", start="March 2021")


def test_for_scoring_excludes_quarantined_pii() -> None:
    dumped = json.dumps(make_profile().for_scoring())
    assert "14-06-1991" not in dumped
    assert "married" not in dumped
    assert "pii" not in json.loads(dumped)
    # ...while the full model still carries it for parsing completeness.
    assert make_profile().pii.date_of_birth == "14-06-1991"


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ContactInfo(name="X", emial="typo@example.com")


def test_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Finding(text="Strong Kafka experience", evidence=[])
    ok = Finding(
        text="Missing Kubernetes",
        evidence=[Evidence(source="job_description", field="must_haves[2]", quote="Kubernetes")],
    )
    assert ok.evidence[0].source == "job_description"


def test_jobspec_req_id_pattern_and_score_bounds() -> None:
    with pytest.raises(ValidationError):
        JobSpec(req_id="CAS-2026-011", title="Wrong prefix")
    with pytest.raises(ValidationError):
        Analysis(req_id="HOY-2026-011", resume_file="x.pdf", overall_score=101)
    ok = Analysis(req_id="HOY-2026-011", resume_file="x.pdf", overall_score=72.5)
    assert ok.strengths == []
