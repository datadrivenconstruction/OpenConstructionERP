# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment terms a contract starts from, per country, and the money they decide.

Three promises are tested here without a database. Each country in the table
resolves to its own figures with a source for every one. An author's figure
always beats the default, even one equal to it. And a country the table does
not know gets nothing at all, which is the case the old platform-wide 5
percent got wrong: it answered for every country as if it were Germany.

The cap tests are the money half. A ceiling on retention is a ceiling on what
the contract holds in total, so the period that reaches it leaves the next one
nothing to hold. A check of each period against the cap on its own passes the
first period and then holds the whole ceiling again every month after, which
is why every cap test here runs at least three periods and asserts the second
and third.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.regional_packs import resolve_progress_billing
from app.modules.contracts.country_defaults import (
    CONTRACT_DEFAULT_FIELDS,
    COUNTRY_CONTRACT_DEFAULTS,
    FROM_REGIONAL_PACK,
    apply_contract_defaults,
    forget_overridden,
    resolve_contract_defaults,
    subcontract_retention_default,
    validate_release_split,
)
from app.modules.contracts.retention import compute_retention, policy_from_rule
from app.modules.contracts.schemas import ContractCreate, ContractUpdate
from app.modules.contracts.service import (
    _contract_release_rule,
    _explicit_payment_terms,
    contract_retention_cap,
    flat_retention_within_cap,
)

#: The countries the brief names; every one must answer on its own row.
REQUIRED = ("DE", "GB", "US", "CA", "FR", "RU", "AE", "SA", "IN", "BR", "CN")


# ── Every country resolves its own figures ─────────────────────────────


@pytest.mark.parametrize("country", REQUIRED)
def test_each_country_resolves_its_own_row_with_a_source_for_every_figure(country: str) -> None:
    resolved = resolve_contract_defaults(country)
    assert resolved is not None, country
    assert resolved["country_code"] == country
    assert set(resolved["values"]) == set(CONTRACT_DEFAULT_FIELDS)
    for field in CONTRACT_DEFAULT_FIELDS:
        source = resolved["sources"][field]
        assert source["source"] and source["reference"] and source["note"], (country, field)
    # Every country in the brief states a retention rate and a valuation rhythm.
    assert Decimal(resolved["values"]["retention_percent"]) > 0
    assert resolved["values"]["valuation_interval"] == "monthly"
    assert resolved["values"]["certificate_name"]
    split = resolved["values"]["retention_release_split"]
    assert split, f"{country} has no release split"
    # The last step pays back all that is left, so no retention is stranded.
    assert split[-1]["release_percent_of_held"] == "100"


def test_the_figures_that_tell_the_markets_apart() -> None:
    """One assertion per market on the figure a domain reader would check first."""
    values = {c: resolve_contract_defaults(c)["values"] for c in REQUIRED}  # type: ignore[index]
    assert values["DE"]["payment_period_days"] == 21
    assert values["DE"]["certificate_name"] == "Abschlagsrechnung"
    assert values["GB"]["retention_percent"] == "3"
    assert values["GB"]["retention_release_split"] == [
        {"event": "substantial_completion", "release_percent_of_held": "50"},
        {"event": "defects_period_end", "release_percent_of_held": "100"},
    ]
    assert values["US"]["retention_percent"] == "10"
    assert values["US"]["payment_period_days"] == 30
    assert values["FR"]["retention_cap_percent"] == "5"
    assert values["FR"]["retention_release_split"] == [
        {"event": "defects_period_end", "release_percent_of_held": "100"}
    ]
    for gulf in ("AE", "SA"):
        assert values[gulf]["retention_percent"] == "10"
        assert values[gulf]["retention_cap_percent"] == "5"
        assert values[gulf]["payment_period_days"] == 56
    assert values["CN"]["retention_cap_percent"] == "3"
    assert "КС-2" in values["RU"]["certificate_name"]
    assert values["CA"]["retention_percent"] == "10"
    assert values["CA"]["payment_period_days"] == 28


def test_the_canadian_holdback_is_statute_and_names_the_province_that_differs() -> None:
    """Ten percent is the statutory holdback in Ontario, BC and Alberta; Manitoba holds 7.5."""
    resolved = resolve_contract_defaults("CA")
    assert resolved is not None
    holdback = resolved["sources"]["retention_percent"]
    assert holdback["source"] == "statute"
    assert "Construction Act" in holdback["reference"]
    assert "7.5" in holdback["note"] and "Manitoba" in holdback["note"]
    # The holdback is a fixed percentage of every payment, not a running total
    # that stops at a ceiling, so no cap is offered.
    assert resolved["values"]["retention_cap_percent"] is None
    assert resolved["values"]["retention_release_split"] == [
        {"event": "substantial_completion", "release_percent_of_held": "100"},
        {"event": "final_completion", "release_percent_of_held": "100"},
    ]


def test_uk_is_read_as_great_britain() -> None:
    assert resolve_contract_defaults("uk") == resolve_contract_defaults("GB")


@pytest.mark.parametrize("country", [None, "", "  ", "XX", "IT", "dach"])
def test_an_unknown_country_gets_no_figures_and_never_germany(country: str | None) -> None:
    assert resolve_contract_defaults(country) is None


def test_a_field_with_no_usual_figure_stays_empty_and_says_why() -> None:
    for country in ("RU", "BR"):
        resolved = resolve_contract_defaults(country)
        assert resolved is not None
        assert resolved["values"]["payment_period_days"] is None
        assert resolved["sources"]["payment_period_days"]["note"]


# ── The table and the packs cannot disagree ───────────────────────────


@pytest.mark.parametrize("country", ["DE", "US"])
def test_where_the_pack_writes_release_events_the_split_is_the_packs(country: str) -> None:
    assert COUNTRY_CONTRACT_DEFAULTS[country]["retention_release_split"]["value"] == FROM_REGIONAL_PACK
    resolved = resolve_contract_defaults(country)
    assert resolved is not None
    assert resolved["release_split_source"] == FROM_REGIONAL_PACK
    pack = resolve_progress_billing(country_code=country)
    assert pack is not None
    expected = [
        (e["event"], Decimal(str(e["release_percent_of_held"])))
        for e in pack["release_events"]["events"]
        if e.get("release_percent_of_held") is not None
        and e["event"] in ("substantial_completion", "final_completion", "defects_period_end")
    ]
    got = [(s["event"], Decimal(s["release_percent_of_held"])) for s in resolved["values"]["retention_release_split"]]
    assert got == expected


def test_the_us_rate_is_the_opening_rate_of_the_packs_ladder() -> None:
    """At signing the pack's ladder is copied only when the contract's rate equals its opening tier."""
    pack = resolve_progress_billing(country_code="US")
    assert pack is not None
    opening = Decimal(str(pack["retention_policy"]["tiers"][0]["rate"]))
    assert Decimal(resolve_contract_defaults("US")["values"]["retention_percent"]) == opening  # type: ignore[index]


def test_the_german_rate_stays_within_the_vob_b_maximum_the_pack_states() -> None:
    pack = resolve_progress_billing(country_code="DE")
    assert pack is not None
    policy = pack["retention_policy"]
    assert policy["rate_is_maximum"] is True
    maximum = Decimal(str(policy["tiers"][0]["rate"]))
    assert Decimal(resolve_contract_defaults("DE")["values"]["retention_percent"]) <= maximum  # type: ignore[index]


@pytest.mark.parametrize("field", ["payment_period_days", "certificate_name"])
def test_a_vob_b_figure_is_not_passed_off_as_law(field: str) -> None:
    """VOB/B binds only where the contract incorporates it; the BGB is the law.

    The tooltip prints the source's label, and "Statute" beside a VOB/B clause
    tells a German estimator that 21 days binds a contract that never agreed
    VOB/B.
    """
    figure = COUNTRY_CONTRACT_DEFAULTS["DE"][field]
    assert "VOB/B" in figure["reference"]
    assert figure["source"] == "standard_form"


def test_the_german_payment_period_is_the_payment_clocks() -> None:
    from app.modules.payment_clock.data import PAYMENT_REGIMES

    regime = next(r for r in PAYMENT_REGIMES if r.get("code") == "de_vob_b_abschlag")
    assert resolve_contract_defaults("DE")["values"]["payment_period_days"] == regime["final_date_days"]  # type: ignore[index]


# ── Explicit always wins ─────────────────────────────────────────────


def test_what_the_author_sent_wins_even_when_it_equals_the_default() -> None:
    defaults = resolve_contract_defaults("GB")
    values, stamp = apply_contract_defaults({"retention_percent": Decimal("3")}, defaults, country_code="GB")
    assert values["retention_percent"] == Decimal("3")
    # Typed by the author, so the contract must not call it a default.
    assert "retention_percent" not in stamp["applied"]
    assert stamp["applied"]["payment_period_days"] == 14
    assert values["payment_period_days"] == 14


def test_the_defaults_fill_only_what_was_left_out() -> None:
    defaults = resolve_contract_defaults("AE")
    values, stamp = apply_contract_defaults(
        {"retention_percent": Decimal("7.5"), "payment_period_days": 28}, defaults, country_code="AE"
    )
    assert values["retention_percent"] == Decimal("7.5")
    assert values["payment_period_days"] == 28
    assert values["retention_cap_percent"] == "5"
    assert set(stamp["applied"]) == {
        "retention_cap_percent",
        "retention_release_split",
        "valuation_interval",
        "certificate_name",
    }
    assert stamp["country_code"] == "AE"
    assert stamp["has_country_defaults"] is True


def test_an_unknown_country_fills_nothing_and_records_the_country() -> None:
    values, stamp = apply_contract_defaults({}, resolve_contract_defaults("IT"), country_code="it")
    assert values == {}
    assert stamp["applied"] == {}
    assert stamp["country_code"] == "IT"
    assert stamp["has_country_defaults"] is False


def test_a_pack_split_is_stamped_but_not_written() -> None:
    values, stamp = apply_contract_defaults({}, resolve_contract_defaults("DE"), country_code="DE")
    assert "retention_release_split" not in values
    assert stamp["applied"]["retention_release_split"]
    assert stamp["release_split_source"] == FROM_REGIONAL_PACK


def test_explicit_is_read_from_the_fields_sent_not_from_their_values() -> None:
    sent = ContractCreate(code="C-1", contract_type="lump_sum", project_id="00000000-0000-0000-0000-000000000001")
    assert _explicit_payment_terms(sent) == {}
    sent = ContractCreate(
        code="C-1",
        contract_type="lump_sum",
        project_id="00000000-0000-0000-0000-000000000001",
        retention_percent=Decimal("5"),
        terms={"payment_terms": {"payment_period_days": 45}},
    )
    assert _explicit_payment_terms(sent) == {"retention_percent": Decimal("5"), "payment_period_days": 45}


def test_no_cap_sent_on_purpose_is_not_replaced_by_the_countrys_cap() -> None:
    sent = ContractCreate(
        code="C-1",
        contract_type="lump_sum",
        project_id="00000000-0000-0000-0000-000000000001",
        retention_cap_percent=None,
        retention_percent=None,
    )
    explicit = _explicit_payment_terms(sent)
    # A null rate cannot be stored, so it is "not sent"; a null cap is an answer.
    assert explicit == {"retention_cap_percent": None}
    values, stamp = apply_contract_defaults(explicit, resolve_contract_defaults("AE"), country_code="AE")
    assert values["retention_cap_percent"] is None
    assert values["retention_percent"] == "10"
    assert "retention_cap_percent" not in stamp["applied"]


def test_a_create_with_nothing_stated_leaves_every_payment_term_unset() -> None:
    sent = ContractCreate(code="C-1", contract_type="lump_sum", project_id="00000000-0000-0000-0000-000000000001")
    assert sent.retention_percent is None
    assert sent.retention_release_event is None
    assert sent.retention_cap_percent is None
    assert sent.retention_release_split is None


# ── The stamp follows later edits ────────────────────────────────────


def test_a_figure_typed_over_loses_its_default_stamp() -> None:
    _values, stamp = apply_contract_defaults({}, resolve_contract_defaults("GB"), country_code="GB")
    after = forget_overridden(stamp, {"retention_percent": Decimal("5"), "payment_period_days": 14})
    assert "retention_percent" not in after["applied"]
    assert "retention_percent" not in after["sources"]
    # Set to the value it was defaulted to: still the default.
    assert after["applied"]["payment_period_days"] == 14
    # The original stamp is not mutated.
    assert "retention_percent" in stamp["applied"]


def test_the_same_number_written_another_way_is_not_an_override() -> None:
    _values, stamp = apply_contract_defaults({}, resolve_contract_defaults("GB"), country_code="GB")
    after = forget_overridden(stamp, {"retention_percent": Decimal("3.00")})
    assert "retention_percent" in after["applied"]


# ── Release splits ───────────────────────────────────────────────────


def test_half_and_half_is_refused_because_it_strands_a_quarter() -> None:
    with pytest.raises(ValueError, match="last step"):
        validate_release_split(
            [
                {"event": "substantial_completion", "release_percent_of_held": "50"},
                {"event": "defects_period_end", "release_percent_of_held": "50"},
            ]
        )


@pytest.mark.parametrize(
    "split",
    [
        [],
        [{"event": "handover_party", "release_percent_of_held": "100"}],
        [
            {"event": "defects_period_end", "release_percent_of_held": "50"},
            {"event": "defects_period_end", "release_percent_of_held": "100"},
        ],
        [{"event": "defects_period_end", "release_percent_of_held": "120"}],
        "substantial_completion",
    ],
)
def test_an_unusable_split_is_refused(split) -> None:
    with pytest.raises(ValueError):
        validate_release_split(split)


def test_the_schema_reads_an_old_event_name_and_refuses_a_stranding_split() -> None:
    sent = ContractUpdate(
        retention_release_split=[
            {"event": "practical_completion", "release_percent_of_held": 50},
            {"event": "defects_liability_end", "release_percent_of_held": 100},
        ]
    )
    assert sent.retention_release_split == [
        {"event": "substantial_completion", "release_percent_of_held": "50"},
        {"event": "defects_period_end", "release_percent_of_held": "100"},
    ]
    with pytest.raises(ValidationError):
        ContractUpdate(retention_release_split=[{"event": "substantial_completion", "release_percent_of_held": 50}])
    with pytest.raises(ValidationError):
        ContractUpdate(valuation_interval="quarterly")


_PROJECT = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize(
    "block",
    [
        # A step of the wrong shape used to reach split[0]["event"] in the create and give a 500.
        {"retention_release_split": ["x"]},
        # Half at each event leaves a quarter of the retention with no event that releases it.
        {
            "retention_release_split": [
                {"event": "substantial_completion", "release_percent_of_held": 50},
                {"event": "defects_period_end", "release_percent_of_held": 50},
            ]
        },
        {"retention_cap_percent": "150"},
        {"payment_period_days": -1},
        {"valuation_interval": "quarterly"},
        "not an object",
    ],
)
def test_payment_terms_written_into_terms_pass_the_same_checks_as_the_fields(block) -> None:
    with pytest.raises(ValidationError):
        ContractCreate(code="C-1", contract_type="lump_sum", project_id=_PROJECT, terms={"payment_terms": block})
    with pytest.raises(ValidationError):
        ContractUpdate(terms={"payment_terms": block})


def test_payment_terms_written_into_terms_are_stored_in_the_fields_own_shape() -> None:
    sent = ContractCreate(
        code="C-1",
        contract_type="lump_sum",
        project_id=_PROJECT,
        terms={
            "ld_per_day": "100",
            "payment_terms": {
                "retention_cap_percent": "5.0",
                "retention_release_split": [
                    {"event": "practical_completion", "release_percent_of_held": 50},
                    {"event": "defects_liability_end", "release_percent_of_held": 100},
                ],
                "payment_period_days": 30,
                "note_for_file": "kept as written",
            },
        },
    )
    assert sent.terms == {
        "ld_per_day": "100",
        "payment_terms": {
            "retention_cap_percent": "5",
            "retention_release_split": [
                {"event": "substantial_completion", "release_percent_of_held": "50"},
                {"event": "defects_period_end", "release_percent_of_held": "100"},
            ],
            "payment_period_days": 30,
            "note_for_file": "kept as written",
        },
    }
    # Terms with no payment-terms block, or a null one, are not touched.
    assert ContractUpdate(terms={"gmp_cap": "1"}).terms == {"gmp_cap": "1"}
    assert ContractUpdate(terms={"payment_terms": None}).terms == {"payment_terms": None}


def test_the_contract_split_keeps_the_packs_documents_and_its_other_events() -> None:
    pack_rule = {
        "events": [
            {"event": "substantial_completion", "release_percent_of_held": "100", "required_documents": ["cert"]},
            {"event": "final_completion", "release_percent_of_held": "100", "required_documents": ["affidavit"]},
            {"event": "rate_step_down", "release_percent_of_held": None, "required_documents": []},
        ]
    }
    contract = SimpleNamespace(
        terms={
            "payment_terms": {
                "retention_release_split": [
                    {"event": "substantial_completion", "release_percent_of_held": "50"},
                    {"event": "final_completion", "release_percent_of_held": "100"},
                ]
            }
        }
    )
    rule = _contract_release_rule(contract, pack_rule)
    assert rule is not None
    by_event = {e["event"]: e for e in rule["events"]}
    assert by_event["substantial_completion"]["release_percent_of_held"] == "50"
    assert by_event["substantial_completion"]["required_documents"] == ["cert"]
    assert by_event["final_completion"]["required_documents"] == ["affidavit"]
    assert "rate_step_down" in by_event
    # The pack's own rule is not touched.
    assert pack_rule["events"][0]["release_percent_of_held"] == "100"


def test_no_split_on_the_contract_leaves_the_pack_in_charge() -> None:
    assert _contract_release_rule(SimpleNamespace(terms={}), {"events": [{"event": "x"}]}) is None


# ── The cap, period by period ────────────────────────────────────────


def test_a_flat_claim_stops_holding_once_the_cap_is_reached() -> None:
    """Rate 10, cap 5 of 100000: the ceiling is 5000 in total, not 5000 a month."""
    held = Decimal("0")
    accruals = []
    for gross in (Decimal("40000"), Decimal("20000"), Decimal("30000")):
        accrual = flat_retention_within_cap(
            gross, Decimal("10"), cap_percent=Decimal("5"), contract_sum=Decimal("100000"), accrued_before=held
        )
        accruals.append(accrual)
        held += accrual
    # The second period reaches the ceiling on 1000 of its 2000; the third holds nothing.
    assert accruals == [Decimal("4000"), Decimal("1000"), Decimal("0")]
    assert held == Decimal("5000")


def test_a_flat_claim_without_a_cap_holds_its_rate_every_period() -> None:
    accrual = flat_retention_within_cap(
        Decimal("30000"),
        Decimal("10"),
        cap_percent=None,
        contract_sum=Decimal("100000"),
        accrued_before=Decimal("9000"),
    )
    assert accrual == Decimal("3000")


@pytest.mark.parametrize("contract_sum", [Decimal("0"), Decimal("-1")])
def test_a_flat_claim_on_a_contract_with_no_sum_holds_its_rate_every_period(contract_sum: Decimal) -> None:
    """A cost-plus contract with no total under a 5 percent cap: no ceiling to measure, so 5 percent holds.

    Read as 5 percent of 0, the ceiling would be 0 and every claim would hold
    nothing, which is what a German cost-plus contract with no total did when
    its country default brought a cap.
    """
    held = Decimal("0")
    accruals = []
    for gross in (Decimal("20000"), Decimal("20000"), Decimal("40000")):
        accrual = flat_retention_within_cap(
            gross, Decimal("5"), cap_percent=Decimal("5"), contract_sum=contract_sum, accrued_before=held
        )
        accruals.append(accrual)
        held += accrual
    assert accruals == [Decimal("1000"), Decimal("1000"), Decimal("2000")]


def test_the_engine_holds_its_rate_when_the_contract_states_no_sum() -> None:
    """A capped policy on a contract sum of 0 is uncapped, not capped at 0."""
    policy = policy_from_rule(
        {"tiers": [{"from_percent_complete": "0", "rate": "5"}], "cap": {"percent_of_contract_sum": "5"}},
        fallback_rate=0,
    )
    position = compute_retention({"A": Decimal("20000")}, contract_sum=Decimal("0"), policy=policy)
    assert position.total == Decimal("1000.00")
    assert position.capped is False
    # The same policy on a contract that states its sum is still held to it.
    capped = compute_retention({"A": Decimal("200000")}, contract_sum=Decimal("100000"), policy=policy)
    assert capped.total == Decimal("5000.00")
    assert capped.capped is True


def test_the_engine_holds_the_cap_across_periods_on_a_schedule_of_values() -> None:
    """Work to date 40k, 60k, 90k at 10 percent with a 5 percent cap: held 4000, 5000, 5000."""
    policy = policy_from_rule(
        {"tiers": [{"from_percent_complete": "0", "rate": "10"}], "cap": {"percent_of_contract_sum": "5"}},
        fallback_rate=0,
    )
    held = [
        compute_retention({"A": Decimal(done)}, contract_sum=Decimal("100000"), policy=policy).total
        for done in ("40000", "60000", "90000")
    ]
    assert held == [Decimal("4000.00"), Decimal("5000.00"), Decimal("5000.00")]
    # What each period accrues is the step in held: nothing once the cap is reached.
    assert [held[0], held[1] - held[0], held[2] - held[1]] == [Decimal("4000"), Decimal("1000"), Decimal("0")]


@pytest.mark.parametrize("country", REQUIRED)
def test_a_subcontract_rate_never_runs_above_the_countrys_cap(country: str) -> None:
    """An agreement holds one rate with no ceiling, so its default may not exceed the cap.

    Only the Gulf rows state a rate above their cap; every other row hands the
    agreement its own rate unchanged.
    """
    defaults = resolve_contract_defaults(country)
    rate, from_field = subcontract_retention_default(defaults)
    values = defaults["values"]
    cap = values["retention_cap_percent"]
    if cap is not None and Decimal(cap) < Decimal(values["retention_percent"]):
        assert (rate, from_field) == (cap, "retention_cap_percent")
    else:
        assert (rate, from_field) == (values["retention_percent"], "retention_percent")
    if cap is not None:
        assert Decimal(rate) <= Decimal(cap)


def test_only_the_gulf_subcontract_is_held_to_the_cap() -> None:
    held = {
        c for c in REQUIRED if subcontract_retention_default(resolve_contract_defaults(c))[1] != "retention_percent"
    }
    assert held == {"AE", "SA"}
    assert subcontract_retention_default(resolve_contract_defaults("AE")) == ("5", "retention_cap_percent")
    assert subcontract_retention_default(resolve_contract_defaults("GB")) == ("3", "retention_percent")


def test_a_country_with_no_row_gives_a_subcontract_no_rate() -> None:
    assert subcontract_retention_default(None) == (None, None)
    assert subcontract_retention_default(resolve_contract_defaults("IT")) == (None, None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", Decimal("5")), ("2.5", Decimal("2.5")), (None, None), ("", None), ("abc", None), ("150", None)],
)
def test_the_contract_cap_is_read_from_its_payment_terms(raw, expected) -> None:
    contract = SimpleNamespace(terms={"payment_terms": {"retention_cap_percent": raw}})
    assert contract_retention_cap(contract) == expected


# ── Canadian provinces ────────────────────────────────────────────────


def test_a_manitoba_project_starts_from_seven_and_a_half_percent() -> None:
    resolved = resolve_contract_defaults("CA", "CA-MB")
    assert resolved is not None
    assert resolved["subdivision_code"] == "CA-MB"
    assert resolved["values"]["retention_percent"] == "7.5"
    assert (
        resolved["sources"]["retention_percent"]["note_key"]
        == "contracts.country_defaults.CA-MB.retention_percent.note"
    )
    # Fields the province does not name come from the country row.
    assert resolved["values"]["payment_period_days"] == 28
    assert (
        resolved["sources"]["payment_period_days"]["note_key"]
        == "contracts.country_defaults.CA.payment_period_days.note"
    )
    assert resolved["release_period"]["value"] == 60


def test_each_province_states_its_own_release_period() -> None:
    periods = {
        code: resolve_contract_defaults("CA", code)["release_period"]["value"]
        for code in ("CA-ON", "CA-BC", "CA-AB", "CA-MB", "CA-QC")
    }
    assert periods == {"CA-ON": 60, "CA-BC": 55, "CA-AB": 60, "CA-MB": 60, "CA-QC": None}


def test_quebec_has_no_statutory_holdback() -> None:
    resolved = resolve_contract_defaults("CA", "QC")
    assert resolved["subdivision_code"] == "CA-QC"
    assert resolved["sources"]["retention_percent"]["source"] == "industry_practice"
    assert resolved["values"]["payment_period_days"] is None


def test_an_unknown_or_foreign_subdivision_reads_the_country_row() -> None:
    national = resolve_contract_defaults("CA")
    for sub in (None, "", "CA-NS", "US-CA", "MB-X"):
        resolved = resolve_contract_defaults("CA", sub)
        assert resolved["subdivision_code"] is None, sub
        assert resolved["release_period"] is None, sub
        assert resolved["values"] == national["values"], sub


def test_a_subdivision_never_lends_its_row_to_another_country() -> None:
    assert resolve_contract_defaults("US", "CA-MB")["subdivision_code"] is None
