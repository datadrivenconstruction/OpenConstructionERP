"""Material take-off from model revisions into the ERP's tendering module (R11).

The take-off is one BOQ ("Design take-off"): a section per IFC class, a position per element group (type key or IFC
class, fixed at setup). The quantity of a position is the sum of one quantity key over the group's elements; which key
comes from ``data/procurement/basis.json`` (a unit convention) unless a person chose another. Every IFC-class section
is raised as a tender package with the ERP's own ``TenderingService``; bids, levelling and award stay there.

A quantity a person changed is an override: kept, flagged, the model value stored beside it (as in the estimate). A
group that leaves the model drops to zero and is flagged ``no_match``; positions and packages are never deleted. A
package that has left draft keeps its quantities in step too, and each change is recorded on the package. For such a
package an accepted revision also prepares a tender addendum DRAFT in the ERP's own addenda (changed positions with
quantities before and after, the linked elements, the revision's sheets); a person reviews and sends it in the
tendering module. This module never publishes or sends one.

Nothing is priced and no lead time is assumed: unit rates stay 0 and every line says ``unpriced`` and
``lead_time_missing`` until a person enters them.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from . import estimate as est_mod
from .models import DesignProcurement, DesignRevision, DesignTakeoffLine, DesignTakeoffSection

IMPACT_SCHEMA = "ddc-procurement-impact/1"
DATA = Path(__file__).resolve().parent / "data" / "procurement"
BASES = ("length_m", "area_m2", "volume_m3", "weight_kg", "count")
UNITS = {"length_m": "m", "area_m2": "m2", "volume_m3": "m3", "weight_kg": "kg", "count": "pcs"}
GROUP_BY = ("type_key", "ifc_class")
ZERO = Decimal(0)
TENDER_URL = "/tendering"
ISSUED = ("issued", "collecting", "evaluating", "awarded", "closed")
MAX_CHANGES = 200  # per package, newest kept
MAX_ADDENDUM_KEYS = 200  # linked element keys kept per addendum line
BASIS_NOTE = (
    "The unit of each line (area, volume, length, weight, count) is a convention by IFC class, not data; "
    "the other available bases are listed and a person may switch."
)
PRICE_NOTE = "No prices and no lead times are assumed: both stay empty (flagged) until a person enters a sourced value."


@lru_cache(maxsize=1)
def basis_table() -> dict[str, Any]:
    doc = json.loads((DATA / "basis.json").read_text(encoding="utf-8"))
    for k in [doc["default"], *doc["by_ifc_class"].values()]:
        if k not in BASES:
            raise ValueError(f"basis.json: unknown quantity key {k}")
    return doc


def default_basis(ifc_class: str) -> str:
    t = basis_table()
    return t["by_ifc_class"].get(ifc_class, t["default"])


# ── grouping ────────────────────────────────────────────────────────────────


@dataclass
class Group:
    key: str
    ifc_class: str
    label: str
    elements: list[str] = field(default_factory=list)
    sums: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(BASES, ZERO))
    present: dict[str, int] = field(default_factory=lambda: dict.fromkeys(BASES, 0))


def group_key(e, group_by: str) -> tuple[str, str]:
    """(key, label) of the group an element falls into."""
    cls = e.ifc_class or "IfcBuildingElementProxy"
    if group_by == "ifc_class":
        return cls, cls
    return (e.type_key, e.type_key) if e.type_key else (f"{cls}/_untyped", f"{cls} (no type)")


def group_elements(elements: list, group_by: str) -> dict[str, Group]:
    skip = set(basis_table()["not_procured"])
    out: dict[str, Group] = {}
    for e in elements:
        cls = e.ifc_class or "IfcBuildingElementProxy"
        if cls in skip:
            continue
        key, label = group_key(e, group_by)
        g = out.setdefault(key, Group(key, cls, label))
        g.elements.append(e.key)
        for b in BASES:
            v = e.quantities.get(b)
            if v is None or isinstance(v, bool):
                continue
            g.sums[b] += est_mod.q4(v)
            g.present[b] += 1
    return out


def measure(g: Group | None, basis: str) -> tuple[Decimal, list[str]]:
    """Quantity of a group in ``basis`` and what is wrong with it. Never fills a missing value."""
    if g is None or not g.elements:
        return ZERO, ["no_match"]
    if g.present[basis] == 0:
        return ZERO, ["no_quantity"]
    return est_mod.q4(g.sums[basis]), (["partial_quantity"] if g.present[basis] < len(g.elements) else [])


def _available(g: Group | None) -> dict[str, Any]:
    if g is None:
        return {}
    return {b: {"sum": est_mod.dstr(g.sums[b]), "elements": g.present[b]} for b in BASES if g.present[b]}


def _flags(base: list[str], *, override: bool, extra: list[str] | None = None) -> list[str]:
    return sorted({*base, *(extra or []), "unpriced", "lead_time_missing", *(["override"] if override else [])})


# ── context ─────────────────────────────────────────────────────────────────


async def _proc(session, project_id: uuid.UUID) -> DesignProcurement | None:
    return (
        await session.execute(select(DesignProcurement).where(DesignProcurement.project_id == project_id))
    ).scalar_one_or_none()


async def _lines(session, project_id: uuid.UUID) -> dict[str, DesignTakeoffLine]:
    rows = (
        await session.execute(select(DesignTakeoffLine).where(DesignTakeoffLine.project_id == project_id))
    ).scalars()
    return {r.group_key: r for r in rows}


async def _sections(session, project_id: uuid.UUID) -> dict[str, DesignTakeoffSection]:
    rows = (
        await session.execute(select(DesignTakeoffSection).where(DesignTakeoffSection.project_id == project_id))
    ).scalars()
    return {r.ifc_class: r for r in rows}


async def _package(session, package_id: uuid.UUID | None):
    if package_id is None:
        return None
    from app.modules.tendering.repository import TenderingRepository

    return await TenderingRepository(session).get_package_by_id(package_id)


# ── impact of a pending revision ────────────────────────────────────────────


async def impact(session, rev: DesignRevision) -> dict[str, Any]:
    """Take-off delta if ``rev`` were accepted now. Writes nothing."""
    out: dict[str, Any] = {"schema": IMPACT_SCHEMA, "revision_id": str(rev.id), "procurement": False}
    proc = await _proc(session, rev.project_id)
    if proc is None or rev.bim_model_id is None:
        return out
    svc = est_mod._svc(session)
    groups = group_elements(await est_mod.load_elements(session, rev.bim_model_id), proc.group_by)
    lines = await _lines(session, rev.project_id)
    sections = await _sections(session, rev.project_id)
    positions = {p.id: p for p in await svc.position_repo.list_by_ids([ln.position_id for ln in lines.values()])}
    packages = {cls: await _package(session, s.package_id) for cls, s in sections.items()}
    rows: list[dict[str, Any]] = []
    for key in sorted(set(groups) | set(lines)):
        g, ln = groups.get(key), lines.get(key)
        cls = ln.ifc_class if ln else g.ifc_class
        basis = ln.basis if ln else default_basis(cls)
        new_model, flags = measure(g, basis)
        pos = positions.get(ln.position_id) if ln else None
        cur = est_mod.q4(pos.quantity) if pos is not None else ZERO
        override = bool(ln and pos is not None and est_mod._overridden(pos, ln, new_model))
        eff = cur if (override or not proc.follow) else new_model
        pkg = packages.get(cls)
        rows.append(
            {
                "group_key": key,
                "label": ln.label if ln else g.label,
                "ifc_class": cls,
                "basis": basis,
                "unit": UNITS[basis],
                "new_line": ln is None,
                "current_quantity": str(cur),
                "model_quantity_now": ln.model_quantity if ln else None,
                "model_quantity_new": str(new_model),
                "new_quantity": str(eff),
                "quantity_delta": str(eff - cur),
                "override": override,
                "override_quantity": str(cur) if override else None,
                "elements": {"before": ln.element_count if ln else 0, "after": len(g.elements) if g else 0},
                "package": {"id": str(pkg.id), "name": pkg.name, "status": pkg.status} if pkg is not None else None,
                "new_package": cls not in sections,
                "flags": _flags(flags, override=override),
            }
        )
    rows.sort(key=lambda r: (not r["override"], Decimal(r["quantity_delta"]) == 0, r["ifc_class"], r["group_key"]))
    moving = [r for r in rows if Decimal(r["quantity_delta"]) != 0]
    touched = {r["ifc_class"] for r in moving}
    out.update(
        {
            "procurement": True,
            "follow": proc.follow,
            "group_by": proc.group_by,
            "rows": rows,
            "totals": {
                "lines_changed": sum(1 for r in moving if not r["new_line"] and Decimal(r["new_quantity"]) != 0),
                "lines_added": sum(1 for r in rows if r["new_line"]),
                "lines_removed": sum(1 for r in moving if Decimal(r["new_quantity"]) == 0 and not r["new_line"]),
                "overrides_kept": sum(1 for r in rows if r["override"]),
                "packages_affected": len(touched),
                "packages_new": len({r["ifc_class"] for r in rows if r["new_package"]}),
                "issued_packages_affected": sum(
                    1 for c in touched if packages.get(c) is not None and packages[c].status in ISSUED
                ),
                "unpriced_lines": len(rows),
            },
            "basis_note": BASIS_NOTE,
            "price_note": PRICE_NOTE,
        }
    )
    return out


# ── apply (accept, setup) ───────────────────────────────────────────────────


def _template_item(pos) -> dict[str, str]:
    return {
        "position_id": str(pos.id),
        "description": pos.description or "",
        "unit": pos.unit or "",
        "quantity": est_mod.dstr(pos.quantity),
        "unit_rate": est_mod.dstr(pos.unit_rate),
        "total": est_mod.dstr(pos.total),
    }


async def _ensure_section(session, proc: DesignProcurement, cls: str, sections: dict[str, DesignTakeoffSection]):
    from app.modules.boq.schemas import SectionCreate

    if cls in sections:
        return sections[cls]
    sec = await est_mod._svc(session).create_section(
        proc.boq_id,
        SectionCreate(
            ordinal=f"T{len(sections) + 1:02d}", description=cls, metadata={"design_takeoff": {"ifc_class": cls}}
        ),
    )
    row = DesignTakeoffSection(project_id=proc.project_id, ifc_class=cls, position_id=sec.id)
    session.add(row)
    await session.flush()
    sections[cls] = row
    return row


async def _ensure_line(
    session, proc: DesignProcurement, g: Group, sec: DesignTakeoffSection, sec_ordinal: str, n: int
) -> DesignTakeoffLine:
    from app.modules.boq.schemas import PositionCreate

    basis = default_basis(g.ifc_class)
    pos = await est_mod._svc(session).add_position(
        PositionCreate(
            boq_id=proc.boq_id,
            parent_id=sec.position_id,
            ordinal=f"{sec_ordinal}.{n:03d}",
            description=g.label,
            unit=UNITS[basis],
            quantity=0,
            unit_rate=ZERO,
            source="cad_import",
            metadata={"design_takeoff": {"group_key": g.key, "ifc_class": g.ifc_class}},
        )
    )
    ln = DesignTakeoffLine(
        project_id=proc.project_id,
        group_key=g.key,
        ifc_class=g.ifc_class,
        label=g.label,
        basis=basis,
        position_id=pos.id,
        available={},
        flags=[],
    )
    session.add(ln)
    await session.flush()
    return ln


async def recompute(
    session, project_id: uuid.UUID, rev_id: uuid.UUID, model_id: uuid.UUID, user_id: uuid.UUID, *, force: bool = False
) -> int:
    """Make the take-off follow the model of ``model_id``. Flushes. Returns the lines held."""
    proc = await _proc(session, project_id)
    if proc is None or (not proc.follow and not force):
        return 0
    svc = est_mod._svc(session)
    groups = group_elements(await est_mod.load_elements(session, model_id), proc.group_by)
    lines, sections = await _lines(session, project_id), await _sections(session, project_id)
    per_class: dict[str, int] = {}
    fresh: set[str] = set()  # lines this revision adds: an addendum adds them, it does not change them
    for ln in lines.values():
        per_class[ln.ifc_class] = per_class.get(ln.ifc_class, 0) + 1
    for key in sorted(groups, key=lambda k: (groups[k].ifc_class, k)):
        g = groups[key]
        sec = await _ensure_section(session, proc, g.ifc_class, sections)
        if key not in lines:
            per_class[g.ifc_class] = per_class.get(g.ifc_class, 0) + 1
            sec_pos = await svc.position_repo.get_by_id(sec.position_id)
            if sec_pos is None:  # a person deleted the section in the BOQ module: not recreated, no line
                per_class[g.ifc_class] -= 1
                continue
            lines[key] = await _ensure_line(session, proc, g, sec, sec_pos.ordinal, per_class[g.ifc_class])
            fresh.add(key)
    positions = {p.id: p for p in await svc.position_repo.list_by_ids([ln.position_id for ln in lines.values()])}
    packages = {cls: await _package(session, s.package_id) for cls, s in sections.items()}
    changes: dict[str, list[dict[str, Any]]] = {}
    for key, ln in lines.items():
        g, pos = groups.get(key), positions.get(ln.position_id)
        if pos is None:  # deleted in the BOQ module (or with its section): kept as a flagged row, not recreated
            ln.element_count, ln.available = (len(g.elements) if g else 0), _available(g)
            ln.flags = _flags([], override=False, extra=["position_deleted"])
            ln.revision_id = rev_id
            continue
        qty, base = measure(g, ln.basis)
        override = est_mod._overridden(pos, ln, qty)
        before = est_mod.q4(pos.quantity)
        elements_before = ln.element_count if key not in fresh else 0
        extra: list[str] = []
        if not override:
            await est_mod._write_quantity(svc, ln, pos, qty)
            pkg = packages.get(ln.ifc_class)
            if pkg is not None and pkg.status in ISSUED and before != qty:
                extra.append("changed_after_issue")
                changes.setdefault(ln.ifc_class, []).append(
                    {
                        "revision_id": str(rev_id),
                        "group_key": key,
                        "label": ln.label,
                        "unit": pos.unit,
                        "from": est_mod.dstr(before),
                        "to": est_mod.dstr(qty),
                        "package_status": pkg.status,
                        "op": "add" if key in fresh else "change",
                        "position_id": str(pos.id),
                        "ordinal": pos.ordinal or "",
                        "elements_before": elements_before,
                        "elements_after": len(g.elements) if g else 0,
                        "element_keys": sorted(g.elements)[:MAX_ADDENDUM_KEYS] if g else [],
                    }
                )
        ln.model_quantity, ln.revision_id = est_mod.dstr(qty), rev_id
        ln.element_count, ln.available = (len(g.elements) if g else 0), _available(g)
        ln.flags = _flags(base, override=override, extra=extra)
    proc.revision_id = rev_id
    await session.flush()
    await _sync_packages(session, proc, sections, lines, positions, rev_id, changes, user_id)
    return len(lines)


async def _sync_packages(
    session,
    proc: DesignProcurement,
    sections: dict[str, DesignTakeoffSection],
    lines: dict[str, DesignTakeoffLine],
    positions: dict,
    rev_id: uuid.UUID,
    changes: dict[str, list[dict[str, Any]]],
    user_id: uuid.UUID,
) -> None:
    from app.modules.tendering.schemas import CreatePackageFromBOQData, PackageUpdate
    from app.modules.tendering.service import TenderingService

    svc = TenderingService(session)
    for cls, sec in sorted(sections.items()):
        mine = [ln for ln in lines.values() if ln.ifc_class == cls and ln.position_id in positions]
        if not mine:
            continue
        if sec.package_id is None:
            created = await svc.create_package_from_boq(
                CreatePackageFromBOQData(
                    project_id=proc.project_id,
                    boq_id=proc.boq_id,
                    section_ids=[sec.position_id],
                    package_name=f"Design take-off: {cls}"[:255],
                    package_description="Quantities from accepted design revisions, by element type. "
                    "No prices and no lead times are assumed.",
                    metadata={"origin": "design_takeoff"},
                ),
                actor_id=str(user_id),
            )
            sec.package_id = created.id
            await session.flush()
        pkg = await _package(session, sec.package_id)
        if pkg is None:  # a person deleted it in the tendering register: not recreated
            continue
        old = (pkg.metadata_ or {}).get("design_takeoff") or {}
        history = [
            *(old.get("changes_after_issue") or []),
            *({k: v for k, v in c.items() if k != "element_keys"} for c in changes.get(cls, [])),
        ][-MAX_CHANGES:]
        ordered = sorted(mine, key=lambda x: x.group_key)
        template = [_template_item(positions[ln.position_id]) for ln in ordered]
        meta = {
            "line_item_template": template,
            "included_position_count": len(template) + 1,
            "source_section_ids": [str(sec.position_id)],
            "design_takeoff": {
                "ifc_class": cls,
                "revision_id": str(rev_id),
                "group_by": proc.group_by,
                "price": None,
                "lead_time_days": None,
                "flags": ["unpriced", "lead_time_missing"],
                "lines": [
                    {
                        "position_id": str(ln.position_id),
                        "group_key": ln.group_key,
                        "basis": ln.basis,
                        "model_quantity": ln.model_quantity,
                        "flags": ln.flags,
                    }
                    for ln in ordered
                ],
                "changes_after_issue": history,
                "addenda": old.get("addenda") or {},
            },
        }
        await svc.update_package(pkg.id, PackageUpdate(metadata=meta))
        if changes.get(cls) and pkg.status in ISSUED and str(rev_id) not in meta["design_takeoff"]["addenda"]:
            draft = await _addendum_draft(session, svc, proc, pkg, rev_id, changes[cls])
            meta["design_takeoff"]["addenda"] = {**meta["design_takeoff"]["addenda"], str(rev_id): draft}
            await svc.update_package(pkg.id, PackageUpdate(metadata={"design_takeoff": meta["design_takeoff"]}))


async def _revision_sheets(session, project_id: uuid.UUID, rev_id: uuid.UUID) -> list[Any]:
    """The revision's sheets in Documents (put there when it was shared)."""
    from .integration import _sheet_docs

    docs = await _sheet_docs(session, project_id)
    return [
        d
        for _, d in sorted(docs.items())
        if ((d.metadata_ or {}).get("design") or {}).get("revision_id") == str(rev_id)
    ]


def _sheet_number(d) -> str:
    from pathlib import PurePosixPath

    return PurePosixPath(((d.metadata_ or {}).get("design") or {}).get("sheet") or d.name or "").stem


async def _addendum_draft(
    session, svc, proc: DesignProcurement, pkg, rev_id: uuid.UUID, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """A DRAFT addendum in the ERP's tendering module: unpublished, so no bidder sees or receives it until a person
    reviews and sends it there. Positions with quantities before/after; elements and sheets of the revision."""
    from app.modules.tendering.schemas import AddendumBOQChange, AddendumCreate, AddendumDocumentChange

    rev = await session.get(DesignRevision, rev_id)
    number = rev.number if rev is not None else 0
    sheets = await _revision_sheets(session, proc.project_id, rev_id)
    text = [
        f"Design revision {number} was accepted and changes quantities of this issued package.",
        "Prepared as a draft: check it, then publish it to the bidders yourself.",
        "",
    ]
    for r in rows:
        text.append(
            f"- {r['ordinal']} {r['label']}: {r['from']} -> {r['to']} {r['unit']} "
            f"(elements {r['elements_before']} -> {r['elements_after']})"
        )
    if sheets:
        text += ["", f"Drawings of revision {number}: " + ", ".join(_sheet_number(d) for d in sheets)]
    data = AddendumCreate(
        title=f"Design revision {number}: quantity changes"[:200],
        body="\n".join(text)[:10000],
        boq_changes=[
            AddendumBOQChange(
                op=r["op"],
                position_id=r["position_id"],
                ordinal=r["ordinal"][:60],
                description=r["label"][:2000],
                unit=(r["unit"] or "")[:30],
                quantity_before=None if r["op"] == "add" else r["from"],
                quantity_after=r["to"],
            )
            for r in rows
        ][:2000],
        document_changes=[
            AddendumDocumentChange(
                document_id=d.id,
                drawing_number=_sheet_number(d)[:120] or None,
                title=(d.name or "")[:255],
                revision=str(number),
                note="Design revision sheet",
            )
            for d in sheets
        ][:200],
    )
    made = await svc.create_addendum(pkg.id, data)
    return {
        "addendum_id": made.id,
        "revision_no": made.revision_no,
        "revision_number": number,
        "lines": [
            {
                "position_id": r["position_id"],
                "group_key": r["group_key"],
                "op": r["op"],
                "from": r["from"],
                "to": r["to"],
                "unit": r["unit"],
                "element_keys": r["element_keys"],
            }
            for r in rows
        ],
        "sheets": [str(d.id) for d in sheets],
    }


async def recompute_on_accept(
    session, project_id: uuid.UUID, revision_id: uuid.UUID, model_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    await recompute(session, project_id, revision_id, model_id, user_id)


async def setup(session, project_id: uuid.UUID, group_by: str, user_id: uuid.UUID) -> DesignProcurement:
    """Create the take-off BOQ and fill it from the latest accepted revision."""
    from app.modules.boq.schemas import BOQCreate

    if group_by not in GROUP_BY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"group_by is one of {', '.join(GROUP_BY)}")
    if await _proc(session, project_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The project already has a design take-off")
    rev = (
        await session.execute(
            select(DesignRevision).where(DesignRevision.project_id == project_id, DesignRevision.status == "published")
        )
    ).scalar_one_or_none()
    if rev is None or rev.bim_model_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Accept a revision first: the take-off follows its elements")
    boq = await est_mod._svc(session).create_boq(
        BOQCreate(
            project_id=project_id,
            name="Design take-off",
            description="Material take-off by element type from accepted model revisions",
        )
    )
    proc = DesignProcurement(project_id=project_id, boq_id=boq.id, group_by=group_by, follow=True, created_by=user_id)
    session.add(proc)
    await session.flush()
    await recompute(session, project_id, rev.id, rev.bim_model_id, user_id)
    return proc


async def set_follow(session, project_id: uuid.UUID, follow: bool) -> DesignProcurement:
    proc = await _proc(session, project_id)
    if proc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The project has no design take-off")
    proc.follow = follow
    await session.flush()
    return proc


async def set_basis(
    session, project_id: uuid.UUID, line_id: uuid.UUID, basis: str, user_id: uuid.UUID
) -> DesignTakeoffLine:
    """A person measures a line in another quantity key; the position takes the model value in that key."""
    if basis not in BASES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"basis is one of {', '.join(BASES)}")
    ln = await session.get(DesignTakeoffLine, line_id)
    proc = await _proc(session, project_id)
    if ln is None or proc is None or ln.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Take-off line not found")
    if basis == ln.basis:
        return ln
    svc = est_mod._svc(session)
    pos = await svc.position_repo.get_by_id(ln.position_id)
    ln.basis, ln.basis_by_person = basis, True
    # The old quantity belonged to another unit: it cannot be an override of the new one.
    from app.modules.boq.service import _compute_total

    await svc.position_repo.update_fields(
        pos.id, unit=UNITS[basis], quantity="0", total=_compute_total("0", pos.unit_rate)
    )
    ln.last_applied_quantity = ln.model_quantity = "0"
    await session.flush()
    rev = await session.get(DesignRevision, proc.revision_id) if proc.revision_id else None
    if rev is not None and rev.bim_model_id is not None:
        await recompute(session, project_id, rev.id, rev.bim_model_id, user_id, force=True)
    return ln


# ── read ────────────────────────────────────────────────────────────────────


async def summary(session, project_id: uuid.UUID) -> dict[str, Any]:
    proc = await _proc(session, project_id)
    if proc is None:
        return {"procurement": False}
    svc = est_mod._svc(session)
    lines, sections = await _lines(session, project_id), await _sections(session, project_id)
    positions = {p.id: p for p in await svc.position_repo.list_by_ids([ln.position_id for ln in lines.values()])}
    packages_out, rows_out = [], []
    for cls, s in sorted(sections.items()):
        pkg = await _package(session, s.package_id)
        design = ((pkg.metadata_ or {}).get("design_takeoff") or {}) if pkg is not None else {}
        packages_out.append(
            {
                "ifc_class": cls,
                "package_id": str(s.package_id) if s.package_id else None,
                "name": pkg.name if pkg is not None else None,
                "status": pkg.status if pkg is not None else None,
                "missing": s.package_id is not None and pkg is None,
                "lines": sum(1 for ln in lines.values() if ln.ifc_class == cls),
                "url": TENDER_URL,
                "changes_after_issue": design.get("changes_after_issue") or [],
                "addenda": _addenda_state(pkg, design),
            }
        )
    for ln in sorted(lines.values(), key=lambda x: (x.ifc_class, x.group_key)):
        pos = positions.get(ln.position_id)
        override = bool(
            pos is not None
            and ln.model_quantity is not None
            and est_mod._overridden(pos, ln, Decimal(ln.model_quantity))
        )
        flags = [f for f in (ln.flags or []) if f != "override"]
        rows_out.append(
            {
                "line_id": str(ln.id),
                "group_key": ln.group_key,
                "label": ln.label,
                "ifc_class": ln.ifc_class,
                "basis": ln.basis,
                "basis_by_person": ln.basis_by_person,
                "unit": UNITS[ln.basis],
                "position_id": str(ln.position_id),
                "quantity": est_mod.dstr(pos.quantity) if pos is not None else "0",
                "model_quantity": ln.model_quantity,
                "override": override,
                "elements": ln.element_count,
                "available": ln.available,
                "flags": sorted(set(flags + (["override"] if override else []))),
            }
        )
    return {
        "procurement": True,
        "boq_id": str(proc.boq_id),
        "group_by": proc.group_by,
        "follow": proc.follow,
        "revision_id": str(proc.revision_id) if proc.revision_id else None,
        "packages": packages_out,
        "lines": rows_out,
        "url": TENDER_URL,
        "basis_note": BASIS_NOTE,
        "price_note": PRICE_NOTE,
    }


def _addenda_state(pkg, design: dict[str, Any]) -> list[dict[str, Any]]:
    """Addendum drafts this module prepared, with what the tendering module says of them now."""
    stored = (
        {a.get("id"): a for a in ((pkg.metadata_ or {}).get("addenda") or []) if isinstance(a, dict)} if pkg else {}
    )
    out = []
    for rev_id, d in (design.get("addenda") or {}).items():
        a = stored.get(d.get("addendum_id"))
        out.append(
            {
                "revision_id": rev_id,
                "revision_number": d.get("revision_number"),
                "addendum_id": d.get("addendum_id"),
                "revision_no": d.get("revision_no"),
                "lines": len(d.get("lines") or []),
                "sheets": len(d.get("sheets") or []),
                "elements": sum(len(x.get("element_keys") or []) for x in d.get("lines") or []),
                "state": "missing" if a is None else "published" if a.get("published_at") else "draft",
            }
        )
    return sorted(out, key=lambda x: x["revision_no"] or 0)


# ── change orders (R9) ──────────────────────────────────────────────────────


def for_change_order(imp: dict[str, Any] | None) -> dict[str, Any] | None:
    if not imp or not imp.get("procurement"):
        return None
    t = imp["totals"]
    return {
        k: t[k]
        for k in (
            "lines_changed",
            "lines_added",
            "lines_removed",
            "overrides_kept",
            "packages_affected",
            "issued_packages_affected",
        )
    }
