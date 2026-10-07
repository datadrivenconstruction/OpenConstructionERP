# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legacy contract dashboards must agree with payment applications, without backfill."""

from decimal import Decimal

import pytest

from app.modules.contracts.schemas import ContractDashboardResponse
from app.modules.contracts.service import ContractsService
from tests.modules.test_aia_payment_applications import _seed_claim, session  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current,original,metadata,terms,expected_original,expected_changes",
    [
        ("120", None, {"change_order_total": "20"}, {}, "100", "20"),
        ("80", None, {"change_order_total": "-20"}, {}, "100", "-20"),
        ("120", None, {}, {"change_orders_net": "20"}, "100", "20"),
        ("100", None, {"change_order_total": "0"}, {"change_orders_net": "20"}, "100", "0"),
        ("125", None, {"variation_total": "25"}, {"change_orders_net": "99"}, "100", "25"),
        ("100", None, {}, {}, "100", "0"),
        ("20", "0", {"change_order_total": "20"}, {}, "0", "20"),
        ("120", "95", {"change_order_total": "20"}, {}, "95", "20"),
    ],
)
async def test_dashboard_preserves_or_reconstructs_original_like_canonical(
    session, current, original, metadata, terms, expected_original, expected_changes
):
    claim = await _seed_claim(session, country_code="US")
    service = ContractsService(session)
    contract = await service.get_contract(claim.contract_id)
    contract.total_value = Decimal(current)
    contract.original_contract_value = Decimal(original) if original is not None else None
    contract.metadata_ = metadata
    contract.terms = terms
    await session.flush()

    # Validate the actual dashboard response schema, as consumed by the UI.
    dashboard = ContractDashboardResponse.model_validate(await service.contract_dashboard(contract.id))
    application = await service.build_payment_application(claim.id)
    assert application["summary"]["original_contract_sum"] == Decimal(expected_original)
    assert application["summary"]["change_orders_net"] == Decimal(expected_changes)
    assert dashboard.original_contract_value == Decimal(expected_original)
    assert dashboard.agreed_variations == Decimal(expected_changes)
    assert dashboard.current_contract_value == Decimal(current)

    # Even an inconsistent explicit baseline is historical data, never rewritten.
    await session.refresh(contract)
    assert contract.original_contract_value == (Decimal(original) if original is not None else None)
    assert contract.total_value == Decimal(current)
