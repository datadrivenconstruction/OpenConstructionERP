"""Committed from documents split across budget lines adds up to the cent."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.costmodel.repository import BudgetLineRepository


def _line(cost_line_id: uuid.UUID, *, planned: str, committed: str = "0") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        cost_line_id=cost_line_id,
        category="subcontractor",
        planned_amount=planned,
        committed_amount=committed,
        actual_amount="0",
        forecast_amount="0",
        currency="EUR",
    )


def _repo(monkeypatch: pytest.MonkeyPatch, lines: list[Any], spine: dict[str, Decimal]) -> BudgetLineRepository:
    repo = BudgetLineRepository(SimpleNamespace())  # type: ignore[arg-type]

    async def _lines(_pid: uuid.UUID) -> list[Any]:
        return lines

    async def _fx(_pid: uuid.UUID) -> tuple[str, dict[str, str]]:
        return "EUR", {}

    async def _spine(_pid: uuid.UUID) -> dict[str, Decimal]:
        return spine

    monkeypatch.setattr(repo, "_list_lines_for_rollup", _lines)
    monkeypatch.setattr(repo, "_project_fx_context", _fx)
    monkeypatch.setattr(repo, "_spine_committed_by_cost_line", _spine)
    return repo


@pytest.mark.asyncio
async def test_three_lines_split_100_to_the_cent(monkeypatch: pytest.MonkeyPatch) -> None:
    cost_line_id = uuid.uuid4()
    lines = [_line(cost_line_id, planned="10", committed="999") for _ in range(3)]
    repo = _repo(monkeypatch, lines, {str(cost_line_id): Decimal("100.00")})

    by_line, unbudgeted, from_documents = await repo.effective_committed(uuid.uuid4())

    shares = [by_line[line.id] for line in lines]
    assert shares == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    assert sum(shares) == Decimal("100.00")
    assert from_documents == {line.id for line in lines}
    assert unbudgeted == Decimal("0")

    totals = await repo.aggregate_by_project(uuid.uuid4())
    assert Decimal(totals["total_committed"]) == sum(shares)


@pytest.mark.asyncio
async def test_uneven_planned_split_is_whole_cents(monkeypatch: pytest.MonkeyPatch) -> None:
    cost_line_id = uuid.uuid4()
    lines = [_line(cost_line_id, planned=p) for p in ("1", "1", "1", "7")]
    repo = _repo(monkeypatch, lines, {str(cost_line_id): Decimal("100.005")})

    by_line, _unbudgeted, _from_documents = await repo.effective_committed(uuid.uuid4())

    shares = [by_line[line.id] for line in lines]
    assert all(share == share.quantize(Decimal("0.01")) for share in shares)
    # 100.005 rounds half-even to 100.00 before it is split.
    assert sum(shares) == Decimal("100.00")
    totals = await repo.aggregate_by_project(uuid.uuid4())
    assert Decimal(totals["total_committed"]) == sum(shares)
