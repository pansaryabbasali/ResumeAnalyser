"""Run the benchmark harness end-to-end. M2 supports stub mode only.

Stub mode (``--stub``) proves the plumbing before any real extraction exists:
fake profiles are built straight from the ATS log (name + file only), fake
scores are derived from the candidate's name length. The resulting numbers are
meaningless BY DESIGN — what matters is that labels load, every fixture fact is
looked up, the ordering metric computes, and a report lands in eval/reports/.

Usage:  python eval/run_eval.py --stub
"""

from __future__ import annotations

import argparse
import datetime as dt

import harness

from resume_analyzer.models import ContactInfo, ResumeProfile


def stub_profiles(records: list[harness.ApplicationRecord]) -> dict[str, ResumeProfile]:
    """Minimal profiles from the log alone: only name and file are 'right'."""
    return {
        r.resume_file: ResumeProfile(
            source_file=r.resume_file,
            contact=ContactInfo(name=r.candidate_name),
        )
        for r in records
    }


def stub_scores(records: list[harness.ApplicationRecord]) -> dict[str, float]:
    """Deterministic junk: score = length of the candidate's name."""
    return {r.application_id: float(len(r.candidate_name)) for r in records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stub", action="store_true", help="run on stub outputs (M2 smoke)")
    args = parser.parse_args()
    if not args.stub:
        raise SystemExit("Only --stub exists until M3 lands real extraction.")

    records = harness.load_labels()
    counts = harness.outcome_counts(records)
    facts = harness.load_fixture()
    extraction = harness.grade_extraction(stub_profiles(records), facts)
    ordering = harness.pairwise_ordering(records, stub_scores(records))

    today = dt.date.today().isoformat()
    lines = [
        "**SMOKE RUN ON STUB OUTPUTS — every number below is meaningless by design.**",
        "This report only proves the harness plumbing works end-to-end before M3.",
        "",
        "## Benchmark labels",
        f"- applications loaded: {len(records)}",
        f"- outcomes: {counts['advanced']} advanced / "
        f"{counts['hold_second_review']} hold_second_review / {counts['rejected']} rejected",
        "",
        "## Extraction answer key",
        f"- facts: {len(facts)} across {len({f.resume_file for f in facts})} resumes",
        f"- stub pass rate: {extraction.passed}/{extraction.total} "
        f"({extraction.rate:.0%}) — stub profiles only carry the candidate name",
        "",
        "## Pairwise ordering metric (M5 gate, easy classes only)",
        f"- comparable advanced-vs-rejected pairs: {ordering.total}",
        f"- stub ordering rate: {ordering.correct}/{ordering.total} ({ordering.rate:.0%}) "
        "— scores are name lengths, as intended",
        "- per requisition: "
        + ", ".join(f"{req} {c}/{t}" for req, (c, t) in sorted(ordering.per_req.items())),
        "",
        f"_Generated {today} by `python eval/run_eval.py --stub`._",
    ]
    out = harness.write_report(
        harness.REPORTS_DIR / f"{today}_M2_harness_smoke.md",
        "M2 harness smoke report",
        lines,
    )
    print(f"report written: {out}")
    print(f"labels {len(records)} | facts {len(facts)} | "
          f"stub extraction {extraction.rate:.0%} | stub ordering {ordering.rate:.0%}")


if __name__ == "__main__":
    main()
