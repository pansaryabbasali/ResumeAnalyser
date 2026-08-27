"""Prompts for structured resume extraction (M3).

The JSON schema below is the prompt-side mirror of ``ResumeProfile`` — if
models.py changes, this text must change with it (guarded by tests that round
trip a fake response through validation).
"""

PROFILE_SCHEMA = """\
{
  "contact": {"name": str, "email": str|null, "phone": str|null, "city": str|null},
  "headline": str|null,
  "summary": str|null,
  "skills": [{"category": str|null, "items": [str]}],
  "experience": [{"title": str, "company": str, "location": str|null,
                  "start": "YYYY-MM"|null, "end": "YYYY-MM"|null, "bullets": [str]}],
  "education": [{"degree": str, "institution": str|null, "years": str|null, "grade": str|null}],
  "certifications": [str],
  "publications": [str],
  "languages_known": [str],
  "links": [str],
  "notice_period": str|null,
  "expected_ctc": str|null,
  "pii": {"date_of_birth": str|null, "gender": str|null, "marital_status": str|null,
          "photo_present": bool, "other": [str]}
}"""

RULES = """\
Rules — follow every one:
- Output ONLY the JSON object. No markdown fences, no commentary.
- Copy values verbatim from the resume. NEVER invent, infer or embellish a value
  that is not printed. A missing value is null; a missing list is [].
- Normalize every experience date to "YYYY-MM" (e.g. "Mar 2021" -> "2021-03").
  If a role is current ("present"), set "end": null. Education "years" stays as written.
- "headline" is the role/title line printed under the candidate's name, if any.
- Keep a grade such as "(CGPA 8.2/10)" inside "degree" as written AND copy the
  grade part into "grade".
- Notice period lines ("Notice period: 60 days", "immediate joiner") go into
  "notice_period"; expected salary/CTC lines go into "expected_ctc".
- Date of birth, gender, marital status go ONLY into "pii". A declaration
  statement ("I hereby declare...") goes into "pii"."other" verbatim.
- "languages_known" lists spoken-language entries as written (e.g. "Kannada (native)").
- "links" collects URLs (LinkedIn, GitHub, portfolio)."""

SYSTEM = (
    "You are a precise resume-parsing engine. You convert raw resume text into "
    "structured JSON exactly matching a given schema, copying values verbatim and "
    "never inventing information. You output only JSON."
)


def single_pass_prompt(resume_text: str) -> str:
    return (
        f"Convert this resume into JSON matching exactly this schema:\n\n{PROFILE_SCHEMA}\n\n"
        f"{RULES}\n\nRESUME TEXT:\n---\n{resume_text}\n---"
    )


def section_prompt(part_name: str, part_schema: str, section_text: str) -> str:
    return (
        f"From this part of a resume, extract JSON matching exactly this schema:\n\n"
        f"{part_schema}\n\n{RULES}\n\nRESUME {part_name.upper()} TEXT:\n---\n{section_text}\n---"
    )


def repair_prompt(previous_output: str, errors: str) -> str:
    return (
        "Your previous JSON output failed validation.\n\n"
        f"VALIDATION ERRORS:\n{errors}\n\n"
        f"PREVIOUS OUTPUT:\n{previous_output}\n\n"
        "Return the corrected, complete JSON object only. Fix every listed error, "
        "change nothing else, and follow the original schema and rules exactly."
    )


IDENTITY_SCHEMA = """\
{
  "contact": {"name": str, "email": str|null, "phone": str|null, "city": str|null},
  "headline": str|null,
  "summary": str|null,
  "languages_known": [str],
  "links": [str],
  "notice_period": str|null,
  "expected_ctc": str|null,
  "pii": {"date_of_birth": str|null, "gender": str|null, "marital_status": str|null,
          "photo_present": bool, "other": [str]}
}"""

EXPERIENCE_SCHEMA = """\
{
  "experience": [{"title": str, "company": str, "location": str|null,
                  "start": "YYYY-MM"|null, "end": "YYYY-MM"|null, "bullets": [str]}]
}"""

CREDENTIALS_SCHEMA = """\
{
  "skills": [{"category": str|null, "items": [str]}],
  "education": [{"degree": str, "institution": str|null, "years": str|null, "grade": str|null}],
  "certifications": [str],
  "publications": [str]
}"""
