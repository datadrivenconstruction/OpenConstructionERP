"""Spec book text to proposed submittals. Pure functions, no I/O, one page at a time.

The parser is fed ``(page_number, text)`` pairs by :meth:`SpecParser.feed` and keeps only
the section it is inside, never the pages. Every proposal carries a confidence: 0.9 for an
explicit "Submit ..." under a SUBMITTALS heading, 0.7 for a listed item under that heading,
0.6 inferred from a keyword in Part 2 or 3. It proposes; a person decides.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

PARSER_VERSION = "1"
_FORMATS = Path(__file__).with_name("spec_formats.json")
_MAX_EXCERPT = 400

_PART = re.compile(r"^\s*PART\s+(\d)\b", re.IGNORECASE)
_SUBHEADING = re.compile(r"^\s*(\d)\.(\d{1,2})\s+(\S.*)$")
_LIST_MARKER = re.compile(r"^\s*(?:[A-Z]\.|\d{1,2}\.|[-•*]|\([a-z0-9]{1,3}\)|[a-z]\))\s+")
_END = re.compile(r"^\s*END\s+OF\s+SECTION\b", re.IGNORECASE)
_DOT_LEADER = re.compile(r"\.{4,}\s*\d*\s*$|(?:\s\.){4,}")
_PAGE_TAIL = re.compile(r"\s+(?:Page|Seite)\s+\d+.*$", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


@dataclass
class Proposal:
    spec_section: str
    section_title: str
    kind: str
    submittal_type: str
    title: str
    source_page: int
    source_excerpt: str
    confidence: float


@dataclass
class _Section:
    number: str
    title: str
    part: int = 0
    in_submittals: bool = False
    submit_lead: bool = False
    seen: set[str] = field(default_factory=set)
    item: list[str] = field(default_factory=list)
    item_page: int = 0


@lru_cache(maxsize=1)
def _formats() -> dict[str, Any]:
    data = json.loads(_FORMATS.read_text(encoding="utf-8"))
    data["_headers"] = [(re.compile(h["pattern"], re.IGNORECASE), h["group"]) for h in data["section_headers"]]
    data["_sub_headings"] = [re.compile(p, re.IGNORECASE) for p in data["submittal_headings"]]
    data["_types"] = [(t, [re.compile(p, re.IGNORECASE) for p in t["patterns"]]) for t in data["types"]]
    data["_submit"] = re.compile("|".join(re.escape(w) for w in data["submit_words"]), re.IGNORECASE)
    return data


def normalise_section(raw: str, mode: str) -> str:
    """The register's spelling of a section number: "03 30 00", "LB 013", "E10"."""
    if mode == "digits":
        digits = re.sub(r"[^\d.]", "", raw)
        base, _, tail = digits.partition(".")
        grouped = " ".join(base[i : i + 2] for i in range(0, len(base), 2))
        return f"{grouped}.{tail}" if tail else grouped
    if mode.startswith("prefix:"):
        return f"{mode.split(':', 1)[1]} {raw.strip()}"
    return raw.strip().upper()


def match_section_header(line: str) -> tuple[str, str] | None:
    """(number, title) when the line opens a spec section, else None."""
    if len(line) > 200:
        return None
    for pattern, mode in _formats()["_headers"]:
        m = pattern.match(line)
        if m:
            title = _PAGE_TAIL.sub("", m.group(2)).strip(" .-")
            if title:
                return normalise_section(m.group(1), mode), title
    return None


def is_toc_page(text: str) -> bool:
    """A table of contents repeats every section header; its lines end in dot leaders."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 4:
        return False
    leaders = sum(1 for ln in lines if _DOT_LEADER.search(ln))
    return leaders / len(lines) >= 0.3


def classify(text: str) -> dict[str, Any] | None:
    """The type entry an item asks for: its lead-in decides, the whole text is the fallback."""
    lead = re.split(r"[:;]|\.\s", text, maxsplit=1)[0]
    for scope in (lead, text):
        best: tuple[int, dict[str, Any]] | None = None
        for entry, patterns in _formats()["_types"]:
            for p in patterns:
                m = p.search(scope)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), entry)
        if best is not None:
            return best[1]
    return None


def required_kinds(section: str) -> list[str]:
    return list(_formats()["required_kinds"].get(section, []))


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


class SpecParser:
    """Incremental parser: ``feed`` pages in order, read ``proposals`` and ``sections``."""

    def __init__(self) -> None:
        self.proposals: list[Proposal] = []
        self.sections: list[tuple[str, str]] = []
        self._cur: _Section | None = None

    def feed(self, page_number: int, text: str) -> None:
        if not text or is_toc_page(text):
            return
        for raw in text.splitlines():
            line = raw.rstrip()
            if line.strip():
                self._line(page_number, line)

    def finish(self) -> None:
        self._flush()
        self._cur = None

    def _line(self, page: int, line: str) -> None:
        fmt = _formats()
        header = match_section_header(line)
        if header is not None:
            if self._cur is not None and self._cur.number == header[0]:
                return  # running page header of the same section
            self._flush()
            self._cur = _Section(number=header[0], title=header[1])
            self.sections.append(header)
            return
        cur = self._cur
        if cur is None:
            return
        if _END.match(line):
            self._flush()
            self._cur = None
            return
        part = _PART.match(line)
        if part:
            self._flush()
            cur.part, cur.in_submittals, cur.submit_lead = int(part.group(1)), False, False
            return
        sub = _SUBHEADING.match(line) if cur.part <= 1 else None
        is_sub_heading = any(p.match(line) for p in fmt["_sub_headings"]) and not _LIST_MARKER.match(line)
        if is_sub_heading and (sub is not None or len(line.split()) <= 6):
            self._flush()
            cur.in_submittals = True
            return
        if sub is not None:
            self._flush()
            cur.in_submittals = False
            return
        if cur.in_submittals:
            self._submittal_line(cur, page, line)
        elif cur.part >= 2:
            self._inferred(cur, page, line)

    def _submittal_line(self, cur: _Section, page: int, line: str) -> None:
        if _LIST_MARKER.match(line):
            self._flush()
            cur.item, cur.item_page = [line], page
        elif cur.item:
            cur.item.append(line)
        elif classify(line) is None:
            if _formats()["_submit"].search(line):
                cur.submit_lead = True  # "Submit the following:" above the list
        else:
            cur.item, cur.item_page = [line], page

    def _inferred(self, cur: _Section, page: int, line: str) -> None:
        if not _formats()["_submit"].search(line):
            return
        entry = classify(line)
        if entry is not None:
            self._emit(cur, entry, page, line, 0.6)

    def _flush(self) -> None:
        cur = self._cur
        if cur is None or not cur.item:
            return
        text = _clean(" ".join(cur.item))
        entry = classify(text)
        if entry is not None:
            explicit = cur.submit_lead or bool(_formats()["_submit"].search(text))
            self._emit(cur, entry, cur.item_page, text, 0.9 if explicit else 0.7)
        elif _formats()["_submit"].search(text):
            cur.submit_lead = True  # "A. Submit the following:" above the typed items
        cur.item = []

    def _emit(self, cur: _Section, entry: dict[str, Any], page: int, text: str, confidence: float) -> None:
        if entry["kind"] in cur.seen:
            return
        cur.seen.add(entry["kind"])
        self.proposals.append(
            Proposal(
                spec_section=cur.number,
                section_title=cur.title,
                kind=entry["kind"],
                submittal_type=entry["submittal_type"],
                title=f"{entry['label']} - {cur.title}"[:500],
                source_page=page,
                source_excerpt=_clean(text)[:_MAX_EXCERPT],
                confidence=confidence,
            )
        )


def parse_pages(pages: Iterable[tuple[int, str]]) -> SpecParser:
    """Parse a stream of ``(page_number, text)``; pages are consumed one at a time."""
    parser = SpecParser()
    for number, text in pages:
        parser.feed(number, text)
    parser.finish()
    return parser


def iter_pdf_pages(path: Path) -> Iterator[tuple[int, str]]:
    """Text of each PDF page, closing every page before the next is read."""
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(str(path)) as pdf:
        for index, page in enumerate(pdf.pages):
            try:
                yield index + 1, page.extract_text() or ""
            finally:
                page.close()
