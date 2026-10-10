# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The invoice of a certificate that has a previous one behind it.

Raising the invoice of a certified claim refuses when the certificate was
taxed on another amount than the claim's gross. A refusal that fires on the
ordinary second certificate would stop every project at its second month, so
this walks two certificates through the contracts module itself: measured,
completed, taxed, confirmed and certified, with nothing stored by hand. The
second one counts the first as previous, and its invoice has to be raised on
the certificate's own figures.

The rates are the synthetic ones of the certificate tests, not a published
rate of any country.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.contracts.service import ContractsService
from app.modules.finance.service import FinanceService
from tests.pg.test_hakedis_progress_claims import (  # type: ignore[import-not-found]
    OWNER_ID,
    TAX_CHOICES,
    _amounts,
    _bill,
    _certify,
    _claim,
    _confirm_taxes,
    _contract,
    _enter_manual_lines,
    _measure,
    _project,
    rates,  # noqa: F401  (fixture)
    session,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.asyncio

D = Decimal


async def _certified(session, svc: ContractsService, contract, lines, number: int):  # noqa: F811
    claim = await _measure(svc, await _claim(session, contract, number), lines, number)
    await _enter_manual_lines(svc, claim.id, advance="0.00")
    await svc.save_hakedis_taxes(claim.id, TAX_CHOICES, str(OWNER_ID))
    await _confirm_taxes(session, claim.id)
    certified = await _certify(svc, claim.id)
    assert certified.status == "certified"
    return certified, await svc.hakedis_view(claim.id, locale="tr")


async def test_the_second_certificate_is_invoiced_on_its_own_figures(session) -> None:  # noqa: F811
    project = await _project(session)
    contract = await _contract(session, project)
    lines = await _bill(session, contract)
    svc = ContractsService(session)
    finance = FinanceService(session)

    _first, first_view = await _certified(session, svc, contract, lines, 1)
    second, second_view = await _certified(session, svc, contract, lines, 2)
    amounts = _amounts(second_view)

    # The case that tells the two readings apart: the second sheet has a
    # previous total, so its cumulative work is not its own amount.
    assert amounts["previous_certificates"] == D(first_view["carried_total"]) > 0
    assert amounts["total"] > amounts["this_certificate"] > 0

    invoice = await finance.create_receivable_from_claim(second.id, actor_id=str(OWNER_ID))

    assert D(str(invoice.amount_subtotal)) == amounts["this_certificate"] == D(str(second.gross_amount))
    assert D(str(invoice.tax_amount)) == amounts["vat"]
    assert invoice.currency_code == "TRY"
    print(
        f"second certificate: total {amounts['total']} | previous {amounts['previous_certificates']} | "
        f"this {amounts['this_certificate']} | VAT {amounts['vat']} | invoice subtotal {invoice.amount_subtotal} "
        f"tax {invoice.tax_amount}"
    )
