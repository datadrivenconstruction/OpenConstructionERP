# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the file_search module (W3).

Three layers:

* **Pure**       — ``extract_text`` graceful-degradation when optional
                   deps are unavailable; ``_build_snippet`` window.
* **Indexer**    — index_file persists a row, upsert is idempotent, the
                   row carries the right ``ocr_engine`` for the input
                   mime, and ``delete_index_for_file`` removes it.
* **Search**     — searching by content returns a hit with the expected
                   snippet and correct file_id; searching by filename
                   works without an indexed row; reindex_project runs
                   over every file kind without error.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-file-search-"))
_TMP_DB = _TMP_DIR / "file_search.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

import app.modules.documents.models  # noqa: E402, F401
import app.modules.file_search.models  # noqa: E402, F401

# Force ORM registration of every module the index references.
import app.modules.projects.models  # noqa: E402, F401
import app.modules.users.models  # noqa: E402, F401
from app.modules.file_search.extractors import extract_text  # noqa: E402
from app.modules.file_search.models import FileSearchIndex  # noqa: E402
from app.modules.file_search.service import (  # noqa: E402
    _build_snippet,
    delete_index_for_file,
    index_file,
    reindex_project,
    search_content,
)

# ── Pure: extract_text graceful degradation ───────────────────────────────


def test_extract_text_empty_payload_returns_none_engine() -> None:
    """An empty payload must not crash and must report engine='none'."""
    result = extract_text(b"", "application/pdf")
    assert result.text == ""
    assert result.engine == "none"
    assert result.page_count is None


def test_extract_text_plaintext_decodes_utf8() -> None:
    """Plain text payloads ought to decode UTF-8 directly."""
    payload = b"Foundation level structural calculation page"
    result = extract_text(payload, "text/plain")
    assert "Foundation" in result.text
    assert result.engine == "plaintext"


def test_extract_text_unknown_binary_yields_empty() -> None:
    """Binary mimes we don't know how to handle return empty text."""
    payload = b"\x00\x01\x02\x03\x04\x05" * 16
    result = extract_text(payload, "application/octet-stream")
    assert result.text == ""
    assert result.engine == "none"


# ── Pure: _build_snippet window ──────────────────────────────────────────


def test_build_snippet_returns_window_around_match() -> None:
    text = "alpha beta " * 50 + "the magical needle is here " + "gamma delta " * 50
    snippet = _build_snippet(text, "needle")
    assert "needle" in snippet
    # Window is bounded; we should not get the whole text back.
    assert len(snippet) < len(text)


def test_build_snippet_leading_window_when_no_match() -> None:
    """If the term is missing from the text, return the leading slice."""
    text = "a" * 500
    snippet = _build_snippet(text, "needle")
    assert snippet.startswith("a")
    assert len(snippet) <= 200


def test_build_snippet_empty_text_returns_empty() -> None:
    assert _build_snippet("", "q") == ""


# ── Fixtures: real DB session ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """A real AsyncSession over a freshly create_all'd temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session


async def _seed_project(session) -> uuid.UUID:
    """Insert a minimal user + project; return the project_id."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"fs-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="File Search Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="File Search Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


async def _seed_document(session, project_id, name, body_text):
    """Insert a document row + write the body to a temp file.

    Returns the (document, file_path). file_path lives in the test
    tmp dir so it gets cleaned up automatically.
    """
    from app.modules.documents.models import Document

    tmp_dir = Path(tempfile.mkdtemp(prefix="oe-fs-doc-"))
    file_path = tmp_dir / name
    file_path.write_text(body_text, encoding="utf-8")
    doc = Document(
        project_id=project_id,
        name=name,
        description="",
        category="specification",
        file_size=len(body_text),
        mime_type="text/plain",
        file_path=str(file_path),
        uploaded_by="tester",
    )
    session.add(doc)
    await session.flush()
    return doc, file_path


# ── Indexer ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_file_persists_extracted_text(db_session) -> None:
    """index_file → row exists with the body text + engine=plaintext."""
    project_id = await _seed_project(db_session)
    body = (
        "STRUCTURAL CALCULATION — FOUNDATION DESIGN\n"
        "Concrete grade: C30/37\n"
        "Reinforcement: B500B\n"
        "Foundation: piled raft, 24 piles, 800 mm diameter\n"
    )
    doc, _ = await _seed_document(db_session, project_id, "calc.txt", body)

    row = await index_file(db_session, project_id, "document", str(doc.id))
    await db_session.flush()

    assert row.file_kind == "document"
    assert row.file_id == str(doc.id)
    assert "FOUNDATION" in row.content_text
    assert row.ocr_engine == "plaintext"
    assert row.indexed_at is not None


@pytest.mark.asyncio
async def test_index_file_is_idempotent_upsert(db_session) -> None:
    """Re-indexing the same file overwrites the existing row, no duplicate."""
    project_id = await _seed_project(db_session)
    doc, file_path = await _seed_document(db_session, project_id, "doc.txt", "first version of the body")
    await index_file(db_session, project_id, "document", str(doc.id))
    # Mutate file → re-index.
    file_path.write_text("second version of the body", encoding="utf-8")
    await index_file(db_session, project_id, "document", str(doc.id))

    from sqlalchemy import select

    count = (
        (await db_session.execute(select(FileSearchIndex).where(FileSearchIndex.file_id == str(doc.id))))
        .scalars()
        .all()
    )
    assert len(count) == 1
    assert "second version" in count[0].content_text


@pytest.mark.asyncio
async def test_index_file_handles_missing_file_on_disk(db_session) -> None:
    """File row exists but the bytes are gone → row still indexed (empty)."""
    project_id = await _seed_project(db_session)
    doc, file_path = await _seed_document(db_session, project_id, "ghost.txt", "ephemeral body")
    file_path.unlink()  # remove the bytes
    row = await index_file(db_session, project_id, "document", str(doc.id))

    assert row.file_id == str(doc.id)
    assert row.content_text == ""
    assert row.ocr_engine == "none"


# ── Search ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_content_returns_matching_hit_with_snippet(db_session) -> None:
    """Index a doc with known text → search returns hit + correct snippet."""
    project_id = await _seed_project(db_session)
    body = (
        "Section A — Foundations.\n"
        "All footings must be cast in concrete grade C30/37 with a "
        "minimum cover of 50 mm. The reinforcement shall be tied with "
        "B500B steel bars at the spacing called out on drawing S-101.\n"
        "Section B — Slabs.\n"
    )
    doc, _ = await _seed_document(db_session, project_id, "spec.txt", body)
    await index_file(db_session, project_id, "document", str(doc.id))

    hits = await search_content(db_session, project_id, "B500B", mode="content")
    assert len(hits) >= 1
    h = hits[0]
    assert h.file_id == str(doc.id)
    assert h.kind == "document"
    assert "B500B" in h.snippet
    assert h.score > 0


@pytest.mark.asyncio
async def test_search_filename_mode_returns_by_canonical_name(db_session) -> None:
    """mode=filename hits the canonical name even with no indexed row."""
    project_id = await _seed_project(db_session)
    doc, _ = await _seed_document(db_session, project_id, "S-101-piles-rev-A.pdf", "irrelevant body")
    # Deliberately do NOT index — filename mode must still work.

    hits = await search_content(db_session, project_id, "piles", mode="filename")
    assert len(hits) == 1
    assert hits[0].file_id == str(doc.id)
    assert "piles" in hits[0].canonical_name.lower()


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty_list(db_session) -> None:
    project_id = await _seed_project(db_session)
    hits = await search_content(db_session, project_id, "", mode="content")
    assert hits == []


@pytest.mark.asyncio
async def test_search_other_project_isolation(db_session) -> None:
    """Search must NEVER return hits from a different project."""
    project_a = await _seed_project(db_session)
    project_b = await _seed_project(db_session)
    doc_a, _ = await _seed_document(db_session, project_a, "a.txt", "secret token zebra-mango-quartz")
    await index_file(db_session, project_a, "document", str(doc_a.id))

    hits = await search_content(db_session, project_b, "zebra-mango-quartz")
    assert hits == []


@pytest.mark.asyncio
async def test_delete_index_for_file_removes_row(db_session) -> None:
    """delete_index_for_file → row gone; search no longer hits."""
    project_id = await _seed_project(db_session)
    doc, _ = await _seed_document(db_session, project_id, "removable.txt", "transient body about gamma-irrelevant-text")
    await index_file(db_session, project_id, "document", str(doc.id))

    deleted = await delete_index_for_file(db_session, project_id, str(doc.id))
    assert deleted == 1
    hits = await search_content(db_session, project_id, "gamma-irrelevant-text")
    assert hits == []


@pytest.mark.asyncio
async def test_reindex_project_runs_without_error(db_session) -> None:
    """reindex_project re-OCRs every doc; no error on empty kinds."""
    project_id = await _seed_project(db_session)
    doc1, _ = await _seed_document(db_session, project_id, "one.txt", "first body alpha")
    doc2, _ = await _seed_document(db_session, project_id, "two.txt", "second body beta")

    indexed, _skipped, errors = await reindex_project(db_session, project_id)
    assert indexed == 2
    assert errors == 0

    hits = await search_content(db_session, project_id, "alpha")
    assert any(h.file_id == str(doc1.id) for h in hits)
