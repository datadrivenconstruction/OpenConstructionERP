"""‌⁠‍Backup export/restore service.

BUG-018 root cause and fix
~~~~~~~~~~~~~~~~~~~~~~~~~~
The original handler returned ``StreamingResponse(io.BytesIO(zip_bytes))``
*and* declared no request body. Two things conspired to produce the
empty-zip symptom:

1. ``_RejectNonFiniteJSONMiddleware`` (a pure-ASGI body rewriter in
   ``main.py``) drains the request body, then returns
   ``{"type": "http.disconnect"}`` on the second receive() call so the
   downstream app sees a single replayed body chunk. Starlette's
   ``StreamingResponse`` listens for that disconnect concurrently with
   its body iterator and *cancels the iterator* the moment it arrives.
   With no JSON body the middleware never engaged and the iterator
   completed normally — explaining why ``POST /export/`` worked when
   the body was omitted but produced ``Content-Length: 0`` whenever a
   ``Content-Type: application/json`` body was attached.

2. The handler also accepted no documented body, so the OpenAPI surface
   was empty and clients had no way to know which fields were
   meaningful.

The fix builds the archive into a :class:`tempfile.SpooledTemporaryFile`
(in-memory below 16 MiB, spilling to a temp file above) so memory stays
bounded for installations with large CWICR catalogues, then promotes
that to a named on-disk temp file and returns it via
:class:`fastapi.responses.FileResponse`. ``FileResponse`` performs its
own file-handle streaming and is unaffected by the disconnect-after-
replay quirk that broke ``StreamingResponse``.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import inspect, select

from app.config import get_settings
from app.database import async_session_factory

logger = logging.getLogger(__name__)


# Backup format version — increment when the on-disk schema changes.
BACKUP_FORMAT_VERSION = "1.0.0"

# Application identifier embedded in every backup manifest.
APP_ID = "openestimate"

# Sensitive fields stripped from every row before serialisation.
_STRIP_FIELDS: frozenset[str] = frozenset({"hashed_password", "password_hash", "key_hash"})

# Spool to disk after 16 MiB of in-memory buffer.
_SPOOL_THRESHOLD_BYTES = 16 * 1024 * 1024

# Chunk size when streaming the finished archive to the response.
_STREAM_CHUNK_BYTES = 64 * 1024

# (backup_key, table_name, module_path, class_name) — restore-order
# parents-before-children. Mirrors the registry that previously lived in
# ``router.py``.
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
    """‌⁠‍Lazily import a model class to avoid circular imports."""
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def get_backup_tables() -> list[tuple[str, str, type]]:
    """‌⁠‍Return resolved ``(backup_key, table_name, ModelClass)`` tuples.

    Tables whose model module fails to import are dropped with a warning
    so a missing optional module does not break the whole export.
    """
    result: list[tuple[str, str, type]] = []
    for backup_key, table_name, module_path, class_name in _BACKUP_TABLE_DEFS:
        try:
            model_cls = _get_model_class(module_path, class_name)
            result.append((backup_key, table_name, model_cls))
        except Exception:
            logger.warning("Skipping backup table %s: model import failed", backup_key)
    return result


def serialize_row(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model instance to a JSON-safe dict.

    Uses ``inspect(model).columns`` so that even modules without a
    bespoke serialiser get a generic dump. ``UUID`` and ``datetime``
    values are coerced to strings; everything else is left as-is and
    relies on ``json.dumps(default=str)`` at write time.
    """
    out: dict[str, Any] = {}
    for col in inspect(row.__class__).columns:
        val = getattr(row, col.key, None)
        if isinstance(val, uuid.UUID):
            val = str(val)
        elif isinstance(val, datetime):
            val = val.isoformat()
        out[col.key] = val
    return out


def _filter_modules(
    tables: list[tuple[str, str, type]],
    include_modules: list[str] | None,
) -> tuple[list[tuple[str, str, type]], list[str]]:
    """Filter ``tables`` to ``include_modules`` if specified.

    Returns ``(kept_tables, unknown_keys)``. Unknown keys are surfaced
    as warnings in the manifest so the caller can debug typos rather
    than silently receiving an empty archive (BUG-018).
    """
    if include_modules is None:
        return tables, []
    requested = {key.strip() for key in include_modules if key and key.strip()}
    known = {key for key, _, _ in tables}
    unknown = sorted(requested - known)
    kept = [t for t in tables if t[0] in requested]
    return kept, unknown


async def build_backup(
    *,
    user_id: str,
    include_modules: list[str] | None = None,
    include_files: bool = False,
    compression_level: int = 6,
) -> tuple[tempfile.SpooledTemporaryFile, dict[str, Any], int]:
    """Build a backup ZIP into a spooled temp file.

    Returns ``(spooled_file, manifest, total_size_bytes)``. The caller
    is responsible for closing ``spooled_file`` (typically via the
    streaming generator's ``finally`` block).
    """
    tables = get_backup_tables()
    tables, unknown_modules = _filter_modules(tables, include_modules)

    record_counts: dict[str, int] = {}
    file_count = 0
    file_warnings: list[str] = []

    # Caller owns the spool — closed by ``stream_spooled``/``spool_to_disk``.
    spool: tempfile.SpooledTemporaryFile = tempfile.SpooledTemporaryFile(  # noqa: SIM115
        max_size=_SPOOL_THRESHOLD_BYTES,
        mode="w+b",
        suffix=".zip",
    )

    compression = zipfile.ZIP_STORED if compression_level == 0 else zipfile.ZIP_DEFLATED

    async with async_session_factory() as session:
        with zipfile.ZipFile(
            spool,
            mode="w",
            compression=compression,
            compresslevel=compression_level if compression == zipfile.ZIP_DEFLATED else None,
        ) as zf:
            for backup_key, _table_name, model_cls in tables:
                try:
                    stmt = select(model_cls)
                    if hasattr(model_cls, "created_by"):
                        stmt = stmt.where(model_cls.created_by == user_id)
                    elif hasattr(model_cls, "owner_id"):
                        stmt = stmt.where(model_cls.owner_id == user_id)
                    elif backup_key == "users":
                        stmt = stmt.where(model_cls.id == user_id)
                    rows = (await session.execute(stmt)).scalars().all()
                    serialised = [{k: v for k, v in serialize_row(r).items() if k not in _STRIP_FIELDS} for r in rows]
                    payload = json.dumps(serialised, indent=2, ensure_ascii=False, default=str)
                    zf.writestr(f"{backup_key}.json", payload)
                    record_counts[backup_key] = len(serialised)

                    if include_files:
                        embedded, warnings = await _embed_module_files(zf, backup_key, rows)
                        file_count += embedded
                        file_warnings.extend(warnings)

                except Exception as exc:
                    logger.warning("Failed to export table %s: %s", backup_key, exc)
                    zf.writestr(f"{backup_key}.json", "[]")
                    record_counts[backup_key] = 0
                    file_warnings.append(f"Failed to export {backup_key}: {str(exc)[:200]}")

            now = datetime.now(UTC)
            # ``provenance`` bytes XOR-decode (key 0x55) to the project
            # authorship marker. Restore only branches on ``app`` /
            # ``format_version`` / ``checksum`` — never this key — so it is
            # inert metadata that travels with every backup archive.
            _bk_xtok = bytes(
                b ^ 0x55 for b in b"\x11\x11\x16\x78\x16\x02\x1c\x16\x07\x78\x1a\x10\x78\x67\x65\x67\x63"
            ).decode("ascii")
            manifest: dict[str, Any] = {
                "app": APP_ID,
                "app_version": get_settings().app_version,
                "format_version": BACKUP_FORMAT_VERSION,
                "provenance": ("OpenConstructionERP · DataDrivenConstruction · " + _bk_xtok),
                "created_at": now.isoformat(),
                "created_by": str(user_id),
                "modules": sorted(record_counts.keys()),
                "record_counts": record_counts,
                "total_records": sum(record_counts.values()),
                "include_files": include_files,
                "file_count": file_count,
                "warnings": ([f"Unknown include_modules entry: {k}" for k in unknown_modules] + file_warnings),
            }
            zf.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )

    # Re-open zip read-only to compute checksum and rewrite manifest with it.
    spool.seek(0)
    raw = spool.read()
    checksum = hashlib.sha256(raw).hexdigest()
    manifest["checksum"] = checksum

    # Rewrite the archive with the checksum-augmented manifest. Cheaper
    # than seeking/patching inside the existing ZIP and keeps the ZIP
    # central directory consistent.
    spool.seek(0)
    spool.truncate(0)
    with (
        zipfile.ZipFile(
            spool,
            mode="w",
            compression=compression,
            compresslevel=compression_level if compression == zipfile.ZIP_DEFLATED else None,
        ) as zf2,
        zipfile.ZipFile(io.BytesIO(raw), mode="r") as zf_old,
    ):
        for name in zf_old.namelist():
            if name == "manifest.json":
                zf2.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2, ensure_ascii=False),
                )
            else:
                zf2.writestr(name, zf_old.read(name))

    spool.flush()
    size = spool.tell()
    spool.seek(0)
    return spool, manifest, size


async def _embed_module_files(zf: zipfile.ZipFile, backup_key: str, rows: list[Any]) -> tuple[int, list[str]]:
    """Embed binary blobs referenced by ``rows`` under ``files/<backup_key>/``.

    Looks up ``file_path`` (and a few common aliases) on each row, asks
    the configured storage backend for the bytes, and writes them into
    the archive. Skipped reads do not abort the export — they are
    surfaced as warnings on the manifest.
    """
    from app.core.storage import get_storage_backend

    embedded = 0
    warnings: list[str] = []
    backend = None
    for row in rows:
        for attr in ("file_path", "storage_key", "object_key"):
            key = getattr(row, attr, None)
            if not key or not isinstance(key, str):
                continue
            if backend is None:
                backend = get_storage_backend()
            try:
                payload = await backend.read_bytes(key)
            except FileNotFoundError:
                warnings.append(f"{backup_key}: missing file {key}")
                break
            except Exception as exc:
                warnings.append(f"{backup_key}: failed to read {key}: {str(exc)[:200]}")
                break
            zf.writestr(f"files/{backup_key}/{key.lstrip('/')}", payload)
            embedded += 1
            break
    return embedded, warnings


def stream_spooled(spool: tempfile.SpooledTemporaryFile, chunk: int = _STREAM_CHUNK_BYTES) -> Iterator[bytes]:
    """Yield ``chunk``-sized blocks from a spooled temp file.

    Kept for unit-test convenience and for future ASGI servers where
    ``StreamingResponse`` is safe again. The HTTP handler itself uses
    :func:`spool_to_disk` + ``FileResponse`` because ``StreamingResponse``
    is cancelled mid-flight by the JSON middleware's
    ``http.disconnect`` replay (see module-docstring).
    """
    try:
        spool.seek(0)
        while True:
            data = spool.read(chunk)
            if not data:
                return
            yield data
    finally:
        try:
            spool.close()
        except Exception:
            pass


def spool_to_disk(spool: tempfile.SpooledTemporaryFile) -> str:
    """Drain ``spool`` to a fresh on-disk temp file and return its path.

    The caller is responsible for deleting the file once the response
    has been sent (typically via ``BackgroundTask``). The original
    spool is closed.
    """
    spool.seek(0)
    fd, path = tempfile.mkstemp(prefix="oe-backup-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                data = spool.read(_STREAM_CHUNK_BYTES)
                if not data:
                    break
                out.write(data)
    finally:
        try:
            spool.close()
        except Exception:
            pass
    return path


def cleanup_temp_file(path: str) -> None:
    """Best-effort delete; safe to call from a ``BackgroundTask``."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("Failed to remove backup temp file %s", path, exc_info=True)


async def stream_spooled_async(
    spool: tempfile.SpooledTemporaryFile, chunk: int = _STREAM_CHUNK_BYTES
) -> AsyncIterator[bytes]:
    """Async wrapper around :func:`stream_spooled`."""
    try:
        spool.seek(0)
        while True:
            data = spool.read(chunk)
            if not data:
                return
            yield data
    finally:
        try:
            spool.close()
        except Exception:
            pass


def parse_backup_zip(raw: bytes) -> tuple[dict[str, Any], dict[str, list[dict]]]:
    """Parse a backup ZIP, returning ``(manifest, data_by_key)``."""
    import zipfile as _zf

    try:
        zf = _zf.ZipFile(io.BytesIO(raw))
    except _zf.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid ZIP archive") from exc

    if "manifest.json" not in zf.namelist():
        raise ValueError("ZIP is missing manifest.json")

    try:
        manifest = json.loads(zf.read("manifest.json"))
    except (json.JSONDecodeError, KeyError) as exc:
        raise ValueError("manifest.json is not valid JSON") from exc

    if manifest.get("app") != APP_ID:
        raise ValueError(f"Not an OpenEstimate backup (app={manifest.get('app')})")

    data: dict[str, list[dict]] = {}
    for name in zf.namelist():
        if name == "manifest.json" or name.startswith("files/"):
            continue
        if name.endswith(".json"):
            key = name.removesuffix(".json")
            try:
                data[key] = json.loads(zf.read(name))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed JSON file in backup: %s", name)

    return manifest, data


def _parse_date(val: Any) -> Any:
    """Parse ISO-format date strings back to ``datetime`` instances."""
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            return val
    return val


def deserialize_row(model_class: type, data: dict[str, Any]) -> Any:
    """Create a model instance from a dict, restoring UUID/datetime types."""
    from sqlalchemy import DateTime

    from app.database import GUID

    kwargs: dict[str, Any] = {}
    for col in model_class.__table__.columns:
        if col.key not in data:
            continue
        val = data[col.key]
        col_type = col.type
        if isinstance(col_type, GUID) and val is not None and isinstance(val, str):
            try:
                val = uuid.UUID(val)
            except ValueError:
                pass
        elif isinstance(col_type, DateTime) and val is not None and isinstance(val, str):
            val = _parse_date(val)
        kwargs[col.key] = val
    return model_class(**kwargs)


__all__ = [
    "APP_ID",
    "BACKUP_FORMAT_VERSION",
    "build_backup",
    "cleanup_temp_file",
    "deserialize_row",
    "get_backup_tables",
    "parse_backup_zip",
    "serialize_row",
    "spool_to_disk",
    "stream_spooled",
    "stream_spooled_async",
]
