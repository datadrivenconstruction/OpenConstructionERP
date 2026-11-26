"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Committed from documents split across budget lines adds up to the cent."""

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


def _repo(
    monkeypatch: pytest.MonkeyPatch,
    lines: list[Any],
    spine: dict[str, Decimal],
    explicit: list[tuple[str, str | None, Decimal]] | None = None,
) -> BudgetLineRepository:
    repo = BudgetLineRepository(SimpleNamespace())  # type: ignore[arg-type]

    async def _lines(_pid: uuid.UUID) -> list[Any]:
        return lines

    async def _fx(_pid: uuid.UUID) -> tuple[str, dict[str, str]]:
        return "EUR", {}

    async def _spine(_pid: uuid.UUID) -> dict[str, Decimal]:
        return spine

    monkeypatch.setattr(repo, "_list_lines_for_rollup", _lines)
    monkeypatch.setattr(repo, "_project_fx_context", _fx)

    async def _explicit(_pid: uuid.UUID, _base: str, _fx: dict[str, str]) -> list[tuple[str, str | None, Decimal]]:
        return explicit or []

    monkeypatch.setattr(repo, "_spine_committed_by_cost_line", _spine)
    monkeypatch.setattr(repo, "_explicit_commitments", _explicit)
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


@pytest.mark.asyncio
async def test_order_booked_to_a_cost_type_line_commits_there_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cost code 1.01 has a labour line (planned 400) and a material line (planned 600).
    # A 300 material order is booked to the material line and a 100 order sits on the
    # cost line with no budget line named: the 300 lands on material, only the 100 is shared.
    cost_line_id = uuid.uuid4()
    labour = _line(cost_line_id, planned="400")
    material = _line(cost_line_id, planned="600")
    repo = _repo(
        monkeypatch,
        [labour, material],
        {str(cost_line_id): Decimal("400.00")},
        explicit=[(str(material.id), str(cost_line_id), Decimal("300"))],
    )

    by_line, unbudgeted, from_documents = await repo.effective_committed(uuid.uuid4())

    assert by_line[labour.id] == Decimal("40.00")
    assert by_line[material.id] == Decimal("360.00")
    assert sum(by_line.values()) == Decimal("400.00")
    assert unbudgeted == Decimal("0")
    assert from_documents == {labour.id, material.id}


@pytest.mark.asyncio
async def test_agreement_booked_to_a_line_without_cost_line_supersedes_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    line = _line(uuid.uuid4(), planned="5000", committed="1234")
    repo = _repo(monkeypatch, [line], {}, explicit=[(str(line.id), None, Decimal("4500"))])

    by_line, _unbudgeted, from_documents = await repo.effective_committed(uuid.uuid4())

    assert by_line[line.id] == Decimal("4500.00")
    assert from_documents == {line.id}
