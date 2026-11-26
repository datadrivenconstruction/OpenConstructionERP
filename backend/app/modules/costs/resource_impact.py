"""Impact of changing one resource, previewed first and applied on confirmation.

A resource (a labour grade, a concrete class, a machine) is shared by many
work items, and through them by assemblies and bills. Changing its price or its
name used to be a blind edit followed by a region-wide reprice. This module
answers "what does this touch and by how much" before anything is written, and
then writes exactly that, in one transaction, with an audit record.

The work-item delta is exact: every matching line is recomputed as
``quantity x new_price`` against the cost it carries now. Assemblies report the
component-level delta (``factor x item delta``) before their bid factor; they
pull the new rates through the existing ``costs.region.repriced`` subscriber
after the apply. Bills are only counted, never changed here: a bill keeps the
prices it was priced at until its estimator aligns it (BOQ price alignment).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.audit import audit_log
from app.modules.costs.models import CostItem, ResourcePrice
from app.modules.costs.resource_pricing import (
    _breakdown_metadata,
    _q2,
    _safe_publish,
    _to_decimal,
    component_quantity,
    resource_key_for,
)
from app.modules.costs.validators import ChangeIssue, check_resource_change

logger = logging.getLogger(__name__)

_SCAN_ROWS = 2000
_MAX_ITEMS = 250_000
_MAX_POSITIONS = 50_000
_SAMPLE = 200
_UNSET: Any = object()


class ResourceNotFoundError(LookupError):
    """The resource key is not on the region's price sheet."""


class ResourceChangeRefusedError(ValueError):
    """The change has blocking findings or the region moved since the preview."""

    def __init__(self, message: str, issues: list[ChangeIssue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


def rewrite_components(
    components: list[Any],
    key: str,
    new_price: Decimal,
    new_name: str | None,
) -> tuple[list[Any], Decimal, int, bool]:
    """Rewrite the lines of one recipe that carry ``key``.

    Returns ``(new_components, delta, matched_lines, unreadable)``. ``delta`` is
    the change of the item's rate, the sum over matching lines of
    ``q2(quantity x new_price) - current line cost``. A matching line without a
    usable quantity makes the recipe unreadable; the caller leaves it alone.
    """
    out: list[Any] = []
    delta = Decimal("0")
    matched = 0
    unreadable = False
    for comp in components or []:
        if not isinstance(comp, dict) or resource_key_for(comp.get("code"), comp.get("name")) != key:
            out.append(comp)
            continue
        matched += 1
        qty = component_quantity(comp)
        if qty is None:
            unreadable = True
            out.append(comp)
            continue
        if comp.get("cost") not in (None, ""):
            old_cost = _to_decimal(comp.get("cost"))
        else:
            old_cost = _q2(qty * _to_decimal(comp.get("unit_rate")))
        new_cost = _q2(qty * new_price)
        delta += new_cost - old_cost
        new_comp = dict(comp)
        new_comp["unit_rate"] = float(new_price)
        new_comp["cost"] = float(new_cost)
        if new_name is not None:
            new_comp["name"] = new_name
        out.append(new_comp)
    return out, delta, matched, unreadable


def _by_type(components: list[Any]) -> tuple[dict[str, Decimal], Decimal]:
    by_type: dict[str, Decimal] = {}
    total = Decimal("0")
    for comp in components:
        if not isinstance(comp, dict):
            continue
        cost = _to_decimal(comp.get("cost"))
        ctype = str(comp.get("type") or "other")
        by_type[ctype] = by_type.get(ctype, Decimal("0")) + cost
        total += cost
    return by_type, total


@dataclass
class ImpactResult:
    """Everything the preview shows and the apply writes."""

    region: str
    resource_key: str
    new_resource_key: str
    old_name: str
    new_name: str
    old_unit_price: Decimal
    new_unit_price: Decimal
    currency: str
    cost_items: list[dict[str, Any]] = field(default_factory=list)
    cost_items_count: int = 0
    cost_items_unreadable: int = 0
    cost_items_delta_total: Decimal = Decimal("0")
    assemblies: list[dict[str, Any]] = field(default_factory=list)
    assemblies_count: int = 0
    boqs: list[dict[str, Any]] = field(default_factory=list)
    boq_positions_count: int = 0
    issues: list[ChangeIssue] = field(default_factory=list)
    truncated: bool = False
    applied: bool = False
    audit_id: uuid.UUID | None = None
    # id -> (new components, new rate, delta); kept for the apply, not returned.
    _writes: dict[uuid.UUID, tuple[list[Any], Decimal]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "resource_key": self.resource_key,
            "new_resource_key": self.new_resource_key,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "old_unit_price": self.old_unit_price,
            "new_unit_price": self.new_unit_price,
            "currency": self.currency,
            "cost_items_count": self.cost_items_count,
            "cost_items_unreadable": self.cost_items_unreadable,
            "cost_items_delta_total": self.cost_items_delta_total,
            "cost_items": self.cost_items[:_SAMPLE],
            "assemblies_count": self.assemblies_count,
            "assemblies": self.assemblies[:_SAMPLE],
            "boq_positions_count": self.boq_positions_count,
            "boqs": self.boqs[:_SAMPLE],
            "issues": [{"code": i.code, "blocking": i.blocking, "detail": i.detail} for i in self.issues],
            "truncated": self.truncated,
            "applied": self.applied,
            "audit_id": self.audit_id,
        }


class ResourceImpactService:
    """Preview and apply a change to one resource of a region's price sheet."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def preview(
        self,
        region: str,
        resource_key: str,
        *,
        new_unit_price: Decimal | None = None,
        new_name: str | None = None,
        user_id: str | None = None,
        project_ids: set[uuid.UUID] | None = None,
        scope_projects: bool = False,
    ) -> ImpactResult:
        """Compute the effect of the change without writing anything."""
        row = (
            await self.session.execute(
                select(ResourcePrice).where(ResourcePrice.region == region, ResourcePrice.resource_key == resource_key)
            )
        ).scalar_one_or_none()
        if row is None:
            raise ResourceNotFoundError(resource_key)
        old_price = _to_decimal(row.unit_price)
        price = _q2(new_unit_price) if new_unit_price is not None else old_price
        name = " ".join(new_name.split()) if new_name is not None else row.resource_name
        new_key = resource_key if not resource_key.startswith("name:") else resource_key_for(None, name)
        res = ImpactResult(
            region=region,
            resource_key=resource_key,
            new_resource_key=new_key,
            old_name=row.resource_name,
            new_name=name,
            old_unit_price=old_price,
            new_unit_price=price,
            currency=row.currency or "",
        )
        rename = name if name != row.resource_name else None
        await self._scan_cost_items(res, rename)
        await self._scan_assemblies(res)
        await self._scan_positions(res, user_id, project_ids if scope_projects else _UNSET)
        existing = set(
            (
                await self.session.execute(
                    select(ResourcePrice.resource_key).where(
                        ResourcePrice.region == region, ResourcePrice.resource_key != resource_key
                    )
                )
            )
            .scalars()
            .all()
        )
        res.issues = check_resource_change(
            old_name=row.resource_name,
            new_name=name,
            old_price=old_price,
            new_price=price,
            old_key=resource_key,
            new_key=new_key,
            existing_keys=existing,
            unreadable_items=res.cost_items_unreadable,
        )
        return res

    async def apply(
        self,
        region: str,
        resource_key: str,
        *,
        new_unit_price: Decimal | None = None,
        new_name: str | None = None,
        expected_cost_items: int | None = None,
        user_id: str | None = None,
        project_ids: set[uuid.UUID] | None = None,
        scope_projects: bool = False,
    ) -> ImpactResult:
        """Write the previewed change in one transaction and audit it."""
        res = await self.preview(
            region,
            resource_key,
            new_unit_price=new_unit_price,
            new_name=new_name,
            user_id=user_id,
            project_ids=project_ids,
            scope_projects=scope_projects,
        )
        blocking = [i for i in res.issues if i.blocking]
        if blocking:
            raise ResourceChangeRefusedError("blocking findings", blocking)
        if expected_cost_items is not None and expected_cost_items != res.cost_items_count:
            raise ResourceChangeRefusedError(
                f"the region changed since the preview: {res.cost_items_count} work items use the resource now, "
                f"the preview showed {expected_cost_items}"
            )
        rename = res.new_name if res.new_name != res.old_name else None
        ids = list(res._writes)
        for start in range(0, len(ids), 1000):
            chunk = ids[start : start + 1000]
            items = (
                (
                    await self.session.execute(
                        select(CostItem)
                        .options(load_only(CostItem.rate, CostItem.components, CostItem.metadata_))
                        .where(CostItem.id.in_(chunk))
                    )
                )
                .scalars()
                .all()
            )
            for item in items:
                comps, _delta, _m, unreadable = rewrite_components(
                    item.components or [], resource_key, res.new_unit_price, rename
                )
                if unreadable:
                    continue
                new_rate = res._writes[item.id][1]
                item.components = comps
                item.rate = str(new_rate)
                by_type, total = _by_type(comps)
                if total == new_rate:
                    item.metadata_ = _breakdown_metadata(item.metadata_, by_type, total)
            await self.session.flush()
        row = (
            await self.session.execute(
                select(ResourcePrice).where(ResourcePrice.region == region, ResourcePrice.resource_key == resource_key)
            )
        ).scalar_one()
        row.unit_price = str(res.new_unit_price)
        row.resource_name = res.new_name[:300]
        row.resource_key = res.new_resource_key
        row.source = "user"
        try:
            row.updated_by = uuid.UUID(str(user_id)) if user_id else None
        except ValueError:
            row.updated_by = None
        entry = await audit_log(
            self.session,
            action="update",
            entity_type="resource_price",
            entity_id=str(row.id),
            user_id=str(row.updated_by) if row.updated_by else None,
            details={
                "kind": "resource_change",
                "region": region,
                "resource_key": resource_key,
                "new_resource_key": res.new_resource_key,
                "old_name": res.old_name,
                "new_name": res.new_name,
                "old_unit_price": str(res.old_unit_price),
                "new_unit_price": str(res.new_unit_price),
                "cost_items": res.cost_items_count,
                "cost_items_delta_total": str(res.cost_items_delta_total),
                "assemblies": res.assemblies_count,
                "boq_positions_untouched": res.boq_positions_count,
            },
        )
        await self.session.commit()
        res.applied = True
        res.audit_id = entry.id
        if res.cost_items_count:
            await _safe_publish(
                "costs.region.repriced",
                {"region": region, "items_changed": res.cost_items_count},
                source_module="oe_costs",
            )
        return res

    async def _scan_cost_items(self, res: ImpactResult, rename: str | None) -> None:
        stmt = (
            select(CostItem)
            .options(load_only(CostItem.code, CostItem.description, CostItem.unit, CostItem.rate, CostItem.components))
            .where(CostItem.region == res.region, CostItem.is_active.is_(True))
            .order_by(CostItem.id)
        )
        code_key = not res.resource_key.startswith("name:")
        if code_key and res.resource_key.isascii():
            # Narrows the walk for coded resources; the exact match runs below.
            stmt = stmt.where(cast(CostItem.components, String).contains(res.resource_key))
        offset = 0
        while offset < _MAX_ITEMS:
            page = (await self.session.execute(stmt.offset(offset).limit(_SCAN_ROWS))).scalars().all()
            if not page:
                break
            for item in page:
                comps, delta, matched, unreadable = rewrite_components(
                    item.components or [], res.resource_key, res.new_unit_price, rename
                )
                if not matched:
                    continue
                if unreadable:
                    res.cost_items_unreadable += 1
                    continue
                old_rate = _to_decimal(item.rate)
                new_rate = _q2(old_rate + delta)
                res.cost_items_count += 1
                res.cost_items_delta_total += delta
                res._writes[item.id] = (comps, new_rate)
                res.cost_items.append(
                    {
                        "id": item.id,
                        "code": item.code,
                        "description": (item.description or "")[:300],
                        "unit": item.unit,
                        "lines": matched,
                        "old_rate": old_rate,
                        "new_rate": new_rate,
                        "delta": delta,
                    }
                )
            for item in page:
                self.session.expunge(item)
            offset += len(page)
            if len(page) < _SCAN_ROWS:
                break
        else:
            res.truncated = True
        res.cost_items.sort(key=lambda r: abs(r["delta"]), reverse=True)

    async def _scan_assemblies(self, res: ImpactResult) -> None:
        if not res._writes:
            return
        from app.modules.assemblies.models import Assembly, Component

        deltas = {item["id"]: item["delta"] for item in res.cost_items}
        by_asm: dict[uuid.UUID, list[Decimal]] = {}
        ids = list(res._writes)
        for start in range(0, len(ids), 1000):
            rows = (
                await self.session.execute(
                    select(Component.assembly_id, Component.cost_item_id, Component.factor).where(
                        Component.cost_item_id.in_(ids[start : start + 1000])
                    )
                )
            ).all()
            for asm_id, item_id, factor in rows:
                by_asm.setdefault(asm_id, []).append(_to_decimal(factor, Decimal("1")) * deltas.get(item_id, 0))
        if not by_asm:
            return
        meta = {
            a.id: a
            for a in (
                await self.session.execute(
                    select(Assembly).options(load_only(Assembly.code, Assembly.name)).where(Assembly.id.in_(by_asm))
                )
            )
            .scalars()
            .all()
        }
        res.assemblies_count = len(by_asm)
        for asm_id, parts in by_asm.items():
            asm = meta.get(asm_id)
            res.assemblies.append(
                {
                    "id": asm_id,
                    "code": asm.code if asm else "",
                    "name": asm.name if asm else "",
                    "components": len(parts),
                    "delta": _q2(sum(parts, Decimal("0"))),
                }
            )
        res.assemblies.sort(key=lambda r: abs(r["delta"]), reverse=True)

    async def _scan_positions(self, res: ImpactResult, user_id: str | None, scope: Any = None) -> None:
        from app.dependencies import accessible_project_ids
        from app.modules.boq.models import BOQ, Position
        from app.modules.boq.price_alignment import position_row_delta

        if scope is _UNSET:
            project_ids = await accessible_project_ids(self.session, user_id, live_only=True)
        else:
            project_ids = scope
        if project_ids is not None and not project_ids:
            return
        stmt = (
            select(Position.id, Position.quantity, Position.metadata_, BOQ.id, BOQ.name, BOQ.project_id)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(cast(Position.metadata_, String).contains("resources"))
            .limit(_MAX_POSITIONS + 1)
        )
        if project_ids is not None:
            stmt = stmt.where(BOQ.project_id.in_(project_ids))
        rows = (await self.session.execute(stmt)).all()
        if len(rows) > _MAX_POSITIONS:
            res.truncated = True
            rows = rows[:_MAX_POSITIONS]
        by_boq: dict[uuid.UUID, dict[str, Any]] = {}
        for _pid, qty, meta, boq_id, boq_name, project_id in rows:
            resources = (meta or {}).get("resources") if isinstance(meta, dict) else None
            if not isinstance(resources, list):
                continue
            hit = False
            delta = Decimal("0")
            for r in resources:
                if isinstance(r, dict) and resource_key_for(r.get("code"), r.get("name")) == res.resource_key:
                    hit = True
                    delta += position_row_delta(r, meta, qty, res.new_unit_price)
            if not hit:
                continue
            res.boq_positions_count += 1
            entry = by_boq.setdefault(
                boq_id,
                {"boq_id": boq_id, "boq_name": boq_name, "project_id": project_id, "positions": 0, "delta_total": 0},
            )
            entry["positions"] += 1
            entry["delta_total"] = _q2(Decimal(entry["delta_total"]) + delta)
        res.boqs = sorted(by_boq.values(), key=lambda r: r["positions"], reverse=True)
