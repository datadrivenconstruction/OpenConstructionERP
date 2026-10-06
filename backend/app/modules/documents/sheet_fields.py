# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reading a drawing sheet's title block, and ordering its revisions.

One module for everything the register reads off a drawing page: the sheet
number, title, scale, revision and issue date from the page text, the same
fields from the file name when the page says nothing, the discipline the number
implies, the key two numbers stack on, and the order of two revision labels.
The splitter in ``documents.service`` and the drawing-index parser in
``documents.sheet_index`` both read revisions through here, so a title block and
a pasted register can never disagree about what "Rev. 02" means.

Stdlib only, on purpose: ``sheet_index`` advertises a pure core, and this is
imported by it.

Why the revision pattern looks the way it does. The first version matched
``REV`` anywhere with no word boundary in front and took the first hit on the
page, so an Italian plan that mentions a "porta scorrevole" (sliding door) above
its title block was registered at revision "ole", "Revisione: 02" read as "e"
and "REVIEWED BY" as "IEWED". The label now has to stand as a word on both
sides, the value is bounded to the shapes a revision actually takes, and the
value is matched case-sensitively so a lower-case word after a label ("indice
di ...") is never read as one.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

# ── Discipline ────────────────────────────────────────────────────────────

# First letter of a sheet number, the US/UK convention ("A-201", "S-100").
DISCIPLINE_PREFIX_MAP: dict[str, str] = {
    "A": "Architectural",
    "S": "Structural",
    "M": "Mechanical",
    "E": "Electrical",
    "P": "Plumbing",
    "C": "Civil",
    "L": "Landscape",
}

# Whole-word discipline codes, the Italian convention ("ARC_PT_01", "STR-04").
# IMP is "impianti", building services as a whole, so it maps to MEP rather than
# to any one of mechanical, electrical or plumbing.
DISCIPLINE_CODE_MAP: dict[str, str] = {
    "ARC": "Architectural",
    "STR": "Structural",
    "IMP": "MEP",
    "MEC": "Mechanical",
    "ELE": "Electrical",
    "IDR": "Plumbing",
}

_LEADING_LETTERS = re.compile(r"[A-Za-z]+")


def detect_discipline_from_sheet_number(sheet_number: str | None) -> str | None:
    """Name the discipline a sheet number implies, or None.

    The run of letters a number starts with is looked up whole first, so
    "ARC_PT_01" is architectural and "STR-04" structural. Only a one or two
    letter prefix falls back to its first letter ("A-201", "A201", "AR-101");
    a longer word that is not a known code ("TAV_01", "TAVOLA") says nothing
    about the discipline, and reading its first letter would call every Tavola
    a "T" drawing.
    """
    if not sheet_number:
        return None
    match = _LEADING_LETTERS.match(sheet_number.strip())
    if match is None:
        return None
    prefix = match.group(0).upper()
    if prefix in DISCIPLINE_CODE_MAP:
        return DISCIPLINE_CODE_MAP[prefix]
    if len(prefix) <= 2:
        return DISCIPLINE_PREFIX_MAP.get(prefix[0])
    return None


# ── Stack key ─────────────────────────────────────────────────────────────

_KEY_SEPARATORS = re.compile(r"[\s._\-/]+")
_LEADING_ZEROS = re.compile(r"(?<!\d)0+(?=\d)")


def sheet_chain_key(sheet_number: str | None) -> str:
    """The key two sheet numbers stack on: equal keys are the same drawing.

    Case, dashes, dots, underscores, slashes and spaces are drafting style, and
    so are leading zeros, so "A-101", "a101", "A 101" and "A-0101" share one
    key, as do "TAV_01" and "TAV-1". Every other character is kept, so
    different drawings stay apart. A word prefix is kept too: "TAV_03" and the
    bare "3" a "TAVOLA 3" label yields are different keys, because a bare
    number cannot stack on anything without the title check below, and folding
    "TAV_03" into it would put every Tavola file name under that check.

    Returns an empty string for a missing or blank number, which never stacks.
    """
    if not sheet_number:
        return ""
    key = _KEY_SEPARATORS.sub("", sheet_number.strip().upper())
    return _LEADING_ZEROS.sub("", key)


def chain_key_is_bare(key: str) -> bool:
    """True when a stack key is digits only.

    A bare number ("TAVOLA 1") carries no discipline, and Italian sets commonly
    number each discipline from 1, so the stacker asks for more than the key
    before it treats two of them as one drawing.
    """
    return key.isdigit()


# ── Revision order ────────────────────────────────────────────────────────

_REVISION_LABEL_PREFIX = re.compile(r"^(?:REV(?:ISION[EI]?)?\.?\s*|R(?=\d))", re.IGNORECASE)
_REV_NUMERIC = re.compile(r"^\d{1,4}$")
_REV_LETTERS = re.compile(r"^[A-Z]{1,3}$")
_REV_PREFIXED = re.compile(r"^([A-Z])[-.]?(\d{1,3})$")
_REV_NUMBER_LETTER = re.compile(r"^(\d{1,3})([A-Z])$")

# Preliminary issues come before construction issues: P01 < P02 < C01 < C02.
_SERIES_ORDER = {"P": 0, "C": 1}


def _letters_value(letters: str) -> int:
    """A=1 ... Z=26, AA=27, the way a revision letter rolls over."""
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value


def _revision_rank(revision: str | None) -> tuple[str, tuple[int, ...]] | None:
    """Parse a revision label into a (scheme, sortable value) pair, or None."""
    if not revision:
        return None
    text = _REVISION_LABEL_PREFIX.sub("", revision.strip()).strip().upper()
    if not text:
        return None
    if _REV_NUMERIC.match(text):
        return ("numeric", (int(text),))
    if _REV_LETTERS.match(text):
        return ("letters", (_letters_value(text),))
    prefixed = _REV_PREFIXED.match(text)
    if prefixed:
        series, number = prefixed.group(1), int(prefixed.group(2))
        if series in _SERIES_ORDER:
            return ("series", (_SERIES_ORDER[series], number))
        return (f"prefix-{series}", (number,))
    number_letter = _REV_NUMBER_LETTER.match(text)
    if number_letter:
        return ("number-letter", (int(number_letter.group(1)), _letters_value(number_letter.group(2))))
    return None


def compare_revisions(a: str | None, b: str | None) -> int | None:
    """Order two revision labels: -1 if ``a`` is earlier, 0 if equal, 1 if later.

    Two labels compare only within one scheme: numbers with numbers ("02" < "10"),
    letters with letters (A < B < ... < Z < AA), number-letter pairs ("1A" < "1B" <
    "2A"), and prefixed labels with the same prefix ("X01" < "X02"). The P and C
    series compare with each other too, every preliminary issue before every
    construction issue. Anything else, including a missing label on either side,
    returns None: the order is not knowable from the labels, and the caller has
    to say so rather than guess.
    """
    rank_a, rank_b = _revision_rank(a), _revision_rank(b)
    if rank_a is None or rank_b is None or rank_a[0] != rank_b[0]:
        return None
    if rank_a[1] == rank_b[1]:
        return 0
    return -1 if rank_a[1] < rank_b[1] else 1


# ── Title block reading ───────────────────────────────────────────────────

# A title block lays its fields out in columns, and the text extractor joins
# the cells that share a visual row into one line separated by runs of spaces.
# So "SCALE: 1:50    DRAWN: AB    DATE: 2026-01-14" arrives as a single line and
# a pattern that captures to the end of it captures three fields, not one.
#
# Two independent signals mark where the next field begins. A run of two or more
# spaces is the column gap. A following label is the field name itself, and the
# label carries no internal space so that "AS NOTED" is not mistaken for one.
_FIELD_LABEL_BREAK = re.compile(r"[ \t]+(?=[A-Za-z][A-Za-z.]{0,14}[ \t]*[:=])")
_COLUMN_GAP_BREAK = re.compile(r"[ \t]{2,}")


def _trim_title_block_value(value: str, *, cut_on_column_gap: bool) -> str:
    """Cut a captured title block value where the next field starts.

    Args:
        value: The raw capture, already bounded to a single line.
        cut_on_column_gap: Whether a run of two or more spaces also ends the
            value. True for narrow-vocabulary fields like the scale, where such
            a run can only be a column gap. False for free text like the sheet
            title, where wide letter spacing inside one cell can produce the
            same run and cutting on it would truncate a real title.

    Returns:
        The value up to the first break, stripped.
    """
    cuts = [m.start() for m in (_FIELD_LABEL_BREAK.search(value),) if m is not None]
    if cut_on_column_gap:
        gap = _COLUMN_GAP_BREAK.search(value)
        if gap is not None:
            cuts.append(gap.start())
    return (value[: min(cuts)] if cuts else value).strip()


# Label words that mark a line as part of a title block. A revision found near
# one of these is preferred over one found anywhere else on the page.
_TITLE_BLOCK_CUE = re.compile(
    r"(?<!\w)(?:SCALE|SCALA|MA(?:SS|ß)STAB|[ÉE]CHELLE|ESCALA|DATE|DATA|DATUM|FECHA|SHEET|DWG|DRAWING|"
    r"TAVOLA|TAV\.|ELABORATO|OGGETTO|TITOLO|TITLE|TITEL|BLATT|PLANO|PLANCHE|DRAWN|DISEGNATO|CHECKED|"
    r"PROGETTISTA|COMMITTENTE|FORMATO|PROJECT|PROGETTO|GEZEICHNET|GEPR[ÜU]FT)(?!\w)",
    re.IGNORECASE,
)

# Revision. The label is case-insensitive and must stand as a word: nothing
# word-like before it, no letter after it. Between label and value only
# horizontal whitespace is allowed, so "INDICE" on its own line never reads the
# first entry of the table of contents below it as a revision. The value is
# case-sensitive and bounded: one or two capitals with up to three digits (A, B,
# AA, P01, C02), or up to three digits with an optional capital (0, 02, 1A).
_REVISION_LABEL = (
    r"(?i:R[EÉ]V(?:ISION[EI]?|ISI[OÓ]N|IS[AÃ]O)?"
    r"|INDICE(?:[ \t]+(?:DI[ \t]+)?REV(?:ISIONE)?\.?)?"
    r"|IND\."
    r"|(?:ÄNDERUNGS|AENDERUNGS|PLAN)?INDEX"
    r"|STAND)"
)
_REVISION = re.compile(
    r"(?<!\w)" + _REVISION_LABEL + r"(?![^\W\d])\.?"
    r"(?:[ \t]*(?i:n[°º]?|no|nr|#)\.?(?=[ \t:]*\d))?"
    r"[ \t]*(?P<sep>[:=])?[ \t]*"
    r"(?P<value>[A-Z]{1,2}\d{0,3}|\d{1,3}[A-Z]?)"
    # Not followed by more word, by a date or decimal continuation ("12.03"),
    # or by a period that opens a sentence ("1. Premessa").
    r"(?!\w)(?![./-]\d)(?!\.[ \t]*[^\W\d_])"
)
# Two-letter values that are words in the languages these labels come from,
# read after a label in running text ("INDEX OF DRAWINGS").
_REVISION_STOPWORDS = frozenset({"OF", "DI", "DE", "DA", "DU", "LA", "LE", "EL", "IN", "TO", "AT", "ON", "BY", "NO"})
_PROSE_WORDS = 10


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, (len(text) if end == -1 else end)


def _revision_from(text: str, *, drop_prose: bool = True) -> str | None:
    """The best revision candidate in ``text``, or None.

    Every bounded match is a candidate. A candidate on a long line of running
    text with no separator after its label is prose and dropped, unless
    ``drop_prose`` is off: a pasted register row is one long line by design.
    The rest are ranked: a separator after the label, a short line, and a neighbouring line
    carrying another title-block label each count one; on a tie the later
    candidate wins, because a title block sits at the foot of the sheet and the
    extractor reads top to bottom.
    """
    lines = text.split("\n")
    best: tuple[int, int, str] | None = None
    for match in _REVISION.finditer(text):
        value = match.group("value")
        if value in _REVISION_STOPWORDS:
            continue
        start, end = _line_bounds(text, match.start())
        line = text[start:end]
        has_sep = match.group("sep") is not None
        if drop_prose and len(line.split()) > _PROSE_WORDS and not has_sep:
            continue
        line_no = text.count("\n", 0, match.start())
        neighbours = "\n".join(lines[max(0, line_no - 2) : line_no] + lines[line_no + 1 : line_no + 3])
        score = int(has_sep) + int(len(line.strip()) <= 40) + int(_TITLE_BLOCK_CUE.search(neighbours) is not None)
        candidate = (score, match.start(), value)
        if best is None or candidate[:2] >= best[:2]:
            best = candidate
    return best[2] if best else None


# Sheet number, labelled. The label words are matched case-insensitively and as
# whole words, so "TAVOLE" (the plural, as in "ELENCO TAVOLE") is not "TAV".
_NUMBER_LABEL = re.compile(
    r"(?<!\w)(?i:SHEET[ \t]*(?:NO\.?|NUMBER|#)|SHEET(?=[ \t]*:)|DWG[ \t]*(?:NO\.?|#)|DWG(?=[ \t]*:)"
    r"|DRAWING[ \t]*(?:NO\.?|NUMBER)|TAVOLA|TAV\.?|ELABORATO|BLATT(?:[ \t]*NR\.?)?|PLAN[ \t-]*NR\.?"
    r"|PLANNUMMER|PLANO|PLANCHE|N[°º][ \t]*(?:DE[ \t]*)?PLAN(?:CHE|O)?)(?![^\W\d])"
    r"(?:[ \t]*(?i:n[°º]?|no|nr)\.?(?=[ \t:]*\w))?"
    r"[ \t]*[:=]?[ \t]*"
    r"(?P<value>(?i:[A-Z0-9](?:[A-Z0-9._\-]{0,18}[A-Z0-9])?))(?![\w./-])"
)
# Codes printed without a label, tried after the labelled form. The first and
# last are the original A-101 / A101 shapes; the two between are the Italian
# conventions, written in capitals and therefore matched case-sensitively, so
# "Strada 12" or "UNI EN 1992" never qualify.
_NUMBER_CODES = (
    re.compile(r"\b([A-Z]-\d{2,4}(?:\.\d+)?)\b", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,4}(?:_[A-Z]{1,4})*_\d{1,4}(?:_\d{1,4})?)(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9])((?:ARC|STR|IMP|MEC|ELE|IDR)(?:[-.][A-Z]{1,3})?[-.]?\d{1,4}(?:\.\d{1,3})?)(?![\w])"),
    re.compile(r"\b([A-Z]\d{3,4})\b", re.IGNORECASE),
)


# A number named after one of these words is another drawing the sheet points
# at ("vedi Tav. ARC-05", "siehe Plan-Nr. 12", "see A-501"), not its own.
_CROSS_REFERENCE = re.compile(
    r"(?<!\w)(?:vedi|v\.|cfr|rif|see|ref|refer[ \t]+to|siehe|vgl|voir|ver|v[ée]ase)\.?[ \t:]*$",
    re.IGNORECASE,
)


def _is_cross_reference(text: str, start: int) -> bool:
    line_start = text.rfind("\n", 0, start) + 1
    return _CROSS_REFERENCE.search(text[line_start:start]) is not None


def _sheet_number_from(text: str) -> str | None:
    """The sheet's own number in ``text``, or None.

    Labelled numbers are ranked the way revisions are (a separator after the
    label, a short line, a neighbouring title-block label; the later wins a
    tie), because the label words also appear in notes that point at other
    drawings. A number introduced by a reference word is never the sheet's
    own. Unlabelled codes are the fallback, the first one that is not a
    reference.
    """
    lines = text.split("\n")
    best: tuple[int, int, str] | None = None
    for match in _NUMBER_LABEL.finditer(text):
        value = match.group("value")
        if not any(ch.isdigit() for ch in value) or _is_cross_reference(text, match.start()):
            continue
        start, end = _line_bounds(text, match.start())
        line = text[start:end]
        has_sep = ":" in text[match.start() : match.start("value")] or "=" in text[match.start() : match.start("value")]
        line_no = text.count("\n", 0, match.start())
        neighbours = "\n".join(lines[max(0, line_no - 2) : line_no] + lines[line_no + 1 : line_no + 3])
        score = int(has_sep) + int(len(line.strip()) <= 40) + int(_TITLE_BLOCK_CUE.search(neighbours) is not None)
        if best is None or (score, match.start()) >= best[:2]:
            best = (score, match.start(), value)
    if best is not None:
        return best[2]
    for pattern in _NUMBER_CODES:
        for match in pattern.finditer(text):
            if not _is_cross_reference(text, match.start()):
                return match.group(1).strip()
    return None


# Title labels in priority order. A label that names the drawing itself beats
# OGGETTO, which on an Italian sheet is as often the subject of the whole works.
_TITLE_LABELS = (
    r"SHEET[ \t]*TITLE|DRAWING[ \t]*TITLE|TITOLO|CONTENUTO|PLANINHALT|PLANBEZEICHNUNG|TITLE|TITEL|TITRE|T[ÍI]TULO",
    r"OGGETTO",
)


def _title_from(text: str) -> str | None:
    """Read the title next to its label, or on the next line when the label stands alone.

    The first label found decides: a title too short to be one ("AB") is not
    replaced by a search further down, which would pick up whatever free text
    happened to follow a later label.
    """
    for labels in _TITLE_LABELS:
        pattern = re.compile(
            r"(?:(?<!\w)(?:" + labels + r")(?![^\W\d])[ \t]*[:=][ \t]*"
            r"|^[ \t]*(?:" + labels + r")(?![^\W\d])[ \t]*)"
            r"(?P<value>[^\r\n]*)",
            re.IGNORECASE | re.MULTILINE,
        )
        match = pattern.search(text)
        if match is None:
            continue
        value = match.group("value")
        if not value.strip():
            following = text[match.end() :].lstrip("\r\n").split("\n", 1)[0]
            value = "" if _TITLE_BLOCK_CUE.match(following.strip()) else following
        title = _trim_title_block_value(value.strip(), cut_on_column_gap=False)
        return title[:500] if len(title) > 2 else None
    return None


# Scale patterns: "1:100", "1/4\" = 1'-0\"", "SCALE: 1:50".
#
# The labelled pattern is bounded to the label's own line. It used to allow \s
# inside the character class, which matches a newline, so the capture ran off
# the end of the line and the trailing \S* then took the first token of the next
# one. A title block reading "SCALE: 1:50" above "REV C" was stored as
# "1:50\nREV", and that string is what the sheet detail drawer prints.
# Horizontal whitespace only, on both sides of the separator, because a title
# block field and its value share a line and a scale value can contain spaces of
# its own ("1/4\" = 1'-0\"", "AS NOTED").
#
# The imperial form needs "=" inside the first capture, or it is cut at the
# equals and stored as '1/4" ='.
_SCALE_PATTERNS = (
    re.compile(
        r"(?<!\w)(?:SCALE|SCALA|MA(?:SS|ß)STAB|[ÉE]CHELLE|ESCALA)[ \t]*[:=][ \t]*([^\r\n]+?)[ \t]*(?:\r?\n|$)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(1\s*:\s*\d{1,4})\b"),
    re.compile(r"(1/\d+\"\s*=\s*1'[\s-]*0\")"),
)


def _scale_from(text: str) -> str | None:
    for idx, pattern in enumerate(_SCALE_PATTERNS):
        match = pattern.search(text)
        if match:
            value = match.group(1)
            if idx == 0:
                # Only the labelled pattern can run into a neighbouring column;
                # the two below are bounded by their own character sets.
                value = _trim_title_block_value(value, cut_on_column_gap=True)
            return value.strip()[:50]
    return None


# Issue date. Every label but the English one reads day first; under DATE a
# date whose day and month could swap is left unset rather than guessed.
_DATE = re.compile(
    r"(?<!\w)(?P<label>(?i:DATA(?:[ \t]+(?:DI[ \t]+)?EMISSIONE)?|DATUM|DATE|FECHA|STAND))(?![^\W\d])"
    r"[ \t]*[:=]?[ \t]*"
    r"(?:(?P<iy>\d{4})[-./](?P<im>\d{1,2})[-./](?P<id>\d{1,2})"
    r"|(?P<a>\d{1,2})[-./](?P<b>\d{1,2})[-./](?P<y>\d{4}|\d{2}))(?!\d)"
)


def _date_from(text: str) -> str | None:
    for match in _DATE.finditer(text):
        if match.group("iy"):
            year, month, day = int(match.group("iy")), int(match.group("im")), int(match.group("id"))
        else:
            first, second = int(match.group("a")), int(match.group("b"))
            year = int(match.group("y"))
            if year < 100:
                year += 2000
            if match.group("label").upper() == "DATE":
                if first > 12 >= second:
                    day, month = first, second
                elif second > 12 >= first:
                    month, day = first, second
                else:
                    continue
            else:
                day, month = first, second
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


# ── File name ─────────────────────────────────────────────────────────────

_FILE_REVISION = re.compile(
    r"(?:^|[_\-\s.])(?i:REV(?:ISIONE|ISION)?[_\-\s.]?(?P<rev>[A-Z]?\d{1,3}|[A-Z]{1,2})|R(?P<r>\d{1,3}))(?=$|[_\-\s.])"
)
_FILE_NUMBER = re.compile(
    r"^(?P<number>[A-Za-z]{1,4}(?:[_\-.][A-Za-z]{1,4})*[_\-.]?\d{1,4}(?:[_\-.]\d{1,4})?|\d{1,4})(?=$|[_\-\s])"
)
# "ARC PT 01 Pianta": the same code with spaces for separators, as Italian and
# German offices name files. Spaces also separate ordinary words, so this one
# is narrow: at the very start, one or two groups of up to four UPPER-CASE
# letters, then up to four digits that end there. "Pianta piano terra 1" and
# "Via Roma 12" fail on case, "PIANTA PIANO TERRA 1" on length.
_FILE_SPACED_NUMBER = re.compile(r"^(?P<number>(?P<a>[A-Z]{1,4})(?: (?P<b>[A-Z]{1,4}))? \d{1,4})(?=$|[ _\-])")
# Capitals with the spaced code's shape that are something else: a street
# ("VIA ROMA 12") or a cited standard ("UNI EN 1090", "NTC 2018").
_FILE_SPACED_NOT_A_CODE = frozenset({"VIA", "DIN", "EN", "ISO", "UNI", "CEI", "NTC", "DM", "DPR", "SIA", "VDI"})


def fields_from_filename(filename: str | None) -> dict[str, str | None]:
    """Sheet number, revision and title from a drawing's file name.

    Reads the conventions drawing files are named by: "TAV_01_Pianta piano
    terra_rev02.pdf", "ARC_PT_01_R03.pdf", "A-101 Rev B.pdf". The revision
    token (_R03, _rev02, -REV-B, " Rev B") is cut out first and stored bare
    ("03", "B"), the same shape a title block's "Rev. 03" yields, so the two
    compare. The number is the code the remaining name starts with, and what
    follows it is the title. A code spaced out ("ARC PT 01 Pianta") is read
    only in its narrow upper-case shape, see ``_FILE_SPACED_NUMBER``.
    """
    result: dict[str, str | None] = {"sheet_number": None, "revision": None, "sheet_title": None}
    if not filename:
        return result
    stem = re.split(r"[\\/]", filename)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", stem).strip()
    revisions = list(_FILE_REVISION.finditer(stem))
    if revisions:
        last = revisions[-1]
        result["revision"] = (last.group("rev") or last.group("r")).upper()
        stem = (stem[: last.start()] + stem[last.end() :]).strip(" _-.")
    number = _FILE_NUMBER.match(stem)
    if number is None:
        spaced = _FILE_SPACED_NUMBER.match(stem)
        if spaced and not {spaced.group("a"), spaced.group("b")} & _FILE_SPACED_NOT_A_CODE:
            number = spaced
    if number:
        result["sheet_number"] = number.group("number")
        rest = stem[number.end() :]
        title = re.sub(r"[_\s]+", " ", rest).strip(" -_.")
        if len(title) > 2:
            result["sheet_title"] = title[:500]
    return result


# ── Entry point ───────────────────────────────────────────────────────────


def detect_sheet_info(
    page_text: str,
    *,
    title_block_text: str | None = None,
    filename: str | None = None,
) -> dict[str, str | None]:
    """Read sheet number, title, scale, revision and issue date for one page.

    Regex over text the PDF already carries; no OCR. Each field is looked for
    in the title block region first when the caller has it, then on the whole
    page, then in the file name when the caller passes one. The splitter passes
    the file name only for a single-page PDF, where the name describes that one
    drawing; a set's name says nothing about its individual pages.

    Args:
        page_text: The page's extracted text.
        title_block_text: Text of the bottom-right region, where a title block
            sits, when the extractor can crop by position.
        filename: The uploaded file's name, for the fallback.

    Returns:
        Dict with keys sheet_number, sheet_title, scale, revision and
        revision_date. The date is an ISO "YYYY-MM-DD" string.
    """
    sources = [t for t in (title_block_text, page_text) if t]

    def first(reader: Callable[[str], str | None]) -> str | None:
        for text in sources:
            value = reader(text)
            if value:
                return value
        return None

    result: dict[str, str | None] = {
        "sheet_number": first(_sheet_number_from),
        "sheet_title": first(_title_from),
        "scale": first(_scale_from),
        "revision": first(_revision_from),
        "revision_date": first(_date_from),
    }
    if filename:
        from_name = fields_from_filename(filename)
        for key in ("sheet_number", "revision", "sheet_title"):
            if result[key] is None:
                result[key] = from_name[key]
    return result


def extract_inline_revision(text: str | None) -> str | None:
    """A revision label inside one free-text cell or line ("Pianta - Rev C")."""
    if not text:
        return None
    return _revision_from(text, drop_prose=False)
