# Quantitative Developer — Treasury & Markets Technology

| | |
|---|---|
| **Requisition** | HOY-2026-021 |
| **Division** | Treasury & Markets — Markets Technology |
| **Location** | Bengaluru (Hoysala Digital Centre, Bellandur) — hybrid, min. 4 days on-site |
| **Employment type** | Full-time, permanent |
| **CTC range** | ₹40 – 65 LPA base; discretionary performance bonus |
| **Posted** | 2026-07-17 |
| **Closes** | 2026-08-20 |
| **Hiring manager** | Ananya Bhat, Head of Markets Technology |

## About Hoysala Bank

Hoysala Bank Ltd. is an old-generation private-sector bank headquartered in
Bengaluru, founded in 1927. The bank serves 14 million customers through 830+
branches across 14 states, with total business of about ₹3.6 lakh crore and some
21,500 employees. Our Treasury & Markets division runs trading books in government
securities, interest-rate derivatives and FX from the Mumbai dealing room, with the
quant and technology teams based in Bengaluru.

## The role

Markets Technology (26 engineers) builds and runs "Rampart", Hoysala's in-house
pricing and risk library, and the intraday risk services around it. Rampart is a
C++ core with Python bindings, used by the desk for pricing and by Risk for
end-of-day and intraday calculations across G-Sec, SDL, T-Bill, OIS/IRS, FX forward
and FX option books, consuming CCIL and dealing-platform feeds. As a Quantitative
Developer you sit between the quants and the desk: you turn models into fast,
correct, well-tested production code.

## What you'll do

- Extend Rampart's C++ core: G-Sec and OIS curve construction, instrument pricing,
  sensitivities (algorithmic differentiation), scenario engines.
- Maintain and improve the pybind11-based Python API that quants and risk managers
  script against.
- Profile and optimize hot paths — intraday risk runs must complete within strict
  time budgets on a fixed compute envelope.
- Harden numerical code: unit and regression test suites, reproducible builds,
  golden-number testing against model specifications and FIMMDA valuation checks.
- Work daily with dealers, market-risk quants and the ALM desk on priorities.
- Improve the platform: CMake build, CI pipelines, Linux runtime environment.

## What you bring (must-haves)

- 4+ years of professional C++ development (C++17 or later) on Linux in
  performance-sensitive systems.
- Strong Python and experience exposing C++ to Python (pybind11, Cython or similar).
- Solid numerical programming fundamentals: floating-point behavior, stability,
  vectorization, profiling.
- Rigorous testing habits for numerical code.
- Fluent professional English and the communication skills to work directly with
  trading and risk stakeholders.

## Nice to have

- Knowledge of fixed-income mathematics: discounting, yield curves, swaps, FX
  forwards, vanilla options and Greeks; familiarity with Indian market conventions
  (G-Sec day counts, FBIL benchmarks, CCIL settlement).
- Experience with QuantLib or an in-house pricing library at a bank, primary
  dealer, prop-trading firm or exchange-adjacent shop.
- Algorithmic differentiation (AAD) experience.
- Low-latency or HPC background (SIMD, cache-aware data structures, multithreading).

## What we offer

- Competitive base within the stated range, discretionary bonus linked to desk and
  personal performance.
- Group medical cover for family including parents; term and accident insurance.
- ₹1.2 lakh annual learning budget; CQF sponsorship for the right candidate.
- A codebase where correctness and speed both matter, and where your users are one
  video call (or one flight to Mumbai) away.

## Application process

Apply via the Hoysala Careers portal with an English-language CV in PDF.
Process: recruiter screen → C++/Python technical interview → take-home numerical
exercise (~3 hours) discussed in a follow-up session → hiring-manager and desk
conversation → offer.

*Hoysala Bank is an equal-opportunity employer. We welcome applications from all
backgrounds and are happy to discuss accommodations at any stage.*
