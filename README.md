# Resume Analyzer — Application Screening Support for Hoysala Bank

A decision-support tool for Hoysala Bank's Talent Acquisition team: analyze a
candidate's resume against a specific job description, extract what each actually
says, score the alignment, and explain the score with evidence — so recruiters spend
their time on judgment calls instead of keyword hunting.

*Sections 1–4 define the engagement and the data. The system itself is designed and
built on top of this repository; every design decision will be validated against the
benchmark data described in section 4.*

## 1. The client: Hoysala Bank Ltd.

**Hoysala Bank** is an old-generation private-sector bank headquartered in
Bengaluru, founded in 1927.

| | |
|---|---|
| Headcount | ~21,500 employees |
| Scale | ~₹3.6 lakh crore total business, 830+ branches across 14 states |
| Customers | 14M retail and business customers; Hoysala One app with 5.2M MAU |
| Divisions | Retail & Digital Banking, Commercial Banking, Treasury & Markets, Corporate Functions |
| Technology | ~2,400 people at the Hoysala Digital Centre (Bellandur, Bengaluru) and a Chennai hub |
| Transformation | **Project Garuda** (2025–2028): core-banking, payments and data/AI platform modernization |

Project Garuda has turned Hoysala into an aggressive hirer in the most competitive
talent market in the country. In the 2026-Q3 round alone, the bank opened eight
requisitions spanning software engineering, SRE, AI engineering, treasury quant
roles, HR and engineering management — and received over 2,300 applications for
them through Naukri, LinkedIn, referrals and agencies.

## 2. Problem statement

Recruitment at Hoysala is run by a Talent Acquisition team of nine recruiters, each
covering several very different domains. The 2026-Q3 round exposed the limits of the
current screening process:

- **Volume vs. attention.** With 280+ applications per requisition — Naukri alone
  delivers hundreds, many from aspirational applicants far from the requirement —
  recruiters average under two minutes per CV at first screen. Strong candidates
  with unconventional profiles (career switchers, research backgrounds, adjacent
  stacks) are the most likely casualties of a fast skim.
- **Domain stretch.** The recruiter screening a POSH-savvy HRBP in the morning
  screens a C++ quant developer in the afternoon. Nuances — FRTB parallel-run vs.
  IRDAI capital modeling, Kubernetes administration vs. production SRE practice —
  get lost, and hiring managers receive shortlists they then partially re-screen
  themselves.
- **Inconsistency.** The same profile can land in "advance" with one recruiter and
  "reject" with another. There is no shared, explainable standard for what "meets
  the must-haves" means.
- **Format chaos.** Resumes arrive as everything from crisp two-pagers to
  Naukri-template exports with declaration blocks, tables of percentages since
  class 10, and four different notions of what a "notice period" line looks like.
- **Fairness and compliance.** Screening support must be transparent about *why*
  it scored a candidate the way it did, must never use name, gender, age or other
  protected attributes as signal, must handle applicant personal data in line with
  the DPDP Act, and must keep a human decision-maker in the loop — consistent with
  the spirit of RBI's FREE-AI recommendations on responsible AI in finance. It must
  never silently auto-reject.

## 3. Project scope

**Goal:** a screening-support tool that, given one resume (PDF, as submitted by
candidates through the careers portal) and one job description (as published from
the ATS), produces a structured, evidence-backed analysis:

1. **Structured extraction** of the resume (contact, roles, dates, skills,
   education, certifications, notice period) and of the JD (must-have vs.
   nice-to-have requirements, experience expectations, domain context).
2. **Alignment scoring** between the two — skills coverage, experience depth and
   seniority fit, domain relevance — with every score traceable to specific
   passages, never a bare number.
3. **A recruiter-facing report** per application: strengths, gaps, red flags to
   verify in a screen call, and concrete follow-up questions.
4. **Ranking support** across all applicants for one requisition, so a recruiter
   can triage the pile in evidence order rather than submission order.

**Explicitly out of scope:** automated rejection or advancement. The tool prepares
the decision; the recruiter makes it. This boundary is a governance requirement, not
a temporary limitation.

**Acceptance benchmark:** the 2026-Q3 sample in this repository ships with the
recruiters' actual screening outcomes (see `applications_log.csv`). The tool's
assessments will be measured against those outcomes — including the deliberately
hard middle of the distribution, the "hold for second review" pile, where a
screening tool earns or loses its keep.

## 4. The dataset

Talent Acquisition has provided a working sample from the 2026-Q3 hiring round: all
eight job descriptions, and for each requisition five representative applications
selected across the outcome spectrum (advanced, on hold, rejected), together with
the recruiter's screening decision and notes for every application.

```
dataset/
├── job_descriptions/        # 8 requisitions, as published from the ATS (markdown)
├── resumes/                 # 40 applications, one folder per requisition
│   └── HOY-2026-0XX/        #   candidate PDFs exactly as submitted
└── applications_log.csv     # ATS export: one row per application
```

### Requisitions (2026-Q3 round)

| Req ID | Role | Division | Location |
|---|---|---|---|
| HOY-2026-011 | Senior Backend Engineer — Payments Platform | Technology — Payments & Cards | Bengaluru |
| HOY-2026-014 | Site Reliability Engineer | Technology — Infrastructure & Platform | Bengaluru / Chennai |
| HOY-2026-017 | AI Engineer — GenAI Center of Excellence | Technology — Data & AI | Bengaluru |
| HOY-2026-019 | Quantitative Researcher — Market Risk Models | Risk Management | Bengaluru |
| HOY-2026-021 | Quantitative Developer — Treasury & Markets | Treasury & Markets | Bengaluru |
| HOY-2026-023 | HR Business Partner — Technology | Human Resources | Bengaluru |
| HOY-2026-025 | Engineering Manager — Core Banking Modernization | Technology — Core Banking | Bengaluru |
| HOY-2026-027 | Product Manager — Mobile Banking | Retail & Digital Banking | Bengaluru |

### `applications_log.csv` schema

| Column | Meaning |
|---|---|
| `application_id` | ATS application number (`APP-26-XXXXX`) |
| `req_id` | Requisition the candidate applied to |
| `role_title` | Requisition title at time of application |
| `candidate_name`, `email`, `phone`, `city` | Contact details as entered by the candidate |
| `source` | Channel: Naukri, LinkedIn, careers site, Instahyre, IIMJobs, referral, or agency |
| `applied_date` | Submission date |
| `resume_file` | Path to the submitted PDF, relative to `dataset/` |
| `recruiter_screen_outcome` | `advanced` (9), `hold_second_review` (15), `rejected` (16) |
| `recruiter_notes` | The recruiter's free-text screening note |

Two properties of this sample matter for anyone building on it:

- **The resumes are as heterogeneous as the process that produced them** —
  candidates submit whatever their CV looks like. Layouts range from single-column
  classic to accent-colored modern to dense academic CVs with publication lists;
  conventions range from crisp product-company two-pagers to traditional formats
  with personal-details blocks and declaration lines; quality ranges from
  meticulously quantified to keyword-stuffed to typo-ridden.
- **The middle is the point.** Nine applications are clear advances and sixteen are
  clear rejections — but fifteen sit in `hold_second_review`: career switchers,
  physicists without finance, staff engineers without formal reports, founders of
  shut-down startups, actuaries eyeing the trading book. A screening tool that only
  reproduces the easy calls adds nothing; the benchmark deliberately over-weights
  the hard ones.

## 5. Status

- [x] Engagement scoped; 2026-Q3 sample dataset received and versioned (this repo)
- [ ] Data validation & benchmark definition
- [ ] System design
- [ ] Implementation
