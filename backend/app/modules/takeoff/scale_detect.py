# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tier-1 drawing-scale detection from an already-extracted PDF text layer.

This is the deterministic, AI-free complement to the vision plan-reader's
scale proposal (``plan_read.scale_ratio_from_plan_scale``). Where the vision
path *looks at the pixels*, this path simply *reads the text the architect
already typed on the sheet* - the explicit scale note (``SCALE 1:100``,
``1/4" = 1'-0"``) that almost every drawing carries in its title block.

Nothing here calls a network, an AI provider, a database, or a PDF reader. It is a
pure string -> candidate function so it unit-tests with no dependency at all
(mirrors :mod:`recognize` and :mod:`plan_read`). The service layer feeds it the
per-page ``text`` already stored in ``TakeoffDocument.page_data`` and turns the
top candidate into a one-click calibration the user confirms (CLAUDE.md rule 7:
augmented, human-confirmed - we never auto-apply a detected scale).

Coordinate / unit contract (matches the frontend ``scale-helpers``):
a paper scale ``1:N`` means one paper unit represents ``N`` real-world units.
The frontend renders the PDF at 72 points-per-inch, so the canonical
pixels-per-metre is ``72 / (0.0254 * N)`` - but this module only ever returns
the integer ratio ``N`` and a human-readable label; the px/m derivation stays
in the frontend's single-sourced ``presetScale`` so there is one definition.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Inches per foot - the metric/imperial bridge for the imperial notations.
_INCHES_PER_FOOT = 12

# Plausible architectural / engineering ratio band. A ratio outside this band
# is almost never a real drawing scale: ``1:1`` is a rare detail callout we
# still allow, while ``1:100000`` is map/page-coordinate noise and ``1:0`` is
# malformed. The upper bound (10000) comfortably covers civil site plans
# (1:2500, 1:5000) without admitting the six-figure values that show up in
# geographic coordinate strings or part numbers.
_MIN_RATIO = 1
_MAX_RATIO = 10_000

# How close (in characters) the literal word "scale" must sit before a ratio
# token for the candidate to earn the keyword-proximity confidence boost. A
# small window keeps "...at a scale suitable for ... 1:100 year flood" from
# falsely binding the boost to an unrelated ratio far down the line.
_SCALE_KEYWORD_WINDOW = 24

# Confidence tiers. A ratio adjacent to the word "scale" is the strongest
# signal; a bare ``1:100`` somewhere on the sheet is good but weaker; an
# imperial equation (``1/4" = 1'-0"``) is itself an explicit scale statement so
# it ranks with the keyword tier even without the word "scale".
_CONF_SCALE_KEYWORD = 0.95
_CONF_IMPERIAL = 0.9
_CONF_LABEL_ABOVE = 0.9
_CONF_BARE_RATIO = 0.7
# A bare ratio that no drawing is plotted at, or one beside "section"/"detail",
# is still offered but never outranks the sheet's own scale.
_CONF_ODD_RATIO = 0.5
_CONF_DETAIL = 0.45
# Below this the best candidate is offered in the list but not applied.
_MIN_BEST_CONFIDENCE = 0.5

# Words that, appearing immediately before a ``1:N`` token, mark it as a
# drawing scale even without the literal "scale" (covers common title-block and
# localized abbreviations seen in multi-country sheets).
_SCALE_WORDS: tuple[str, ...] = (
    "scale",
    "scaled",
    "sc",
    "scl",
    "ech",  # echelle (FR)
    "echelle",
    "échelle",  # echelle (FR, accented)
    "escala",  # ES / PT
    "massstab",  # DE
    "maßstab",  # massstab (DE, sharp-s)
    "mst",
    "masstab",
    "schaal",  # NL
    "skala",  # PL / SE
    "масштаб",  # masshtab (RU)
    "м",  # RU / UA abbreviation
    "m",  # Latin "M 1:100"
    "e",  # ES / PT "E 1:100"
    "esc",
    "éch",
    "scala",  # IT
    "mk",  # FI abbreviation
    "mittakaava",  # FI
    "měřítko",  # CS
    "meritko",
    "mierka",  # SK
    "ölçek",  # TR
    "olcek",
    "målestok",  # DA / NO
    "malestok",
    "målestokk",
    "mõõtkava",  # ET
    "mastelis",  # LT
    "mērogs",  # LV
    "mjerilo",  # HR
    "merilo",  # SL
    "lépték",  # HU
    "méretarány",
    "scara",  # RO
    "scară",
    "κλίμακα",  # EL
    "мащаб",  # BG
    "縮尺",  # JA
    "比例",  # ZH
    "축척",  # KO
    "مقياس",  # AR
    "पैमाना",  # HI
)

# Long keywords may sit a few characters before the ratio ("Scale = 1:100") or on
# the title-block line above it, as whole words. Abbreviations of one or two letters
# ("M 1:100", "E 1:50") are initials of anything, so they count only directly before
# the ratio and only when they do not follow a number ("gutter 10 m 1:80" is a fall).
_LONG_SCALE_WORDS: tuple[str, ...] = tuple(w for w in _SCALE_WORDS if len(w) >= 3)
_INITIAL_SCALE_WORDS: frozenset[str] = frozenset(w for w in _SCALE_WORDS if len(w) < 3)

# What else a ratio on a drawing can be: the proportions of a mix, and the fall of a
# surface. Stems, matched at the start of a word in the text before the ratio.
_NOT_SCALE_STEMS: tuple[str, ...] = (
    # mixes: mortar, concrete, cement, grout, plaster, screed
    "mix", "mortar", "concrete", "cement", "grout", "plaster", "render", "screed", "lime",
    "mörtel", "moertel", "beton", "zement", "putz", "estrich", "mischung",
    "mortier", "béton", "ciment", "enduit", "chape",
    "mortero", "hormig", "cemento", "lechada", "malta", "calcestruzz",
    "zapraw", "tynk", "wylewk", "mortel", "cement",
    "раствор", "бетон", "цемент", "штукатур", "стяжк", "смес",
    "砂浆", "混凝土", "モルタル", "コンクリート", "몰탈", "콘크리트",
    # falls: slope, gradient, ramp, pitch, drainage
    "slope", "fall", "gradient", "ramp", "pitch", "drain", "gutter", "batter", "taper", "incline",
    "gefälle", "gefaelle", "neigung", "rampe", "pente", "pendiente", "rampa", "pendenza",
    "spadek", "nachyl", "pochyl", "helling", "afschot",
    "уклон", "рампа", "пандус", "скат", "坡度", "勾配", "경사",
    # not drawings at all
    "ratio", "aspect", "odds",
)  # fmt: skip

# Words that mark a ratio as the scale of a detail or section callout.
_DETAIL_WORDS: tuple[str, ...] = (
    "section",
    "detail",
    "détail",
    "coupe",
    "schnitt",
    "corte",
    "sezione",
    "dettaglio",
    "detalle",
    "doorsnede",
    "przekrój",
    "szczegół",
    "разрез",
    "узел",
    "деталь",
    "詳細",
    "详图",
    "剖面",
    "断面",
)


def _unspaced(word: str) -> bool:
    """True for a word of a script written without spaces, where it has no word start."""
    return any("\u3040" <= c <= "\ud7af" for c in word)


def _has_word(text: str, words: tuple[str, ...]) -> bool:
    """True when one of the words stands in ``text`` as a whole word, ignoring digits around it."""
    for word in words:
        pos = text.find(word)
        while pos >= 0:
            if _unspaced(word):
                return True
            end = pos + len(word)
            if not (pos > 0 and text[pos - 1].isalpha()) and not (end < len(text) and text[end].isalpha()):
                return True
            pos = text.find(word, pos + 1)
    return False


def _has_stem(text: str, stems: tuple[str, ...]) -> bool:
    """True when a word in ``text`` starts with one of the stems."""
    for stem in stems:
        pos = text.find(stem)
        while pos >= 0:
            if _unspaced(stem) or pos == 0 or not text[pos - 1].isalpha():
                return True
            pos = text.find(stem, pos + 1)
    return False


# Sheets that say they are not to scale.
_NTS_RE = re.compile(
    r"\b(?:n\.?\s?t\.?\s?s\.?|not\s+to\s+scale|sans\s+[ée]chelle|ohne\s+ma(?:ß|ss)stab|sin\s+escala)(?![\w])",
    re.IGNORECASE,
)

# Scales drawings are actually plotted at (metric ratios and imperial equivalents).
_STANDARD_RATIOS = frozenset(
    {1, 2, 5, 10, 20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 750}
    | {1000, 1250, 1500, 2000, 2500, 5000, 10000}
    | {4, 8, 12, 16, 24, 32, 48, 64, 96, 120, 128, 192, 240, 360, 480, 600, 720, 960, 1200}
)

# ISO 216 sheet sizes, long side and short side.
_ISO_A_MM = {0: (1189.0, 841.0), 1: (841.0, 594.0), 2: (594.0, 420.0), 3: (420.0, 297.0), 4: (297.0, 210.0)}

# Pre-compiled patterns ------------------------------------------------------

# A ratio stated for a paper size: "1:100 @ A1", "1:50 at A3", "1:100 auf A1".
_AT_PAPER_RE = re.compile(r"\s*(?:@|at|auf|en|in|à|на)\s*A([0-4])(?![\w])", re.IGNORECASE)

# Ratio token: "1:100", "1 : 50", "1:1 000" (some locales space-group the
# right-hand side). We capture the left and right numbers separately and reject
# anything but a unit antecedent (left side must be 1..few - a "16:9" aspect
# ratio or a "2:34" timestamp is filtered downstream by the antecedent check).
_RATIO_RE = re.compile(r"(?<![\d.])(\d{1,3})\s*[:\uff1a]\s*(\d{1,3}(?:[ \u00a0]\d{3})*|\d{1,6})(?![\d.])")

# "1/50" is a scale only straight after a scale keyword ("ECHELLE : 1/50");
# anywhere else it is a fraction or a date.
_SLASH_RE = re.compile(r"(?<![\d./])1\s*/\s*(\d{1,5})(?![\d./\"'\u2033])")

# Imperial fraction or whole inch on the LEFT of an equals sign:
#   1/4" = 1'-0"      3/8" = 1'-0"      1/2 in = 1 ft       1" = 20'
# Left side: a whole and/or fraction measure captured as one ``lmeas`` token
# ("1", "1/4", "1 1/2") then parsed in Python so a missing space before the
# inch mark ("1\"") is handled the same as a spaced one. The inch mark
# (``"`` / ``in``) is mandatory so a bare "1 = 20" never matches.
# Right side: feet (with ' or ft) and optional residual inches.
_IMPERIAL_RE = re.compile(
    r"""
    (?<![\w./-])
    (?P<lmeas>\d+(?:\s+\d+)?(?:\s*/\s*\d+)?)   # 1 | 1/4 | 1 1/2
    \s*(?P<lunit>"|''|\u2033|in\b|inch\b|inches\b)  # inch mark on the left
    \s*=\s*
    (?:(?P<rf>\d+(?:\.\d+)?)\s*(?:'|ft\b|foot\b|feet\b|\u2032))?   # feet
    # Separator before residual inches may be a hyphen or a unicode en-dash
    # (some sheets render 1'-6" with an en-dash); both are matched via escape
    # so the source file carries no literal long-dash character.
    (?:\s*[-\u2013]?\s*(?P<ri>\d+(?:\.\d+)?)\s*(?:"|''|\u2033)?)?  # residual inches
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _parse_left_inches(lmeas: str) -> tuple[int, int | None, int | None]:
    """Parse a left-hand inch measure into ``(whole, frac_num, frac_den)``.

    Accepts ``"1"`` -> (1, None, None), ``"1/4"`` -> (0, 1, 4), and the mixed
    ``"1 1/2"`` -> (1, 1, 2). Returns ``(0, None, None)`` for an unparseable
    string so the caller skips it.
    """
    text = lmeas.strip()
    whole = 0
    num: int | None = None
    den: int | None = None
    frac_part = ""
    if "/" in text:
        head, _, frac_part = text.rpartition("/")
        # head is "1 1" (whole + frac-numerator) or just the numerator "1".
        head_tokens = head.split()
        if len(head_tokens) == 2 and head_tokens[0].isdigit() and head_tokens[1].isdigit():
            whole = int(head_tokens[0])
            num = int(head_tokens[1])
        elif len(head_tokens) == 1 and head_tokens[0].isdigit():
            num = int(head_tokens[0])
        if frac_part.strip().isdigit():
            den = int(frac_part.strip())
        else:
            den = None
    elif text.isdigit():
        whole = int(text)
    return whole, num, den


@dataclass
class ScaleCandidate:
    """One detected drawing-scale candidate with its supporting evidence.

    ``ratio`` is the integer ``N`` of a ``1:N`` paper scale (one paper unit =
    ``N`` real-world units). ``label`` is the human-readable form for the UI
    ("1:100"). ``evidence`` is the exact matched substring from the sheet and
    ``page`` the 1-based page it was found on. ``confidence`` orders candidates
    so the caller can offer the strongest one first.
    """

    ratio: int
    label: str
    confidence: float
    page: int
    evidence: str
    source: str  # "ratio" | "imperial"
    # The raw notation kind kept for deduplication / debugging; not surfaced.
    detail: dict[str, object] = field(default_factory=dict)


def _normalize_group(num_text: str) -> int | None:
    """Parse a possibly space-grouped integer ("1 000" -> 1000)."""
    cleaned = num_text.replace("\u00a0", "").replace(" ", "")
    if not cleaned.isdigit():
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _word_before(text: str, start: int) -> str:
    """Return the lowercased alphabetic word ending just before ``start``.

    Skips intervening spaces, colons and punctuation so "Scale: 1:100" still
    resolves the antecedent to "scale". Returns "" when no word precedes.
    """
    i = start
    # Skip separators between the word and the token.
    while i > 0 and text[i - 1] in " \t:\uff1a=.-\u00a0":
        i -= 1
    end = i
    while i > 0 and (text[i - 1].isalpha() or text[i - 1] in "éèëà"):
        i -= 1
    return text[i:end].lower()


def _line_bounds(text: str, pos: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return start, len(text) if end < 0 else end


def _named_callout(text: str, start: int, cap: float | None) -> bool:
    """A detail ratio labelled with a full scale word on its own line ("Detail scale 1:1")."""
    if cap != _CONF_DETAIL:
        return False
    line_start, _line_end = _line_bounds(text, start)
    before = text[max(line_start, start - _SCALE_KEYWORD_WINDOW) : start].lower()
    return _has_word(before, _LONG_SCALE_WORDS)


def _is_initial(text: str, start: int) -> bool:
    """True for a scale initial directly before the token and not after a number."""
    word = _word_before(text, start)
    if word not in _INITIAL_SCALE_WORDS:
        return False
    i = len(text[:start].rstrip(" \t:\uff1a=.-\u00a0")) - len(word)
    before = text[:i].rstrip()
    return not (before and before[-1].isdigit())


def _context(text: str, start: int, end: int) -> tuple[bool, float | None]:
    """Keyword evidence for the token at ``start:end``: (near a scale word, confidence cap)."""
    line_start, _line_end = _line_bounds(text, start)
    before = text[max(line_start, start - _SCALE_KEYWORD_WINDOW) : start].lower()
    tail = text[end : end + 2]
    if re.match(r"\s*[:\uff1a]\s*\d", tail):
        return False, 0.0  # "1:2:3" is a mix
    if _has_stem(before, _NOT_SCALE_STEMS):
        return False, 0.0
    cap = _CONF_DETAIL if _has_word(before, _DETAIL_WORDS) else None
    if _is_initial(text, start) or _has_word(before, _LONG_SCALE_WORDS):
        return True, cap
    if line_start > 0:
        # A title block prints the label at the end of the line above its value;
        # "Do not scale from this drawing" mentions the word but labels nothing.
        prev_start = text.rfind("\n", 0, line_start - 1) + 1
        prev = text[prev_start : line_start - 1].lower()
        if any(re.search(r"(?<!\w)" + re.escape(w) + r"\s*:?\s*$", prev) for w in _LONG_SCALE_WORDS):
            if not _RATIO_RE.search(prev):
                return True, cap if cap is not None else _CONF_LABEL_ABOVE
    return False, cap


def _stated_paper(text: str, end: int) -> dict[str, object]:
    m = _AT_PAPER_RE.match(text, end)
    return {"at_paper": int(m.group(1))} if m else {}


def _ratio_is_plausible(ratio: int) -> bool:
    """True when ``ratio`` falls in the architectural/engineering band."""
    return _MIN_RATIO <= ratio <= _MAX_RATIO


def _scan_ratios(text: str, page: int) -> list[ScaleCandidate]:
    """Find ``1:N`` ratio scales in one page's text."""
    out: list[ScaleCandidate] = []
    for m in _RATIO_RE.finditer(text):
        left = _normalize_group(m.group(1))
        right = _normalize_group(m.group(2))
        if left is None or right is None:
            continue
        # A drawing ratio's antecedent is unity (1:N). "16:9", "2:34" (a time),
        # "3:1" mix ratios are not page scales - require left == 1. This single
        # rule removes the bulk of false positives (timestamps, aspect ratios,
        # odds) without needing a notation-specific blocklist.
        if left != 1:
            continue
        if not _ratio_is_plausible(right):
            continue

        near_keyword, cap = _context(text, m.start(), m.end())
        if cap == 0.0:
            continue
        if near_keyword:
            confidence = _CONF_SCALE_KEYWORD
        else:
            confidence = _CONF_BARE_RATIO if right in _STANDARD_RATIOS else _CONF_ODD_RATIO
        if cap is not None:
            confidence = min(confidence, cap)
        out.append(
            ScaleCandidate(
                ratio=right,
                label=f"1:{right}",
                confidence=confidence,
                page=page,
                evidence=m.group(0).strip(),
                source="ratio",
                detail={
                    "near_keyword": near_keyword,
                    "antecedent": left,
                    "callout": _named_callout(text, m.start(), cap),
                    **_stated_paper(text, m.end()),
                },
            )
        )
    for m in _SLASH_RE.finditer(text):
        right = int(m.group(1))
        if not _ratio_is_plausible(right):
            continue
        near_keyword, cap = _context(text, m.start(), m.end())
        if not near_keyword or cap == 0.0:
            continue
        out.append(
            ScaleCandidate(
                ratio=right,
                label=f"1:{right}",
                confidence=min(_CONF_SCALE_KEYWORD, cap) if cap is not None else _CONF_SCALE_KEYWORD,
                page=page,
                evidence=m.group(0).strip(),
                source="ratio",
                detail={
                    "near_keyword": True,
                    "antecedent": 1,
                    "slash": True,
                    "callout": _named_callout(text, m.start(), cap),
                },
            )
        )
    return out


def _imperial_ratio(
    left_whole: int,
    frac_num: int | None,
    frac_den: int | None,
    feet: float,
    inches: float,
) -> float | None:
    """Compute the integer-style ratio N for an imperial scale equation.

    paper_inches = left_whole + frac_num/frac_den   (e.g. 1/4 -> 0.25)
    real_inches  = feet * 12 + inches
    ratio        = real_inches / paper_inches
    Returns ``None`` when the equation is degenerate (zero paper or real span).
    """
    paper_inches = float(left_whole)
    if frac_num is not None and frac_den:
        paper_inches += frac_num / frac_den
    real_inches = feet * _INCHES_PER_FOOT + inches
    if paper_inches <= 0 or real_inches <= 0:
        return None
    return real_inches / paper_inches


def _scan_imperial(text: str, page: int) -> list[ScaleCandidate]:
    """Find imperial scale equations (``1/4" = 1'-0"``, ``1" = 20'``)."""
    out: list[ScaleCandidate] = []
    for m in _IMPERIAL_RE.finditer(text):
        # The right side must carry at least feet OR inches - a match with
        # neither rf nor ri is just ``X" = `` noise, so skip it.
        rf = m.group("rf")
        ri = m.group("ri")
        if rf is None and ri is None:
            continue
        lw, ln, ld = _parse_left_inches(m.group("lmeas"))
        # A left side that parsed to nothing numeric (or a fraction missing its
        # denominator) is not a real measure; require at least one component.
        if lw == 0 and ln is None:
            continue
        if ln is not None and ld is None:
            continue  # "1/" with no denominator
        feet = float(rf) if rf else 0.0
        inches = float(ri) if ri else 0.0

        ratio_f = _imperial_ratio(lw, ln, ld, feet, inches)
        if ratio_f is None:
            continue
        ratio = round(ratio_f)
        if not _ratio_is_plausible(ratio):
            continue

        # Build a faithful label of what was on the sheet for the badge.
        if ln is not None and ld:
            left_label = f"{lw} {ln}/{ld}" if lw else f"{ln}/{ld}"
        else:
            left_label = str(lw)
        right_label = ""
        if rf:
            right_label += f"{_trim(rf)}'"
        if ri:
            right_label += f'-{_trim(ri)}"' if rf else f'{_trim(ri)}"'
        line_start, _line_end = _line_bounds(text, m.start())
        before = text[max(line_start, m.start() - _SCALE_KEYWORD_WINDOW) : m.start()].lower()
        is_detail = _has_word(before, _DETAIL_WORDS)
        out.append(
            ScaleCandidate(
                ratio=ratio,
                label=f"1:{ratio}",
                confidence=_CONF_DETAIL if is_detail else _CONF_IMPERIAL,
                page=page,
                evidence=m.group(0).strip(),
                source="imperial",
                detail={"imperial": f'{left_label}" = {right_label}'},
            )
        )
    return out


def _trim(num_text: str) -> str:
    """Render "1.0" as "1" but keep "1.5" as "1.5" for labels."""
    try:
        f = float(num_text)
    except ValueError:
        return num_text
    if f.is_integer():
        return str(int(f))
    return f"{f:g}"


def detect_scales_in_text(text: str, page: int = 1) -> list[ScaleCandidate]:
    """Detect every drawing-scale candidate in one page's extracted text.

    Returns the candidates found on ``page`` (deduplicated by ratio+source),
    unsorted. The caller (:func:`rank_candidates`) merges and ranks across all
    pages. An empty / None text yields ``[]`` cleanly.
    """
    if not text:
        return []
    candidates = _scan_ratios(text, page) + _scan_imperial(text, page)
    if _NTS_RE.search(text):
        # "NTS": only a ratio the sheet labels as its scale still counts.
        candidates = [c for c in candidates if c.detail.get("near_keyword") or c.source == "imperial"]
    return _dedupe(candidates)


def _dedupe(candidates: list[ScaleCandidate]) -> list[ScaleCandidate]:
    """Collapse duplicates by (ratio, source), keeping the highest confidence.

    A title block often repeats the scale; without this a sheet reading
    "SCALE 1:100" twice would offer the same ratio twice. We keep the most
    confident instance (so a keyword-adjacent hit wins over a bare repeat).
    """
    best: dict[tuple[int, str], ScaleCandidate] = {}
    for c in candidates:
        key = (c.ratio, c.source)
        existing = best.get(key)
        if existing is None or c.confidence > existing.confidence:
            best[key] = c
    return list(best.values())


def rank_candidates(candidates: list[ScaleCandidate]) -> list[ScaleCandidate]:
    """Order candidates best-first for the UI.

    Sort key (descending priority):
      1. confidence (keyword-adjacent and imperial equations rank highest),
      2. earliest page (the title-block scale is usually on the first sheet),
      3. largest ratio: a sheet's main drawing is the one at the smallest scale,
         the views enlarged from it take less paper and carry larger scales.
    Across pages, the same ratio+source is collapsed once more so a scale that
    repeats on every sheet is offered a single time.
    """
    deduped = _dedupe(candidates)
    deduped.sort(key=lambda c: (-c.confidence, c.page, -c.ratio))
    return deduped


def _paper_of(width_pt: float, height_pt: float) -> int | None:
    """The ISO A size of a page, None when it is not one."""
    long_mm = max(width_pt, height_pt) * 25.4 / 72.0
    short_mm = min(width_pt, height_pt) * 25.4 / 72.0
    for size, (a, b) in _ISO_A_MM.items():
        if abs(long_mm - a) <= 0.02 * a and abs(short_mm - b) <= 0.02 * b:
            return size
    return None


def _as_plotted(cand: ScaleCandidate, page: dict[str, object]) -> ScaleCandidate:
    """A scale stated for one paper size ("1:100 @ A1") read on the page it is actually on."""
    stated = cand.detail.get("at_paper")
    width, height = page.get("width_pt"), page.get("height_pt")
    if not isinstance(stated, int) or not isinstance(width, (int, float)) or not isinstance(height, (int, float)):
        return cand
    actual = _paper_of(float(width), float(height))
    if actual is None or actual == stated:
        return cand
    # Each A size is a linear factor of the square root of two from the next.
    ratio = round(cand.ratio * 2 ** ((actual - stated) / 2))
    return ScaleCandidate(
        ratio,
        f"1:{ratio}",
        cand.confidence,
        cand.page,
        cand.evidence,
        cand.source,
        {**cand.detail, "stated_ratio": cand.ratio},
    )


def detect_best_scale(
    pages: list[dict[str, object]],
) -> tuple[ScaleCandidate | None, list[ScaleCandidate]]:
    """Scan a document's per-page text for scales; return ``(best, all)``.

    ``pages`` is the ``TakeoffDocument.page_data`` shape:
    ``[{"page": 1, "text": "...", ...}, ...]``. Pages without a ``text`` key (or
    with empty text - e.g. scanned sheets that need OCR) contribute nothing. The
    return is the single best candidate (or ``None`` when the drawing carries no
    explicit scale note) plus the full ranked list for the "other matches" UI.
    """
    found: list[ScaleCandidate] = []
    for idx, page in enumerate(pages or []):
        if not isinstance(page, dict):
            continue
        text = page.get("text")
        page_no = page.get("page", idx + 1)
        try:
            page_int = int(page_no)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            page_int = idx + 1
        if isinstance(text, str) and text:
            found.extend(_as_plotted(c, page) for c in detect_scales_in_text(text, page_int))
    ranked = rank_candidates(found)
    best = None
    if ranked:
        top = ranked[0]
        if top.confidence >= _MIN_BEST_CONFIDENCE:
            best = top
        elif top.detail.get("callout") and len({c.ratio for c in ranked}) == 1:
            # one callout scale and nothing else on the sheet: the sheet is that detail
            best = top
    return best, ranked
