# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Field Reports service - business logic for field report management.

Stateless service layer. Handles:
- Field report CRUD
- Status transitions (draft -> submitted -> approved)
- Weather fetching (optional OpenWeatherMap)
- Summary aggregation
- PDF export
"""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.json_merge import merge_metadata
from app.core.pdf_branding import branded_cover_brand
from app.core.validation.messages import translate
from app.modules.fieldreports.builtin_templates import (
    BUILTIN_TEMPLATES,
    get_builtin,
    is_builtin_id,
)
from app.modules.fieldreports.models import FieldReport, FieldReportTemplate
from app.modules.fieldreports.repository import (
    FieldReportRepository,
    FieldReportTemplateRepository,
)
from app.modules.fieldreports.schemas import (
    FieldReportCreate,
    FieldReportTemplateCreate,
    FieldReportTemplateUpdate,
    FieldReportUpdate,
)

logger = logging.getLogger(__name__)


class FieldReportService:
    """Business logic for field report operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FieldReportRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_report(
        self,
        data: FieldReportCreate,
        user_id: str | None = None,
    ) -> FieldReport:
        """Create a new field report.

        If ``lat`` and ``lon`` are provided and OPENWEATHERMAP_API_KEY is
        configured, weather_data is auto-populated from OpenWeatherMap.
        """
        workforce_data = [entry.model_dump() for entry in data.workforce]

        # Auto-fetch weather when coordinates are provided. Falls back to
        # the owning project's ``address`` dict - sites typically have
        # fixed coordinates, so the user shouldn't need to repeat them on
        # every daily report. We accept several common key shapes the
        # frontend may emit (lat/lon, latitude/longitude, coordinates.lat).
        weather_data: dict[str, Any] | None = None
        lat = data.lat
        lon = data.lon
        if lat is None or lon is None:
            fallback = await self._project_coords(data.project_id)
            if fallback is not None:
                lat = lat if lat is not None else fallback[0]
                lon = lon if lon is not None else fallback[1]
        if lat is not None and lon is not None:
            weather_data = await self._try_fetch_weather(lat, lon)

        report = FieldReport(
            project_id=data.project_id,
            report_date=data.report_date,
            report_type=data.report_type,
            weather_condition=data.weather_condition,
            temperature_c=data.temperature_c,
            wind_speed=data.wind_speed,
            precipitation=data.precipitation,
            humidity=data.humidity,
            workforce=workforce_data,
            equipment_on_site=data.equipment_on_site,
            work_performed=data.work_performed,
            delays=data.delays,
            delay_hours=data.delay_hours,
            visitors=data.visitors,
            deliveries=data.deliveries,
            safety_incidents=data.safety_incidents,
            materials_used=data.materials_used,
            photos=data.photos,
            notes=data.notes,
            signature_by=data.signature_by,
            signature_data=data.signature_data,
            status="draft",
            created_by=user_id,
            metadata_=data.metadata,
            weather_data=weather_data,
        )

        # If weather was fetched and user didn't set temperature/humidity,
        # back-fill from the API response.
        if weather_data and data.temperature_c is None and weather_data.get("temperature_c") is not None:
            report.temperature_c = weather_data["temperature_c"]
        if weather_data and data.humidity is None and weather_data.get("humidity_pct") is not None:
            report.humidity = weather_data["humidity_pct"]

        report = await self.repo.create(report)
        logger.info(
            "Field report created: %s (%s) for project %s",
            report.report_date,
            report.report_type,
            data.project_id,
        )
        return report

    async def _project_coords(
        self,
        project_id: uuid.UUID,
    ) -> tuple[float, float] | None:
        """Best-effort lat/lon read from the owning project's address dict.

        Returns None on any failure (missing project, missing address,
        non-numeric coords, import errors). Tolerates several key shapes
        because the frontend has historically emitted both flat
        ``lat``/``lon`` and nested ``coordinates.lat`` payloads.
        """
        try:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, project_id)
            if project is None:
                return None
            address = getattr(project, "address", None)
            if not isinstance(address, dict):
                return None

            def _pick(d: dict, *keys: str) -> object | None:
                for k in keys:
                    if k in d and d[k] is not None:
                        return d[k]
                return None

            raw_lat = _pick(address, "lat", "latitude")
            raw_lon = _pick(address, "lon", "lng", "longitude")
            coords = address.get("coordinates")
            if (raw_lat is None or raw_lon is None) and isinstance(coords, dict):
                raw_lat = raw_lat if raw_lat is not None else _pick(coords, "lat", "latitude")
                raw_lon = raw_lon if raw_lon is not None else _pick(coords, "lon", "lng", "longitude")

            if raw_lat is None or raw_lon is None:
                return None
            lat_f = float(raw_lat)
            lon_f = float(raw_lon)
            # Sanity guard - match the schema's bounds so a junk address
            # doesn't poison the weather call with nonsense coords.
            if not (-90.0 <= lat_f <= 90.0):
                return None
            if not (-180.0 <= lon_f <= 180.0):
                return None
            return (lat_f, lon_f)
        except Exception:
            return None

    async def _try_fetch_weather(self, lat: float, lon: float) -> dict[str, Any] | None:
        """Attempt to fetch weather, returning None on any failure."""
        import os

        try:
            from app.config import get_settings

            api_key = get_settings().openweathermap_api_key
            if not api_key:
                api_key = os.environ.get("OPENWEATHERMAP_API_KEY", "")
            if not api_key:
                return None

            from app.modules.fieldreports.weather import fetch_weather

            return await fetch_weather(lat, lon, api_key=api_key)
        except Exception:
            logger.warning("Auto weather fetch failed for lat=%s lon=%s", lat, lon)
            return None

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_report(self, report_id: uuid.UUID) -> FieldReport:
        """Get field report by ID. Raises 404 if not found."""
        report = await self.repo.get_by_id(report_id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Field report not found",
            )
        return report

    async def list_reports(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        date_from: date | None = None,
        date_to: date | None = None,
        report_type: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[FieldReport], int]:
        """List field reports for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            report_type=report_type,
            status=status_filter,
        )

    async def get_by_date(self, project_id: uuid.UUID, report_date: date) -> FieldReport | None:
        """Get a field report for a specific date."""
        return await self.repo.get_by_date(project_id, report_date)

    async def get_calendar(self, project_id: uuid.UUID, year: int, month: int) -> list[FieldReport]:
        """Get all reports for a month (calendar view)."""
        return await self.repo.get_for_month(project_id, year, month)

    # ── Update ────────────────────────────────────────────────────────────

    async def update_report(
        self,
        report_id: uuid.UUID,
        data: FieldReportUpdate,
    ) -> FieldReport:
        """Update field report fields. Only allowed for draft reports."""
        report = await self.get_report(report_id)

        if report.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit a report with status '{report.status}' - only draft reports are editable",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(report, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        # Convert workforce entries from Pydantic models to dicts
        if "workforce" in fields and fields["workforce"] is not None:
            fields["workforce"] = [
                entry.model_dump() if hasattr(entry, "model_dump") else entry for entry in fields["workforce"]
            ]

        if not fields:
            return report

        await self.repo.update_fields(report_id, **fields)
        await self.session.refresh(report)

        logger.info("Field report updated: %s (fields=%s)", report_id, list(fields.keys()))
        return report

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_report(self, report_id: uuid.UUID) -> None:
        """Delete a field report. Only draft reports can be deleted.

        Once a report is submitted or approved its labour log has been
        published downstream (cost actuals / payroll) and an audit-trail
        entry written, so a hard delete would orphan that data.
        """
        report = await self.get_report(report_id)  # Raises 404 if not found
        if report.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete a report with status '{report.status}' - only draft reports can be deleted",
            )
        await self.repo.delete(report_id)
        logger.info("Field report deleted: %s", report_id)

    # ── Status transitions ────────────────────────────────────────────────

    async def submit_report(self, report_id: uuid.UUID) -> FieldReport:
        """Submit a draft report for approval (draft -> submitted).

        If the report's ``metadata.schedule_progress`` carries one or more
        progress entries, fires ``fieldreports.report.submitted`` so the
        schedule module can append matching :class:`ScheduleProgressEntry`
        rows. Wiring lives in ``schedule/events.py`` - the publisher does
        not import the schedule module to keep the dependency direction
        one-way (schedule subscribes to fieldreports, not vice versa).
        """
        report = await self.get_report(report_id)
        if report.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit report with status '{report.status}' - must be draft",
            )

        # Snapshot the progress payload before update_fields() expires the
        # session - the inline metadata read might MissingGreenlet otherwise.
        md = report.metadata_ if isinstance(report.metadata_, dict) else {}
        schedule_progress = md.get("schedule_progress") if isinstance(md, dict) else None
        project_id_s = str(report.project_id)

        await self.repo.update_fields(report_id, status="submitted")
        await self.session.refresh(report)
        logger.info("Field report submitted: %s", report_id)

        if isinstance(schedule_progress, list) and schedule_progress:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "fieldreports.report.submitted",
                {
                    "report_id": str(report_id),
                    "project_id": project_id_s,
                    "report_date": str(report.report_date),
                    "schedule_progress": schedule_progress,
                    "submitted_by": getattr(report, "created_by", None),
                },
                source_module="oe_fieldreports",
            )

        # Publish the labour log so the cost model and payroll can roll up
        # hours x rate. Best-effort: a failure here must not block submission.
        await self._publish_labour(report, status="submitted")

        return report

    async def approve_report(self, report_id: uuid.UUID, user_id: str) -> FieldReport:
        """Approve a submitted report (submitted -> approved)."""
        report = await self.get_report(report_id)
        if report.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve report with status '{report.status}' - must be submitted",
            )

        prior_status = report.status
        now = datetime.now(UTC)
        await self.repo.update_fields(
            report_id,
            status="approved",
            approved_by=user_id,
            approved_at=now,
        )
        await self.session.refresh(report)

        # Epic H - universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=user_id,
            entity_type="field_report",
            entity_id=str(report_id),
            action="status_changed",
            from_status=prior_status,
            to_status="approved",
            reason="Field report approved",
            module="fieldreports",
            parent_entity_type="project",
            parent_entity_id=str(report.project_id),
            before_state={"status": prior_status},
            after_state={"status": "approved"},
        )

        logger.info("Field report approved: %s by %s", report_id, user_id)

        # Re-publish the labour log on approval. Subscribers are idempotent
        # per (report_id, status), so a submit + approve pair never
        # double-counts the same hours into budget actuals.
        await self._publish_labour(report, status="approved", actor_id=user_id)

        return report

    # ── Labour log publication ──────────────────────────────────────────────

    async def _collect_labour_rows(self, report: FieldReport) -> list[dict[str, Any]]:
        """Normalise a report's workforce into payroll/cost-ready rows.

        Prefers the structured :class:`SiteWorkforceLog` rows (they may carry
        a ``resource_id`` / ``cost_rate`` in metadata); falls back to the
        free-form ``workforce`` JSON column when no structured rows exist.

        Each returned row carries at least ``worker_type`` and ``hours``
        (a float, regular + overtime combined). ``resource_id`` / ``cost_rate``
        / ``currency`` are surfaced when present so the cost model can apply
        the resource rate or the snapshot rate deterministically.
        """
        from sqlalchemy import select

        from app.modules.fieldreports.models import SiteWorkforceLog

        def _to_float(value: object) -> float:
            try:
                f = float(str(value))
            except (TypeError, ValueError):
                return 0.0
            return f if f >= 0.0 else 0.0

        rows: list[dict[str, Any]] = []

        stmt = select(SiteWorkforceLog).where(SiteWorkforceLog.field_report_id == report.id)
        result = await self.session.execute(stmt)
        structured = list(result.scalars().all())

        for log in structured:
            md = log.metadata_ if isinstance(log.metadata_, dict) else {}
            hours = _to_float(log.hours_worked) + _to_float(log.overtime_hours)
            row: dict[str, Any] = {
                "worker_type": log.worker_type,
                "company": log.company,
                "headcount": int(log.headcount or 0),
                "hours": round(hours, 4),
                "overtime_hours": round(_to_float(log.overtime_hours), 4),
                "wbs_id": log.wbs_id,
                "cost_category": log.cost_category,
            }
            resource_id = md.get("resource_id")
            if resource_id:
                row["resource_id"] = str(resource_id)
            if md.get("cost_rate") is not None:
                row["cost_rate"] = str(md["cost_rate"])
            if md.get("currency"):
                row["currency"] = str(md["currency"])
            rows.append(row)

        if rows:
            return rows

        # Fallback: the simpler JSON ``workforce`` column (count + hours).
        workforce = report.workforce if isinstance(report.workforce, list) else []
        for entry in workforce:
            if not isinstance(entry, dict):
                continue
            count = _to_float(entry.get("count"))
            per_head = _to_float(entry.get("hours"))
            total_hours = count * per_head if count else per_head
            row = {
                "worker_type": str(entry.get("trade") or entry.get("worker_type") or "labour"),
                "company": entry.get("company"),
                "headcount": int(count),
                "hours": round(total_hours, 4),
                "overtime_hours": 0.0,
                "wbs_id": entry.get("wbs_id"),
                "cost_category": entry.get("cost_category"),
            }
            if entry.get("resource_id"):
                row["resource_id"] = str(entry["resource_id"])
            if entry.get("cost_rate") is not None:
                row["cost_rate"] = str(entry["cost_rate"])
            if entry.get("currency"):
                row["currency"] = str(entry["currency"])
            rows.append(row)

        return rows

    async def _publish_labour(
        self,
        report: FieldReport,
        *,
        status: str,
        actor_id: str | None = None,
    ) -> None:
        """Gather workforce rows and publish ``fieldreports.labour.logged``.

        Swallows its own errors: the labour rollup is a downstream
        convenience and must never break the report status transition.
        """
        try:
            rows = await self._collect_labour_rows(report)
            if not rows:
                return
            from app.modules.fieldreports.events import publish_labour_logged

            publish_labour_logged(
                report_id=str(report.id),
                project_id=str(report.project_id),
                report_date=str(report.report_date),
                status=status,
                rows=rows,
                actor_id=actor_id,
            )
        except Exception:
            logger.exception(
                "Labour-log publish failed for report=%s - status transition unaffected",
                report.id,
            )

    # ── Link documents ─────────────────────────────────────────────────────

    async def _reject_foreign_document_ids(
        self,
        project_id: uuid.UUID,
        document_ids: list[str],
    ) -> None:
        """Raise 422 if any document_id belongs to a different project.

        A field report's ``document_ids`` JSON array is a cross-module
        reference into ``oe_documents_document``. Without this guard a
        caller who can edit a report in their own project could attach a
        UUID that resolves to a document in another project, and the
        ``GET /reports/{id}/documents/`` endpoint would echo that foreign
        document's name and metadata back to them. The check is symmetric:
        a missing document and a document owned by another project both
        return the same 422, so the endpoint never becomes a UUID-existence
        oracle.
        """
        if not document_ids:
            return
        from sqlalchemy import select as _select

        from app.modules.documents.models import Document

        ids: list[uuid.UUID] = []
        for raw in document_ids:
            try:
                ids.append(uuid.UUID(str(raw)))
            except (ValueError, AttributeError):
                continue
        if not ids:
            return

        stmt = _select(Document.id, Document.project_id).where(Document.id.in_(ids))
        rows = (await self.session.execute(stmt)).all()
        by_id = {str(row[0]): str(row[1]) for row in rows}

        bad: list[str] = []
        for raw in document_ids:
            owner = by_id.get(str(raw))
            if owner is None or owner != str(project_id):
                bad.append(str(raw))
        if bad:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"document_ids reference documents that do not belong to project {project_id}: {bad}"),
            )

    async def link_documents(
        self,
        report_id: uuid.UUID,
        document_ids: list[str],
    ) -> FieldReport:
        """Link documents to a field report (merge, deduplicate).

        Foreign-project or unknown document_ids are rejected with 422 so a
        report can only ever reference documents inside its own project.
        """
        report = await self.get_report(report_id)
        # The attachment list is part of what was submitted and approved, so it
        # follows the same draft-only rule as update_report.
        if report.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot link documents to a report with status '{report.status}' - only draft reports are editable",
            )
        await self._reject_foreign_document_ids(report.project_id, document_ids)

        existing = list(report.document_ids or [])
        merged = list(dict.fromkeys(existing + document_ids))  # preserve order, deduplicate

        await self.repo.update_fields(report_id, document_ids=merged)
        await self.session.refresh(report)

        logger.info(
            "Documents linked to field report %s: %s (total=%d)",
            report_id,
            document_ids,
            len(merged),
        )
        return report

    # ── Weather (optional) ────────────────────────────────────────────────

    async def get_weather(self, lat: float, lon: float) -> dict[str, Any]:
        """Fetch current weather from OpenWeatherMap API.

        Requires OPENWEATHERMAP_API_KEY env var. Falls back gracefully
        if the key is not set or the request fails.
        """
        import os

        api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
        if not api_key:
            return {"error": "OpenWeatherMap API key not configured", "available": False}

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={
                        "lat": lat,
                        "lon": lon,
                        "appid": api_key,
                        "units": "metric",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    weather = data.get("weather", [{}])[0]
                    main = data.get("main", {})
                    wind = data.get("wind", {})
                    return {
                        "available": True,
                        "condition": weather.get("main", "Clear").lower(),
                        "description": weather.get("description", ""),
                        "temperature_c": main.get("temp"),
                        "humidity": main.get("humidity"),
                        "wind_speed_ms": wind.get("speed"),
                    }
                return {"error": f"API returned {resp.status_code}", "available": False}
        except Exception as exc:
            logger.warning("Weather API request failed: %s", exc)
            return {"error": str(exc), "available": False}

    # ── Summary ───────────────────────────────────────────────────────────

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Get aggregated stats for a project's field reports.

        Counts / by_status / by_type / delay_hours come from SQL aggregates;
        only the JSON `workforce` column is iterated in Python because
        count*hours math doesn't survive a portable JSON_EXTRACT path.
        """
        agg = await self.repo.aggregates_for_project(project_id)
        workforce_rows = await self.repo.workforce_for_project(project_id)

        total_workforce_hours = 0.0
        for entries in workforce_rows:
            for entry in entries:
                if isinstance(entry, dict):
                    try:
                        count = float(entry.get("count", 0) or 0)
                        hours = float(entry.get("hours", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        continue
                    total_workforce_hours += count * hours

        return {
            "total": agg["total"],
            "by_status": agg["by_status"],
            "by_type": agg["by_type"],
            "total_workforce_hours": round(total_workforce_hours, 1),
            "total_delay_hours": round(float(agg["total_delay_hours"]), 1),
        }

    # ── PDF Export ────────────────────────────────────────────────────────

    async def generate_pdf(self, report_id: uuid.UUID) -> bytes:
        """Generate a PDF report for a single field report.

        Uses a minimal text-based PDF approach (no heavy dependencies).
        Returns raw PDF bytes.
        """
        report = await self.get_report(report_id)

        lines: list[str] = []
        # Workspace brand title line (issue #284); falls back to the default name.
        lines.append(branded_cover_brand())
        lines.append("FIELD REPORT")
        lines.append(f"Project: {report.project_id}")
        lines.append(f"Date: {report.report_date}")
        lines.append(f"Type: {report.report_type}")
        lines.append(f"Status: {report.status}")
        lines.append(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")
        lines.append("-" * 80)

        lines.append("\nWEATHER")
        lines.append(f"  Condition: {report.weather_condition}")
        if report.temperature_c is not None:
            lines.append(f"  Temperature: {report.temperature_c} C")
        if report.wind_speed:
            lines.append(f"  Wind: {report.wind_speed}")
        if report.precipitation:
            lines.append(f"  Precipitation: {report.precipitation}")
        if report.humidity is not None:
            lines.append(f"  Humidity: {report.humidity}%")

        lines.append("\nWORKFORCE")
        workforce = report.workforce or []
        if workforce:
            for entry in workforce:
                if isinstance(entry, dict):
                    lines.append(
                        f"  {entry.get('trade', '?')}: {entry.get('count', 0)} workers, {entry.get('hours', 0)} hrs"
                    )
        else:
            lines.append("  (none recorded)")

        lines.append("\nWORK PERFORMED")
        lines.append(f"  {report.work_performed or '(none)'}")

        if report.delays:
            lines.append(f"\nDELAYS ({report.delay_hours} hrs)")
            lines.append(f"  {report.delays}")

        if report.safety_incidents:
            lines.append("\nSAFETY INCIDENTS")
            lines.append(f"  {report.safety_incidents}")

        if report.visitors:
            lines.append(f"\nVISITORS: {report.visitors}")

        if report.deliveries:
            lines.append(f"\nDELIVERIES: {report.deliveries}")

        if report.notes:
            lines.append(f"\nNOTES: {report.notes}")

        if report.signature_by:
            lines.append(f"\nSigned by: {report.signature_by}")

        if report.approved_by:
            lines.append(f"Approved by: {report.approved_by} at {report.approved_at}")

        content = "\n".join(lines)
        pdf = _build_minimal_pdf(content)
        logger.info("Field report PDF exported: %s", report_id)
        return pdf


class FieldReportTemplateService:
    """Business logic for report templates.

    Merges code-defined built-in templates with the project's own
    custom templates. Built-ins are read-only; mutation endpoints reject
    them with HTTP 400. All project-scoped access control is enforced by
    the router via ``verify_project_access`` exactly like field reports.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FieldReportTemplateRepository(session)

    @staticmethod
    def _builtin_to_dict() -> list[dict[str, Any]]:
        """Return built-in templates as response-shaped dicts."""
        return [
            {
                "id": tpl["id"],
                "project_id": None,
                "name": tpl["name"],
                "description": tpl.get("description"),
                "report_type": tpl.get("report_type", "daily"),
                "fields": tpl["fields"],
                "is_active": True,
                "is_builtin": True,
                "created_by": None,
                "metadata_": {},
                "created_at": None,
                "updated_at": None,
            }
            for tpl in BUILTIN_TEMPLATES
        ]

    async def list_templates(self, project_id: uuid.UUID, *, include_builtin: bool = True) -> list[dict[str, Any]]:
        """List built-in + custom templates available for a project."""
        out: list[dict[str, Any]] = []
        if include_builtin:
            out.extend(self._builtin_to_dict())
        customs = await self.repo.list_for_project(project_id)
        out.extend(customs)  # ORM objects - Pydantic from_attributes handles them
        return out

    async def get_template(self, template_id: str, project_id: uuid.UUID) -> Any:
        """Get a single template (built-in or custom). Raises 404."""
        if is_builtin_id(template_id):
            tpl = get_builtin(template_id)
            if tpl is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=translate("errors.template_not_found", locale=get_locale()),
                )
            return self._builtin_to_dict_one(tpl)

        try:
            tpl_uuid = uuid.UUID(template_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.template_not_found", locale=get_locale()),
            ) from None
        row = await self.repo.get_by_id(tpl_uuid)
        if row is None or str(row.project_id) != str(project_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.template_not_found", locale=get_locale()),
            )
        return row

    @staticmethod
    def _builtin_to_dict_one(tpl: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": tpl["id"],
            "project_id": None,
            "name": tpl["name"],
            "description": tpl.get("description"),
            "report_type": tpl.get("report_type", "daily"),
            "fields": tpl["fields"],
            "is_active": True,
            "is_builtin": True,
            "created_by": None,
            "metadata_": {},
            "created_at": None,
            "updated_at": None,
        }

    async def create_template(self, data: FieldReportTemplateCreate, user_id: str | None = None) -> FieldReportTemplate:
        """Create a custom, project-scoped template."""
        template = FieldReportTemplate(
            project_id=data.project_id,
            name=data.name,
            description=data.description,
            report_type=data.report_type,
            fields=[f.model_dump() for f in data.fields],
            is_active=data.is_active,
            created_by=user_id,
            metadata_=data.metadata,
        )
        template = await self.repo.create(template)
        logger.info(
            "Field report template created: %s for project %s",
            template.name,
            data.project_id,
        )
        return template

    async def update_template(
        self,
        template_id: uuid.UUID,
        data: FieldReportTemplateUpdate,
    ) -> FieldReportTemplate:
        """Update a custom template. Built-ins cannot be updated."""
        template = await self.repo.get_by_id(template_id)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.template_not_found", locale=get_locale()),
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(template, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )
        if "fields" in fields and fields["fields"] is not None:
            fields["fields"] = [f.model_dump() if hasattr(f, "model_dump") else f for f in fields["fields"]]
        if not fields:
            return template

        await self.repo.update_fields(template_id, **fields)
        await self.session.refresh(template)
        logger.info("Field report template updated: %s", template_id)
        return template

    async def delete_template(self, template_id: uuid.UUID) -> None:
        """Delete a custom template. Built-ins cannot be deleted."""
        template = await self.repo.get_by_id(template_id)
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.template_not_found", locale=get_locale()),
            )
        await self.repo.delete(template_id)
        logger.info("Field report template deleted: %s", template_id)


def _build_minimal_pdf(text: str) -> bytes:
    """Build a minimal valid PDF document from plain text.

    This produces a basic but valid PDF without requiring any external library.
    """
    safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    text_lines = safe_text.split("\n")
    text_commands: list[str] = []
    text_commands.append("BT")
    text_commands.append("/F1 10 Tf")
    text_commands.append("50 750 Td")
    text_commands.append("12 TL")
    for line in text_lines:
        text_commands.append(f"({line}) '")
    text_commands.append("ET")
    stream_content = "\n".join(text_commands)

    objects: list[str] = []

    objects.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")
    objects.append("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj")
    objects.append(
        "3 0 obj\n<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj"
    )
    objects.append(f"4 0 obj\n<< /Length {len(stream_content)} >>\nstream\n{stream_content}\nendstream\nendobj")
    objects.append("5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj")

    parts: list[str] = ["%PDF-1.4"]
    offsets: list[int] = []
    current = len(parts[0]) + 1

    for obj in objects:
        offsets.append(current)
        parts.append(obj)
        current += len(obj) + 1

    xref_offset = current
    xref_lines = [f"xref\n0 {len(objects) + 1}", "0000000000 65535 f "]
    for off in offsets:
        xref_lines.append(f"{off:010d} 00000 n ")
    parts.append("\n".join(xref_lines))

    parts.append(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF")

    # Courier (a Type1 base font) only covers Latin-1, and the document is a
    # single-byte stream, so any non-Latin-1 glyph in the report text (Cyrillic,
    # CJK, emoji, …) must be substituted rather than crash the export with a
    # UnicodeEncodeError -> HTTP 500. errors="replace" emits one '?' byte per
    # unencodable char, which keeps each char 1 byte so the /Length stays valid.
    return "\n".join(parts).encode("latin-1", "replace")
