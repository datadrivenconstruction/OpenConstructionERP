# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Confirming a goods receipt publishes the one event the stock ledger follows."""

from __future__ import annotations

import inspect

from app.modules.procurement import events
from app.modules.procurement.service import ProcurementService
from app.modules.supplier_catalogs import events as stock_events


def test_confirm_publishes_the_posted_event_with_its_idempotency_key() -> None:
    src = inspect.getsource(ProcurementService.confirm_goods_receipt)
    assert '"procurement.goods_receipt.posted"' in src
    assert 'f"gr:{gr_id}:posted"' in src


def test_event_is_listed_and_the_stock_ledger_subscribes_to_it() -> None:
    assert "procurement.goods_receipt.posted" in events.PUBLISHED_EVENTS
    assert stock_events.PROCUREMENT_GR_POSTED == "procurement.goods_receipt.posted"
    assert "_on_procurement_gr_posted" in inspect.getsource(stock_events.register_subscribers)
