# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate branches (variants) of a BOQ: fork, tree, compare, cherry-pick, merge.

A branch is built from the machinery the bill already has rather than beside
it. Forking is ``BOQService.duplicate_boq`` (positions, markups, cost vectors);
the fork point is a :class:`BOQSnapshot` written on the branch; carrying
changes back writes a snapshot of the receiving bill first, so any merge or
cherry-pick is undone with the existing version-history restore. The only new
state is :class:`BOQBranch`, which records where a branch came from and
whether it was merged.

The branch bill is marked with ``BOQ.branch_of_id`` so the project's bill
register and every "which bill" resolver leave it out: a variant is not a
second estimate of the project until somebody merges it.
"""

from __future__ import annotations

import copy
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.i18n import t as translate
from app.modules.boq.branch_diff import (
    LINEAGE_KEY,
    LineState,
    compare_lines,
    divergence,
    lineage_of,
    lines_from_positions,
    lines_from_snapshot,
    plan_apply,
)
from app.modules.boq.models import BOQ, BOQBranch, BOQMarkup, BOQSnapshot, Position
from app.modules.boq.service import BOQService, _safe_publish

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _refuse(code: int, error: str, **extra: Any) -> HTTPException:
    """A structured refusal: ``error`` for clients, ``message`` in the reader's language."""
    message = translate(f"boq.branch.errors.{error}", locale=get_locale(), **extra)
    return HTTPException(status_code=code, detail={"error": error, "message": message, **extra})


class BranchService:
    """Business logic for estimate branches. Access control lives in the router."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.boq = BOQService(session)

    # ── Lookups ──────────────────────────────────────────────────────────

    async def branch_row(self, boq_id: uuid.UUID) -> BOQBranch | None:
        """The branch record of a bill, or None for a bill that is not a branch."""
        stmt = select(BOQBranch).where(BOQBranch.boq_id == boq_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _header(self, boq_id: uuid.UUID) -> Any:
        header = await self.boq.boq_repo.get_header(boq_id)
        if header is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
        return header

    async def main_of(self, boq_id: uuid.UUID) -> uuid.UUID:
        """The main estimate at the root of a bill's branch tree (the bill itself for a main)."""
        await self._header(boq_id)
        row = await self.branch_row(boq_id)
        return row.main_boq_id if row is not None else boq_id

    async def _chain(self, boq_id: uuid.UUID) -> list[uuid.UUID]:
        """The bill and its ancestors up to the main estimate, nearest first."""
        chain = [boq_id]
        current = boq_id
        for _ in range(64):
            row = await self.branch_row(current)
            if row is None:
                break
            parent = row.parent_boq_id or row.main_boq_id
            if parent in chain:
                break
            chain.append(parent)
            current = parent
        return chain

    async def _snapshot_lines(self, snapshot_id: uuid.UUID | None) -> dict[str, LineState] | None:
        if snapshot_id is None:
            return None
        snap = await self.session.get(BOQSnapshot, snapshot_id)
        if snap is None:
            return None
        return lines_from_snapshot(snap.snapshot_data)

    async def pair_base(self, source_id: uuid.UUID, target_id: uuid.UUID) -> dict[str, LineState] | None:
        """The common ancestor of two bills of one tree, as lines, or None when unknown.

        The ancestor is the fork point of the branch just below the lowest
        common ancestor on the source's side (or on the target's side when the
        source is that ancestor itself). Pulling from a parent into its child
        and merging a child into its parent both resolve to the child's fork
        point, which is exact; siblings resolve to the older fork, which is the
        best approximation a linear snapshot history allows.
        """
        source_chain = await self._chain(source_id)
        target_chain = await self._chain(target_id)
        common = next((b for b in source_chain if b in target_chain), None)
        if common is None:
            return None
        side = source_chain if common != source_id else target_chain
        idx = side.index(common)
        if idx == 0:
            return None
        child = side[idx - 1]
        row = await self.branch_row(child)
        return await self._snapshot_lines(row.base_snapshot_id if row else None)

    async def _lines(self, boq_id: uuid.UUID) -> tuple[dict[str, LineState], dict[str, Position]]:
        positions = await self.boq.position_repo.list_all_for_boq(boq_id)
        lines = lines_from_positions(positions)
        by_id = {str(p.id): p for p in positions}
        by_key = {key: by_id[line.id] for key, line in lines.items() if line.id in by_id}
        return lines, by_key

    async def _snapshot(self, boq_id: uuid.UUID, *, name: str, user_id: uuid.UUID | None) -> BOQSnapshot:
        """``create_snapshot`` on the bill as stored now, not as an earlier read cached it.

        ``create_snapshot`` serialises ``boq.positions`` of the identity-map
        instance; rows written since by bulk statements are not in that list.
        """
        await self.session.execute(select(BOQ).where(BOQ.id == boq_id).execution_options(populate_existing=True))
        return await self.boq.create_snapshot(boq_id, name=name, user_id=user_id)

    async def _stamp_lineage(self, boq_id: uuid.UUID) -> None:
        """Give every line of a bill a lineage key, so its copies can be paired with it.

        Bookkeeping in the metadata blob only: no figure, version or status
        moves, which is why a locked bill is stamped too.
        """
        for pos in await self.boq.position_repo.list_all_for_boq(boq_id):
            meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
            if isinstance(meta.get(LINEAGE_KEY), str) and meta[LINEAGE_KEY]:
                continue
            await self.boq.position_repo.update_fields(pos.id, metadata_={**meta, LINEAGE_KEY: str(pos.id)})

    # ── Fork ─────────────────────────────────────────────────────────────

    async def create_branch(
        self,
        source_boq_id: uuid.UUID,
        *,
        name: str,
        note: str = "",
        snapshot_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> BOQ:
        """Fork a branch from a bill's current state or from one of its snapshots.

        Raises:
            HTTPException: 404 when the bill or snapshot is missing, 409 when the
                source is a branch that was merged or archived.
        """
        header = await self._header(source_boq_id)
        source_row = await self.branch_row(source_boq_id)
        if source_row is not None and source_row.status != "open":
            raise _refuse(status.HTTP_409_CONFLICT, "branch_closed")
        main_id = source_row.main_boq_id if source_row is not None else source_boq_id

        snapshot: BOQSnapshot | None = None
        if snapshot_id is not None:
            snapshot = await self.boq.get_snapshot(source_boq_id, snapshot_id)

        await self._stamp_lineage(source_boq_id)
        new_boq = await self.boq.duplicate_boq(source_boq_id)
        new_id = new_boq.id
        locale = get_locale()

        if snapshot is not None:
            data = copy.deepcopy(snapshot.snapshot_data or {})
            for row in data.get("positions") or []:
                if isinstance(row, dict):
                    meta = dict(row.get("metadata") or {})
                    meta[LINEAGE_KEY] = lineage_of(meta, row.get("id"))
                    row["metadata"] = meta
            base = BOQSnapshot(
                boq_id=new_id,
                name=translate("boq.branch.base_snapshot_from", locale=locale, snapshot=snapshot.name or ""),
                description="",
                snapshot_data=data,
                total_value=snapshot.total_value,
                position_count=snapshot.position_count,
                created_by=actor_id,
            )
            self.session.add(base)
            await self.session.flush()
            await self.boq.restore_snapshot(new_id, base.id)
        else:
            base = await self._snapshot(
                new_id,
                name=translate("boq.branch.base_snapshot", locale=locale),
                user_id=actor_id,
            )
        base_id = base.id

        await self.boq.boq_repo.update_fields(
            new_id,
            name=name,
            parent_estimate_id=source_boq_id,
            branch_of_id=main_id,
            status="draft",
            is_locked=False,
            created_by=actor_id,
        )
        row = BOQBranch(
            boq_id=new_id,
            main_boq_id=main_id,
            parent_boq_id=source_boq_id,
            base_snapshot_id=base_id,
            source_snapshot_id=snapshot_id,
            status="open",
            note=note,
            created_by=actor_id,
        )
        self.session.add(row)
        await self.session.flush()

        await self._log(
            actor_id,
            "branch.created",
            main_id,
            header["project_id"],
            f"Branch '{name}' created from BOQ {source_boq_id}",
            {"branch_boq_id": str(new_id), "source_boq_id": str(source_boq_id), "snapshot_id": str(snapshot_id or "")},
        )
        await _safe_publish(
            "boq.branch.created",
            {
                "branch_boq_id": str(new_id),
                "main_boq_id": str(main_id),
                "source_boq_id": str(source_boq_id),
                "project_id": str(header["project_id"]),
            },
            session=self.session,
        )
        return await self.boq.get_boq(new_id)

    async def update_branch(
        self,
        branch_boq_id: uuid.UUID,
        *,
        name: str | None = None,
        note: str | None = None,
        new_status: str | None = None,
    ) -> BOQBranch:
        """Rename, annotate, archive or reopen a branch. A merged branch stays merged."""
        row = await self.branch_row(branch_boq_id)
        if row is None:
            raise _refuse(status.HTTP_404_NOT_FOUND, "not_a_branch")
        if new_status is not None and row.status == "merged":
            raise _refuse(status.HTTP_409_CONFLICT, "branch_closed")
        if name is not None:
            await self.boq.boq_repo.update_fields(branch_boq_id, name=name)
        if note is not None:
            row.note = note
        if new_status is not None:
            row.status = new_status
        await self.session.flush()
        return row

    # ── Tree ─────────────────────────────────────────────────────────────

    async def tree(self, boq_id: uuid.UUID) -> dict[str, Any]:
        """The branch tree a bill belongs to: main first, then every branch."""
        main_id = await self.main_of(boq_id)
        rows = list(
            (
                await self.session.execute(
                    select(BOQBranch).where(BOQBranch.main_boq_id == main_id).order_by(BOQBranch.created_at)
                )
            )
            .scalars()
            .all()
        )
        ids = [main_id, *[r.boq_id for r in rows]]
        headers = {
            h.id: h
            for h in (
                await self.session.execute(
                    select(
                        BOQ.id,
                        BOQ.name,
                        BOQ.project_id,
                        BOQ.is_locked,
                        BOQ.created_at,
                        BOQ.created_by,
                    ).where(BOQ.id.in_(ids))
                )
            ).all()
        }
        totals = await self.boq.boq_repo.totals_for_boqs(ids)
        counts = dict(
            (
                await self.session.execute(
                    select(Position.boq_id, func.count()).where(Position.boq_id.in_(ids)).group_by(Position.boq_id)
                )
            ).all()
        )
        authors = await self._user_names({r.created_by for r in rows} | {h.created_by for h in headers.values()})
        project_id = headers[main_id].project_id if main_id in headers else None
        currency = await self._project_currency(project_id)
        options, by_boq = await self._design_options(project_id)

        def _money(value: Any) -> str:
            return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))

        def _grand(bid: uuid.UUID) -> Decimal:
            return Decimal(str((totals.get(bid) or {}).get("grand_total") or 0))

        nodes: list[dict[str, Any]] = []
        main = headers.get(main_id)
        nodes.append(
            {
                "boq_id": main_id,
                "name": main.name if main else "",
                "is_main": True,
                "status": "open",
                "is_locked": bool(main.is_locked) if main else False,
                "created_at": main.created_at.isoformat() if main and main.created_at else None,
                "created_by": main.created_by if main else None,
                "author": authors.get(main.created_by, "") if main else "",
                "position_count": int(counts.get(main_id, 0)),
                "direct_cost": _money((totals.get(main_id) or {}).get("direct_cost")),
                "grand_total": _money(_grand(main_id)),
                "design_option": by_boq.get(main_id),
            }
        )
        for r in rows:
            h = headers.get(r.boq_id)
            if h is None:
                continue
            parent = r.parent_boq_id if r.parent_boq_id in headers else main_id
            nodes.append(
                {
                    "boq_id": r.boq_id,
                    "name": h.name,
                    "is_main": False,
                    "parent_boq_id": parent,
                    "status": r.status,
                    "note": r.note or "",
                    "is_locked": bool(h.is_locked),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "created_by": r.created_by,
                    "author": authors.get(r.created_by, ""),
                    "position_count": int(counts.get(r.boq_id, 0)),
                    "direct_cost": _money((totals.get(r.boq_id) or {}).get("direct_cost")),
                    "grand_total": _money(_grand(r.boq_id)),
                    "delta_vs_parent": _money(_grand(r.boq_id) - _grand(parent)),
                    "base_snapshot_id": r.base_snapshot_id,
                    "source_snapshot_id": r.source_snapshot_id,
                    "merged_at": r.merged_at,
                    "merged_by": r.merged_by,
                    "merge_snapshot_id": r.merge_snapshot_id,
                    "design_option": by_boq.get(r.boq_id),
                }
            )
        return {"main_boq_id": main_id, "currency": currency, "nodes": nodes, "design_options": options}

    async def _user_names(self, user_ids: set[Any]) -> dict[Any, str]:
        ids = [u for u in user_ids if u is not None]
        if not ids:
            return {}
        try:
            from app.modules.users.models import User
        except ImportError:
            return {}
        rows = (await self.session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(ids)))).all()
        return {r.id: (r.full_name or r.email or "") for r in rows}

    async def _project_currency(self, project_id: uuid.UUID | None) -> str:
        if project_id is None:
            return ""
        from app.modules.projects.models import Project

        row = (await self.session.execute(select(Project.currency).where(Project.id == project_id))).first()
        return (row[0] or "") if row else ""

    async def _project_standard(self, boq_id: uuid.UUID) -> str:
        from app.modules.projects.models import Project

        stmt = select(Project.classification_standard).join(BOQ, BOQ.project_id == Project.id).where(BOQ.id == boq_id)
        row = (await self.session.execute(stmt)).first()
        return (row[0] or "") if row else ""

    async def _design_options(
        self, project_id: uuid.UUID | None
    ) -> tuple[list[dict[str, Any]], dict[uuid.UUID, dict[str, Any]]]:
        """The project's design options, and which bill each one prices. Empty without the module."""
        if project_id is None:
            return [], {}
        try:
            from app.modules.design_options.models import DesignOption, DesignOptionSet
        except ImportError:
            return [], {}
        stmt = (
            select(DesignOption.id, DesignOption.name, DesignOption.set_id, DesignOption.boq_id, DesignOptionSet.name)
            .join(DesignOptionSet, DesignOptionSet.id == DesignOption.set_id)
            .where(DesignOption.project_id == project_id)
            .order_by(DesignOptionSet.name, DesignOption.sort_order)
        )
        options: list[dict[str, Any]] = []
        by_boq: dict[uuid.UUID, dict[str, Any]] = {}
        for oid, oname, set_id, boq_id, set_name in (await self.session.execute(stmt)).all():
            ref = {"id": oid, "name": oname or "", "set_id": set_id, "set_name": set_name or "", "boq_id": boq_id}
            options.append(ref)
            if boq_id is not None:
                by_boq.setdefault(boq_id, ref)
        return options, by_boq

    # ── Compare ──────────────────────────────────────────────────────────

    async def compare(self, a_id: uuid.UUID, b_id: uuid.UUID) -> dict[str, Any]:
        """Position-level compare of two bills, with totals by section and cost group."""
        a_header = await self._header(a_id)
        b_header = await self._header(b_id)
        a_lines, _ = await self._lines(a_id)
        b_lines, _ = await self._lines(b_id)
        result = compare_lines(a_lines, b_lines, standard=await self._project_standard(a_id))
        return {
            "a_boq_id": a_id,
            "b_boq_id": b_id,
            "a_name": a_header["name"],
            "b_name": b_header["name"],
            "currency": await self._project_currency(a_header["project_id"]),
            **result,
        }

    # ── Cherry-pick and merge ────────────────────────────────────────────

    async def plan(self, source_id: uuid.UUID, target_id: uuid.UUID, keys: list[str] | None = None) -> dict[str, Any]:
        """Preview carrying changes from source into target, conflicts marked."""
        if source_id == target_id:
            raise _refuse(status.HTTP_400_BAD_REQUEST, "same_bill")
        source_header = await self._header(source_id)
        target_header = await self._header(target_id)
        if source_header["project_id"] != target_header["project_id"]:
            raise _refuse(status.HTTP_400_BAD_REQUEST, "different_project")
        if await self.main_of(source_id) != await self.main_of(target_id):
            raise _refuse(status.HTTP_400_BAD_REQUEST, "different_tree")
        base = await self.pair_base(source_id, target_id)
        source_lines, _ = await self._lines(source_id)
        target_lines, _ = await self._lines(target_id)
        items = plan_apply(base, source_lines, target_lines, keys)
        return {
            "source_boq_id": source_id,
            "target_boq_id": target_id,
            "base_known": base is not None,
            "items": items,
            "conflicts": sum(1 for i in items if i["conflict"]),
        }

    async def cherry_pick(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        keys: list[str] | None,
        resolutions: dict[str, str],
        actor_id: uuid.UUID | None = None,
        snapshot_label: str | None = None,
    ) -> dict[str, Any]:
        """Carry the named changes into the target bill, refusing while a conflict is undecided.

        The target is snapshotted first, so the version history can undo it.

        Raises:
            HTTPException: 409 ``unresolved_conflicts`` listing the undecided
                lines, 409 when the target is locked or a closed branch.
        """
        target_row = await self.branch_row(target_id)
        if target_row is not None and target_row.status != "open":
            raise _refuse(status.HTTP_409_CONFLICT, "branch_closed")
        await self.boq._ensure_boq_writable(target_id)
        plan = await self.plan(source_id, target_id, keys)
        undecided = [
            i for i in plan["items"] if i["conflict"] and resolutions.get(i["key"]) not in ("source", "target")
        ]
        if undecided:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "unresolved_conflicts",
                    "message": translate(
                        "boq.branch.errors.unresolved_conflicts", locale=get_locale(), count=len(undecided)
                    ),
                    "conflicts": [{"key": i["key"], "ordinal": i["ordinal"]} for i in undecided],
                },
            )
        source_header = await self._header(source_id)
        locale = get_locale()
        snap = await self._snapshot(
            target_id,
            name=snapshot_label
            or translate("boq.branch.before_cherry_pick", locale=locale, source=source_header["name"] or ""),
            user_id=actor_id,
        )
        result = await self._apply(source_id, target_id, plan["items"], resolutions)
        result["snapshot_id"] = snap.id
        target_header = await self._header(target_id)
        await self._log(
            actor_id,
            "branch.cherry_picked",
            target_id,
            target_header["project_id"],
            f"Changes from BOQ {source_id} applied",
            {k: v for k, v in result.items() if k in ("added", "updated", "removed", "kept_target")},
        )
        await _safe_publish(
            "boq.branch.cherry_picked",
            {
                "source_boq_id": str(source_id),
                "target_boq_id": str(target_id),
                "project_id": str(target_header["project_id"]),
            },
            session=self.session,
        )
        return result

    async def merge(
        self,
        branch_id: uuid.UUID,
        *,
        resolutions: dict[str, str],
        include_markups: bool = False,
        actor_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Merge an open branch back into its main estimate and close it.

        Main is snapshotted first. Afterwards the branch is locked and marked
        merged, so the record of what was merged cannot drift.
        """
        row = await self.branch_row(branch_id)
        if row is None:
            raise _refuse(status.HTTP_404_NOT_FOUND, "not_a_branch")
        if row.status != "open":
            raise _refuse(status.HTTP_409_CONFLICT, "branch_closed")
        main_id = row.main_boq_id
        branch_header = await self._header(branch_id)
        label = translate("boq.branch.before_merge", locale=get_locale(), branch=branch_header["name"] or "")
        result = await self.cherry_pick(
            branch_id, main_id, keys=None, resolutions=resolutions, actor_id=actor_id, snapshot_label=label
        )
        if include_markups:
            await self._replace_markups(branch_id, main_id)
        row.status = "merged"
        row.merged_at = _now_iso()
        row.merged_by = actor_id
        row.merge_snapshot_id = result["snapshot_id"]
        await self.session.flush()
        await self.boq.boq_repo.update_fields(branch_id, is_locked=True)
        result["status"] = "merged"
        await _safe_publish(
            "boq.branch.merged",
            {
                "branch_boq_id": str(branch_id),
                "main_boq_id": str(main_id),
                "project_id": str(branch_header["project_id"]),
                "snapshot_id": str(result["snapshot_id"]),
            },
            session=self.session,
        )
        return result

    async def _apply(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        items: list[dict[str, Any]],
        resolutions: dict[str, str],
    ) -> dict[str, Any]:
        """Write a plan into the target: parents before children, leaves before sections."""
        source_lines, source_pos = await self._lines(source_id)
        target_lines, target_pos = await self._lines(target_id)
        taken_ordinals = {p.ordinal for p in target_pos.values()}
        result: dict[str, Any] = {
            "target_boq_id": target_id,
            "added": 0,
            "updated": 0,
            "removed": 0,
            "kept_target": 0,
            "skipped": [],
        }
        todo = []
        for item in items:
            if item["conflict"] and resolutions.get(item["key"]) == "target":
                result["kept_target"] += 1
                continue
            todo.append(item)

        def _parent_id(line: LineState) -> uuid.UUID | None:
            if line.parent_key and line.parent_key in target_pos:
                return target_pos[line.parent_key].id
            return None

        def _free_ordinal(wanted: str, own_key: str) -> str:
            holder = next((k for k, p in target_pos.items() if p.ordinal == wanted), None)
            if wanted not in taken_ordinals or holder == own_key:
                return wanted
            n = 1
            while f"{wanted}.{n}" in taken_ordinals:
                n += 1
            return f"{wanted}.{n}"

        for item in sorted((i for i in todo if i["action"] != "remove"), key=lambda i: i["depth"]):
            key = item["key"]
            src = source_pos.get(key)
            line = source_lines.get(key)
            if src is None or line is None:
                result["skipped"].append(key)
                continue
            meta = dict(src.metadata_) if isinstance(src.metadata_, dict) else {}
            meta[LINEAGE_KEY] = key if not key.startswith("id:") else str(src.id)
            if item["action"] == "add":
                ordinal = _free_ordinal(src.ordinal, key)
                new = Position(
                    boq_id=target_id,
                    parent_id=_parent_id(line),
                    ordinal=ordinal,
                    description=src.description,
                    unit=src.unit,
                    quantity=src.quantity,
                    unit_rate=src.unit_rate,
                    total=src.total,
                    net_cost_rate=src.net_cost_rate,
                    target_rate=src.target_rate,
                    sale_rate=src.sale_rate,
                    classification=dict(src.classification or {}),
                    source=src.source,
                    confidence=src.confidence,
                    risk_dispersion=src.risk_dispersion,
                    price_basis=src.price_basis,
                    cad_element_ids=list(src.cad_element_ids or []),
                    cad_model_id=src.cad_model_id,
                    reference_code=src.reference_code,
                    norm_id=src.norm_id,
                    norm_work_key=src.norm_work_key,
                    validation_status="pending",
                    metadata_=meta,
                    sort_order=src.sort_order,
                )
                self.session.add(new)
                await self.session.flush()
                target_pos[key] = new
                taken_ordinals.add(ordinal)
                result["added"] += 1
            else:
                tgt = target_pos.get(key)
                if tgt is None:
                    result["skipped"].append(key)
                    continue
                fields: dict[str, Any] = {
                    "description": src.description,
                    "unit": src.unit,
                    "quantity": src.quantity,
                    "unit_rate": src.unit_rate,
                    "total": src.total,
                    "classification": dict(src.classification or {}),
                    "metadata_": meta,
                    "validation_status": "pending",
                    "version": int(tgt.version or 0) + 1,
                }
                if src.ordinal != tgt.ordinal:
                    ordinal = _free_ordinal(src.ordinal, key)
                    taken_ordinals.discard(tgt.ordinal)
                    taken_ordinals.add(ordinal)
                    fields["ordinal"] = ordinal
                parent = _parent_id(line)
                if (line.parent_key is None or parent is not None) and parent != tgt.parent_id:
                    fields["parent_id"] = parent
                await self.boq.position_repo.update_fields(tgt.id, **fields)
                result["updated"] += 1

        for item in sorted((i for i in todo if i["action"] == "remove"), key=lambda i: -i["depth"]):
            tgt = target_pos.get(item["key"])
            if tgt is None:
                continue
            try:
                await self.boq.delete_position(tgt.id, cascade=False)
            except HTTPException as exc:
                # A section the target filled with lines of its own stays.
                if exc.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
                    result["skipped"].append(item["key"])
                    continue
                raise
            result["removed"] += 1

        await self.session.flush()
        return result

    async def _replace_markups(self, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
        """Make the target's markup stack the source's, scopes re-pointed by lineage."""
        _, source_pos = await self._lines(source_id)
        _, target_pos = await self._lines(target_id)
        source_key_of = {p.id: k for k, p in source_pos.items()}
        for markup in await self.boq.markup_repo.list_for_boq(target_id):
            await self.boq.markup_repo.delete(markup.id)
        await self.session.flush()
        originals = await self.boq.markup_repo.list_for_boq(source_id)
        copies: list[BOQMarkup] = []
        for m in originals:
            scope = None
            if m.scope_position_id is not None:
                key = source_key_of.get(m.scope_position_id)
                scope = target_pos[key].id if key in target_pos else None
            copies.append(
                BOQMarkup(
                    boq_id=target_id,
                    name=m.name,
                    markup_type=m.markup_type,
                    category=m.category,
                    percentage=m.percentage,
                    fixed_amount=m.fixed_amount,
                    apply_to=m.apply_to,
                    sort_order=m.sort_order,
                    is_active=m.is_active,
                    scope_position_id=scope,
                    metadata_=dict(m.metadata_ or {}),
                )
            )
        if not copies:
            return
        created = await self.boq.markup_repo.bulk_create(copies)
        id_map = {orig.id: new.id for orig, new in zip(originals, created, strict=True)}
        for orig, new in zip(originals, created, strict=True):
            if orig.overrides_id is not None and orig.overrides_id in id_map:
                await self.boq.markup_repo.update_fields(new.id, overrides_id=id_map[orig.overrides_id])

    # ── Status for validation ────────────────────────────────────────────

    async def divergence(self, branch_id: uuid.UUID) -> dict[str, Any] | None:
        """Drift of an open branch from its main estimate; None for a bill that is not one."""
        row = await self.branch_row(branch_id)
        if row is None:
            return None
        base = await self.pair_base(branch_id, row.main_boq_id)
        branch_lines, _ = await self._lines(branch_id)
        main_lines, _ = await self._lines(row.main_boq_id)
        drift = divergence(base, branch_lines, main_lines)
        created = row.created_at
        days = (datetime.now(UTC) - created).days if created is not None else 0
        return {"status": row.status, "days_open": max(days, 0), **drift}

    # ── Design options ───────────────────────────────────────────────────

    async def link_design_option(self, branch_id: uuid.UUID, option_id: uuid.UUID | None) -> None:
        """Make a design option price itself from this bill, or unlink whichever option does.

        Delegates to the design-options module's own link, which checks the
        option's project and reprices it.
        """
        try:
            from app.modules.design_options.models import DesignOption
            from app.modules.design_options.schemas import DesignOptionLinkRequest
            from app.modules.design_options.service import DesignOptionsService
        except ImportError as exc:
            raise _refuse(status.HTTP_404_NOT_FOUND, "design_options_unavailable") from exc
        header = await self._header(branch_id)
        service = DesignOptionsService(self.session)
        if option_id is None:
            linked = (
                (await self.session.execute(select(DesignOption).where(DesignOption.boq_id == branch_id)))
                .scalars()
                .all()
            )
            for option in linked:
                await service.link_references(option, DesignOptionLinkRequest(boq_id=None))
            return
        option = await service.get_option(option_id)
        if option.project_id != header["project_id"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Design option not found")
        await service.link_references(option, DesignOptionLinkRequest(boq_id=branch_id))

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _log(
        self,
        actor_id: uuid.UUID | None,
        action: str,
        boq_id: uuid.UUID,
        project_id: uuid.UUID | None,
        description: str,
        changes: dict[str, Any],
    ) -> None:
        if actor_id is None:
            return
        try:
            async with self.session.begin_nested():
                await self.boq.log_activity(
                    user_id=actor_id,
                    action=action,
                    target_type="boq",
                    target_id=boq_id,
                    description=description,
                    project_id=project_id,
                    boq_id=boq_id,
                    changes=changes,
                )
        except Exception:  # noqa: BLE001 - the audit row must not undo the user's change
            logger.debug("%s log failed", action, exc_info=True)
