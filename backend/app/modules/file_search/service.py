# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File search service — index + query business logic.

Stateless service. The indexer pulls the on-disk bytes for the file
(documents / sheets / markups; other kinds use the embedded ``file_path``
column on their canonical model), runs the appropriate extractor from
:mod:`app.modules.file_search.extractors`, and upserts a row into
``oe_file_search_index``.

Query side picks the dialect-correct full-text strategy:

* PostgreSQL — ``to_tsvector('simple', content_text) @@ plainto_tsquery``
  with ``ts_rank`` for ordering; the migration also adds a generated
  ``tsv_vector`` column + GIN index for hot-path performance.
* SQLite      — case-insensitive ``LIKE %q%`` ranked by the position of
  the first match (earlier match → higher score). No regex, no FTS5,
  so this works against the same SQLite file the test suite uses.

Both code paths produce the SAME ``SearchHit`` shape — the dialect
choice is invisible to the router.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_search.extractors import ExtractionResult, extract_text
from app.modules.file_search.models import FileSearchIndex
from app.modules.file_search.schemas import SearchHit

logger = logging.getLogger(__name__)

SNIPPET_WINDOW: int = 200  # chars on either side of the first match

# Mapping of file_kind → ORM model + attribute holding the on-disk path.
# Polled lazily because the ORM modules import each other transitively
# and we want to avoid an eager import here that the loader does not
# expect.
_KIND_LOADERS: dict[str, tuple[str, str, str, str]] = {
    # kind → (module path, ORM attr, file_path attr, canonical_name attr)
    "document": (
        "app.modules.documents.models",
        "Document",
        "file_path",
        "name",
    ),
    "sheet": (
        "app.modules.documents.models",
        "Sheet",
        "thumbnail_path",  # sheets don't store source PDFs separately
        "sheet_title",
    ),
    "photo": (
        "app.modules.documents.models",
        "ProjectPhoto",
        "file_path",
        "filename",
    ),
}


async def _fetch_file_payload(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: str,
    file_id: str,
) -> tuple[bytes, str, str]:
    """Resolve and read the on-disk bytes for a single file.

    Returns ``(payload, mime, canonical_name)``. Returns
    ``(b"", "", "")`` when the file isn't a kind we can index, when the
    record is missing, or when the path resolves to nothing on disk
    (e.g. stale demo seed). Never raises — the caller decides how to
    treat the empty payload (the indexer simply persists a blank row
    with engine="none").
    """
    import importlib

    spec = _KIND_LOADERS.get(kind)
    if spec is None:
        return b"", "", ""
    module_path, cls_name, path_attr, name_attr = spec

    try:
        mod = importlib.import_module(module_path)
    except ModuleNotFoundError:
        return b"", "", ""
    Cls = getattr(mod, cls_name, None)
    if Cls is None:
        return b"", "", ""

    # Try UUID-keyed lookup first (Document / ProjectPhoto / Sheet all
    # use the Base UUID PK). Fall back to string-id where the model
    # stores string ids.
    obj = None
    try:
        obj = await session.get(Cls, uuid.UUID(file_id))
    except (ValueError, TypeError):
        obj = None

    if obj is None or getattr(obj, "project_id", None) != project_id:
        return b"", "", ""

    file_path = getattr(obj, path_attr, None)
    canonical_name = getattr(obj, name_attr, None) or ""

    if not file_path:
        return b"", "", canonical_name

    try:
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return b"", "", canonical_name
        payload = path.read_bytes()
    except Exception:
        logger.exception("Failed to read file bytes for indexing: %s", file_path)
        return b"", "", canonical_name

    mime = getattr(obj, "mime_type", "") or ""
    return payload, mime, canonical_name


async def _upsert_index_row(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: str,
    file_id: str,
    extraction: ExtractionResult,
) -> FileSearchIndex:
    """Insert-or-update the canonical index row for a single file.

    Uses a plain SELECT-then-UPDATE/INSERT cycle because we have to
    support both SQLite (no native ON CONFLICT for our column tuple) and
    Postgres uniformly. The unique constraint on
    ``(project_id, file_kind, file_id)`` covers the race window between
    parallel uploads of the same row.
    """
    stmt = select(FileSearchIndex).where(
        FileSearchIndex.project_id == project_id,
        FileSearchIndex.file_kind == kind,
        FileSearchIndex.file_id == file_id,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()

    now = datetime.now(UTC)
    if existing is not None:
        existing.content_text = extraction.text
        existing.page_count = extraction.page_count
        existing.ocr_engine = extraction.engine
        existing.language = extraction.language
        existing.indexed_at = now
        await session.flush()
        return existing

    row = FileSearchIndex(
        project_id=project_id,
        file_kind=kind,
        file_id=file_id,
        content_text=extraction.text,
        page_count=extraction.page_count,
        ocr_engine=extraction.engine,
        language=extraction.language,
        indexed_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def index_file(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: str,
    file_id: str,
    *,
    payload_override: bytes | None = None,
    mime_override: str | None = None,
) -> FileSearchIndex:
    """Index (or re-index) a single file.

    Args:
        session: Active SQLAlchemy async session.
        project_id: Owning project UUID.
        kind: One of the file-manager file kinds (``"document"``,
            ``"sheet"``, ``"photo"``, etc.).
        file_id: ID of the underlying canonical record. Treated as
            string so SQLite + Postgres handle it identically.
        payload_override: Bypass the on-disk lookup and use these bytes
            directly. Useful for tests and for the upload hook which
            already has the bytes in memory.
        mime_override: Override mime type (test convenience).

    Returns:
        The persisted ``FileSearchIndex`` row.
    """
    if payload_override is not None:
        payload = payload_override
        mime = mime_override or ""
    else:
        payload, mime, _name = await _fetch_file_payload(session, project_id, kind, file_id)

    extraction = extract_text(payload, mime)
    return await _upsert_index_row(session, project_id, kind, file_id, extraction)


async def delete_index_for_file(
    session: AsyncSession,
    project_id: uuid.UUID,
    file_id: str,
    kind: str | None = None,
) -> int:
    """Remove a single file's row(s) from the index.

    If ``kind`` is ``None`` every row for this ``file_id`` is removed
    (covers the rare case where the same UUID is reused across kinds).
    Returns the number of rows deleted.
    """
    stmt = delete(FileSearchIndex).where(
        FileSearchIndex.project_id == project_id,
        FileSearchIndex.file_id == file_id,
    )
    if kind is not None:
        stmt = stmt.where(FileSearchIndex.file_kind == kind)
    result = await session.execute(stmt)
    await session.flush()
    return int(result.rowcount or 0)


def _build_snippet(text: str, q: str) -> str:
    """Return a SNIPPET_WINDOW-char window centred on the first match.

    Case-insensitive partial match. If the term is not found (e.g.
    Postgres stem matched but our naive ``find`` didn't), returns the
    leading window of the text — still useful context.
    """
    if not text:
        return ""
    needle = q.strip()
    if not needle:
        return text[:SNIPPET_WINDOW]
    lower = text.lower()
    pos = lower.find(needle.lower())
    if pos < 0:
        return text[:SNIPPET_WINDOW]
    start = max(0, pos - SNIPPET_WINDOW // 2)
    end = min(len(text), pos + len(needle) + SNIPPET_WINDOW // 2)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


async def _resolve_canonical_name(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: str,
    file_id: str,
) -> str:
    """Best-effort lookup of the human-facing name for a file row.

    Falls back to ``f"{kind}/{file_id}"`` if the underlying record is
    gone — search results stay legible even if the source row was
    deleted between indexing and the next search.
    """
    spec = _KIND_LOADERS.get(kind)
    if spec is None:
        return f"{kind}/{file_id}"
    import importlib

    try:
        mod = importlib.import_module(spec[0])
    except ModuleNotFoundError:
        return f"{kind}/{file_id}"
    Cls = getattr(mod, spec[1], None)
    if Cls is None:
        return f"{kind}/{file_id}"
    try:
        obj = await session.get(Cls, uuid.UUID(file_id))
    except (ValueError, TypeError):
        return f"{kind}/{file_id}"
    if obj is None or getattr(obj, "project_id", None) != project_id:
        return f"{kind}/{file_id}"
    return getattr(obj, spec[3], None) or f"{kind}/{file_id}"


async def search_content(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: str,
    *,
    kind: str | None = None,
    mode: str = "content",
    limit: int = 50,
) -> list[SearchHit]:
    """Search the content index.

    Args:
        session: Active async session.
        project_id: Project to scope the search to.
        q: Free-text query (already trimmed by the router).
        kind: Optional file_kind filter.
        mode: ``"content"`` (default) hits the indexed text; ``"filename"``
              walks the canonical-name attribute on each kind's ORM
              model. Filename search bypasses the index entirely so it
              works even on unindexed files.
        limit: Maximum number of hits to return.

    Returns:
        Ranked list of :class:`SearchHit`. May be shorter than ``limit``.
    """
    q = (q or "").strip()
    if not q:
        return []

    if mode == "filename":
        return await _search_by_filename(session, project_id, q, kind, limit)

    # ── Content search ──────────────────────────────────────────────
    dialect = session.bind.dialect.name if session.bind else "sqlite"
    rows: list[FileSearchIndex]
    if dialect == "postgresql":
        rows = await _content_search_postgres(session, project_id, q, kind, limit)
    else:
        rows = await _content_search_sqlite(session, project_id, q, kind, limit)

    hits: list[SearchHit] = []
    for row in rows:
        name = await _resolve_canonical_name(session, project_id, row.file_kind, row.file_id)
        snippet = _build_snippet(row.content_text, q)
        hits.append(
            SearchHit(
                file_id=row.file_id,
                kind=row.file_kind,
                canonical_name=name,
                snippet=snippet,
                score=_score_for(row.content_text, q),
                page_count=row.page_count,
            )
        )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits


def _score_for(text: str, q: str) -> float:
    """Cheap dialect-agnostic rank.

    Score is normalised to ``[0, 1]`` and rewards (a) more matches,
    (b) earlier first match. This is the SAME ranker the SQLite fallback
    uses, so prod (Postgres) results stay consistent with CI (SQLite)
    even though Postgres internally uses ``ts_rank``.
    """
    if not text or not q:
        return 0.0
    lower = text.lower()
    needle = q.lower()
    count = lower.count(needle)
    if count == 0:
        return 0.0
    pos = lower.find(needle)
    position_bonus = 1.0 - (pos / max(len(text), 1))
    count_score = min(count / 10.0, 1.0)
    return round(0.5 * position_bonus + 0.5 * count_score, 4)


async def _content_search_postgres(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: str,
    kind: str | None,
    limit: int,
) -> list[FileSearchIndex]:
    """Postgres tsvector-backed search."""
    from sqlalchemy import text as sa_text

    sql = """
        SELECT * FROM oe_file_search_index
        WHERE project_id = :pid
        AND (
            tsv_vector @@ plainto_tsquery('simple', :q)
            OR content_text ILIKE :like
        )
    """
    params: dict = {
        "pid": str(project_id),
        "q": q,
        "like": f"%{q}%",
    }
    if kind is not None:
        sql += " AND file_kind = :kind"
        params["kind"] = kind
    sql += " ORDER BY ts_rank(tsv_vector, plainto_tsquery('simple', :q)) DESC LIMIT :limit"
    params["limit"] = limit

    result = await session.execute(sa_text(sql), params)
    rows = result.mappings().all()
    out: list[FileSearchIndex] = []
    for row in rows:
        out.append(
            FileSearchIndex(
                id=row["id"],
                project_id=row["project_id"],
                file_kind=row["file_kind"],
                file_id=row["file_id"],
                content_text=row["content_text"],
                page_count=row["page_count"],
                ocr_engine=row["ocr_engine"],
                language=row["language"],
                indexed_at=row["indexed_at"],
            )
        )
    return out


async def _content_search_sqlite(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: str,
    kind: str | None,
    limit: int,
) -> list[FileSearchIndex]:
    """SQLite ``LIKE``-backed search.

    Case-insensitive: SQLite's ``LIKE`` is ASCII-case-insensitive by
    default. For non-ASCII queries we wrap with ``lower(content_text)``
    so the test suite (which feeds plain English fixtures) still passes
    on a default-collation SQLite.
    """
    needle = f"%{q.lower()}%"
    from sqlalchemy import func

    stmt = select(FileSearchIndex).where(
        FileSearchIndex.project_id == project_id,
        func.lower(FileSearchIndex.content_text).like(needle),
    )
    if kind is not None:
        stmt = stmt.where(FileSearchIndex.file_kind == kind)
    stmt = stmt.limit(limit * 4)  # over-fetch; final ordering happens in Python
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _search_by_filename(
    session: AsyncSession,
    project_id: uuid.UUID,
    q: str,
    kind: str | None,
    limit: int,
) -> list[SearchHit]:
    """Match against canonical-name attributes across kinds.

    Walks the kinds registered in ``_KIND_LOADERS`` and runs a
    case-insensitive substring match on each kind's name attribute.
    """
    import importlib

    from sqlalchemy import func

    needle = f"%{q.lower()}%"
    hits: list[SearchHit] = []
    target_kinds = [kind] if kind in _KIND_LOADERS else list(_KIND_LOADERS.keys())

    for k in target_kinds:
        spec = _KIND_LOADERS.get(k)
        if spec is None:
            continue
        try:
            mod = importlib.import_module(spec[0])
        except ModuleNotFoundError:
            continue
        Cls = getattr(mod, spec[1], None)
        if Cls is None:
            continue
        name_attr = getattr(Cls, spec[3], None)
        if name_attr is None:
            continue
        stmt = select(Cls).where(Cls.project_id == project_id).where(func.lower(name_attr).like(needle)).limit(limit)
        result = await session.execute(stmt)
        for row in result.scalars().all():
            name = getattr(row, spec[3], None) or f"{k}/{row.id}"
            hits.append(
                SearchHit(
                    file_id=str(row.id),
                    kind=k,
                    canonical_name=name,
                    snippet=name,
                    score=_score_for(name, q),
                    page_count=None,
                )
            )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


async def reindex_project(
    session: AsyncSession,
    project_id: uuid.UUID,
) -> tuple[int, int, int]:
    """Re-OCR every file across every kind registered with the indexer.

    Returns ``(indexed, skipped, errors)`` so callers can surface
    progress to the operator.
    """
    import importlib

    indexed = 0
    skipped = 0
    errors = 0

    for kind, spec in _KIND_LOADERS.items():
        try:
            mod = importlib.import_module(spec[0])
        except ModuleNotFoundError:
            continue
        Cls = getattr(mod, spec[1], None)
        if Cls is None:
            continue
        stmt = select(Cls).where(Cls.project_id == project_id)
        result = await session.execute(stmt)
        for row in result.scalars().all():
            try:
                await index_file(session, project_id, kind, str(row.id))
                indexed += 1
            except Exception:
                logger.exception("Reindex failed for kind=%s file_id=%s", kind, row.id)
                errors += 1
                continue

    return indexed, skipped, errors
