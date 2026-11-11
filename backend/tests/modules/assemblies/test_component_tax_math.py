# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Component input tax: the arithmetic, the rate lookup and the TAX-001..006 rules (issue #559).

Rates in these tests are fixtures, not claims about any country.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.assemblies import component_tax as ct
from app.modules.assemblies.validators import (
    ASSEMBLIES_TAX_RULES,
    ExemptWithRateRule,
    InclusiveNeedsRateRule,
    MasterPriceDriftRule,
    RegistryRateInForceRule,
    TaxableNeedsRateRule,
    TaxRateValidRule,
)
from app.modules.i18n_foundation.tax_rules import TaxRateRow

D = Decimal


def line(price: str, **kw: object) -> ct.LineTax:
    base = {
        "status": "taxable",
        "rate_pct": D("18"),
        "includes_tax": False,
        "treatment": "cost_incorporated",
        "currency": "EUR",
    }
    return ct.compute_line_tax(D(price), **{**base, **kw})  # type: ignore[arg-type]


# ── arithmetic ───────────────────────────────────────────────────────────────


def test_issue_example_material_and_labour() -> None:
    material = line("1000")
    labour = line("500", status="exempt", rate_pct=None)
    assert (material.net, material.tax, material.tax_in_cost, material.cost) == (
        D("1000.00"),
        D("180.00"),
        D("180.00"),
        D("1180.00"),
    )
    assert (labour.net, labour.tax, labour.cost) == (D("500.00"), D("0.00"), D("500.00"))
    totals = ct.sum_lines([material.as_dict(), labour.as_dict()], D("1"))
    assert D(totals["net"]) == D("1500.00")
    assert D(totals["tax_in_cost"]) == D("180.00")
    assert D(totals["cost"]) == D("1680.00")
    assert D(totals["gross_outlay"]) == D("1680.00")


def test_inclusive_price_is_not_taxed_again() -> None:
    got = line("1180", includes_tax=True)
    assert (got.net, got.tax, got.cost, got.gross_outlay) == (D("1000.00"), D("180.00"), D("1180.00"), D("1180.00"))


def test_recoverable_tax_stays_out_of_cost_but_in_outlay() -> None:
    got = line("1000", treatment="recoverable")
    assert (got.cost, got.tax_in_cost, got.tax_recoverable, got.gross_outlay) == (
        D("1000.00"),
        D("0.00"),
        D("180.00"),
        D("1180.00"),
    )


def test_inclusive_recoverable_cost_is_the_net() -> None:
    got = line("1180", includes_tax=True, treatment="recoverable")
    assert got.cost == D("1000.00")
    assert got.tax_recoverable == D("180.00")


@pytest.mark.parametrize("status", ["exempt", "out_of_scope"])
def test_exempt_and_out_of_scope_carry_no_tax_even_with_rate_and_inclusive_flag(status: str) -> None:
    got = line("250", status=status, includes_tax=True)
    assert (got.net, got.tax, got.cost, got.rate_pct, got.includes_tax) == (
        D("250.00"),
        D("0.00"),
        D("250.00"),
        D("0"),
        False,
    )


def test_zero_rate_taxable_is_zero_tax() -> None:
    got = line("99.99", rate_pct=D("0"))
    assert got.tax == D("0.00")
    assert got.cost == D("99.99")


def test_mixed_rates_sum_line_by_line() -> None:
    a, b, c = line("100", rate_pct=D("18")), line("200", rate_pct=D("8")), line("300", status="exempt", rate_pct=None)
    totals = ct.sum_lines([x.as_dict() for x in (a, b, c)], D("1"))
    assert D(totals["tax"]) == D("34.00")  # 18 + 16
    assert D(totals["cost"]) == D("634.00")


def test_rounding_is_per_line_half_up() -> None:
    # 10.05 x 7.5 % = 0.75375 -> 0.75 per line; three lines add up the rounded figures, not the raw ones
    one = line("10.05", rate_pct=D("7.5"))
    assert one.tax == D("0.75")
    assert D(ct.sum_lines([one.as_dict()] * 3, D("1"))["tax"]) == D("2.25")
    # exact half rounds up
    assert line("0.25", rate_pct=D("10")).tax == D("0.03")  # 0.025


def test_inclusive_split_always_adds_back_to_the_entered_price() -> None:
    for price in ("0.01", "9.99", "123.45", "99999.99"):
        got = line(price, includes_tax=True, rate_pct=D("7.7"))
        assert got.net + got.tax == D(price)


def test_zero_decimal_currency_rounds_to_whole_units() -> None:
    got = line("1000", currency="JPY", rate_pct=D("10"))
    assert got.tax == D("100")
    assert got.cost == D("1100")


def test_bid_factor_scales_every_total() -> None:
    totals = ct.sum_lines([line("1000").as_dict()], D("1.1"))
    assert D(totals["cost"]) == D("1298.000")
    assert D(totals["net"]) == D("1100.000")


# ── effective fields and rate lookup ─────────────────────────────────────────


def ns(**kw: object) -> SimpleNamespace:
    base = dict(tax_code=None, tax_rate=None, tax_status=None, price_includes_tax=None, input_tax_treatment=None)
    return SimpleNamespace(**{**base, **kw})


def row(code: str, rate: str, **kw: object) -> TaxRateRow:
    base = dict(
        country_code="XX",
        tax_code=code,
        tax_name=code,
        rate_pct=rate,
        tax_type="vat",
        combination="national",
        subdivision_code=None,
        effective_from="2020-01-01",
        effective_to=None,
        is_default=False,
    )
    return TaxRateRow(**{**base, **kw})  # type: ignore[arg-type]


def rate(component: object, resource: object | None = None, rows: list[TaxRateRow] | None = None, **kw: object):
    args = dict(rows=rows or [], country="XX", subdivision=None, on_date="2026-06-01")
    return ct.resolve_rate(component, resource, **{**args, **kw})  # type: ignore[arg-type]


def test_component_fields_override_resource_and_inherit_when_unset() -> None:
    comp = ns(tax_status="exempt")
    res = ns(tax_status="taxable", price_includes_tax=True, input_tax_treatment="recoverable")
    eff = ct.effective_tax(comp, res, "cost_incorporated")
    assert (eff.status, eff.includes_tax, eff.treatment) == ("exempt", True, "recoverable")
    assert ct.effective_tax(ns(), None, "cost_incorporated").treatment == "cost_incorporated"
    assert ct.effective_tax(ns(input_tax_treatment="recoverable"), res, "cost_incorporated").treatment == "recoverable"


def test_rate_order_component_rate_then_code_then_resource() -> None:
    rows = [row("STD", "18"), row("RED", "8")]
    assert rate(ns(tax_rate="5", tax_code="STD"), ns(tax_rate="9"), rows).rate_pct == D("5")
    assert rate(ns(tax_code="RED"), ns(tax_rate="9"), rows).rate_pct == D("8")
    assert rate(ns(), ns(tax_rate="9"), rows).rate_pct == D("9")
    assert rate(ns(), ns(tax_code="STD"), rows).source == "resource_code"
    assert rate(ns(), ns()).reason == "no_rate"


def test_no_blanket_rate_is_ever_assumed() -> None:
    assert rate(ns(tax_status="taxable"), None, [row("STD", "18")]).rate_pct is None


def test_unresolvable_codes_report_why() -> None:
    rows = [row("OLD", "10", effective_to="2021-12-31")]
    assert rate(ns(tax_code="NOPE"), None, rows).reason == "unknown_code"
    gone = rate(ns(tax_code="OLD"), None, rows)
    assert (gone.reason, gone.in_force, gone.rate_pct) == ("outside_validity", False, None)
    assert rate(ns(tax_code="OLD"), None, rows, on_date="2021-06-01").rate_pct == D("10")
    assert rate(ns(tax_code="OLD"), None, rows, country=None).reason == "no_country"
    assert rate(ns(tax_rate="180")).reason == "invalid_rate"


def test_subdivision_code_goes_through_the_resolver() -> None:
    rows = [
        row("VAT", "5", country_code="CA", combination="federal", is_default=True),
        row("VAT", "7", country_code="CA", combination="stacks_on_federal", subdivision_code="CA-BC"),
    ]
    assert rate(ns(tax_code="VAT"), None, rows, country="CA", subdivision="CA-BC").rate_pct == D("12")
    # a subdivision nobody named is not guessed
    assert rate(ns(tax_code="VAT"), None, rows, country="CA").rate_pct is None


# ── rules ────────────────────────────────────────────────────────────────────


def tax_row(**kw: object) -> dict:
    base = {
        "classified": True,
        "status": "taxable",
        "explicit_rate": "18",
        "code": None,
        "includes_tax": False,
        "reason": None,
        "in_force": True,
        "on_date": "2026-06-01",
        "master_price": None,
        "unit_cost": "10",
    }
    return {"id": "c1", "description": "Cement", "tax": {**base, **kw}}


async def run(rule: object, comp: dict, approved: bool = False, locale: str = "en"):
    ctx = ValidationContext(
        data={"assembly": {"id": "a1", "approved": approved}, "components": [comp]}, metadata={"locale": locale}
    )
    return [r for r in await rule.validate(ctx) if not r.passed]  # type: ignore[attr-defined]


CASES = [
    (TaxRateValidRule, tax_row(explicit_rate="180"), tax_row(), Severity.ERROR, "TAX-001"),
    (
        TaxRateValidRule,
        tax_row(explicit_rate=None, code="X", reason="unknown_code"),
        tax_row(),
        Severity.ERROR,
        "TAX-001",
    ),
    (TaxableNeedsRateRule, tax_row(explicit_rate=None, reason="no_rate"), tax_row(), Severity.ERROR, "TAX-002"),
    (
        ExemptWithRateRule,
        tax_row(status="exempt"),
        tax_row(status="exempt", explicit_rate=None),
        Severity.WARNING,
        "TAX-003",
    ),
    (
        InclusiveNeedsRateRule,
        tax_row(includes_tax=True, explicit_rate=None, reason="no_rate"),
        tax_row(includes_tax=True),
        Severity.ERROR,
        "TAX-004",
    ),
    (MasterPriceDriftRule, tax_row(master_price="12"), tax_row(master_price="10"), Severity.INFO, "TAX-005"),
    (
        RegistryRateInForceRule,
        tax_row(in_force=False, code="OLD", explicit_rate=None),
        tax_row(),
        Severity.WARNING,
        "TAX-006",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("rule_cls", "bad", "good", "severity", "tag"), CASES)
async def test_each_tax_rule_fires_and_passes(
    rule_cls: type, bad: dict, good: dict, severity: Severity, tag: str
) -> None:
    rule = rule_cls()
    failed = await run(rule, bad)
    assert failed
    assert failed[0].severity == severity
    assert failed[0].message.startswith(tag)
    assert "component_tax." not in failed[0].message
    assert not await run(rule, good)


@pytest.mark.asyncio
async def test_rules_ignore_unclassified_components_and_drift_ignores_approved() -> None:
    plain = {"id": "c", "description": "x", "tax": {"classified": False}}
    for rule_cls in ASSEMBLIES_TAX_RULES:
        assert not await run(rule_cls(), plain)
        assert not await run(rule_cls(), {"id": "c", "description": "x"})
    assert not await run(MasterPriceDriftRule(), tax_row(master_price="12"), approved=True)


@pytest.mark.asyncio
async def test_inclusive_exempt_needs_no_rate() -> None:
    assert not await run(
        InclusiveNeedsRateRule(), tax_row(includes_tax=True, status="exempt", explicit_rate=None, reason="no_rate")
    )


@pytest.mark.asyncio
async def test_messages_follow_the_locale() -> None:
    de = await run(TaxableNeedsRateRule(), tax_row(explicit_rate=None, reason="no_rate"), locale="de")
    ru = await run(TaxableNeedsRateRule(), tax_row(explicit_rate=None, reason="no_rate"), locale="ru")
    assert "steuerpflichtig" in de[0].message
    assert "облагается" in ru[0].message
