"""Extraction machinery, fully offline: sectionizer, JSON tolerance, cache, strategies."""

import json
from types import SimpleNamespace

import pytest

from resume_analyzer.extract import (
    LLMOutputError,
    ResponseCache,
    ResumeExtractor,
    split_sections,
)
from resume_analyzer.extract.resume import parse_json_response

SAMPLE_TEXT = """Asha Rao
Backend Engineer
Bengaluru | +91 90000 00000 | asha@example.com

SUMMARY
Engineer with 5 years of experience.

EXPERIENCE
Backend Engineer — Acme Pay, Bengaluru Mar 2021 - present
- Built payment services.

EDUCATION
B.E. Computer Science - Good College (VTU), 2012 - 2016

Certifications
- AWS Solutions Architect (2023)

Personal details
DOB: 01-01-1994 | Languages known: Kannada, English

Declaration
I hereby declare the above is true. - Asha Rao
"""

VALID_PROFILE_JSON = json.dumps(
    {
        "contact": {"name": "Asha Rao", "email": "asha@example.com",
                    "phone": "+91 90000 00000", "city": "Bengaluru"},
        "headline": "Backend Engineer",
        "summary": "Engineer with 5 years of experience.",
        "skills": [],
        "experience": [{"title": "Backend Engineer", "company": "Acme Pay",
                        "location": "Bengaluru", "start": "2021-03", "end": None,
                        "bullets": ["Built payment services."]}],
        "education": [{"degree": "B.E. Computer Science", "institution": "Good College (VTU)",
                       "years": "2012 - 2016", "grade": None}],
        "certifications": ["AWS Solutions Architect (2023)"],
        "publications": [],
        "languages_known": ["Kannada", "English"],
        "links": [],
        "notice_period": None,
        "expected_ctc": None,
        "pii": {"date_of_birth": "01-01-1994", "gender": None, "marital_status": None,
                "photo_present": False,
                "other": ["I hereby declare the above is true. - Asha Rao"]},
    }
)


class FakeGateway:
    """Returns queued responses in order; records every prompt it was asked."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def ask(self, prompt: str, *, system: str | None = None, **params):
        self.prompts.append(prompt)
        return SimpleNamespace(
            text=self.responses.pop(0),
            provider="fake",
            model="fake-1",
            usage=SimpleNamespace(total_tokens=100),
        )


@pytest.fixture
def cache(tmp_path):
    with ResponseCache(tmp_path / "cache.sqlite") as c:
        yield c


# --------------------------------------------------------------------------- sectionizer


def test_split_sections_buckets_headers_correctly() -> None:
    parts = split_sections(SAMPLE_TEXT)
    assert "Asha Rao" in parts["identity"]  # preamble
    assert "DOB: 01-01-1994" in parts["identity"]  # personal details
    assert "I hereby declare" in parts["identity"]  # declaration
    assert "Acme Pay" in parts["experience"]
    assert "Good College" in parts["credentials"]
    assert "AWS Solutions Architect" in parts["credentials"]  # mixed-case header


def test_split_sections_no_headers_is_all_identity() -> None:
    parts = split_sections("Just a name\nand one line about them")
    assert parts["experience"] == "" and parts["credentials"] == ""
    assert "Just a name" in parts["identity"]


# --------------------------------------------------------------------------- JSON parsing


def test_parse_json_tolerates_fences_and_prose() -> None:
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_response('Here is the JSON:\n{"a": 1}\nHope that helps!') == {"a": 1}


def test_parse_json_rejects_garbage() -> None:
    with pytest.raises(LLMOutputError):
        parse_json_response("I cannot parse this resume.")
    with pytest.raises(LLMOutputError):
        parse_json_response('{"unterminated": ')
    with pytest.raises(LLMOutputError):
        parse_json_response("[1, 2, 3]")


# --------------------------------------------------------------------------- cache


def test_cache_roundtrip_and_key_sensitivity(cache) -> None:
    key = ResponseCache.make_key("t", "sys", "prompt", {"temperature": 0.0})
    assert cache.get(key) is None
    from resume_analyzer.extract import CachedResponse

    cache.put(key, "t", CachedResponse("out", "groq", "llama", 42))
    hit = cache.get(key)
    assert hit is not None and hit.text == "out" and hit.total_tokens == 42
    # Any ingredient change produces a different key.
    assert key != ResponseCache.make_key("t", "sys", "prompt!", {"temperature": 0.0})
    assert key != ResponseCache.make_key("t", "sys", "prompt", {"temperature": 0.7})


def test_second_extraction_is_served_from_cache(cache) -> None:
    gateway = FakeGateway([VALID_PROFILE_JSON])
    extractor = ResumeExtractor(gateway, cache)
    first = extractor.extract(SAMPLE_TEXT, "resumes/x.pdf")
    assert (first.calls, first.cache_hits) == (1, 0)
    again = ResumeExtractor(FakeGateway([]), cache).extract(SAMPLE_TEXT, "resumes/x.pdf")
    assert (again.calls, again.cache_hits) == (0, 1)  # gateway had no responses to give
    assert again.profile.contact.name == "Asha Rao"


# --------------------------------------------------------------------------- strategies


def test_single_pass_extracts_and_quarantines(cache) -> None:
    extractor = ResumeExtractor(FakeGateway([VALID_PROFILE_JSON]), cache)
    result = extractor.extract(SAMPLE_TEXT, "resumes/x.pdf", strategy="single_pass")
    profile = result.profile
    assert profile.experience[0].start == "2021-03" and profile.experience[0].end is None
    assert profile.pii.date_of_birth == "01-01-1994"
    assert "01-01-1994" not in json.dumps(profile.for_scoring())
    assert result.tokens == 100 and result.repairs == 0


def test_single_pass_repairs_invalid_output_once(cache) -> None:
    bad = json.dumps({"contact": {"email": "x@y.z"}})  # name missing -> validation error
    extractor = ResumeExtractor(FakeGateway([bad, VALID_PROFILE_JSON]), cache)
    result = extractor.extract(SAMPLE_TEXT, "resumes/x.pdf")
    assert result.repairs == 1 and result.calls == 2
    assert result.profile.contact.name == "Asha Rao"


def test_single_pass_gives_up_after_one_repair(cache) -> None:
    extractor = ResumeExtractor(FakeGateway(["junk", "more junk"]), cache)
    with pytest.raises(LLMOutputError, match="after repair"):
        extractor.extract(SAMPLE_TEXT, "resumes/x.pdf")


def test_sectioned_merges_three_fragments(cache) -> None:
    full = json.loads(VALID_PROFILE_JSON)
    identity = {k: full[k] for k in ("contact", "headline", "summary", "languages_known",
                                     "links", "notice_period", "expected_ctc", "pii")}
    experience = {"experience": full["experience"]}
    credentials = {k: full[k] for k in ("skills", "education", "certifications", "publications")}
    gateway = FakeGateway([json.dumps(identity), json.dumps(experience),
                           json.dumps(credentials)])
    result = ResumeExtractor(gateway, cache).extract(
        SAMPLE_TEXT, "resumes/x.pdf", strategy="sectioned"
    )
    assert result.strategy == "sectioned" and result.calls == 3
    assert result.profile.contact.name == "Asha Rao"
    assert result.profile.experience[0].company == "Acme Pay"
    assert result.profile.certifications == ["AWS Solutions Architect (2023)"]
