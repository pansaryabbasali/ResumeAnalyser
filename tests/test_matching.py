"""Matching layer: pool building, normalization, lexical matcher. Offline."""

import pytest

from resume_analyzer.matching import (
    LexicalMatcher,
    build_pool,
    make_matcher,
    normalize_tokens,
)
from resume_analyzer.models import (
    ContactInfo,
    QuarantinedPII,
    ResumeProfile,
    RoleEntry,
    SkillGroup,
)


def make_profile() -> ResumeProfile:
    return ResumeProfile(
        source_file="resumes/x.pdf",
        contact=ContactInfo(name="Asha Rao"),
        headline="Platform Engineer",
        skills=[SkillGroup(category="Platform", items=["K8s", "Terraform", "AWS"])],
        experience=[
            RoleEntry(
                title="SRE", company="Acme", start="2020-01",
                bullets=["Ran EKS clusters with Prometheus monitoring."],
            )
        ],
        certifications=["CKA (2023)"],
        pii=QuarantinedPII(date_of_birth="14-06-1991", marital_status="married"),
    )


def test_normalize_folds_synonyms_and_drops_stopwords() -> None:
    tokens = normalize_tokens("Strong experience with K8s, Postgres and Golang")
    assert {"kubernetes", "postgresql", "go"} <= tokens
    assert "experience" not in tokens and "with" not in tokens


def test_pool_has_field_paths_and_never_pii() -> None:
    pool = build_pool(make_profile())
    fields = {item.field for item in pool}
    assert "headline" in fields and "skills[0]" in fields
    assert "experience[0].bullets[0]" in fields and "certifications[0]" in fields
    joined = " ".join(item.text for item in pool)
    assert "14-06-1991" not in joined and "married" not in joined


def test_lexical_matcher_scores_coverage_with_evidence() -> None:
    pool = build_pool(make_profile())
    matcher = LexicalMatcher()
    full = matcher.best_match("Kubernetes and Terraform", pool)
    assert full.score == 1.0 and full.item is not None  # k8s synonym + terraform
    partial = matcher.best_match("Kubernetes and Ansible", pool)
    assert 0.0 < partial.score < 1.0
    miss = matcher.best_match("Figma prototyping", pool)
    assert miss.score == 0.0 and miss.item is None
    assert matcher.best_match("anything", []).score == 0.0


def test_matcher_registry_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown matcher"):
        make_matcher("gpt-vibes")


@pytest.mark.models
def test_minilm_catches_semantics_keywords_miss() -> None:
    """Requirement texts are full sentences in this corpus; terse queries sit
    below the measured calibration floor by design (noise, not signal)."""
    pool = build_pool(make_profile())
    matcher = make_matcher("minilm")
    semantic = matcher.best_match(
        "Hands-on experience running containerized workloads on Kubernetes clusters "
        "with Prometheus-style monitoring in production", pool,
    )
    unrelated = matcher.best_match(
        "Experience planning fashion retail merchandising campaigns for festive seasons", pool,
    )
    assert semantic.score > 0.3
    assert unrelated.score < semantic.score
