"""Parse all requisitions into JobSpecs and grade against the JD answer key.

M4 gates: 8/8 JDs parse into valid JobSpecs; 16/16 answer-key facts (100%),
where each fact also proves exact must-have/nice-to-have separation. No LLM
calls — the parser is deterministic (see extract/jd.py docstring for why).

Usage:  python eval/run_jd_extraction.py
"""

from __future__ import annotations

import datetime as dt
import json

import harness

from resume_analyzer.extract.jd import parse_jd_file
from resume_analyzer.models import JobSpec

JD_DIR = harness.DATASET_DIR / "job_descriptions"
OUTPUTS_DIR = harness.EVAL_DIR / "outputs"


def main() -> None:
    specs: dict[str, JobSpec] = {}
    failures: list[tuple[str, str]] = []
    for path in sorted(JD_DIR.glob("*.md")):
        try:
            spec = parse_jd_file(path)
            specs[spec.req_id] = spec
        except Exception as exc:
            failures.append((path.name, f"{type(exc).__name__}: {exc}"))

    grade = harness.grade_jd_extraction(specs)
    failed = [r for r in grade.results if not r.passed]

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUTPUTS_DIR / "jobspecs.json"
    out_json.write_text(
        json.dumps({rid: s.model_dump(mode="json") for rid, s in sorted(specs.items())},
                   indent=1, ensure_ascii=False),
        encoding="utf-8",
    )

    today = dt.date.today().isoformat()
    lines = [
        f"- JDs parsed into valid JobSpecs: **{len(specs)}/8**"
        + (f" — failures: {failures}" if failures else ""),
        f"- answer-key facts passed: **{grade.passed}/{grade.total} ({grade.rate:.0%})**"
        " — gate: 100%, each fact also proves exact must/nice separation",
        "- LLM calls: **0** (deterministic parser — the ATS format is ours)",
        "- per req: "
        + ", ".join(
            f"{rid} ({len(s.must_haves)} must / {len(s.nice_to_haves)} nice, "
            f"min {s.min_years_experience or '—'} yrs)"
            for rid, s in sorted(specs.items())
        ),
        f"- JobSpecs saved: `eval/outputs/{out_json.name}`",
    ]
    if failed:
        lines += ["", "## Failed facts"] + [
            f"- `{r.fact.req_id}` · {r.fact.list_name}: {r.detail}" for r in failed
        ]
    lines += ["", f"_Generated {today} by `python eval/run_jd_extraction.py`._"]
    report = harness.write_report(
        harness.REPORTS_DIR / f"{today}_M4_jd_extraction.md",
        "M4 JD extraction report",
        lines,
    )
    print(f"report: {report}")
    print(f"specs {len(specs)}/8 | facts {grade.passed}/{grade.total} ({grade.rate:.0%})")


if __name__ == "__main__":
    main()
