"""Draft change orders from accepted revisions (R9), through the ERP's own change-order service.

The cost delta is the revision impact (ddc-impact/1) taken before the accept moves the positions; the changed
elements come from the BIM hub's model diff. Nothing is approved here: a person approves in the register.
"""

from __future__ import annotations

import json
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from .models import DesignChangeOrder, DesignEstimate, DesignProjectOption, DesignRevision

MODES = ("off", "ask", "always")
DEFAULT_MODE = "ask"
MAX_KEYS = 1000
CREATE_PERMISSION = "changeorders.create"


def acceptance_url(revision_id: uuid.UUID | str) -> str:
    return f"/design/acceptance?revision={revision_id}"


def register_url(order_id: uuid.UUID | str) -> str:
    return f"/changeorders?highlight={order_id}"


async def mode(session, project_id: uuid.UUID) -> str:
    row = (
        await session.execute(select(DesignProjectOption).where(DesignProjectOption.project_id == project_id))
    ).scalar_one_or_none()
    return row.change_orders if row is not None and row.change_orders in MODES else DEFAULT_MODE


async def set_mode(session, project_id: uuid.UUID, value: str, user_id: uuid.UUID) -> None:
    row = (
        await session.execute(select(DesignProjectOption).where(DesignProjectOption.project_id == project_id))
    ).scalar_one_or_none()
    if row is None:
        session.add(DesignProjectOption(project_id=project_id, change_orders=value, updated_by=user_id))
    else:
        row.change_orders, row.updated_by = value, user_id
    await session.flush()


async def can_create(session, user_id: uuid.UUID) -> bool:
    from app.core.permissions import permission_registry
    from app.modules.users.models import User

    user = await session.get(User, user_id)
    return user is not None and permission_registry.role_has_permission(getattr(user, "role", ""), CREATE_PERMISSION)


async def require_create(session, user_id: uuid.UUID) -> None:
    if not await can_create(session, user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role may not create change orders")


def wanted(current_mode: str, asked: bool | None) -> bool:
    return current_mode == "always" or (current_mode == "ask" and asked is True)


# ── snapshot (before the accept moves anything) ─────────────────────────────


async def _elements(session, rev: DesignRevision) -> dict[str, Any] | None:
    from app.modules.bim_hub.service import BIMHubService

    parent = await session.get(DesignRevision, rev.parent_id) if rev.parent_id else None
    if rev.bim_model_id is None:
        return None
    if parent is None or parent.bim_model_id is None:
        return {"first_revision": True, "bim_model_id": str(rev.bim_model_id)}
    diff = await BIMHubService(session).compute_diff(new_model_id=rev.bim_model_id, old_model_id=parent.bim_model_id)
    details = diff.diff_details or {}

    def keys(name: str) -> list[str]:
        return sorted(str(d["stable_id"]) for d in details.get(name, []))

    added, removed, changed = keys("added"), keys("deleted"), keys("modified")
    return {
        "bim_model_id": str(rev.bim_model_id),
        "parent_bim_model_id": str(parent.bim_model_id),
        "bim_diff_id": str(diff.id),
        "added": added[:MAX_KEYS],
        "removed": removed[:MAX_KEYS],
        "changed": changed[:MAX_KEYS],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "truncated": max(len(added), len(removed), len(changed)) > MAX_KEYS,
    }


async def snapshot(session, rev: DesignRevision) -> dict[str, Any]:
    from .estimate import impact
    from .procurement import impact as procurement_impact
    from .schedule import impact as schedule_impact

    return {
        "impact": await impact(session, rev),
        "elements": await _elements(session, rev),
        "schedule": await schedule_impact(session, rev),
        "procurement": await procurement_impact(session, rev),
    }


async def store(session, rev: DesignRevision, snap: dict[str, Any], user_id: uuid.UUID) -> DesignChangeOrder:
    row = DesignChangeOrder(project_id=rev.project_id, revision_id=rev.id, snapshot=snap, created_by=user_id)
    session.add(row)
    await session.flush()
    return row


# ── the change order ────────────────────────────────────────────────────────


def _moving(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if Decimal(r["quantity_delta"]) != 0]


def _change_type(r: dict[str, Any]) -> str:
    if r["new_position"]:
        return "added"
    if Decimal(r["new_quantity"]) == 0:
        return "removed"
    return "modified"


def _unpriced(r: dict[str, Any]) -> bool:
    return Decimal(r["unit_rate"]) == 0


def co_token(key: str, **params: Any) -> str:
    """Neutral token for a generated sentence; the UI renders it in the reader's language (``designRecordText``)."""
    return f"[co:{key}|{json.dumps(params, sort_keys=True, ensure_ascii=False)}]" if params else f"[co:{key}]"


def _description(rev: DesignRevision, snap: dict[str, Any], unpriced: int) -> str:
    lines: list[str] = []
    els = snap.get("elements") or {}
    if "added_count" in els:
        lines.append(
            co_token("elements", added=els["added_count"], removed=els["removed_count"], changed=els["changed_count"])
        )
    if not (snap.get("impact") or {}).get("estimate"):
        lines.append(co_token("no_estimate"))
    if unpriced:
        lines.append(co_token("unpriced", count=unpriced))
    sch = snap.get("schedule") or {}
    if sch.get("schedule"):
        tot = sch["totals"]
        lines.append(
            co_token(
                "schedule", **{"from": tot["current_finish"], "to": tot["after_finish"], "days": tot["delta_days"]}
            )
        )
        if not sch.get("complete"):
            lines.append(co_token("schedule_rates", count=len(sch["rate_missing"])))
    prc = (snap.get("procurement") or {}).get("totals")
    if prc:
        lines.append(
            co_token(
                "procurement",
                changed=prc["lines_changed"],
                added=prc["lines_added"],
                removed=prc["lines_removed"],
                packages=prc["packages_affected"],
                issued=prc["issued_packages_affected"],
            )
        )
    return "\n".join(lines)[:5000]


async def _mark_in_estimate(
    session, project_id: uuid.UUID, order_id: uuid.UUID, code: str, rev: DesignRevision
) -> None:
    """Tell the register's bill writeback that this scope is already in the design estimate.

    The accept moved the design positions; approving the order would otherwise add its items to that bill again.
    The change-order service skips a bill holding a section whose metadata names the order.
    """
    from app.modules.boq.models import Position

    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    if est is None:
        return
    last = (
        await session.execute(
            select(Position.sort_order)
            .where(Position.boq_id == est.boq_id)
            .order_by(Position.sort_order.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    session.add(
        Position(
            boq_id=est.boq_id,
            parent_id=None,
            ordinal=f"CO-{code}",
            description=f"{code}: already in this estimate through design revision R{rev.number}",
            unit="section",
            quantity="0",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            confidence=None,
            cad_element_ids=[],
            sort_order=(last or 0) + 1,
            metadata_={
                "change_order_id": str(order_id),
                "change_order_code": code,
                "origin": "design_revision",
                "design_revision_id": str(rev.id),
            },
        )
    )
    await session.flush()


async def create(session, rev: DesignRevision, row: DesignChangeOrder, user_id: uuid.UUID):
    """Create the draft order from the stored snapshot and link it to ``row``. Flushes, does not commit."""
    from app.modules.changeorders.schemas import ChangeOrderCreate, ChangeOrderItemCreate
    from app.modules.changeorders.service import ChangeOrderService

    from .procurement import for_change_order as procurement_for_co
    from .schedule import for_change_order

    snap = row.snapshot
    imp = snap["impact"]
    rows = _moving(imp.get("rows") or [])
    unpriced = [r for r in rows if _unpriced(r)]
    totals = imp.get("totals") or {}
    meta = {
        "source": "design_revision",
        "design_revision_id": str(rev.id),
        "design": {
            "revision_id": str(rev.id),
            "revision_number": rev.number,
            "parent_revision_id": str(rev.parent_id) if rev.parent_id else None,
            "acceptance_url": acceptance_url(rev.id),
            "elements": snap.get("elements"),
            "estimate": {
                "present": bool(imp.get("estimate")),
                "totals": totals or None,
                "unpriced_positions": [r["rule"] for r in unpriced],
                "overrides_kept": [r["rule"] for r in imp.get("rows") or [] if r.get("override")],
            },
            "schedule": for_change_order(snap.get("schedule")),
            "procurement": procurement_for_co(snap.get("procurement")),
        },
    }
    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == rev.project_id))
    ).scalar_one_or_none()
    title = f"design_revision:{rev.number}" + (f":{rev.message}" if rev.message else "")
    svc = ChangeOrderService(session)
    order = await svc.create_order(
        ChangeOrderCreate(
            project_id=rev.project_id,
            title=title[:255],
            description=_description(rev, snap, len(unpriced)),
            reason_category="design_change",
            metadata=meta,
            schedule_impact_days=max((meta["design"]["schedule"] or {}).get("delta_days", 0), 0),
        )
    )
    order_id, code = order.id, order.code
    for i, r in enumerate(rows):
        label = f"{r['ordinal'] or r['cost_group']} {r['label']}"
        if _unpriced(r):
            label += " " + co_token("item_unpriced")
        item_meta = {
            "design_rule": r["rule"],
            "cost_group": r["cost_group"],
            "flags": r["flags"],
            "unpriced": _unpriced(r),
            "impact_cost_delta": r["cost_delta"],
            "elements": r["elements"],
        }
        if est is not None and r["position_id"]:
            item_meta.update(
                boq_id=str(est.boq_id), boq_position_id=r["position_id"], boq_position_ordinal=r["ordinal"]
            )
        await svc.add_item(
            order_id,
            ChangeOrderItemCreate(
                description=label[:5000],
                change_type=_change_type(r),
                original_quantity=r["current_quantity"],
                new_quantity=r["new_quantity"],
                original_rate=r["unit_rate"],
                new_rate=r["unit_rate"],
                unit=(r["unit"] or "")[:20],
                sort_order=i,
                metadata=item_meta,
            ),
            actor_id=str(user_id),
        )
    if rows:
        await _mark_in_estimate(session, rev.project_id, order_id, code, rev)
    row.change_order_id = order_id
    await session.flush()
    return order_id


def cost_history(snap: dict[str, Any]) -> dict[str, Any] | None:
    """Estimate total before and after the accept, read from the snapshot taken before positions moved."""
    imp = (snap or {}).get("impact") or {}
    t = imp.get("totals")
    if not t:
        return None

    def money(v: Any) -> str:
        return format(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")

    return {
        "before": money(t["current"]),
        "after": money(t["after"]),
        "delta": money(t["delta"]),
        "unpriced_positions": t.get("unpriced_positions", 0),
        "currency": imp.get("currency"),
    }


async def view(session, rev: DesignRevision) -> dict[str, Any]:
    from app.modules.changeorders.models import ChangeOrder

    current = await mode(session, rev.project_id)
    row = (
        await session.execute(select(DesignChangeOrder).where(DesignChangeOrder.revision_id == rev.id))
    ).scalar_one_or_none()
    out: dict[str, Any] = {
        "revision_id": str(rev.id),
        "number": rev.number,
        "revision_status": rev.status,
        "mode": current,
        "state": "none",
        "change_order": None,
        "snapshot": row is not None,
    }
    if row is None:
        return out
    out["cost"] = cost_history(row.snapshot)
    if row.change_order_id is None and (row.snapshot or {}).get("change_orders_off"):
        out["snapshot"] = False  # accepted while change orders were off: history only, no order from it
        return out
    if row.change_order_id is None:
        out["state"] = "declined"
        return out
    order = await session.get(ChangeOrder, row.change_order_id)
    if order is None:
        out["state"] = "deleted"
        return out
    unpriced = ((order.metadata_ or {}).get("design") or {}).get("estimate", {}).get("unpriced_positions") or []
    out["state"] = "created"
    out["change_order"] = {
        "id": str(order.id),
        "code": order.code,
        "title": order.title,
        "status": order.status,
        "cost_impact": format(Decimal(str(order.cost_impact or 0)), "f"),
        "currency": order.currency or None,
        "unpriced_positions": len(unpriced),
        "url": register_url(order.id),
    }
    return out


async def create_later(session, rev: DesignRevision, user_id: uuid.UUID) -> None:
    """Create the order of an accepted revision from its snapshot; the same order when one exists."""
    from app.modules.changeorders.models import ChangeOrder

    if rev.status not in ("published", "archived"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only an accepted revision gets a change order")
    row = (
        await session.execute(
            select(DesignChangeOrder).where(DesignChangeOrder.revision_id == rev.id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or (row.change_order_id is None and (row.snapshot or {}).get("change_orders_off")):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This revision was accepted while change orders were off: there is no cost snapshot",
        )
    if row.change_order_id is not None and await session.get(ChangeOrder, row.change_order_id) is not None:
        return
    await require_create(session, user_id)
    await create(session, rev, row, user_id)
