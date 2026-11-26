"""Submitted / assessed / certified grid of one progress claim.

Submitted is the claim line's period quantity and stored period value;
assessed and certified amounts are their quantity times the schedule line's
unit rate. The running total is the stored cumulative completed value, read
against the same line on the latest earlier claim that was not rejected.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.valuation_grid import GridLine, grid_with_findings
from app.modules.contracts.models import ContractLine, ProgressClaim, ProgressClaimLine

NOTE_KEY = "valuation_note"


def claim_note(claim: ProgressClaim) -> str:
    """The valuation note kept in the claim's metadata."""
    meta = claim.metadata_ if isinstance(claim.metadata_, dict) else {}
    return str(meta.get(NOTE_KEY) or "")


async def build_claim_grid(session: AsyncSession, claim: ProgressClaim) -> dict[str, Any]:
    """The grid of ``claim`` with findings, ready for :class:`ValuationGridResponse`."""
    lines = list(
        (await session.execute(select(ProgressClaimLine).where(ProgressClaimLine.progress_claim_id == claim.id)))
        .scalars()
        .all()
    )
    sov = {
        cl.id: cl
        for cl in (await session.execute(select(ContractLine).where(ContractLine.contract_id == claim.contract_id)))
        .scalars()
        .all()
    }
    earlier = (
        await session.execute(
            select(ProgressClaimLine, ProgressClaim.created_at)
            .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
            .where(
                ProgressClaim.contract_id == claim.contract_id,
                ProgressClaim.id != claim.id,
                ProgressClaim.status != "rejected",
                ProgressClaim.created_at < claim.created_at,
            )
            .order_by(ProgressClaim.created_at)
        )
    ).all()
    prior_cum: dict[Any, Decimal] = {}
    prior_cert: dict[Any, Decimal] = {}
    for row, _created in earlier:
        prior_cum[row.contract_line_id] = Decimal(str(row.cumulative_completed_value))
        prior_cert[row.contract_line_id] = prior_cert.get(row.contract_line_id, Decimal("0")) + Decimal(
            str(row.certified_qty)
        )
    grid_lines: list[GridLine] = []
    for ln in lines:
        cl = sov.get(ln.contract_line_id)
        rate = Decimal(str(cl.unit_rate)) if cl is not None and cl.unit_rate is not None else None
        label = " ".join(p for p in ((cl.code or "") if cl else "", (cl.description or "") if cl else "") if p)
        grid_lines.append(
            GridLine(
                id=str(ln.id),
                label=label or str(ln.contract_line_id),
                unit=getattr(cl, "unit", None) if cl is not None else None,
                submitted_qty=Decimal(str(ln.period_completed_qty)),
                assessed_qty=Decimal(str(ln.assessed_qty)),
                certified_qty=Decimal(str(ln.certified_qty)),
                rate=rate,
                rate_source="contract_line.unit_rate" if rate is not None else None,
                submitted_amount=Decimal(str(ln.period_completed_value)),
                submitted_amount_field="period_completed_value",
                prior_certified_qty=prior_cert.get(ln.contract_line_id, Decimal("0")),
                prior_cumulative=prior_cum.get(ln.contract_line_id),
                cumulative=Decimal(str(ln.cumulative_completed_value)),
                cumulative_field="cumulative_completed_value",
            )
        )
    note = claim_note(claim)
    grid = await grid_with_findings(grid_lines, note=note, target_type="progress_claim", target_id=str(claim.id))
    return {
        "source_kind": "progress_claim",
        "source_id": str(claim.id),
        "document_number": claim.claim_number or "",
        "status": claim.status,
        "currency": claim.currency or "",
        "note": note,
        **grid,
    }
