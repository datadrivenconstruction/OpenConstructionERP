# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``project_completeness`` rule set, rule by rule and as a set.

Twenty two demo templates named this set while nothing registered into it, so
the first thing asserted here is that the name now resolves to exactly these
rules and to nothing from another concern: the set once read as implemented
because a carbon rule was registered into it as a second home, and one rule is
enough to make a whole set resolve.

The rules read the project record the shared payload builder carries, not the
bill, so the second thing asserted is the silence contract: a payload with no
record, or a null one, produces no result from any rule. A completeness finding
about a project the rule has not seen would be a finding about the payload.

Then each rule in both directions, and finally that every message key each
rule can emit exists in every locale the catalogue ships, so a finding in
German or Russian is a sentence and not a humanised key.

Pure Python, no database.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext, ValidationRule, rule_registry
from app.core.validation.messages import available_locales, is_key_present, translate
from app.core.validation.project_context import PROJECT_CONTEXT_KEYS, PROJECT_RECORD_KEY, with_project_context
from app.core.validation.rules import register_builtin_rules
from app.core.validation.rules.project_completeness import (
    POST_ESTIMATING_PHASES,
    PROJECT_COMPLETENESS_RULE_SET,
    PROJECT_COMPLETENESS_RULES,
    ProjectBillsHaveBaseDate,
    ProjectClassificationStandardSet,
    ProjectClientRecorded,
    ProjectCountrySet,
    ProjectCurrencyMatchesBill,
    ProjectCurrencySet,
    ProjectDatesOrdered,
    ProjectDatesSet,
    ProjectHasPricedBill,
    ProjectProcurementStarted,
)

EXPECTED_RULE_IDS = {
    "project_completeness.country_set",
    "project_completeness.currency_set",
    "project_completeness.currency_matches_bill",
    "project_completeness.priced_bill_present",
    "project_completeness.bill_base_date_set",
    "project_completeness.classification_standard_set",
    "project_completeness.planned_dates_set",
    "project_completeness.planned_dates_ordered",
    "project_completeness.client_recorded",
    "project_completeness.procurement_started",
}

#: Every message key a rule can emit, by rule id. Listed rather than derived
#: from the source so a rule that grows a new failure branch has to be
#: registered here, where the locale sweep below will find its translations
#: missing.
MESSAGE_KEYS: dict[str, tuple[str, ...]] = {
    "project_completeness.country_set": ("fail", "suggestion"),
    "project_completeness.currency_set": ("fail", "suggestion"),
    "project_completeness.currency_matches_bill": ("fail", "suggestion"),
    "project_completeness.priced_bill_present": ("fail", "suggestion"),
    "project_completeness.bill_base_date_set": ("fail", "suggestion"),
    "project_completeness.classification_standard_set": ("fail", "suggestion"),
    "project_completeness.planned_dates_set": (
        "both_missing",
        "start_missing",
        "end_missing",
        "unreadable",
        "suggestion",
    ),
    "project_completeness.planned_dates_ordered": ("fail", "suggestion"),
    "project_completeness.client_recorded": ("fail", "suggestion"),
    "project_completeness.procurement_started": ("fail", "suggestion"),
}


def bill(**overrides: Any) -> dict[str, Any]:
    """One bill as the payload builder describes it."""
    base: dict[str, Any] = {
        "id": "b1",
        "name": "Estimate",
        "status": "draft",
        "base_date": "2026-Q1",
        "metadata": {},
        "position_count": 12,
    }
    return {**base, **overrides}


def record(**overrides: Any) -> dict[str, Any]:
    """A complete project record; each test breaks exactly the field it is about."""
    base: dict[str, Any] = {
        "id": "p1",
        "name": "Quay",
        "country_code": "DE",
        "region": "DACH",
        "currency": "EUR",
        "classification_standard": "din276",
        "status": "active",
        "phase": None,
        "planned_start_date": "2026-04-01",
        "planned_end_date": "2027-03-31",
        "client_id": "c-1",
        "bills": [bill()],
        "contract_count": 0,
        "client_party_count": 0,
        "tender_count": 0,
    }
    return {**base, **overrides}


def context(project: dict[str, Any] | None = None, *, positions: list[dict] | None = None, **meta: Any) -> Any:
    """A validation context whose payload carries ``project`` under the builder's key."""
    data: dict[str, Any] = {"positions": positions or []}
    if project is not None or "record_is_null" in meta:
        data[PROJECT_RECORD_KEY] = project
    meta.pop("record_is_null", None)
    return ValidationContext(data=data, metadata=meta)


def run(rule: ValidationRule, ctx: ValidationContext) -> list:
    return asyncio.run(rule.validate(ctx))


def only(results: list) -> Any:
    assert len(results) == 1, f"expected exactly one result, got {len(results)}: {results}"
    return results[0]


# ── the set ───────────────────────────────────────────────────────────────


def test_the_set_resolves_to_exactly_these_rules() -> None:
    """The name twenty two demos ask for resolves to these rules and no others."""
    register_builtin_rules()
    assert rule_registry.has_rules(PROJECT_COMPLETENESS_RULE_SET)
    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([PROJECT_COMPLETENESS_RULE_SET])}
    assert registered == EXPECTED_RULE_IDS, (
        f"missing: {sorted(EXPECTED_RULE_IDS - registered)}; foreign: {sorted(registered - EXPECTED_RULE_IDS)}"
    )


def test_every_rule_belongs_to_the_set_and_is_named_under_it() -> None:
    ids = [rule_class.rule_id for rule_class in PROJECT_COMPLETENESS_RULES]
    assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"
    assert set(ids) == EXPECTED_RULE_IDS
    for rule_class in PROJECT_COMPLETENESS_RULES:
        assert rule_class.standard == PROJECT_COMPLETENESS_RULE_SET
        assert rule_class.rule_id.startswith(PROJECT_COMPLETENESS_RULE_SET + ".")
        assert rule_class.rule_id in MESSAGE_KEYS, f"{rule_class.rule_id} has no message keys listed"


def test_country_and_currency_block_and_everything_else_warns() -> None:
    errors = {rule_class.rule_id for rule_class in PROJECT_COMPLETENESS_RULES if rule_class.severity == Severity.ERROR}
    assert errors == {"project_completeness.country_set", "project_completeness.currency_set"}
    for rule_class in PROJECT_COMPLETENESS_RULES:
        if rule_class.rule_id not in errors:
            assert rule_class.severity == Severity.WARNING, rule_class.rule_id
        assert rule_class.category in {RuleCategory.COMPLETENESS, RuleCategory.CONSISTENCY}, rule_class.rule_id


def test_the_builder_declares_the_key_the_rules_read() -> None:
    """A surface reaching the engine through the builder carries the record key."""
    assert PROJECT_RECORD_KEY in PROJECT_CONTEXT_KEYS


async def test_the_builder_without_a_session_writes_a_null_record() -> None:
    """No database in scope: the key is written, and its value says nothing answered."""
    payload = await with_project_context(None, "not-a-uuid", {"positions": [{"id": "x"}]})
    assert payload["positions"] == [{"id": "x"}]
    assert PROJECT_RECORD_KEY in payload
    assert payload[PROJECT_RECORD_KEY] is None


# ── the silence contract ──────────────────────────────────────────────────


@pytest.mark.parametrize("rule_class", PROJECT_COMPLETENESS_RULES, ids=lambda cls: cls.rule_id)
def test_every_rule_is_silent_when_nobody_asked_about_the_project(rule_class: type[ValidationRule]) -> None:
    """A payload without the record key was built by a surface that never asked."""
    assert run(rule_class(), context(None, positions=[{"id": "p", "currency": "USD"}])) == []


@pytest.mark.parametrize("rule_class", PROJECT_COMPLETENESS_RULES, ids=lambda cls: cls.rule_id)
def test_every_rule_is_silent_when_the_project_could_not_be_found(rule_class: type[ValidationRule]) -> None:
    """A null record says the question was asked and no project answered."""
    assert run(rule_class(), context(None, record_is_null=True)) == []


@pytest.mark.parametrize("rule_class", PROJECT_COMPLETENESS_RULES, ids=lambda cls: cls.rule_id)
def test_a_complete_project_produces_no_failure(rule_class: type[ValidationRule]) -> None:
    results = run(rule_class(), context(record(phase="tender", tender_count=1)))
    assert all(result.passed for result in results), [result.message for result in results]


# ── country ───────────────────────────────────────────────────────────────


def test_country_passes_on_a_two_letter_code() -> None:
    result = only(run(ProjectCountrySet(), context(record(country_code="jp"))))
    assert result.passed
    assert result.details["country_code"] == "JP"


@pytest.mark.parametrize("value", [None, "", "  ", "Germany", "D"])
def test_country_fails_when_no_code_is_recorded(value: str | None) -> None:
    result = only(run(ProjectCountrySet(), context(record(country_code=value))))
    assert not result.passed
    assert result.severity == Severity.ERROR
    assert result.suggestion


def test_the_region_default_is_not_evidence_of_a_country() -> None:
    """Every project carries a region because the column has a default."""
    result = only(run(ProjectCountrySet(), context(record(country_code=None, region="DACH"))))
    assert not result.passed
    assert result.details == {"country_code": None, "region": "DACH"}


# ── currency ──────────────────────────────────────────────────────────────


def test_currency_passes_when_stated() -> None:
    assert only(run(ProjectCurrencySet(), context(record(currency="inr")))).passed


@pytest.mark.parametrize("value", [None, "", "   "])
def test_currency_fails_when_empty(value: str | None) -> None:
    result = only(run(ProjectCurrencySet(), context(record(currency=value))))
    assert not result.passed
    assert result.severity == Severity.ERROR


def test_bill_currency_passes_when_every_row_is_in_the_project_currency() -> None:
    rows = [{"id": "1", "currency": "EUR"}, {"id": "2", "metadata": {"currency": "eur"}}]
    result = only(run(ProjectCurrencyMatchesBill(), context(record(), positions=rows)))
    assert result.passed
    assert result.details["bill_currencies"] == ["EUR"]


def test_bill_currency_fails_on_a_row_in_another_currency() -> None:
    rows = [{"id": "1", "currency": "EUR"}, {"id": "2", "currency": "USD"}, {"id": "3", "currency": "USD"}]
    result = only(run(ProjectCurrencyMatchesBill(), context(record(), positions=rows)))
    assert not result.passed
    assert result.severity == Severity.WARNING
    assert result.category == RuleCategory.CONSISTENCY
    assert result.details == {"project_currency": "EUR", "bill_currencies": ["EUR", "USD"], "rows_in_other_currency": 2}
    assert "USD" in result.message and "EUR" in result.message


def test_bill_currency_is_silent_when_no_row_states_a_currency() -> None:
    rows = [{"id": "1"}, {"id": "2", "metadata": {}}]
    assert run(ProjectCurrencyMatchesBill(), context(record(), positions=rows)) == []


def test_bill_currency_is_silent_when_the_project_has_none() -> None:
    """The project currency rule already speaks; a second finding would count the gap twice."""
    rows = [{"id": "1", "currency": "USD"}]
    assert run(ProjectCurrencyMatchesBill(), context(record(currency=""), positions=rows)) == []


# ── bills ─────────────────────────────────────────────────────────────────


def test_priced_bill_passes_when_one_bill_has_rows() -> None:
    bills = [bill(id="a", position_count=0), bill(id="b", position_count=3)]
    result = only(run(ProjectHasPricedBill(), context(record(bills=bills))))
    assert result.passed
    assert result.details == {"bills": 2, "bills_with_positions": 1}


@pytest.mark.parametrize("bills", [[], [bill(position_count=0)], [bill(position_count=None)]])
def test_priced_bill_fails_without_a_bill_that_has_rows(bills: list) -> None:
    result = only(run(ProjectHasPricedBill(), context(record(bills=bills))))
    assert not result.passed
    assert result.severity == Severity.WARNING


def test_priced_bill_is_silent_when_the_bills_could_not_be_listed() -> None:
    assert run(ProjectHasPricedBill(), context(record(bills=None))) == []


@pytest.mark.parametrize(
    "the_bill",
    [
        bill(base_date="2026-03-15", metadata={}),
        bill(base_date=None, metadata={"base_date": "2026-Q2"}),
        bill(base_date=None, metadata={"price_level": "Tokyo 2026"}),
    ],
    ids=["column", "metadata_base_date", "metadata_price_level"],
)
def test_base_date_is_read_from_the_column_or_the_imported_metadata(the_bill: dict) -> None:
    result = only(run(ProjectBillsHaveBaseDate(), context(record(bills=[the_bill]))))
    assert result.passed
    assert result.element_ref == "b1"


def test_base_date_fails_per_bill_and_links_the_bill() -> None:
    bills = [bill(id="a", name="Dated", base_date="2026-Q1"), bill(id="b", name="Undated", base_date=None)]
    results = run(ProjectBillsHaveBaseDate(), context(record(bills=bills)))
    assert [(r.element_ref, r.passed) for r in results] == [("a", True), ("b", False)]
    failed = results[1]
    assert failed.severity == Severity.WARNING
    assert "Undated" in failed.message
    assert failed.details == {"bill": "Undated", "base_date": None}


def test_base_date_is_silent_with_no_bills() -> None:
    """The gap belongs to the priced-bill rule; two findings would double count it."""
    assert run(ProjectBillsHaveBaseDate(), context(record(bills=[]))) == []
    assert run(ProjectBillsHaveBaseDate(), context(record(bills=None))) == []


# ── classification ────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["din276", "NRM", "masterformat", "sekisan"])
def test_classification_passes_on_a_named_standard(value: str) -> None:
    assert only(run(ProjectClassificationStandardSet(), context(record(classification_standard=value)))).passed


@pytest.mark.parametrize("value", [None, "", "none", "None", "null"])
def test_classification_fails_when_none_is_chosen(value: str | None) -> None:
    result = only(run(ProjectClassificationStandardSet(), context(record(classification_standard=value))))
    assert not result.passed
    assert result.severity == Severity.WARNING


# ── dates ─────────────────────────────────────────────────────────────────


def test_dates_pass_when_both_read_as_dates() -> None:
    result = only(run(ProjectDatesSet(), context(record(planned_start_date="2026-04-01T00:00:00Z"))))
    assert result.passed


@pytest.mark.parametrize(
    ("start", "end", "key", "unreadable"),
    [
        (None, None, "both_missing", None),
        ("", "  ", "both_missing", None),
        (None, "2027-03-31", "start_missing", None),
        ("2026-04-01", None, "end_missing", None),
        ("Q2 2026", "2027-03-31", "unreadable", "Q2 2026"),
        ("2026-04-01", "soon", "unreadable", "soon"),
    ],
)
def test_dates_fail_with_the_message_that_names_the_gap(
    start: str | None, end: str | None, key: str, unreadable: str | None
) -> None:
    result = only(run(ProjectDatesSet(), context(record(planned_start_date=start, planned_end_date=end))))
    assert not result.passed
    assert result.severity == Severity.WARNING
    params = {"value": unreadable} if unreadable is not None else {}
    assert result.message == translate(f"project_completeness.planned_dates_set.{key}", **params)
    if unreadable is not None:
        assert unreadable in result.message


def test_dates_ordered_passes_when_start_is_not_after_end() -> None:
    assert only(run(ProjectDatesOrdered(), context(record()))).passed
    same_day = record(planned_start_date="2026-04-01", planned_end_date="2026-04-01")
    assert only(run(ProjectDatesOrdered(), context(same_day))).passed


def test_dates_ordered_fails_when_the_project_ends_before_it_starts() -> None:
    reversed_dates = record(planned_start_date="2027-03-31", planned_end_date="2026-04-01")
    result = only(run(ProjectDatesOrdered(), context(reversed_dates)))
    assert not result.passed
    assert result.category == RuleCategory.CONSISTENCY
    assert result.details == {"planned_start_date": "2027-03-31", "planned_end_date": "2026-04-01"}
    assert "2027-03-31" in result.message and "2026-04-01" in result.message


@pytest.mark.parametrize(
    ("start", "end"),
    [(None, None), ("2026-04-01", None), (None, "2027-03-31"), ("not a date", "2027-03-31")],
)
def test_dates_ordered_is_silent_unless_both_dates_read(start: str | None, end: str | None) -> None:
    """The dates-set rule owns the missing and unreadable cases."""
    assert run(ProjectDatesOrdered(), context(record(planned_start_date=start, planned_end_date=end))) == []


# ── client ────────────────────────────────────────────────────────────────


def test_client_passes_on_the_project_client() -> None:
    assert only(run(ProjectClientRecorded(), context(record(client_id="c-1", client_party_count=0)))).passed


def test_client_passes_on_an_employer_party_on_a_contract() -> None:
    result = only(run(ProjectClientRecorded(), context(record(client_id=None, client_party_count=1))))
    assert result.passed
    assert result.details == {"client_id": None, "client_party_count": 1}


@pytest.mark.parametrize("parties", [0, None])
def test_client_fails_with_neither(parties: int | None) -> None:
    result = only(run(ProjectClientRecorded(), context(record(client_id="", client_party_count=parties))))
    assert not result.passed
    assert result.severity == Severity.WARNING


# ── procurement ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("phase", [None, "", "concept", "design", "Design", "something_else"])
def test_procurement_is_silent_while_the_project_is_still_estimating(phase: str | None) -> None:
    assert run(ProjectProcurementStarted(), context(record(phase=phase, contract_count=0, tender_count=0))) == []


@pytest.mark.parametrize("phase", sorted(POST_ESTIMATING_PHASES))
def test_procurement_fails_past_estimating_with_neither_contract_nor_tender(phase: str) -> None:
    result = only(run(ProjectProcurementStarted(), context(record(phase=phase, contract_count=0, tender_count=0))))
    assert not result.passed
    assert result.severity == Severity.WARNING
    assert phase in result.message
    assert result.details == {"phase": phase, "contract_count": 0, "tender_count": 0}


def test_procurement_passes_on_a_contract_or_a_tender_package() -> None:
    assert only(run(ProjectProcurementStarted(), context(record(phase="construction", contract_count=1)))).passed
    assert only(run(ProjectProcurementStarted(), context(record(phase="TENDER", tender_count=2)))).passed


def test_procurement_is_silent_when_neither_register_could_be_asked() -> None:
    """No register and an empty register are different facts; only the second is a finding."""
    unknown = record(phase="tender", contract_count=None, tender_count=None)
    assert run(ProjectProcurementStarted(), context(unknown)) == []


def test_procurement_judges_on_the_register_it_could_ask() -> None:
    result = only(
        run(ProjectProcurementStarted(), context(record(phase="tender", contract_count=None, tender_count=0)))
    )
    assert not result.passed


# ── messages in every locale ──────────────────────────────────────────────


def test_every_message_key_exists_in_every_shipped_locale() -> None:
    """A finding in any catalogue language is a sentence, never a humanised key."""
    locales = available_locales()
    assert {"en", "de", "es", "ru"} <= set(locales), locales
    missing = [
        f"{rule_id}.{key} [{locale}]"
        for rule_id, keys in MESSAGE_KEYS.items()
        for key in keys
        for locale in locales
        if not is_key_present(f"{rule_id}.{key}", locale)
    ]
    assert not missing, "message keys missing from the validation catalogues: " + ", ".join(missing)


@pytest.mark.parametrize("locale", ["de", "es", "ru"])
def test_a_finding_is_translated_and_not_english(locale: str) -> None:
    ctx = context(record(country_code=None), locale=locale)
    result = only(run(ProjectCountrySet(), ctx))
    english = only(run(ProjectCountrySet(), context(record(country_code=None)))).message
    assert result.message != english, f"{locale} fell back to English: {result.message}"
    assert not result.message.startswith("project_completeness"), result.message
    assert result.suggestion and result.suggestion != english


def test_a_passing_result_uses_the_shared_ok_string() -> None:
    result = only(run(ProjectCountrySet(), context(record(), locale="de")))
    assert result.passed
    assert result.message == translate("common.ok", locale="de")
    assert result.suggestion is None
