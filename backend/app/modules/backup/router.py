"""Backup & Restore API.

Endpoints:
    POST /export    -- Download a ZIP backup of all user data
    POST /restore   -- Upload and restore from a backup ZIP
    POST /validate  -- Validate a backup ZIP without importing
"""

import hashlib
import io
import json
import logging
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import CurrentUserId

router = APIRouter()
logger = logging.getLogger(__name__)

# Backup format version — increment when schema changes
BACKUP_FORMAT_VERSION = "1.0.0"

# Application identifier embedded in every backup manifest
APP_ID = "openestimate"

# Maximum upload size: 100 MB
MAX_BACKUP_SIZE = 100 * 1024 * 1024


# ── Response schemas ──────────────────────────────────────────────────────────


class RestoreResponse(BaseModel):
    """Result of a restore operation."""

    status: str
    mode: str
    imported: dict[str, int]
    skipped: dict[str, int]
    warnings: list[str]


class ValidateResponse(BaseModel):
    """Result of a backup validation check."""

    valid: bool
    format_version: str
    created_at: str
    record_counts: dict[str, int]
    warnings: list[str]
    checksum: str


# ── Table registry ────────────────────────────────────────────────────────────
# Each entry: (backup_key, table_name, module_path, class_name)
# Listed in FK dependency order so that restore inserts parents before children.

_BACKUP_TABLE_DEFS: list[tuple[str, str, str, str]] = [
    ("users", "oe_users_user", "app.modules.users.models", "User"),
    ("projects", "oe_projects_project", "app.modules.projects.models", "Project"),
    ("boqs", "oe_boq_boq", "app.modules.boq.models", "BOQ"),
    ("positions", "oe_boq_position", "app.modules.boq.models", "Position"),
    ("markups", "oe_boq_markup", "app.modules.boq.models", "BOQMarkup"),
    ("schedules", "oe_schedule_schedule", "app.modules.schedule.models", "Schedule"),
    ("activities", "oe_schedule_activity", "app.modules.schedule.models", "Activity"),
    ("budget_lines", "oe_costmodel_budget_line", "app.modules.costmodel.models", "BudgetLine"),
    ("cash_flows", "oe_costmodel_cash_flow", "app.modules.costmodel.models", "CashFlow"),
    ("cost_snapshots", "oe_costmodel_snapshot", "app.modules.costmodel.models", "CostSnapshot"),
    ("risks", "oe_risk_register", "app.modules.risk.models", "RiskItem"),
    ("change_orders", "oe_changeorders_order", "app.modules.changeorders.models", "ChangeOrder"),
    (
        "change_order_items",
        "oe_changeorders_item",
        "app.modules.changeorders.models",
        "ChangeOrderItem",
    ),
    ("documents", "oe_documents_document", "app.modules.documents.models", "Document"),
    ("assemblies", "oe_assemblies_assembly", "app.modules.assemblies.models", "Assembly"),
    (
        "assembly_components",
        "oe_assemblies_component",
        "app.modules.assemblies.models",
        "Component",
    ),
    ("tender_packages", "oe_tendering_package", "app.modules.tendering.models", "TenderPackage"),
    ("tender_bids", "oe_tendering_bid", "app.modules.tendering.models", "TenderBid"),
    ("ai_settings", "oe_ai_settings", "app.modules.ai.models", "AISettings"),
]


def _get_model_class(module_path: str, class_name: str) -> type:
    """Lazily import a model class to avoid circular imports."""
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def _get_backup_tables() -> list[tuple[str, str, type]]:
    """Return resolved (backup_key, table_name, ModelClass) tuples."""
    result: list[tuple[str, str, type]] = []
    for backup_key, table_name, module_path, class_name in _BACKUP_TABLE_DEFS:
        try:
            model_cls = _get_model_class(module_path, class_name)
            result.append((backup_key, table_name, model_cls))
        except Exception:
            logger.warning("Skipping backup table %s: model import failed", backup_key)
    return result


# ── Serialisation helpers ─────────────────────────────────────────────────────


def serialize_row(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model instance to a JSON-safe dict.

    Handles UUID -> str, datetime -> ISO string, and preserves JSON columns as-is.
    Uses ``col.key`` (Python attribute name) rather than ``col.name`` (DB column name)
    so that mapped columns like ``metadata_`` (mapped to DB column ``metadata``) are
    serialised under the attribute key the ORM uses.
    """
    d: dict[str, Any] = {}
    for col in row.__table__.columns:
        val = getattr(row, col.key)
        if isinstance(val, uuid.UUID):
            val = str(val)
        elif isinstance(val, datetime):
            val = val.isoformat()
        d[col.key] = val
    return d


def _parse_date(val: Any) -> Any:
    """Parse ISO-format date strings back to Python datetime objects.

    Backup export serialises datetime columns as ISO strings, but SQLite
    DateTime columns require actual datetime objects on insert.
    """
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return val
    return val


def deserialize_row(model_class: type, data: dict[str, Any]) -> Any:
    """Create a model instance from a dict, converting UUID strings and dates back.

    Checks each column's type: if it uses the ``GUID`` custom type (which wraps
    UUID values as String(36)), string values are converted back to ``uuid.UUID``.
    DateTime columns are parsed from ISO strings back to Python datetime objects.
    """
    from sqlalchemy import DateTime

    from app.database import GUID

    kwargs: dict[str, Any] = {}
    for col in model_class.__table__.columns:
        if col.key not in data:
            continue
        val = data[col.key]
        col_type = col.type
        # Convert UUID strings back to uuid.UUID for GUID columns
        if isinstance(col_type, GUID) and val is not None and isinstance(val, str):
            try:
                val = uuid.UUID(val)
            except ValueError:
                pass  # leave as-is if not a valid UUID string
        # Convert ISO date strings back to datetime for DateTime columns
        elif isinstance(col_type, DateTime) and val is not None and isinstance(val, str):
            val = _parse_date(val)
        kwargs[col.key] = val
    return model_class(**kwargs)


# ── ZIP helpers ───────────────────────────────────────────────────────────────


def create_backup_zip(data: dict[str, list[dict]], manifest: dict[str, Any]) -> bytes:
    """Build an in-memory ZIP with manifest.json + per-table JSON files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)
        zf.writestr("manifest.json", manifest_json)
        for key, records in data.items():
            payload = json.dumps(records, indent=2, ensure_ascii=False, default=str)
            zf.writestr(f"{key}.json", payload)
    return buf.getvalue()


def parse_backup_zip(raw: bytes) -> tuple[dict[str, Any], dict[str, list[dict]]]:
    """Parse a backup ZIP, returning (manifest, data_by_key).

    Raises:
        HTTPException 400 on invalid ZIP or missing manifest.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP archive")

    if "manifest.json" not in zf.namelist():
        raise HTTPException(status_code=400, detail="ZIP is missing manifest.json")

    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (json.JSONDecodeError, KeyError):
        raise HTTPException(status_code=400, detail="manifest.json is not valid JSON")

    if manifest.get("app") != APP_ID:
        raise HTTPException(
            status_code=400,
            detail=f"Not an OpenEstimate backup (app={manifest.get('app')})",
        )

    data: dict[str, list[dict]] = {}
    for name in zf.namelist():
        if name == "manifest.json":
            continue
        if name.endswith(".json"):
            key = name.removesuffix(".json")
            try:
                data[key] = json.loads(zf.read(name))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON file in backup: %s", name)

    return manifest, data


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/export/", tags=["Backup"])
async def export_backup(user_id: CurrentUserId) -> StreamingResponse:
    """Export all user data as a downloadable ZIP backup.

    The ZIP contains:
    - ``manifest.json`` — backup metadata (version, timestamp, checksums)
    - One ``.json`` file per data table with all records serialised
    """
    from sqlalchemy import select

    from app.database import async_session_factory

    tables = _get_backup_tables()
    data: dict[str, list[dict]] = {}
    record_counts: dict[str, int] = {}

    async with async_session_factory() as session:
        for backup_key, _table_name, model_cls in tables:
            try:
                rows = (await session.execute(select(model_cls))).scalars().all()
                serialised = [serialize_row(r) for r in rows]
                data[backup_key] = serialised
                record_counts[backup_key] = len(serialised)
            except Exception:
                logger.warning("Failed to export table %s (skipping)", backup_key)
                data[backup_key] = []
                record_counts[backup_key] = 0

    now = datetime.now(UTC)
    manifest: dict[str, Any] = {
        "app": APP_ID,
        "format_version": BACKUP_FORMAT_VERSION,
        "created_at": now.isoformat(),
        "created_by": user_id,
        "record_counts": record_counts,
        "total_records": sum(record_counts.values()),
    }

    zip_bytes = create_backup_zip(data, manifest)

    # Add checksum to manifest (for validation on restore)
    manifest["checksum"] = hashlib.sha256(zip_bytes).hexdigest()

    # Rebuild ZIP with checksum included in manifest
    zip_bytes = create_backup_zip(data, manifest)

    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"openestimate_backup_{timestamp}.zip"

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore/", response_model=RestoreResponse, tags=["Backup"])
async def restore_backup(
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    mode: str = "replace",
) -> RestoreResponse:
    """Upload and restore from a backup ZIP.

    Args:
        file: ZIP backup file (multipart/form-data).
        mode: ``replace`` (default) deletes all existing data first, then inserts.
              ``merge`` skips records whose UUID already exists, inserts new ones.

    Returns:
        Counts of imported and skipped records per table.
    """
    if mode not in ("replace", "merge"):
        raise HTTPException(status_code=400, detail="mode must be 'replace' or 'merge'")

    raw = await file.read()
    if len(raw) > MAX_BACKUP_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Backup file exceeds maximum size ({MAX_BACKUP_SIZE // (1024 * 1024)} MB)",
        )

    manifest, data = parse_backup_zip(raw)
    tables = _get_backup_tables()

    imported: dict[str, int] = {}
    skipped: dict[str, int] = {}
    warnings: list[str] = []

    from sqlalchemy import delete, select

    from app.database import async_session_factory

    async with async_session_factory() as session:
        try:
            if mode == "replace":
                # Delete in reverse FK order to avoid constraint violations
                for backup_key, _table_name, model_cls in reversed(tables):
                    try:
                        await session.execute(delete(model_cls))
                    except Exception as exc:
                        warnings.append(f"Failed to clear {backup_key}: {exc}")

            # Insert in FK dependency order
            for backup_key, _table_name, model_cls in tables:
                records = data.get(backup_key, [])
                if not records:
                    imported[backup_key] = 0
                    skipped[backup_key] = 0
                    continue

                count_imported = 0
                count_skipped = 0

                for record in records:
                    if mode == "merge":
                        # Check if record with this UUID already exists
                        record_id = record.get("id")
                        if record_id:
                            try:
                                existing = (
                                    await session.execute(
                                        select(model_cls).where(
                                            model_cls.id == uuid.UUID(record_id)
                                            if isinstance(record_id, str)
                                            else model_cls.id == record_id
                                        )
                                    )
                                ).scalar_one_or_none()
                                if existing is not None:
                                    count_skipped += 1
                                    continue
                            except Exception:
                                pass  # If check fails, attempt insert anyway

                    try:
                        obj = deserialize_row(model_cls, record)
                        session.add(obj)
                        count_imported += 1
                    except Exception as exc:
                        count_skipped += 1
                        logger.warning("Skipped record in %s: %s", backup_key, str(exc)[:100])

                imported[backup_key] = count_imported
                skipped[backup_key] = count_skipped

                # Flush after each table to surface FK violations early
                try:
                    await session.flush()
                except Exception as exc:
                    warnings.append(f"Flush error after {backup_key}: {str(exc)[:200]}")
                    # Attempt to continue — some tables may have partial success
                    await session.rollback()
                    # Re-open transaction for remaining tables
                    warnings.append(f"Rolled back {backup_key} due to error; subsequent tables may also be affected")

            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Restore failed: {str(exc)[:300]}",
            )

    total_imported = sum(imported.values())
    total_skipped = sum(skipped.values())

    # Determine actual restore status based on results
    if total_imported == 0 and total_skipped > 0:
        restore_status = "failed"
    elif total_skipped > 0 or warnings:
        restore_status = "partial"
    else:
        restore_status = "success"

    logger.info(
        "Backup restored: mode=%s status=%s imported=%d skipped=%d warnings=%d",
        mode,
        restore_status,
        total_imported,
        total_skipped,
        len(warnings),
    )

    return RestoreResponse(
        status=restore_status,
        mode=mode,
        imported=imported,
        skipped=skipped,
        warnings=warnings,
    )


@router.post("/validate/", response_model=ValidateResponse, tags=["Backup"])
async def validate_backup(
    user_id: CurrentUserId,
    file: UploadFile = File(...),
) -> ValidateResponse:
    """Validate a backup ZIP without importing any data.

    Parses the ZIP, checks the manifest, counts records per table,
    and reports any structural warnings (missing tables, unknown keys, etc.).
    """
    raw = await file.read()
    if len(raw) > MAX_BACKUP_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Backup file exceeds maximum size ({MAX_BACKUP_SIZE // (1024 * 1024)} MB)",
        )

    manifest, data = parse_backup_zip(raw)
    warnings: list[str] = []

    # Check format version compatibility
    backup_version = manifest.get("format_version", "unknown")
    if backup_version != BACKUP_FORMAT_VERSION:
        warnings.append(f"Format version mismatch: backup={backup_version}, current={BACKUP_FORMAT_VERSION}")

    # Build set of known backup keys
    known_keys = {key for key, _, _, _ in _BACKUP_TABLE_DEFS}

    # Check for unknown data files
    for key in data:
        if key not in known_keys:
            warnings.append(f"Unknown data key in backup: '{key}' (will be ignored on restore)")

    # Check for missing tables
    for key in known_keys:
        if key not in data:
            warnings.append(f"Expected data key '{key}' not found in backup")

    # Count records
    record_counts: dict[str, int] = {}
    for key, records in data.items():
        if not isinstance(records, list):
            warnings.append(f"Data key '{key}' is not a list (type={type(records).__name__})")
            record_counts[key] = 0
        else:
            record_counts[key] = len(records)

    checksum = hashlib.sha256(raw).hexdigest()

    return ValidateResponse(
        valid=len(warnings) == 0 or all("not found" not in w.lower() for w in warnings),
        format_version=backup_version,
        created_at=manifest.get("created_at", "unknown"),
        record_counts=record_counts,
        warnings=warnings,
        checksum=checksum,
    )
