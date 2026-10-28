# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Demo document bytes are stored once per install and outlive a sibling deletion.

Every demo project is handed the same native CAD sources, and the seeder used to
write them into a folder per project. One eighteen megabyte coordinated model was
therefore on disk once per project, and a seeded install spent most of its size
repeating a handful of files. The bytes now go to a content-addressed store that
the whole install shares, which is what makes the properties below matter rather
than being pedantry about a seeder.

Sharing one file between rows turns an ordinary deletion into a way to lose
somebody else's document. ``DocumentService.delete_document`` unlinked the blob
whenever it removed a row, so deleting one project's copy of the shared model
would have taken the file away from every other project, leaving rows that look
healthy in every listing and answer 404 on download. That guard is asserted here,
against rows in a database, rather than beside the seeder: a unit test over the
helper would keep passing the day ``delete_document`` stopped calling it.

The idempotency half is the other reason this file exists. A seeder that is safe
to run twice has to be safe when the first run died halfway, so a row whose file
has gone is repaired instead of skipped, and a blob already in place is not
rewritten. Both directions are checked, because a seeder that rewrote every blob
on every run would pass a test that only counted files.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.modules.documents.models import Document
from app.modules.documents.service import DocumentService
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.scripts import seed_demo_assets

# One entry, attached to every project, standing in for the native CAD sources
# the real bundles carry. ``kind="asset"`` resolves against the seeder's assets
# folder, which the fixture below redirects into the temporary tree.
_ENTRY = {
    "kind": "asset",
    "src": "shared_source.bin",
    "name": "Coordinated model source.rvt",
    "category": "model",
    "mime": "application/octet-stream",
    "tags": ["bim"],
    "description": "Native source model",
}

_BYTES = b"a genuine looking payload that two projects both point at" * 64


@pytest.fixture
def quiet_document_deletes():
    """Unsubscribe the ``documents.document.deleted`` handlers for one test.

    All three of them open a session of their own and commit it, which is right
    in production and wrong in this lane: ``pg_session`` hands out a savepoint
    joined to its own connection and never binds ``async_session_factory`` to
    the embedded cluster, so a detached handler reaches for a database that is
    not there. The failure is not confined to the test that triggers it, which
    is why ``no_detached_subscribers`` in this package's conftest exists; this
    fixture is the same measure for a different event. The subscribers are not
    what is under test here and they are not broken.
    """
    from app.core.events import event_bus

    name = "documents.document.deleted"
    removed = list(event_bus._handlers.get(name, []))
    for fn in removed:
        event_bus.unsubscribe(name, fn)
    try:
        yield
    finally:
        for fn in removed:
            event_bus.subscribe(name, fn)


@pytest.fixture
def demo_store(tmp_path, monkeypatch):
    """Point the seeder's sources and the upload root into a temporary tree."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "shared_source.bin").write_bytes(_BYTES)
    monkeypatch.setattr(seed_demo_assets, "ASSETS", assets)

    uploads = tmp_path / "uploads"
    monkeypatch.setattr("app.modules.documents.service.UPLOAD_BASE", uploads)
    return uploads


@pytest.fixture
async def two_projects(pg_session):
    """Two projects that will be handed the same document entry."""
    owner = User(
        email=f"shared-blob-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Shared blob owner",
    )
    pg_session.add(owner)
    await pg_session.flush()
    projects = [
        Project(name="Shared blob project A", owner_id=owner.id, currency="EUR"),
        Project(name="Shared blob project B", owner_id=owner.id, currency="EUR"),
    ]
    for project in projects:
        pg_session.add(project)
    await pg_session.flush()
    return [p.id for p in projects]


def _blobs(uploads: Path) -> list[Path]:
    """Every file in the shared store, ignoring interrupted writes."""
    shared = uploads / seed_demo_assets._SHARED_BLOB_DIRNAME
    if not shared.is_dir():
        return []
    return sorted(p for p in shared.iterdir() if p.is_file() and not p.name.endswith(".tmp"))


async def _attach(session, pid: uuid.UUID) -> int:
    return await seed_demo_assets._attach_documents(session, pid, "seed", [dict(_ENTRY)], "bundle")


async def _rows(session) -> list[Document]:
    return list((await session.execute(select(Document))).scalars().all())


# ── One copy of the bytes, one row per project ──────────────────────────────


async def test_two_projects_share_one_file(pg_session, demo_store, two_projects) -> None:
    """The same source attached to two projects is stored once, not twice."""
    for pid in two_projects:
        assert await _attach(pg_session, pid) == 1

    blobs = _blobs(demo_store)
    assert len(blobs) == 1, f"expected one shared blob, found {[b.name for b in blobs]}"
    assert blobs[0].read_bytes() == _BYTES

    rows = await _rows(pg_session)
    assert len(rows) == 2
    assert {r.project_id for r in rows} == set(two_projects)
    assert len({r.file_path for r in rows}) == 1
    assert rows[0].file_path == str(blobs[0])
    assert all(r.file_size == len(_BYTES) for r in rows)


async def test_the_blob_is_named_after_its_own_contents(pg_session, demo_store, two_projects) -> None:
    """The store can be verified with a hash function and nothing else.

    This is the property that keeps a demo install an ordinary directory anybody
    can copy: the name of every file is a prefix of the digest of that file, so
    the whole store can be checked without running our code.
    """
    await _attach(pg_session, two_projects[0])
    blob = _blobs(demo_store)[0]
    assert blob.stem == hashlib.sha256(_BYTES).hexdigest()[:32]
    assert blob.suffix == ".rvt"


# ── Twice-safe, including after a run that died halfway ─────────────────────


async def test_a_second_run_neither_duplicates_nor_rewrites(pg_session, demo_store, two_projects) -> None:
    """Re-seeding leaves the store and the rows exactly as they were."""
    for pid in two_projects:
        await _attach(pg_session, pid)
    first = _blobs(demo_store)
    stamp = first[0].stat().st_mtime_ns
    paths_before = {(r.id, r.file_path) for r in await _rows(pg_session)}

    for pid in two_projects:
        assert await _attach(pg_session, pid) == 1

    assert [b.name for b in _blobs(demo_store)] == [b.name for b in first]
    assert _blobs(demo_store)[0].stat().st_mtime_ns == stamp, "an untouched blob was rewritten"
    assert {(r.id, r.file_path) for r in await _rows(pg_session)} == paths_before
    assert len(await _rows(pg_session)) == 2


async def test_a_row_whose_file_vanished_is_repaired(pg_session, demo_store, two_projects) -> None:
    """A row must never be left pointing at a file that is not there.

    This is the state an install is in when the process died between writing the
    blob and committing the row, or when somebody cleaned the uploads folder out.
    The old seeder saw a row, called the entry done, and left that download
    broken for good.
    """
    for pid in two_projects:
        await _attach(pg_session, pid)
    blob = _blobs(demo_store)[0]
    blob.unlink()
    assert not _blobs(demo_store)

    for pid in two_projects:
        assert await _attach(pg_session, pid) == 1

    restored = _blobs(demo_store)
    assert len(restored) == 1
    assert restored[0].read_bytes() == _BYTES
    for row in await _rows(pg_session):
        assert Path(row.file_path).is_file(), f"{row.id} still points at nothing"


# ── Deleting one document does not delete another's bytes ───────────────────


async def test_deleting_one_document_keeps_the_shared_file(
    pg_session,
    demo_store,
    two_projects,
    quiet_document_deletes,
) -> None:
    """The last reference removes the file; every earlier one leaves it alone."""
    for pid in two_projects:
        await _attach(pg_session, pid)
    rows = await _rows(pg_session)
    blob = Path(rows[0].file_path)
    assert blob.is_file()

    service = DocumentService(pg_session)
    await service.delete_document(rows[0].id)
    await pg_session.flush()

    assert blob.is_file(), "deleting one project's row took the other project's bytes"
    survivors = await _rows(pg_session)
    assert len(survivors) == 1
    assert Path(survivors[0].file_path).is_file()

    await service.delete_document(survivors[0].id)
    await pg_session.flush()

    assert not blob.exists(), "the last reference should have removed the file"


# -- An install that predates the store reclaims on its next seed -------------


def _legacy_copy(uploads: Path, pid: uuid.UUID, name: str) -> Path:
    """Write the per-project copy an older install would be holding."""
    folder = uploads / str(pid)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{uuid.uuid4().hex[:12]}_{name}"
    dest.write_bytes(_BYTES)
    return dest


async def _legacy_row(session, pid: uuid.UUID, path: Path) -> Document:
    """The Document row that older install would have written beside it."""
    row = Document(
        id=seed_demo_assets._u(str(pid), "doc", _ENTRY["name"]),
        project_id=pid,
        name=_ENTRY["name"],
        category="model",
        file_size=len(_BYTES),
        mime_type="application/octet-stream",
        file_path=str(path),
        uploaded_by="seed",
        tags=[],
        metadata_={"source": "demo_asset_seed"},
    )
    session.add(row)
    await session.flush()
    return row


async def test_per_project_copies_are_adopted_on_the_next_seed(pg_session, demo_store, two_projects) -> None:
    """Healthy rows in per-project folders are moved into the store, not skipped.

    Without this the change would only ever pay on a data directory that starts
    empty, because the idempotency check finds a row whose file is right where
    it says it is and leaves it alone.
    """
    legacy = [_legacy_copy(demo_store, pid, _ENTRY["name"]) for pid in two_projects]
    for pid, path in zip(two_projects, legacy, strict=True):
        await _legacy_row(pg_session, pid, path)
    assert all(p.is_file() for p in legacy)
    assert not _blobs(demo_store)

    for pid in two_projects:
        assert await _attach(pg_session, pid) == 1

    blobs = _blobs(demo_store)
    assert len(blobs) == 1, f"two copies should have collapsed to one, found {[b.name for b in blobs]}"
    rows = await _rows(pg_session)
    assert len(rows) == 2, "adoption must not create a second row"
    assert {r.file_path for r in rows} == {str(blobs[0])}
    assert all(not p.exists() for p in legacy), "the per-project copies were not reclaimed"


async def test_a_copy_another_row_still_names_is_kept(pg_session, demo_store, two_projects) -> None:
    """Adoption removes the old file only when nothing else points at it.

    A second row naming the same path is exactly the case where deleting it
    would break a document this seeder does not own.
    """
    pid, other_pid = two_projects
    legacy = _legacy_copy(demo_store, pid, _ENTRY["name"])
    await _legacy_row(pg_session, pid, legacy)
    bystander = Document(
        id=uuid.uuid4(),
        project_id=other_pid,
        name="Someone else's document.rvt",
        category="model",
        file_size=len(_BYTES),
        mime_type="application/octet-stream",
        file_path=str(legacy),
        uploaded_by="user",
        tags=[],
        metadata_={},
    )
    pg_session.add(bystander)
    await pg_session.flush()

    assert await _attach(pg_session, pid) == 1

    assert legacy.is_file(), "a file another document still names was deleted"
    await pg_session.refresh(bystander)
    assert bystander.file_path == str(legacy)
    assert len(_blobs(demo_store)) == 1
