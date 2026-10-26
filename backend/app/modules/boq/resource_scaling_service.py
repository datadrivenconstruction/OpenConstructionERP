# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Load a bill's lines for proportional scaling, and write a confirmed plan.

The arithmetic is :mod:`app.modules.boq.resource_scaling`. This module reads
the lines in scope, converts costs through the project's FX table the way the
rest of the bill does, and on apply: refuses a locked bill, takes a version
snapshot (the undo), rewrites the norms with the derived unit rates and
totals in one batch, and announces it so the activity feed records who scaled
what by which factor.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status

from app.modules.boq.resource_scaling import (
    RoundingRule,
    ScaleLine,
    ScalePlan,
    ScaleScope,
    ScalingError,
    plan_scaling,
    scope_line_ids,
    to_decimal,
)

#: Stored name of the snapshot taken before a scaling is applied. English data,
#: worded for the reader by ``snapshotNames.ts`` like the other system names.
SCALING_SNAPSHOT_NAME = "Before proportional scaling"

#: Event announcing an applied scaling; the activity feed words it.
SCALED_EVENT = "boq.positions.resources_scaled"


@dataclass(slots=True)
class ScaleRequest:
    """What the user asked for, independent of the transport."""

    metric: str
    target: Decimal | None
    section_id: uuid.UUID | None = None
    position_ids: list[uuid.UUID] | None = None
    resource_type: str | None = None
    resource_key: str | None = None
    decimals: int = 3
    rounding_mode: str = "half_up"
    excluded_position_ids: list[uuid.UUID] | None = None


def _is_locked_line(meta: dict[str, Any]) -> bool:
    return bool(meta.get("locked"))


def _to_base_factory(fx_map: dict[str, str] | None, base_currency: str) -> Callable[[Decimal, str], Decimal | None]:
    from app.modules.boq.service import resource_fx_factor

    base = (base_currency or "").strip().upper()

    def to_base(amount: Decimal, code: str) -> Decimal | None:
        cur = (code or "").strip().upper()
        if resource_fx_factor(cur, base, fx_map) is None:
            return None
        if cur and base and cur != base:
            return amount * to_decimal((fx_map or {}).get(cur))
        return amount

    return to_base


async def build_plan(service: Any, boq_id: uuid.UUID, req: ScaleRequest) -> tuple[ScalePlan, dict[str, Any]]:
    """The plan for ``req`` and the stored rows it was computed from, by id."""
    from app.modules.boq.service import _is_section

    positions = await service.position_repo.list_all_for_boq(boq_id)
    by_id = {str(p.id): p for p in positions}
    if req.section_id is not None:
        section = by_id.get(str(req.section_id))
        if section is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "scaling_scope_not_found"})
        in_scope = scope_line_ids(positions, str(req.section_id), _is_section)
        if not _is_section(section):
            in_scope.add(str(section.id))
    elif req.position_ids:
        in_scope = {str(pid) for pid in req.position_ids if str(pid) in by_id and not _is_section(by_id[str(pid)])}
    else:
        in_scope = scope_line_ids(positions, None, _is_section)

    excluded = {str(pid) for pid in req.excluded_position_ids or []}
    base_currency, fx_map = await service.get_export_fx(boq_id)
    lines: list[ScaleLine] = []
    for p in positions:
        pid = str(p.id)
        if pid not in in_scope:
            continue
        meta = p.metadata_ if isinstance(p.metadata_, dict) else {}
        resources = meta.get("resources")
        lines.append(
            ScaleLine(
                id=pid,
                ordinal=p.ordinal or "",
                description=(p.description or "")[:200],
                quantity=to_decimal(p.quantity),
                resources=[dict(r) if isinstance(r, dict) else r for r in resources]
                if isinstance(resources, list)
                else [],
                total=to_decimal(p.total),
                currency=str(meta.get("currency") or ""),
                locked=_is_locked_line(meta),
                excluded=pid in excluded,
            )
        )
    try:
        plan = plan_scaling(
            lines,
            scope=ScaleScope(resource_type=req.resource_type or None, resource_key=req.resource_key or None),
            metric=req.metric,  # type: ignore[arg-type]
            target=req.target,
            rounding=RoundingRule(decimals=req.decimals, mode=req.rounding_mode),  # type: ignore[arg-type]
            to_base=_to_base_factory(fx_map, base_currency),
        )
    except ScalingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": f"scaling_{exc.code}", "message": str(exc), "params": exc.params},
        ) from exc
    return plan, by_id


async def apply_plan(
    service: Any,
    boq_id: uuid.UUID,
    req: ScaleRequest,
    *,
    user_id: uuid.UUID | None,
    expected_factor: Decimal | None = None,
) -> dict[str, Any]:
    """Write the plan for ``req``: snapshot, rewrite, announce. Returns the plan and the snapshot id.

    Raises:
        HTTPException 409: the bill is locked, or the figures moved since the
            preview the user confirmed (``expected_factor`` no longer matches).
    """
    from app.modules.boq.service import (
        _compute_total,
        _has_contributing_resources,
        _quantize_money_str,
        _resource_total_in_base,
        _safe_publish,
        _stamp_resource_breakdown,
    )

    await service._ensure_not_locked(boq_id)
    plan, by_id = await build_plan(service, boq_id, req)
    if expected_factor is not None and abs(plan.factor - expected_factor) > abs(expected_factor) * Decimal("1e-9"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "scaling_preview_stale", "params": {"factor": str(plan.factor)}},
        )
    changed = plan.changed_lines
    if not changed:
        return {"plan": plan.to_dict(), "snapshot_id": None, "updated": 0}

    snapshot = await service.create_snapshot(
        boq_id,
        name=SCALING_SNAPSHOT_NAME,
        description=(
            f"{plan.metric}: {plan.current} -> target {plan.target}, factor {plan.factor:.6f}, "
            f"{len(changed)} position(s)"
        ),
        user_id=user_id,
    )
    base_currency, fx_map = await service.get_export_fx(boq_id)
    writes: list[dict[str, Any]] = []
    for line in changed:
        position = by_id[line.id]
        meta = dict(position.metadata_) if isinstance(position.metadata_, dict) else {}
        meta["resources"] = line.resources
        _stamp_resource_breakdown(meta)
        row: dict[str, Any] = {"id": position.id, "metadata_": meta, "version": int(position.version or 0) + 1}
        if _has_contributing_resources(line.resources):
            res_dicts = [r for r in line.resources or [] if isinstance(r, dict)]
            unit_rate = _quantize_money_str(_resource_total_in_base(res_dicts, fx_map, base_currency or ""))
            row["unit_rate"] = unit_rate
            row["total"] = _compute_total(position.quantity, unit_rate)
        writes.append(row)
    await service.position_repo.update_many(writes)

    project_id = await service.position_repo.project_id_for_boq(boq_id)
    await _safe_publish(
        SCALED_EVENT,
        {
            "boq_id": str(boq_id),
            "project_id": str(project_id) if project_id else None,
            "user_id": str(user_id) if user_id else None,
            "count": len(changed),
            "changes": {
                "metric": plan.metric,
                "target": str(plan.target),
                "before": str(plan.current),
                "achieved": str(plan.achieved),
                "factor": str(plan.factor),
                "resource_type": req.resource_type,
                "resource_key": req.resource_key,
                "section_id": str(req.section_id) if req.section_id else None,
                "rounding": {"decimals": plan.rounding.decimals, "mode": plan.rounding.mode},
                "snapshot_id": str(snapshot.id),
                "position_ids": [line.id for line in changed],
            },
        },
        session=service.session,
    )
    return {"plan": plan.to_dict(), "snapshot_id": str(snapshot.id), "updated": len(changed)}
