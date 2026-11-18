# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Fill a CVR report by WBS from the records the project already holds.

A monthly CVR used to be typed in by hand, cost head by cost head. Every figure
on it already exists elsewhere on the platform, so this module reads them and
folds them per WBS element (the BOQ position's ``wbs_id``):

``budget_cost``
    Sum of the positions' cost budgets, quantity x target rate when a position
    has one, else quantity x unit rate (:mod:`app.modules.boq.budget_basis`).
``committed_cost`` / ``cost_to_date``
    The open commitment and the actual cost of every order, subcontract and
    supplier invoice, from :func:`app.modules.finance.cost_position.load_cost_position`,
    the same figures the finance dashboard shows. An order lands on the WBS of
    its lines. A subcontract agreement lands on the WBS of the positions its
    contract lines are priced against, in proportion to the line values.
``value_to_date``
    The latest cumulative value claimed on client contract lines, carried to
    the WBS of the position the line is priced against.
``forecast_value``
    Sum of the positions' sale values (quantity x sale rate, else their total).
``forecast_cost``
    ``cost_to_date + committed_cost + max(budget_cost - cost_to_date - committed_cost, 0)``:
    what is spent, plus what is promised, plus the budget not yet bought.

Anything without a WBS lands on one "unallocated" line and is reported by the
``cvr.unmapped_cost`` rule, so the report always adds up to the module totals.
The folding is pure (:func:`fold`) and tested with worked numbers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.budget_basis import is_priced_line, position_budget, sale_value

ZERO = Decimal("0")
UNMAPPED = ""

#: Fields a refresh from the spine writes; a person's later edit of one of them
#: is recorded in ``metadata.overrides`` and survives every later refresh.
SPINE_FIELDS: tuple[str, ...] = (
    "budget_cost",
    "committed_cost",
    "cost_to_date",
    "value_to_date",
    "forecast_cost",
    "forecast_value",
)


@dataclass
class WbsFigures:
    """One WBS element's figures, in project currency."""

    budget_cost: Decimal = ZERO
    committed_cost: Decimal = ZERO
    cost_to_date: Decimal = ZERO
    value_to_date: Decimal = ZERO
    forecast_value: Decimal = ZERO
    positions: int = 0
    target_positions: int = 0

    @property
    def forecast_cost(self) -> Decimal:
        uncommitted = self.budget_cost - self.cost_to_date - self.committed_cost
        return self.cost_to_date + self.committed_cost + max(uncommitted, ZERO)


@dataclass(frozen=True)
class CostSource:
    """One commitment/actual record, already converted to project currency.

    ``allocation`` maps WBS key to share (fractions adding up to 1); empty
    means the record has no WBS and is unallocated.
    """

    kind: str
    ref: str
    committed: Decimal
    actual: Decimal
    allocation: tuple[tuple[str, Decimal], ...] = ()


@dataclass
class Rollup:
    """The folded figures plus what the rules need to judge them."""

    by_wbs: dict[str, WbsFigures] = field(default_factory=dict)
    budget_positions: list[dict[str, Any]] = field(default_factory=list)
    unmapped_sources: list[dict[str, Any]] = field(default_factory=list)

    def totals(self) -> dict[str, Decimal]:
        out = dict.fromkeys(("budget_cost", "committed_cost", "cost_to_date", "value_to_date", "forecast_value"), ZERO)
        for fig in self.by_wbs.values():
            for key in out:
                out[key] += getattr(fig, key)
        return out


def fold(
    positions: list[object],
    sources: list[CostSource],
    value_by_position: dict[str, Decimal] | None = None,
) -> Rollup:
    """Fold positions, cost sources and claimed value per WBS key. Pure."""
    value_by_position = value_by_position or {}
    rollup = Rollup()

    def bucket(key: str) -> WbsFigures:
        return rollup.by_wbs.setdefault(key, WbsFigures())

    for pos in positions:
        if not is_priced_line(pos):
            continue
        key = str(getattr(pos, "wbs_id", None) or UNMAPPED)
        budget = position_budget(pos)
        fig = bucket(key)
        fig.budget_cost += budget.amount
        fig.forecast_value += sale_value(pos)
        fig.value_to_date += value_by_position.get(str(pos.id), ZERO)
        fig.positions += 1
        if budget.basis == "target":
            fig.target_positions += 1
        rollup.budget_positions.append(
            {"id": str(pos.id), "ordinal": str(getattr(pos, "ordinal", "") or ""), "basis": budget.basis}
        )

    for src in sources:
        if not src.allocation:
            fig = bucket(UNMAPPED)
            fig.committed_cost += src.committed
            fig.cost_to_date += src.actual
            rollup.unmapped_sources.append(
                {"kind": src.kind, "ref": src.ref, "committed": str(src.committed), "actual": str(src.actual)}
            )
            continue
        # The last share takes the rounding rest so the parts add up exactly.
        committed_left, actual_left = src.committed, src.actual
        for index, (key, share) in enumerate(src.allocation):
            last = index == len(src.allocation) - 1
            committed = committed_left if last else (src.committed * share).quantize(Decimal("0.0001"))
            actual = actual_left if last else (src.actual * share).quantize(Decimal("0.0001"))
            committed_left -= committed
            actual_left -= actual
            fig = bucket(key)
            fig.committed_cost += committed
            fig.cost_to_date += actual
    return rollup


def _shares(weights: dict[str, Decimal]) -> tuple[tuple[str, Decimal], ...]:
    total = sum(weights.values(), ZERO)
    if total <= 0:
        return ()
    return tuple((key, value / total) for key, value in sorted(weights.items()) if value > 0)


async def load_rollup(session: AsyncSession, project_id: uuid.UUID) -> tuple[Rollup, str]:
    """Read the project's records and fold them. Returns the rollup and the project currency."""
    from app.modules.boq.repository import PositionRepository
    from app.modules.costmodel.repository import BudgetLineRepository, _amount_in_base
    from app.modules.finance.cost_position import load_cost_position

    base, fx = await BudgetLineRepository(session)._project_fx_context(project_id)

    def in_base(amount: Decimal, currency: str | None) -> Decimal:
        return _amount_in_base(str(amount), (currency or "").strip().upper(), base, fx)

    positions = list(await PositionRepository(session).list_for_project(project_id))
    wbs_by_cost_line: dict[str, dict[str, Decimal]] = {}
    for pos in positions:
        if pos.cost_line_id is not None and getattr(pos, "wbs_id", None):
            weights = wbs_by_cost_line.setdefault(str(pos.cost_line_id), {})
            weights[str(pos.wbs_id)] = weights.get(str(pos.wbs_id), ZERO) + max(position_budget(pos).amount, ZERO)

    # Subcontract agreements reach a WBS through the contract that carries them.
    agreement_alloc: dict[str, tuple[tuple[str, Decimal], ...]] = {}
    value_by_position: dict[str, Decimal] = {}
    try:
        from app.modules.contracts.models import Contract, ContractLine, ProgressClaimLine
    except ImportError:  # pragma: no cover - contracts not installed
        Contract = None  # noqa: N806
    if Contract is not None:
        line_rows = (
            await session.execute(
                select(
                    ContractLine.id,
                    ContractLine.contract_id,
                    ContractLine.cost_line_id,
                    ContractLine.total_value,
                    Contract.counterparty_type,
                    Contract.currency,
                )
                .join(Contract, Contract.id == ContractLine.contract_id)
                .where(Contract.project_id == project_id, ContractLine.cost_line_id.is_not(None))
            )
        ).all()
        contract_weights: dict[str, dict[str, Decimal]] = {}
        client_lines: dict[uuid.UUID, tuple[str, str]] = {}
        for line_id, contract_id, cost_line_id, total, counterparty, ccy in line_rows:
            if counterparty == "subcontractor":
                for key, share in _shares(wbs_by_cost_line.get(str(cost_line_id), {})):
                    weights = contract_weights.setdefault(str(contract_id), {})
                    weights[key] = weights.get(key, ZERO) + Decimal(str(total or 0)) * share
            else:
                client_lines[line_id] = (str(cost_line_id), ccy or "")

        try:
            from app.modules.subcontractors.models import SubcontractAgreement
        except ImportError:  # pragma: no cover
            SubcontractAgreement = None  # noqa: N806
        if SubcontractAgreement is not None and contract_weights:
            links = (
                await session.execute(
                    select(SubcontractAgreement.id, SubcontractAgreement.contract_id).where(
                        SubcontractAgreement.project_id == project_id,
                        SubcontractAgreement.contract_id.is_not(None),
                    )
                )
            ).all()
            for agreement_id, contract_id in links:
                agreement_alloc[str(agreement_id)] = _shares(contract_weights.get(str(contract_id), {}))

        if client_lines:
            cumulative: dict[uuid.UUID, Decimal] = {}
            for contract_line_id, value in (
                await session.execute(
                    select(ProgressClaimLine.contract_line_id, ProgressClaimLine.cumulative_completed_value).where(
                        ProgressClaimLine.contract_line_id.in_(sorted(client_lines))
                    )
                )
            ).all():
                cumulative[contract_line_id] = max(cumulative.get(contract_line_id, ZERO), Decimal(str(value or 0)))
            positions_by_cost_line: dict[str, list[object]] = {}
            for pos in positions:
                if pos.cost_line_id is not None:
                    positions_by_cost_line.setdefault(str(pos.cost_line_id), []).append(pos)
            for contract_line_id, value in cumulative.items():
                cost_line_id, ccy = client_lines[contract_line_id]
                targets = positions_by_cost_line.get(cost_line_id, [])
                if not targets:
                    continue
                share = in_base(value, ccy) / len(targets)
                for pos in targets:
                    value_by_position[str(pos.id)] = value_by_position.get(str(pos.id), ZERO) + share

    position = await load_cost_position(session, project_id=project_id)
    sources: list[CostSource] = []
    for fig in position.sources:
        committed = in_base(fig.committed, fig.currency)
        actual = in_base(fig.actual, fig.currency)
        if fig.wbs_id:
            allocation: tuple[tuple[str, Decimal], ...] = ((str(fig.wbs_id), Decimal("1")),)
        elif fig.kind == "subcontract":
            allocation = agreement_alloc.get(str(fig.ref), ())
        else:
            allocation = ()
        sources.append(CostSource(fig.kind, str(fig.ref), committed, actual, allocation))

    return fold(positions, sources, value_by_position), base


async def wbs_labels(session: AsyncSession, project_id: uuid.UUID) -> dict[str, tuple[str, str, int]]:
    """``wbs_id -> (code, name, sort_order)`` for the project's WBS elements."""
    try:
        from app.modules.projects.models import ProjectWBS
    except ImportError:  # pragma: no cover
        return {}
    rows = (
        await session.execute(
            select(ProjectWBS.id, ProjectWBS.code, ProjectWBS.name, ProjectWBS.sort_order).where(
                ProjectWBS.project_id == project_id
            )
        )
    ).all()
    return {str(r[0]): (r[1] or "", r[2] or "", int(r[3] or 0)) for r in rows}
