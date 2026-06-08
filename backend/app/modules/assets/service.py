"""Asset Operations service.

Reads tracked assets straight from the shared BIM tables, computes
lifecycle health, rolls up a portfolio summary, discovers asset
candidates from raw BIM elements, and dispatches warranty-expiry alerts
through the notifications module (gracefully degrading when it is absent).

Persistence rule: this module never creates tables. Service-log writes go
through the BIM Hub element repository's ``update_asset_info`` (the same
JSON-merge path the existing Asset Register edit modal uses), so shipping
this needs no migration.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.core.sql_json import json_path_text
from app.modules.assets import discovery as disc
from app.modules.assets import lifecycle as lc
from app.modules.assets.schemas import (
    AssetHealthSchema,
    AssetListResponse,
    AssetRow,
    DiscoveryCandidate,
    DiscoveryResponse,
    PortfolioSummary,
    ServiceLogResponse,
    WarrantyAlertItem,
    WarrantyAlertResponse,
)
from app.modules.bim_hub.models import BIMElement, BIMModel

logger = logging.getLogger(__name__)


def _health_schema(info: dict[str, Any], today: date) -> AssetHealthSchema:
    h = lc.compute_health(info, today=today)
    return AssetHealthSchema(
        warranty_status=h.warranty_status,
        warranty_until=h.warranty_until,
        days_to_warranty_expiry=h.days_to_warranty_expiry,
        maintenance_status=h.maintenance_status,
        next_maintenance_due=h.next_maintenance_due,
        days_to_maintenance=h.days_to_maintenance,
        maintenance_interval_days=h.maintenance_interval_days,
        last_serviced=h.last_serviced,
        age_days=h.age_days,
        age_years=h.age_years,
        service_log_count=h.service_log_count,
        attention_score=h.attention_score,
        issues=h.issues,
    )


def _asset_row(element: BIMElement, model: BIMModel, today: date) -> AssetRow:
    info = dict(element.asset_info or {})
    return AssetRow(
        id=element.id,
        model_id=element.model_id,
        project_id=model.project_id,
        model_name=model.name,
        stable_id=element.stable_id,
        element_type=element.element_type,
        name=element.name,
        storey=element.storey,
        manufacturer=info.get("manufacturer"),
        model=info.get("model"),
        serial_number=info.get("serial_number"),
        operational_status=info.get("operational_status"),
        parent_system=info.get("parent_system"),
        asset_info=info,
        health=_health_schema(info, today),
    )


class AssetOpsService:
    """Operational-phase asset intelligence over the BIM asset register."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Tracked-asset reads ─────────────────────────────────────────────

    def _tracked_query(self, project_id: uuid.UUID):
        return (
            select(BIMElement, BIMModel)
            .join(BIMModel, BIMElement.model_id == BIMModel.id)
            .where(
                BIMModel.project_id == project_id,
                BIMElement.is_tracked_asset.is_(True),
            )
            .options(noload(BIMElement.boq_links))
        )

    async def list_assets(
        self,
        project_id: uuid.UUID,
        *,
        warranty_status: str | None = None,
        maintenance_status: str | None = None,
        operational_status: str | None = None,
        search: str | None = None,
        sort: str = "attention",
        offset: int = 0,
        limit: int = 50,
    ) -> AssetListResponse:
        """List tracked assets enriched with computed health.

        ``warranty_status`` / ``maintenance_status`` are computed filters
        (the values are derived, not stored) so they are applied in Python
        after the cheap stored-column filters narrow the set. ``sort`` is
        ``attention`` (worst first), ``name``, or ``warranty`` (soonest
        expiry first).
        """
        today = date.today()
        stmt = self._tracked_query(project_id)
        if operational_status:
            stmt = stmt.where(json_path_text(BIMElement.asset_info, "$.operational_status") == operational_status)
        if search and search.strip():
            q = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                func.lower(BIMElement.stable_id).like(q)
                | func.lower(func.coalesce(BIMElement.name, "")).like(q)
                | func.lower(func.coalesce(json_path_text(BIMElement.asset_info, "$.manufacturer"), "")).like(q)
                | func.lower(func.coalesce(json_path_text(BIMElement.asset_info, "$.serial_number"), "")).like(q)
            )

        rows = (await self.session.execute(stmt)).all()
        all_rows = [_asset_row(el, mod, today) for el, mod in rows]

        # Computed-status filters (Python side - the values are derived).
        if warranty_status:
            all_rows = [r for r in all_rows if r.health.warranty_status == warranty_status]
        if maintenance_status:
            all_rows = [r for r in all_rows if r.health.maintenance_status == maintenance_status]

        total = len(all_rows)
        all_rows = _sort_rows(all_rows, sort)
        page = all_rows[offset : offset + limit]
        return AssetListResponse(items=page, total=total, offset=offset, limit=limit)

    async def portfolio_summary(self, project_id: uuid.UUID) -> PortfolioSummary:
        """Roll up KPIs across every tracked asset in a project."""
        today = date.today()
        rows = (await self.session.execute(self._tracked_query(project_id))).all()
        assets = [_asset_row(el, mod, today) for el, mod in rows]

        summary = PortfolioSummary(total_assets=len(assets))
        ages: list[float] = []
        models: set[uuid.UUID] = set()
        for a in assets:
            models.add(a.model_id)
            op = a.operational_status or "unknown"
            summary.by_operational_status[op] = summary.by_operational_status.get(op, 0) + 1
            ws = a.health.warranty_status
            summary.by_warranty_status[ws] = summary.by_warranty_status.get(ws, 0) + 1
            ms = a.health.maintenance_status
            summary.by_maintenance_status[ms] = summary.by_maintenance_status.get(ms, 0) + 1
            if ws == lc.WARRANTY_EXPIRED:
                summary.warranties_expired += 1
            elif ws == lc.WARRANTY_EXPIRING:
                summary.warranties_expiring_soon += 1
            if ms == lc.MAINT_OVERDUE:
                summary.maintenance_overdue += 1
            elif ms == lc.MAINT_DUE:
                summary.maintenance_due += 1
            if a.health.attention_score > 0:
                summary.needs_attention += 1
            if a.health.age_years is not None:
                ages.append(a.health.age_years)

        summary.models_covered = len(models)
        if ages:
            summary.avg_age_years = round(sum(ages) / len(ages), 1)
        summary.top_attention = _sort_rows([a for a in assets if a.health.attention_score > 0], "attention")[:8]
        return summary

    # ── Discovery ────────────────────────────────────────────────────────

    async def discover_candidates(
        self,
        project_id: uuid.UUID,
        *,
        model_id: uuid.UUID | None = None,
        threshold: int = 35,
        scan_limit: int = 5000,
        result_limit: int = 100,
    ) -> DiscoveryResponse:
        """Scan a project's BIM elements for likely managed assets.

        Pure scoring (``discovery.score_candidate``) over each element's
        category / family / properties. Already-tracked elements are
        excluded. Returns the top ``result_limit`` candidates ranked by
        score.
        """
        stmt = (
            select(BIMElement, BIMModel)
            .join(BIMModel, BIMElement.model_id == BIMModel.id)
            .where(BIMModel.project_id == project_id)
            .options(noload(BIMElement.boq_links))
            .limit(scan_limit)
        )
        if model_id is not None:
            stmt = stmt.where(BIMElement.model_id == model_id)

        rows = (await self.session.execute(stmt)).all()
        candidates: list[DiscoveryCandidate] = []
        already_tracked = 0
        models: set[uuid.UUID] = set()
        for el, mod in rows:
            models.add(el.model_id)
            if el.is_tracked_asset:
                already_tracked += 1
                continue
            cs = disc.score_candidate(
                element_type=el.element_type,
                properties=el.properties,
                already_tracked=False,
                threshold=threshold,
            )
            if not cs.is_candidate:
                continue
            candidates.append(
                DiscoveryCandidate(
                    id=el.id,
                    model_id=el.model_id,
                    model_name=mod.name,
                    stable_id=el.stable_id,
                    element_type=el.element_type,
                    name=el.name,
                    storey=el.storey,
                    score=cs.score,
                    reasons=cs.reasons,
                    suggested_asset_info=disc.extract_suggested_asset_info(el.properties),
                )
            )

        candidates.sort(key=lambda c: (-c.score, c.stable_id))
        return DiscoveryResponse(
            items=candidates[:result_limit],
            total_candidates=len(candidates),
            scanned_elements=len(rows),
            already_tracked=already_tracked,
            models_scanned=len(models),
            threshold=threshold,
        )

    # ── Warranty alerts (cross-module: notifications) ────────────────────

    async def warranty_alerts(
        self,
        project_id: uuid.UUID,
        *,
        lead_days: int = 90,
        dispatch: bool = False,
        actor_user_id: str | None = None,
    ) -> WarrantyAlertResponse:
        """Find expired / soon-to-expire warranties and optionally notify.

        When ``dispatch`` is true, one notification per recipient is created
        for the project owner and team members. If the notifications module
        is not installed, the scan still returns the list and flags
        ``notifications_unavailable`` (graceful degradation).
        """
        today = date.today()
        rows = (await self.session.execute(self._tracked_query(project_id))).all()
        items: list[WarrantyAlertItem] = []
        for el, mod in rows:
            info = dict(el.asset_info or {})
            h = lc.compute_health(info, today=today, warranty_lead_days=lead_days)
            if h.warranty_status in (lc.WARRANTY_EXPIRED, lc.WARRANTY_EXPIRING):
                items.append(
                    WarrantyAlertItem(
                        id=el.id,
                        model_id=el.model_id,
                        model_name=mod.name,
                        stable_id=el.stable_id,
                        name=el.name,
                        warranty_until=h.warranty_until,
                        days_to_expiry=h.days_to_warranty_expiry,
                        status=h.warranty_status,
                    )
                )

        # Worst first: expired (negative days) before expiring.
        items.sort(key=lambda i: i.days_to_expiry if i.days_to_expiry is not None else 0)

        resp = WarrantyAlertResponse(items=items, total=len(items))
        if not dispatch or not items:
            return resp

        recipients = await self._project_recipients(project_id)
        if not recipients:
            return resp

        try:
            from app.modules.notifications.service import NotificationService
        except Exception:  # noqa: BLE001 - notifications module absent
            logger.info("Notifications module unavailable; warranty alerts not dispatched")
            resp.notifications_unavailable = True
            return resp

        expired = sum(1 for i in items if i.status == lc.WARRANTY_EXPIRED)
        expiring = len(items) - expired
        try:
            notif = NotificationService(self.session)
            created = await notif.notify_users(
                list(recipients),
                "warning",
                "notification.asset_warranty_alert_title",
                entity_type="project",
                entity_id=str(project_id),
                body_key="notification.asset_warranty_alert_body",
                body_context={
                    "expired": expired,
                    "expiring": expiring,
                    "total": len(items),
                    "lead_days": lead_days,
                },
                action_url="/assets",
                metadata={"lead_days": lead_days, "actor": actor_user_id},
            )
            resp.dispatched = True
            resp.notifications_sent = len(created)
            resp.recipients = len(recipients)
        except Exception:
            logger.exception("Failed to dispatch warranty alerts for project %s", project_id)
            resp.notifications_unavailable = True
        return resp

    async def _project_recipients(self, project_id: uuid.UUID) -> set[uuid.UUID]:
        """Resolve notification recipients: project owner + team members."""
        recipients: set[uuid.UUID] = set()
        try:
            from app.modules.projects.models import Project

            owner = (
                await self.session.execute(select(Project.owner_id).where(Project.id == project_id))
            ).scalar_one_or_none()
            if owner:
                recipients.add(owner if isinstance(owner, uuid.UUID) else uuid.UUID(str(owner)))
        except Exception:
            logger.exception("Owner lookup failed for project %s", project_id)
        try:
            from app.modules.teams.models import Team, TeamMembership

            member_rows = (
                await self.session.execute(
                    select(TeamMembership.user_id)
                    .join(Team, TeamMembership.team_id == Team.id)
                    .where(Team.project_id == project_id)
                )
            ).scalars()
            for m in member_rows:
                if m:
                    recipients.add(m if isinstance(m, uuid.UUID) else uuid.UUID(str(m)))
        except Exception:
            # Team membership is optional; owner-only is still valid.
            logger.debug("Team membership lookup skipped for project %s", project_id)
        return recipients

    # ── Service log (write rides BIM Hub asset_info JSON) ────────────────

    async def append_service_log(
        self,
        element_id: uuid.UUID,
        *,
        entry: dict[str, Any],
        actor_user_id: str | None = None,
    ) -> ServiceLogResponse:
        """Append a service event to an asset's ``asset_info.service_log``.

        Reuses the BIM Hub element repository's JSON-merge writer so the
        canonical persistence path (and its tracked-asset auto-flip) is
        respected. 404 if the element is missing.

        IDOR defence: an element is addressed by its own UUID, but it belongs
        to a model that belongs to a project. Before mutating it we resolve the
        parent project and verify the caller has access, exactly like every
        other write path in this module. Without this check any user holding
        ``bim.update`` could append history to any element in any tenant by
        enumerating UUIDs.
        """
        from app.dependencies import verify_project_access
        from app.modules.bim_hub.models import BIMModel
        from app.modules.bim_hub.repository import BIMElementRepository

        repo = BIMElementRepository(self.session)
        element = await repo.get(element_id)
        if element is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

        model = await self.session.get(BIMModel, element.model_id)
        if model is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        await verify_project_access(model.project_id, actor_user_id or "", self.session)

        info = dict(element.asset_info or {})
        log = info.get("service_log")
        if not isinstance(log, list):
            log = []
        log = [*log, entry]
        # Keep the last_serviced convenience field in sync with the newest
        # dated entry so health computation does not have to re-scan.
        dates = [lc.parse_iso_date(e.get("date")) for e in log if isinstance(e, dict)]
        dates = [d for d in dates if d is not None]
        merged: dict[str, Any] = {"service_log": log}
        if dates:
            merged["last_serviced"] = max(dates).isoformat()

        updated = await repo.update_asset_info(element_id, asset_info=merged, is_tracked_asset=None)
        if updated is None:  # pragma: no cover - we already fetched it
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
        await self.session.commit()

        final_info = dict(updated.asset_info or {})
        return ServiceLogResponse(
            asset_id=updated.id,
            service_log=final_info.get("service_log", []),
            health=_health_schema(final_info, date.today()),
        )


def _sort_rows(rows: list[AssetRow], sort: str) -> list[AssetRow]:
    """Sort enriched asset rows by the requested key."""
    if sort == "name":
        return sorted(rows, key=lambda r: (r.name or r.stable_id or "").lower())
    if sort == "warranty":
        # Soonest expiry first; unknowns (None) last.
        def wkey(r: AssetRow) -> tuple[int, int]:
            d = r.health.days_to_warranty_expiry
            return (0, d) if d is not None else (1, 0)

        return sorted(rows, key=wkey)
    # Default: worst (highest attention) first.
    return sorted(rows, key=lambda r: (-r.health.attention_score, (r.name or r.stable_id or "")))
