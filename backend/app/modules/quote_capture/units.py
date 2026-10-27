# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ normalisation for quote lines (``m²`` = ``m2`` = ``qm``, ``lfm`` = ``lm``, ``Stk`` = ``pcs``).

Canonical codes follow the bill of quantities (``m``, ``m2``, ``m3``, ``lm``, ``pcs``,
``kg``, ``t``, ``h``, ``lsum`` ...). Some spellings mean different things per
language: ``ml`` is a linear metre in a French quote and a millilitre elsewhere,
``u`` is a piece in French and Spanish. Those are resolved by locale.
"""

from __future__ import annotations

_SUPER = str.maketrans({"²": "2", "³": "3"})

_ALIASES: dict[str, str] = {
    # length
    "m": "m", "lfm": "lm", "lfdm": "lm", "lm": "lm", "lin m": "lm", "lin.m": "lm", "rm": "lm", "mtr": "m",
    "meter": "m", "metre": "m", "mètre": "m", "m.l.": "lm", "мп": "lm", "пм": "lm", "м": "m",
    "متر": "m", "م.ط": "lm", "متر طولي": "lm", "lf": "lf", "ft": "ft",
    # area
    "m2": "m2", "qm": "m2", "sqm": "m2", "sq m": "m2", "sq.m": "m2", "m^2": "m2", "м2": "m2", "кв.м": "m2",
    "م2": "m2", "متر مربع": "m2", "sf": "sf", "sq ft": "sf", "sqft": "sf",
    # volume
    "m3": "m3", "cbm": "m3", "cum": "m3", "cu m": "m3", "m^3": "m3", "м3": "m3", "куб.м": "m3", "م3": "m3",
    "متر مكعب": "m3", "cy": "cy",
    # pieces
    "pcs": "pcs", "pc": "pcs", "pce": "pcs", "piece": "pcs", "pieces": "pcs", "ea": "pcs", "each": "pcs",
    "no": "pcs", "nr": "pcs", "stk": "pcs", "st": "pcs", "stück": "pcs", "stck": "pcs", "pièce": "pcs",
    "pièces": "pcs", "unité": "pcs", "шт": "pcs", "قطعة": "pcs", "عدد": "pcs", "حبة": "pcs",
    "set": "set", "satz": "set", "jeu": "set", "ens": "set",
    # lump sum
    "ls": "lsum", "lsum": "lsum", "l.s": "lsum", "lump sum": "lsum", "psch": "lsum", "pschl": "lsum",
    "pauschal": "lsum", "pau": "lsum", "forfait": "lsum", "fft": "lsum", "ff": "lsum", "مقطوع": "lsum",
    # mass, time, liquids
    "kg": "kg", "кг": "kg", "كغ": "kg", "كجم": "kg", "t": "t", "to": "t", "tonne": "t", "tonnes": "t",
    "т": "t", "طن": "t", "h": "h", "hr": "h", "hrs": "h", "std": "h", "heure": "h", "ч": "h", "ساعة": "h",
    "day": "day", "days": "day", "tag": "day", "jour": "day", "يوم": "day",
    "l": "l", "ltr": "l", "liter": "l", "litre": "l",
}  # fmt: skip

_BY_LANG: dict[str, dict[str, str]] = {
    "fr": {"ml": "lm", "u": "pcs", "m.l": "lm"},
    "es": {"ml": "lm", "u": "pcs", "ud": "pcs", "uds": "pcs", "pa": "lsum"},
    "it": {"ml": "lm", "cad": "pcs"},
    "pt": {"ml": "lm", "un": "pcs", "vb": "lsum"},
    "ar": {"م": "m", "م.ط": "lm"},
}


def _key(raw: str) -> str:
    return " ".join(raw.translate(_SUPER).strip().casefold().split())


def _lookup(raw: str, locale: str | None) -> str | None:
    key = _key(raw)
    by_lang = _BY_LANG.get((locale or "").replace("_", "-").split("-")[0].lower(), {})
    for candidate in (key, key.rstrip(".")):
        if candidate in by_lang:
            return by_lang[candidate]
        if candidate in _ALIASES:
            return _ALIASES[candidate]
    return None


def normalise_unit(raw: str | None, locale: str | None = None) -> str:
    """Return the canonical unit code, or the cleaned raw spelling when unknown."""
    if not raw:
        return ""
    return _lookup(raw, locale) or _key(raw)


def is_known_unit(raw: str | None, locale: str | None = None) -> bool:
    return bool(raw) and _lookup(raw, locale) is not None


def same_unit(a: str | None, b: str | None, locale: str | None = None) -> bool:
    """True when two spellings name the same unit (``m²`` and ``qm``)."""
    na, nb = normalise_unit(a, locale), normalise_unit(b, locale)
    return bool(na) and na == nb
