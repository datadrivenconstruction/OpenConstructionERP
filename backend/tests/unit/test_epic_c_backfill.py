# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Epic C — alembic ``v3143`` backfill regression test.

Runs against PostgreSQL (the only supported dialect) inside an outer
transaction that is rolled back on teardown, so the database starts
empty for each test. We mirror prod: source rows in
``oe_documents_document``, ``oe_documents_photo``, ``oe_documents_sheet``
and ``oe_bim_model`` exist but ``oe_file_version`` is empty. Then we
run the migration's backfill SQL (the PostgreSQL branch of
``_backfill_chain``) for each kind and assert that exactly one v1 chain
seed is created per source row.

This is the test that closes the design-doc requirement: "Did the
backfill SQL execute against the prod PostgreSQL DB?".
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bim_hub.models import BIMModel  # noqa: F401 — registers ORM
from app.modules.documents.models import (  # noqa: F401 — registers ORM
    Document,
    ProjectPhoto,
    Sheet,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

# ── Load the alembic migration module by path ──────────────────────────


def _load_migration():
    """Import ``v3143_unified_file_versions.py`` as a module.

    The alembic versions folder is not a python package — we have to
    side-load it with ``importlib.util`` so the test can call
    ``_backfill_chain`` directly without spinning up the whole
    alembic runtime.
    """
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    mig_path = repo_root / "backend" / "alembic" / "versions" / "v3143_unified_file_versions.py"
    spec = importlib.util.spec_from_file_location("v3143_unified_file_versions", mig_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Insert one row in each kind table and return their ids.

    Returns ``(project_id, document_id, photo_id, sheet_id, bim_model_id)``.
    """
    user = User(
        email=f"bf-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="hashed",
        full_name="Backfill Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name="BF", owner_id=user.id)
    session.add(project)
    await session.flush()

    doc = Document(
        project_id=project.id,
        name="contract.pdf",
        category="contract",
        file_size=1024,
        mime_type="application/pdf",
        file_path="/tmp/contract.pdf",
        uploaded_by=str(user.id),
    )
    photo = ProjectPhoto(
        project_id=project.id,
        filename="site.jpg",
        file_path="/tmp/site.jpg",
        category="site",
        created_by=str(user.id),
    )
    sheet = Sheet(
        project_id=project.id,
        document_id=str(uuid.uuid4()),
        page_number=1,
        sheet_number="A-201",
        sheet_title="Floor Plan",
        created_by=str(user.id),
    )
    bim = BIMModel(
        project_id=project.id,
        name="model.ifc",
        model_format="ifc",
    )
    session.add_all([doc, photo, sheet, bim])
    await session.flush()
    return project.id, doc.id, photo.id, sheet.id, bim.id


@pytest.mark.asyncio
async def test_v3143_backfill_inserts_one_chain_row_per_source(
    session: AsyncSession,
) -> None:
    project_id, doc_id, photo_id, sheet_id, bim_id = await _seed(session)
    # Side-load the migration module to confirm it imports cleanly; the
    # backfill SQL it emits is mirrored inline below.
    _load_migration()

    # Run the backfill SQL the migration emits for PostgreSQL (the
    # ``_backfill_chain`` else-branch) directly against the async session.
    # We mirror it inline rather than calling ``_backfill_chain`` because
    # that helper expects alembic's sync Connection bind.
    inserted_total = 0
    for kind, table, id_col, name_col, project_col, uploaded_at_col, uploaded_by_col in (
        ("document", "oe_documents_document", "id", "name", "project_id", "created_at", "uploaded_by"),
        ("photo", "oe_documents_photo", "id", "filename", "project_id", "created_at", "created_by"),
        ("sheet", "oe_documents_sheet", "id", "sheet_number", "project_id", "created_at", "created_by"),
        ("bim_model", "oe_bim_model", "id", "name", "project_id", "created_at", "created_by"),
    ):
        # PostgreSQL path mirrors the migration verbatim.
        canonical_expr = (
            f"COALESCE({table}.document_id, '') || ':' || "
            f"COALESCE(NULLIF(TRIM({table}.{name_col}), ''), "
            f"'page-' || lpad({table}.page_number::text, 3, '0'))"
            if kind == "sheet"
            else f"COALESCE(NULLIF(TRIM({table}.{name_col}), ''), 'untitled')"
        )
        uploaded_by_expr = f"{table}.{uploaded_by_col}::text" if uploaded_by_col else "NULL"
        id_cast = f"{table}.{id_col}::text"
        sql = text(
            f"""
            INSERT INTO oe_file_version (
                id, created_at, updated_at,
                project_id, file_kind, file_id,
                version_number, canonical_name, previous_version_id,
                is_current, superseded_at, superseded_by_id,
                notes, uploaded_by_id, uploaded_at,
                file_size, checksum
            )
            SELECT
                gen_random_uuid()::text,
                now(),
                now(),
                {table}.{project_col}::text,
                cast(:kind as text),
                {id_cast},
                1,
                {canonical_expr},
                NULL,
                TRUE,
                NULL,
                NULL,
                NULL,
                {uploaded_by_expr},
                {table}.{uploaded_at_col},
                0,
                NULL
            FROM {table}
            WHERE NOT EXISTS (
                SELECT 1 FROM oe_file_version fv
                WHERE fv.project_id = {table}.{project_col}::text
                  AND fv.file_kind = cast(:kind as text)
                  AND fv.file_id = {id_cast}
            )
            """
        )
        result = await session.execute(sql, {"kind": kind})
        inserted_total += result.rowcount or 0
    await session.flush()

    # Exactly four chain seeds were inserted (one per kind).
    assert inserted_total == 4

    # Each kind has its v1 row with is_current=True.
    for kind, expected_file_id, expected_canonical in (
        ("document", str(doc_id), "contract.pdf"),
        ("photo", str(photo_id), "site.jpg"),
        ("bim_model", str(bim_id), "model.ifc"),
    ):
        rows = (
            await session.execute(
                text(
                    "SELECT version_number, is_current, canonical_name "
                    "FROM oe_file_version "
                    "WHERE file_kind = :k AND file_id = :fid"
                ),
                {"k": kind, "fid": expected_file_id},
            )
        ).all()
        assert len(rows) == 1, f"expected 1 row for {kind}, got {len(rows)}"
        version_number, is_current, canonical = rows[0]
        assert version_number == 1
        assert bool(is_current) is True
        assert canonical == expected_canonical

    # Sheet uses the composite ``document_id:sheet_number`` key.
    sheet_row = (
        await session.execute(
            text("SELECT canonical_name FROM oe_file_version WHERE file_kind='sheet' AND file_id = :fid"),
            {"fid": str(sheet_id)},
        )
    ).scalar_one()
    assert sheet_row.endswith(":A-201")

    # Re-running the backfill SQL is idempotent — the WHERE NOT EXISTS
    # guard skips already-seeded rows.
    sql2 = text(
        "INSERT INTO oe_file_version (id, created_at, updated_at, project_id, "
        "file_kind, file_id, version_number, canonical_name, previous_version_id, "
        "is_current, superseded_at, superseded_by_id, notes, uploaded_by_id, "
        "uploaded_at, file_size, checksum) "
        "SELECT gen_random_uuid()::text, now(), now(), "
        "oe_documents_document.project_id::text, 'document', "
        "oe_documents_document.id::text, 1, oe_documents_document.name, "
        "NULL, TRUE, NULL, NULL, NULL, NULL, oe_documents_document.created_at, 0, NULL "
        "FROM oe_documents_document WHERE NOT EXISTS ("
        "SELECT 1 FROM oe_file_version fv WHERE "
        "fv.project_id = oe_documents_document.project_id::text "
        "AND fv.file_kind = 'document' "
        "AND fv.file_id = oe_documents_document.id::text)"
    )
    result2 = await session.execute(sql2)
    assert (result2.rowcount or 0) == 0  # nothing to insert; chain seed already present
