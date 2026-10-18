# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phase comparison: every layer of the cost side by side on the account tree.

Each phase of a project leaves its own figure on the same cost line: the
budget, the estimate, the best tender, the award, the changes, the commitment,
the changes still waiting, the measured work, the certified work, the
invoices, the payments and the forecast. Read across, a row tells the story of
one part of the building; read down, a column is one phase of the whole
project. Accounts carry the sum of everything below them, so the comparison
reads at any level of the tree.

Percent columns put each layer against the plan (the budget, else the
estimate), and measured work and invoices against the commitment.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.cost_control import ZERO
from app.modules.costmodel.cost_control_schemas import (
    PHASE_LAYERS,
    CostControlAccount,
    CostControlRow,
    PhaseComparison,
    PhaseRow,
)
from app.modules.costmodel.cost_control_service import CostControlService
from app.modules.costmodel.forecast_docs import PCT, money

#: Report row field each layer is read from (the tender is read separately).
_ROW_FIELD: dict[str, str] = {
    "budget": "budget",
    "estimate": "estimate",
    "awarded": "awarded",
    "changes": "changes",
    "committed": "committed",
    "pending": "pending_changes",
    "measured": "measured",
    "certified": "certified",
    "invoiced": "invoiced",
    "paid": "paid",
    "forecast": "forecast",
}

#: Submissions whose prices count as a tender figure, and the line states that are priced in them.
_INCLUDED = "included"


def _pct(part: Decimal, whole: Decimal) -> str | None:
    if whole == ZERO:
        return None
    return str((part / whole * Decimal("100")).quantize(PCT))


async def tender_by_line(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    """The best (lowest) valid offer per bid line, carried to the cost lines the bid line is on.

    An installation without bid management, or a project without bid lines on
    cost lines, has no tender figure.
    """
    try:
        from app.modules.bid_management.models import BidPackage, BidPackageLineItem, BidSubmission, BidSubmissionLine
    except ImportError:  # pragma: no cover - module not installed
        return {}
    from app.modules.costmodel.inheritance import SOURCE_BID_LINE, expand, row_vectors
    from app.modules.costmodel.repository import CostSpineRepository, _amount_in_base

    rows = (
        await session.execute(
            select(
                BidPackageLineItem.id,
                BidPackageLineItem.cost_line_id,
                BidSubmissionLine.total_price,
                BidSubmission.currency,
                BidPackage.currency,
            )
            .join(BidPackage, BidPackage.id == BidPackageLineItem.package_id)
            .join(BidSubmissionLine, BidSubmissionLine.line_item_id == BidPackageLineItem.id)
            .join(BidSubmission, BidSubmission.id == BidSubmissionLine.submission_id)
            .where(
                BidPackage.project_id == project_id,
                BidPackageLineItem.cost_line_id.is_not(None),
                BidSubmission.is_valid.is_(True),
                BidSubmissionLine.inclusion_status == _INCLUDED,
            )
        )
    ).all()
    if not rows:
        return {}
    base, fx = await CostSpineRepository(session)._fx_context(project_id)
    best: dict[uuid.UUID, Decimal] = {}
    line_of: dict[uuid.UUID, uuid.UUID] = {}
    for item_id, cost_line_id, total, sub_ccy, pkg_ccy in rows:
        ccy = (sub_ccy or pkg_ccy or "").strip().upper()
        value = _amount_in_base(str(money(total)), ccy, base, fx)
        if value <= ZERO:
            continue
        line_of[item_id] = cost_line_id
        if item_id not in best or value < best[item_id]:
            best[item_id] = value
    vectors = await row_vectors(session, SOURCE_BID_LINE, {k: line_of[k] for k in best})
    out: dict[str, Decimal] = {}
    for item_id, value in best.items():
        for key, part in expand(value, vectors[str(item_id)]):
            out[str(key)] = out.get(str(key), ZERO) + part
    return out


def _values(row: CostControlRow, tender: Decimal) -> dict[str, Decimal]:
    values = {layer: getattr(row, field) for layer, field in _ROW_FIELD.items()}
    values["tender"] = tender
    return {layer: values[layer] for layer in PHASE_LAYERS}


def _phase_row(
    key: str,
    kind: str,
    values: dict[str, Decimal],
    *,
    code: str = "",
    description: str = "",
    account_id: str | None = None,
    parent_key: str | None = None,
    level: int = 1,
) -> PhaseRow:
    plan = values["budget"] if values["budget"] != ZERO else values["estimate"]
    return PhaseRow(
        key=key,
        kind=kind,  # type: ignore[arg-type]
        account_id=account_id,
        parent_key=parent_key,
        level=level,
        code=code,
        description=description,
        values=values,
        pct={layer: _pct(values[layer], plan) for layer in PHASE_LAYERS},
        progress_pct=_pct(values["measured"], values["committed"]),
        invoiced_pct=_pct(values["invoiced"], values["committed"]),
    )


def _add(into: dict[str, Decimal], values: dict[str, Decimal]) -> None:
    for layer in PHASE_LAYERS:
        into[layer] = into.get(layer, ZERO) + values[layer]


async def phase_comparison(session: AsyncSession, project_id: uuid.UUID) -> PhaseComparison:
    """The phase comparison of a project on its account tree, accounts summing everything below them."""
    report = await CostControlService(session).report(project_id)
    tender = await tender_by_line(session, project_id)
    accounts: dict[str, CostControlAccount] = {a.id: a for a in report.accounts}
    children: dict[str | None, list[CostControlAccount]] = {}
    for account in report.accounts:
        parent = account.parent_id if account.parent_id in accounts else None
        children.setdefault(parent, []).append(account)
    for siblings in children.values():
        siblings.sort(key=lambda a: a.code)

    lines_by_account: dict[str | None, list[CostControlRow]] = {}
    leftovers: list[CostControlRow] = []
    for row in report.rows:
        if row.kind in ("cost_line", "allowance"):
            owner = row.account_id if row.account_id in accounts else None
            lines_by_account.setdefault(owner, []).append(row)
        else:
            leftovers.append(row)

    out: list[PhaseRow] = []
    total: dict[str, Decimal] = dict.fromkeys(PHASE_LAYERS, ZERO)

    def line_row(row: CostControlRow, parent_key: str | None, level: int) -> PhaseRow:
        kind = "allowance" if row.kind == "allowance" else "cost_line"
        return _phase_row(
            row.key,
            kind,
            _values(row, tender.get(row.key, ZERO) if row.kind == "cost_line" else ZERO),
            code=row.code,
            description=row.description,
            account_id=row.account_id,
            parent_key=parent_key,
            level=level,
        )

    def walk(account: CostControlAccount, parent_key: str | None, level: int) -> dict[str, Decimal]:
        key = f"account:{account.id}"
        sums: dict[str, Decimal] = dict.fromkeys(PHASE_LAYERS, ZERO)
        position = len(out)
        out.append(_phase_row(key, "account", sums))  # replaced once the subtree is summed
        for child in children.get(account.id, []):
            _add(sums, walk(child, key, level + 1))
        for row in sorted(lines_by_account.get(account.id, []), key=lambda r: (r.kind != "allowance", r.code)):
            phase = line_row(row, key, level + 1)
            _add(sums, phase.values)
            out.append(phase)
        out[position] = _phase_row(
            key,
            "account",
            sums,
            code=account.code,
            description=account.title or account.name,
            account_id=account.id,
            parent_key=parent_key,
            level=level,
        )
        return sums

    for root in children.get(None, []):
        _add(total, walk(root, None, 1))
    for row in sorted(lines_by_account.get(None, []), key=lambda r: r.code):
        phase = line_row(row, None, 1)
        _add(total, phase.values)
        out.append(phase)
    unassigned: dict[str, Decimal] = dict.fromkeys(PHASE_LAYERS, ZERO)
    for row in leftovers:
        _add(unassigned, _values(row, ZERO))
    if any(v != ZERO for v in unassigned.values()):
        _add(total, unassigned)
        out.append(_phase_row("unassigned", "unassigned", unassigned))
    return PhaseComparison(
        project_id=project_id,
        currency=report.currency,
        as_of=report.as_of,
        layers=list(PHASE_LAYERS),
        rows=out,
        totals=_phase_row("total", "account", total),
    )
