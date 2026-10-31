# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check business logic.

Builds a plain snapshot of an estimate, builds the comparables pool from the
company's other estimates, runs the ``estimate_checks`` rule set through the core
validation engine and attaches human acceptances. Results are cached in memory
by estimate revision, so opening the panel twice costs one computation.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, BOQActivityLog, BOQMarkup, Position
from app.modules.estimate_checks.kpis import (
    KPI_BY_ID,
    KPI_DEFS,
    STATUS_NORMAL,
    STATUS_SUSPECT,
    STATUS_WARNING,
    compute_kpis,
    history_row,
    merge_settings,
)
from app.modules.estimate_checks.repository import EstimateCheckRepository
from app.modules.estimate_checks.validators import evaluate
from app.modules.projects.models import Project

# Single-company install: one workspace. A tenant claim can key it later.
WORKSPACE_KEY = ""
HISTORY_LIMIT = 150
HISTORY_TTL_S = 900.0
_RESULT_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_RESULT_CACHE_MAX = 64
_HISTORY_CACHE: dict[tuple[str, ...], tuple[float, list[dict[str, Any]]]] = {}


def clear_caches() -> None:
    """Drop every cached rating and comparables pool (tests, settings change)."""
    _RESULT_CACHE.clear()
    _HISTORY_CACHE.clear()


def _position_dict(p: Position, db_rate: float | None = None) -> dict[str, Any]:
    meta = p.metadata_ if isinstance(p.metadata_, dict) else {}
    return {
        "id": str(p.id),
        "ordinal": p.ordinal or "",
        "description": p.description or "",
        "unit": p.unit or "",
        "quantity": p.quantity,
        "unit_rate": p.unit_rate,
        "total": p.total,
        "node_type": getattr(p, "node_type", None),
        "resources": meta.get("resources") if isinstance(meta.get("resources"), list) else [],
        "metadata": {k: meta.get(k) for k in ("quotes", "quote_count", "subcontractor") if k in meta},
        "db_rate": db_rate,
    }


def _markup_dict(m: BOQMarkup | Any) -> dict[str, Any]:
    return {
        "category": m.category,
        "percentage": m.percentage,
        "is_active": m.is_active,
        "scoped": m.scope_position_id is not None,
    }


class EstimateCheckService:
    """On-demand estimate check for one BOQ."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EstimateCheckRepository(session)

    # ── settings and preference ────────────────────────────────────────

    async def settings(self) -> dict[str, Any]:
        row = await self.repo.get_settings(WORKSPACE_KEY)
        return merge_settings(row.settings_ if row else None)

    async def save_settings(self, body: dict[str, Any], user_id: str) -> dict[str, Any]:
        kpis = {k: v for k, v in (body.get("kpis") or {}).items() if k in KPI_BY_ID}
        for cfg in kpis.values():
            low, high = cfg.get("low"), cfg.get("high")
            if low is not None and high is not None and low > high:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "low must not exceed high")
        await self.repo.save_settings(WORKSPACE_KEY, {**body, "kpis": kpis}, user_id)
        clear_caches()
        return await self.settings()

    async def preference(self, user_id: str) -> str:
        row = await self.repo.get_pref(user_id)
        return row.display_mode if row else "badge"

    async def save_preference(self, user_id: str, mode: str) -> str:
        row = await self.repo.save_pref(user_id, mode)
        return row.display_mode

    # ── snapshot and revision ──────────────────────────────────────────

    async def _boq(self, boq_id: uuid.UUID) -> BOQ:
        boq = (await self.session.execute(select(BOQ).where(BOQ.id == boq_id))).scalar_one_or_none()
        if boq is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "BOQ not found")
        return boq

    async def revision(self, boq_id: uuid.UUID) -> str:
        """Cheap fingerprint of everything a rating depends on."""
        pos = (
            await self.session.execute(
                select(func.count(Position.id), func.max(Position.updated_at), func.sum(Position.version)).where(
                    Position.boq_id == boq_id
                )
            )
        ).one()
        mk = (
            await self.session.execute(
                select(func.count(BOQMarkup.id), func.max(BOQMarkup.updated_at)).where(BOQMarkup.boq_id == boq_id)
            )
        ).one()
        acc = await self.repo.list_acceptances(boq_id)
        acc_key = max((str(a.updated_at) for a in acc), default="")
        return f"{pos[0]}:{pos[1]}:{pos[2]}:{mk[0]}:{mk[1]}:{len(acc)}:{acc_key}"

    async def _db_rates(self, positions: list[Position]) -> dict[str, float]:
        """Cost database rate per position, for lines priced from a cost item."""
        ids: dict[str, str] = {}
        for p in positions:
            meta = p.metadata_ if isinstance(p.metadata_, dict) else {}
            cid = meta.get("cost_item_id")
            if cid:
                ids[str(p.id)] = str(cid)
        if not ids:
            return {}
        try:
            from app.modules.costs.models import CostItem
        except ImportError:
            return {}
        wanted = []
        for v in set(ids.values()):
            try:
                wanted.append(uuid.UUID(v))
            except ValueError:
                continue
        if not wanted:
            return {}
        rows = (await self.session.execute(select(CostItem.id, CostItem.rate).where(CostItem.id.in_(wanted)))).all()
        rate_by_item = {str(r[0]): r[1] for r in rows}
        out = {}
        for pid, cid in ids.items():
            try:
                out[pid] = float(rate_by_item[cid])
            except (KeyError, TypeError, ValueError):
                continue
        return out

    async def snapshot(self, boq_id: uuid.UUID) -> tuple[dict[str, Any], dict[str, Position]]:
        positions = list(
            (await self.session.execute(select(Position).where(Position.boq_id == boq_id))).scalars().all()
        )
        markups = list(
            (await self.session.execute(select(BOQMarkup).where(BOQMarkup.boq_id == boq_id))).scalars().all()
        )
        rates = await self._db_rates(positions)
        snap = {
            "positions": [_position_dict(p, rates.get(str(p.id))) for p in positions],
            "markups": [_markup_dict(m) for m in markups if m.scope_position_id is None],
        }
        return snap, {str(p.id): p for p in positions}

    # ── comparables ────────────────────────────────────────────────────

    async def _pool(self, exclude: uuid.UUID, project: Project | None, scope: str) -> list[dict[str, Any]]:
        stmt = select(BOQ.id).join(Project, Project.id == BOQ.project_id).where(BOQ.id != exclude)
        if project is not None and scope in ("type_currency_region", "currency_region", "currency"):
            stmt = stmt.where(Project.currency == (project.currency or ""))
            if scope in ("type_currency_region", "currency_region"):
                stmt = stmt.where(Project.region == (project.region or ""))
            if scope == "type_currency_region":
                stmt = stmt.where(Project.project_type == project.project_type)
        stmt = stmt.order_by(BOQ.updated_at.desc()).limit(HISTORY_LIMIT)
        ids = [r[0] for r in (await self.session.execute(stmt)).all()]
        key = (scope, str(exclude), *sorted(str(i) for i in ids))
        hit = _HISTORY_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < HISTORY_TTL_S:
            return hit[1]
        if not ids:
            return []
        cols = (
            Position.boq_id,
            Position.id,
            Position.ordinal,
            Position.description,
            Position.unit,
            Position.quantity,
            Position.unit_rate,
            Position.total,
            Position.node_type,
            Position.metadata_,
        )
        by_boq: dict[Any, dict[str, Any]] = {i: {"positions": [], "markups": []} for i in ids}
        for row in (await self.session.execute(select(*cols).where(Position.boq_id.in_(ids)))).all():
            meta = row[9] if isinstance(row[9], dict) else {}
            by_boq[row[0]]["positions"].append(
                {
                    "id": str(row[1]),
                    "description": row[3] or "",
                    "unit": row[4] or "",
                    "quantity": row[5],
                    "unit_rate": row[6],
                    "total": row[7],
                    "node_type": row[8],
                    "resources": meta.get("resources") if isinstance(meta.get("resources"), list) else [],
                    "metadata": {k: meta.get(k) for k in ("quotes", "quote_count", "subcontractor") if k in meta},
                }
            )
        mk_rows = (
            await self.session.execute(
                select(BOQMarkup.boq_id, BOQMarkup.category, BOQMarkup.percentage, BOQMarkup.is_active).where(
                    BOQMarkup.boq_id.in_(ids), BOQMarkup.scope_position_id.is_(None)
                )
            )
        ).all()
        for r in mk_rows:
            by_boq[r[0]]["markups"].append({"category": r[1], "percentage": r[2], "is_active": r[3]})
        pool = [history_row(s) for s in by_boq.values() if s["positions"]]
        if len(_HISTORY_CACHE) > 32:
            _HISTORY_CACHE.clear()
        _HISTORY_CACHE[key] = (time.monotonic(), pool)
        return pool

    async def comparables(
        self, boq_id: uuid.UUID, project: Project | None, settings: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        mode = settings.get("comparables", "auto")
        if mode == "all":
            return "all", await self._pool(boq_id, project, "all")
        scopes = (
            ["currency", "all"]
            if mode == "currency"
            else ["type_currency_region", "currency_region", "currency", "all"]
        )
        if project is None or not project.project_type:
            scopes = [s for s in scopes if s != "type_currency_region"]
        need = int(settings["min_comparables"])
        pool: list[dict[str, Any]] = []
        scope = "all"
        for scope in scopes:
            pool = await self._pool(boq_id, project, scope)
            if len(pool) >= need:
                break
        return scope, pool

    # ── the check ──────────────────────────────────────────────────────

    async def check(self, boq_id: uuid.UUID) -> dict[str, Any]:
        boq = await self._boq(boq_id)
        rev = await self.revision(boq_id)
        cached = _RESULT_CACHE.get((str(boq_id), rev))
        if cached is not None:
            _RESULT_CACHE.move_to_end((str(boq_id), rev))
            return cached

        settings = await self.settings()
        project = (await self.session.execute(select(Project).where(Project.id == boq.project_id))).scalar_one_or_none()
        snap, by_id = await self.snapshot(boq_id)
        kpis = compute_kpis(snap, db_tolerance_pct=float(settings["database_rate_tolerance_pct"]))
        n_lines = int(kpis.pop("_meta").value or 0)
        scope, pool = await self.comparables(boq_id, project, settings)
        ratings = await evaluate(
            {"kpis": kpis, "positions": n_lines},
            {"history": pool, "settings": settings},
            target_id=str(boq_id),
        )
        acc = {a.kpi_id: a for a in await self.repo.list_acceptances(boq_id)}
        counts = {"normal": 0, "suspect": 0, "warning": 0, "accepted": 0}
        order = {k.kpi_id: i for i, k in enumerate(KPI_DEFS)}
        out_kpis = []
        for r in sorted(ratings, key=lambda x: order.get(x["kpi_id"], 99)):
            a = acc.get(r["kpi_id"])
            ids = r.pop("position_ids", [])
            r["position_count"] = len(ids)
            r["positions"] = [
                {"id": pid, "ordinal": by_id[pid].ordinal or "", "description": (by_id[pid].description or "")[:160]}
                for pid in ids[:50]
                if pid in by_id
            ]
            r["accepted"] = (
                {
                    "reason": a.reason,
                    "accepted_by": a.accepted_by,
                    "accepted_at": a.updated_at or a.created_at,
                    "status_at_accept": a.status_at_accept,
                    "value_at_accept": a.value_at_accept,
                }
                if a is not None and r["status"] in (STATUS_SUSPECT, STATUS_WARNING)
                else None
            )
            if r["accepted"] is not None:
                counts["accepted"] += 1
            elif r["status"] in (STATUS_NORMAL, STATUS_SUSPECT, STATUS_WARNING):
                counts[r["status"]] += 1
            out_kpis.append(r)
        result = {
            "boq_id": str(boq_id),
            "revision": rev,
            "currency": (project.currency if project else "") or "",
            "comparables_scope": scope,
            "comparables_pool": len(pool),
            "counts": counts,
            "kpis": out_kpis,
        }
        _RESULT_CACHE[(str(boq_id), rev)] = result
        while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)
        return result

    async def accept(self, boq_id: uuid.UUID, kpi_id: str, reason: str, user_id: str) -> dict[str, Any]:
        if kpi_id not in KPI_BY_ID:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown check")
        boq = await self._boq(boq_id)
        current = next((k for k in (await self.check(boq_id))["kpis"] if k["kpi_id"] == kpi_id), None)
        if current is None or current["status"] not in (STATUS_SUSPECT, STATUS_WARNING):
            raise HTTPException(status.HTTP_409_CONFLICT, "Only a suspect or warning finding can be accepted")
        value = None if current["value"] is None else str(current["value"])
        await self.repo.upsert_acceptance(boq_id, kpi_id, reason.strip(), current["status"], value, user_id)
        self._audit(boq, user_id, "estimate_check.accepted", kpi_id, {"reason": reason.strip(), "value": value})
        await self.session.flush()
        return await self.check(boq_id)

    async def withdraw(self, boq_id: uuid.UUID, kpi_id: str, user_id: str) -> dict[str, Any]:
        boq = await self._boq(boq_id)
        if await self.repo.delete_acceptance(boq_id, kpi_id):
            self._audit(boq, user_id, "estimate_check.acceptance_withdrawn", kpi_id, {})
            await self.session.flush()
        return await self.check(boq_id)

    def _audit(self, boq: BOQ, user_id: str, action: str, kpi_id: str, changes: dict[str, Any]) -> None:
        try:
            uid: uuid.UUID | None = uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            uid = None
        self.session.add(
            BOQActivityLog(
                project_id=boq.project_id,
                boq_id=boq.id,
                user_id=uid,
                action=action,
                target_type="estimate_check",
                target_id=None,
                description=f"Estimate check {kpi_id}: {changes.get('reason') or 'acceptance withdrawn'}"[:2000],
                changes={"kpi_id": kpi_id, **changes},
            )
        )
