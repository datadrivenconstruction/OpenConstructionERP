# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What kind of sheet a drawing page is, from its printed title.

Rooms and walls can only be proposed from a floor plan. On an elevation the windows
look like rooms, on a schedule the cells do. A sheet says what it is in its title, so
the printed lines are read for drawing-type words, and the line that wins is the one a
reader would take for the title: tall, standing alone, in the title block, or under a
label such as "Drawing title". A stray "see section A-A" in a note does not compete.

A page without such a line (a scan, a sketch) is ``unknown``: the caller decides from
the geometry alone (:func:`app.modules.takeoff.vector_plan.looks_like_rooms`).

Pure: words in, a verdict out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PLAN = "plan"
STRUCTURAL = "structural"  # a plan, but of what holds the building up or covers it: no rooms on it
ELEVATION = "elevation"
SECTION = "section"
SCHEDULE = "schedule"
DETAIL = "detail"
COVER = "cover"
SITE = "site"
UNKNOWN = "unknown"

# Sheets with nothing a room or wall takeoff can use.
NOT_A_PLAN = frozenset({ELEVATION, SECTION, SCHEDULE, DETAIL, COVER, SITE})

# Vocabulary per kind. Stems match at the start of a word, so plurals and case endings
# count ("план", "плана"; "Schnitt", "Schnitte"). Longer phrases are tried first through
# the kind order below: "foundation plan" is structural before it is a plan.
_VOCAB: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        COVER,
        (
            "cover sheet",
            "title sheet",
            "drawing index",
            "index of drawings",
            "drawing list",
            "general notes",
            "deckblatt",
            "planliste",
            "page de garde",
            "portada",
            "copertina",
            "титульный",
            "общие данные",
            "общие указания",
            "ведомость чертежей",
        ),
    ),
    (
        SITE,
        (
            "site plan",
            "location plan",
            "lageplan",
            "plan de masse",
            "plan de situation",
            "plano de situación",
            "planimetria generale",
            "plan sytuacyjny",
            "генплан",
            "генеральный план",
            "ситуационный план",
            "situatietekening",
            "总平面",
            "配置図",
            "배치도",
        ),
    ),
    (
        STRUCTURAL,
        (
            "foundation",
            "footing",
            "framing",
            "structural",
            "reinforcement",
            "roof plan",
            "fundament",
            "dachaufsicht",
            "dachdraufsicht",
            "schalplan",
            "bewehrung",
            "fondation",
            "plan de toiture",
            "plan de couverture",
            "cimentación",
            "cimentacion",
            "planta de cubierta",
            "fondazion",
            "pianta copertura",
            "rzut dachu",
            "fundamentowanie",
            "фундамент",
            "кровл",
            "армирован",
            "funderingsplan",
            "基础",
            "屋顶",
            "基礎",
            "屋根伏",
            "기초",
            "지붕",
        ),
    ),
    (
        SCHEDULE,
        (
            "schedule",
            "bill of quantities",
            "stückliste",
            "türliste",
            "fensterliste",
            "raumbuch",
            "nomenclature",
            "tableau des",
            "planilla",
            "cuadro de",
            "abaco",
            "abachi",
            "zestawienie",
            "ведомость",
            "спецификац",
            "экспликац",
            "明细表",
            "一覧表",
            "일람표",
        ),
    ),
    (
        ELEVATION,
        (
            "elevation",
            "ansicht",
            "fassade",
            "façade",
            "facade",
            "alzado",
            "prospetto",
            "prospetti",
            "elewacj",
            "фасад",
            "gevel",
            "aanzicht",
            "pohled",
            "görünüş",
            "立面",
            "입면",
        ),
    ),
    (
        SECTION,
        (
            "section",
            "schnitt",
            "coupe",
            "corte",
            "sezion",
            "przekr",
            "разрез",
            "doorsnede",
            "řez",
            "kesit",
            "剖面",
            "断面",
            "단면",
        ),
    ),
    (
        DETAIL,
        (
            "detail",
            "détail",
            "detalle",
            "dettagl",
            "szczeg",
            "узел",
            "узлы",
            "деталь",
            "детали",
            "详图",
            "詳細図",
            "상세",
        ),
    ),
    (
        PLAN,
        (
            "floor plan",
            "plan",
            "grundriss",
            "grundriß",
            "erdgeschoss",
            "obergeschoss",
            "untergeschoss",
            "planta",
            "pianta",
            "rzut",
            "план",
            "plattegrond",
            "půdorys",
            "pôdorys",
            "kat planı",
            "alaplan",
            "平面",
            "평면",
        ),
    ),
)

# A word on these marks the line as pointing elsewhere rather than naming this sheet.
_REFERENCE_WORDS = re.compile(
    r"(?<!\w)(?:see|refer|ref|key|note|notes|typ|typical of|as per|siehe|voir|ver|vedi|см)(?!\w)", re.IGNORECASE
)
_TITLE_LABEL = re.compile(
    r"(?<!\w)(?:title|drawing|sheet\s*name|titel|bezeichnung|planinhalt|titre|título|titolo|tytuł|название|наименование)"
    r"(?!\w)\s*:?\s*$",
    re.IGNORECASE,
)
_NO_WORD_START = re.compile(r"^[぀-ヿ㐀-鿿가-힯]")
_MAX_TITLE_WORDS = 8
# Share of the page, from the right and from the bottom, a title block keeps to.
_BLOCK_RIGHT = 0.3
_BLOCK_BOTTOM = 0.2

Word = tuple[float, float, float, float, str]


@dataclass
class SheetVerdict:
    """The kind of a sheet, the line that said so and how strongly it did."""

    kind: str = UNKNOWN
    title: str = ""
    weight: float = 0.0
    # Said by the title block rather than by a caption somewhere on the drawing. An inset
    # section on a plan has its caption too, so only this line can overrule the geometry.
    from_title_block: bool = False


def _ends_well(stem: str, text: str, end: int) -> bool:
    """Stems take endings, except that "plan" is also how plant, plane and planning begin."""
    if stem != "plan":
        return True
    rest = text[end : end + 2]
    return not rest[:1].isalpha() or (rest[0] == "s" and not rest[1:].isalpha())


def _kind_of(line: str) -> str | None:
    text = line.casefold()
    for kind, stems in _VOCAB:
        for stem in stems:
            pos = text.find(stem)
            while pos >= 0:
                # Scripts written without spaces have no word start to look for.
                starts = pos == 0 or _NO_WORD_START.match(stem) or not text[pos - 1].isalpha()
                if starts and _ends_well(stem, text, pos + len(stem)):
                    return kind
                pos = text.find(stem, pos + 1)
    return None


def text_lines(words: list[Word]) -> list[list[Word]]:
    """Words joined into printed lines: same baseline, gap within a few letter heights."""
    out: list[list[Word]] = []
    open_lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        h = max(1.0, w[3] - w[1])
        for ln in open_lines:
            last = ln[-1]
            if abs(last[3] - w[3]) <= 0.25 * h and -h <= w[0] - last[2] <= 2.5 * h:
                ln.append(w)
                break
        else:
            line = [w]
            open_lines.append(line)
            out.append(line)
        open_lines = [ln for ln in open_lines if ln[-1][3] >= w[1] - 2.0 * h][-40:]
    for ln in out:
        ln.sort(key=lambda w: w[0])
    return out


def classify(words: list[Word], page_w: float, page_h: float) -> SheetVerdict:
    """The kind of the sheet from its printed lines; ``unknown`` when no line names one."""
    if not words or page_w <= 0 or page_h <= 0:
        return SheetVerdict()
    lines = text_lines(words)
    heights = sorted(max(w[3] - w[1] for w in ln) for ln in lines)
    typical = heights[len(heights) // 2] or 1.0
    above: dict[int, str] = {}
    ordered = sorted(range(len(lines)), key=lambda i: lines[i][0][1])
    for pos, i in enumerate(ordered):
        ln = lines[i]
        for j in ordered[max(0, pos - 6) : pos]:
            up = lines[j]
            if abs(up[0][0] - ln[0][0]) <= 0.02 * page_w and ln[0][1] - up[0][3] <= 3.0 * (ln[0][3] - ln[0][1]):
                above[i] = " ".join(w[4] for w in up)
    best = SheetVerdict()
    for i, ln in enumerate(lines):
        text = " ".join(w[4] for w in ln)
        # Scale notes and revision columns often share a printed line with the title.
        n_words = sum(1 for w in ln if any(c.isalpha() for c in w[4]))
        if not n_words or n_words > _MAX_TITLE_WORDS:
            continue
        kind = _kind_of(text)
        if kind is None or _REFERENCE_WORDS.search(text):
            continue
        height = max(w[3] - w[1] for w in ln)
        weight = height / typical
        x_mid = 0.5 * (ln[0][0] + ln[-1][2])
        y_mid = 0.5 * (ln[0][1] + ln[0][3])
        in_corner = x_mid >= (1.0 - _BLOCK_RIGHT) * page_w and y_mid >= (1.0 - _BLOCK_BOTTOM) * page_h
        labelled = i in above and bool(_TITLE_LABEL.search(above[i]))
        from_block = in_corner or labelled
        if (from_block, weight) > (best.from_title_block, best.weight):
            best = SheetVerdict(kind, text, weight, from_block)
    return best
