"""Align the resource prices of a bill with a region's resource price sheet.

A bill keeps the resource prices it was priced at. When the price sheet of
the region moves (a reprice, a resource change), the bill does not follow on
its own, and should not: the estimator decides. This module lists, per
resource, where the bill's rows differ from the sheet (old price, new price,
delta, positions affected, money effect) and, for the resources the estimator
selects, rewrites the rows and re-derives the unit rate the same way
``recalculate-rates`` does.

Rows in another currency than the sheet are never aligned: converting a price
list on the fly would put an exchange rate nobody chose into the bill. A
position whose buildup cannot re-derive its rate keeps its rate; the rows are
still aligned and the position is stamped so the validation rule
``boq.resources.aligned_rate_kept`` reports it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.resource_basis import PER_POSITION, ROW_POSITION_QUANTITY_KEY, resource_basis
from app.modules.costs.resource_pricing import _PRICE_EPS, _q2, _to_decimal, resource_key_for

logger = logging.getLogger(__name__)

ALIGNMENT_KEY = "price_alignment"


def _row_line_quantity(row: dict[str, Any], metadata: Any, position_quantity: Any) -> Decimal:
    """Quantity of the resource for the whole position."""
    if resource_basis(metadata) == PER_POSITION and row.get(ROW_POSITION_QUANTITY_KEY) not in (None, ""):
        return _to_decimal(row.get(ROW_POSITION_QUANTITY_KEY))
    return _to_decimal(row.get("quantity")) * _to_decimal(position_quantity)


def position_row_delta(row: dict[str, Any], metadata: Any, position_quantity: Any, new_price: Decimal) -> Decimal:
    """Money effect on the position total of pricing ``row`` at ``new_price``."""
    old = _to_decimal(row.get("unit_rate"))
    return _q2(_row_line_quantity(row, metadata, position_quantity) * (new_price - old))


def _currency_ok(row_ccy: Any, sheet_ccy: str) -> bool:
    row = str(row_ccy or "").strip().upper()
    sheet = (sheet_ccy or "").strip().upper()
    return not row or not sheet or row == sheet


def find_drift(
    positions: list[dict[str, Any]],
    sheet: dict[str, tuple[Decimal, str, str]],
) -> tuple[list[dict[str, Any]], int]:
    """Group the rows whose price differs from the sheet, per resource.

    Args:
        positions: ``{"id", "quantity", "metadata"}`` per leaf position.
        sheet: ``resource_key -> (unit_price, currency, name)``, priced rows only.

    Returns:
        ``(groups, rows_skipped_currency)``. Each group carries ``resource_key``,
        ``name``, ``code``, ``old_prices`` (distinct, sorted), ``new_price``,
        ``delta`` (new minus the highest old), ``positions``, ``rows`` and
        ``amount_delta`` (effect on the bill's total, rounded per row).
    """
    groups: dict[str, dict[str, Any]] = {}
    skipped = 0
    for pos in positions:
        meta = pos.get("metadata") if isinstance(pos.get("metadata"), dict) else {}
        resources = meta.get("resources")
        if not isinstance(resources, list):
            continue
        for row in resources:
            if not isinstance(row, dict):
                continue
            key = resource_key_for(row.get("code"), row.get("name"))
            hit = sheet.get(key)
            if hit is None:
                continue
            price, ccy, name = hit
            old = _to_decimal(row.get("unit_rate"))
            if abs(price - old) < _PRICE_EPS:
                continue
            if not _currency_ok(row.get("currency"), ccy):
                skipped += 1
                continue
            g = groups.setdefault(
                key,
                {
                    "resource_key": key,
                    "name": name or str(row.get("name") or ""),
                    "code": str(row.get("code") or ""),
                    "unit": str(row.get("unit") or ""),
                    "currency": ccy,
                    "old_prices": set(),
                    "new_price": price,
                    "position_ids": set(),
                    "rows": 0,
                    "amount_delta": Decimal("0"),
                },
            )
            g["old_prices"].add(_q2(old))
            g["position_ids"].add(str(pos["id"]))
            g["rows"] += 1
            g["amount_delta"] += position_row_delta(row, meta, pos.get("quantity"), price)
    out = []
    for g in groups.values():
        olds = sorted(g.pop("old_prices"))
        ids = sorted(g.pop("position_ids"))
        g["old_prices"] = olds
        g["delta"] = g["new_price"] - olds[-1]
        g["positions"] = len(ids)
        g["position_ids"] = ids
        out.append(g)
    out.sort(key=lambda g: abs(g["amount_delta"]), reverse=True)
    return out, skipped


def align_rows(
    resources: list[Any],
    sheet: dict[str, tuple[Decimal, str, str]],
    selected: set[str],
) -> tuple[list[Any], list[dict[str, str]]]:
    """Price the selected resources' rows at the sheet price.

    Returns the new rows and one ``{resource_key, from, to}`` per changed row.
    """
    out: list[Any] = []
    changes: list[dict[str, str]] = []
    for row in resources:
        if not isinstance(row, dict):
            out.append(row)
            continue
        key = resource_key_for(row.get("code"), row.get("name"))
        hit = sheet.get(key) if key in selected else None
        old = _to_decimal(row.get("unit_rate"))
        if hit is None or abs(hit[0] - old) < _PRICE_EPS or not _currency_ok(row.get("currency"), hit[1]):
            out.append(row)
            continue
        new = dict(row)
        new["unit_rate"] = float(hit[0])
        if "total" in row:
            new["total"] = float(_q2(_to_decimal(row.get("quantity")) * hit[0]))
        out.append(new)
        changes.append({"resource_key": key, "from": str(old), "to": str(hit[0])})
    return out, changes


async def load_sheet(session: AsyncSession, region: str) -> dict[str, tuple[Decimal, str, str]]:
    """Priced rows of a region's resource price sheet."""
    from app.modules.costs.models import ResourcePrice

    rows = (
        await session.execute(
            select(
                ResourcePrice.resource_key,
                ResourcePrice.unit_price,
                ResourcePrice.currency,
                ResourcePrice.resource_name,
            ).where(ResourcePrice.region == region, ResourcePrice.is_active.is_(True))
        )
    ).all()
    out: dict[str, tuple[Decimal, str, str]] = {}
    for key, price, ccy, name in rows:
        p = _to_decimal(price)
        if p >= _PRICE_EPS:
            out[key] = (p, ccy or "", name or "")
    return out


def _leaf_inputs(positions: list[Any]) -> list[dict[str, Any]]:
    parents = {p.parent_id for p in positions if p.parent_id}
    return [
        {"id": p.id, "quantity": p.quantity, "metadata": p.metadata_ if isinstance(p.metadata_, dict) else {}}
        for p in positions
        if p.id not in parents
    ]


async def preview_alignment(session: AsyncSession, boq_id: uuid.UUID, region: str) -> dict[str, Any]:
    """Dry run: what aligning the bill with the region's sheet would change."""
    from app.modules.boq.repository import PositionRepository

    sheet = await load_sheet(session, region)
    positions = await PositionRepository(session).list_all_for_boq(boq_id)
    groups, skipped = find_drift(_leaf_inputs(positions), sheet)
    return {
        "boq_id": boq_id,
        "region": region,
        "sheet_resources": len(sheet),
        "rows": groups,
        "rows_skipped_currency": skipped,
        "amount_delta_total": _q2(sum((g["amount_delta"] for g in groups), Decimal("0"))),
    }


async def apply_alignment(
    session: AsyncSession,
    boq_id: uuid.UUID,
    region: str,
    resource_keys: list[str],
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Align the selected resources and re-derive unit rates, in one transaction."""
    from app.core.audit import audit_log
    from app.modules.boq.resource_norms import untrusted_buildup_reason
    from app.modules.boq.service import BOQService, _compute_total, _derived_unit_rate_str

    service = BOQService(session)
    await service._ensure_not_locked(boq_id)
    sheet = await load_sheet(session, region)
    selected = {k for k in resource_keys if k in sheet}
    positions = await service.position_repo.list_all_for_boq(boq_id)
    snapshots = [
        (p.id, p.source, p.quantity, dict(p.metadata_) if isinstance(p.metadata_, dict) else {})
        for p in positions
        if p.id not in {q.parent_id for q in positions if q.parent_id}
    ]
    fx_base, fx_map = await service._resolve_project_fx(boq_id)
    stamp_at = datetime.now(UTC).isoformat()
    positions_changed = 0
    rows_changed = 0
    rates_kept = 0
    for pos_id, source, qty, meta in snapshots:
        resources = meta.get("resources")
        if not isinstance(resources, list) or not selected:
            continue
        new_rows, changes = align_rows(resources, sheet, selected)
        if not changes:
            continue
        meta["resources"] = new_rows
        reason = untrusted_buildup_reason(source=source, metadata=meta, quantity=qty, resources=new_rows)
        fields: dict[str, Any] = {}
        new_rate = _derived_unit_rate_str(new_rows, meta, qty, fx_map, fx_base or "")
        kept = reason is not None or _to_decimal(new_rate) <= 0
        if not kept:
            fields["unit_rate"] = new_rate
            fields["total"] = _compute_total(qty, new_rate)
        else:
            rates_kept += 1
        meta[ALIGNMENT_KEY] = {"region": region, "at": stamp_at, "rows": changes, "rate_kept": kept}
        fields["metadata_"] = meta
        await service.position_repo.update_fields(pos_id, **fields)
        positions_changed += 1
        rows_changed += len(changes)
    entry = await audit_log(
        session,
        action="update",
        entity_type="boq",
        entity_id=str(boq_id),
        user_id=user_id,
        details={
            "kind": "resource_price_alignment",
            "region": region,
            "resource_keys": sorted(selected),
            "positions_changed": positions_changed,
            "rows_changed": rows_changed,
            "rates_kept": rates_kept,
        },
    )
    await session.commit()
    return {
        "boq_id": boq_id,
        "region": region,
        "positions_changed": positions_changed,
        "rows_changed": rows_changed,
        "rates_kept": rates_kept,
        "audit_id": entry.id,
    }
