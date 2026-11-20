"""Deterministic reading of project text: numbers, labelled values, quote anchoring.

Pure Python, no ERP imports, no model. Every candidate carries the verbatim text it was read from,
so a citation can always be re-found on its page.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .brief_fields import FIELDS, FieldError, coerce

MAX_QUOTE = 1000
FT_M = 0.3048
SQFT_M2 = 0.09290304


@dataclass
class Candidate:
    pointer: str
    value: Any
    document_id: str | None
    page: int
    quote: str
    kind: str  # provenance source kind
    origin: str  # "rule:<name>" | "model"
    region: list[float] | None = None
    note: str | None = None
    alternatives: list[Any] = field(default_factory=list)  # set when the number format was ambiguous


# ── numbers ──────────────────────────────────────────────────────────────────

NUM = r"\d{1,3}(?:[  '’ .,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
_NUM_RE = re.compile(NUM)
_WORDS = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"],
    "de": ["null", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf"],
    "ru": [
        "ноль",
        "один",
        "два",
        "три",
        "четыре",
        "пять",
        "шесть",
        "семь",
        "восемь",
        "девять",
        "десять",
        "одиннадцать",
        "двенадцать",
    ],
}
_WORD_NUM = {w: i for lang in _WORDS.values() for i, w in enumerate(lang)}
_WORD_NUM.update({"eine": 1, "einen": 1, "einem": 1, "eins": 1, "одна": 1, "одно": 1, "две": 2, "первый": 1})
_WORD_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, _WORD_NUM), key=len, reverse=True)) + r")\w*\b", re.I)

# exact stop words, and stems marked with "*" that match by prefix
_LANG_WORDS = {
    "de": ("und", "der", "die", "das", "mit", "nicht", "für", "geschoss*", "gebäude*", "wohn*", "fläche*"),
    "en": ("the", "and", "with", "for", "not", "of", "building*", "floor*", "area*", "storey*"),
    "ru": ("и", "на", "для", "не", "с", "здани*", "этаж*", "площад*", "жил*", "общ*", "бюджет*"),
    "fr": ("le", "la", "les", "des", "et", "avec", "pour", "bâtiment*", "étage*", "surface*"),
    "es": ("el", "los", "las", "con", "para", "de", "y", "edificio*", "planta*", "superficie*"),
}
_DECIMAL_COMMA = {"de", "ru", "fr", "es"}


def detect_language(text: str) -> str | None:
    """Coarse language of a text from stop-word hits; ``None`` when no language clearly wins."""
    tokens = re.findall(r"[^\W\d_]+", text.lower())
    if len(tokens) < 8:
        return None
    sample = tokens[:4000]
    scores = {}
    for lang, words in _LANG_WORDS.items():
        exact = {w for w in words if not w.endswith("*")}
        stems = tuple(w[:-1] for w in words if w.endswith("*"))
        scores[lang] = sum(1 for t in sample if t in exact or t.startswith(stems))
    best = sorted(scores.items(), key=lambda kv: -kv[1])
    if best[0][1] < 3 or (len(best) > 1 and best[0][1] < best[1][1] * 1.3):
        return None
    return best[0][0]


def decimal_hint(lang: str | None) -> str | None:
    if lang is None:
        return None
    return "," if lang in _DECIMAL_COMMA else "."


def parse_number(raw: str, hint: str | None = None) -> tuple[float, list[float]]:
    """``(value, alternatives)``. ``alternatives`` lists the other readings when a lone separator
    followed by three digits could be a thousands mark or a decimal mark and ``hint`` ('.' or ',')
    does not settle it."""
    s = raw.strip().replace(" ", " ").replace(" ", " ").replace("’", "'")
    if " " in s or "'" in s:
        s = s.replace(" ", "").replace("'", "")
    seps = [c for c in s if c in ".,"]
    if not seps:
        return float(s), []
    if len(set(seps)) == 2:
        dec = s[max(s.rfind("."), s.rfind(","))]
        thou = "," if dec == "." else "."
        return float(s.replace(thou, "").replace(dec, ".")), []
    sep = seps[0]
    if len(seps) > 1:
        parts = s.split(sep)
        if all(len(p) == 3 for p in parts[1:]):
            return float("".join(parts)), []
        raise ValueError(f"not a number: {raw!r}")
    head, tail = s.split(sep)
    as_decimal = float(f"{head}.{tail}")
    if len(tail) != 3 or not head or head == "0" or len(head) > 3:
        if len(tail) == 3 and len(head) > 3:
            raise ValueError(f"not a number: {raw!r}")
        return as_decimal, []
    as_thousands = float(head + tail)
    if hint == sep:
        return as_decimal, []
    if hint is not None:
        return as_thousands, []
    return as_thousands, [as_decimal]


def numbers_in(text: str) -> list[float]:
    """Every number in ``text`` under both readings of an ambiguous separator, plus number words."""
    found: list[float] = []
    for m in _NUM_RE.finditer(text):
        try:
            value, alt = parse_number(m.group(0))
        except ValueError:
            continue
        found.append(value)
        found.extend(alt)
        # "1.5" read as thousands is 15 only with a three-digit tail, handled above
    for m in _WORD_RE.finditer(text):
        found.append(float(_WORD_NUM[m.group(1).lower()]))
    return found


_FACTORS = {
    "m": (1.0, FT_M),
    "m2": (1.0, SQFT_M2),
    "ratio": (1.0, 0.01),
    "deg": (1.0,),
    None: (1.0, 1e3, 1e6, 1e9),
}


def value_supported(pointer: str, value: Any, quote: str) -> bool:
    """A numeric value must be derivable from a number written in its quote (allowed: unit conversion,
    percent, thousand/million multipliers for money). Non-numeric values are not checked here."""
    spec = FIELDS.get(pointer)
    if spec is None or spec.kind not in ("integer", "number"):
        return True
    factors = _FACTORS.get(spec.unit if spec.unit in _FACTORS else None, (1.0,))
    if pointer == "/budget/amount":
        factors = _FACTORS[None]
    for n in numbers_in(quote):
        for f in factors:
            if abs(n * f - value) <= max(1e-9, abs(value) * 0.005):
                return True
    return False


# ── anchoring ────────────────────────────────────────────────────────────────

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_QUOTES = dict.fromkeys(map(ord, "“”„«»″"), '"')
_APOS = dict.fromkeys(map(ord, "‘’′`´"), "'")


def _norm_chars(text: str) -> tuple[str, list[int]]:
    """Casefolded text with whitespace runs collapsed, and the original index of every kept char."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch == "­":
            continue
        ch = unicodedata.normalize("NFKC", ch)
        ch = ch.translate(_DASHES).translate(_QUOTES).translate(_APOS)
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        prev_space = False
        for c in ch.casefold():
            out.append(c)
            idx.append(i)
    return "".join(out), idx


def anchor_quote(pages: list[str], quote: str, page_hint: int | None = None) -> tuple[int, str] | None:
    """Find ``quote`` in the document pages (1-based). Returns ``(page, verbatim text from the page)``
    or ``None``. The hinted page is tried first; a quote found only elsewhere moves the citation there."""
    if not isinstance(quote, str) or len(quote.strip()) < 3 or "…" in quote or "..." in quote:
        return None
    nq, _ = _norm_chars(quote.strip())
    nq = nq.strip()
    if len(nq) < 3:
        return None
    order = list(range(len(pages)))
    if page_hint is not None and 1 <= page_hint <= len(pages):
        order.remove(page_hint - 1)
        order.insert(0, page_hint - 1)
    for p in order:
        norm, idx = _norm_chars(pages[p])
        at = norm.find(nq)
        if at >= 0:
            start = idx[at]
            end = idx[at + len(nq) - 1] + 1
            return p + 1, " ".join(pages[p][start:end].split())[:MAX_QUOTE]
    return None


# ── language-aware labelled rules ────────────────────────────────────────────

_SEP = r"(?:[ \t]*[:=|\-–—][ \t]*|[ \t]+)(?:(?:ca|circa|approx|about|ок|около|rund|etwa|environ|aprox|von|of|max|min)\.?[ \t]*)?"
_AREA = r"(?:m\s?²|m\s?2|m\^2|㎡|qm|sqm|sq\.?\s?m|кв\.?\s?м|м\s?²|м2|sq\.?\s?ft|sf|ft²)(?![\w²])"
_LEN = r"(?:m|м|metres?|meters?|ft|feet|′)(?![\w²])"
_INT = r"(?<![\d.,])\d{1,3}(?![\d]|[.,]\d)"
_FLOOR_WORDS = (
    r"(?:Vollgeschoss\w*|Obergeschoss\w*|Geschoss(?!h[oö]he|fl[aä]che)\w*|Etagen?|stor(?:e)?ys?|stories|floors?|levels?|"
    r"этаж\w*|étages?|plantas?)"
)
_BELOW = (
    r"(?:Untergeschoss\w*|Kellergeschoss\w*|basement(?:\s+(?:levels?|floors?|storeys?|stories))?|"
    r"подземн\w+\s+этаж\w*|sous-sols?|s[oó]tanos?)"
)
_PARKING = (
    r"(?:Pkw-|PKW-|Kfz-)?Stellpl[aä]tze?|(?:car\s+)?parking\s+(?:spaces|places|bays|stalls)|машино-?мест\w*|"
    r"парковочн\w+\s+мест\w*|places?\s+de\s+stationnement|plazas?\s+de\s+(?:aparcamiento|garaje|estacionamiento)"
)
_MULT = r"(?:Mio\.?|Millionen|Million|million|mln\.?|млн\.?|Mrd\.?|billion|млрд\.?|Tsd\.?|тыс\.?|k|M)"
_CUR = r"(?:€|EUR|Euro|£|GBP|US\s?\$|USD|R\$|BRL|\$|₽|руб\w*|RUB|₴|UAH|грн|RMB|CNY|¥|元|₹|INR|Rs\.?)"
_CURRENCY = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "usd": "USD",
    "us$": "USD",
    "us $": "USD",
    "r$": "BRL",
    "brl": "BRL",
    "₽": "RUB",
    "rub": "RUB",
    "руб": "RUB",
    "₴": "UAH",
    "uah": "UAH",
    "грн": "UAH",
    "rmb": "CNY",
    "cny": "CNY",
    "元": "CNY",
    "₹": "INR",
    "inr": "INR",
    "rs": "INR",
    "rs.": "INR",
}
_MULT_VAL = {
    "mio": 1e6,
    "millionen": 1e6,
    "million": 1e6,
    "mln": 1e6,
    "млн": 1e6,
    "m": 1e6,
    "mrd": 1e9,
    "billion": 1e9,
    "млрд": 1e9,
    "tsd": 1e3,
    "тыс": 1e3,
    "k": 1e3,
}

_FLAGS = re.IGNORECASE | re.UNICODE


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, _FLAGS)


@dataclass(frozen=True)
class _Rule:
    name: str
    pointer: str
    rx: re.Pattern[str]
    kind: str  # int | num | area | length | ratio


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "gfa",
        "/massing/gross_floor_area_m2",
        _rx(
            r"\b(?:BGF|Brutto-?\s?(?:grund|geschoss)fl[aä]che|gross\s+(?:floor|internal)\s+area|GFA|gross\s+area|"
            r"общая\s+площадь(?:\s+здания)?|площадь\s+здания|surface\s+de\s+plancher|superficie\s+construida)\b"
            + _SEP
            + rf"(?P<n>{NUM})[ \t]*{_AREA}"
        ),
        "area",
    ),
    _Rule(
        "max_floors",
        "/site/max_floors",
        _rx(
            rf"\b(?:max(?:imale?)?\.?[ \t]*(?:zul[aä]ssige\s+)?Geschosse|zul[aä]ssige\s+(?:Zahl\s+der\s+)?Vollgeschosse|"
            rf"maximum\s+(?:of\s+)?(?:number\s+of\s+)?(?:storeys|stories|floors)|max\.?[ \t]*(?:storeys|stories|floors)|"
            rf"максимальн\w+\s+этажность|этажность\s+не\s+более)"
            rf"{_SEP}(?P<n>{_INT})"
        ),
        "int",
    ),
    _Rule(
        "floors_below",
        "/massing/floors_below",
        _rx(
            rf"(?:(?P<n>{_INT})[ \t]*[-–]?[ \t]*{_BELOW}|{_BELOW}(?:[ \t]*[:=|][ \t]*|\t[ \t]*| {(2,)})(?P<n2>{_INT}))"
        ),
        "int",
    ),
    _Rule(
        "floors_above",
        "/massing/floors_above",
        _rx(
            rf"(?:(?<![Gg]round )(?<![Bb]asement )(?P<n>{_INT})(?![.\s]*(?:st|nd|rd|th)\b)(?!\.\s)[ \t]*[-–]?[ \t]*"
            rf"(?:oberirdische\s+|above-ground\s+|надземных\s+)?{_FLOOR_WORDS}"
            rf"|\b(?:Anzahl\s+(?:der\s+)?(?:Voll)?geschosse|Geschosse|Vollgeschosse|Geschosszahl|"
            rf"(?:number\s+of\s+)?(?:floors|storeys|stories)(?:\s+above\s+ground)?|этажность|количество\s+этажей|"
            rf"nombre\s+d['’]étages)(?:[ \t]*[:=|][ \t]*|\t[ \t]*| {(2,)})(?P<n2>{_INT}))"
        ),
        "int",
    ),
    _Rule(
        "ground_floor_height",
        "/massing/ground_floor_height_m",
        _rx(
            r"\b(?:Erdgeschossh[oö]he|EG-H[oö]he|ground\s+floor\s+height|высота\s+(?:первого|1-го)\s+этажа)\b"
            rf"{_SEP}(?P<n>{NUM})[ \t]*{_LEN}"
        ),
        "length",
    ),
    _Rule(
        "floor_height",
        "/massing/floor_height_m",
        _rx(
            r"\b(?:Geschossh[oö]he|Stockwerksh[oö]he|storey\s+height|story\s+height|floor[- ]to[- ]floor(?:\s+height)?|"
            r"floor\s+height|высота\s+этажа|hauteur\s+d['’]étage)\b"
            rf"{_SEP}(?P<n>{NUM})[ \t]*{_LEN}"
        ),
        "length",
    ),
    _Rule(
        "max_height",
        "/site/max_height_m",
        _rx(
            r"\b(?:max(?:imale?)?\.?[ \t]*(?:zul[aä]ssige\s+)?(?:Geb[aä]udeh[oö]he|Bauh[oö]he|Firsth[oö]he|Traufh[oö]he)|"
            r"zul[aä]ssige\s+(?:Geb[aä]ude|Bau|First)h[oö]he|maximum\s+(?:building\s+)?height|"
            r"max\.?[ \t]*(?:building\s+)?height|height\s+limit|предельная\s+высота|максимальная\s+высота(?:\s+здания)?)"
            rf"{_SEP}(?P<n>{NUM})[ \t]*{_LEN}"
        ),
        "length",
    ),
    _Rule(
        "far",
        "/site/floor_area_ratio_max",
        _rx(
            r"\b(?:GFZ|Geschossfl[aä]chenzahl|floor\s+area\s+ratio|FAR|plot\s+ratio)\b"
            rf"{_SEP}(?P<n>\d+(?:[.,]\d+)?)(?![ \t]*%)"
        ),
        "ratio",
    ),
    _Rule(
        "coverage",
        "/site/site_coverage_max",
        _rx(
            r"\b(?:GRZ|Grundfl[aä]chenzahl|site\s+coverage|plot\s+coverage|lot\s+coverage|коэффициент\s+застройки)\b"
            rf"{_SEP}(?P<n>\d+(?:[.,]\d+)?)(?P<pct>[ \t]*%)?"
        ),
        "ratio",
    ),
    _Rule(
        "parking",
        "/programme/parking_spaces",
        _rx(
            rf"(?:(?P<n>{_INT})[ \t]*(?:{_PARKING})|\b(?:{_PARKING})(?:[ \t]*[:=|][ \t]*|\t[ \t]*| {(2,)})(?P<n2>{_INT}))"
        ),
        "int",
    ),
    _Rule(
        "footprint",
        "/massing/footprint",
        _rx(
            r"\b(?:Grundriss|Geb[aä]udegrundriss|footprint|Abmessungen|dimensions|габариты|в\s+плане)\b[^\n]{0,30}?"
            rf"(?P<w>{NUM})[ \t]*{_LEN}?[ \t]*[x×х*][ \t]*(?P<d>{NUM})[ \t]*{_LEN}"
        ),
        "pair",
    ),
    _Rule(
        "budget",
        "/budget/amount",
        _rx(
            r"\b(?:Budget|Baukosten|Gesamtkosten|Investitionsvolumen|Bausumme|Kostenrahmen|"
            r"(?:construction|project|total)\s+(?:cost|budget)s?|бюджет|стоимость\s+строительства|"
            r"сметная\s+стоимость|co[uû]t\s+(?:de\s+construction|total)|presupuesto)\b"
            rf"{_SEP}(?:(?P<c1>{_CUR})[ \t]*)?(?P<n>{NUM})[ \t]*(?P<m>{_MULT})?(?:[ \t]*(?P<c2>{_CUR}))?"
            r"(?P<vat>[^\n]{0,40}?(?:inkl\.?|zzgl\.?|incl\.?|excl\.?|plus|ohne|netto|brutto|with|without|с|без)[ \t]*"
            r"(?:MwSt\.?|USt\.?|VAT|НДС))?"
        ),
        "budget",
    ),
    _Rule(
        "lift",
        "/massing/lift",
        _rx(
            r"(?P<neg>\b(?:kein(?:e|en)?|ohne|no|without|без)\s+)?"
            r"\b(?:Aufz(?:ug|üge)|Fahrst(?:uhl|ühle)|lifts?|elevators?|лифт\w*|ascenseurs?|ascensor(?:es)?)\b"
        ),
        "lift",
    ),
    _Rule(
        "address",
        "/site/address",
        _rx(
            r"\b(?:Adresse|Baugrundst[uü]ck|Standort|Bauort|Site\s+address|Address|Location|Адрес(?:\s+объекта)?)[ \t]*[:：][ \t]*"
            r"(?P<t>[^\n]{8,200})"
        ),
        "text",
    ),
)

_KEYWORDS: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (pointer, value, _rx(pat))
    for pointer, value, pat in (
        (
            "/use/category",
            "mixed_use",
            r"\b(?:Wohn-\s*und\s*Gesch[aä]ftsh(?:aus|äuser)|mixed[- ]use|смешанн\w+\s+(?:использован|застройк))",
        ),
        (
            "/use/category",
            "residential_multi",
            r"\b(?:Mehrfamilienh(?:aus|äuser)|MFH|Wohnanlage|Wohnblock|Geschosswohnungsbau|"
            r"(?:apartment|residential)\s+(?:building|block)s?|multi-?family|многоквартирн\w+|жилой\s+(?:дом|комплекс)|"
            r"immeuble\s+(?:d['’]habitation|collectif)|edificio\s+(?:de\s+viviendas|residencial))",
        ),
        (
            "/use/category",
            "residential_single",
            r"\b(?:Einfamilienh(?:aus|äuser)|EFH|single-?family|одноквартирн\w+|"
            r"maison\s+individuelle|vivienda\s+unifamiliar)",
        ),
        (
            "/use/category",
            "office",
            r"\b(?:B[uü]rogeb[aä]ude|Verwaltungsgeb[aä]ude|office\s+(?:building|block)|административн\w+\s+здани\w+|офисн\w+\s+здани\w+)",
        ),
        (
            "/use/category",
            "school",
            r"\b(?:Schulgeb[aä]ude|Grundschule|Gymnasium|school\s+building|primary\s+school|secondary\s+school|школ\w+)",
        ),
        ("/use/category", "kindergarten", r"\b(?:Kindertagesst[aä]tte|Kindergarten|Kita\b|nursery|детск\w+\s+сад\w*)"),
        ("/use/category", "hotel", r"\b(?:Hotel\w*|гостиниц\w+)"),
        (
            "/use/category",
            "healthcare",
            r"\b(?:Krankenhaus|Klinik\w*|hospital|healthcare\s+facility|больниц\w+|поликлиник\w+)",
        ),
        ("/use/category", "warehouse", r"\b(?:Lagerhalle|Logistikzentrum|Lagergeb[aä]ude|warehouse|склад\w*)"),
        (
            "/use/category",
            "industrial",
            r"\b(?:Produktionshalle|Werkhalle|industrial\s+(?:building|facility)|производственн\w+\s+здани\w+)",
        ),
        (
            "/use/category",
            "retail",
            r"\b(?:Einkaufszentrum|Supermarkt|Einzelhandel\w*|shopping\s+(?:centre|center|mall)|retail\s+(?:building|unit)s?|торговый\s+центр)",
        ),
        ("/use/category", "parking", r"\b(?:Parkhaus|parking\s+(?:garage|structure)|многоуровневый\s+паркинг)"),
        ("/structure/system", "masonry", r"\b(?:Mauerwerk\w*|masonry|кирпичн\w+\s+(?:стен|здани))"),
        (
            "/structure/system",
            "timber",
            r"\b(?:Holzbau|Holzrahmenbau|Brettsperrholz|CLT\b|timber\s+(?:frame|construction)|деревянн\w+\s+каркас)",
        ),
        ("/structure/system", "steel", r"\b(?:Stahlbau|Stahlskelett|steel\s+frame|стальн\w+\s+каркас)"),
        (
            "/structure/system",
            "concrete_frame",
            r"\b(?:Stahlbetonskelett|Skelettbau|concrete\s+frame|монолитн\w+\s+каркас)",
        ),
        (
            "/structure/system",
            "concrete_walls",
            r"\b(?:Stahlbetonw[aä]nde|Schottenbauweise|(?:concrete|shear)\s+wall\s+(?:system|construction)|"
            r"монолитн\w+\s+несущие\s+стены)",
        ),
        (
            "/structure/foundation",
            "strip",
            r"\b(?:Streifenfundament\w*|strip\s+(?:foundation|footing)s?|ленточн\w+\s+фундамент)",
        ),
        (
            "/structure/foundation",
            "raft",
            r"\b(?:Bodenplatte|Fundamentplatte|raft\s+foundation|mat\s+foundation|плитн\w+\s+фундамент)",
        ),
        (
            "/structure/foundation",
            "piles",
            r"\b(?:Pfahlgr[uü]ndung|Bohrpf[aä]hle|pile\s+foundation|bored\s+piles|свайн\w+\s+фундамент)",
        ),
        ("/envelope/roof", "flat", r"\b(?:Flachdach|flat\s+roof|плоская\s+кровля|toit[- ]terrasse|cubierta\s+plana)"),
        ("/envelope/roof", "gable", r"\b(?:Satteldach|gable\s+roof|двускатная\s+крыша)"),
        ("/envelope/roof", "hip", r"\b(?:Walmdach|hip(?:ped)?\s+roof|вальмовая\s+крыша)"),
        ("/envelope/roof", "shed", r"\b(?:Pultdach|shed\s+roof|односкатная\s+крыша)"),
    )
)

_COUNTRY_WORDS = (
    ("DE", r"Deutschland|Germany|Allemagne|Alemania|Германия"),
    ("US", r"United\s+States|U\.?S\.?A\.?|Vereinigte\s+Staaten|США"),
    ("GB", r"United\s+Kingdom|Great\s+Britain|England|Vereinigtes\s+K[oö]nigreich|Royaume-Uni|Великобритания"),
    ("RU", r"Russia|Russland|Россия|Российская\s+Федерация"),
    ("FR", r"France|Frankreich|Франция"),
    ("ES", r"Spain|Spanien|España|Испания"),
    ("UA", r"Ukraine|Україна|Украина"),
    ("BR", r"Brazil|Brasil|Brasilien|Бразилия"),
    ("CN", r"China|Китай"),
    ("IN", r"India|Indien|Индия"),
)
_COUNTRY_RX = tuple((code, _rx(rf"\b(?:{pat})\b")) for code, pat in _COUNTRY_WORDS)
_BICYCLE = _rx(r"(?:fahrrad|bike|bicycle|cycle|велосипед|motorrad|moto)")


def _clean(text: str) -> str:
    return " ".join(text.split())[:MAX_QUOTE]


def _hit(rule: _Rule, m: re.Match[str], hint: str | None, page: int, doc_id: str | None, kind: str) -> list[Candidate]:
    quote = _clean(m.group(0))
    mk = lambda pointer, value, alt=(), note=None: Candidate(  # noqa: E731
        pointer, value, doc_id, page, quote, kind, f"rule:{rule.name}", alternatives=list(alt), note=note
    )
    if rule.kind == "text":
        return [mk(rule.pointer, _clean(m.group("t")))]
    if rule.kind == "lift":
        return [mk(rule.pointer, m.group("neg") is None)]
    if rule.kind == "pair":
        w, wa = parse_number(m.group("w"), hint)
        d, da = parse_number(m.group("d"), hint)
        if wa or da:
            return []
        return [mk("/massing/footprint/width_m", w), mk("/massing/footprint/depth_m", d)]
    if rule.kind == "budget":
        value, alt = parse_number(m.group("n"), hint)
        mult = (m.group("m") or "").strip(".").lower()
        factor = _MULT_VAL.get(mult, 1.0) if mult else 1.0
        # a bare "M" or "k" next to a plain figure is only a multiplier when a currency follows
        out = [mk(rule.pointer, value * factor, [a * factor for a in alt])]
        cur = (m.group("c1") or m.group("c2") or "").strip().lower().replace("  ", " ")
        code = _CURRENCY.get(cur) or (_CURRENCY.get(cur.rstrip(".")) if cur else None)
        if cur.startswith("руб"):
            code = "RUB"
        if code:
            out.append(mk("/budget/currency", code))
        vat = (m.group("vat") or "").lower()
        if vat:
            neg = re.search(r"zzgl|excl|plus|ohne|netto|without|без", vat)
            out.append(mk("/budget/includes_vat", neg is None))
        return out
    raw = m.group("n") if "n" in m.groupdict() and m.group("n") else m.groupdict().get("n2")
    if raw is None:
        return []
    value, alt = parse_number(raw, hint)
    if rule.kind == "int":
        if value != int(value):
            return []
        if rule.name == "parking" and _BICYCLE.search(m.string[max(0, m.start() - 14) : m.end()]):
            return []
        return [mk(rule.pointer, int(value))]
    if rule.kind == "area":
        if re.search(r"sq\.?\s?ft|sf|ft²", m.group(0)[-8:], re.I):
            return [mk(rule.pointer, round(value * SQFT_M2, 2), [round(a * SQFT_M2, 2) for a in alt])]
        return [mk(rule.pointer, value, alt)]
    if rule.kind == "length":
        feet = re.search(r"(?:ft|feet|′)\s*$", m.group(0), re.I)
        f = FT_M if feet else 1.0
        return [mk(rule.pointer, round(value * f, 3), [round(a * f, 3) for a in alt])]
    if rule.kind == "ratio":
        value, alt = (float(raw.replace(",", ".")), [])
        if m.groupdict().get("pct"):
            value /= 100
        return [mk(rule.pointer, value)]
    return []


def extract_candidates(
    pages: list[str], *, document_id: str | None, kind: str = "document", language: str | None = None
) -> list[Candidate]:
    """All rule-based candidates of one document. Values that fail their field check are dropped
    here; the caller sees only the ones that fit (the model path reports its rejects separately)."""
    if language is None:
        language = detect_language("\n".join(pages))
    hint = decimal_hint(language)
    out: list[Candidate] = []
    for number, text in enumerate(pages, start=1):
        taken: list[tuple[int, int]] = []
        for rule in _RULES:
            for m in rule.rx.finditer(text):
                if any(a < m.end() and m.start() < b for a, b in taken) and rule.name in ("floors_above", "parking"):
                    continue
                try:
                    cands = _hit(rule, m, hint, number, document_id, kind)
                except (ValueError, TypeError):
                    continue
                if rule.name in ("max_floors", "floors_below", "ground_floor_height", "floor_height", "max_height"):
                    taken.append((m.start(), m.end()))
                good = []
                for c in cands:
                    try:
                        c.value = coerce(c.pointer, c.value)
                        c.alternatives = [a for a in c.alternatives if _fits(c.pointer, a)]
                    except FieldError:
                        continue
                    good.append(c)
                out.extend(good)
        for pointer, value, rx in _KEYWORDS:
            m = rx.search(text)
            if m:
                out.append(Candidate(pointer, value, document_id, number, _clean(m.group(0)), kind, "rule:keyword"))
        out.extend(_country_candidates(text, number, document_id, kind))
    return out


def _fits(pointer: str, value: Any) -> bool:
    try:
        coerce(pointer, value)
        return True
    except FieldError:
        return False


_ADDRESS_LINE = re.compile(
    r"^[^\n]*\b(?:Adresse|Standort|Bauort|Projektort|Site\s+address|Address|Location|Адрес|Объект)\b[^\n]*$",
    _FLAGS | re.M,
)


def _country_candidates(text: str, page: int, doc_id: str | None, kind: str) -> list[Candidate]:
    """A country counts only when it is named on a line that gives the project's address or location."""
    out = []
    for line in _ADDRESS_LINE.finditer(text):
        for code, rx in _COUNTRY_RX:
            if rx.search(line.group(0)):
                out.append(Candidate("/country", code, doc_id, page, _clean(line.group(0)), kind, "rule:country"))
    return out
