"""Requirement-vs-resume matching (M5).

A resume becomes an *evidence pool*: a list of (field-path, text) items built
from the scoring view only — the PII quarantine never enters the pool, so
nothing downstream can match on it even by accident.

A *matcher* answers one narrow question: how well does this requirement text
match this pool, and which pool item is the best evidence? Three families
compete in the M5 bake-off:

- ``LexicalMatcher`` — normalized keyword coverage with a synonyms table
  (k8s -> kubernetes). Transparent, fast, zero dependencies.
- ``EmbeddingMatcher`` — local sentence-transformers cosine similarity
  (MiniLM and bge-small variants). Catches semantics keywords miss.
- ``HybridMatcher`` — max of a lexical and an embedding matcher: exact hits
  stay exact, semantic recall fills the gaps.

Embedding models are lazy-loaded and encodings memoized per text, so pool
items are encoded once per resume regardless of requirement count.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from resume_analyzer.models import ResumeProfile

# --------------------------------------------------------------------------- evidence pool


@dataclass(frozen=True)
class PoolItem:
    field: str  # e.g. "experience[0].bullets[2]" — the Evidence.field locator
    text: str


def build_pool(profile: ResumeProfile) -> list[PoolItem]:
    """Flatten a profile into evidence items. PII is excluded by construction."""
    items: list[PoolItem] = []
    if profile.headline:
        items.append(PoolItem("headline", profile.headline))
    if profile.summary:
        items.append(PoolItem("summary", profile.summary))
    for gi, group in enumerate(profile.skills):
        label = f"{group.category}: " if group.category else ""
        if group.items:
            items.append(PoolItem(f"skills[{gi}]", label + ", ".join(group.items)))
    for ri, role in enumerate(profile.experience):
        items.append(PoolItem(f"experience[{ri}]", f"{role.title} — {role.company}"))
        for bi, bullet in enumerate(role.bullets):
            items.append(PoolItem(f"experience[{ri}].bullets[{bi}]", bullet))
    for ei, edu in enumerate(profile.education):
        text = edu.degree + (f", {edu.institution}" if edu.institution else "")
        items.append(PoolItem(f"education[{ei}]", text))
    for ci, cert in enumerate(profile.certifications):
        items.append(PoolItem(f"certifications[{ci}]", cert))
    for pi, pub in enumerate(profile.publications):
        items.append(PoolItem(f"publications[{pi}]", pub))
    if profile.languages_known:
        items.append(PoolItem("languages_known", ", ".join(profile.languages_known)))
    return items


# --------------------------------------------------------------------------- normalization

# Token-level synonym folding, applied to requirement and resume alike.
SYNONYMS = {
    "k8s": "kubernetes",
    "eks": "kubernetes",
    "gke": "kubernetes",
    "aks": "kubernetes",
    "golang": "go",
    "postgres": "postgresql",
    "js": "javascript",
    "ts": "typescript",
    "tf": "terraform",
    "gha": "github-actions",
    "ci/cd": "cicd",
    "ci": "cicd",
    "cd": "cicd",
    "expected-shortfall": "es",
    "value-at-risk": "var",
}

# Words that carry no matching signal in requirement or resume text.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "e.g", "eg", "etc", "for",
    "from", "have", "in", "is", "it", "its", "least", "of", "on", "one", "or",
    "our", "such", "that", "the", "their", "this", "to", "we", "with", "you",
    "your", "years", "year", "experience", "experienced", "professional",
    "strong", "solid", "deep", "hands-on", "working", "knowledge", "fluent",
    "demonstrated", "demonstrable", "ability", "track", "record", "similar",
    "major", "prefer", "preferred", "plus", "test", "run",
}

_TOKEN_RE = re.compile(r"[a-z0-9+#][a-z0-9+#./-]*")


def normalize_tokens(text: str) -> set[str]:
    """Lowercased content tokens with synonyms folded and stopwords dropped."""
    tokens: set[str] = set()
    for raw in _TOKEN_RE.findall(text.lower()):
        token = SYNONYMS.get(raw, raw)
        if token in STOPWORDS or len(token) < 2:
            continue
        tokens.add(token)
    return tokens


# --------------------------------------------------------------------------- matchers


@dataclass(frozen=True)
class MatchResult:
    score: float  # 0..1
    item: PoolItem | None


class Matcher(Protocol):
    name: str

    def best_match(self, requirement_text: str, pool: list[PoolItem]) -> MatchResult: ...


class LexicalMatcher:
    """Coverage of the requirement's content tokens across the whole pool."""

    name = "lexical"

    def best_match(self, requirement_text: str, pool: list[PoolItem]) -> MatchResult:
        req_tokens = normalize_tokens(requirement_text)
        if not req_tokens or not pool:
            return MatchResult(0.0, None)
        pool_tokens = [(item, normalize_tokens(item.text)) for item in pool]
        all_tokens: set[str] = set().union(*(t for _, t in pool_tokens))
        covered = req_tokens & all_tokens
        score = len(covered) / len(req_tokens)
        best_item = max(pool_tokens, key=lambda p: len(req_tokens & p[1]))[0] if covered else None
        return MatchResult(score, best_item)


class EmbeddingMatcher:
    """Max cosine similarity between requirement and pool items, calibrated to 0..1.

    Raw cosine bands are model-specific (bge famously compresses all pairs into
    a narrow high band), so each model carries its own [floor, ceiling],
    **measured on this corpus** (2026-08-31): floor = the mean best-match
    cosine of requirements against clearly-unrelated resumes, ceiling ≈ the
    mean against their genuinely-matching strong resumes. Measurement method
    and numbers are in the M5 bake-off report.
    """

    def __init__(self, model_name: str, display_name: str, floor: float, ceiling: float):
        self.model_name = model_name
        self.name = display_name
        self.floor, self.ceiling = floor, ceiling
        self._model = None
        self._vectors: dict[str, object] = {}

    def _encode(self, texts: list[str]):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        missing = [t for t in texts if t not in self._vectors]
        if missing:
            encoded = self._model.encode(missing, normalize_embeddings=True)
            for text, vector in zip(missing, encoded, strict=True):
                self._vectors[text] = vector
        return [self._vectors[t] for t in texts]

    def best_match(self, requirement_text: str, pool: list[PoolItem]) -> MatchResult:
        if not pool:
            return MatchResult(0.0, None)
        req_vec = self._encode([requirement_text])[0]
        pool_vecs = self._encode([item.text for item in pool])
        sims = [float(req_vec @ vec) for vec in pool_vecs]
        best_i = max(range(len(sims)), key=sims.__getitem__)
        scaled = (sims[best_i] - self.floor) / (self.ceiling - self.floor)
        score = max(0.0, min(1.0, scaled))
        return MatchResult(score, pool[best_i] if score > 0 else None)


class HybridMatcher:
    """max(lexical, embedding): exact hits stay exact, semantics fill the gaps."""

    def __init__(self, embedding: EmbeddingMatcher):
        self._lexical = LexicalMatcher()
        self._embedding = embedding
        self.name = f"hybrid(lexical+{embedding.name})"

    def best_match(self, requirement_text: str, pool: list[PoolItem]) -> MatchResult:
        lex = self._lexical.best_match(requirement_text, pool)
        emb = self._embedding.best_match(requirement_text, pool)
        return lex if lex.score >= emb.score else emb


def _minilm() -> EmbeddingMatcher:
    # Bands measured on this corpus: unrelated best-match mean 0.29 (p90 0.40),
    # related mean 0.53 — see the M5 bake-off report.
    return EmbeddingMatcher(
        "sentence-transformers/all-MiniLM-L6-v2", "minilm", floor=0.30, ceiling=0.65
    )


def _bge() -> EmbeddingMatcher:
    # bge compresses cosines into a narrow high band: unrelated mean 0.63,
    # related mean 0.76 on this corpus.
    return EmbeddingMatcher("BAAI/bge-small-en-v1.5", "bge", floor=0.63, ceiling=0.80)


def make_matcher(name: str) -> Matcher:
    """Registry used by the eval runner and the bake-off."""
    if name == "lexical":
        return LexicalMatcher()
    if name == "minilm":
        return _minilm()
    if name == "bge":
        return _bge()
    if name == "hybrid-minilm":
        return HybridMatcher(_minilm())
    if name == "hybrid-bge":
        return HybridMatcher(_bge())
    raise ValueError(f"unknown matcher {name!r}")
