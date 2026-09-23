# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Backup export/restore service.

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
   completed normally - explaining why ``POST /export/`` worked when
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

import asyncio
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, inspect, or_, select

from app.config import get_settings
from app.database import async_session_factory
from app.modules.backup.graph_scope import derive_backup_graph

logger = logging.getLogger(__name__)


# Backup format version - increment when the on-disk schema changes.
BACKUP_FORMAT_VERSION = "1.0.0"

# Application identifier embedded in every backup manifest.
APP_ID = "openestimate"

# Sensitive fields stripped from every row before serialisation, so a backup
# file copied between machines never carries a secret in plain text. A column is
# stripped when its name matches exactly or ends with a secret-bearing suffix.
# The suffixes are deliberately narrow (no bare ``_key``) so the storage-key
# columns a restore needs - ``object_key``, ``storage_key``, ``file_path`` - are
# never stripped.
_STRIP_FIELDS: frozenset[str] = frozenset(
    {
        "hashed_password",
        "password_hash",
        "key_hash",
        "password",
        "api_key",
        "apikey",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "client_secret",
        "webhook_secret",
        "private_key",
    }
)
_SENSITIVE_SUFFIXES: tuple[str, ...] = ("_api_key", "_secret", "_token", "_password")


def _is_sensitive_field(key: str) -> bool:
    """True for a column that must never be written into a backup archive."""
    k = key.lower()
    return k in _STRIP_FIELDS or k.endswith(_SENSITIVE_SUFFIXES)


# Spool to disk after 16 MiB of in-memory buffer.
_SPOOL_THRESHOLD_BYTES = 16 * 1024 * 1024

# Chunk size when streaming the finished archive to the response.
_STREAM_CHUNK_BYTES = 64 * 1024

# Hard ceiling on the decompressed size of any single backup entry. A crafted
# "zip bomb" declares a tiny compressed size but inflates to gigabytes; every
# entry is read through ``_read_zip_member`` which aborts past this limit, so a
# restore cannot exhaust memory on a small VPS.
_MAX_ENTRY_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024  # 1 GiB per entry

# (backup_key, table_name, module_path, class_name) - restore-order
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


# Per-user ownership scope for every backup table.
#
# A backup is the requesting user's own data, not the whole instance. Both
# export (which rows to dump) and restore in ``replace`` mode (which rows to
# delete before re-importing) MUST use the exact same scope, or they diverge
# dangerously: the original code exported a per-user subset but deleted every
# row of every table on restore, so a single user restoring their own backup
# wiped every other user's data. The scope below makes the two symmetric.
#
# Ownership is project-rooted. Every row is reachable from the requesting user
# either directly (``users`` / ``ai_settings``) or through the project graph
# (``projects.owner_id`` -> children by foreign key). Predicate kinds:
#   ("self",)              -> id == user_id            (the users table)
#   ("eq", "<column>")     -> <column> == user_id      (direct owner column)
#   ("in", "<fk>", "<key>")-> <fk> IN (ids owned in parent backup_key)
# A row is in scope if ANY of its predicates match (logical OR).
_BACKUP_SCOPE: dict[str, list[tuple[str, ...]]] = {
    "users": [("self",)],
    "projects": [("eq", "owner_id")],
    "boqs": [("in", "project_id", "projects")],
    "positions": [("in", "boq_id", "boqs")],
    "markups": [("in", "boq_id", "boqs")],
    "schedules": [("eq", "created_by"), ("in", "project_id", "projects")],
    "activities": [("in", "schedule_id", "schedules")],
    "budget_lines": [("in", "project_id", "projects")],
    "cash_flows": [("in", "project_id", "projects")],
    "cost_snapshots": [("in", "project_id", "projects")],
    "risks": [("in", "project_id", "projects")],
    "change_orders": [("in", "project_id", "projects")],
    "change_order_items": [("in", "change_order_id", "change_orders")],
    "documents": [("in", "project_id", "projects")],
    "assemblies": [("eq", "owner_id"), ("in", "project_id", "projects")],
    "assembly_components": [("in", "assembly_id", "assemblies")],
    "tender_packages": [("in", "project_id", "projects")],
    "tender_bids": [("in", "package_id", "tender_packages")],
    "ai_settings": [("eq", "user_id")],
}


# --- Schema-driven registry (v11.6.0 full-coverage) --------------------------
# The curated ``_BACKUP_TABLE_DEFS`` / ``_BACKUP_SCOPE`` above cover the 19
# historical core tables. The registry below derives the FULL user-owned scope
# straight from the mapped schema (see ``graph_scope.derive_backup_graph``), so a
# personal backup no longer silently drops the several hundred other user-owned
# tables (equipment logs, diaries, HSE records, takeoff, BIM and so on). The
# curated data stays as the stable friendly-key source and as a safe fallback if
# derivation ever fails.


@dataclass(frozen=True)
class _BackupRegistry:
    """Resolved backup scope: which tables, their predicates, their owner columns.

    Attributes:
        table_defs: ``(backup_key, table_name, ModelClass)`` in restore order
            (parents before children).
        scope: ``backup_key -> [predicate]`` consumed by ``build_scope_clause``.
        by_key: ``backup_key -> ModelClass`` for quick lookups.
        owner_columns: ``backup_key -> {column}`` (the ``eq`` predicate columns)
            forced to the restoring user on import.
    """

    table_defs: list[tuple[str, str, type]]
    scope: dict[str, list[tuple[str, ...]]]
    by_key: dict[str, type]
    owner_columns: dict[str, frozenset[str]]


def _import_all_module_models() -> None:
    """Best-effort import of every module's models so the ORM registry is full.

    In the running app the module loader has already imported these, but a fresh
    process (a test, a CLI call) may not have, and the derivation can only see
    tables that are mapped. A module that fails to import is skipped with a debug
    log; its tables simply stay out of scope, exactly as before.
    """
    import importlib
    import pathlib

    import app.modules as modules_pkg

    modules_root = pathlib.Path(modules_pkg.__file__).parent
    for path in sorted(modules_root.iterdir()):
        if path.is_dir() and (path / "models.py").exists():
            try:
                importlib.import_module(f"app.modules.{path.name}.models")
            except Exception:
                logger.debug("Backup graph: could not import %s models", path.name, exc_info=True)


def _derive_registry() -> tuple[list[tuple[str, str, type]], dict[str, list[tuple[str, ...]]], dict[str, type]]:
    """Derive the full user-owned scope from the mapped schema."""
    from app.database import Base

    _import_all_module_models()
    class_for_table = {m.local_table.name: m.class_ for m in Base.registry.mappers}
    friendly = {table_name: key for key, table_name, _module, _cls in _BACKUP_TABLE_DEFS}
    graph = derive_backup_graph(Base.metadata, set(class_for_table), friendly_keys=friendly)

    table_defs: list[tuple[str, str, type]] = []
    by_key: dict[str, type] = {}
    for key, table_name in graph.table_defs:
        model_cls = class_for_table.get(table_name)
        if model_cls is None:
            continue
        table_defs.append((key, table_name, model_cls))
        by_key[key] = model_cls
    return table_defs, graph.scope, by_key


def _curated_registry() -> tuple[list[tuple[str, str, type]], dict[str, list[tuple[str, ...]]], dict[str, type]]:
    """The historical curated 19-table scope, used as a safe fallback."""
    table_defs: list[tuple[str, str, type]] = []
    by_key: dict[str, type] = {}
    for key, table_name, module_path, class_name in _BACKUP_TABLE_DEFS:
        try:
            model_cls = _get_model_class(module_path, class_name)
        except Exception:
            logger.warning("Skipping backup table %s: model import failed", key)
            continue
        table_defs.append((key, table_name, model_cls))
        by_key[key] = model_cls
    return table_defs, {k: list(v) for k, v in _BACKUP_SCOPE.items()}, by_key


def _build_registry() -> _BackupRegistry:
    """Assemble the active registry, preferring schema-driven full coverage.

    If derivation fails, or somehow drops one of the curated keys, fall back to
    the curated core so a backup is never quietly emptier than it was before the
    full-coverage rewrite.
    """
    try:
        table_defs, scope, by_key = _derive_registry()
        derived_keys = {key for key, _table, _cls in table_defs}
        curated_keys = {key for key, _table, _module, _cls in _BACKUP_TABLE_DEFS}
        if not curated_keys <= derived_keys:
            logger.warning(
                "Backup graph dropped curated keys %s; using curated core",
                sorted(curated_keys - derived_keys),
            )
            table_defs, scope, by_key = _curated_registry()
        else:
            logger.info("Backup scope: %d user-owned tables (schema-derived)", len(table_defs))
    except Exception:
        logger.warning("Backup graph derivation failed; using curated core", exc_info=True)
        table_defs, scope, by_key = _curated_registry()

    owner_columns = {
        key: frozenset(pred[1] for pred in preds if pred and pred[0] == "eq") for key, preds in scope.items()
    }
    return _BackupRegistry(table_defs=table_defs, scope=scope, by_key=by_key, owner_columns=owner_columns)


_REGISTRY: _BackupRegistry | None = None


def get_backup_registry() -> _BackupRegistry:
    """Return the process-wide backup registry, building it once and caching it."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def reset_backup_registry() -> None:
    """Drop the cached registry so the next call rebuilds it (used by tests)."""
    global _REGISTRY
    _REGISTRY = None


def build_scope_clause(
    by_key: dict[str, type],
    backup_key: str,
    user_id: str,
    scope: dict[str, list[tuple[str, ...]]] | None = None,
) -> Any:
    """Build a WHERE clause selecting only rows owned by ``user_id``.

    Children reference their owner through a nested ``IN (SELECT ...)``
    subquery so no IDs are materialised in Python: there is no bind-parameter
    ceiling and, because parents are deleted after their children in restore,
    the subqueries always see intact parent rows.

    Returns ``None`` when the table has no known ownership path. Callers treat
    ``None`` as "owns nothing", a safe default that neither leaks another
    user's rows on export nor deletes them on restore.
    """
    if scope is None:
        scope = get_backup_registry().scope
    preds = scope.get(backup_key)
    model_cls = by_key.get(backup_key)
    if not preds or model_cls is None:
        return None
    clauses: list[Any] = []
    for pred in preds:
        kind = pred[0]
        if kind == "self":
            clauses.append(model_cls.id == user_id)
        elif kind == "eq":
            col = getattr(model_cls, pred[1], None)
            if col is not None:
                clauses.append(col == user_id)
        elif kind == "in":
            col = getattr(model_cls, pred[1], None)
            parent_cls = by_key.get(pred[2])
            parent_clause = build_scope_clause(by_key, pred[2], user_id, scope)
            if col is not None and parent_cls is not None and parent_clause is not None:
                clauses.append(col.in_(select(parent_cls.id).where(parent_clause)))
    if not clauses:
        return None
    return or_(*clauses) if len(clauses) > 1 else clauses[0]


def _owner_columns(backup_key: str) -> frozenset[str]:
    """Columns that anchor a table's rows to their owning user.

    These are the direct-ownership (``eq``) predicates in the active backup scope
    (``owner_id``, ``created_by``, ``user_id`` and the like). On restore they are
    forced to the restoring user so ownership is pinned to the caller rather than
    trusted from an attacker-supplied archive. Child tables have no direct owner
    column here; they inherit their owner through the parent whose owner column
    is forced.
    """
    return get_backup_registry().owner_columns.get(backup_key, frozenset())


def _get_model_class(module_path: str, class_name: str) -> type:
    """Lazily import a model class to avoid circular imports."""
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def get_backup_tables() -> list[tuple[str, str, type]]:
    """Return resolved ``(backup_key, table_name, ModelClass)`` tuples.

    Sourced from the schema-driven registry (v11.6.0): it covers every user-owned
    table, not just the curated core, and orders them parents-before-children so a
    restore inserts a parent before any row that references it. Falls back to the
    curated core if derivation fails.
    """
    return list(get_backup_registry().table_defs)


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
    all_tables = get_backup_tables()
    # Resolve scope against the FULL table set: a filtered export of, say,
    # only ``boqs`` still needs ``projects`` available to build the subquery.
    by_key = {key: cls for key, _table_name, cls in all_tables}
    tables, unknown_modules = _filter_modules(all_tables, include_modules)

    record_counts: dict[str, int] = {}
    file_count = 0
    file_warnings: list[str] = []

    # Caller owns the spool - closed by ``stream_spooled``/``spool_to_disk``.
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
                    clause = build_scope_clause(by_key, backup_key, str(user_id))
                    if clause is None:
                        # No known ownership path: export nothing rather than
                        # dump every user's rows for this table.
                        logger.warning("No backup scope for table %s; exporting 0 rows", backup_key)
                        rows = []
                    else:
                        rows = (await session.execute(select(model_cls).where(clause))).scalars().all()
                    # Reading the loaded rows stays here, next to the session
                    # that owns them. Encoding and deflating them is pure CPU
                    # that grows with the account, so it runs in a worker
                    # thread: on the loop it froze every other request on this
                    # worker for seconds at a time. The zip is only ever
                    # touched by one call at a time, each awaited in turn.
                    serialised = [
                        {k: v for k, v in serialize_row(r).items() if not _is_sensitive_field(k)} for r in rows
                    ]
                    await asyncio.to_thread(_write_json_member, zf, f"{backup_key}.json", serialised)
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
            # ``format_version`` / ``checksum`` - never this key - so it is
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

    # Hashing and re-deflating the whole archive touches no database, so it
    # runs off the event loop in one piece.
    size = await asyncio.to_thread(_finalize_archive, spool, manifest, compression, compression_level)
    return spool, manifest, size


def _write_json_member(zf: zipfile.ZipFile, name: str, rows: list[dict[str, Any]]) -> None:
    """Encode ``rows`` and write them into ``zf`` as ``name``.

    Synchronous on purpose: :func:`build_backup` runs it in a worker thread.
    """
    zf.writestr(name, json.dumps(rows, indent=2, ensure_ascii=False, default=str))


def _finalize_archive(
    spool: tempfile.SpooledTemporaryFile,
    manifest: dict[str, Any],
    compression: int,
    compression_level: int,
) -> int:
    """Stamp the archive checksum into ``manifest`` and rewrite the archive with it.

    Returns the archive size and leaves ``spool`` rewound. Synchronous on
    purpose: :func:`build_backup` runs it in a worker thread, since it reads,
    hashes and re-deflates every member of the archive.
    """
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
    return size


async def _embed_module_files(zf: zipfile.ZipFile, backup_key: str, rows: list[Any]) -> tuple[int, list[str]]:
    """Embed binary blobs referenced by ``rows`` under ``files/<backup_key>/``.

    Looks up ``file_path`` (and a few common aliases) on each row, asks
    the configured storage backend for the bytes, and writes them into
    the archive. Skipped reads do not abort the export - they are
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
            # A blob can be a drawing or a model; deflating it is CPU work the
            # event loop must not carry. Reads above stay awaited here.
            await asyncio.to_thread(zf.writestr, f"files/{backup_key}/{key.lstrip('/')}", payload)
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


def _read_zip_member(zf: zipfile.ZipFile, name: str, cap: int = _MAX_ENTRY_UNCOMPRESSED_BYTES) -> bytes:
    """Read one ZIP member, aborting if it decompresses past ``cap`` bytes.

    ``ZipFile.read`` inflates the whole member with no size ceiling, so a bomb
    that declares a tiny size but expands to gigabytes would OOM the process.
    Reading in chunks and stopping at ``cap`` bounds the damage from an untrusted
    archive. Raises ``ValueError`` when the limit is exceeded.
    """
    out = bytearray()
    with zf.open(name) as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > cap:
                raise ValueError(f"Backup entry {name!r} exceeds the {cap}-byte decompression limit")
    return bytes(out)


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
        manifest = json.loads(_read_zip_member(zf, "manifest.json"))
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
                data[key] = json.loads(_read_zip_member(zf, name))
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


class RestoreError(Exception):
    """Abort signal for a restore that must roll back wholesale.

    Raised on a fatal clear or flush failure so the caller rolls back the
    single restore transaction and returns one clean error rather than
    committing a half-applied database. ``stage`` is ``"clear"`` or
    ``"import"`` and ``table`` is the backup key that failed.
    """

    def __init__(self, message: str, *, stage: str, table: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.table = table


# Tables never touched on restore: account-level config, not the project work
# data a transfer is about. The account restoring a backup already exists on the
# target machine with its own id, email, password and AI settings.
#   users:        cloning the exporter's row collides on the unique email and
#                 fails the NOT NULL password (the hash is stripped from every
#                 backup), which is exactly why a cross-machine restore aborted.
#   ai_settings:  one row per user (unique user_id); repointing it to the
#                 restoring user would collide with that user's own settings.
#                 The restoring account keeps its own AI keys, which are the
#                 right ones for its environment anyway.
# Ownership on every other imported row is repointed to the restoring user via
# ``remap_owner_refs``, so the actual work data lands under that account.
RESTORE_SKIP_KEYS: frozenset[str] = frozenset({"users", "ai_settings"})


def remap_owner_refs(
    record: dict[str, Any],
    old_owner: str,
    new_owner: str,
    owner_columns: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Repoint a row's ownership to the restoring user.

    Two steps. First the table's ``owner_columns`` (the direct-ownership anchors,
    see ``_owner_columns``) are forced to ``new_owner`` unconditionally. This is a
    security boundary, not a convenience: the archive and the ``created_by`` in
    its manifest are both supplied by whoever runs the restore, so ownership is
    pinned to the caller here and never trusted from the file. Without it a
    crafted backup could insert rows stamped with another account's user id and
    have them surface inside that person's workspace.

    Second, any other field still equal to ``old_owner`` (the exporter's id from
    the manifest) is repointed to ``new_owner`` as well, so secondary references
    like ``uploaded_by`` follow the data onto the new machine for the common case
    of a user moving their own backup between their own computers.
    """
    out = dict(record)
    for col in owner_columns:
        if col in out:
            out[col] = new_owner
    if old_owner and old_owner != new_owner:
        out = {key: (new_owner if isinstance(val, str) and val == old_owner else val) for key, val in out.items()}
    return out


_FILE_KEY_ATTRS: tuple[str, ...] = ("file_path", "storage_key", "object_key")


def _row_file_key(obj: Any) -> str | None:
    """The storage key a row points at, if any (documents, drawings, photos)."""
    for attr in _FILE_KEY_ATTRS:
        val = getattr(obj, attr, None)
        if isinstance(val, str) and val:
            return val
    return None


async def _import_table_rows(
    session: Any,
    model_cls: type,
    records: list[dict[str, Any]],
    backup_key: str,
    warnings: list[str],
    file_key_sink: set[str] | None = None,
) -> tuple[int, int]:
    """Insert already-remapped ``records`` for one table, resiliently.

    The fast path adds every row inside a single SAVEPOINT and flushes once. If
    any row trips a constraint - a globally unique code that already exists on
    this machine, or a reference to an account that was not part of the transfer
    - the SAVEPOINT rolls back and the rows are retried one per SAVEPOINT, so
    only the offending rows are skipped (each with a warning) and every other
    row still imports. Without this, one stray row would fail the whole-table
    flush and roll the entire restore back, which is exactly the "the backup
    restores into nothing" symptom a transfer between two machines can hit.

    Returns ``(imported, skipped)``.
    """
    if not records:
        return 0, 0

    # Fast path: the whole table in one SAVEPOINT.
    try:
        async with session.begin_nested():
            objs = [deserialize_row(model_cls, record) for record in records]
            for obj in objs:
                session.add(obj)
            await session.flush()
        if file_key_sink is not None:
            for obj in objs:
                key = _row_file_key(obj)
                if key:
                    file_key_sink.add(key)
        return len(records), 0
    except Exception:
        # A row tripped a constraint; fall back to per-row so the rest of the
        # table still imports. The failed SAVEPOINT has rolled back, expunging
        # the objects it added, so the retries below start from a clean slate.
        pass

    # Per-row fallback. Each row inserts in its own SAVEPOINT so one bad row is
    # skipped instead of sinking the table. Rows are retried in passes: a row
    # whose parent is a self-referential row listed later (Position.parent_id,
    # BOQ.parent_estimate_id, Project.parent_project_id, Document.parent_document_id)
    # fails on the first pass but lands on a later one once its parent is in. Each
    # pass that inserts at least one row may unblock others; we stop when a pass
    # makes no progress. A record is rebuilt fresh per attempt so a rolled-back
    # object is never re-added to the session.
    imported = 0
    skipped = 0
    pending: list[dict[str, Any]] = list(records)

    while pending:
        still_failing: list[tuple[dict[str, Any], Exception]] = []
        progressed = False
        for record in pending:
            try:
                obj = deserialize_row(model_cls, record)
            except Exception as exc:
                skipped += 1
                logger.warning("Skipped record in %s: %s", backup_key, str(exc)[:100])
                continue
            try:
                async with session.begin_nested():
                    session.add(obj)
                    await session.flush()
                imported += 1
                progressed = True
                if file_key_sink is not None:
                    key = _row_file_key(obj)
                    if key:
                        file_key_sink.add(key)
            except Exception as exc:
                still_failing.append((record, exc))
        if not progressed:
            for _record, exc in still_failing:
                skipped += 1
                warnings.append(f"{backup_key}: skipped a row ({str(exc)[:150]})")
                logger.warning("Restore skipped a row in %s: %s", backup_key, str(exc)[:200])
            break
        pending = [record for record, _exc in still_failing]
    return imported, skipped


async def _account_has_restorable_data(session: Any, user_id: str, by_key: dict[str, type]) -> bool:
    """True if the caller already owns data a replace-mode restore would clear.

    Replace deletes the caller's own anchor rows (projects, schedules,
    assemblies) before importing. In the database a project delete cascades
    across roughly ninety project-scoped modules that a backup does not carry
    (photos, BIM, takeoff, point clouds, diaries, schedule baselines and so on),
    and restore only rebuilds the backed-up tables, so replacing into a populated
    account would silently destroy all of that. Replace is therefore only allowed
    into an empty account; this check is how the guard detects a populated one.
    """
    for key in ("projects", "schedules", "assemblies"):
        cls = by_key.get(key)
        if cls is None:
            continue
        clause = build_scope_clause(by_key, key, str(user_id))
        if clause is None:
            continue
        row = (await session.execute(select(cls.id).where(clause).limit(1))).first()
        if row is not None:
            return True
    return False


async def restore_backup_data(
    session: Any,
    *,
    user_id: str,
    manifest: dict[str, Any],
    data: dict[str, list[dict]],
    mode: str,
    file_key_sink: set[str] | None = None,
) -> tuple[dict[str, int], dict[str, int], list[str]]:
    """Restore parsed backup ``data`` into the DB as ``user_id``.

    Runs inside the caller's transaction: the caller commits on success and
    rolls back on a raised :class:`RestoreError`. ``merge`` (the safe default)
    adds rows whose id does not already exist and deletes nothing. ``replace``
    first clears the caller's own rows, and is refused with a ``RestoreError``
    whose ``stage`` is ``"guard"`` unless the account is empty, because a project
    delete cascades in the database far beyond the backed-up tables and would
    destroy data a backup cannot rebuild (see ``_account_has_restorable_data``).

    Import is best-effort per row: a row that violates a constraint is skipped
    with a warning rather than aborting, so the import side is not strictly
    all-or-nothing, though the replace clear and the final commit are. The
    ``users`` and ``ai_settings`` tables are never touched (see
    ``RESTORE_SKIP_KEYS``) and every imported row's ownership is forced to
    ``user_id`` (see ``remap_owner_refs``) so a backup lands cleanly under the
    restoring account and never under the id an archive claims.

    When ``file_key_sink`` is given, the storage keys referenced by successfully
    imported rows are collected into it, so the caller can restrict file restore
    to exactly the blobs those rows own.
    """
    tables = get_backup_tables()
    by_key = {key: cls for key, _table_name, cls in tables}
    old_owner = str(manifest.get("created_by") or "")
    new_owner = str(user_id)

    imported: dict[str, int] = {}
    skipped: dict[str, int] = {}
    warnings: list[str] = []

    if mode == "replace":
        # A project delete cascades across roughly ninety project-scoped modules
        # the backup does not carry, so replacing a populated account would
        # silently destroy data restore cannot rebuild. Refuse replace unless the
        # account is empty; merge is the non-destructive way to add a backup to
        # existing data.
        if await _account_has_restorable_data(session, new_owner, by_key):
            raise RestoreError(
                "Replace mode needs an empty account. Your account already has data, and "
                "replacing it would remove project information this backup does not carry. "
                "Use merge to add the backup to your existing data.",
                stage="guard",
                table="account",
            )
        # FK-safe: children before parents. Scoped to the restoring user's own
        # rows so another user's data is never cleared, and ``users`` is
        # skipped so the restoring account is never deleted from under itself.
        for backup_key, _table_name, model_cls in reversed(tables):
            if backup_key in RESTORE_SKIP_KEYS:
                continue
            scope = build_scope_clause(by_key, backup_key, new_owner)
            if scope is None:
                continue
            try:
                await session.execute(delete(model_cls).where(scope))
            except Exception as exc:
                raise RestoreError(str(exc), stage="clear", table=backup_key) from exc

    for backup_key, _table_name, model_cls in tables:
        if backup_key in RESTORE_SKIP_KEYS:
            imported[backup_key] = 0
            skipped[backup_key] = 0
            continue

        records = data.get(backup_key, [])
        if not records:
            imported[backup_key] = 0
            skipped[backup_key] = 0
            continue

        # Repoint ownership to the restoring user and drop merge-mode duplicates
        # before insert, so the resilient importer only ever sees rows meant to
        # land on this machine. Ownership columns are forced to the caller so the
        # archive can never stamp a row with another account's id.
        owner_cols = _owner_columns(backup_key)
        prepared: list[dict[str, Any]] = []
        count_skipped = 0
        for record in records:
            record = remap_owner_refs(record, old_owner, new_owner, owner_cols)
            if mode == "merge":
                record_id = record.get("id")
                if record_id:
                    try:
                        lookup_id = uuid.UUID(record_id) if isinstance(record_id, str) else record_id
                    except (ValueError, TypeError):
                        count_skipped += 1
                        continue
                    existing = (
                        await session.execute(select(model_cls).where(model_cls.id == lookup_id))
                    ).scalar_one_or_none()
                    if existing is not None:
                        count_skipped += 1
                        continue
            prepared.append(record)

        # Insert in FK order (parents before children, per table order). A single
        # row that violates a constraint is skipped with a warning rather than
        # aborting the whole transfer (see ``_import_table_rows``).
        count_imported, import_skipped = await _import_table_rows(
            session, model_cls, prepared, backup_key, warnings, file_key_sink
        )
        imported[backup_key] = count_imported
        skipped[backup_key] = count_skipped + import_skipped

    return imported, skipped, warnings


async def restore_backup_files(
    raw: bytes,
    *,
    backend: Any = None,
    allowed_keys: set[str] | None = None,
) -> tuple[int, list[str]]:
    """Write a backup's embedded ``files/`` blobs into storage, safely.

    Export can embed the binaries referenced by ``file_path`` columns
    (documents, drawings, photos) under ``files/<backup_key>/<storage-key>``.
    This writes them back so a transferred backup keeps those files, not just
    the rows that point at them. It is best-effort and runs OUTSIDE the DB
    transaction: a file that fails to write is reported as a warning and never
    undoes the data restore, exactly as the export lists an unreadable file as
    a warning rather than aborting. Returns ``(written_count, warnings)``.

    Two guards keep an untrusted archive from touching storage it does not own,
    because storage keys are a namespace shared across accounts:
      * ``allowed_keys`` (when given) is the set of storage keys that rows
        actually imported in this restore point at. Only those are written, so a
        crafted archive cannot push blobs for arbitrary keys.
      * an existing blob is never overwritten. A transfer fills in the files a
        fresh machine is missing; it must not clobber a blob already in storage,
        which could belong to someone else.
    ``backend`` defaults to the configured storage backend and is injectable
    for tests.
    """
    written = 0
    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return 0, ["Could not reopen the archive to restore files"]

    names = [n for n in zf.namelist() if n.startswith("files/") and not n.endswith("/")]
    if not names:
        return 0, warnings

    if backend is None:
        from app.core.storage import get_storage_backend

        backend = get_storage_backend()

    for name in names:
        # Embedded as ``files/<backup_key>/<storage-key>``; recover the storage
        # key by dropping the first two path segments.
        parts = name.split("/", 2)
        if len(parts) < 3 or not parts[2]:
            continue
        key = parts[2]
        # Only restore a file that backs a row actually imported this restore.
        if allowed_keys is not None and key not in allowed_keys:
            continue
        try:
            if await backend.exists(key):
                warnings.append(f"Kept existing file, not overwritten: {key}")
                continue
            await backend.put(key, _read_zip_member(zf, name))
            written += 1
        except Exception as exc:
            warnings.append(f"Failed to restore file {key}: {str(exc)[:200]}")

    return written, warnings


__all__ = [
    "APP_ID",
    "BACKUP_FORMAT_VERSION",
    "RESTORE_SKIP_KEYS",
    "RestoreError",
    "build_backup",
    "build_scope_clause",
    "cleanup_temp_file",
    "deserialize_row",
    "get_backup_registry",
    "get_backup_tables",
    "reset_backup_registry",
    "parse_backup_zip",
    "remap_owner_refs",
    "restore_backup_data",
    "restore_backup_files",
    "serialize_row",
    "spool_to_disk",
    "stream_spooled",
    "stream_spooled_async",
]
