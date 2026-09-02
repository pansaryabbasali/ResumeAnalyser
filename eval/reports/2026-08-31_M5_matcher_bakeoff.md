# M5 matcher bake-off — ranking agreement

Gate: every recruiter-advanced application outscores every rejected one
within its requisition — 18 pairs, hold_second_review excluded by design.

| matcher | pairs correct | min margin | median margin | means adv/hold/rej | runtime |
|---|---|---|---|---|---|
| lexical | 18/18 (100%) | +15.2 | +26.2 | 38 / 23 / 12 | 0.0s |
| minilm | 18/18 (100%) | +20.4 | +36.6 | 61 / 42 / 25 | 13.6s |
| bge | 18/18 (100%) | +17.8 | +35.8 | 65 / 49 / 29 | 7.3s |
| hybrid-minilm | 18/18 (100%) | +16.5 | +39.2 | 65 / 43 / 27 | 6.5s |
| hybrid-bge | 18/18 (100%) | +23.9 | +34.9 | 68 / 51 / 30 | 7.4s |

_Generated 2026-08-31 by `python eval/run_scoring.py --matcher all`._
