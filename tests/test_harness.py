"""The benchmark harness: labels load, answer key is coherent, metrics compute."""

import sys

import harness
import pytest
import run_eval

from resume_analyzer.models import ContactInfo, EducationEntry, ResumeProfile, RoleEntry

KARTHIK = "resumes/HOY-2026-011/Karthik_Raghavan_Resume_2026.pdf"


def test_labels_load_with_expected_distribution() -> None:
    records = harness.load_labels()
    assert len(records) == 40
    counts = harness.outcome_counts(records)
    assert counts == {"advanced": 9, "hold_second_review": 15, "rejected": 16}


def test_labels_reference_files_that_exist() -> None:
    for record in harness.load_labels():
        assert (harness.DATASET_DIR / record.resume_file).is_file(), record.resume_file


def test_fixture_is_coherent_with_labels_and_vocabulary() -> None:
    records = {r.application_id: r for r in harness.load_labels()}
    facts = harness.load_fixture()
    assert len(facts) >= 35
    empty = ResumeProfile(source_file="x.pdf", contact=ContactInfo(name="Nobody"))
    for fact in facts:
        assert fact.application_id in records, fact.application_id
        assert fact.resume_file == records[fact.application_id].resume_file
        harness.collect_field(empty, fact.field)  # unknown field would raise KeyError
        assert fact.expect_empty or fact.expected


def test_grade_extraction_passes_and_fails_correctly() -> None:
    profile = ResumeProfile(
        source_file=KARTHIK,
        contact=ContactInfo(name="Karthik Raghavan", email="karthik.raghavan89@gmail.com"),
        experience=[RoleEntry(title="Senior Backend Engineer", company="Aurus Pay Technologies",
                              start="2021-03")],
        education=[EducationEntry(degree="B.Tech CSE", institution="NIT Tiruchirappalli")],
        certifications=["Confluent Certified Developer for Apache Kafka (2022)"],
        notice_period="30 days",
    )
    facts = [f for f in harness.load_fixture() if f.resume_file == KARTHIK]
    report = harness.grade_extraction({KARTHIK: profile}, facts)
    assert report.total == 6
    assert report.passed == 6  # all six Karthik facts satisfied by this profile

    # A profile missing the file entirely fails every fact, never crashes.
    report_missing = harness.grade_extraction({}, facts)
    assert report_missing.passed == 0


def test_expect_empty_fact_semantics() -> None:
    aryan_file = "resumes/HOY-2026-017/ARYAN_KAPOOR_AI_EXPERT_RESUME.pdf"
    facts = [f for f in harness.load_fixture() if f.expect_empty]
    assert len(facts) == 1 and facts[0].resume_file == aryan_file
    empty = ResumeProfile(source_file=aryan_file, contact=ContactInfo(name="Aryan Kapoor"))
    hallucinated = ResumeProfile(
        source_file=aryan_file,
        contact=ContactInfo(name="Aryan Kapoor"),
        education=[EducationEntry(degree="Invented MBA")],
    )
    assert harness.grade_extraction({aryan_file: empty}, facts).passed == 1
    assert harness.grade_extraction({aryan_file: hallucinated}, facts).passed == 0


def test_pairwise_ordering_metric() -> None:
    def rec(app_id: str, outcome: str) -> harness.ApplicationRecord:
        return harness.ApplicationRecord(app_id, "HOY-2026-011", "t", "n", "f.pdf", outcome, "")

    records = [rec("A1", "advanced"), rec("R1", "rejected"), rec("R2", "rejected"),
               rec("H1", "hold_second_review")]
    perfect = harness.pairwise_ordering(records, {"A1": 90.0, "R1": 40.0, "R2": 10.0, "H1": 99.0})
    assert (perfect.correct, perfect.total, perfect.rate) == (2, 2, 1.0)  # holds take no part
    partial = harness.pairwise_ordering(records, {"A1": 50.0, "R1": 70.0, "R2": 10.0})
    assert (partial.correct, partial.total) == (1, 2)
    unscored = harness.pairwise_ordering(records, {"A1": 90.0})  # missing scores never inflate
    assert (unscored.correct, unscored.total) == (0, 2)


def test_stub_run_writes_labeled_smoke_report(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(harness, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--stub"])
    run_eval.main()
    reports = list(tmp_path.glob("*_M2_harness_smoke.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "STUB OUTPUTS" in body and "meaningless by design" in body
    assert "40" in body


def test_stub_run_rejects_non_stub_mode(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["run_eval.py"])
    with pytest.raises(SystemExit, match="stub"):
        run_eval.main()
