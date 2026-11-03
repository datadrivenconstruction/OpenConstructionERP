# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure retrieval and citation logic for the project document assistant.

Nothing here touches the database or the network, so every decision that
shapes an answer (how a document is cut into passages, how passages rank,
when retrieval is too weak to answer, which claims survive the citation
check) is deterministic and measured by the evaluation harness in
``evaluation.py``.

Ranking is Okapi BM25 over a language-neutral tokenizer (casefold, accent
fold, light suffix stripping for Latin and Cyrillic scripts). It needs no
model and no extra memory beyond the passages themselves, which keeps the
core inside the 3 GB server budget. Confidence is the IDF-weighted share of
the question's terms that the best passage actually contains, so a high BM25
score on one rare word cannot pass as a confident hit.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

#: Below this confidence the assistant answers "not found in project documents".
DEFAULT_CONFIDENCE_THRESHOLD = 0.6
#: Words per passage window and overlap between consecutive windows.
WINDOW_WORDS = 140
WINDOW_OVERLAP = 30
#: A claim must share at least this share of its content words with a cited passage.
GROUNDING_MIN_OVERLAP = 0.35
#: A verbatim quote attached to a claim must be this fully present in the cited passage.
QUOTE_MIN_OVERLAP = 0.8

PAGE_BREAK = "\f"

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "shall",
        "should",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "within",
        "must",
        "may",
        "per",
        "any",
        "all",
        "der",
        "die",
        "das",
        "und",
        "ist",
        "im",
        "in",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einer",
        "zu",
        "mit",
        "von",
        "für",
        "fur",
        "auf",
        "wie",
        "was",
        "wo",
        "welche",
        "welcher",
        "nicht",
        "oder",
        "bei",
        "sind",
        "wird",
        "werden",
        "muss",
        "le",
        "la",
        "les",
        "des",
        "un",
        "une",
        "et",
        "est",
        "du",
        "de",
        "en",
        "pour",
        "que",
        "qui",
        "dans",
        "sur",
        "au",
        "aux",
        "el",
        "los",
        "las",
        "del",
        "y",
        "es",
        "por",
        "para",
        "con",
        "que",
        "una",
        "и",
        "в",
        "во",
        "на",
        "не",
        "что",
        "как",
        "где",
        "какой",
        "какая",
        "какие",
        "по",
        "с",
        "со",
        "к",
        "ко",
        "из",
        "для",
        "это",
        "ли",
        "или",
        "о",
        "об",
        "от",
        "до",
        "при",
        "а",
    ]
)

_LATIN_SUFFIXES = (
    "ations",
    "ation",
    "ments",
    "ment",
    "ings",
    "ing",
    "ungen",
    "ung",
    "ies",
    "es",
    "ed",
    "en",
    "er",
    "s",
)
_CYRILLIC_SUFFIXES = (
    "ами",
    "ями",
    "ого",
    "его",
    "ому",
    "ему",
    "ых",
    "их",
    "ой",
    "ий",
    "ый",
    "ая",
    "яя",
    "ое",
    "ее",
    "ые",
    "ие",
    "ов",
    "ей",
    "ев",
    "ах",
    "ях",
    "ам",
    "ям",
    "ом",
    "ем",
    "ию",
    "ия",
    "а",
    "я",
    "ы",
    "и",
    "е",
    "у",
    "ю",
    "о",
)
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# A heading line: "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE", "3.2.1 Concrete cover", "Clause 14 Payment".
_HEADING_RE = re.compile(
    r"^\s*(?:(?:section|clause|article|abschnitt|раздел|статья|пункт)\s+)?"
    r"((?:\d{2}\s\d{2}\s\d{2})|(?:\d{1,3}(?:\.\d{1,3}){0,4}))\.?\s+([^\n]{2,90})$",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Tokens are accent-folded before stemming (й -> и), so the suffixes must be folded the same way.
_CYRILLIC_SUFFIXES = tuple(dict.fromkeys(_fold(s) for s in _CYRILLIC_SUFFIXES))


def _stem(token: str) -> str:
    if token.isdigit() or len(token) <= 4:
        return token
    suffixes = _CYRILLIC_SUFFIXES if _CYRILLIC_RE.search(token) else _LATIN_SUFFIXES
    for suffix in suffixes:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    """Language-neutral search tokens for *text* (stopwords removed, light stemming)."""
    out: list[str] = []
    for raw in _TOKEN_RE.findall(_fold(text or "")):
        if raw in _STOPWORDS or (len(raw) < 2 and not raw.isdigit()):
            continue
        out.append(_stem(raw))
    return out


@dataclass
class Passage:
    """One retrievable unit of project text with everything a citation needs."""

    passage_id: str
    source_kind: str  # specification | drawing | contract | document | rfi | submittal | correspondence | minutes
    source_id: str
    title: str
    text: str
    document_id: str | None = None
    revision: str | None = None
    page: int | None = None
    sheet_number: str | None = None
    section: str | None = None
    is_current: bool = True
    deep_link: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def citation(self, ref: int, score: float) -> dict[str, Any]:
        """The citation payload the API returns for this passage."""
        return {
            "ref": ref,
            "passage_id": self.passage_id,
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "document_id": self.document_id,
            "title": self.title,
            "revision": self.revision,
            "page": self.page,
            "sheet_number": self.sheet_number,
            "section": self.section,
            "snippet": self.text[:400],
            "deep_link": self.deep_link,
            "score": round(score, 4),
        }


def split_sections(page_text: str) -> list[tuple[str | None, str]]:
    """Cut one page into ``(section label, body)`` runs at heading lines."""
    runs: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in page_text.splitlines():
        match = _HEADING_RE.match(line)
        if match and len(line.split()) <= 14:
            runs.append((f"{match.group(1)} {match.group(2).strip()}".strip(), [line]))
        else:
            runs[-1][1].append(line)
    return [(label, "\n".join(lines).strip()) for label, lines in runs if "\n".join(lines).strip()]


def _windows(text: str) -> list[str]:
    words = text.split()
    if len(words) <= WINDOW_WORDS:
        return [text] if words else []
    step = WINDOW_WORDS - WINDOW_OVERLAP
    return [" ".join(words[i : i + WINDOW_WORDS]) for i in range(0, max(len(words) - WINDOW_OVERLAP, 1), step)]


def chunk_document(
    *,
    source_kind: str,
    source_id: str,
    title: str,
    content_text: str,
    document_id: str | None = None,
    revision: str | None = None,
    is_current: bool = True,
    sheets_by_page: dict[int, dict[str, Any]] | None = None,
    link_for_page: Any = None,
) -> list[Passage]:
    """Cut an extracted document into page- and section-addressed passages.

    Pages are separated by form feeds (the file-search extractor writes one
    between PDF pages). A section heading carries over a page break, so text
    that continues a clause on the next page is still cited to that clause.
    """
    pages = (content_text or "").split(PAGE_BREAK)
    passages: list[Passage] = []
    current_section: str | None = None
    for page_idx, page_text in enumerate(pages, start=1):
        if not page_text.strip():
            continue
        sheet = (sheets_by_page or {}).get(page_idx) or {}
        for label, body in split_sections(page_text):
            if label:
                current_section = label
            for w_idx, window in enumerate(_windows(body)):
                passages.append(
                    Passage(
                        passage_id=f"{source_id}:p{page_idx}:{len(passages)}:{w_idx}",
                        source_kind="drawing" if sheet else source_kind,
                        source_id=source_id,
                        title=title,
                        text=window,
                        document_id=document_id,
                        revision=sheet.get("revision") or revision,
                        page=page_idx,
                        sheet_number=sheet.get("sheet_number"),
                        section=current_section or sheet.get("sheet_title"),
                        is_current=is_current,
                        deep_link=link_for_page(page_idx) if callable(link_for_page) else "",
                    )
                )
    return passages


def record_passages(
    *,
    source_kind: str,
    source_id: str,
    title: str,
    text: str,
    deep_link: str,
    revision: str | None = None,
    section: str | None = None,
) -> list[Passage]:
    """Passages for a structured record (RFI, submittal, letter, minutes, contract terms)."""
    return [
        Passage(
            passage_id=f"{source_id}:r:{idx}",
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            text=window,
            revision=revision,
            section=section,
            deep_link=deep_link,
        )
        for idx, window in enumerate(_windows(text))
    ]


@dataclass
class Hit:
    """A ranked passage with its BM25 score and query coverage."""

    passage: Passage
    score: float
    coverage: float


class BM25Index:
    """In-memory Okapi BM25 over a project's passages (title counted twice)."""

    def __init__(self, passages: list[Passage], *, k1: float = 1.2, b: float = 0.75) -> None:
        self.passages = passages
        self.k1 = k1
        self.b = b
        self._tf: list[Counter[str]] = []
        df: Counter[str] = Counter()
        for p in passages:
            toks = tokenize(p.text) + tokenize(f"{p.title} {p.section or ''} {p.sheet_number or ''}") * 2
            tf = Counter(toks)
            self._tf.append(tf)
            df.update(tf.keys())
        self._len = [sum(tf.values()) for tf in self._tf]
        self._avg = (sum(self._len) / len(self._len)) if self._len else 0.0
        n = len(passages)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, *, k: int = 8, extra_terms: list[str] | None = None) -> list[Hit]:
        """Top *k* passages for *query*; *extra_terms* (query expansion) count half."""
        terms = list(dict.fromkeys(tokenize(query)))
        extra = [t for t in dict.fromkeys(tokenize(" ".join(extra_terms or []))) if t not in terms]
        if not (terms or extra) or not self.passages:
            return []
        weights = dict.fromkeys(terms, 1.0) | dict.fromkeys(extra, 0.5)
        total_idf = sum(self.idf.get(t, 0.0) * w for t, w in weights.items()) or 1.0
        hits: list[Hit] = []
        for idx, tf in enumerate(self._tf):
            score = 0.0
            covered = 0.0
            norm = self.k1 * (1 - self.b + self.b * self._len[idx] / (self._avg or 1.0))
            for t, w in weights.items():
                f = tf.get(t, 0)
                if not f:
                    continue
                idf = self.idf.get(t, 0.0)
                score += w * idf * f * (self.k1 + 1) / (f + norm)
                covered += w * idf
            if score <= 0:
                continue
            if not self.passages[idx].is_current:
                score *= 0.8
            hits.append(Hit(self.passages[idx], score, min(covered / total_idf, 1.0)))
        hits.sort(key=lambda h: (-h.score, h.passage.passage_id))
        return hits[:k]


def confidence_of(hits: list[Hit]) -> float:
    """Retrieval confidence in [0, 1]: query coverage of the best passage, nudged by agreement."""
    if not hits:
        return 0.0
    top = hits[0].coverage
    support = sum(1 for h in hits[1:3] if h.coverage >= 0.5 * top) * 0.05
    return round(min(top + support, 1.0), 4)


def supports_answer(hit: Hit, top: Hit) -> bool:
    """A lower-ranked passage is cited only when it is nearly as relevant as the best one."""
    return hit is top or (hit.score >= 0.6 * top.score and hit.coverage >= 0.7 * top.coverage)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 12]


def extractive_claims(query: str, hits: list[Hit], *, max_claims: int = 3) -> list[dict[str, Any]]:
    """Answer without a language model: the best-matching sentence of each top passage, cited."""
    q_terms = set(tokenize(query))
    claims: list[dict[str, Any]] = []
    for ref, hit in enumerate(hits[:max_claims], start=1):
        if not supports_answer(hit, hits[0]):
            continue
        best = max(
            _sentences(hit.passage.text) or [hit.passage.text[:300]],
            key=lambda s: (len(q_terms & set(tokenize(s))), -len(s)),
        )
        if not q_terms & set(tokenize(best)):
            continue
        claims.append({"text": best, "citations": [ref], "quoted": True})
    return claims


def grounded(claim_text: str, passage_texts: list[str], *, min_overlap: float = GROUNDING_MIN_OVERLAP) -> bool:
    """True when a claim's content words are mostly found in the passages it cites."""
    words = set(tokenize(claim_text))
    if not words:
        return False
    pool: set[str] = set()
    for text in passage_texts:
        pool |= set(tokenize(text))
    return len(words & pool) / len(words) >= min_overlap


def verify_claims(raw_claims: list[Any], hits: list[Hit]) -> list[dict[str, Any]]:
    """Keep only claims that cite retrieved passages and are grounded in them.

    A claim with no citation, a citation outside the retrieved set, or wording
    the cited passages do not support is dropped rather than shown uncited.
    """
    kept: list[dict[str, Any]] = []
    for item in raw_claims or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        refs: list[int] = []
        for raw in item.get("citations") or []:
            try:
                ref = int(str(raw).strip("[]S "))
            except (TypeError, ValueError):
                continue
            if 1 <= ref <= len(hits) and ref not in refs:
                refs.append(ref)
        if not text or not refs:
            continue
        cited = [hits[r - 1].passage.text + " " + hits[r - 1].passage.title for r in refs]
        quote = str(item.get("quote") or "").strip()
        # The quote is verbatim source text, so it grounds a claim written in another language.
        if quote:
            if not grounded(quote, cited, min_overlap=QUOTE_MIN_OVERLAP):
                continue
        elif not grounded(text, cited):
            continue
        kept.append({"text": text, "citations": refs, "quote": quote or None, "quoted": False})
    return kept
