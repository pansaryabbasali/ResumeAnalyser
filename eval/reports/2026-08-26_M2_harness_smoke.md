# M2 harness smoke report

**SMOKE RUN ON STUB OUTPUTS — every number below is meaningless by design.**
This report only proves the harness plumbing works end-to-end before M3.

## Benchmark labels
- applications loaded: 40
- outcomes: 9 advanced / 15 hold_second_review / 16 rejected

## Extraction answer key
- facts: 38 across 15 resumes
- stub pass rate: 1/38 (3%) — stub profiles only carry the candidate name

## Pairwise ordering metric (M5 gate, easy classes only)
- comparable advanced-vs-rejected pairs: 18
- stub ordering rate: 12/18 (67%) — scores are name lengths, as intended
- per requisition: HOY-2026-011 2/2, HOY-2026-014 3/4, HOY-2026-017 2/2, HOY-2026-019 2/2, HOY-2026-021 0/2, HOY-2026-023 1/2, HOY-2026-025 1/2, HOY-2026-027 1/2

_Generated 2026-08-26 by `python eval/run_eval.py --stub`._
