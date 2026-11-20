"""Element <-> BOQ position <-> schedule activity <-> tender package, both ways.

The design keeps which elements feed which position (estimate rules, R6; take-off groups, R11) and which activity
(R10). ``sync`` writes that into the ERP's own link fields, so the ERP's screens show it without knowing the module:
position ``cad_element_ids``/``cad_model_id`` (BOQ row <-> viewer highlight), ``oe_bim_boq_link`` rows with
``link_type='design'`` (viewer: element -> positions; BIM coverage), activity ``bim_element_ids`` (4D).
Only rows the design owns are touched; links a person drew by hand stay. ``lookup`` answers the other way round
for the workspace: for these elements, which positions, activities and packages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, update

from .models import DesignEstimate, DesignEstimateBinding, DesignRevision, DesignSchedule, DesignScheduleBinding
from .procurement_models import DesignProcurement, DesignTakeoffLine, DesignTakeoffSection

LINK_TYPE = "design"
# A deep link into the viewer carries element ids in the URL; past this many it opens the model unfiltered.
ISOLATE_MAX = 400


@dataclass
class Node:
    keys: list[str]
    model_id: uuid.UUID | None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Graph:
    positions: dict[uuid.UUID, Node] = field(default_factory=dict)
    activities: dict[uuid.UUID, Node] = field(default_factory=dict)
    packages: dict[uuid.UUID, Node] = field(default_factory=dict)
    # model id -> element key -> BIMElement id
    ids: dict[uuid.UUID, dict[str, uuid.UUID]] = field(default_factory=dict)


async def _model_of(session, revision_id: uuid.UUID | None) -> uuid.UUID | None:
    if revision_id is None:
        return None
    rev = await session.get(DesignRevision, revision_id)
    return rev.bim_model_id if rev is not None else None


async def _elements(session, model_id: uuid.UUID) -> list[tuple[str, uuid.UUID, str]]:
    from app.modules.bim_hub.models import BIMElement

    rows = await session.execute(
        select(BIMElement.stable_id, BIMElement.id, BIMElement.storey).where(BIMElement.model_id == model_id)
    )
    return [(k, i, s or "") for k, i, s in rows]


async def build(session, project_id: uuid.UUID) -> Graph:
    """What the design links today, from its own binding tables (no ERP rows are read but elements)."""
    from . import estimate as est_mod
    from . import procurement as prc

    g = Graph()
    storeys: dict[uuid.UUID, dict[str, str]] = {}

    async def index(model_id: uuid.UUID | None) -> None:
        if model_id is None or model_id in g.ids:
            return
        rows = await _elements(session, model_id)
        g.ids[model_id] = {k: i for k, i, _ in rows}
        storeys[model_id] = {k: s for k, _, s in rows}

    est = (
        await session.execute(select(DesignEstimate).where(DesignEstimate.project_id == project_id))
    ).scalar_one_or_none()
    by_rule: dict[str, tuple[uuid.UUID, list[str]]] = {}
    if est is not None:
        model = await _model_of(session, est.revision_id)
        await index(model)
        bindings = (
            (await session.execute(select(DesignEstimateBinding).where(DesignEstimateBinding.project_id == project_id)))
            .scalars()
            .all()
        )
        for b in bindings:
            keys = [k for k in (b.element_keys or []) if isinstance(k, str)]
            by_rule[b.rule_code] = (b.position_id, keys)
            g.positions[b.position_id] = Node(
                keys, model, {"source": "estimate", "boq_id": b.boq_id, "rule": b.rule_code}
            )

    sched = (
        await session.execute(select(DesignSchedule).where(DesignSchedule.project_id == project_id))
    ).scalar_one_or_none()
    if sched is not None:
        model = await _model_of(session, sched.revision_id or (est.revision_id if est else None))
        await index(model)
        of = storeys.get(model, {}) if model else {}
        for b in (
            (await session.execute(select(DesignScheduleBinding).where(DesignScheduleBinding.project_id == project_id)))
            .scalars()
            .all()
        ):
            pid, keys = by_rule.get(b.rule_code, (None, []))
            if b.storey:
                keys = [k for k in keys if of.get(k) == b.storey]
            g.activities[b.activity_id] = Node(
                keys,
                model,
                {
                    "schedule_id": sched.schedule_id,
                    "rule": b.rule_code,
                    "storey": b.storey,
                    "positions": [pid] if pid else [],
                },
            )

    proc = (
        await session.execute(select(DesignProcurement).where(DesignProcurement.project_id == project_id))
    ).scalar_one_or_none()
    if proc is not None:
        model = await _model_of(session, proc.revision_id)
        groups = prc.group_elements(await est_mod.load_elements(session, model), proc.group_by) if model else {}
        await index(model)
        per_class: dict[str, list[str]] = {}
        for ln in (
            (await session.execute(select(DesignTakeoffLine).where(DesignTakeoffLine.project_id == project_id)))
            .scalars()
            .all()
        ):
            keys = list(groups[ln.group_key].elements) if ln.group_key in groups else []
            per_class.setdefault(ln.ifc_class, []).extend(keys)
            g.positions[ln.position_id] = Node(
                keys,
                model,
                {"source": "takeoff", "boq_id": proc.boq_id, "group": ln.group_key, "ifc_class": ln.ifc_class},
            )
        for sec in (
            (await session.execute(select(DesignTakeoffSection).where(DesignTakeoffSection.project_id == project_id)))
            .scalars()
            .all()
        ):
            if sec.package_id is not None:
                g.packages[sec.package_id] = Node(
                    per_class.get(sec.ifc_class, []),
                    model,
                    {"ifc_class": sec.ifc_class, "section_position_id": sec.position_id},
                )
    return g


def _uuids(g: Graph, node: Node) -> list[uuid.UUID]:
    table = g.ids.get(node.model_id, {}) if node.model_id else {}
    return [table[k] for k in node.keys if k in table]


async def sync(session, project_id: uuid.UUID) -> dict[str, int]:
    """Write the design's links into the ERP link fields. Flushes; the caller commits. Idempotent."""
    from app.modules.bim_hub.models import BOQElementLink
    from app.modules.boq.models import Position
    from app.modules.schedule.models import Activity

    g = await build(session, project_id)
    positions = list(g.positions)
    if positions:
        await session.execute(
            delete(BOQElementLink).where(
                BOQElementLink.boq_position_id.in_(positions), BOQElementLink.link_type == LINK_TYPE
            )
        )
    links = 0
    existing = (
        {p.id for p in (await session.execute(select(Position.id).where(Position.id.in_(positions)))).all()}
        if positions
        else set()
    )
    for pid, node in g.positions.items():
        if pid not in existing:  # a person deleted the position in the BOQ: nothing to link
            continue
        await session.execute(
            update(Position)
            .where(Position.id == pid)
            .values(cad_element_ids=list(node.keys), cad_model_id=str(node.model_id) if node.model_id else None)
        )
        rule = node.extra.get("rule") or node.extra.get("group")
        for eid in dict.fromkeys(_uuids(g, node)):
            session.add(
                BOQElementLink(
                    boq_position_id=pid,
                    bim_element_id=eid,
                    link_type=LINK_TYPE,
                    rule_id=str(rule)[:100] if rule else None,
                    metadata_={"source": node.extra["source"]},
                )
            )
            links += 1
    acts = 0
    for aid, node in g.activities.items():
        done = await session.execute(
            update(Activity).where(Activity.id == aid).values(bim_element_ids=[str(i) for i in _uuids(g, node)])
        )
        acts += done.rowcount or 0
    await session.flush()
    return {"positions": len(existing), "element_links": links, "activities": acts}


async def lookup(session, project_id: uuid.UUID, keys: list[str]) -> dict[str, Any]:
    """For each element key: the positions, activities and packages it feeds, with what an ERP screen needs to open them."""
    from app.modules.boq.models import Position
    from app.modules.schedule.models import Activity
    from app.modules.tendering.models import TenderPackage

    g = await build(session, project_id)
    want = set(keys)
    hit_p = {pid: n for pid, n in g.positions.items() if want & set(n.keys)}
    hit_a = {aid: n for aid, n in g.activities.items() if want & set(n.keys)}
    hit_k = {kid: n for kid, n in g.packages.items() if want & set(n.keys)}
    pos_rows = (
        {p.id: p for p in (await session.execute(select(Position).where(Position.id.in_(list(hit_p))))).scalars()}
        if hit_p
        else {}
    )
    act_rows = (
        {a.id: a for a in (await session.execute(select(Activity).where(Activity.id.in_(list(hit_a))))).scalars()}
        if hit_a
        else {}
    )
    pkg_rows = (
        {
            p.id: p
            for p in (await session.execute(select(TenderPackage).where(TenderPackage.id.in_(list(hit_k))))).scalars()
        }
        if hit_k
        else {}
    )

    def matched(n: Node) -> list[str]:
        return [k for k in n.keys if k in want]

    positions = [
        {
            "position_id": str(pid),
            "boq_id": str(n.extra["boq_id"]),
            "source": n.extra["source"],
            "ordinal": pos_rows[pid].ordinal,
            "description": pos_rows[pid].description,
            "quantity": str(pos_rows[pid].quantity) if pos_rows[pid].quantity is not None else None,
            "unit": pos_rows[pid].unit,
            "elements": matched(n),
        }
        for pid, n in hit_p.items()
        if pid in pos_rows
    ]
    positions.sort(key=lambda r: (r["source"], r["ordinal"]))
    activities = [
        {
            "activity_id": str(aid),
            "schedule_id": str(n.extra["schedule_id"]),
            "name": act_rows[aid].name,
            "start_date": act_rows[aid].start_date,
            "end_date": act_rows[aid].end_date,
            "storey": n.extra["storey"],
            "elements": matched(n),
        }
        for aid, n in hit_a.items()
        if aid in act_rows
    ]
    activities.sort(key=lambda r: (r["start_date"] or "", r["name"]))
    packages = [
        {
            "package_id": str(kid),
            "name": pkg_rows[kid].name,
            "status": pkg_rows[kid].status,
            "ifc_class": n.extra["ifc_class"],
            "elements": matched(n),
        }
        for kid, n in hit_k.items()
        if kid in pkg_rows
    ]
    packages.sort(key=lambda r: r["name"])
    return {"keys": sorted(want), "positions": positions, "activities": activities, "packages": packages}


async def position_elements(session, project_id: uuid.UUID, position_id: uuid.UUID) -> dict[str, Any] | None:
    """The elements behind one design-owned position (estimate or take-off), for 'show in model'."""
    g = await build(session, project_id)
    node = g.positions.get(position_id)
    if node is None:
        return None
    ids = [str(i) for i in _uuids(g, node)]
    return {
        "position_id": str(position_id),
        "boq_id": str(node.extra["boq_id"]),
        "model_id": str(node.model_id) if node.model_id else None,
        "keys": node.keys,
        "element_ids": ids,
        "isolate": ids if 0 < len(ids) <= ISOLATE_MAX else None,
    }
