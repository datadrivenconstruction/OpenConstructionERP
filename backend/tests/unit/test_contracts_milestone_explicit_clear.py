# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An instalment can be switched from a fixed amount to a percentage.

The contracts updates drop None so an omitted field is never written as
NULL. For an instalment that made the switch impossible: ``value`` wins over
``percent_of_contract``, and a PATCH sending ``value: null`` was ignored. The
same held for clearing the instalment's own payment terms back to the
contract's.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.contracts.schemas import ContractMilestoneUpdate
from app.modules.contracts.service import _MILESTONE_CLEARABLE, ContractsService


class _Repo:
    def __init__(self) -> None:
        self.written: dict[str, Any] = {}

    async def update_fields(self, _id: Any, **fields: Any) -> None:
        self.written.update(fields)


class _Session:
    async def refresh(self, _obj: Any) -> None:
        return None


async def _apply(payload: dict[str, Any], clearable: frozenset[str]) -> dict[str, Any]:
    svc = ContractsService.__new__(ContractsService)
    svc.session = _Session()
    repo = _Repo()
    obj = SimpleNamespace(id="m1", metadata_={})
    await svc._apply_update(repo, obj, ContractMilestoneUpdate(**payload), clearable=clearable)
    return repo.written


@pytest.mark.asyncio
async def test_an_explicit_null_clears_the_amount_so_the_percentage_counts() -> None:
    written = await _apply({"value": None, "percent_of_contract": "10"}, _MILESTONE_CLEARABLE)
    assert written == {"value": None, "percent_of_contract": Decimal("10")}


@pytest.mark.asyncio
async def test_an_explicit_null_clears_the_instalments_own_terms() -> None:
    assert await _apply({"payment_terms_days": None}, _MILESTONE_CLEARABLE) == {"payment_terms_days": None}


@pytest.mark.asyncio
async def test_an_omitted_field_is_still_left_alone() -> None:
    assert await _apply({"name": "Roof on"}, _MILESTONE_CLEARABLE) == {"name": "Roof on"}


@pytest.mark.asyncio
async def test_a_null_outside_the_clearable_set_is_still_dropped() -> None:
    # ``status`` is not nullable: a null there means "not sent", as before.
    assert await _apply({"status": None, "name": "Roof on"}, _MILESTONE_CLEARABLE) == {"name": "Roof on"}
    # And without a clearable set the old behaviour holds for every field.
    assert await _apply({"value": None, "name": "Roof on"}, frozenset()) == {"name": "Roof on"}
