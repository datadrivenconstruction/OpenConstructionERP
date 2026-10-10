# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Two Turkish rules read a bill against the unit-price book, and say so when they could not.

``birimfiyat.unit_matches_poz_definition`` and
``birimfiyat.unit_rate_within_published_price`` judge a line by what the
installed national cost base holds for its poz. The base reaches a rule as
data, so every test here hands the rule an in-memory catalogue and no database.

Three outcomes are kept apart, because folding any two of them together is how
a check comes to read green over something it never looked at:

* a value: the line was compared, and the result says what was found;
* held: the book could not be read, or the bill is in another currency, and
  ONE result for the bill says the check did not run and why;
* silence: the line is not one these rules judge, and another rule owns it.

The bill is a mechanical and electrical one. Its poz numbers and their units
are those of chapters 25 and 35 of the Ministry book. The prices are invented
for this file, round figures no book carries, and so are the descriptions: the
Ministry's price data is not reproduced in this repository.
"""

from __future__ import annotations

import asyncio
import re
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, ValidationRule, ValidationStatus
from app.core.validation.messages import is_key_present
from app.core.validation.poz_catalogue import (
    POZ_CATALOGUE_KEY,
    POZ_CATALOGUE_RULE_IDS,
    POZ_IN_CHUNK,
    TR_POZ_REGION,
    PozCatalogue,
    PozCatalogueState,
    PozEntry,
    PublishedPriceTolerance,
    load_poz_catalogue,
    rule_sets_reach_poz_catalogue,
    tolerance_from_document,
    with_poz_catalogue,
    with_poz_catalogue_for_rule_sets,
)
from app.core.validation.rules import (
    BirimFiyatRateAgainstPublished,
    BirimFiyatUnitMatchesPoz,
    ministry_poz_of,
    register_builtin_rules,
)

# (poz, unit as the book prints it, a description written for this test, an invented price)
_BOOK: list[tuple[str, str, str, str]] = [
    ("25.112.1203", "Tk", "Engelli klozet takımı", "9000.00"),
    ("25.182.1203", "Ad", "Sulama başlığı", "2000.00"),
    ("25.245.2005", "Ad", "Kollektör ağızlığı", "400.00"),
    ("25.305.6704", "m", "Pik boru", "1000.00"),
    ("25.330.3107", "Ad", "Kompansatör", "15000.00"),
    ("25.400.2562", "m", "Boru yalıtımı", "1200.00"),
    ("25.450.5105", "Ad", "Kanal tipi aspiratör", "11000.00"),
    ("25.495.2120", "Ad", "Su soğutma grubu", "14000000.00"),
    ("25.627.1124", "Ad", "Soğuk depo cihazı", "500000.00"),
    ("25.735.1100", "Ad", "Köpüklü yangın dolabı", "26000.00"),
    ("35.100.2201", "Ad", "Gömme tip pano", "3000.00"),
    ("35.100.7000", "Kg", "Bakır bara", "700.00"),
    ("35.120.2007", "Ad", "Otomatik transfer şalteri", "42000.00"),
    ("35.140.5210", "m", "Yeraltı kablosu", "900.00"),
    ("35.180.1315", "Ad", "Kesintisiz güç kaynağı", "700000.00"),
    ("35.410.3110", "Ad", "Yangın alarm kontrol ünitesi", "70000.00"),
    ("35.500.2407", "m", "Sinyal kablosu", "100.00"),
    ("35.515.4038", "m", "Halojensiz kumanda kablosu", "150.00"),
    ("35.545.6043", "Ad", "Fiber optik terminasyon birimi", "2200.00"),
    ("35.715.1353", "Ad", "Hidrolik yük asansörü", "980000.00"),
    ("35.740.5417", "Ad", "Ses izolasyon kabini", "360000.00"),
]

PIPE = "25.305.6704"  # m, 1000.00 in the test's book
UPS = "35.180.1315"  # Ad, 700000.00
CABLE = "35.140.5210"  # m, 900.00

RULES: tuple[type[ValidationRule], ...] = (BirimFiyatUnitMatchesPoz, BirimFiyatRateAgainstPublished)

_A_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def _entries(overrides: dict[str, PozEntry] | None = None) -> MappingProxyType[str, PozEntry]:
    book = {poz: PozEntry(code=poz, unit=unit, rate=Decimal(price), currency="TRY") for poz, unit, _, price in _BOOK}
    book.update(overrides or {})
    return MappingProxyType(book)


def _catalogue(
    state: PozCatalogueState = PozCatalogueState.LOADED,
    *,
    entries: MappingProxyType[str, PozEntry] | None = None,
    above: str | None = None,
    below: str | None = None,
) -> PozCatalogue:
    found = _entries() if entries is None else entries
    if state in (PozCatalogueState.NOT_INSTALLED, PozCatalogueState.UNAVAILABLE):
        found = MappingProxyType({})
    return PozCatalogue(
        region=TR_POZ_REGION,
        state=state,
        entries=found,
        asked=len(_BOOK),
        home_currency="TRY",
        tolerance=PublishedPriceTolerance(
            warn_above_percent=None if above is None else Decimal(above),
            warn_below_percent=None if below is None else Decimal(below),
            review_status="unconfirmed",
        ),
    )


def _line(poz: str = PIPE, unit: str = "m", rate: float = 1000.0, ordinal: str = "1.1", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"p-{ordinal}",
        "ordinal": ordinal,
        "description": "Tesisat kalemi",
        "unit": unit,
        "quantity": 10.0,
        "unit_rate": rate,
        "total": 10.0 * rate,
        "classification": {"birimfiyat": poz} if poz else {},
        "type": "position",
        **extra,
    }


def _mep_bill() -> list[dict[str, Any]]:
    """Every poz of the test's book once, in the book's unit and at the book's price."""
    rows: list[dict[str, Any]] = [
        {
            "id": "s-1",
            "ordinal": "1",
            "description": "Mekanik",
            "classification": {"birimfiyat": "25"},
            "type": "section",
        },
        {
            "id": "s-2",
            "ordinal": "2",
            "description": "Elektrik",
            "classification": {"birimfiyat": "35"},
            "type": "section",
        },
    ]
    for number, (poz, unit, description, price) in enumerate(_BOOK, start=1):
        chapter = "1" if poz.startswith("25") else "2"
        rows.append(
            _line(
                poz,
                unit,
                float(price),
                ordinal=f"{chapter}.{number}",
                description=description,
                parent_id=f"s-{chapter}",
            )
        )
    return rows


_NO_CURRENCY = object()


def _run(
    rule: type[ValidationRule],
    positions: list[dict[str, Any]],
    catalogue: PozCatalogue | None,
    *,
    currency: Any = "TRY",
    locale: str = "en",
) -> list[Any]:
    data: dict[str, Any] = {"positions": positions}
    if currency is not _NO_CURRENCY:
        data["project_record"] = {"currency": currency}
    if catalogue is not None:
        data = with_poz_catalogue(data, catalogue)
    return asyncio.run(rule().validate(ValidationContext(data=data, metadata={"locale": locale})))


def _failed(results: list[Any]) -> list[Any]:
    return [r for r in results if not r.passed]


# ── Shape ────────────────────────────────────────────────────────────────────


def test_the_two_rules_are_the_two_the_loader_gates_on() -> None:
    assert {rule.rule_id for rule in RULES} == set(POZ_CATALOGUE_RULE_IDS)
    assert {rule.standard for rule in RULES} == {"birimfiyat"}


def test_the_rate_rule_reports_only_as_shipped() -> None:
    """Its own severity is information; a warning exists only past a threshold somebody set."""
    assert BirimFiyatRateAgainstPublished.severity is Severity.INFO
    assert BirimFiyatUnitMatchesPoz.severity is Severity.WARNING


@pytest.mark.parametrize("locale", ["en", "tr"])
@pytest.mark.parametrize(
    "key",
    [
        "birimfiyat.unit_matches_poz_definition.fail",
        "birimfiyat.unit_matches_poz_definition.suggestion",
        "birimfiyat.unit_matches_poz_definition.not_installed",
        "birimfiyat.unit_matches_poz_definition.unavailable",
        "birimfiyat.unit_rate_within_published_price.below",
        "birimfiyat.unit_rate_within_published_price.above",
        "birimfiyat.unit_rate_within_published_price.fail",
        "birimfiyat.unit_rate_within_published_price.suggestion",
        "birimfiyat.unit_rate_within_published_price.repriced",
        "birimfiyat.unit_rate_within_published_price.currency_differs",
        "birimfiyat.unit_rate_within_published_price.currency_unknown",
    ],
)
def test_every_message_the_rules_can_emit_exists(key: str, locale: str) -> None:
    assert is_key_present(key, locale)


# ── Silence: nobody asked ────────────────────────────────────────────────────


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_id)
def test_a_payload_no_caller_put_a_catalogue_in_is_not_judged(rule: type[ValidationRule]) -> None:
    assert _run(rule, _mep_bill(), None) == []


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_id)
def test_something_else_under_the_key_is_not_mistaken_for_a_catalogue(rule: type[ValidationRule]) -> None:
    data = {"positions": _mep_bill(), POZ_CATALOGUE_KEY: {"state": "loaded"}}
    assert asyncio.run(rule().validate(ValidationContext(data=data))) == []


# ── Value: a bill that agrees with the book ──────────────────────────────────


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_id)
def test_a_mechanical_and_electrical_bill_priced_from_the_book_agrees_with_it(rule: type[ValidationRule]) -> None:
    results = _run(rule, _mep_bill(), _catalogue())
    assert len(results) == len(_BOOK), "every line citing a poz the book has must be judged, and no section row"
    assert _failed(results) == []
    assert {r.element_ref for r in results} == {row["id"] for row in _mep_bill() if row["type"] == "position"}


@pytest.mark.parametrize(
    ("typed", "book"),
    [
        ("adet", "Ad"),
        ("AD", "Ad"),
        ("Ad.", "Ad"),
        ("pcs", "Ad"),
        ("MT", "m"),
        ("Metre", "m"),
        ("takım", "Tk"),
        ("TK", "Tk"),
        ("set", "Tk"),
        ("KG", "Kg"),
        ("m2", "m²"),
        ("M²", "m²"),
        ("m3", "m³"),
        ("M3", "m³"),
    ],
)
def test_a_unit_spelled_another_way_is_the_same_unit(typed: str, book: str) -> None:
    """The six units chapters 25 and 35 measure in, each in the spellings a bill uses.

    The book unit is set by the test, so that all six are covered whatever the
    unit of the poz it is attached to.
    """
    entries = _entries({PIPE: PozEntry(code=PIPE, unit=book, rate=Decimal("1000.00"), currency="TRY")})
    results = _run(BirimFiyatUnitMatchesPoz, [_line(PIPE, typed)], _catalogue(entries=entries))
    assert len(results) == 1
    assert results[0].passed, results[0].message


# ── Value: the unit differs ──────────────────────────────────────────────────


def test_a_line_in_another_unit_than_the_book_is_a_warning_naming_all_three() -> None:
    results = _run(BirimFiyatUnitMatchesPoz, [_line(UPS, "m", 700000.0, ordinal="2.4")], _catalogue())
    assert len(results) == 1
    finding = results[0]
    assert not finding.passed
    assert finding.severity is Severity.WARNING
    assert finding.element_ref == "p-2.4"
    for expected in (UPS, "'m'", "'Ad'", "2.4"):
        assert expected in finding.message
    assert finding.suggestion
    assert finding.details["book_unit"] == "Ad"
    assert finding.details["given_unit"] == "m"


def test_a_bulk_unit_is_not_the_plain_unit_the_book_defines() -> None:
    results = _run(BirimFiyatUnitMatchesPoz, [_line(PIPE, "100 m")], _catalogue())
    assert len(_failed(results)) == 1


def test_a_rate_per_another_unit_is_compared_with_nothing() -> None:
    """The unit rule reports the line; a second finding about its rate would be noise."""
    assert _run(BirimFiyatRateAgainstPublished, [_line(UPS, "m", 1.0)], _catalogue()) == []


# ── Value: the rate differs ──────────────────────────────────────────────────


def test_a_rate_below_the_published_price_is_stated_as_information() -> None:
    results = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 880.0, ordinal="1.4")], _catalogue())
    assert len(results) == 1
    finding = results[0]
    assert not finding.passed
    assert finding.severity is Severity.INFO
    assert finding.element_ref == "p-1.4"
    assert "12.0 percent below" in finding.message
    assert "880.00 TRY" in finding.message
    assert "1,000.00 TRY" in finding.message
    assert PIPE in finding.message
    assert finding.details["direction"] == "below"
    assert finding.details["difference_percent"] == "12.0"
    assert finding.details["published_price"] == "1000.00"


def test_a_rate_above_the_published_price_is_stated_as_information() -> None:
    results = _run(BirimFiyatRateAgainstPublished, [_line(CABLE, "m", 1035.0)], _catalogue())
    assert len(results) == 1
    assert results[0].severity is Severity.INFO
    assert not results[0].passed
    assert "15.0 percent above" in results[0].message
    assert results[0].details["direction"] == "above"


@pytest.mark.parametrize("rate", [1.0, 500.0, 4000.0, 1_000_000.0])
def test_no_difference_is_a_warning_while_the_thresholds_are_unset(rate: float) -> None:
    """Unset is not zero: however far the rate sits, the shipped rule only reports."""
    results = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", rate)], _catalogue())
    assert [r.severity for r in results] == [Severity.INFO]
    assert not results[0].passed


def test_a_message_never_names_the_year_of_a_book_it_cannot_know() -> None:
    """The base stores no edition, so a year in the text would be invented."""
    for locale in ("en", "tr"):
        for rate in (880.0, 1150.0):
            finding = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", rate)], _catalogue(), locale=locale)[0]
            assert not _A_YEAR.search(finding.message), finding.message
            assert not _A_YEAR.search(finding.suggestion or ""), finding.suggestion
            assert finding.details["edition"] is None
    held = _run(BirimFiyatUnitMatchesPoz, _mep_bill(), _catalogue(PozCatalogueState.NOT_INSTALLED))[0]
    assert not _A_YEAR.search(held.message)


def test_the_advice_states_the_25_percent_from_the_one_constant() -> None:
    finding = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 880.0)], _catalogue())[0]
    assert "25 percent" in (finding.suggestion or "")


def test_a_difference_past_a_threshold_somebody_set_is_a_warning() -> None:
    catalogue = _catalogue(above="10")
    over = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 1120.0)], catalogue)[0]
    assert over.severity is Severity.WARNING
    assert not over.passed
    assert "12.0 percent above" in over.message
    assert "10.0 percent" in over.message
    assert over.details["warn_above_percent"] == "10"

    within = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 1080.0)], catalogue)[0]
    assert within.severity is Severity.INFO
    assert "8.0 percent above" in within.message

    exactly = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 1100.0)], catalogue)[0]
    assert exactly.severity is Severity.INFO, "the threshold itself is allowed; only more than it is a warning"


def test_a_threshold_in_one_direction_says_nothing_about_the_other() -> None:
    """A tender discount stays information when only the upper bound is set."""
    discounted = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 600.0)], _catalogue(above="10"))[0]
    assert discounted.severity is Severity.INFO
    assert "40.0 percent below" in discounted.message

    too_low = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 600.0)], _catalogue(below="20"))[0]
    assert too_low.severity is Severity.WARNING
    raised = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 1600.0)], _catalogue(below="20"))[0]
    assert raised.severity is Severity.INFO


def test_a_line_not_priced_yet_has_no_rate_to_compare() -> None:
    assert _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 0.0)], _catalogue()) == []


def test_a_book_row_without_a_readable_price_is_not_compared() -> None:
    entries = _entries({PIPE: PozEntry(code=PIPE, unit="m", rate=None, currency="TRY")})
    assert _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 880.0)], _catalogue(entries=entries)) == []


# ── Silence: lines another rule owns ─────────────────────────────────────────


@pytest.mark.parametrize(
    "poz",
    [
        "",  # no poz: birimfiyat.code_required
        "ÖZEL-1",  # the bill's own item: birimfiyat.own_item_analysed
        "04.613/1A",  # the older numbering: no current book carries it
        "25,305,6704",  # malformed: birimfiyat.valid_poz
        "99.100.1001",  # no such chapter: birimfiyat.chapter_recognised
        "25.305.9999",  # a Ministry chapter, but not a number the installed book has
    ],
)
@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_id)
def test_a_line_these_rules_do_not_judge_gets_nothing_from_them(rule: type[ValidationRule], poz: str) -> None:
    assert _run(rule, [_line(poz, "Ad", 5.0)], _catalogue()) == []


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.rule_id)
def test_another_publishers_list_is_left_alone_even_when_the_base_carries_it(rule: type[ValidationRule]) -> None:
    """Chapter 43 is another institution's list; the Ministry's are 10, 15, 19, 25 and 35."""
    other = "43.560.1101"
    entries = _entries({other: PozEntry(code=other, unit="m", rate=Decimal("300.00"), currency="TRY")})
    assert ministry_poz_of(_line(other)) is None
    assert _run(rule, [_line(other, "Ad", 1.0)], _catalogue(entries=entries)) == []


def test_a_unit_the_lists_do_not_use_is_left_to_the_rule_that_says_so() -> None:
    assert _run(BirimFiyatUnitMatchesPoz, [_line(PIPE, "fathom")], _catalogue()) == []


def test_the_poz_is_looked_up_as_the_other_rules_read_it() -> None:
    assert ministry_poz_of(_line("  25.305.6704 ")) == PIPE
    assert ministry_poz_of(_line("ÖZEL-1")) is None
    assert ministry_poz_of(_line("")) is None
    assert ministry_poz_of({"classification": None}) is None


# ── Held: another currency ───────────────────────────────────────────────────


def test_a_bill_in_another_currency_is_held_once_with_the_reason() -> None:
    results = _run(BirimFiyatRateAgainstPublished, _mep_bill(), _catalogue(), currency="EUR")
    assert len(results) == 1, "one result for the bill, not one for each of its lines"
    held = results[0]
    assert held.severity is Severity.INFO
    assert not held.passed
    assert held.element_ref is None
    assert "EUR" in held.message
    assert "TRY" in held.message
    assert str(len(_BOOK)) in held.message
    assert held.details["held"] == "currency_differs"


def test_the_unit_check_does_not_depend_on_the_currency() -> None:
    results = _run(BirimFiyatUnitMatchesPoz, _mep_bill(), _catalogue(), currency="EUR")
    assert len(results) == len(_BOOK)
    assert _failed(results) == []


def test_a_line_priced_in_its_own_currency_is_held_and_the_rest_are_compared() -> None:
    bill = [
        _line(PIPE, "m", 1000.0, ordinal="1.1"),
        _line(CABLE, "m", 30.0, ordinal="1.2", metadata={"currency": "usd"}),
    ]
    results = _run(BirimFiyatRateAgainstPublished, bill, _catalogue())
    assert [r.passed for r in results] == [True, False]
    assert results[0].element_ref == "p-1.1"
    assert results[1].details["held"] == "currency_differs"
    assert "USD" in results[1].message


def test_a_bill_whose_currency_nobody_recorded_is_held_not_assumed_to_be_lira() -> None:
    for currency in (_NO_CURRENCY, "", None):
        results = _run(BirimFiyatRateAgainstPublished, _mep_bill(), _catalogue(), currency=currency)
        assert len(results) == 1
        assert results[0].details["held"] == "currency_unknown"
        assert results[0].severity is Severity.INFO
        assert not results[0].passed


# ── Held: the book could not be read ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("state", "reason"),
    [(PozCatalogueState.NOT_INSTALLED, "not_installed"), (PozCatalogueState.UNAVAILABLE, "unavailable")],
)
def test_a_book_that_was_not_read_is_reported_once_never_passed_and_never_failed(
    state: PozCatalogueState, reason: str
) -> None:
    results = _run(BirimFiyatUnitMatchesPoz, _mep_bill(), _catalogue(state))
    assert len(results) == 1, "never one result per line"
    held = results[0]
    assert not held.passed, "a check that did not run is not a pass"
    assert held.severity is Severity.INFO, "and it is not a failure of the bill"
    assert held.element_ref is None
    assert TR_POZ_REGION in held.message
    assert str(len(_BOOK)) in held.message
    assert held.details["held"] == reason


@pytest.mark.parametrize("state", [PozCatalogueState.NOT_INSTALLED, PozCatalogueState.UNAVAILABLE])
def test_the_rate_rule_says_it_itself_only_when_the_unit_rule_is_not_there_to(
    state: PozCatalogueState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(BirimFiyatRateAgainstPublished, "_unit_rule_reports", staticmethod(lambda: True))
    assert _run(BirimFiyatRateAgainstPublished, _mep_bill(), _catalogue(state)) == []

    monkeypatch.setattr(BirimFiyatRateAgainstPublished, "_unit_rule_reports", staticmethod(lambda: False))
    results = _run(BirimFiyatRateAgainstPublished, _mep_bill(), _catalogue(state))
    assert len(results) == 1
    assert results[0].rule_id == BirimFiyatRateAgainstPublished.rule_id
    assert results[0].severity is Severity.INFO
    assert not results[0].passed


@pytest.mark.parametrize("state", [PozCatalogueState.NOT_INSTALLED, PozCatalogueState.UNAVAILABLE])
def test_through_the_engine_an_unread_book_is_one_information_result_for_the_bill(state: PozCatalogueState) -> None:
    from app.core.validation.engine import validation_engine

    register_builtin_rules()
    data = with_poz_catalogue({"positions": _mep_bill(), "project_record": {"currency": "TRY"}}, _catalogue(state))
    report = asyncio.run(validation_engine.validate(data=data, rule_sets=["birimfiyat"], metadata={"locale": "en"}))
    ours = [r for r in report.results if r.rule_id in POZ_CATALOGUE_RULE_IDS]
    assert len(ours) == 1
    assert ours[0].severity is Severity.INFO
    assert not ours[0].passed
    assert not report.has_errors
    assert report.status is not ValidationStatus.PASSED, "a bill nobody checked against the book is not reported clean"


def test_a_base_priced_into_another_market_holds_the_rates_and_still_checks_the_units() -> None:
    catalogue = _catalogue(PozCatalogueState.REPRICED)
    rates = _run(BirimFiyatRateAgainstPublished, _mep_bill(), catalogue)
    assert len(rates) == 1
    assert rates[0].severity is Severity.INFO
    assert not rates[0].passed
    assert rates[0].element_ref is None
    assert rates[0].details["held"] == "repriced"
    assert TR_POZ_REGION in rates[0].message

    units = _run(BirimFiyatUnitMatchesPoz, [*_mep_bill(), _line(UPS, "m", ordinal="9.9")], catalogue)
    assert len(units) == len(_BOOK) + 1, "a market switch rewrites prices, not units"
    assert [r.element_ref for r in _failed(units)] == ["p-9.9"]


# ── Turkish ──────────────────────────────────────────────────────────────────


def test_a_turkish_reader_gets_turkish_with_its_own_letters() -> None:
    unit = _run(BirimFiyatUnitMatchesPoz, [_line(UPS, "m")], _catalogue(), locale="tr")[0]
    assert "poz" in unit.message
    assert "ölçülmüş" in unit.message
    rate = _run(BirimFiyatRateAgainstPublished, [_line(PIPE, "m", 880.0)], _catalogue(), locale="tr")[0]
    assert "yüzde 12.0 altında" in rate.message
    assert "yüklenici kârı" in (rate.suggestion or "")
    held = _run(BirimFiyatUnitMatchesPoz, _mep_bill(), _catalogue(PozCatalogueState.NOT_INSTALLED), locale="tr")[0]
    assert "yüklü değil" in held.message


# ── The caller's side: who pays for the lookup ───────────────────────────────


class _Untouchable:
    """A session that fails the test the moment anything is asked of it."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the session was touched ({name}) for a run that reads no price book")


def test_a_run_that_reaches_neither_rule_pays_nothing() -> None:
    register_builtin_rules()
    assert rule_sets_reach_poz_catalogue(["birimfiyat"])
    assert rule_sets_reach_poz_catalogue(["boq_quality", "birimfiyat", "project_completeness"])
    for other in (["boq_quality"], ["din276", "gaeb", "boq_quality"], ["nrm"], ["italy"], [], ["no_such_set"]):
        assert not rule_sets_reach_poz_catalogue(other), other
        data = {"positions": _mep_bill()}
        out = asyncio.run(with_poz_catalogue_for_rule_sets(_Untouchable(), data, other))  # type: ignore[arg-type]
        assert out is data, "the payload of another country's bill is handed back as it came"
        assert POZ_CATALOGUE_KEY not in out


def test_a_turkish_run_with_no_session_is_held_as_unavailable_not_skipped() -> None:
    register_builtin_rules()
    bill = [*_mep_bill(), _line("ÖZEL-1", "Ad"), _line("43.560.1101", "m"), _line(PIPE, "m", ordinal="7.7")]
    data = {"positions": bill}
    out = asyncio.run(with_poz_catalogue_for_rule_sets(None, data, ["birimfiyat"]))
    assert POZ_CATALOGUE_KEY not in data, "the caller's mapping is left as it was"
    catalogue = out[POZ_CATALOGUE_KEY]
    assert catalogue.state is PozCatalogueState.UNAVAILABLE
    assert catalogue.asked == len(_BOOK), "distinct Ministry poz only: no own item, no other publisher, no duplicate"


def test_a_bill_citing_no_ministry_poz_asks_the_database_nothing() -> None:
    catalogue = asyncio.run(load_poz_catalogue(_Untouchable(), []))  # type: ignore[arg-type]
    assert catalogue.state is PozCatalogueState.LOADED
    assert catalogue.asked == 0
    assert dict(catalogue.entries) == {}


def test_the_catalogue_cannot_be_written_to_by_a_rule() -> None:
    catalogue = _catalogue()
    with pytest.raises(TypeError):
        catalogue.entries["25.000.0000"] = PozEntry("25.000.0000", "m", Decimal(1), "TRY")  # type: ignore[index]
    with pytest.raises(AttributeError):
        catalogue.state = PozCatalogueState.NOT_INSTALLED  # type: ignore[misc]
    with pytest.raises(TypeError):
        PozCatalogue(region="X", state=PozCatalogueState.LOADED).entries["a"] = None  # type: ignore[index]


def test_one_statement_carries_a_5000_line_bill() -> None:
    """asyncpg takes 32,767 bind parameters; one chunk plus the two other binds stays far below."""
    assert POZ_IN_CHUNK >= 5000
    assert POZ_IN_CHUNK + 2 < 32767


# ── The thresholds are data, and unset stays unset ───────────────────────────


def test_thresholds_are_read_as_written_and_nothing_is_supplied_for_a_missing_one() -> None:
    unset = tolerance_from_document({"published_price_comparison": {"warn_above_percent": None}})
    assert unset.warn_above_percent is None
    assert unset.warn_below_percent is None

    stated = tolerance_from_document(
        {"published_price_comparison": {"warn_above_percent": 15, "warn_below_percent": "32.5", "review_status": "x"}}
    )
    assert stated.warn_above_percent == Decimal("15")
    assert stated.warn_below_percent == Decimal("32.5")
    assert stated.review_status == "x"

    assert tolerance_from_document({"published_price_comparison": {"warn_above_percent": 0}}).warn_above_percent == 0


@pytest.mark.parametrize(
    "document", [None, {}, {"published_price_comparison": None}, {"published_price_comparison": []}]
)
def test_a_document_without_the_block_sets_no_threshold(document: Any) -> None:
    assert tolerance_from_document(document) == PublishedPriceTolerance()


@pytest.mark.parametrize("written", ["fifteen", -5, True, "", float("nan"), float("inf"), [15]])
def test_an_unreadable_threshold_is_unset_not_guessed(written: Any) -> None:
    tolerance = tolerance_from_document({"published_price_comparison": {"warn_above_percent": written}})
    assert tolerance.warn_above_percent is None
