# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The hour unit must be labelled as an hour in every backend locale.

``units.h`` is the only time-valued key in the backend catalogue, and it is the
only one where a mistranslation changes a number rather than a word. Every
other key names a dimension - a metre is a metre in any language - so a wrong
label there reads as clumsy. A wrong label here reads as a different quantity:
the value beside it is an hourly figure, so a label naming a longer period
misstates it by the length of that period.

Three locales carried such a label, and they were not three instances of one
fault. Two of them named a longer period and one named no period at all:

  * zh said 工日 and ja said 人工, the worker-day of Chinese and Japanese
    estimating practice. The convention behind them is real - CJK estimating
    does quantify labour in worker-days - and it was applied to the label
    without being applied to the number, which is what made it wrong. For
    these two a conversion factor at least exists, whether or not we want it.
  * ko said 인, which is 人, a person. That is a COUNT, not a period. It puts
    a headcount beside a rate, and no multiplier of any working day makes it
    true. A later pass that treats all three as one problem and applies a
    worker-day factor to Korean would make Korean worse, not better. 인 was
    also the only time unit ko had: ``units.h`` is the sole time-valued key in
    the catalogue, so before this fix the Korean file had no word for an hour
    at all.

The platform already has the honest way to express a worker-day: ``BASE_UNITS``
in frontend/src/features/boq/boqHelpers.ts offers ``day``, ``shift`` and ``mh``
as tokens of their own, and ``LOCALE_UNITS`` offers 工日, 人日 and 인일 beside
小时, 時間 and 시간 - so a worker-day is a unit a bill can be written in, not a
translation of the hour. Note the asymmetry there too: 工日 and 인 are both
tokens that picker offers, so those two labels collided with a different unit
the product itself sells, while 人工 is offered nowhere in the product at all.

What the label may say, from data the platform already holds:

  * ``h``, the ISO 80000-3 symbol for the hour, which is valid unchanged in
    every language and is what nine of these files already use;
  * an abbreviation of the platform's own name for the hour in that language,
    taken from ``units.h`` in frontend/src/app/locales/<locale>.ts. Danish
    ``t`` for ``Time``, German ``Std`` for ``Stunde``, Thai ``ชม.`` for
    ``ชั่วโมง`` and Czech ``hod`` for ``Hodina`` are all this shape, so the
    test reads an abbreviation as a subsequence rather than a prefix.

Two shapes of check were tried first and rejected against the data:

  * asserting the label is not a string the same locale offers as a different
    unit. da and no give ``units.t`` and ``units.h`` the same value ``t`` -
    tonne and time - so this reds on correct Danish and Norwegian;
  * a list of the three known-bad strings. That is the right answer by a
    mechanism that cannot produce a wrong one, and it stays green for ever.

Limit of this check, stated because it is not visible from a pass: the two
catalogues are its two witnesses, so a label wrong in both the same way is not
caught. It also cannot speak for a locale whose frontend name for the hour is
still the untranslated English word, because then the platform holds no name in
that language to compare against; the count of those is asserted below so the
gate cannot go quiet without saying so.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.core.i18n import LOCALES_DIR

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_LOCALES = REPO_ROOT / "frontend" / "src" / "app" / "locales"

#: ISO 80000-3 symbol for the hour. Language-independent by definition.
ISO_HOUR_SYMBOL = "h"

#: The key under test, and the English word the frontend catalogue gives it.
HOUR_KEY = "h"
ENGLISH_HOUR_NAME = "Hour"

#: Locales whose frontend name for the hour is still the English word, so the
#: platform holds nothing in that language to compare a short form against.
#: Held as a number rather than a list: a list of names would have to be edited
#: whenever a language is filled in, and the point is only that the gate has
#: not gone quiet.
MAX_UNJUDGEABLE_LOCALES = 1


def _fold(value: str) -> str:
    """Case, width and punctuation folded away, so only the letters remain."""
    folded = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^\w]", "", folded, flags=re.UNICODE)


def _abbreviates(short: str, long: str) -> bool:
    """True when ``short`` is ``long`` with letters dropped, order preserved.

    A subsequence and not a prefix: Turkish ``sa`` abbreviates ``Saat`` and
    German ``Std`` abbreviates ``Stunde`` by dropping interior letters.
    """
    remaining = iter(long)
    return all(character in remaining for character in short)


def frontend_hour_name(locale: str, frontend_dir: Path) -> str | None:
    """The platform's own name for the hour in ``locale``, or None.

    Read out of the TypeScript source rather than a build artefact, so the
    check sees what an editor of that file sees.
    """
    path = frontend_dir / f"{locale}.ts"
    if not path.exists():
        return None
    match = re.search(r'"units\.h":\s*"((?:[^"\\]|\\.)*)"', path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


@dataclass(frozen=True)
class HourLabel:
    """One locale's answer, and what vindicates it."""

    locale: str
    label: str | None
    frontend_name: str | None
    #: Which clause accepts the label, ``None`` when none does.
    clause: str | None
    #: True when the platform holds no name in this language to judge against.
    unjudgeable: bool


def verdict(label: str | None, frontend_name: str | None) -> tuple[str | None, bool]:
    """Which clause accepts ``label``, and whether it could be judged at all."""
    if not label:
        return None, False
    folded = _fold(label)
    if folded == ISO_HOUR_SYMBOL:
        return "ISO 80000-3 symbol", False
    if not frontend_name or _fold(frontend_name) == _fold(ENGLISH_HOUR_NAME):
        return None, True
    if _abbreviates(folded, _fold(frontend_name)):
        return f"abbreviates {frontend_name!r}", False
    return None, False


def audit_hour_labels(backend_dir: Path, frontend_dir: Path) -> list[HourLabel]:
    """Judge ``units.h`` in every backend locale file under ``backend_dir``."""
    audited: list[HourLabel] = []
    for path in sorted(backend_dir.glob("*.json")):
        units = json.loads(path.read_text(encoding="utf-8")).get("units", {})
        label = units.get(HOUR_KEY)
        name = frontend_hour_name(path.stem, frontend_dir)
        clause, unjudgeable = verdict(label, name)
        audited.append(HourLabel(path.stem, label, name, clause, unjudgeable))
    return audited


def test_no_locale_labels_the_hour_with_the_name_of_another_period() -> None:
    audited = audit_hour_labels(LOCALES_DIR, FRONTEND_LOCALES)

    assert audited, f"no backend locale files found under {LOCALES_DIR}"

    wrong = [entry for entry in audited if entry.clause is None and not entry.unjudgeable]
    detail = "\n".join(
        f"  {entry.locale}: units.h is {entry.label!r}, but this product calls an hour "
        f"{entry.frontend_name!r} in that language"
        for entry in wrong
    )
    assert not wrong, (
        "A backend locale labels the hour with a word that is not an hour. The value beside "
        "this label is an hourly figure, so a label naming a longer period misstates it by the "
        "length of that period. A worker-day is a unit in its own right - the BOQ unit picker "
        "already offers day, shift, mh and the locale-native 工日 / 人日 / 인일 - and is not a "
        f"translation of the hour.\n{detail}"
    )


def test_the_check_still_has_something_to_compare_against() -> None:
    """A gate with no witness passes everything; count the ones it cannot judge.

    ``verdict`` returns "could not judge" when the frontend catalogue has no
    name for the hour in that language, and a locale that cannot be judged is
    indistinguishable from one that passed. If translating a locale ever
    regressed to the English word, this is where it shows up.
    """
    audited = audit_hour_labels(LOCALES_DIR, FRONTEND_LOCALES)

    unjudgeable = [entry.locale for entry in audited if entry.unjudgeable]
    assert len(unjudgeable) <= MAX_UNJUDGEABLE_LOCALES, (
        f"{len(unjudgeable)} of {len(audited)} locales have no translated name for the hour in "
        f"frontend/src/app/locales, so this file cannot judge their backend label: "
        f"{sorted(unjudgeable)}. Translate units.h there, or the hour check is silent for them."
    )
