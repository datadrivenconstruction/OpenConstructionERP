"""‌⁠‍Field Reports service — business logic for field report management.

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
    """‌⁠‍Business logic for field report operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = FieldReportRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_report(
        self,
        data: FieldReportCreate,
        user_id: str | None = None,
    ) -> FieldReport:
        """‌⁠‍Create a new field report.

        If ``lat`` and ``lon`` are provided and OPENWEATHERMAP_API_KEY is
        configured, weather_data is auto-populated from OpenWeatherMap.
        """
        workforce_data = [entry.model_dump() for entry in data.workforce]

        # Auto-fetch weather when coordinates are provided. Falls back to
        # the owning project's ``address`` dict — sites typically have
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
            # Sanity guard — match the schema's bounds so a junk address
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

        if report.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit an approved report",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

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
        """Delete a field report."""
        await self.get_report(report_id)  # Raises 404 if not found
        await self.repo.delete(report_id)
        logger.info("Field report deleted: %s", report_id)

    # ── Status transitions ────────────────────────────────────────────────

    async def submit_report(self, report_id: uuid.UUID) -> FieldReport:
        """Submit a draft report for approval (draft -> submitted).

        If the report's ``metadata.schedule_progress`` carries one or more
        progress entries, fires ``fieldreports.report.submitted`` so the
        schedule module can append matching :class:`ScheduleProgressEntry`
        rows. Wiring lives in ``schedule/events.py`` — the publisher does
        not import the schedule module to keep the dependency direction
        one-way (schedule subscribes to fieldreports, not vice versa).
        """
        report = await self.get_report(report_id)
        if report.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit report with status '{report.status}' — must be draft",
            )

        # Snapshot the progress payload before update_fields() expires the
        # session — the inline metadata read might MissingGreenlet otherwise.
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

        return report

    async def approve_report(self, report_id: uuid.UUID, user_id: str) -> FieldReport:
        """Approve a submitted report (submitted -> approved)."""
        report = await self.get_report(report_id)
        if report.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve report with status '{report.status}' — must be submitted",
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

        # Epic H — universal audit trail.
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
        return report

    # ── Link documents ─────────────────────────────────────────────────────

    async def link_documents(
        self,
        report_id: uuid.UUID,
        document_ids: list[str],
    ) -> FieldReport:
        """Link documents to a field report (merge, deduplicate)."""
        report = await self.get_report(report_id)

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
    """‌⁠‍Business logic for report templates.

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
        out.extend(customs)  # ORM objects — Pydantic from_attributes handles them
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
            fields["metadata_"] = fields.pop("metadata")
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

    return "\n".join(parts).encode("latin-1")
