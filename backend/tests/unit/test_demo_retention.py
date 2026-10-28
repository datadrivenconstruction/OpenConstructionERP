# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :mod:`app.core.demo_retention`.

This job deletes user data, so the suite pins the dangerous cases rather than
the happy path. What is covered, and why each one is here:

* A self-hosted install is never armed - neither by the retention window on
  its own, nor by the demo flag on its own.
* Seeded demo content survives at any age. The five demo projects are the
  reason the demo exists; a sweep that eats them has destroyed the thing it
  was protecting.
* A file inside the window survives.
* A blob another live row still points at survives, including when the other
  pointer is a recycle-bin snapshot whose own row is already gone.
* A row with no blob, and a blob with no row, are each handled without a
  crash - and the blob with no row is left strictly alone.
* A path outside the data directory is never unlinked.
* Two runs remove the same set: nothing the second time, with the on-disk
  file set unchanged.
* The database tripwire of the read-only demo does not refuse the sweep's own
  deletes even when a request write scope is bound to the context.
* The negative control: the sweep, called through its real entry point with
  its real arming, does delete an aged visitor upload - row and bytes. Without
  it a green suite would be indistinguishable from a job that does nothing.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import demo_retention
from app.core.demo_retention import (
    UPLOAD_SOURCES,
    demo_retention_enabled,
    is_seeded_row,
    register_jobs,
    sweep_demo_uploads,
)
from app.modules.bim_hub.models import BIMModel
from app.modules.documents.models import Document, ProjectPhoto
from app.modules.file_trash.models import FileTrash
from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffDocument
from app.modules.users.models import User
from tests._pg import transactional_session

_ENV_KEYS = ("OE_DEMO_READ_ONLY", "OE_DEMO_UPLOADS_RETENTION_DAYS")


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_demo_env():
    """Leave the process with retention disarmed, before and after every test.

    ``get_settings`` is an ``lru_cache``, so restoring the environment is not
    enough on its own - the cache has to be cleared too, explicitly, rather
    than relying on the order fixture finalizers happen to run in.
    """
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    get_settings.cache_clear()
    yield
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    get_settings.cache_clear()
    assert demo_retention_enabled() is False


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the whole platform's data directory at a throwaway tree.

    Everything the sweep may unlink has to live under this root, because the
    containment check refuses to touch anything else.
    """
    from app.core.storage import reset_storage_backend_cache

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("OE_DATA_DIR", str(root))
    get_settings.cache_clear()
    reset_storage_backend_cache()
    yield root
    reset_storage_backend_cache()


@pytest.fixture
def armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both halves of the switch, the way the hosted demo sets them."""
    monkeypatch.setenv("OE_DEMO_READ_ONLY", "true")
    monkeypatch.setenv("OE_DEMO_UPLOADS_RETENTION_DAYS", "14")
    get_settings.cache_clear()
    assert demo_retention_enabled() is True


# ── Builders ────────────────────────────────────────────────────────────────


async def _project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"retention-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Retention Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Retention Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


def _blob(root: Path, name: str, *, size: int = 2048) -> Path:
    """Write a file inside the data directory and return its path."""
    target = root / "uploads" / "documents" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size)
    return target


def _ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _document(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    path: Path | str,
    age_days: int,
    seeded: bool = False,
) -> Document:
    doc = Document(
        project_id=project_id,
        name=Path(str(path)).name,
        category="drawing",
        file_size=1024,
        mime_type="application/pdf",
        file_path=str(path),
        uploaded_by="visitor",
        created_at=_ago(age_days),
        metadata_={"seed": True, "demo": True} if seeded else {},
    )
    session.add(doc)
    await session.flush()
    return doc


async def _takeoff(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    *,
    path: Path | str,
    age_days: int,
    seeded: bool = False,
) -> TakeoffDocument:
    row = TakeoffDocument(
        project_id=project_id,
        owner_id=owner_id,
        filename=Path(str(path)).name,
        file_path=str(path),
        created_at=_ago(age_days),
        metadata_={"seed": True} if seeded else {},
    )
    session.add(row)
    await session.flush()
    return row


async def _bim(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    age_days: int,
    seeded: bool = False,
) -> BIMModel:
    row = BIMModel(
        project_id=project_id,
        name="tower.ifc",
        status="ready",
        created_at=_ago(age_days),
        metadata_={"seed": True, "demo": True} if seeded else {},
    )
    session.add(row)
    await session.flush()
    return row


def _bim_blob(root: Path, project_id: uuid.UUID, model_id: uuid.UUID, *, size: int = 4096) -> Path:
    target = root / "bim" / str(project_id) / str(model_id) / "geometry.dae"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"y" * size)
    return target


def _tree(root: Path) -> set[Path]:
    """Every blob under ``root``, for before/after comparison.

    The run report lives in the same directory and is rewritten on every call,
    including a dry run - that is the point of it - so it is not part of the
    file set a sweep is allowed to change.
    """
    return {p for p in root.rglob("*") if p.is_file() and p.name != demo_retention.REPORT_FILENAME}


# ── Arming ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_self_hosted_install_is_never_swept(session: AsyncSession, data_dir: Path) -> None:
    """No demo flag, no retention window: the sweep reads nothing and deletes nothing."""
    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "somebodys-real-project.pdf")
    doc = await _document(session, project_id, path=blob, age_days=400)

    report = await sweep_demo_uploads(session)

    assert report.armed is False
    assert report.skipped_reason is not None
    assert report.rows_deleted == 0
    assert blob.exists()
    assert await session.get(Document, doc.id) is not None


@pytest.mark.asyncio
async def test_a_retention_window_alone_does_not_arm_a_self_hosted_install(
    session: AsyncSession,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dangerous half of the switch is inert without the half that says
    which deployment this is. This is the fat-fingered env var on somebody's
    own server, and it must do nothing."""
    monkeypatch.setenv("OE_DEMO_UPLOADS_RETENTION_DAYS", "1")
    get_settings.cache_clear()
    assert get_settings().demo_uploads_retention_days == 1
    assert demo_retention_enabled() is False

    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "revit-model-export.pdf")
    doc = await _document(session, project_id, path=blob, age_days=400)

    report = await sweep_demo_uploads(session)

    assert report.armed is False
    assert blob.exists()
    assert await session.get(Document, doc.id) is not None


@pytest.mark.asyncio
async def test_the_demo_flag_alone_does_not_arm_retention(
    session: AsyncSession,
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only demo with no window configured keeps everything, which is
    what every demo did before this policy existed."""
    monkeypatch.setenv("OE_DEMO_READ_ONLY", "true")
    get_settings.cache_clear()
    assert get_settings().demo_read_only is True
    assert demo_retention_enabled() is False

    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "visitor-upload.pdf")
    await _document(session, project_id, path=blob, age_days=400)

    report = await sweep_demo_uploads(session)

    assert report.armed is False
    assert blob.exists()


def test_the_scheduler_never_starts_on_a_deployment_that_is_not_a_demo() -> None:
    """Not merely "the loop finds nothing to do" - there is no loop."""
    assert demo_retention_enabled() is False
    assert register_jobs() is None


# ── The negative control ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_aged_visitor_upload_is_removed_row_and_bytes(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Negative control: the job can actually delete something.

    Driven through the same entry point and the same arming the scheduler
    uses, and asserting on both halves - the row is gone AND the bytes are
    gone. A suite without this one cannot tell a careful policy from a job
    that quietly does nothing.
    """
    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "stranger-takeoff.pdf", size=8192)
    doc = await _document(session, project_id, path=blob, age_days=30)

    report = await sweep_demo_uploads(session)

    assert report.armed is True
    assert report.rows_deleted == 1
    assert report.blobs_deleted == 1
    assert report.bytes_freed == 8192
    assert report.errors == []
    assert not blob.exists()
    assert await session.get(Document, doc.id) is None


# ── What must survive ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_seeded_file_is_never_removed(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Seeded content is the demo. Age does not make it disposable."""
    _user_id, project_id = await _project(session)
    seeded_blob = _blob(data_dir, "seeded-floor-plan.pdf")
    seeded_doc = await _document(session, project_id, path=seeded_blob, age_days=900, seeded=True)

    report = await sweep_demo_uploads(session)

    assert seeded_blob.exists()
    assert await session.get(Document, seeded_doc.id) is not None
    documents = next(o for o in report.sources if o.kind == "document")
    assert documents.rows_kept_seeded == 1
    assert documents.rows_deleted == 0


@pytest.mark.asyncio
async def test_a_seeded_marker_is_read_off_the_row_not_the_filename(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Two files with the same name, one seeded and one not, part ways.

    The distinction is structural. A visitor who uploads a file called
    ``seed.pdf`` gets no protection from it, and a seeded row whose file was
    renamed keeps all of it.
    """
    _user_id, project_id = await _project(session)
    seeded_blob = _blob(data_dir, "renamed-by-a-visitor.pdf")
    decoy_blob = _blob(data_dir, "seed-demo-official.pdf")
    seeded_doc = await _document(session, project_id, path=seeded_blob, age_days=100, seeded=True)
    decoy_doc = await _document(session, project_id, path=decoy_blob, age_days=100)

    await sweep_demo_uploads(session)

    assert seeded_blob.exists()
    assert await session.get(Document, seeded_doc.id) is not None
    assert not decoy_blob.exists()
    assert await session.get(Document, decoy_doc.id) is None


@pytest.mark.asyncio
async def test_a_file_inside_the_window_is_never_removed(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Uploaded yesterday, with a 14-day window: not a candidate at all."""
    _user_id, project_id = await _project(session)
    fresh_blob = _blob(data_dir, "uploaded-yesterday.pdf")
    fresh_doc = await _document(session, project_id, path=fresh_blob, age_days=1)

    report = await sweep_demo_uploads(session)

    assert fresh_blob.exists()
    assert await session.get(Document, fresh_doc.id) is not None
    documents = next(o for o in report.sources if o.kind == "document")
    assert documents.rows_examined == 0


@pytest.mark.asyncio
async def test_the_window_boundary_is_the_configured_one(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """13 days old survives a 14-day window; 15 days old does not."""
    _user_id, project_id = await _project(session)
    inside = _blob(data_dir, "thirteen-days.pdf")
    outside = _blob(data_dir, "fifteen-days.pdf")
    await _document(session, project_id, path=inside, age_days=13)
    await _document(session, project_id, path=outside, age_days=15)

    await sweep_demo_uploads(session)

    assert inside.exists()
    assert not outside.exists()


@pytest.mark.asyncio
async def test_a_row_that_cannot_prove_it_is_a_visitor_upload_is_kept(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Unknown resolves to keep, never to delete.

    A row whose metadata is not a JSON object cannot carry the seed marker, so
    the policy cannot tell what it is - and a record that cannot prove it is
    disposable is not disposable.
    """
    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "unreadable-metadata.pdf")
    doc = await _document(session, project_id, path=blob, age_days=200)
    doc.metadata_ = ["not", "an", "object"]
    await session.flush()

    report = await sweep_demo_uploads(session)

    assert blob.exists()
    assert await session.get(Document, doc.id) is not None
    documents = next(o for o in report.sources if o.kind == "document")
    assert documents.rows_kept_unmarked == 1


# ── Blobs and rows that do not line up ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_row_whose_blob_is_already_gone_is_handled(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """The row goes, the missing blob is counted, nothing raises."""
    _user_id, project_id = await _project(session)
    missing = data_dir / "uploads" / "documents" / "never-written.pdf"
    doc = await _document(session, project_id, path=missing, age_days=60)

    report = await sweep_demo_uploads(session)

    assert report.errors == []
    assert await session.get(Document, doc.id) is None
    documents = next(o for o in report.sources if o.kind == "document")
    assert documents.rows_deleted == 1
    assert documents.blobs_missing == 1
    assert documents.blobs_deleted == 0


@pytest.mark.asyncio
async def test_a_blob_with_no_row_is_left_strictly_alone(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """The sweep is row-driven, and that is a safety property, not an omission.

    A file on disk that no row names may still be referenced by the recycle
    bin, by an upload in flight, or by a module this registry does not cover.
    Reclaiming it is not this job's business, and a sweep that walked the disk
    instead of the tables would delete exactly the files that are hardest to
    get back.
    """
    _user_id, project_id = await _project(session)
    stray = _blob(data_dir, "orphan-nobody-references.dae")

    report = await sweep_demo_uploads(session)

    assert report.errors == []
    assert stray.exists()


@pytest.mark.asyncio
async def test_a_blob_a_live_row_still_points_at_is_not_deleted(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Zero-copy sharing across tables.

    Opening a Project-Files PDF in takeoff references the same bytes rather
    than copying them. When the documents row ages out and the takeoff row has
    not, the bytes have to stay - otherwise the surviving row points at
    nothing.
    """
    user_id, project_id = await _project(session)
    shared = _blob(data_dir, "opened-in-takeoff.pdf")
    old_doc = await _document(session, project_id, path=shared, age_days=90)
    young_takeoff = await _takeoff(session, project_id, user_id, path=shared, age_days=2)

    report = await sweep_demo_uploads(session)

    assert await session.get(Document, old_doc.id) is None
    assert await session.get(TakeoffDocument, young_takeoff.id) is not None
    assert shared.exists()
    documents = next(o for o in report.sources if o.kind == "document")
    assert documents.blobs_kept_referenced == 1
    assert documents.bytes_freed == 0


@pytest.mark.asyncio
async def test_a_blob_the_recycle_bin_still_holds_is_not_deleted(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """A soft-deleted file has no row of its own and is still restorable.

    ``file_trash`` snapshots the row into ``oe_file_trash`` and removes the
    original, so the blob is alive with nothing in its own table pointing at
    it. Here a second, aged row shares that same blob; deleting it would make
    the pending restore restore a broken file.
    """
    user_id, project_id = await _project(session)
    shared = _blob(data_dir, "soft-deleted-then-shared.pdf")
    doomed = await _takeoff(session, project_id, user_id, path=shared, age_days=120)
    session.add(
        FileTrash(
            project_id=project_id,
            original_kind="document",
            original_id=str(uuid.uuid4()),
            canonical_name="soft-deleted-then-shared.pdf",
            payload_json={"file_path": str(shared)},
            trashed_at=_ago(1),
            retention_days=30,
        )
    )
    await session.flush()

    report = await sweep_demo_uploads(session)

    assert await session.get(TakeoffDocument, doomed.id) is None
    assert shared.exists()
    takeoff = next(o for o in report.sources if o.kind == "takeoff")
    assert takeoff.blobs_kept_referenced == 1


@pytest.mark.asyncio
async def test_a_blob_two_doomed_rows_share_is_freed_once(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Both pointers age out, so nothing is left pointing at the bytes."""
    user_id, project_id = await _project(session)
    shared = _blob(data_dir, "both-sides-aged-out.pdf", size=4096)
    await _document(session, project_id, path=shared, age_days=90)
    await _takeoff(session, project_id, user_id, path=shared, age_days=90)

    report = await sweep_demo_uploads(session)

    assert not shared.exists()
    assert report.rows_deleted == 2
    assert report.blobs_deleted == 1
    assert report.bytes_freed == 4096


@pytest.mark.asyncio
async def test_a_path_outside_the_data_directory_is_never_unlinked(
    session: AsyncSession,
    data_dir: Path,
    tmp_path: Path,
    armed: None,
) -> None:
    """Containment, not trust. A stored path can point anywhere - a packaged
    asset, an operator's home directory - and only the active data root is
    ours to delete from."""
    _user_id, project_id = await _project(session)
    outside = tmp_path / "elsewhere" / "not-ours.pdf"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"z" * 512)
    doc = await _document(session, project_id, path=outside, age_days=300)

    report = await sweep_demo_uploads(session)

    assert outside.exists()
    assert await session.get(Document, doc.id) is None
    documents = next(o for o in report.sources if o.kind == "document")
    assert documents.blobs_kept_outside_data_dir == 1


# ── Idempotence and dry runs ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_running_twice_removes_the_same_set_the_second_time(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Which is to say nothing.

    The second report's counts are zero AND the on-disk file set is unchanged -
    a job that crashed on its first statement also reports zero, so the counts
    alone would not tell the two apart.
    """
    user_id, project_id = await _project(session)
    doomed = _blob(data_dir, "goes-on-the-first-run.pdf")
    seeded = _blob(data_dir, "stays-forever.pdf")
    await _document(session, project_id, path=doomed, age_days=60)
    await _document(session, project_id, path=seeded, age_days=60, seeded=True)
    await _takeoff(session, project_id, user_id, path=seeded, age_days=60, seeded=True)

    first = await sweep_demo_uploads(session)
    after_first = _tree(data_dir)

    second = await sweep_demo_uploads(session)
    after_second = _tree(data_dir)

    assert first.rows_deleted == 1
    assert first.blobs_deleted == 1
    assert second.rows_deleted == 0
    assert second.blobs_deleted == 0
    assert second.bytes_freed == 0
    assert second.errors == []
    assert after_second == after_first
    assert seeded in after_second
    assert doomed not in after_first


@pytest.mark.asyncio
async def test_a_dry_run_reports_what_a_real_run_would_free_and_frees_nothing(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """The preview an operator runs first has to be worth trusting: same
    verdict, same byte count, no deletions."""
    user_id, project_id = await _project(session)
    doomed = _blob(data_dir, "would-go.pdf", size=1024)
    shared = _blob(data_dir, "shared-with-a-young-row.pdf", size=2048)
    await _document(session, project_id, path=doomed, age_days=60)
    await _document(session, project_id, path=shared, age_days=60)
    await _takeoff(session, project_id, user_id, path=shared, age_days=1)

    before = _tree(data_dir)
    preview = await sweep_demo_uploads(session, dry_run=True)
    assert _tree(data_dir) == before

    real = await sweep_demo_uploads(session)

    assert preview.dry_run is True
    assert preview.rows_deleted == real.rows_deleted == 2
    assert preview.blobs_deleted == real.blobs_deleted == 1
    assert preview.bytes_freed == real.bytes_freed == 1024
    assert shared.exists()
    assert not doomed.exists()


@pytest.mark.asyncio
async def test_a_dry_run_prices_a_blob_two_doomed_rows_share_the_way_the_real_run_frees_it(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """The two-phase plan exists for this case.

    A real run frees the shared blob once the second of the two rows goes. A
    dry run, where neither row is actually deleted, has to reach the same
    verdict instead of reporting the blob as still referenced.
    """
    user_id, project_id = await _project(session)
    shared = _blob(data_dir, "shared-by-two-doomed-rows.pdf", size=3072)
    await _document(session, project_id, path=shared, age_days=90)
    await _takeoff(session, project_id, user_id, path=shared, age_days=90)

    preview = await sweep_demo_uploads(session, dry_run=True)

    assert shared.exists()
    assert preview.blobs_deleted == 1
    assert preview.bytes_freed == 3072


# ── BIM, the biggest source ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_aged_visitor_bim_model_loses_its_whole_prefix(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """BIM blobs are a storage prefix rather than a single path, and go
    through the configured backend so an S3 demo behaves the same."""
    _user_id, project_id = await _project(session)
    model = await _bim(session, project_id, age_days=45)
    blob = _bim_blob(data_dir, project_id, model.id, size=16384)

    report = await sweep_demo_uploads(session)

    assert not blob.exists()
    assert await session.get(BIMModel, model.id) is None
    bim = next(o for o in report.sources if o.kind == "bim_model")
    assert bim.rows_deleted == 1
    assert bim.blobs_deleted == 1
    assert bim.bytes_freed == 16384


@pytest.mark.asyncio
async def test_a_seeded_bim_model_keeps_its_geometry(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """The seeded models are what the /bim page exists to show."""
    _user_id, project_id = await _project(session)
    model = await _bim(session, project_id, age_days=900, seeded=True)
    blob = _bim_blob(data_dir, project_id, model.id)

    await sweep_demo_uploads(session)

    assert blob.exists()
    assert await session.get(BIMModel, model.id) is not None


# ── Interaction with the read-only demo ─────────────────────────────────────


@pytest.mark.asyncio
async def test_the_sweep_deletes_even_with_a_request_write_scope_bound(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """The demo's database tripwire must not refuse the demo's own housekeeping.

    Retention only ever runs on a deployment where the read-only listener is
    armed, and a context variable propagates into any task created from a
    request. If the sweep inherited a request's write scope it would be
    refused at its first DELETE. It binds "no request in scope" for its own
    duration instead, which is what a scheduler, a seeder and the CLI all run
    with anyway.
    """
    from app.core.demo_read_only import WriteScope, _reset_write_scope, _set_write_scope, install

    install()
    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "deleted-under-a-bound-scope.pdf")
    doc = await _document(session, project_id, path=blob, age_days=60)

    token = _set_write_scope(WriteScope.NONE)
    try:
        report = await sweep_demo_uploads(session)
    finally:
        _reset_write_scope(token)

    assert report.errors == []
    assert report.rows_deleted == 1
    assert not blob.exists()
    assert await session.get(Document, doc.id) is None


# ── The report artifact ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_run_writes_a_report_a_watchdog_can_read(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """Including a dry run and a run that deleted nothing.

    A stale timestamp in this file is the signal that the job stopped, which
    is the failure mode a log line nobody reads does not give anybody.
    """
    import json

    await _project(session)

    report = await sweep_demo_uploads(session, dry_run=True)
    written = json.loads(demo_retention.report_path().read_text(encoding="utf-8"))

    assert demo_retention.report_path().parent == data_dir
    assert written["dry_run"] is True
    assert written["armed"] is True
    assert written["window_days"] == 14
    assert written["rows_deleted"] == 0
    assert written["started_at"] == report.started_at.isoformat()
    assert written["finished_at"] is not None
    assert {s["kind"] for s in written["sources"]} == {s.kind for s in UPLOAD_SOURCES}


@pytest.mark.asyncio
async def test_a_disarmed_run_still_leaves_a_report(
    session: AsyncSession,
    data_dir: Path,
) -> None:
    """Silence and "not my job" have to look different to a watchdog."""
    import json

    await sweep_demo_uploads(session)
    written = json.loads(demo_retention.report_path().read_text(encoding="utf-8"))

    assert written["armed"] is False
    assert written["skipped_reason"]


# ── Registry invariants ─────────────────────────────────────────────────────


def test_every_registered_source_can_answer_whether_it_is_seeded() -> None:
    """Membership requires the row's own metadata column.

    A model that inherits the answer from a parent, or has none, would make
    "no marker found" mean "not seeded", and that is the reading that deletes
    somebody's file. Such a model belongs in ``EXCLUDED_SOURCES`` with a
    reason, not in the registry.
    """
    for source in UPLOAD_SOURCES:
        model = source.load_model()
        assert hasattr(model, "metadata_"), f"{source.kind} has no metadata column"
        assert hasattr(model, "created_at"), f"{source.kind} has no created_at"
        assert source.path_attrs or source.prefix_for is not None, f"{source.kind} points at no blob"
        for attr in source.path_attrs:
            assert hasattr(model, attr), f"{source.kind} has no column {attr}"


def test_the_seed_marker_reader_treats_an_unanswerable_row_as_unknown() -> None:
    class _Marked:
        metadata_ = {"seed": True}

    class _MarkerString:
        metadata_ = {"seed": "dwg_takeoff_demo_seed"}

    class _Visitor:
        metadata_: dict = {}

    class _Falsy:
        metadata_ = {"seed": False, "demo": False}

    class _NoColumn:
        pass

    class _NotAnObject:
        metadata_ = "seed"

    assert is_seeded_row(_Marked()) is True
    assert is_seeded_row(_MarkerString()) is True
    assert is_seeded_row(_Visitor()) is False
    assert is_seeded_row(_Falsy()) is False
    assert is_seeded_row(_NoColumn()) is None
    assert is_seeded_row(_NotAnObject()) is None


@pytest.mark.asyncio
async def test_photos_carry_their_thumbnail_with_them(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """A source with two path columns frees both."""
    _user_id, project_id = await _project(session)
    full = _blob(data_dir, "site-photo.jpg", size=1024)
    thumb = _blob(data_dir, "site-photo-thumb.jpg", size=256)
    photo = ProjectPhoto(
        project_id=project_id,
        filename="site-photo.jpg",
        file_path=str(full),
        thumbnail_path=str(thumb),
        created_at=_ago(60),
        metadata_={},
    )
    session.add(photo)
    await session.flush()

    report = await sweep_demo_uploads(session)

    assert not full.exists()
    assert not thumb.exists()
    photos = next(o for o in report.sources if o.kind == "photo")
    assert photos.blobs_deleted == 2
    assert photos.bytes_freed == 1280
    assert (await session.execute(select(ProjectPhoto.id).where(ProjectPhoto.id == photo.id))).first() is None


# ── The production entry point ──────────────────────────────────────────────


class _FixedSessionFactory:
    """Hand ``run_sweep_once`` the test's own session instead of a real one.

    The wrapper must not close it: the suite's transactional session owns its
    own lifetime and closing it here would take the rollback with it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> _FixedSessionFactory:
        return self

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_the_entry_point_the_scheduler_calls_actually_deletes(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scheduler and the CLI both go through ``run_sweep_once``, not
    through ``sweep_demo_uploads`` directly. A suite that only ever calls the
    inner function proves nothing about the code that runs in production."""
    import app.database

    monkeypatch.setattr(app.database, "async_session_factory", _FixedSessionFactory(session))
    _user_id, project_id = await _project(session)
    blob = _blob(data_dir, "visitor.pdf", size=8192)
    doc = await _document(session, project_id, path=blob, age_days=40)

    report = await demo_retention.run_sweep_once()

    assert report.armed is True
    assert report.failed is False
    assert report.rows_deleted == 1
    assert report.bytes_freed == 8192
    assert not blob.exists()
    assert await session.get(Document, doc.id) is None


@pytest.mark.asyncio
async def test_a_crashed_sweep_is_reported_as_a_failure_not_as_nothing_to_do(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watchdog has to tell "this is not a demo" from "the sweep blew up".

    Both used to surface as ``armed: false`` with a reason in the same field,
    which means the artifact written by the component that noticed the failure
    is the one nobody can act on.
    """
    import json

    import app.database

    def _explode() -> None:
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(app.database, "async_session_factory", _explode)

    report = await demo_retention.run_sweep_once()

    assert report.failed is True
    assert "database is on fire" in (report.failure or "")
    assert report.skipped_reason is None
    assert report.armed is True, "the deployment did want this run; it just did not get one"

    written = json.loads(demo_retention.report_path().read_text(encoding="utf-8"))
    assert written["failed"] is True
    assert written["skipped_reason"] is None


def test_the_cli_separates_a_failure_from_a_deployment_that_is_not_a_demo(
    data_dir: Path,
    armed: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exit 1 means "I was asked and I could not", exit 2 means "nothing was
    asked of me". A self-hosted install must never page anybody."""
    import scripts.demo_retention_sweep as cli

    async def _failed() -> demo_retention.RetentionReport:
        return demo_retention.RetentionReport(
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            dry_run=False,
            window_days=14,
            armed=True,
            failure="sweep failed: database is on fire",
        )

    monkeypatch.setattr(cli, "run_sweep_once", lambda **_kw: _failed())
    assert cli.main([]) == 1
    assert "database is on fire" in capsys.readouterr().err

    monkeypatch.setattr(cli, "demo_retention_enabled", lambda: False)
    assert cli.main([]) == 2


# ── Backlog and unmeasurable storage ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_capped_source_says_so_instead_of_looking_finished(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
) -> None:
    """``rows_deleted: 1000`` on its own cannot tell a finished source from
    one that stopped at the cap with more backlog behind it."""
    _user_id, project_id = await _project(session)
    for name in ("one.pdf", "two.pdf"):
        await _document(session, project_id, path=_blob(data_dir, name), age_days=40)

    capped = await sweep_demo_uploads(session, max_rows_per_source=1)
    docs = next(o for o in capped.sources if o.kind == "document")
    assert docs.capped is True
    assert capped.capped is True
    assert docs.rows_deleted == 1

    finished = await sweep_demo_uploads(session, max_rows_per_source=50)
    docs = next(o for o in finished.sources if o.kind == "document")
    assert docs.capped is False
    assert finished.capped is False
    assert docs.rows_deleted == 1


@pytest.mark.asyncio
async def test_a_prefix_that_cannot_be_sized_is_still_deleted_and_reported(
    session: AsyncSession,
    data_dir: Path,
    armed: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The size probe is not a permission slip.

    By the time the blobs are removed the row is already deleted and
    committed, so a probe failure that skipped the delete would strand the
    largest class of blob on the disk forever - and report it as
    ``blobs_missing``, which says the opposite of what happened.
    """
    from app.core.storage import get_storage_backend

    _user_id, project_id = await _project(session)
    model = await _bim(session, project_id, age_days=45)
    blob = _bim_blob(data_dir, project_id, model.id, size=16384)

    async def _cannot_list(*_args: object, **_kwargs: object) -> list[tuple[str, int]]:
        raise OSError("storage backend is unreachable")

    monkeypatch.setattr(get_storage_backend(), "list_prefix", _cannot_list)

    report = await sweep_demo_uploads(session)

    assert not blob.exists(), "an unmeasurable prefix must still be deleted"
    assert await session.get(BIMModel, model.id) is None
    bim = next(o for o in report.sources if o.kind == "bim_model")
    assert bim.blobs_missing == 0, "the prefix was there; reporting it as missing would be a lie"
    assert any("could not size" in err for err in bim.errors)
    assert report.errors, "the run has to surface it, not swallow it"
