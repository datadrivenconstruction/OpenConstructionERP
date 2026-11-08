# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Sensor evidence: readings of one device as a hashed CSV and a printable PDF, filed as project documents.

A neighbour's vibration or noise claim is answered with the readings of the device that
sat nearest. The export is cut from the stored series for one window, hashed with SHA-256
and filed in the documents module, so the file a lawyer receives is the file that was
exported. The claims evidence pack is assembled on demand from the activity log, so the
filing also writes one activity row that the pack lists with its integrity code.

:func:`file_project_document` is the shared helper: the pour record export of the maturity
module files its PDF through it into the ``Concrete / Pour records`` folder.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RegisterColumn,
    RegisterDocument,
    build_register_pdf,
    export_filename,
    short_digest,
)
from app.modules.documents.models import Document, DocumentFolder
from app.modules.documents.service import DocumentService
from app.modules.site_sensors.models import SensorAlert, SensorDevice
from app.modules.site_sensors.repository import SiteSensorsRepository

MAX_WINDOW = timedelta(days=366)
# Above this many raw readings the PDF prints hourly summaries; the CSV always holds every reading.
PDF_RAW_ROW_LIMIT = 1000
CSV_COLUMNS = ("time_utc", "source", "value", "min", "max", "count")
EVIDENCE_ENTITY = "sensor_evidence"
EVIDENCE_MODULE = "site_sensors"

FOLDER_CONCRETE = ("site_sensors.concrete", "Concrete", "site_sensors.folder.concrete")
FOLDER_POUR_RECORDS = ("site_sensors.concrete.pour_records", "Pour records", "site_sensors.folder.pour_records")
FOLDER_MONITORING = (
    "site_sensors.monitoring_evidence",
    "Monitoring evidence",
    "site_sensors.folder.monitoring_evidence",
)
# Each path is a chain of (code, name, name_key), parent first.
PATH_POUR_RECORDS = (FOLDER_CONCRETE, FOLDER_POUR_RECORDS)
PATH_MONITORING = (FOLDER_MONITORING,)


class EvidenceError(ValueError):
    """A request that cannot produce evidence; ``args[0]`` is a stable message key."""


@dataclass(frozen=True)
class FiledEvidence:
    """What one export filed."""

    csv_document: Document
    pdf_document: Document
    csv_sha256: str
    reading_count: int


def sha256_hex(data: bytes) -> str:
    """Lower-case hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def check_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """The window as aware UTC datetimes.

    Raises:
        EvidenceError: ``window_reversed`` when it ends before it starts, ``window_too_long`` past a year.
    """
    start, end = _utc(start), _utc(end)
    if end <= start:
        raise EvidenceError("window_reversed")
    if end - start > MAX_WINDOW:
        raise EvidenceError("window_too_long")
    return start, end


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _stamp(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value: float) -> str:
    return f"{value:.6g}"


def readings_csv(raw: list[tuple[datetime, float]], hourly: list[dict[str, Any]]) -> bytes:
    """Every stored reading of the window, hourly rows first for the part already folded.

    ``source`` is ``raw`` for a reading and ``hourly`` for a folded hour (value is the mean).
    """
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    rows: list[tuple[datetime, list[str]]] = [
        (h["hour"], [_stamp(h["hour"]), "hourly", _num(h["avg"]), _num(h["min"]), _num(h["max"]), str(h["n"])])
        for h in hourly
    ]
    rows += [(t, [_stamp(t), "raw", _num(v), "", "", "1"]) for t, v in raw]
    for _, line in sorted(rows, key=lambda r: (_utc(r[0]), r[1][1])):
        writer.writerow(line)
    return out.getvalue().encode("utf-8")


def summarise(raw: list[tuple[datetime, float]], hourly: list[dict[str, Any]]) -> dict[str, Any]:
    """Count, lowest, highest and mean over raw readings and folded hours (weighted by their count)."""
    count = len(raw) + sum(int(h["n"]) for h in hourly)
    if count == 0:
        return {"count": 0, "min": None, "max": None, "mean": None}
    total = sum(v for _, v in raw) + sum(h["avg"] * h["n"] for h in hourly)
    lows = [v for _, v in raw] + [h["min"] for h in hourly]
    highs = [v for _, v in raw] + [h["max"] for h in hourly]
    return {"count": count, "min": min(lows), "max": max(highs), "mean": total / count}


def hourly_summaries(raw: list[tuple[datetime, float]]) -> list[dict[str, Any]]:
    """Raw readings folded into hours: ``hour``, ``n``, ``min``, ``max``, ``avg``."""
    buckets: dict[datetime, list[float]] = {}
    for t, v in raw:
        buckets.setdefault(_utc(t).replace(minute=0, second=0, microsecond=0), []).append(v)
    return [
        {"hour": h, "n": len(vs), "min": min(vs), "max": max(vs), "avg": sum(vs) / len(vs)}
        for h, vs in sorted(buckets.items())
    ]


def _catalogue() -> Any:
    from app.core.document_forms_i18n import register_form_catalogue

    return register_form_catalogue("site_sensors_evidence")


def evidence_register(
    *,
    device: SensorDevice,
    limit: float | None,
    start: datetime,
    end: datetime,
    raw: list[tuple[datetime, float]],
    hourly: list[dict[str, Any]],
    exceedances: int,
    csv_digest: str,
    project: ProjectHeader,
    locale: str = "en",
    generated: str = "",
) -> RegisterDocument:
    """The printable evidence sheet; printed as a register so it carries page numbers and a footer."""
    cat = _catalogue()
    locale = cat.normalize(locale)
    stats = summarise(raw, hourly)
    summarised = len(raw) > PDF_RAW_ROW_LIMIT
    if summarised:
        shown = [
            (h["hour"], h["avg"], h["min"], h["max"], h["n"])
            for h in sorted(hourly + hourly_summaries(raw), key=lambda h: h["hour"])
        ]
    else:
        shown = [(h["hour"], h["avg"], h["min"], h["max"], h["n"]) for h in hourly] + [
            (t, v, None, None, 1) for t, v in raw
        ]
        shown.sort(key=lambda r: _utc(r[0]))
    rows = [
        [_stamp(t), _num(v), "" if lo is None else _num(lo), "" if hi is None else _num(hi), n]
        for t, v, lo, hi, n in shown
    ]
    unit = device.unit or ""

    def value(x: float | None) -> str:
        return EMPTY if x is None else f"{_num(x)} {unit}".strip()

    details = cat.register_details(locale, project, count=stats["count"])
    details += [
        (cat.tr(locale, "device"), f"{device.code} {device.name}".strip()),
        (cat.tr(locale, "sensor_kind"), device.kind.replace("_", " ")),
        (cat.tr(locale, "period_from"), _stamp(start)),
        (cat.tr(locale, "period_to"), _stamp(end)),
        (cat.tr(locale, "limit"), value(limit)),
        (cat.tr(locale, "peak"), value(stats["max"])),
        (cat.tr(locale, "lowest"), value(stats["min"])),
        (cat.tr(locale, "mean"), value(stats["mean"])),
        (cat.tr(locale, "over_limit"), str(exceedances)),
        (cat.tr(locale, "csv_digest"), short_digest(csv_digest, 64)),
    ]
    if summarised:
        details.append(("", cat.tr(locale, "summarised", total=stats["count"])))
    columns = [
        RegisterColumn(cat.tr(locale, "col_time"), weight=2.0, nobreak=True),
        RegisterColumn(f"{cat.tr(locale, 'col_value')} ({unit})" if unit else cat.tr(locale, "col_value")),
        RegisterColumn(cat.tr(locale, "col_min")),
        RegisterColumn(cat.tr(locale, "col_max")),
        RegisterColumn(cat.tr(locale, "col_count"), kind="count", weight=0.8),
    ]
    return RegisterDocument(
        title=cat.tr(locale, "register_title"),
        columns=columns,
        rows=rows,
        details=details,
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=cat.tr(locale, "empty_register"),
        **cat.furniture(locale, project),
    )


def evidence_stem(device: SensorDevice, start: datetime, end: datetime, locale: str = "en") -> str:
    """Base filename: ``sensor-evidence-NS-01-20261020-20261022``."""
    cat = _catalogue()
    word = cat.tr(cat.normalize(locale), "register_filename")
    return export_filename(f"{word}-{device.code}-{start:%Y%m%d}-{end:%Y%m%d}", "sensor-evidence", "").rstrip(".")


async def ensure_folder_path(
    session: AsyncSession, project_id: uuid.UUID, path: tuple[tuple[str, str, str], ...]
) -> DocumentFolder:
    """The last folder of ``path``, creating the chain when the project lacks it."""
    parent: DocumentFolder | None = None
    for order, (code, name, name_key) in enumerate(path):
        row = (
            await session.execute(
                select(DocumentFolder).where(DocumentFolder.project_id == project_id, DocumentFolder.code == code)
            )
        ).scalar_one_or_none()
        if row is None:
            row = DocumentFolder(
                project_id=project_id,
                code=code,
                name=name,
                name_key=name_key,
                source="manual",
                sort_order=order,
                parent_id=parent.id if parent is not None else None,
            )
            session.add(row)
            await session.flush()
        parent = row
    assert parent is not None
    return parent


async def file_project_document(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    user_id: str,
    filename: str,
    content: bytes,
    folder_path: tuple[tuple[str, str, str], ...] = PATH_MONITORING,
    description: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    category: str = "other",
) -> Document:
    """File bytes as a project document in a folder (created on first use).

    The pour record export calls this with ``folder_path=PATH_POUR_RECORDS``.
    """
    folder = await ensure_folder_path(session, project_id, folder_path)
    upload = UploadFile(file=io.BytesIO(content), filename=filename)
    document = await DocumentService(session).upload_document(project_id, upload, category, user_id)
    document.folder_id = folder.id
    document.description = description
    document.tags = list(tags or [])
    document.metadata_ = dict(metadata or {})
    await session.flush()
    return document


async def file_pour_record(
    session: AsyncSession, *, project_id: uuid.UUID, strip_id: uuid.UUID, user_id: str, filename: str, content: bytes
) -> Document:
    """File a pour record PDF in ``Concrete / Pour records``; a repeat export of the same strip reuses it."""
    folder = await ensure_folder_path(session, project_id, PATH_POUR_RECORDS)
    existing = (
        await session.execute(
            select(Document).where(
                Document.project_id == project_id, Document.folder_id == folder.id, Document.name == filename
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    return await file_project_document(
        session,
        project_id=project_id,
        user_id=user_id,
        filename=filename,
        content=content,
        folder_path=PATH_POUR_RECORDS,
        tags=["pour-record"],
        metadata={"format": "pdf", "strip_id": str(strip_id), "sha256": sha256_hex(content)},
    )


async def exceedance_count(session: AsyncSession, device_id: uuid.UUID, start: datetime, end: datetime) -> int:
    """Limit exceedance alerts the device raised in the window."""
    rows = await session.execute(
        select(SensorAlert.id).where(
            SensorAlert.device_id == device_id,
            SensorAlert.kind == "exceedance",
            SensorAlert.raised_at >= start,
            SensorAlert.raised_at <= end,
        )
    )
    return len(rows.all())


async def file_device_evidence(
    session: AsyncSession,
    device: SensorDevice,
    start: datetime,
    end: datetime,
    *,
    user_id: str,
    locale: str = "en",
    claim_ref: str = "",
    alert_id: uuid.UUID | None = None,
    generated: str = "",
    project: ProjectHeader | None = None,
    limit: float | None = None,
) -> FiledEvidence:
    """Cut the window from the stored series, hash it, file CSV and PDF, log it for the claims pack.

    Raises:
        EvidenceError: A bad window, or ``no_readings`` when the window holds nothing to file.
    """
    start, end = check_window(start, end)
    repo = SiteSensorsRepository(session)
    raw = await repo.raw(device.id, start, end)
    hourly = await repo.hourly(device.id, start, end)
    if not raw and not hourly:
        raise EvidenceError("no_readings")
    csv_bytes = readings_csv(raw, hourly)
    digest = sha256_hex(csv_bytes)
    project = project or ProjectHeader()
    document = evidence_register(
        device=device,
        limit=limit,
        start=start,
        end=end,
        raw=raw,
        hourly=hourly,
        exceedances=await exceedance_count(session, device.id, start, end),
        csv_digest=digest,
        project=project,
        locale=locale,
        generated=generated,
    )
    pdf_bytes = build_register_pdf(document)
    stem = evidence_stem(device, start, end, locale)
    count = summarise(raw, hourly)["count"]
    meta = {
        "source": EVIDENCE_MODULE,
        "device_id": str(device.id),
        "device_code": device.code,
        "from": _stamp(start),
        "to": _stamp(end),
        "readings": count,
        "csv_sha256": digest,
        "claim_ref": claim_ref,
        "alert_id": str(alert_id) if alert_id else None,
    }
    note = f"{device.code} {_stamp(start)} - {_stamp(end)}, SHA-256 {digest}"
    tags = ["sensor-evidence", device.kind]
    csv_doc = await file_project_document(
        session,
        project_id=device.project_id,
        user_id=user_id,
        filename=f"{stem}.csv",
        content=csv_bytes,
        description=note,
        tags=tags,
        metadata={**meta, "format": "csv", "sha256": digest},
    )
    pdf_doc = await file_project_document(
        session,
        project_id=device.project_id,
        user_id=user_id,
        filename=f"{stem}.pdf",
        content=pdf_bytes,
        description=note,
        tags=tags,
        metadata={**meta, "format": "pdf", "sha256": sha256_hex(pdf_bytes)},
    )
    await log_activity(
        session,
        actor_id=user_id or None,
        entity_type=EVIDENCE_ENTITY,
        entity_id=csv_doc.id,
        action="evidence_filed",
        reason=f"{claim_ref} SHA-256 {digest}".strip(),
        metadata={**meta, "csv_document_id": str(csv_doc.id), "pdf_document_id": str(pdf_doc.id)},
        module=EVIDENCE_MODULE,
        parent_entity_type="project",
        parent_entity_id=device.project_id,
    )
    if alert_id is not None:
        alert = await session.get(SensorAlert, alert_id)
        if alert is not None and alert.device_id == device.id:
            alert.note = (alert.note + "\n" if alert.note else "") + f"SHA-256 {digest[:16]}"
    await session.flush()
    return FiledEvidence(csv_doc, pdf_doc, digest, count)


async def evidence_rows(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Filed evidence of a project for the validation payload: one row per export."""
    from app.core.audit_log import ActivityLog

    rows = (
        await session.execute(
            select(ActivityLog).where(
                ActivityLog.entity_type == EVIDENCE_ENTITY,
                ActivityLog.parent_entity_id == str(project_id),
            )
        )
    ).scalars()
    out = []
    for r in rows:
        meta = r.metadata_ or {}
        out.append(
            {
                "id": str(r.entity_id),
                "device": meta.get("device_code", ""),
                "sha256": meta.get("csv_sha256", ""),
                "readings": meta.get("readings", 0),
                "filed": bool(meta.get("csv_document_id") and meta.get("pdf_document_id")),
            }
        )
    return out


async def bim_link_rows(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Devices and strikes that name a BIM element, for the validation payload."""
    from app.modules.site_sensors.models import FormworkStrip

    out: list[dict[str, Any]] = []
    for model, label in ((SensorDevice, "code"), (FormworkStrip, "element")):
        stmt = select(model).where(model.project_id == project_id, model.bim_element_id.is_not(None))
        for r in (await session.execute(stmt)).scalars():
            out.append(
                {
                    "id": str(r.id),
                    "label": getattr(r, label, ""),
                    "model_id": str(r.bim_model_id) if r.bim_model_id else None,
                    "element_id": str(r.bim_element_id),
                }
            )
    return out


async def strike_status_by_element(session: AsyncSession, project_id: uuid.UUID) -> dict[str, str]:
    """BIM element id to strike status (``planned``, ``released``, ``struck``), the latest strip per element.

    Feeds a viewer overlay; the viewer's colour modes are a closed set, so the overlay itself is not wired.
    """
    from app.modules.site_sensors.models import FormworkStrip

    stmt = (
        select(FormworkStrip)
        .where(FormworkStrip.project_id == project_id, FormworkStrip.bim_element_id.is_not(None))
        .order_by(FormworkStrip.created_at)
    )
    return {str(s.bim_element_id): s.status for s in (await session.execute(stmt)).scalars()}
