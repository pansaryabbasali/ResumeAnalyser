"""Score all 40 applications and grade ranking agreement (M5).

The gate: within each requisition, every recruiter-advanced application must
outscore every rejected one — >=90% of the 18 such pairs. The 15
hold_second_review applications are scored (M6 needs them) but take no part in
the gate.

No LLM calls: matching runs on local models (or pure lexical) over the
committed M3/M4 extraction outputs.

Usage:
  python eval/run_scoring.py --matcher all                # bake-off comparison
  python eval/run_scoring.py --matcher hybrid-bge --save  # winner: save analyses for M6
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import time

import harness

from resume_analyzer.matching import make_matcher
from resume_analyzer.models import Analysis, JobSpec, ResumeProfile
from resume_analyzer.scoring import analyze

PROFILES_JSON = harness.EVAL_DIR / "outputs" / "profiles_single_pass_all.json"
JOBSPECS_JSON = harness.EVAL_DIR / "outputs" / "jobspecs.json"
MATCHERS = ["lexical", "minilm", "bge", "hybrid-minilm", "hybrid-bge"]


def load_inputs():
    profiles = {
        file: ResumeProfile(**data)
        for file, data in json.loads(PROFILES_JSON.read_text(encoding="utf-8")).items()
    }
    specs = {
        rid: JobSpec(**data)
        for rid, data in json.loads(JOBSPECS_JSON.read_text(encoding="utf-8")).items()
    }
    return profiles, specs, harness.load_labels()


def run_matcher(name: str, profiles, specs, records):
    matcher = make_matcher(name)
    started = time.perf_counter()
    analyses: dict[str, Analysis] = {}
    for record in records:
        analyses[record.application_id] = analyze(
            profiles[record.resume_file], specs[record.req_id], matcher,
            application_id=record.application_id,
        )
    elapsed = time.perf_counter() - started
    scores = {app_id: a.overall_score for app_id, a in analyses.items()}
    ordering = harness.pairwise_ordering(records, scores)

    by_outcome = {"advanced": [], "hold_second_review": [], "rejected": []}
    for record in records:
        by_outcome[record.outcome].append(scores[record.application_id])
    margins = []
    for record_a in records:
        if record_a.outcome != "advanced":
            continue
        for record_r in records:
            if record_r.outcome == "rejected" and record_r.req_id == record_a.req_id:
                margins.append(scores[record_a.application_id] - scores[record_r.application_id])
    failed_pairs = [
        (a.application_id, a.candidate_name, r.application_id, r.candidate_name, a.req_id)
        for a in records if a.outcome == "advanced"
        for r in records
        if r.outcome == "rejected" and r.req_id == a.req_id
        and scores[a.application_id] <= scores[r.application_id]
    ]
    return {
        "matcher": name,
        "analyses": analyses,
        "ordering": ordering,
        "elapsed": elapsed,
        "means": {k: statistics.mean(v) for k, v in by_outcome.items()},
        "min_margin": min(margins) if margins else 0.0,
        "median_margin": statistics.median(margins) if margins else 0.0,
        "failed_pairs": failed_pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matcher", choices=[*MATCHERS, "all"], required=True)
    parser.add_argument("--save", action="store_true",
                        help="save analyses json (winner run, M6 input)")
    args = parser.parse_args()

    profiles, specs, records = load_inputs()
    names = MATCHERS if args.matcher == "all" else [args.matcher]
    results = []
    for name in names:
        result = run_matcher(name, profiles, specs, records)
        results.append(result)
        o = result["ordering"]
        print(f"{name:>16}: pairs {o.correct}/{o.total} ({o.rate:.0%}) "
              f"min-margin {result['min_margin']:+.1f} "
              f"median-margin {result['median_margin']:+.1f} "
              f"means adv/hold/rej "
              f"{result['means']['advanced']:.0f}/"
              f"{result['means']['hold_second_review']:.0f}/"
              f"{result['means']['rejected']:.0f} "
              f"({result['elapsed']:.1f}s)")

    today = dt.date.today().isoformat()
    if args.matcher == "all":
        lines = [
            "Gate: every recruiter-advanced application outscores every rejected one",
            "within its requisition — 18 pairs, hold_second_review excluded by design.",
            "",
            "| matcher | pairs correct | min margin | median margin | "
            "means adv/hold/rej | runtime |",
            "|---|---|---|---|---|---|",
        ]
        for r in results:
            o = r["ordering"]
            lines.append(
                f"| {r['matcher']} | {o.correct}/{o.total} ({o.rate:.0%}) "
                f"| {r['min_margin']:+.1f} | {r['median_margin']:+.1f} "
                f"| {r['means']['advanced']:.0f} / {r['means']['hold_second_review']:.0f} "
                f"/ {r['means']['rejected']:.0f} | {r['elapsed']:.1f}s |"
            )
        for r in results:
            if r["failed_pairs"]:
                lines += ["", f"## Failed pairs — {r['matcher']}"] + [
                    f"- {req}: {an} ({a}) scored <= {rn} ({b})"
                    for a, an, b, rn, req in r["failed_pairs"]
                ]
        lines += ["", f"_Generated {today} by `python eval/run_scoring.py --matcher all`._"]
        report = harness.write_report(
            harness.REPORTS_DIR / f"{today}_M5_matcher_bakeoff.md",
            "M5 matcher bake-off — ranking agreement", lines,
        )
        print(f"\nreport: {report}")
        return

    result = results[0]
    o = result["ordering"]
    if args.save:
        out = harness.EVAL_DIR / "outputs" / f"analyses_{result['matcher']}.json"
        out.write_text(
            json.dumps(
                {app_id: a.model_dump(mode="json")
                 for app_id, a in sorted(result["analyses"].items())},
                indent=1, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"analyses saved: {out}")
    lines = [
        f"- matcher: **{result['matcher']}**",
        f"- pairwise ordering: **{o.correct}/{o.total} ({o.rate:.0%})** — gate: >=90%",
        f"- margins (advanced minus rejected, same req): min {result['min_margin']:+.1f}, "
        f"median {result['median_margin']:+.1f} points",
        f"- score means: advanced {result['means']['advanced']:.1f} · hold "
        f"{result['means']['hold_second_review']:.1f} · rejected "
        f"{result['means']['rejected']:.1f}",
        "- per req: " + ", ".join(f"{req} {c}/{t}"
                                   for req, (c, t) in sorted(o.per_req.items())),
        f"- runtime: {result['elapsed']:.1f}s, zero LLM calls",
    ]
    if result["failed_pairs"]:
        lines += ["", "## Failed pairs"] + [
            f"- {req}: {an} ({a}) scored <= {rn} ({b})"
            for a, an, b, rn, req in result["failed_pairs"]
        ]
    lines += ["", f"_Generated {today} by `python eval/run_scoring.py "
              f"--matcher {result['matcher']}`._"]
    report = harness.write_report(
        harness.REPORTS_DIR / f"{today}_M5_scoring_{result['matcher']}.md",
        f"M5 scoring report — {result['matcher']}", lines,
    )
    print(f"report: {report}")


if __name__ == "__main__":
    main()
