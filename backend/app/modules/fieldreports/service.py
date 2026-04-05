"""Field Reports service — business logic for field report management.

Stateless service layer. Handles:
- Field report CRUD
- Status transitions (draft -> submitted -> approved)
- Weather fetching (optional OpenWeatherMap)
- Summary aggregation
- PDF export
"""

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fieldreports.models import FieldReport
from app.modules.fieldreports.repository import FieldReportRepository
from app.modules.fieldreports.schemas import FieldReportCreate, FieldReportUpdate

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
        """Create a new field report."""
        workforce_data = [entry.model_dump() for entry in data.workforce]

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
        )
        report = await self.repo.create(report)
        logger.info(
            "Field report created: %s (%s) for project %s",
            report.report_date,
            report.report_type,
            data.project_id,
        )
        return report

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

    async def get_by_date(
        self, project_id: uuid.UUID, report_date: date
    ) -> FieldReport | None:
        """Get a field report for a specific date."""
        return await self.repo.get_by_date(project_id, report_date)

    async def get_calendar(
        self, project_id: uuid.UUID, year: int, month: int
    ) -> list[FieldReport]:
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
                entry.model_dump() if hasattr(entry, "model_dump") else entry
                for entry in fields["workforce"]
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
        """Submit a draft report for approval (draft -> submitted)."""
        report = await self.get_report(report_id)
        if report.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot submit report with status '{report.status}' — must be draft",
            )

        await self.repo.update_fields(report_id, status="submitted")
        await self.session.refresh(report)
        logger.info("Field report submitted: %s", report_id)
        return report

    async def approve_report(
        self, report_id: uuid.UUID, user_id: str
    ) -> FieldReport:
        """Approve a submitted report (submitted -> approved)."""
        report = await self.get_report(report_id)
        if report.status != "submitted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve report with status '{report.status}' — must be submitted",
            )

        now = datetime.now(timezone.utc)
        await self.repo.update_fields(
            report_id,
            status="approved",
            approved_by=user_id,
            approved_at=now,
        )
        await self.session.refresh(report)
        logger.info("Field report approved: %s by %s", report_id, user_id)
        return report

    # ── Weather (optional) ────────────────────────────────────────────────

    async def get_weather(
        self, lat: float, lon: float
    ) -> dict[str, Any]:
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
        """Get aggregated stats for a project's field reports."""
        reports = await self.repo.all_for_project(project_id)

        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        total_workforce_hours = 0.0
        total_delay_hours = 0.0

        for report in reports:
            by_status[report.status] = by_status.get(report.status, 0) + 1
            by_type[report.report_type] = by_type.get(report.report_type, 0) + 1
            total_delay_hours += report.delay_hours or 0.0

            # Sum workforce hours
            for entry in (report.workforce or []):
                if isinstance(entry, dict):
                    count = entry.get("count", 0)
                    hours = entry.get("hours", 0.0)
                    total_workforce_hours += count * hours

        return {
            "total": len(reports),
            "by_status": by_status,
            "by_type": by_type,
            "total_workforce_hours": round(total_workforce_hours, 1),
            "total_delay_hours": round(total_delay_hours, 1),
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
        lines.append(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
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
                        f"  {entry.get('trade', '?')}: "
                        f"{entry.get('count', 0)} workers, "
                        f"{entry.get('hours', 0)} hrs"
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
    objects.append(
        f"4 0 obj\n<< /Length {len(stream_content)} >>\n"
        f"stream\n{stream_content}\nendstream\nendobj"
    )
    objects.append(
        "5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>\nendobj"
    )

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

    parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF"
    )

    return "\n".join(parts).encode("latin-1")
