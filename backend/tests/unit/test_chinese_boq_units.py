# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit vocabulary for Chinese bills of quantities.

A GB/T 50500 bill writes its units as words. ``app.modules.boq.units`` keeps
non-Latin units verbatim rather than folding them to Latin, so those words
reach the validation rules exactly as an estimator typed them - and an
unrecognised unit is skipped, never flagged. A Chinese bill therefore used to
produce no findings rather than wrong ones, which is safe and useless.

These tests pin the three things that were decided when the vocabulary was
extended, because none of them is self-evident from the code:

1. Chinese metric words are in the metric set.
2. Chinese count words are in ``_COUNT_UNITS`` and in NEITHER measurement
   system set. A count of discrete items has no dimension, so it cannot be
   the wrong measurement system; both system sets are only ever read as the
   *wrong* set, and a count unit listed in one would make every count row on
   a project of the other system report a mismatch.
3. The CJK compatibility glyphs are rejected before storage, which is why
   they are deliberately absent from the vocabulary.
"""

from __future__ import annotations

import pytest

from app.core.match_service.boosts.unit import (
    _DIMENSION_GROUP,
    _LOCALE_UNIT_ALIASES,
    _VALID_UNITS,
    _normalise_unit,
)
from app.core.validation.rules import _IMPERIAL_BOQ_UNITS, _METRIC_BOQ_UNITS
from app.modules.bim_hub.service import _COUNT_UNITS, normalize_unit_token
from app.modules.boq.units import normalise_unit

# Metric units as a Chinese bill writes them. Both readings are listed
# because both are written: the colloquial forms sit beside the SI-derived
# ones and a real bill mixes them.
CHINESE_METRIC_UNITS = (
    "米",
    "平方米",
    "立方米",
    "吨",
    "千克",
    "公斤",
    "毫米",
    "厘米",
    "千米",
    "公里",
    "升",
    "公顷",
)

# Count units. Every one of these is dimensionless.
CHINESE_COUNT_UNITS = (
    "项",
    "台",
    "套",
    "樘",
    "个",
    "块",
    "根",
    "组",
    "座",
    "只",
    "片",
    "件",
    "棵",
)

# Real bill count words that are deliberately NOT in ``_COUNT_UNITS``. Each
# denotes a group whose size an estimator sets by hand, so the number of linked
# BIM elements is not the quantity.
CHINESE_GROUP_UNITS_THAT_ARE_NOT_ONE_PER_ELEMENT = ("副", "处")

# Produced by a Chinese IME left in full-width mode. ``str.lower()`` folds
# full-width capitals to full-width lowercase but never to ASCII, and nothing
# on the write path applies NFKC, so these arrive exactly as typed.
FULLWIDTH_METRIC_UNITS = ("ｍ", "ｍ２", "ｍ３")

# CJK compatibility glyphs. Common in real Chinese documents and rejected by
# the write path, which is the reason they are not in the vocabulary.
CJK_COMPATIBILITY_GLYPHS = ("㎡", "㎥", "㎏", "㎜")


@pytest.mark.parametrize("unit", CHINESE_METRIC_UNITS + FULLWIDTH_METRIC_UNITS)
def test_chinese_metric_units_are_recognised_as_metric(unit: str) -> None:
    assert unit in _METRIC_BOQ_UNITS
    assert unit not in _IMPERIAL_BOQ_UNITS


@pytest.mark.parametrize("unit", CHINESE_COUNT_UNITS)
def test_chinese_count_units_are_counts(unit: str) -> None:
    assert unit in _COUNT_UNITS


@pytest.mark.parametrize("unit", CHINESE_COUNT_UNITS)
def test_chinese_count_units_reach_the_count_branch(unit: str) -> None:
    """Membership in the set is not the same as reaching the branch that reads it.

    ``bim_hub`` never tests the raw unit: it folds the token through
    ``normalize_unit_token`` first, which lower-cases, strips trailing
    periods and folds superscripts. None of those touch CJK today, so the
    word arrives at the ``_COUNT_UNITS`` test unchanged - but that is a
    property of the folding function, not of the set, and this asserts the
    path rather than assuming it. If the folding ever starts transliterating
    CJK, the set entries become the wrong spelling and the guard against
    overwriting a hand-entered piece count goes quiet.
    """
    assert normalize_unit_token(unit) in _COUNT_UNITS


@pytest.mark.parametrize("unit", CHINESE_COUNT_UNITS)
def test_chinese_count_units_belong_to_no_measurement_system(unit: str) -> None:
    """A count unit in either system set would misfire on every count row.

    ``BOQUnitSystemConsistencyRule`` reads the set for the system the project
    is NOT in. Putting 个 in the metric set would flag every 个 row on an
    imperial project as a metric mismatch, and vice versa. This is the
    assertion that stops a future contributor from tidying the count units in
    beside the metric words: nothing else would fail if they did, because an
    unrecognised unit is skipped rather than flagged.
    """
    assert unit not in _METRIC_BOQ_UNITS
    assert unit not in _IMPERIAL_BOQ_UNITS


@pytest.mark.parametrize("unit", CHINESE_METRIC_UNITS + CHINESE_COUNT_UNITS + FULLWIDTH_METRIC_UNITS)
def test_chinese_units_survive_the_write_path(unit: str) -> None:
    """Every unit in the vocabulary must be one the write path can store.

    A token the write path rejects would be decoration: it could never reach
    the rule that reads it. This is the load-bearing property, and it holds
    whatever ``normalise_unit`` chooses to return.
    """
    assert normalise_unit(unit) is not None


@pytest.mark.parametrize("unit", CHINESE_METRIC_UNITS + CHINESE_COUNT_UNITS + FULLWIDTH_METRIC_UNITS)
def test_chinese_units_are_not_aliased_to_latin(unit: str) -> None:
    """Pin on a policy, not on a fact: local spellings are kept as typed.

    ``boq/units.py`` deliberately carries no CJK, Cyrillic or accented
    entries in ``_UNIT_ALIASES`` - the bill shows what the estimator wrote,
    and the vocabulary in the rules is what makes that readable to the
    engine. Adding an alias such as 平方米 -> m2 would fail this test.

    That failure is a decision point, not a defect. Aliasing is a coherent
    alternative design, but it moves the vocabulary out of the rules and
    into the write path for every market at once, so it should be taken
    deliberately and this test should be deleted in the same change - not
    loosened to make a surprise pass.
    """
    assert normalise_unit(unit) == unit


@pytest.mark.parametrize("glyph", CJK_COMPATIBILITY_GLYPHS)
def test_cjk_compatibility_glyphs_are_still_rejected(glyph: str) -> None:
    """Guard on the reason these are absent from the vocabulary.

    ``_is_safe_unit_shape`` requires the first character to be a letter, a
    digit or '%'. These glyphs are category So, so ``normalise_unit`` returns
    None and ``PositionCreate`` raises: a bill row measured in ㎡ cannot be
    stored at all. That is a real import gap for the Chinese market - NFKC
    would fold ㎡ to m2 in one line - but it is a change to a write path every
    market shares, so it was left alone.

    When someone does fix it, this test fails, and that failure is the signal
    to add the compatibility glyphs to ``_METRIC_BOQ_UNITS``.
    """
    assert normalise_unit(glyph) is None
    assert glyph not in _METRIC_BOQ_UNITS


# ── The imperial half, which is the half a Chinese project reads ────────────

# Imperial units written in Chinese. Four of these are the platform's own
# spellings: the zh locale renders ft, sqft, cy and lf as 英尺, 平方英尺, 立方码
# and 线性英尺. The rest are the standard Chinese names for the same family.
CHINESE_IMPERIAL_UNITS = (
    "英尺",
    "平方英尺",
    "立方英尺",
    "线性英尺",
    "英寸",
    "平方英寸",
    "码",
    "平方码",
    "立方码",
    "英里",
    "磅",
    "盎司",
    "短吨",
    "加仑",
)

# Labour and plant time. A 工日 is a man-day and a 台班 a machine-shift; both are
# whole-shift units of roughly eight hours.
CHINESE_LABOUR_AND_PLANT_UNITS = ("工日", "台班")

# Every distinct unit string in the two Chinese demo projects this repository
# ships, with the number of rows carrying it. Written out rather than derived so
# a demo pack edited to use a unit nobody taught the platform fails the test
# below instead of quietly shrinking its own coverage.
SHIPPED_CHINESE_DEMO_UNITS = {
    "m2": 75,
    "m3": 45,
    "项": 30,
    "m": 29,
    "樘": 10,
    "台": 10,
    "t": 9,
    "套": 6,
    "根": 4,
    "组": 4,
}

# The demo projects the census above was read from.
_CHINESE_DEMO_IDS = ("office-shanghai", "residential-shenzhen")


def shipped_chinese_demo_units() -> dict[str, int]:
    """Read the units priced in the shipped Chinese demo projects, from disk.

    The dict above is the census as it stood when this file was written, and it
    is documentation. This is the gate: the tests below run over whatever the
    templates actually carry today, so a demo row added in a unit no vocabulary
    knows fails by name instead of going uncounted.

    Returns:
        Unit token to the number of BOQ rows priced in it, across both projects.
    """
    from app.core.demo_projects import DEMO_TEMPLATES

    counted: dict[str, int] = {}
    for demo_id in _CHINESE_DEMO_IDS:
        for section in DEMO_TEMPLATES[demo_id].sections:
            for row in section[3]:
                counted[row[2]] = counted.get(row[2], 0) + 1
    return counted


SHIPPED_UNITS_ON_DISK = tuple(sorted(shipped_chinese_demo_units()))


@pytest.mark.parametrize("unit", CHINESE_IMPERIAL_UNITS)
def test_chinese_imperial_units_are_recognised_as_imperial(unit: str) -> None:
    """This is the direction a Chinese project actually depends on.

    ``BOQUnitSystemConsistencyRule`` reads the set for the system the project
    is NOT in. China is metric, so a Chinese bill is judged against the
    imperial set and never against the metric one - the Chinese metric words
    earn their keep on an imperial project carrying a Chinese row. A
    vocabulary that covered only the metric words therefore left the market it
    was added for exactly as unprotected as before, because an imperial row in
    a Chinese bill is written 英尺 rather than "ft".
    """
    assert unit in _IMPERIAL_BOQ_UNITS
    assert unit not in _METRIC_BOQ_UNITS


@pytest.mark.parametrize("unit", CHINESE_IMPERIAL_UNITS)
def test_chinese_imperial_units_survive_the_write_path(unit: str) -> None:
    """A unit the write path rejects could never reach the rule that reads it."""
    assert normalise_unit(unit) is not None


# ── Labour and plant time ───────────────────────────────────────────────────


@pytest.mark.parametrize("unit", CHINESE_LABOUR_AND_PLANT_UNITS)
def test_labour_and_plant_units_belong_to_no_measurement_system(unit: str) -> None:
    """A man-day has no dimension, so it cannot be the wrong measurement system.

    Same reasoning as the count units above, and the same consequence if it is
    ignored: 工日 in the metric set would flag every labour row on an imperial
    project, and in the imperial set every labour row on a Chinese one.
    """
    assert unit not in _METRIC_BOQ_UNITS
    assert unit not in _IMPERIAL_BOQ_UNITS


@pytest.mark.parametrize("unit", CHINESE_LABOUR_AND_PLANT_UNITS)
def test_labour_and_plant_units_are_not_count_units(unit: str) -> None:
    """Tidying these in beside the count units would corrupt quantities.

    The ``_COUNT_UNITS`` branch in ``bim_hub`` does not merely decline to
    substitute geometry - it overwrites the position quantity with the number
    of linked BIM elements. Labour and plant are booked in fractions of a shift
    (7.5 工日 is an ordinary figure), so a position measured this way would have
    its estimated effort replaced by a whole-number element count. The branch
    these units want is the one below it, which leaves an unrecognised unit's
    manual quantity alone (D-TKC-028), and they reach it by not being here.
    """
    assert unit not in _COUNT_UNITS
    assert normalize_unit_token(unit) not in _COUNT_UNITS


@pytest.mark.parametrize("unit", CHINESE_LABOUR_AND_PLANT_UNITS)
def test_labour_and_plant_units_are_not_folded_to_the_hour(unit: str) -> None:
    """Folding a whole-shift unit into the hour would misprice by that factor.

    The cost matcher's alias table exists to let a locale spelling score
    against a canonical code. Mapping 工日 to "h" would put a man-day rate and
    an hourly rate in one bucket and let the boost promote a candidate whose
    unit rate is out by roughly eight. Unfolded, the token passes through
    verbatim and still behaves: self-equal against another 工日 row, and a
    dimensional mismatch against an area. That is the correct answer, so it is
    pinned rather than left to look like an oversight someone should fix.
    """
    assert unit not in _LOCALE_UNIT_ALIASES
    assert _normalise_unit(unit) == unit
    assert _normalise_unit(unit) not in _VALID_UNITS
    # Self-equal, so a labour row still matches a labour row.
    assert _normalise_unit(unit) == _normalise_unit(unit)
    # And dimensionally distinct from an area, so it cannot be promoted onto one.
    assert _DIMENSION_GROUP.get(_normalise_unit(unit), _normalise_unit(unit)) != _DIMENSION_GROUP["m2"]


# ── Group units the count branch must not claim ─────────────────────────────


@pytest.mark.parametrize("unit", CHINESE_GROUP_UNITS_THAT_ARE_NOT_ONE_PER_ELEMENT)
def test_group_units_are_not_count_units(unit: str) -> None:
    """A unit whose quantity is not one per element must miss the count branch.

    ``_sync_quantity_from_links`` rewrites ``position.quantity`` to the number
    of linked BIM elements once the unit is in ``_COUNT_UNITS``. That is right
    for a piece, and wrong for a group: three waterproofing locations can link
    fifteen elements, and five matched pairs of leaves link ten. Outside the
    set, the unknown-unit branch leaves the estimator's own figure alone, which
    is the correct answer for both. Membership would overwrite a hand-entered
    quantity with a larger number - the E-XMOD-003 corruption arriving through
    a different branch - so this absence is deliberate and pinned here.
    """
    assert unit not in _COUNT_UNITS
    assert normalize_unit_token(unit) not in _COUNT_UNITS


@pytest.mark.parametrize("unit", CHINESE_GROUP_UNITS_THAT_ARE_NOT_ONE_PER_ELEMENT)
def test_group_units_still_fold_for_the_cost_matcher(unit: str) -> None:
    """Excluding them from the count branch must not cost them the unit signal.

    The alias table only picks a dimension family; it converts no quantity and
    writes nothing back to a position. Both units belong there even though
    neither belongs in ``_COUNT_UNITS``.
    """
    assert _normalise_unit(unit) == "pcs"


# ── Reconciliation against the Chinese data we actually ship ────────────────


@pytest.mark.parametrize("unit", SHIPPED_UNITS_ON_DISK)
def test_every_shipped_chinese_demo_unit_is_recognised_somewhere(unit: str) -> None:
    """A unit in our own data that no vocabulary knows is a silent gap.

    Recognition here means one of three things, because a unit is only ever
    read by the vocabulary its dimension belongs to: a measurement-system set
    for a dimensional unit, ``_COUNT_UNITS`` for a count, or the canonical
    catalogue for a Latin short code. What must not happen is a unit that is in
    none of them, because that unit is skipped by every check that reads it.
    """
    from app.modules.boq.units import APPROVED_UNITS

    known = unit in _METRIC_BOQ_UNITS or unit in _IMPERIAL_BOQ_UNITS or unit in _COUNT_UNITS or unit in APPROVED_UNITS
    assert known, f"{unit!r} is priced in our own Chinese demo data and no vocabulary knows it"


@pytest.mark.parametrize("unit", SHIPPED_UNITS_ON_DISK)
def test_every_shipped_chinese_demo_unit_folds_for_the_cost_matcher(unit: str) -> None:
    """The matcher can only score a unit it can fold to a canonical code.

    This is where the gap was: the Chinese block of the alias table was
    assembled from the metric words, so 项, 台, 樘, 根 and 组 had no entry -
    58 of the 222 rows in our own two Chinese demo projects, 30 of them 项.
    An unfolded token is merely self-equal, so those rows scored no unit signal
    at all and a candidate priced per item ranked level with one priced per
    square metre.
    """
    assert _normalise_unit(unit) in _VALID_UNITS


def test_the_shipped_census_is_not_empty() -> None:
    """The two tests above are only as good as the census they run over.

    Both are parametrized from ``SHIPPED_UNITS_ON_DISK``, which is read at
    import time. If a demo project were renamed the lookup would raise, but if
    the row shape changed the census could come back empty and every case would
    silently stop being generated while the file still reported all green. A
    suite that collects nothing passes, so the count is asserted here directly
    rather than inferred from the other tests going green.
    """
    census = shipped_chinese_demo_units()

    assert len(census) >= len(SHIPPED_CHINESE_DEMO_UNITS)
    assert sum(census.values()) >= sum(SHIPPED_CHINESE_DEMO_UNITS.values())


# ── The Chinese label for the canonical hour ────────────────────────────────


def test_the_chinese_label_for_an_hour_is_an_hour() -> None:
    """The backend zh locale rendered the hour as a man-day.

    ``units.h`` is the canonical hour: every one of the other backend locales
    renders it as one, and our own frontend zh locale renders the same key as
    小时. The backend copy said 工日, a man-day - a whole-shift unit the
    platform holds as a separate unit elsewhere, and one this catalogue names
    no other key for. So the published vocabulary gave the hour the name of a
    longer period, contradicting both this platform's canonical token model
    and its own frontend catalogue for the same key. No gate could see it,
    because both values are perfectly good Chinese.

    A worker-day is a unit in its own right rather than a translation of the
    hour: the BOQ picker offers 工日 and 台班 beside 小时, so a bill priced per
    man-day says so in its unit.

    The assertion is on the property rather than only the string: the label for
    an hour must not be any of the whole-shift units the platform recognises
    elsewhere.
    """
    import json
    from pathlib import Path

    locales_dir = Path(__file__).resolve().parents[2] / "locales"
    units = json.loads((locales_dir / "zh.json").read_text(encoding="utf-8"))["units"]

    assert units["h"] == "小时"
    assert units["h"] not in CHINESE_LABOUR_AND_PLANT_UNITS
    assert units["h"] != "人工"
