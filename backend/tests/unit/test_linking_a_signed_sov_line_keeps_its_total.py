# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Linking a schedule of values line to the bill leaves its signed total alone.

A signed line's total is the agreed figure and is not always quantity x rate:
0.7 x 37 is 25.90, and 0.7 x 36.9963 is 25.8974. ``update_line`` rewrote
``total_value`` as quantity x rate on every write, including the link-only
write a signed contract still accepts, so linking a line moved signed money.
The total is now recomputed only when quantity or rate is written.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.contracts.schemas import ContractLineUpdate
from app.modules.contracts.service import ContractService


def _service(line: SimpleNamespace) -> tuple[ContractService, AsyncMock]:
    svc = ContractService.__new__(ContractService)
    svc.session = SimpleNamespace(refresh=AsyncMock())
    update_fields = AsyncMock()
    svc.line_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=line), update_fields=update_fields)
    svc._assert_line_may_be_linked = AsyncMock()  # type: ignore[method-assign]
    svc._assert_line_may_change = AsyncMock()  # type: ignore[method-assign]
    return svc, update_fields


def _signed_line() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        contract_id=uuid.uuid4(),
        quantity=Decimal("0.7"),
        unit_rate=Decimal("36.9963"),
        total_value=Decimal("25.90"),
        metadata_={},
    )


@pytest.mark.asyncio
async def test_link_only_write_keeps_the_signed_total() -> None:
    line = _signed_line()
    svc, update_fields = _service(line)

    await svc.update_line(line.id, ContractLineUpdate(metadata={"boq_position_id": str(uuid.uuid4())}))

    written = update_fields.await_args.kwargs
    assert "total_value" not in written
    assert "metadata_" in written


@pytest.mark.asyncio
async def test_description_edit_keeps_the_total() -> None:
    line = _signed_line()
    svc, update_fields = _service(line)

    await svc.update_line(line.id, ContractLineUpdate(description="Formwork, walls"))

    assert "total_value" not in update_fields.await_args.kwargs


@pytest.mark.asyncio
async def test_quantity_edit_still_recomputes_the_total() -> None:
    line = _signed_line()
    svc, update_fields = _service(line)

    await svc.update_line(line.id, ContractLineUpdate(quantity=Decimal("2")))

    assert update_fields.await_args.kwargs["total_value"] == Decimal("2") * Decimal("36.9963")
