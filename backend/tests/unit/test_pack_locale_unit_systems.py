# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A pack locale may translate a unit label. It may not re-measure it.

A pack ships locale overrides that the host merges over the core strings, so a
pack can give any key a new label. Relabelling is exactly what a locale is for
when the two names mean the same thing: ``units.sqft`` reading "sq ft" instead
of "Square foot" is an abbreviation, and the Hindi ``units.kg`` is a
translation.

Relabelling across measurement systems is a different act. The quantity on the
row does not move when the label does, so ``modules.boq.unit.m3`` rendered as
"cu yd" states a volume that is wrong by a factor of 1.308, and ``.kg`` shown
as "lb" is wrong by 2.205. A user reading a priced bill has no way to see it:
every number looks right for the unit printed beside it. Imperial output is a
real feature, and it needs the conversion, not the label.

So the rule is a correspondence, not a vocabulary: the measurement system of
the unit the KEY names must be the system of the unit the VALUE names. Keying
off the value alone would be wrong in both directions - ``units.ton_us``
reading "ton" is honest, while ``modules.boq.unit.t`` reading "ton" is the
1.102 error - and keying off the key alone says nothing at all.

Anything the two classifiers cannot place is passed, deliberately. A composite
trade unit (``m3_concrete``), a locale-native token (``lfm``, ``Stk``) and a
value written in a non-Latin script all fall through, because a gate that
guesses at those would fire on the packs that are already honest and be turned
off. Pure stdlib and JSON on disk, so this runs without a database.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

# backend/tests/unit/<this file> -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKS_DIR = _REPO_ROOT / "packs"

# Keys whose trailing segment names a unit of measurement. Both namespaces are
# covered: ``units.*`` is what the unit pickers resolve today, and
# ``modules.boq.unit.*`` is the namespace the packs write into.
_UNIT_KEY_PREFIXES = ("units.", "modules.boq.unit.")

_METRIC_CODES = frozenset(
    {
        "m",
        "m2",
        "m3",
        "lm",
        "lfm",
        "km",
        "cm",
        "mm",
        "kg",
        "g",
        "t",
        "l",
        "ha",
        "sqm",
        "cum",
        "rmt",
        "mt",
        "quintal",
        "tonne",
        "degree_c",
    }
)

_IMPERIAL_CODES = frozenset(
    {
        "ft",
        "foot",
        "feet",
        "sqft",
        "sf",
        "cuft",
        "cf",
        "lf",
        "linft",
        "yd",
        "yard",
        "sqyd",
        "sy",
        "cy",
        "cuyd",
        "inch",
        "lb",
        "pound",
        "ton",
        "ton_us",
        "gal",
        "gallon",
        "acre",
        "mile",
        "degree_f",
    }
)


def _label_rx(*tokens: str) -> re.Pattern[str]:
    """Match any of ``tokens`` as a whole word inside a label.

    Longest first so "sq ft" wins over a bare "ft", and the boundaries keep the
    short codes off ordinary prose. ``°F`` carries its own degree sign and
    cannot take a leading word boundary, so the guard is written by hand.
    """
    parts = sorted((re.escape(tok) for tok in tokens), key=len, reverse=True)
    return re.compile(r"(?<![\w°])(?:" + "|".join(parts) + r")(?![\w²³])", re.IGNORECASE)


# Value-side tokens. Bare "in" is deliberately absent: as an English word it is
# everywhere, and no honest label needs it to be readable as inches.
_METRIC_LABEL_RX = _label_rx(
    "m",
    "m2",
    "m²",
    "m3",
    "m³",
    "lm",
    "lfm",
    "km",
    "cm",
    "mm",
    "kg",
    "ha",
    "tonne",
    "tonnes",
    "metre",
    "meter",
    "litre",
    "liter",
)
_IMPERIAL_LABEL_RX = _label_rx(
    "sq ft",
    "sq. ft",
    "sqft",
    "sf",
    "cu yd",
    "cu. yd",
    "cuyd",
    "cy",
    "cu ft",
    "cu. ft",
    "cuft",
    "cf",
    "lin ft",
    "lin. ft",
    "linft",
    "lf",
    "sq yd",
    "sqyd",
    "sy",
    "ft",
    "foot",
    "feet",
    "yd",
    "yard",
    "yards",
    "inch",
    "inches",
    "lb",
    "lbs",
    "pound",
    "pounds",
    "ton",
    "tons",
    "gal",
    "gallon",
    "gallons",
    "acre",
    "acres",
    "mile",
    "miles",
)
_DEGREE_F_RX = re.compile(r"°\s*F\b")
_DEGREE_C_RX = re.compile(r"°\s*C\b")


def _system_of_code(code: str) -> str | None:
    """Classify the unit code a key names, or None when it is not a plain unit.

    The whole code is tried first so ``ton_us`` and ``degree_f`` keep their own
    reading, then the segment before the first underscore, which is what makes
    a composite trade unit like ``m3_concrete`` classify as metric rather than
    fall through unexamined.
    """
    for candidate in (code, code.split("_")[0]):
        lowered = candidate.lower()
        if lowered in _METRIC_CODES:
            return "metric"
        if lowered in _IMPERIAL_CODES:
            return "imperial"
    return None


def _system_of_label(label: str) -> str | None:
    """Classify the unit a label names, or None when it names neither clearly.

    A label carrying tokens from both systems (an equivalence such as "m³ (cu
    yd)") is deliberately unclassified: it is stating a conversion, not hiding
    one.
    """
    metric = bool(_METRIC_LABEL_RX.search(label)) or bool(_DEGREE_C_RX.search(label))
    imperial = bool(_IMPERIAL_LABEL_RX.search(label)) or bool(_DEGREE_F_RX.search(label))
    if metric == imperial:
        return None
    return "metric" if metric else "imperial"


def _walk(node: object, path: str = "") -> list[tuple[str, str]]:
    """Flatten a locale document to (dotted key, string value) pairs.

    Pack locales are written both flat and nested under a ``translation``
    object, and a scan that assumed one shape would silently read nothing from
    the other.
    """
    pairs: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                pairs.append((key if not path else f"{path}.{key}", value))
            else:
                pairs.extend(_walk(value, key if not path else f"{path}.{key}"))
    return pairs


def _locale_files() -> list[Path]:
    return sorted(_PACKS_DIR.glob("*/src/*/locales/*.json"))


def _unit_entries(doc_pairs: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Return (key, unit code, label) for every unit-namespace entry."""
    entries = []
    for key, label in doc_pairs:
        # The nested shape prefixes keys with the container name; the unit
        # namespace is recognised by suffix so both shapes land here.
        for prefix in _UNIT_KEY_PREFIXES:
            index = key.find(prefix)
            if index == -1:
                continue
            code = key[index + len(prefix) :]
            if code and "." not in code:
                entries.append((key, code, label))
            break
    return entries


def test_pack_locales_exist_to_scan() -> None:
    """A scan that reached no file is not a clean scan."""
    files = _locale_files()
    assert files, f"no pack locale files found under {_PACKS_DIR}"
    assert any(_unit_entries(_walk(json.loads(f.read_text("utf-8")))) for f in files), (
        "no unit-namespace keys found in any pack locale; the key namespaces in "
        f"{_UNIT_KEY_PREFIXES} have probably been renamed and this gate is now blind"
    )


@pytest.mark.parametrize("locale_path", _locale_files(), ids=lambda p: f"{p.parents[3].name}/{p.name}")
def test_pack_locale_never_relabels_a_unit_into_another_system(
    locale_path: Path,
) -> None:
    """No pack may print an imperial name over a metric quantity, or vice versa."""
    pairs = _walk(json.loads(locale_path.read_text("utf-8")))
    offences = []
    for key, code, label in _unit_entries(pairs):
        key_system = _system_of_code(code)
        label_system = _system_of_label(label)
        if key_system and label_system and key_system != label_system:
            offences.append(f"  {key!r} names a {key_system} unit but is labelled {label!r} ({label_system})")

    rel = locale_path.relative_to(_REPO_ROOT).as_posix()
    assert not offences, (
        f"{rel} relabels units across measurement systems:\n"
        + "\n".join(offences)
        + "\n\nThe quantity does not convert when the label does, so the row reads a "
        "false number. Give the metric key its own honest label; imperial output "
        "needs a real conversion, which a locale cannot supply."
    )
