"""Scoring engine: experience math, the years-gated blend, analysis assembly."""

from resume_analyzer.matching import LexicalMatcher, build_pool
from resume_analyzer.models import (
    ContactInfo,
    JobSpec,
    Requirement,
    ResumeProfile,
    RoleEntry,
    SkillGroup,
)
from resume_analyzer.scoring import (
    analyze,
    rank,
    score_requirement,
    years_of_experience,
)


def profile_with_roles(*roles: RoleEntry, skills: list[str] | None = None) -> ResumeProfile:
    return ResumeProfile(
        source_file="resumes/x.pdf",
        contact=ContactInfo(name="Test"),
        skills=[SkillGroup(items=skills or [])],
        experience=list(roles),
    )


# --------------------------------------------------------------------------- experience math


def test_years_merges_overlaps_and_open_roles() -> None:
    profile = profile_with_roles(
        RoleEntry(title="A", company="X", start="2020-01", end="2022-01"),
        RoleEntry(title="B", company="Y", start="2021-06", end="2023-06"),  # overlaps A
        RoleEntry(title="C", company="Z", start="2024-08", end=None),  # open -> 2026-08
    )
    # 2020-01..2023-06 = 41 months, 2024-08..2026-08 = 24 months -> 65/12
    assert years_of_experience(profile) == round(65 / 12, 2)


def test_years_ignores_undatable_and_future_roles() -> None:
    profile = profile_with_roles(
        RoleEntry(title="A", company="X", start=None, end=None),
        RoleEntry(title="B", company="Y", start="2027-01", end="2028-01"),  # after reference
    )
    assert years_of_experience(profile) == 0.0


# --------------------------------------------------------------------------- years-gated blend


def test_unrelated_years_earn_at_most_half() -> None:
    """The keyword-stuffer rule: 5 years of anything != 5 years of the asked field."""
    req = Requirement(text="3+ years of backend engineering in Python", kind="experience")
    unrelated = profile_with_roles(
        RoleEntry(title="Growth Marketer", company="Brands", start="2021-01", end=None,
                  bullets=["Ran paid social campaigns."]),
    )
    matched = profile_with_roles(
        RoleEntry(title="Backend Engineer", company="Acme", start="2021-01", end=None,
                  bullets=["Built Python backend services."]),
        skills=["Python"],
    )
    matcher = LexicalMatcher()
    low = score_requirement(req, build_pool(unrelated), 5.6, matcher)
    high = score_requirement(req, build_pool(matched), 5.6, matcher)
    assert low.score <= 0.55 < high.score  # ceiling earned only with textual context
    assert "5.6 yrs vs 3+" in low.note


def test_underyeared_but_matching_profile_is_capped() -> None:
    req = Requirement(text="5+ years on the JVM", kind="experience")
    profile = profile_with_roles(
        RoleEntry(title="Java Developer", company="Bank", start="2024-08", end=None,
                  bullets=["JVM services."]),
        skills=["Java", "JVM"],
    )
    result = score_requirement(req, build_pool(profile), 2.0, LexicalMatcher())
    assert result.score <= 0.4  # 2/5 ceiling regardless of perfect text match


# --------------------------------------------------------------------------- analysis assembly


SPEC = JobSpec(
    req_id="HOY-2026-011",
    title="Backend Engineer",
    must_haves=[
        Requirement(text="5+ years of backend engineering on the JVM", kind="experience"),
        Requirement(text="Kafka and PostgreSQL in production", kind="skill"),
    ],
    nice_to_haves=[Requirement(text="UPI or payments domain", kind="domain")],
)


def strong_profile() -> ResumeProfile:
    return profile_with_roles(
        RoleEntry(title="Senior Backend Engineer", company="Aurus Pay", start="2018-01",
                  end=None, bullets=["Kafka and PostgreSQL services for UPI payments on the JVM."]),
        skills=["Java", "Kafka", "PostgreSQL"],
    )


def weak_profile() -> ResumeProfile:
    return profile_with_roles(
        RoleEntry(title="QA Tester", company="TestCo", start="2024-06", end=None,
                  bullets=["Manual test cases in JIRA."]),
        skills=["Selenium"],
    )


def test_analyze_orders_strong_above_weak_with_evidence() -> None:
    matcher = LexicalMatcher()
    strong = analyze(strong_profile(), SPEC, matcher, application_id="A1")
    weak = analyze(weak_profile(), SPEC, matcher, application_id="W1")
    assert strong.overall_score > weak.overall_score + 30
    assert 0 <= weak.overall_score <= strong.overall_score <= 100
    # Evidence quotes must be traceable to the profile pool, never invented.
    pool_texts = {item.text for item in build_pool(strong_profile())}
    for dim in strong.dimension_scores:
        for ev in dim.evidence:
            assert any(ev.quote in text or text in ev.quote for text in pool_texts)
    # Weights are rounded to 3 decimals for display, so the sum carries rounding dust.
    assert abs(sum(d.weight for d in strong.dimension_scores) - 1.0) < 0.01


def test_rank_is_descending_and_stable() -> None:
    matcher = LexicalMatcher()
    analyses = [
        analyze(weak_profile(), SPEC, matcher, application_id="W1"),
        analyze(strong_profile(), SPEC, matcher, application_id="A1"),
    ]
    ordered = rank(analyses)
    assert [a.application_id for a in ordered] == ["A1", "W1"]
    assert ordered[0].overall_score >= ordered[1].overall_score
