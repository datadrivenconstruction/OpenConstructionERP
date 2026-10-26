# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Exchange fidelity reports: build them for a bill, store them, read them back.

The pure analysis lives in :mod:`app.modules.boq.exchange_fidelity`; this
module loads what it needs (the stored tree, the project name), runs the
optional round trip through the matching importer and keeps the result in
``oe_boq_exchange_report``. Every write here is best effort for the caller:
an export or an import never fails because its report could not be stored.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.exchange_fidelity import (
    FidelityItem,
    FidelityReport,
    analyze_bc3_export,
    analyze_gaeb_export,
    analyze_sheet_export,
    roundtrip_diff,
    tree_rows,
)
from app.modules.boq.models import BOQExchangeReport
from app.modules.boq.repository import ExchangeReportRepository

logger = logging.getLogger(__name__)

#: Response header naming the stored report of an export.
REPORT_HEADER = "X-Exchange-Report-Id"
#: Response header with ``errors,warnings,notes`` counts of that report.
COUNTS_HEADER = "X-Exchange-Fidelity"


async def load_tree(service: Any, boq_id: uuid.UUID) -> list[Any]:
    """The bill's hierarchy as :class:`~app.modules.boq.exchange_fidelity.TreeRow` items."""
    from app.modules.boq.service import _is_section

    positions = await service.position_repo.list_all_for_boq(boq_id)
    return tree_rows(positions, _is_section)


def _reader_for(format_id: str) -> Any:
    from app.modules.boq.importers.bc3 import BC3Importer
    from app.modules.boq.importers.excel import ExcelImporter
    from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

    return {"gaeb_xml": GAEBXMLImporter, "bc3": BC3Importer, "excel": ExcelImporter, "csv": ExcelImporter}.get(
        format_id
    )


async def analyze_export(
    service: Any,
    boq_id: uuid.UUID,
    structured: Any,
    *,
    format_id: str,
    variant: str = "",
    project_name: str = "",
    trace: list[dict[str, Any]] | None = None,
    content: bytes | None = None,
    roundtrip: bool = False,
) -> FidelityReport:
    """The fidelity report of one export of ``structured``.

    ``trace`` is what the writer recorded (GAEB and BC3); ``content`` the bytes
    it produced, read back in memory when ``roundtrip`` is set.
    """
    tree = await load_tree(service, boq_id)
    if format_id == "gaeb_xml":
        report = analyze_gaeb_export(structured, trace or [], variant=variant, project_name=project_name, tree=tree)
    elif format_id == "bc3":
        report = analyze_bc3_export(structured, trace or [], tree=tree)
    elif format_id in ("excel", "csv"):
        report = analyze_sheet_export(structured, format_id=format_id, tree=tree)  # type: ignore[arg-type]
    else:
        raise ValueError(f"no fidelity analysis for {format_id!r}")

    if roundtrip and content is not None:
        report.roundtrip = True
        report.extend(await roundtrip_items(format_id, variant, structured, content))
    return report


async def roundtrip_items(format_id: str, variant: str, structured: Any, content: bytes) -> list[FidelityItem]:
    """Read the exported bytes back with the matching importer and diff them with the bill."""
    from app.modules.boq.importers import ImporterParseError

    reader = _reader_for(format_id)
    if reader is None:
        return []
    try:
        reimported = await reader.parse(content)
    except ImporterParseError as exc:
        return [
            FidelityItem(
                severity="error",
                kind="roundtrip_mismatch",
                field="file",
                detail=str(exc),
                params={"code": exc.code},
            )
        ]
    except Exception as exc:  # noqa: BLE001 - a reader crash is a finding, not a failure
        logger.warning("Round trip of %s export could not be read back", format_id, exc_info=True)
        return [FidelityItem(severity="error", kind="roundtrip_mismatch", field="file", detail=type(exc).__name__)]
    priced = not (format_id == "gaeb_xml" and variant != "x84")
    return roundtrip_diff(
        structured,
        reimported,
        compare_prices=priced,
        compare_text=not (format_id == "gaeb_xml" and variant == "x84"),
        compare_units=not (format_id == "gaeb_xml" and variant == "x84"),
    )


async def record_report(
    session: AsyncSession,
    *,
    boq_id: uuid.UUID,
    report: FidelityReport,
    file_name: str = "",
    user_id: str | uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    is_check: bool = False,
    commit: bool = True,
) -> BOQExchangeReport | None:
    """Store ``report``; ``None`` (logged) when it could not be stored."""
    try:
        payload = report.to_dict()
        row = BOQExchangeReport(
            boq_id=boq_id,
            project_id=project_id,
            direction=report.direction,
            format_id=report.format_id[:30],
            variant=(report.variant or "")[:20],
            file_name=(file_name or "")[:255],
            roundtrip=report.roundtrip,
            is_check=is_check,
            summary={**payload["summary"], "items_truncated": payload["items_truncated"]},
            items=payload["items"],
            created_by=_as_uuid(user_id),
        )
        await ExchangeReportRepository(session).create(row)
        if commit:
            await session.commit()
        return row
    except Exception:  # noqa: BLE001 - the exchange itself already succeeded
        logger.warning("Exchange fidelity report for BOQ %s could not be stored", boq_id, exc_info=True)
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.debug("Rollback after a failed report write failed too", exc_info=True)
        return None


def _as_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def report_headers(row: BOQExchangeReport | None, report: FidelityReport) -> dict[str, str]:
    """Headers an export response carries so the editor can open the report."""
    counts = report.summary()["by_severity"]
    headers = {COUNTS_HEADER: f"{counts['error']},{counts['warning']},{counts['info']}"}
    if row is not None:
        headers[REPORT_HEADER] = str(row.id)
    return headers


def report_out(row: BOQExchangeReport, *, with_items: bool = True) -> dict[str, Any]:
    """A stored report as the API returns it."""
    out: dict[str, Any] = {
        "id": str(row.id),
        "boq_id": str(row.boq_id),
        "direction": row.direction,
        "format_id": row.format_id,
        "variant": row.variant or "",
        "file_name": row.file_name or "",
        "roundtrip": bool(row.roundtrip),
        "is_check": bool(row.is_check),
        "summary": dict(row.summary or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": str(row.created_by) if row.created_by else None,
    }
    if with_items:
        out["items"] = list(row.items or [])
    return out


def summary_out(row: Mapping[str, Any] | Any) -> dict[str, Any]:
    """One register row (no items) as the API returns it."""
    return {
        "id": str(row.id),
        "direction": row.direction,
        "format_id": row.format_id,
        "variant": row.variant or "",
        "file_name": row.file_name or "",
        "roundtrip": bool(row.roundtrip),
        "is_check": bool(row.is_check),
        "summary": dict(row.summary or {}),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": str(row.created_by) if row.created_by else None,
    }


async def with_exchange_fidelity(session: AsyncSession, boq_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
    """Add the critical items of the bill's latest exchanges to a validation payload.

    The ``boq_quality.exchange_fidelity`` rule reads ``data["exchange_fidelity"]``:
    for each direction and format, the newest real report (a check that wrote
    no file is left out) with its error items only.
    """
    try:
        latest = await ExchangeReportRepository(session).latest_per_format(boq_id)
    except Exception:  # noqa: BLE001 - validation must run without this extra
        logger.debug("Exchange reports could not be read for validation of BOQ %s", boq_id, exc_info=True)
        return data
    data["exchange_fidelity"] = [
        {
            "report_id": str(r.id),
            "direction": r.direction,
            "format_id": r.format_id,
            "variant": r.variant or "",
            "file_name": r.file_name or "",
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "items": [it for it in (r.items or []) if isinstance(it, dict) and it.get("severity") == "error"],
        }
        for r in latest
    ]
    return data
