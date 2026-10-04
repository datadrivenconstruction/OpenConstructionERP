# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The national code and unit rules accept what a real bill in the country writes.

Four rules judged a line by one spelling of its national structure and warned
on every other one a real estimate uses:

* Romania read the deviz chapter only as a bare number, so "Cap. 4.1",
  "Capitolul 4" and "4.1." warned as unrecognised.
* Ukraine read the summary-estimate chapter only as a bare number, so a line
  filed under its local estimate "02-01-001" or written "Глава 2" warned, and
  a superscript digit passed ``str.isdigit`` and then broke ``int``.
* Turkey accepted only the older XX.XXX/X poz numbering, so every line of a
  current bill (XX.XXX.XXXX, the Istanbul demo included) warned.
* India (CPWD) and Japan (Sekisan) compared units against a short list with no
  folding, so "m²", the unit the India pack declares as its own default, the
  quintal, the tonne written "MT", 基 and 面 on the Tokyo demo, and every
  full-width "ｍ２" warned.

Each case below is paired with one the rule must still refuse, so a rule that
started accepting everything would fail here rather than read green.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext, ValidationRule
from app.core.validation.rules import (
    BirimFiyatValidPoz,
    CPWDMeasurementUnits,
    RomanianDevizChapterRecognised,
    SekisanMetricUnits,
    UkrainianZkrChapterRecognised,
)


def _line(*, classification: dict[str, str] | None = None, unit: str = "m3", **extra: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "ordinal": "1.1",
        "description": "Excavation",
        "unit": unit,
        "quantity": 10,
        "unit_rate": 100,
        "total": 1000,
        "classification": classification or {},
        **extra,
    }


def _results(rule: ValidationRule, positions: list[dict[str, Any]]) -> list[Any]:
    context = ValidationContext(data={"positions": positions}, metadata={"locale": "en"})
    return asyncio.run(rule.validate(context))


def _passes(rule: ValidationRule, position: dict[str, Any]) -> bool:
    results = _results(rule, [position])
    assert len(results) == 1, f"{rule.rule_id} judged the line {len(results)} times, expected once"
    return results[0].passed


# ── Romania: the deviz general chapter ───────────────────────────────────────


@pytest.mark.parametrize(
    "code",
    [
        "4.1",
        "4.1.1",
        "3.8.2",
        "4.1.",
        "Cap. 4.1",
        "cap.4.1",
        "CAP 4",
        "Capitolul 4",
        "Capitol 5.1",
        "Subcap. 4.1",
        "Subcapitolul 4.1",
        "Cap. nr. 6.2",
        "Capitolul 4 - Cheltuieli pentru investiția de bază",
        "4.1 Construcții și instalații",
        " 4.1 ",
    ],
)
def test_a_romanian_chapter_written_the_way_a_deviz_writes_it_is_recognised(code: str) -> None:
    assert _passes(RomanianDevizChapterRecognised(), _line(classification={"deviz": code})), code


@pytest.mark.parametrize(
    "code",
    [
        "7.2",  # no chapter 7 in the deviz general
        "4.9",  # chapter 4 has no subchapter 9
        "Cap. 7",
        "Capitolul 4.9",
        "4.1x",
        "x4.1",
        "Cap.",
        "Capitolul",
        "41",
        "4²",  # a superscript is not a chapter digit
        "CA01A1",  # a norm symbol, not a deviz chapter
    ],
)
def test_a_romanian_code_that_names_no_deviz_chapter_is_still_refused(code: str) -> None:
    assert not _passes(RomanianDevizChapterRecognised(), _line(classification={"deviz": code})), code


def test_the_romanian_finding_carries_the_chapter_title_of_the_cleaned_code() -> None:
    [result] = _results(RomanianDevizChapterRecognised(), [_line(classification={"deviz": "Cap. 4.1"})])
    assert result.details["given_code"] == "Cap. 4.1"
    assert result.details["chapter_name"] == "Construcții și instalații"


# ── Ukraine: the chapter of the summary estimate ─────────────────────────────


@pytest.mark.parametrize(
    "code",
    [
        "2",
        "02",
        "12",
        "2.",
        "Глава 2",
        "глава 12",
        "ГЛАВА 2",
        "Гл. 2",
        "гл.2",
        "2-1",  # the object estimate of chapter 2
        "2-1-1",  # a local estimate under it
        "02-01-001",  # the same, zero padded
        "2 - 1",
        "Глава № 9",
    ],
)
def test_a_ukrainian_chapter_written_the_way_an_estimate_writes_it_is_recognised(code: str) -> None:
    assert _passes(UkrainianZkrChapterRecognised(), _line(classification={"zkr": code})), code


@pytest.mark.parametrize(
    "code",
    [
        "13",
        "0",
        "00",
        "13-1-1",
        "Глава 13",
        "2.1",  # not how the estimate numbering is written
        "2-1-1-1",
        "A2",
        "²",  # str.isdigit says yes, int says no: this used to raise
        "٢",  # an Arabic-Indic two is not an estimate chapter
        "Розділ 2",
    ],
)
def test_a_ukrainian_code_that_names_no_chapter_is_still_refused(code: str) -> None:
    assert not _passes(UkrainianZkrChapterRecognised(), _line(classification={"zkr": code})), code


def test_the_ukrainian_finding_names_the_chapter_a_local_estimate_number_belongs_to() -> None:
    [result] = _results(UkrainianZkrChapterRecognised(), [_line(classification={"zkr": "02-01-001"})])
    assert result.passed
    assert result.details["chapter_name"] == "Об'єкти основного призначення"


# ── Turkey: the poz number ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code",
    [
        "15.140.1002",  # the current unit-price book numbering
        "16.058.1004",
        "15.150.1003/A",
        "04.013/1",  # the older Bayındırlık numbering
        "16.050/04",
        "Y.16.050/04",
        "y.16.050/04",
        "04.613/1A",
        "16.050",
        "ÖZEL-1",  # the contractor's own analysed item
        "Özel Poz 3",
        "ÖZ.01",
        "OZEL 12",
    ],
)
def test_a_turkish_poz_in_a_shape_the_book_uses_is_accepted(code: str) -> None:
    assert _passes(BirimFiyatValidPoz(), _line(classification={"birimfiyat": code})), code


@pytest.mark.parametrize(
    "code",
    [
        "15.140.100",
        "15.1400.1002",
        "151401002",
        "15-140-1002",
        "Y.15.140.1002",
        "16.050/123",
        "ÖZEL",
        "15",  # a chapter, not an item, on a priced line
    ],
)
def test_a_turkish_poz_in_no_shape_the_book_uses_is_still_refused(code: str) -> None:
    assert not _passes(BirimFiyatValidPoz(), _line(classification={"birimfiyat": code})), code


def test_a_turkish_section_row_may_carry_its_chapter_and_a_priced_line_may_not() -> None:
    section = {
        "id": "s-1",
        "ordinal": "1",
        "description": "Toprak işleri",
        "type": "section",
        "classification": {"birimfiyat": "15"},
    }
    item = _line(classification={"birimfiyat": "15"}, parent_id="s-1")
    results = {r.element_ref: r.passed for r in _results(BirimFiyatValidPoz(), [section, item])}
    assert results == {"s-1": True, item["id"]: False}


# ── India and Japan: the unit lists ──────────────────────────────────────────


@pytest.mark.parametrize(
    "unit",
    [
        "m²",  # the India pack's own default area unit
        "m³",
        "cum",
        "Cu.M.",
        "cu m",
        "sqm",
        "Sq.M",
        "sq m",
        "RMT",
        "metre",
        "Nos.",
        "No.",
        "each",
        "kg",
        "Qtl",
        "quintal",
        "MT",  # the metric tonne as Indian bills write it
        "tonne",
        "litre",
        "kL",
        "point",
        "Job",
        "pair",
        "set",
        "km",
        "hectare",
        "day",
        "LS",
    ],
)
def test_a_cpwd_unit_written_as_an_indian_bill_writes_it_is_accepted(unit: str) -> None:
    assert _passes(CPWDMeasurementUnits(), _line(unit=unit)), unit


@pytest.mark.parametrize("unit", ["ft", "sqft", "cft", "cy", "lb", "gal", "ton", "inch", "bdft"])
def test_an_imperial_unit_is_still_refused_under_cpwd(unit: str) -> None:
    """IS 1200 is metric. Folding must not have opened the list to everything."""
    assert not _passes(CPWDMeasurementUnits(), _line(unit=unit)), unit


@pytest.mark.parametrize(
    "unit",
    [
        "m2",
        "㎡",  # the squared glyph
        "ｍ２",  # full width
        "㎥",
        "ｍ３",
        "ｍ",
        "㎏",
        "ｔ",
        "基",
        "面",
        "本",
        "枚",
        "箇所",
        "個所",
        "ヶ所",
        "カ所",
        "か所",
        "式",
        "台",
        "組",
        "個",
        "人",
        "人工",
        "日",
        "回",
        "袋",
        "缶",
        "対",
        "巻",
        "丁",
        "坪",
        "ℓ",
        "L",
        "トン",
        "m2/回",
    ],
)
def test_a_sekisan_unit_written_as_a_japanese_bill_writes_it_is_accepted(unit: str) -> None:
    assert _passes(SekisanMetricUnits(), _line(unit=unit)), unit


@pytest.mark.parametrize("unit", ["ft", "sqft", "yd", "lb", "gal", "cy", "坪坪", "kgs"])
def test_a_unit_outside_the_japanese_list_is_still_refused(unit: str) -> None:
    assert not _passes(SekisanMetricUnits(), _line(unit=unit)), unit


# ── The shipped demos, which are what a user opens first ─────────────────────


def _demo_positions(demo_id: str) -> list[dict[str, Any]]:
    from app.core.demo_projects import DEMO_TEMPLATES

    template = DEMO_TEMPLATES[demo_id]
    positions: list[dict[str, Any]] = []
    for ordinal, title, classification, items in template.sections:
        section_id = f"s-{ordinal}"
        positions.append(
            {
                "id": section_id,
                "ordinal": ordinal,
                "description": title,
                "classification": classification,
                "type": "section",
            }
        )
        for item_ordinal, description, unit, quantity, rate, item_classification in items:
            positions.append(
                _line(
                    classification=item_classification,
                    unit=unit,
                    ordinal=item_ordinal,
                    description=description,
                    quantity=float(quantity),
                    unit_rate=float(rate),
                    parent_id=section_id,
                )
            )
    return positions


@pytest.mark.parametrize(
    ("demo_id", "rule"),
    [
        ("office-tokyo", SekisanMetricUnits()),
        ("mixed-use-istanbul", BirimFiyatValidPoz()),
        ("govt-building-delhi", CPWDMeasurementUnits()),
        ("it-park-bangalore", CPWDMeasurementUnits()),
        ("office-bucharest", RomanianDevizChapterRecognised()),
        ("school-kyiv", UkrainianZkrChapterRecognised()),
    ],
)
def test_the_shipped_demo_of_the_country_passes_its_national_rule(demo_id: str, rule: ValidationRule) -> None:
    positions = _demo_positions(demo_id)
    results = _results(rule, positions)
    assert len(results) >= 20, f"{rule.rule_id} judged only {len(results)} rows of {demo_id}"
    failed = sorted({str((r.details or {}).get("given_code") or r.message) for r in results if not r.passed})
    assert failed == [], f"{demo_id} fails {rule.rule_id} on {failed}"
