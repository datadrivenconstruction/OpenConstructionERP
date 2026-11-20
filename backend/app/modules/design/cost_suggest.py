"""Where a position has no direct cost item: the ERP's own suggestions, for a person to confirm.

Two sources, both the ERP's: Cost Match (a one-line run, scored by its matcher, kept as a run with a ruling) and
Assemblies (rate = the assembly's total, ranked by shared words with the position text). Nothing is applied here;
``confirm_*`` writes the rate only on a person's call and records where it came from. Candidates whose unit or
currency differ from the position are listed as not usable, never converted.
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from . import estimate as est
from .models import DesignEstimate

MAX_ASSEMBLIES = 8
POOL = 500
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _words(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(text or "")}


def _same_unit(a: str, b: str) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _rate(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None
    return d if d > 0 else None


async def _context(session, project_id: uuid.UUID, position_id: uuid.UUID):
    from app.modules.projects.models import Project

    await est._binding_of(session, project_id, position_id)  # 404 unless this is the design's position
    pos = await est._svc(session).position_repo.get_by_id(position_id)
    project = await session.get(Project, project_id)
    currency = (getattr(project, "currency", None) or "").strip().upper()
    return pos, project, currency


def _usable(unit: str, rate: Any, currency: str, pos, project_currency: str) -> tuple[bool, str | None]:
    if not _same_unit(unit, pos.unit):
        return False, "unit"
    if not (currency or "").strip() or (project_currency and currency.strip().upper() != project_currency):
        return False, "currency"
    if _rate(rate) is None:
        return False, "rate"
    return True, None


async def assemblies(
    session, project_id: uuid.UUID, pos, project_currency: str, user_id: uuid.UUID
) -> list[dict[str, Any]]:
    from app.modules.assemblies.service import AssemblyService

    want = _words(pos.description)
    if not want:
        return []
    rows, _ = await AssemblyService(session).search_assemblies(unit=pos.unit, owner_id=user_id, limit=POOL)
    ranked = []
    for a in rows:
        if a.project_id not in (None, project_id):
            continue
        hit = want & _words(f"{a.name} {a.description} {a.category}")
        if hit:
            ranked.append((len(hit), a, sorted(hit)))
    ranked.sort(key=lambda r: (-r[0], r[1].code))
    out = []
    for n, a, hit in ranked[:MAX_ASSEMBLIES]:
        ok, why = _usable(a.unit, a.total_rate, a.currency, pos, project_currency)
        out.append(
            {
                "assembly_id": str(a.id),
                "code": a.code,
                "name": a.name,
                "unit": a.unit,
                "rate": str(a.total_rate),
                "currency": a.currency,
                "shared_words": hit,
                "usable": ok,
                "unusable_reason": why,
            }
        )
    return out


async def cost_match(
    session, project_id: uuid.UUID, pos, project, project_currency: str, user_id: uuid.UUID, est_row: DesignEstimate
) -> dict[str, Any] | None:
    """One-line Cost Match run over the cost database of the project region. None when no database serves it."""
    from app.core.match_service.region_language import language_for
    from app.modules.cost_match.models import MatchResult
    from app.modules.cost_match.schemas import MatchLineInput, MatchRunCreate
    from app.modules.cost_match.service import CostMatchService
    from app.modules.costs.models import CostItem

    regions = await est.cost_regions(session, est_row.country, getattr(project, "region", None))
    if not regions:
        return None
    region = regions[0]
    source = (
        await session.execute(
            select(CostItem.source).where(CostItem.region == region, CostItem.is_active.is_(True)).limit(1)
        )
    ).scalar_one_or_none() or "cwicr"
    svc = CostMatchService(session)
    run = await svc.create_run(
        MatchRunCreate(
            project_id=project_id,
            name=f"Design estimate {pos.ordinal}",
            source_label="design estimate",
            source_locale=language_for(region) or "en",
            cost_source=source,
            region=region,
            lines=[MatchLineInput(description=pos.description, unit=pos.unit, quantity=None, source_ref="")],
        ),
        created_by=user_id,
    )
    result = (await session.execute(select(MatchResult).where(MatchResult.run_id == run.id))).scalars().first()
    cands = []
    if result.suggested_cost_item_id is not None:
        cands.append(
            {
                "cost_item_id": str(result.suggested_cost_item_id),
                "code": result.suggested_code,
                "description": result.suggested_description,
                "unit": result.suggested_unit,
                "rate": None if result.suggested_rate is None else format(result.suggested_rate, "f"),
                "currency": result.suggested_currency,
                "confidence": format(result.confidence, "f"),
                "suggested": True,
                "reason_codes": list(result.reason_codes or []),
            }
        )
    for a in result.alternatives or []:
        if a.get("cost_item_id") and a["cost_item_id"] != str(result.suggested_cost_item_id):
            cands.append({**a, "suggested": False})
    for c in cands:
        c["usable"], c["unusable_reason"] = _usable(
            c.get("unit", ""), c.get("rate"), c.get("currency", ""), pos, project_currency
        )
    return {
        "run_id": str(run.id),
        "result_id": str(result.id),
        "region": region,
        "tier": result.tier,
        "tie": bool(result.tie),
        "hint": result.hint_code,
        "candidates": cands,
    }


async def suggest(session, project_id: uuid.UUID, position_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, Any]:
    pos, project, currency = await _context(session, project_id, position_id)
    est_row = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one()
    return {
        "position_id": str(position_id),
        "unit": pos.unit,
        "currency": currency,
        "assemblies": await assemblies(session, project_id, pos, currency, user_id),
        "cost_match": await cost_match(session, project_id, pos, project, currency, user_id, est_row),
    }


async def confirm_cost_match(
    session,
    project_id: uuid.UUID,
    position_id: uuid.UUID,
    result_id: uuid.UUID,
    cost_item_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """The person's ruling on the Cost Match result (confirmed, or overridden with another listed item), then the price."""
    from app.modules.cost_match.models import MatchResult, MatchRun
    from app.modules.cost_match.schemas import MatchDecisionCreate
    from app.modules.cost_match.service import CostMatchService, DecisionPayloadError, RunClosedError

    await _context(session, project_id, position_id)
    result = await session.get(MatchResult, result_id)
    if result is None or result.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Match result not found")
    run = await session.get(MatchRun, result.run_id)
    kind = "confirmed" if cost_item_id == result.suggested_cost_item_id else "overridden"
    try:
        decision = await CostMatchService(session).record_decision(
            run,
            result,
            MatchDecisionCreate(
                decision=kind, cost_item_id=None if kind == "confirmed" else cost_item_id, note="design estimate"
            ),
            decided_by=user_id,
        )
    except (DecisionPayloadError, RunClosedError, LookupError, ValueError) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    via = {
        "kind": "cost_match",
        "run_id": str(run.id),
        "result_id": str(result.id),
        "decision": kind,
        "decision_id": str(decision.id),
        "confidence": format(result.confidence, "f"),
        "tier": result.tier,
    }
    await est.price_position(
        session,
        project_id,
        position_id,
        cost_item_id=cost_item_id,
        unit_rate=None,
        source_url=None,
        price_date=None,
        via=via,
    )


async def confirm_assembly(session, project_id: uuid.UUID, position_id: uuid.UUID, assembly_id: uuid.UUID) -> None:
    await _context(session, project_id, position_id)
    await est.price_position(
        session,
        project_id,
        position_id,
        cost_item_id=None,
        unit_rate=None,
        source_url=None,
        price_date=None,
        assembly_id=assembly_id,
    )
