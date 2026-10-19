# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The public works rules speak on an Egyptian public contract and nowhere else.

``contracts.public_works_limits`` holds retention, the advance payment, the
cap on delay damages and the performance security to Law 182/2018;
``contracts.price_adjustment_terms`` asks a contract of six months or more for
coefficients the law accepts. A private Egyptian contract, a subcontract on a
public project and a public project in a country without a limits row are
silent, which is the distinguishing case for each.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.contracts.validators import PriceAdjustmentTermsRule, PublicWorksLimitsRule

pytestmark = pytest.mark.asyncio


def _ctx(
    *,
    country: str = "EG",
    works: str | None = "public",
    counterparty_type: str = "client",
    retention: str = "5",
    terms: dict[str, Any] | None = None,
    securities: list[dict[str, Any]] | None = None,
    ld_clauses: list[dict[str, Any]] | None = None,
    start: str | None = "2026-01-15",
    end: str | None = "2026-03-15",
    locale: str = "en",
) -> ValidationContext:
    return ValidationContext(
        data={
            "project": {"country_code": country, "works": works},
            "contract": {
                "id": "c1",
                "status": "draft",
                "contract_type": "lump_sum",
                "counterparty_type": counterparty_type,
                "total_value": "10000000",
                "retention_percent": retention,
                "start_date": start,
                "end_date": end,
                "terms": terms or {},
            },
            "parties": [],
            "securities": securities
            if securities is not None
            else [{"security_type": "bank_guarantee", "status": "active", "amount": "500000"}],
            "ld_clauses": ld_clauses or [],
        },
        metadata={"locale": locale},
    )


async def _fails(rule: type, context: ValidationContext) -> list:
    return [r for r in await rule().validate(context) if not r.passed]


# ── Retention ─────────────────────────────────────────────────────────────────


async def test_five_percent_retention_passes_and_six_blocks() -> None:
    assert await _fails(PublicWorksLimitsRule, _ctx(retention="5")) == []
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(retention="6"))
    assert found.severity == Severity.ERROR
    assert found.details == {"country": "EG", "percent": "6", "limit": "5"}
    assert "6 percent" in found.message and "5 percent" in found.message


@pytest.mark.parametrize(
    "context",
    [
        _ctx(works="private", retention="10"),
        _ctx(works=None, retention="10"),
        _ctx(counterparty_type="subcontractor", retention="10"),
        _ctx(country="DE", retention="10"),
        _ctx(country="AE", retention="10"),
    ],
    ids=["private_eg", "unrecorded_eg", "subcontract_on_public_eg", "public_de", "public_ae"],
)
async def test_the_rules_are_silent_outside_egyptian_public_main_contracts(context: ValidationContext) -> None:
    assert await PublicWorksLimitsRule().validate(context) == []
    assert await PriceAdjustmentTermsRule().validate(context) == []


# ── Advance payment ──────────────────────────────────────────────────────────


def _advance(amount: str) -> list[dict[str, Any]]:
    return [
        {"security_type": "bank_guarantee", "status": "active", "amount": "500000"},
        {"security_type": "advance_payment_bond", "status": "active", "amount": amount},
    ]


async def test_an_advance_above_a_quarter_blocks() -> None:
    assert await _fails(PublicWorksLimitsRule, _ctx(securities=_advance("2500000"))) == []
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(securities=_advance("3000000")))
    assert found.details["percent"] == "30" and found.details["limit"] == "25"


async def test_an_sme_may_take_half_and_no_more() -> None:
    sme = {"contractor_is_sme": True}
    assert await _fails(PublicWorksLimitsRule, _ctx(terms=sme, securities=_advance("4000000"))) == []
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(terms=sme, securities=_advance("6000000")))
    assert found.details["limit"] == "50"


async def test_the_finance_ministers_approval_lifts_the_cap() -> None:
    approved = {"advance_payment_mof_approval": True}
    assert await _fails(PublicWorksLimitsRule, _ctx(terms=approved, securities=_advance("3000000"))) == []


async def test_a_released_advance_bond_is_not_counted() -> None:
    securities = _advance("3000000")
    securities[1]["status"] = "released"
    assert await _fails(PublicWorksLimitsRule, _ctx(securities=securities)) == []


# ── Delay damages ────────────────────────────────────────────────────────────


async def test_delay_damages_capped_above_fifteen_percent_block() -> None:
    within = [{"id": "ld1", "per_day_amount": "10000", "max_amount": "1500000"}]
    assert await _fails(PublicWorksLimitsRule, _ctx(ld_clauses=within)) == []
    above = [{"id": "ld1", "per_day_amount": "10000", "max_amount": "2000000"}]
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(ld_clauses=above))
    assert found.severity == Severity.ERROR
    assert (found.details["percent"], found.details["limit"]) == ("20", "15")


async def test_uncapped_delay_damages_only_warn() -> None:
    clauses = [{"id": "ld1", "per_day_amount": "10000", "max_amount": None}]
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(ld_clauses=clauses))
    assert found.severity == Severity.WARNING


# ── Performance security ─────────────────────────────────────────────────────


async def test_no_performance_security_warns_and_a_short_one_warns() -> None:
    (missing,) = await _fails(PublicWorksLimitsRule, _ctx(securities=[]))
    assert missing.severity == Severity.WARNING and missing.details["limit"] == "5"
    short = [{"security_type": "performance_bond", "status": "active", "amount": "300000"}]
    (below,) = await _fails(PublicWorksLimitsRule, _ctx(securities=short))
    assert below.severity == Severity.WARNING and below.details["percent"] == "3"
    stated = [{"security_type": "performance_bond", "status": "active", "amount": "0", "percent_of_contract": "5"}]
    assert await _fails(PublicWorksLimitsRule, _ctx(securities=stated)) == []


# ── Price adjustment coefficients ────────────────────────────────────────────


_NINE_MONTHS = {"start": "2026-01-15", "end": "2026-10-15"}


async def test_a_short_contract_needs_no_coefficients() -> None:
    assert await _fails(PriceAdjustmentTermsRule, _ctx(start="2026-01-15", end="2026-06-14")) == []


async def test_a_contract_with_unknown_dates_is_not_judged() -> None:
    assert await PriceAdjustmentTermsRule().validate(_ctx(start=None, end=None)) == []


async def test_nine_months_without_coefficients_blocks() -> None:
    (found,) = await _fails(PriceAdjustmentTermsRule, _ctx(**_NINE_MONTHS))
    assert found.severity == Severity.ERROR
    assert found.details["months"] == "6"
    assert "6 months" in found.message


async def test_valid_coefficients_pass_and_a_sum_of_one_or_more_blocks() -> None:
    good = {"price_adjustment": {"coefficients": [{"item": "cement", "coefficient": "0.15"}]}}
    assert await _fails(PriceAdjustmentTermsRule, _ctx(terms=good, **_NINE_MONTHS)) == []
    full = {
        "price_adjustment": {
            "coefficients": [{"item": "cement", "coefficient": "0.6"}, {"item": "steel", "coefficient": "0.4"}]
        }
    }
    (found,) = await _fails(PriceAdjustmentTermsRule, _ctx(terms=full, **_NINE_MONTHS))
    assert found.details["item"] == "1.0"
    assert "below one" in found.message


async def test_a_datetime_end_date_is_read_by_its_day() -> None:
    (found,) = await _fails(PriceAdjustmentTermsRule, _ctx(start="2026-01-15T00:00:00", end="2026-10-15T12:00:00"))
    assert found.details["months"] == "6"


async def test_the_messages_are_translated() -> None:
    (found,) = await _fails(PublicWorksLimitsRule, _ctx(retention="6", locale="de"))
    assert "public works" not in found.message
    assert "6" in found.message and "5" in found.message
