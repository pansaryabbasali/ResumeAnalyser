"""Run resume extraction over the corpus and grade it against the answer key.

The M3 gates: >=90% fixture-fact survival, and 40/40 resumes producing a valid
profile without a crash. Live LLM calls go through the vendored gateway and the
SQLite response cache, so re-runs (and re-grading) are free.

Usage:
  python eval/run_extraction.py --strategy single_pass --subset fixture
  python eval/run_extraction.py --strategy sectioned   --subset fixture
  python eval/run_extraction.py --strategy single_pass --subset all
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json

import harness

from llm_gateway import Gateway
from resume_analyzer import pdfio
from resume_analyzer.extract import ResponseCache, ResumeExtractor
from resume_analyzer.models import ResumeProfile

CACHE_PATH = harness.REPO_ROOT / ".cache" / "llm_responses.sqlite"
OUTPUTS_DIR = harness.EVAL_DIR / "outputs"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=["single_pass", "sectioned"], required=True)
    parser.add_argument("--subset", choices=["fixture", "all"], default="fixture")
    args = parser.parse_args()

    records = harness.load_labels()
    facts = harness.load_fixture()
    if args.subset == "fixture":
        files = sorted({f.resume_file for f in facts})
    else:
        files = sorted({r.resume_file for r in records})
    graded_facts = [f for f in facts if f.resume_file in set(files)]

    profiles: dict[str, ResumeProfile] = {}
    failures: list[tuple[str, str]] = []
    totals = collections.Counter()
    providers: collections.Counter = collections.Counter()

    with ResponseCache(CACHE_PATH) as cache:
        extractor = ResumeExtractor(Gateway(), cache)
        for i, resume_file in enumerate(files, 1):
            try:
                text = pdfio.extract_text(harness.DATASET_DIR / resume_file)
                result = extractor.extract(text, resume_file, strategy=args.strategy)
            except Exception as exc:  # the gate counts every crash — never skip silently
                failures.append((resume_file, f"{type(exc).__name__}: {exc}"))
                print(f"[{i}/{len(files)}] FAIL {resume_file}: {exc}")
                continue
            profiles[resume_file] = result.profile
            totals.update(
                calls=result.calls, cache_hits=result.cache_hits,
                tokens=result.tokens, repairs=result.repairs,
            )
            providers.update(result.providers)
            print(f"[{i}/{len(files)}] ok {resume_file} "
                  f"(calls={result.calls} cached={result.cache_hits} repairs={result.repairs})")

    grade = harness.grade_extraction(profiles, graded_facts)
    failed_facts = [r for r in grade.results if not r.passed]

    today = dt.date.today().isoformat()
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUTPUTS_DIR / f"profiles_{args.strategy}_{args.subset}.json"
    out_json.write_text(
        json.dumps({f: p.model_dump(mode="json") for f, p in sorted(profiles.items())},
                   indent=1, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        f"- strategy: **{args.strategy}** · subset: **{args.subset}** ({len(files)} resumes)",
        f"- parsed without crash: **{len(profiles)}/{len(files)}**"
        + (f" — failures: {failures}" if failures else ""),
        f"- fixture facts passed: **{grade.passed}/{grade.total} ({grade.rate:.1%})**"
        f" — gate: >=90%",
        f"- LLM calls: {totals['calls']} (cache hits {totals['cache_hits']},"
        f" repair rounds {totals['repairs']}) · tokens: {totals['tokens']:,}",
        f"- providers: {dict(providers)}",
        f"- profiles saved: `eval/outputs/{out_json.name}`",
    ]
    if failed_facts:
        lines += ["", "## Failed facts"] + [
            f"- `{r.fact.resume_file}` · `{r.fact.field}`: {r.detail}" for r in failed_facts
        ]
    lines += ["", f"_Generated {today} by `python eval/run_extraction.py"
              f" --strategy {args.strategy} --subset {args.subset}`._"]
    report = harness.write_report(
        harness.REPORTS_DIR / f"{today}_M3_extraction_{args.strategy}_{args.subset}.md",
        f"M3 extraction report — {args.strategy} / {args.subset}",
        lines,
    )
    print(f"\nreport: {report}")
    print(f"facts {grade.passed}/{grade.total} ({grade.rate:.1%}) | "
          f"crashes {len(failures)} | calls {totals['calls']} | tokens {totals['tokens']:,}")


if __name__ == "__main__":
    main()
