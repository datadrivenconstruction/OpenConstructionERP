# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A German Sicherheitseinbehalt is cut from the payment with VAT in it.

§ 17 Abs. 6 Nr. 1 VOB/B (2016): "Soll der Auftraggeber vereinbarungsgemäß die
Sicherheit in Teilbeträgen von seinen Zahlungen einbehalten, so darf er jeweils
die Zahlung um höchstens 10 v. H. kürzen, bis die vereinbarte Sicherheitssumme
erreicht ist. Sofern Rechnungen ohne Umsatzsteuer gemäß § 13 b UStG gestellt
werden, bleibt die Umsatzsteuer bei der Berechnung des Sicherheitseinbehalts
unberücksichtigt." The payment is the one the invoice asks for, VAT included;
only a reverse-charge invoice, which carries no VAT, is measured without it.

VHB Bund, Formblatt 214 Nr. 4 states the security sum the cut stops at:
"Sicherheit für die Vertragserfüllung in Höhe von fünf Prozent der
Auftragssumme (inkl. Umsatzsteuer, ohne Nachträge)".

The case: a first Abschlagsrechnung of 382,259.79 net at 19 % USt is
454,889.15 gross. Ten percent of that is 45,488.92, so the client pays
409,400.23. Measured on the net, as the platform did, retention was 38,225.98
and the X89 invoice asked for 416,663.17, which is 7,262.94 more than the
client owes. The VAT itself stays on the net Entgelt either way.

Pure tests, no database: the country data, the retention engine, the flat
path and the X89 totals the claim's retention feeds.

Run::

    cd backend
    python -m pytest tests/unit/test_german_retention_is_cut_from_the_gross_payment.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.boq.gaeb_x89 import InvoiceLine, invoice_figures
from app.modules.contracts.country_defaults import (
    COUNTRY_CONTRACT_DEFAULTS,
    COUNTRY_RETENTION_BASIS,
    resolve_retention_basis,
)
from app.modules.contracts.retention import (
    RETENTION_BASIS_GROSS,
    RETENTION_BASIS_NET,
    RetentionPolicy,
    RetentionTier,
    claim_retention,
    compute_retention,
    flat_policy,
    flat_retention_within_cap,
    on_retention_basis,
)

D = Decimal

NET = D("382259.79")
CONTRACT_SUM = D("1000000.00")


def _capped(rate: str, cap: str) -> RetentionPolicy:
    policy = flat_policy(rate)
    return RetentionPolicy(tiers=policy.tiers, source=policy.source, cap_percent_of_contract_sum=D(cap))


def _x89(retention: Decimal, *, vat: str) -> object:
    line = InvoiceLine(oz="01.01", description="Rohbau", unit="psch", bill_qty=D("1"), unit_price=NET, amount=NET)
    return invoice_figures([line], vat_rate=D(vat), retention=retention)


def _engine_accrual(basis_vat: Decimal | None) -> tuple[Decimal, Decimal]:
    """The first claim's retention and the line's stated rate, through the engine."""
    position = compute_retention(
        {"L1": NET},
        contract_sum=CONTRACT_SUM,
        policy=_capped("10", "5"),
        basis_vat_percent=basis_vat,
    )
    figures = claim_retention(position, completed_by_line={"L1": NET}, accrued_before=0, released_to_date=0)
    return figures.accrual, figures.lines["L1"].retention_rate


# ── The country data ─────────────────────────────────────────────────────


def test_germany_measures_retention_on_the_gross_and_says_why() -> None:
    basis = resolve_retention_basis("DE")
    assert basis.basis == RETENTION_BASIS_GROSS
    assert basis.vat_percent == D("19")
    assert basis.vat_source == "country_standard"
    assert "§ 17 Abs. 6 Nr. 1 VOB/B" in (basis.reference or "")
    assert "Formblatt 214" in (basis.reference or "")


@pytest.mark.parametrize("country", sorted(set(COUNTRY_CONTRACT_DEFAULTS) - {"DE"}))
def test_every_other_country_in_the_table_keeps_measuring_on_the_net(country: str) -> None:
    basis = resolve_retention_basis(country)
    assert (basis.basis, basis.vat_percent) == (RETENTION_BASIS_NET, None)


def test_only_germany_is_on_a_gross_basis_today() -> None:
    # France is deliberately not here: its basis belongs to its own change.
    assert {c for c, row in COUNTRY_RETENTION_BASIS.items() if row["basis"] == RETENTION_BASIS_GROSS} == {"DE"}


def test_the_contracts_agreed_vat_comes_before_the_projects_and_the_countrys() -> None:
    agreed = resolve_retention_basis("DE", agreed_vat_rate="7", project_vat_rate="16")
    assert (agreed.vat_percent, agreed.vat_source) == (D("7"), "contract_einvoice")
    project = resolve_retention_basis("DE", project_vat_rate="16")
    assert (project.vat_percent, project.vat_source) == (D("16"), "project_default")


def test_a_german_subcontract_is_presumed_reverse_charge_unless_it_states_a_rate() -> None:
    """§ 13b Abs. 2 Nr. 4, Abs. 5 Satz 2 UStG: a main contractor owes the USt on its sub's work."""
    presumed = resolve_retention_basis("DE", project_vat_rate="19", subcontract=True)
    assert (presumed.basis, presumed.vat_percent, presumed.vat_source) == (
        RETENTION_BASIS_GROSS,
        D("0"),
        "subcontract_presumed",
    )
    assert "§ 13b" in (presumed.reference or "")
    stated = resolve_retention_basis("DE", agreed_vat_rate="19", subcontract=True)
    assert (stated.vat_percent, stated.vat_source) == (D("19"), "contract_einvoice")
    # Outside Germany a subcontract is on the net like any other contract.
    assert resolve_retention_basis("GB", subcontract=True).vat_percent is None


def test_an_unreadable_agreed_rate_falls_through_rather_than_reading_as_zero() -> None:
    basis = resolve_retention_basis("DE", agreed_vat_rate="nineteen")
    assert (basis.vat_percent, basis.vat_source) == (D("19"), "country_standard")


# ── The figure the client pays ───────────────────────────────────────────


def test_measured_on_the_net_the_invoice_asks_for_416663_17() -> None:
    """The old German figure, which is still every net-basis country's: pinned, not removed."""
    accrual, _rate = _engine_accrual(None)
    assert accrual == D("38225.98")
    figures = _x89(accrual, vat="19")
    assert (figures.gross, figures.payable) == (D("454889.15"), D("416663.17"))


def test_a_german_abschlagsrechnung_pays_the_gross_less_ten_percent_of_the_gross() -> None:
    basis = resolve_retention_basis("DE")
    accrual, rate = _engine_accrual(basis.vat_percent)
    assert accrual == D("45488.92")
    # The line states the rate it was held at, on the base it was held on.
    assert rate == D("10.0000")
    figures = _x89(accrual, vat="19")
    assert figures.net == NET
    # VAT is still on the net Entgelt; only the cut moved.
    assert figures.vat_amount == D("72629.36")
    assert figures.gross == D("454889.15")
    assert figures.retention == D("45488.92")
    assert figures.payable == D("409400.23")
    assert figures.payable == figures.gross - figures.retention


def test_the_flat_path_holds_the_same_ten_percent_of_the_gross() -> None:
    """Cost-plus, T&M and a claim with no lines take the flat path, not the engine."""
    vat = resolve_retention_basis("DE").vat_percent
    held = flat_retention_within_cap(
        NET, D("10"), cap_percent=D("5"), contract_sum=CONTRACT_SUM, accrued_before=D("0"), basis_vat_percent=vat
    )
    assert held == D("45488.9150")
    assert _x89(held, vat="19").payable == D("409400.23")


def test_a_reverse_charge_invoice_is_measured_without_vat() -> None:
    """§ 17 Abs. 6 Nr. 1 Satz 2 VOB/B: no USt on the invoice (§ 13b UStG), none in the base."""
    basis = resolve_retention_basis("DE", agreed_vat_rate="0")
    assert (basis.basis, basis.vat_percent) == (RETENTION_BASIS_GROSS, D("0"))
    accrual, _rate = _engine_accrual(basis.vat_percent)
    assert accrual == D("38225.98")
    assert _x89(accrual, vat="0").payable == NET - D("38225.98")


# ── The ceiling ──────────────────────────────────────────────────────────


def test_the_ceiling_is_five_percent_of_the_contract_sum_with_vat_in_it() -> None:
    vat = resolve_retention_basis("DE").vat_percent
    position = compute_retention(
        {"L1": D("900000")}, contract_sum=CONTRACT_SUM, policy=_capped("10", "5"), basis_vat_percent=vat
    )
    assert position.capped is True
    assert position.total == D("59500.00")  # 5 % of 1,190,000.00
    assert on_retention_basis(CONTRACT_SUM, vat) * D("5") / D("100") == D("59500.00")


def test_the_flat_path_stops_at_the_same_ceiling() -> None:
    vat = resolve_retention_basis("DE").vat_percent
    first = flat_retention_within_cap(
        D("900000"),
        D("10"),
        cap_percent=D("5"),
        contract_sum=CONTRACT_SUM,
        accrued_before=D("0"),
        basis_vat_percent=vat,
    )
    assert first == D("59500.00")
    # After the first Abschlagsrechnung held 45,488.92, 14,011.08 is left of the ceiling.
    second = flat_retention_within_cap(
        D("900000"),
        D("10"),
        cap_percent=D("5"),
        contract_sum=CONTRACT_SUM,
        accrued_before=D("45488.92"),
        basis_vat_percent=vat,
    )
    assert second == D("14011.08")


def test_percent_complete_and_the_tier_stay_on_the_net() -> None:
    """VAT does not make the work further along: a 50 % step-down is crossed at 50 % of the net."""
    ladder = RetentionPolicy(
        tiers=(RetentionTier(D("0"), D("10")), RetentionTier(D("50"), D("5"))),
        tier_mode="recompute",
    )
    below = compute_retention({"L1": D("499999.99")}, contract_sum=CONTRACT_SUM, policy=ladder, basis_vat_percent=19)
    at = compute_retention({"L1": D("500000.00")}, contract_sum=CONTRACT_SUM, policy=ladder, basis_vat_percent=19)
    assert (below.rate_now, at.rate_now) == (D("10"), D("5"))
    assert below.percent_complete == D("50.0000")
    assert at.total == D("29750.00")  # 5 % of 595,000.00


# ── UK, US and France are unchanged ──────────────────────────────────────


@pytest.mark.parametrize(
    ("country", "vat", "payable"),
    [
        # 382,259.79 + 76,451.96 VAT - 38,225.98 retention on the net.
        ("GB", "20", D("420485.77")),
        # No federal VAT: the net less 38,225.98.
        ("US", "0", D("344033.81")),
        # Same VAT as GB. Not changed here: whether France measures on the TTC is its own question.
        ("FR", "20", D("420485.77")),
    ],
)
def test_net_basis_countries_hold_ten_percent_of_the_net_as_before(country: str, vat: str, payable: Decimal) -> None:
    basis = resolve_retention_basis(country)
    accrual, rate = _engine_accrual(basis.vat_percent)
    assert (accrual, rate) == (D("38225.98"), D("10.0000"))
    held = flat_retention_within_cap(
        NET,
        D("10"),
        cap_percent=D("5"),
        contract_sum=CONTRACT_SUM,
        accrued_before=D("0"),
        basis_vat_percent=basis.vat_percent,
    )
    assert held == D("38225.9790")
    assert _x89(accrual, vat=vat).payable == payable


def test_a_net_basis_ceiling_is_still_five_percent_of_the_net_sum() -> None:
    position = compute_retention({"L1": D("900000")}, contract_sum=CONTRACT_SUM, policy=_capped("10", "5"))
    assert position.total == D("50000.00")
