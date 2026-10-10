# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Turkish poz rules judge what a bill line carries, and nothing it does not.

Six rules joined the two that read the poz number: the chapter the number
starts with, the unit the line is measured in, one poz in one unit and at one
rate within a bill, an analysis under the bill's own items, and the combined
25 percent contractor profit and general expenses applied once.

Each rule is shown a bill it must pass and a bill it must fail, so a rule
that started accepting everything would fail here rather than read green.
The mechanical and electrical bill at the foot of the file uses poz numbers
of the shape and chapters the Ministry book has (25 and 35), with
descriptions written for this test rather than copied from the book.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, ValidationRule
from app.core.validation.messages import is_key_present
from app.core.validation.rules import (
    BirimFiyatChapterRecognised,
    BirimFiyatCodeRequired,
    BirimFiyatOwnItemAnalysed,
    BirimFiyatPozRateConsistent,
    BirimFiyatPozUnitConsistent,
    BirimFiyatProfitOverheadOnce,
    BirimFiyatUnitRecognised,
    BirimFiyatValidPoz,
)

ALL_RULES: tuple[type[ValidationRule], ...] = (
    BirimFiyatCodeRequired,
    BirimFiyatValidPoz,
    BirimFiyatChapterRecognised,
    BirimFiyatUnitRecognised,
    BirimFiyatPozUnitConsistent,
    BirimFiyatPozRateConsistent,
    BirimFiyatOwnItemAnalysed,
    BirimFiyatProfitOverheadOnce,
)


def _line(poz: str = "25.305.1104", unit: str = "m", rate: float = 100.0, **extra: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "ordinal": extra.pop("ordinal", "1.1"),
        "description": extra.pop("description", "Plastik pis su borusu"),
        "unit": unit,
        "quantity": 10.0,
        "unit_rate": rate,
        "total": 10.0 * rate,
        "classification": {"birimfiyat": poz} if poz else {},
        "type": "position",
        **extra,
    }


def _section(poz: str, ordinal: str = "1") -> dict[str, Any]:
    return {
        "id": f"s-{ordinal}",
        "ordinal": ordinal,
        "description": "Bölüm",
        "classification": {"birimfiyat": poz},
        "type": "section",
    }


def _run(
    rule: ValidationRule,
    positions: list[dict[str, Any]],
    markups: list[dict[str, Any]] | None = None,
    locale: str = "en",
) -> list[Any]:
    data: dict[str, Any] = {"positions": positions}
    if markups is not None:
        data["markups"] = markups
    return asyncio.run(rule.validate(ValidationContext(data=data, metadata={"locale": locale})))


def _failed(results: list[Any]) -> list[Any]:
    return [r for r in results if not r.passed]


def _markup(name: str, category: str, percentage: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "markup_type": "percentage",
        "category": category,
        "percentage": percentage,
        "apply_to": "direct_cost",
        "is_active": True,
        "scope_position_id": None,
        "overrides_id": None,
        **extra,
    }


# ── Shape of the set ─────────────────────────────────────────────────────────


def test_every_rule_belongs_to_the_one_rule_set_the_pack_names() -> None:
    assert {rule.standard for rule in ALL_RULES} == {"birimfiyat"}
    assert len({rule.rule_id for rule in ALL_RULES}) == len(ALL_RULES)


def test_only_the_missing_poz_number_is_an_error() -> None:
    """A check that cannot see the price list must not block a bill."""
    errors = {rule.rule_id for rule in ALL_RULES if rule.severity is Severity.ERROR}
    assert errors == {"birimfiyat.code_required"}


@pytest.mark.parametrize("locale", ["en", "tr"])
@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.rule_id)
def test_every_rule_has_its_message_and_advice_in_english_and_turkish(rule: type[ValidationRule], locale: str) -> None:
    assert is_key_present(f"{rule.rule_id}.fail", locale)
    assert is_key_present(f"{rule.rule_id}.suggestion", locale)


# ── Chapter ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "poz",
    [
        "15.150.1005",  # building works
        "25.305.1104",  # mechanical installation
        "35.150.3101",  # electrical installation
        "19.100.1113",  # hourly plant cost
        "10.100.1062",  # a resource price
        "43.560.1101",  # another public body's list
    ],
)
def test_a_chapter_a_published_list_has_is_recognised(poz: str) -> None:
    results = _run(BirimFiyatChapterRecognised(), [_line(poz)])
    assert [r.passed for r in results] == [True]


@pytest.mark.parametrize("poz", ["99.999.9999", "00.000.0000", "26.305.1104", "30.150.3101"])
def test_a_well_formed_number_under_a_chapter_no_list_has_is_reported(poz: str) -> None:
    assert BirimFiyatValidPoz.poz_is_well_formed(poz), "the shape check passes it, which is why this rule exists"
    results = _run(BirimFiyatChapterRecognised(), [_line(poz)])
    assert [r.passed for r in results] == [False]
    assert poz[:2] in results[0].message
    assert results[0].details["chapter"] == poz[:2]


@pytest.mark.parametrize("poz", ["04.013/1", "Y.16.050/04", "ÖZEL-1", "özel poz 3", "", "not a poz"])
def test_older_numbers_own_items_and_malformed_ones_are_left_to_the_other_rules(poz: str) -> None:
    assert _run(BirimFiyatChapterRecognised(), [_line(poz)]) == []


def test_a_section_row_is_judged_by_the_chapter_it_groups() -> None:
    rows = [
        _section("25", "1"),
        _line("25.305.1104", parent_id="s-1"),
        _section("27", "2"),
        _line("25.320.1101", parent_id="s-2"),
    ]
    results = _run(BirimFiyatChapterRecognised(), rows)
    by_ref = {r.element_ref: r.passed for r in results}
    assert by_ref["s-1"] is True
    assert by_ref["s-2"] is False


def test_the_chapter_is_named_in_the_details_for_the_ministry_book() -> None:
    result = _run(BirimFiyatChapterRecognised(), [_line("35.150.3101")])[0]
    assert result.details["chapter_name"] == "Elektrik tesisatı"


# ── Unit ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "unit",
    [
        "m", "M", "mt", "Mt.", "Metre",
        "m²", "m2", "M2", "M²",
        "m³", "m3", "M³",
        "Ad", "AD", "ad", "adet", "Adet", "ADET",
        "Tk", "TK", "takım", "Takım", "TAKIM",
        "Kg", "KG", "kg",
        "Ton", "TON", "ton",
        "Sa", "saat", "Saat",
        "gün", "Gün", "GÜN",
        "Ay", "Km", "Lt", "LİTRE", "kWh", "Kwh", "Ha", "Dekar", "dm3",
        "100 m²", "1000 Ad", "100 mt",
        "pcs", "lsum",
    ],
)  # fmt: skip
def test_a_unit_the_lists_measure_in_is_recognised(unit: str) -> None:
    results = _run(BirimFiyatUnitRecognised(), [_line(unit=unit)])
    assert [r.passed for r in results] == [True], unit


@pytest.mark.parametrize("unit", ["ft", "lb", "sqft", "each", "yd3", "LF", "m4", "100", "stk"])
def test_a_unit_no_turkish_list_uses_is_reported(unit: str) -> None:
    results = _run(BirimFiyatUnitRecognised(), [_line(unit=unit)])
    assert [r.passed for r in results] == [False], unit
    assert unit in results[0].message


def test_a_line_without_a_unit_is_left_to_the_empty_unit_rule() -> None:
    assert _run(BirimFiyatUnitRecognised(), [_line(unit="")]) == []


# ── One poz, one unit ────────────────────────────────────────────────────────


def test_one_poz_spelled_in_two_ways_of_one_unit_agrees() -> None:
    rows = [_line("25.320.1101", "Ad"), _line("25.320.1101", "adet"), _line("25.320.1101", "ADET")]
    results = _run(BirimFiyatPozUnitConsistent(), rows)
    assert len(results) == 3
    assert _failed(results) == []


def test_one_poz_in_two_units_is_reported_on_every_line_that_cites_it() -> None:
    rows = [_line("25.305.1104", "m"), _line("25.305.1104", "Ad"), _line("25.320.1101", "Ad")]
    results = _run(BirimFiyatPozUnitConsistent(), rows)
    failed = _failed(results)
    assert len(results) == 3
    assert len(failed) == 2
    assert all(r.details["given_code"] == "25.305.1104" for r in failed)
    assert failed[0].details["units"] == ["m", "adet"]
    assert "25.305.1104" in failed[0].message


def test_a_bulk_unit_is_a_different_unit_from_the_plain_one() -> None:
    rows = [_line("15.150.1005", "m²"), _line("15.150.1005", "100 m²")]
    assert len(_failed(_run(BirimFiyatPozUnitConsistent(), rows))) == 2


def test_the_same_own_item_number_in_two_units_is_reported_too() -> None:
    rows = [_line("ÖZEL-1", "Ad"), _line("özel-1", "Tk")]
    assert len(_failed(_run(BirimFiyatPozUnitConsistent(), rows))) == 2


# ── One poz, one rate ────────────────────────────────────────────────────────


def test_one_poz_at_one_rate_agrees() -> None:
    rows = [_line("35.150.3101", "m", 84.5), _line("35.150.3101", "m", 84.50), _line("35.140.1101", "m", 61.0)]
    results = _run(BirimFiyatPozRateConsistent(), rows)
    assert len(results) == 3
    assert _failed(results) == []


def test_one_poz_at_two_rates_is_reported_with_both_rates() -> None:
    rows = [_line("35.150.3101", "m", 84.5), _line("35.150.3101", "m", 91.0), _line("35.140.1101", "m", 61.0)]
    failed = _failed(_run(BirimFiyatPozRateConsistent(), rows))
    assert len(failed) == 2
    assert failed[0].details["unit_rates"] == ["84.50", "91.00"]
    assert "84.50" in failed[0].message
    assert "91.00" in failed[0].message


def test_an_unpriced_line_does_not_make_its_poz_inconsistent() -> None:
    rows = [_line("35.150.3101", "m", 84.5), _line("35.150.3101", "m", 0.0)]
    results = _run(BirimFiyatPozRateConsistent(), rows)
    assert len(results) == 1
    assert results[0].passed


def test_a_difference_in_unit_is_the_unit_rules_finding_not_the_rate_rules() -> None:
    rows = [_line("25.305.1104", "m", 100.0), _line("25.305.1104", "Ad", 900.0)]
    assert _failed(_run(BirimFiyatPozRateConsistent(), rows)) == []


def test_a_rate_typed_as_a_turkish_number_is_read() -> None:
    typed = _line("35.150.3101", "m", 1084.5)
    typed["unit_rate"] = "1.084,50"
    rows = [typed, _line("35.150.3101", "m", 1084.5)]
    assert _failed(_run(BirimFiyatPozRateConsistent(), rows)) == []


# ── Own item ─────────────────────────────────────────────────────────────────


def test_an_own_item_with_resources_under_it_passes() -> None:
    resources = [{"name": "Usta", "unit": "sa", "quantity": 2, "unit_rate": 300}]
    results = _run(BirimFiyatOwnItemAnalysed(), [_line("ÖZEL-1", "Ad", metadata={"resources": resources})])
    assert [r.passed for r in results] == [True]


def test_an_own_item_with_its_analysis_in_the_note_passes() -> None:
    line = _line("Özel Poz 3", "Ad", metadata={"notes": "2 sa usta, 1 sa düz işçi, malzeme teklif 3"})
    assert [r.passed for r in _run(BirimFiyatOwnItemAnalysed(), [line])] == [True]


@pytest.mark.parametrize("metadata", [{}, {"resources": []}, {"resources": [{}]}, {"notes": "   "}, {"notes": 7}])
def test_an_own_item_with_nothing_behind_its_rate_is_reported(metadata: dict[str, Any]) -> None:
    results = _run(BirimFiyatOwnItemAnalysed(), [_line("ÖZEL-1", "Ad", metadata=metadata)])
    assert [r.passed for r in results] == [False]
    assert "ÖZEL-1" in results[0].message


def test_a_number_from_the_book_needs_no_analysis_of_its_own() -> None:
    assert _run(BirimFiyatOwnItemAnalysed(), [_line("25.305.1104")]) == []


# ── The 25 percent, once ─────────────────────────────────────────────────────


def test_the_shipped_turkish_stack_passes() -> None:
    """The stack a new Turkish bill gets has to clear the rule that reads it."""
    from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES

    stack = [_markup(m["name"], m["category"], m["percentage"]) for m in DEFAULT_MARKUP_TEMPLATES["TR"]]
    results = _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)
    assert [r.passed for r in results] == [True]
    assert results[0].details["total_percent"] == "25.0"


def test_the_25_percent_on_two_lines_is_reported() -> None:
    stack = [
        _markup("Yüklenici kârı ve genel giderler", "overhead", "25"),
        _markup("Müteahhit kârı ve genel giderler", "overhead", "25"),
        _markup("KDV", "tax", "20"),
    ]
    results = _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)
    assert [r.passed for r in results] == [False]
    assert "50.00" in results[0].message
    assert Decimal(results[0].details["total_percent"]) == Decimal("50")
    assert results[0].element_ref is None


def test_an_overhead_line_and_a_profit_line_within_25_pass() -> None:
    stack = [_markup("Genel giderler", "overhead", "15"), _markup("Kâr", "profit", "10")]
    assert [r.passed for r in _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)] == [True]


def test_an_overhead_line_and_a_profit_line_above_25_are_reported() -> None:
    stack = [_markup("Genel giderler", "overhead", "25"), _markup("Kâr", "profit", "10")]
    assert [r.passed for r in _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)] == [False]


def test_a_single_line_is_never_questioned_whatever_its_percentage() -> None:
    stack = [_markup("Yüklenici kârı ve genel giderler", "overhead", "32")]
    assert [r.passed for r in _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)] == [True]


def test_a_line_is_recognised_by_its_turkish_name_when_it_is_filed_elsewhere() -> None:
    stack = [
        _markup("Müteahhit kârı ve genel giderler", "overhead", "25"),
        _markup("YÜKLENİCİ KÂRI VE GENEL GİDERLER", "other", "25"),
    ]
    assert [r.passed for r in _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)] == [False]


def test_switched_off_replaced_and_line_scoped_markups_do_not_count() -> None:
    first = _markup("Yüklenici kârı ve genel giderler", "overhead", "25")
    stack = [
        first,
        _markup("Eski satır", "overhead", "25", is_active=False),
        _markup("Tek kaleme özel", "overhead", "25", scope_position_id=str(uuid.uuid4())),
        _markup("Yeni oran", "overhead", "20", overrides_id=first["id"]),
    ]
    results = _run(BirimFiyatProfitOverheadOnce(), [_line()], stack)
    assert [r.passed for r in results] == [True]
    assert results[0].details["lines"] == ["Yeni oran"]


def test_a_bill_whose_markups_were_not_supplied_is_not_judged() -> None:
    """No markup key means the caller did not load the stack, not that it is empty."""
    assert _run(BirimFiyatProfitOverheadOnce(), [_line()], None) == []


# ── Messages ─────────────────────────────────────────────────────────────────


def test_a_turkish_reader_gets_turkish_with_its_own_letters() -> None:
    result = _run(BirimFiyatUnitRecognised(), [_line(unit="sqft")], locale="tr")[0]
    assert "ölçü birimlerinden değil" in result.message
    result = _run(
        BirimFiyatProfitOverheadOnce(),
        [_line()],
        [_markup("Genel giderler", "overhead", "25"), _markup("Kâr", "profit", "25")],
        locale="tr",
    )[0]
    assert "Yüklenici kârı ve genel giderler" in result.message


# ── A mechanical and electrical bill ─────────────────────────────────────────

#: (ordinal, description, unit, quantity, rate, poz). Chapters 25 and 35 of
#: the Ministry book; descriptions are this test's own wording.
_MEP_BILL: list[tuple[str, str, str, float, float, str]] = [
    ("1.1", "Lavabo ve tesisatı", "Ad", 48, 4_200.0, "25.100.1001"),
    ("1.2", "Klozet takımı", "Tk", 48, 9_800.0, "25.102.1101"),
    ("1.3", "Paslanmaz çelik su deposu", "Ad", 2, 185_000.0, "25.150.1217"),
    ("1.4", "Kollektör", "m", 14, 2_450.0, "25.170.1101"),
    ("1.5", "Dikişli çelik boru 2 inç", "m", 620, 780.0, "25.300.1406"),
    ("1.6", "PVC pis su borusu", "m", 940, 310.0, "25.305.1104"),
    ("1.7", "Küresel vana", "Ad", 126, 640.0, "25.320.1101"),
    ("1.8", "Boru askı ve konsol demiri", "Kg", 2_300, 96.0, "25.178.2001"),
    ("1.9", "Kanal yalıtımı", "m²", 1_150, 420.0, "25.126.1110"),
    ("1.10", "Motorlu kontrol vanası", "Ad", 18, 12_400.0, "25.565.3101"),
    ("2.1", "Sac dağıtım panosu", "Ad", 22, 14_600.0, "35.100.1101"),
    ("2.2", "Bakır bara", "Kg", 380, 720.0, "35.100.7000"),
    ("2.3", "Kompakt şalter", "Ad", 64, 5_300.0, "35.110.1703"),
    ("2.4", "Besleme hattı kablosu", "m", 3_400, 165.0, "35.140.1101"),
    ("2.5", "Kolon hattı kablosu", "m", 1_250, 410.0, "35.140.1208"),
    ("2.6", "Halojensiz kablo", "m", 5_800, 92.0, "35.150.3101"),
    ("2.7", "Gaz algılama kontrol paneli", "Ad", 3, 38_500.0, "35.420.1002"),
]


def _mep_positions() -> list[dict[str, Any]]:
    rows = [_section("25", "1"), _section("35", "2")]
    for ordinal, description, unit, quantity, rate, poz in _MEP_BILL:
        rows.append(
            {
                "id": f"p-{ordinal}",
                "parent_id": f"s-{ordinal.split('.')[0]}",
                "ordinal": ordinal,
                "description": description,
                "unit": unit,
                "quantity": float(quantity),
                "unit_rate": rate,
                "total": float(quantity) * rate,
                "classification": {"birimfiyat": poz},
                "type": "position",
            }
        )
    return rows


def _mep_stack() -> list[dict[str, Any]]:
    return [_markup("Yüklenici kârı ve genel giderler", "overhead", "25"), _markup("KDV", "tax", "20")]


@pytest.mark.parametrize("rule", ALL_RULES, ids=lambda r: r.rule_id)
def test_a_mechanical_and_electrical_bill_clears_every_rule(rule: type[ValidationRule]) -> None:
    results = _run(rule(), _mep_positions(), _mep_stack())
    assert _failed(results) == [], [r.message for r in _failed(results)]


def test_every_rule_actually_judged_the_mechanical_and_electrical_bill() -> None:
    """A rule that returned nothing would clear the bill without reading it."""
    judged = {rule.rule_id: len(_run(rule(), _mep_positions(), _mep_stack())) for rule in ALL_RULES}
    lines = len(_MEP_BILL)
    assert judged == {
        "birimfiyat.code_required": lines,
        "birimfiyat.valid_poz": lines + 2,
        "birimfiyat.chapter_recognised": lines + 2,
        "birimfiyat.unit_recognised": lines,
        "birimfiyat.poz_unit_consistent": lines,
        "birimfiyat.poz_rate_consistent": lines,
        "birimfiyat.own_item_analysed": 0,
        "birimfiyat.profit_overhead_once": 1,
    }


def test_the_same_bill_with_five_defects_is_reported_once_for_each() -> None:
    rows = _mep_positions()
    by_ordinal = {row["ordinal"]: row for row in rows}
    by_ordinal["1.5"]["classification"] = {"birimfiyat": "27.300.1406"}  # no chapter 27
    by_ordinal["1.8"]["unit"] = "lb"  # not a unit of the lists
    by_ordinal["2.5"]["classification"] = {"birimfiyat": "35.140.1101"}  # same poz as 2.4, another rate
    by_ordinal["1.7"]["classification"] = {"birimfiyat": "25.305.1104"}  # same poz as 1.6, another unit
    by_ordinal["2.7"]["classification"] = {"birimfiyat": "ÖZEL-1"}  # own item, nothing behind it
    stack = [*_mep_stack(), _markup("Genel giderler", "overhead", "25")]

    failed = {
        rule.rule_id: sorted(str(r.element_ref) for r in _failed(_run(rule(), rows, stack))) for rule in ALL_RULES
    }
    assert failed == {
        "birimfiyat.code_required": [],
        "birimfiyat.valid_poz": [],
        "birimfiyat.chapter_recognised": ["p-1.5"],
        "birimfiyat.unit_recognised": ["p-1.8"],
        "birimfiyat.poz_unit_consistent": ["p-1.6", "p-1.7"],
        "birimfiyat.poz_rate_consistent": ["p-2.4", "p-2.5"],
        "birimfiyat.own_item_analysed": ["p-2.7"],
        "birimfiyat.profit_overhead_once": ["None"],
    }
