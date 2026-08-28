"""JD parsing against the real requisition files — deterministic, offline."""

import harness
import pytest

from resume_analyzer.extract.jd import (
    classify_kind,
    min_years_from_must_haves,
    parse_jd_file,
    parse_jd_markdown,
)

JD_DIR = harness.DATASET_DIR / "job_descriptions"


def all_specs():
    return {s.req_id: s for s in (parse_jd_file(p) for p in sorted(JD_DIR.glob("*.md")))}


def test_payments_jd_parses_completely() -> None:
    spec = parse_jd_file(JD_DIR / "HOY-2026-011_senior-backend-engineer-payments.md")
    assert spec.req_id == "HOY-2026-011"
    assert spec.title == "Senior Backend Engineer — Payments Platform"
    assert spec.division == "Technology — Payments & Cards"
    assert "45 LPA" in spec.ctc_range
    assert spec.min_years_experience == 5.0
    assert len(spec.must_haves) == 5 and len(spec.nice_to_haves) == 4
    assert spec.responsibilities  # "What you'll do" bullets captured


def test_wrapped_bullets_are_joined() -> None:
    spec = parse_jd_file(JD_DIR / "HOY-2026-011_senior-backend-engineer-payments.md")
    # This bullet wraps across two source lines; the parser must join it.
    joined = [r for r in spec.responsibilities if "RuPay credit on UPI" in r]
    assert joined and "\n" not in joined[0]
    assert "unforgiving external deadlines" in joined[0]


def test_all_eight_jds_parse_with_ids_matching_filenames() -> None:
    specs = all_specs()
    assert len(specs) == 8
    for req_id, spec in specs.items():
        assert spec.source_file.startswith(req_id)
        assert spec.title and len(spec.must_haves) >= 4
        assert spec.location and "Bengaluru" in spec.location


def test_min_years_takes_the_overall_bar() -> None:
    specs = all_specs()
    assert specs["HOY-2026-025"].min_years_experience == 8.0  # "8+ yrs ... 3+ managing" -> 8
    assert specs["HOY-2026-019"].min_years_experience is None  # degree-based req, no years
    assert min_years_from_must_haves(["6+ years of which 3+ as HRBP"]) == 6.0


def test_kind_heuristic_on_representative_requirements() -> None:
    assert classify_kind("Fluent professional English.") == "language"
    assert classify_kind("CKA/CKS certification.") == "certification"
    assert classify_kind("MSc or PhD in a quantitative discipline.") == "education"
    assert classify_kind("5+ years of professional backend engineering.") == "experience"
    assert classify_kind("Strong experience with Spring Boot, Kafka.") == "experience"
    assert classify_kind("Deep working knowledge of Kubernetes.") == "skill"


def test_jd_answer_key_scores_16_of_16() -> None:
    """The M4 gate itself, enforced forever: parsing is deterministic, so the
    full answer key runs offline in the suite — a format drift in dataset/ or a
    parser regression fails CI, not a demo."""
    report = harness.grade_jd_extraction(all_specs())
    failed = [f"{r.fact.req_id}/{r.fact.list_name}: {r.detail}"
              for r in report.results if not r.passed]
    assert report.total == 16 and not failed, failed


def test_malformed_jd_fails_loudly() -> None:
    with pytest.raises(ValueError, match="title"):
        parse_jd_markdown("no title here\njust text", source_file="broken.md")
