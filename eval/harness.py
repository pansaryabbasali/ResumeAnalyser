"""Benchmark harness (M2): labels, extraction grading, ranking agreement.

Three jobs, used by every later milestone:

1. ``load_labels()`` — reads ``dataset/applications_log.csv`` (the ATS export)
   into typed records; the ``recruiter_screen_outcome`` column is the benchmark.
2. ``grade_extraction()`` — checks ResumeProfiles against the hand-curated
   answer key in ``fixtures/extraction_fixture.json`` (M3's exit gate).
3. ``pairwise_ordering()`` — the M5 exit gate: within each requisition, every
   'advanced' application must outscore every 'rejected' one. The 15
   'hold_second_review' applications are deliberately excluded — they are
   review cases, not accuracy targets (see build plan).

Reports are written as markdown into ``eval/reports/`` and committed, so every
milestone's numbers live in the repo history.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from resume_analyzer.models import JobSpec, ResumeProfile

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
LABELS_CSV = DATASET_DIR / "applications_log.csv"
FIXTURE_JSON = EVAL_DIR / "fixtures" / "extraction_fixture.json"
JD_FIXTURE_JSON = EVAL_DIR / "fixtures" / "jd_fixture.json"
REPORTS_DIR = EVAL_DIR / "reports"

OUTCOMES = ("advanced", "hold_second_review", "rejected")


# --------------------------------------------------------------------------- labels


@dataclass(frozen=True)
class ApplicationRecord:
    application_id: str
    req_id: str
    role_title: str
    candidate_name: str
    resume_file: str
    outcome: str
    notes: str


def load_labels(csv_path: Path = LABELS_CSV) -> list[ApplicationRecord]:
    """Read the ATS export; fail loudly if it doesn't look like our benchmark."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    records = [
        ApplicationRecord(
            application_id=r["application_id"],
            req_id=r["req_id"],
            role_title=r["role_title"],
            candidate_name=r["candidate_name"],
            resume_file=r["resume_file"],
            outcome=r["recruiter_screen_outcome"],
            notes=r["recruiter_notes"],
        )
        for r in rows
    ]
    if len(records) != 40:
        raise ValueError(f"expected 40 applications, found {len(records)}")
    bad = [r.application_id for r in records if r.outcome not in OUTCOMES]
    if bad:
        raise ValueError(f"unknown outcomes on: {bad}")
    return records


def outcome_counts(records: list[ApplicationRecord]) -> dict[str, int]:
    return {o: sum(1 for r in records if r.outcome == o) for o in OUTCOMES}


# --------------------------------------------------------------------------- extraction grading


@dataclass(frozen=True)
class FixtureFact:
    application_id: str
    resume_file: str
    field: str
    expected: str | None
    expect_empty: bool
    note: str


@dataclass
class FactResult:
    fact: FixtureFact
    passed: bool
    detail: str


@dataclass
class ExtractionReport:
    results: list[FactResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def load_fixture(path: Path = FIXTURE_JSON) -> list[FixtureFact]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        FixtureFact(
            application_id=f["application_id"],
            resume_file=f["resume_file"],
            field=f["field"],
            expected=f.get("expected"),
            expect_empty=f.get("expect_empty", False),
            note=f.get("note", ""),
        )
        for f in data["facts"]
    ]


def collect_field(profile: ResumeProfile, field_name: str) -> list[str]:
    """Gather the string values a fixture field refers to.

    This mapping *is* the operational definition of each fixture field — the
    fixture's vocabulary is bounded to these names on purpose.
    """
    simple = {
        "contact.name": lambda p: [p.contact.name],
        "contact.email": lambda p: [p.contact.email] if p.contact.email else [],
        "contact.phone": lambda p: [p.contact.phone] if p.contact.phone else [],
        "contact.city": lambda p: [p.contact.city] if p.contact.city else [],
        "notice_period": lambda p: [p.notice_period] if p.notice_period else [],
        "expected_ctc": lambda p: [p.expected_ctc] if p.expected_ctc else [],
        "experience.company": lambda p: [r.company for r in p.experience],
        "experience.title": lambda p: [r.title for r in p.experience],
        "experience.start": lambda p: [r.start for r in p.experience if r.start],
        "education.institution": lambda p: [e.institution for e in p.education if e.institution],
        "education.degree": lambda p: (
            [e.degree for e in p.education] + [e.grade for e in p.education if e.grade]
        ),
        "certifications": lambda p: p.certifications,
        "skills": lambda p: p.flat_skills,
        "publications": lambda p: p.publications,
        "languages_known": lambda p: p.languages_known,
        "pii.date_of_birth": lambda p: [p.pii.date_of_birth] if p.pii.date_of_birth else [],
    }
    emptiable = {
        "education": lambda p: [e.degree for e in p.education],
        "experience": lambda p: [r.company for r in p.experience],
    }
    if field_name in simple:
        return simple[field_name](profile)
    if field_name in emptiable:
        return emptiable[field_name](profile)
    raise KeyError(f"fixture field {field_name!r} is not in the harness vocabulary")


def grade_extraction(
    profiles: dict[str, ResumeProfile],
    facts: list[FixtureFact] | None = None,
) -> ExtractionReport:
    """Grade extracted profiles (keyed by resume_file) against the answer key."""
    facts = facts if facts is not None else load_fixture()
    report = ExtractionReport()
    for fact in facts:
        profile = profiles.get(fact.resume_file)
        if profile is None:
            report.results.append(FactResult(fact, False, "no profile extracted for this file"))
            continue
        values = collect_field(profile, fact.field)
        if fact.expect_empty:
            passed = not values
            detail = "empty as expected" if passed else f"expected empty, found {values!r}"
        else:
            assert fact.expected is not None
            passed = any(fact.expected.lower() in v.lower() for v in values)
            detail = "found" if passed else f"{fact.expected!r} not in {values!r}"
        report.results.append(FactResult(fact, passed, detail))
    return report


# --------------------------------------------------------------------------- JD grading


@dataclass(frozen=True)
class JdFact:
    req_id: str
    list_name: str  # "must_haves" | "nice_to_haves"
    expected: str


@dataclass
class JdFactResult:
    fact: JdFact
    passed: bool
    detail: str


@dataclass
class JdReport:
    results: list[JdFactResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


def load_jd_fixture(path: Path = JD_FIXTURE_JSON) -> list[JdFact]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        JdFact(req_id=f["req_id"], list_name=f["list"], expected=f["expected"])
        for f in data["facts"]
    ]


def grade_jd_extraction(
    specs: dict[str, JobSpec], facts: list[JdFact] | None = None
) -> JdReport:
    """Grade parsed JobSpecs (keyed by req_id) against the JD answer key.

    A fact passes only if the phrase appears in the NAMED list and NOT in the
    other one — must/nice separation is exact by definition of the gate.
    """
    facts = facts if facts is not None else load_jd_fixture()
    report = JdReport()
    for fact in facts:
        spec = specs.get(fact.req_id)
        if spec is None:
            report.results.append(JdFactResult(fact, False, "no JobSpec for this req"))
            continue
        named, other = ("must_haves", "nice_to_haves")
        if fact.list_name == "nice_to_haves":
            named, other = other, named
        in_named = any(fact.expected.lower() in r.text.lower() for r in getattr(spec, named))
        in_other = any(fact.expected.lower() in r.text.lower() for r in getattr(spec, other))
        if in_named and not in_other:
            report.results.append(JdFactResult(fact, True, "found, cleanly separated"))
        elif not in_named:
            report.results.append(
                JdFactResult(fact, False, f"{fact.expected!r} missing from {named}")
            )
        else:
            report.results.append(
                JdFactResult(fact, False, f"{fact.expected!r} leaked into {other}")
            )
    return report


# --------------------------------------------------------------------------- ranking agreement


@dataclass
class OrderingReport:
    correct: int = 0
    total: int = 0
    per_req: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def rate(self) -> float:
        return self.correct / self.total if self.total else 0.0


def pairwise_ordering(
    records: list[ApplicationRecord],
    scores: dict[str, float],
) -> OrderingReport:
    """M5 gate: within each req, every 'advanced' must outscore every 'rejected'.

    Applications missing from ``scores`` count as failures — silence must never
    inflate the number. 'hold_second_review' applications take no part.
    """
    report = OrderingReport()
    req_ids = sorted({r.req_id for r in records})
    for req_id in req_ids:
        advanced = [r for r in records if r.req_id == req_id and r.outcome == "advanced"]
        rejected = [r for r in records if r.req_id == req_id and r.outcome == "rejected"]
        correct = total = 0
        for a in advanced:
            for j in rejected:
                total += 1
                both_scored = a.application_id in scores and j.application_id in scores
                if both_scored and scores[a.application_id] > scores[j.application_id]:
                    correct += 1
        report.per_req[req_id] = (correct, total)
        report.correct += correct
        report.total += total
    return report


# --------------------------------------------------------------------------- reporting


def write_report(path: Path, title: str, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join([f"# {title}", ""] + lines) + "\n"
    path.write_text(body, encoding="utf-8")
    return path
