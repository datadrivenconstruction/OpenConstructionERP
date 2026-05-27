# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the file_tags module (W4).

Coverage:

* **slugify** — pure helper: lowercase, non-alnum → underscore, no
                leading/trailing underscore.
* **CRUD**   — create, list, update, delete cycle on the DB.
* **Assign / unassign** — bulk attach/detach; cascade on tag delete.
* **tags_for_file / tags_by_files** — both reads return the expected
                rows for a known file id (or zero rows for one that's
                never been tagged).
* **Seed defaults idempotency** — calling twice yields the same total
                count and the same tag set.

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-file-tags-"))
_TMP_DB = _TMP_DIR / "file_tags.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

import app.modules.file_tags.models  # noqa: E402, F401

# Ensure ORM registration.
import app.modules.projects.models  # noqa: E402, F401
import app.modules.users.models  # noqa: E402, F401
from app.modules.file_tags.models import FileTagAssignment  # noqa: E402
from app.modules.file_tags.schemas import (  # noqa: E402
    TagCreate,
    TagUpdate,
    slugify,
)
from app.modules.file_tags.service import (  # noqa: E402
    assign_tag,
    create_tag,
    delete_tag,
    list_tags,
    remove_assignments_for_file,
    seed_default_tags,
    tags_by_files,
    tags_for_file,
    unassign_tag,
    update_tag,
)

# ── Pure: slugify ─────────────────────────────────────────────────────────


def test_slugify_lowercases_and_replaces_non_alnum() -> None:
    assert slugify("Mechanical & Plumbing") == "mechanical_plumbing"
    assert slugify("Phase 1 — Design") == "phase_1_design"
    assert slugify("S-101 Rev A") == "s_101_rev_a"


def test_slugify_strips_edges_and_collapses_underscores() -> None:
    assert slugify("__hello_world__") == "hello_world"
    assert slugify("***ABC***") == "abc"


def test_slugify_empty_input_falls_back() -> None:
    assert slugify("") == "tag"
    assert slugify("@@@") == "tag"


# ── DB fixtures ───────────────────────────────────────────────────────────


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
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"ft-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Tag Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="File Tags Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


# ── CRUD ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_tag_persists_row_with_normalised_color(db_session) -> None:
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(
            project_id=project_id,
            display_name="Architectural",
            color="#abc",
            category="discipline",
        ),
        user_id=None,
    )
    assert tag.name == "architectural"
    assert tag.display_name == "Architectural"
    assert tag.color == "#aabbcc"  # short hex expanded to full form
    assert tag.category == "discipline"


@pytest.mark.asyncio
async def test_create_tag_rejects_duplicate_slug(db_session) -> None:
    project_id = await _seed_project(db_session)
    payload = TagCreate(
        project_id=project_id,
        display_name="Civil",
        color="#10b981",
    )
    await create_tag(db_session, payload, user_id=None)
    with pytest.raises(ValueError, match="already exists"):
        await create_tag(db_session, payload, user_id=None)


@pytest.mark.asyncio
async def test_list_tags_filters_by_category(db_session) -> None:
    project_id = await _seed_project(db_session)
    await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="A1", category="discipline"),
        user_id=None,
    )
    await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="P1", category="phase"),
        user_id=None,
    )

    disciplines = await list_tags(db_session, project_id, category="discipline")
    assert len(disciplines) == 1
    assert disciplines[0].name == "a1"


@pytest.mark.asyncio
async def test_update_tag_changes_display_name_and_color(db_session) -> None:
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Old"),
        user_id=None,
    )
    updated = await update_tag(
        db_session,
        project_id,
        tag.id,
        TagUpdate(display_name="New", color="#ff0000"),
    )
    assert updated is not None
    assert updated.display_name == "New"
    assert updated.color == "#ff0000"
    # Slug stays the same — renames are display-only.
    assert updated.name == "old"


@pytest.mark.asyncio
async def test_delete_tag_returns_true_for_known_id_false_for_unknown(db_session) -> None:
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Discardable"),
        user_id=None,
    )
    assert await delete_tag(db_session, project_id, tag.id) is True
    assert await delete_tag(db_session, project_id, tag.id) is False


# ── Assignment ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_three_files_then_list_by_file(db_session) -> None:
    """Assign tag to 3 files → list by file returns all 3 assignments."""
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Foundations"),
        user_id=None,
    )

    file_ids = [str(uuid.uuid4()) for _ in range(3)]
    result = await assign_tag(db_session, project_id, tag.id, "document", file_ids, user_id=None)
    assert result.requested == 3
    assert result.changed == 3
    assert result.already_done == 0

    # tags_for_file returns the tag for every assigned file.
    for fid in file_ids:
        rows = await tags_for_file(db_session, project_id, "document", fid)
        assert len(rows) == 1
        assert rows[0].id == tag.id


@pytest.mark.asyncio
async def test_unassign_one_leaves_only_two(db_session) -> None:
    """Unassign 1 → only 2 remain (matches the spec acceptance test)."""
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="MEP"),
        user_id=None,
    )
    file_ids = [str(uuid.uuid4()) for _ in range(3)]
    await assign_tag(db_session, project_id, tag.id, "sheet", file_ids, user_id=None)

    # Detach the first id.
    result = await unassign_tag(db_session, project_id, tag.id, "sheet", file_ids[:1])
    assert result.changed == 1

    # The remaining two are still tagged.
    for fid in file_ids[1:]:
        rows = await tags_for_file(db_session, project_id, "sheet", fid)
        assert len(rows) == 1
    # The detached one is not.
    rows = await tags_for_file(db_session, project_id, "sheet", file_ids[0])
    assert rows == []


@pytest.mark.asyncio
async def test_assign_is_idempotent(db_session) -> None:
    """Re-assigning the same ids increments already_done, not changed."""
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Closeout"),
        user_id=None,
    )
    fid = str(uuid.uuid4())
    first = await assign_tag(db_session, project_id, tag.id, "report", [fid], user_id=None)
    second = await assign_tag(db_session, project_id, tag.id, "report", [fid], user_id=None)
    assert first.changed == 1
    assert second.changed == 0
    assert second.already_done == 1


@pytest.mark.asyncio
async def test_delete_tag_cascades_assignments(db_session) -> None:
    """Deleting the tag cascades to oe_file_tag_assignment."""
    from sqlalchemy import select

    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Doomed"),
        user_id=None,
    )
    fids = [str(uuid.uuid4()) for _ in range(4)]
    await assign_tag(db_session, project_id, tag.id, "document", fids, user_id=None)

    # Sanity: 4 assignments exist.
    count_before = (
        (await db_session.execute(select(FileTagAssignment).where(FileTagAssignment.tag_id == tag.id))).scalars().all()
    )
    assert len(count_before) == 4

    await delete_tag(db_session, project_id, tag.id)

    count_after = (
        (await db_session.execute(select(FileTagAssignment).where(FileTagAssignment.tag_id == tag.id))).scalars().all()
    )
    assert count_after == []


@pytest.mark.asyncio
async def test_tags_by_files_bulk_lookup(db_session) -> None:
    """tags_by_files returns {file_id: [tags]} for an arbitrary id set."""
    project_id = await _seed_project(db_session)
    tag_a = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Arch"),
        user_id=None,
    )
    tag_b = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="Struct"),
        user_id=None,
    )
    fid1, fid2, fid3 = (str(uuid.uuid4()) for _ in range(3))
    await assign_tag(db_session, project_id, tag_a.id, "document", [fid1, fid2], user_id=None)
    await assign_tag(db_session, project_id, tag_b.id, "document", [fid2, fid3], user_id=None)

    out = await tags_by_files(db_session, project_id, "document", [fid1, fid2, fid3])
    assert {t.name for t in out[fid1]} == {"arch"}
    assert {t.name for t in out[fid2]} == {"arch", "struct"}
    assert {t.name for t in out[fid3]} == {"struct"}


@pytest.mark.asyncio
async def test_remove_assignments_for_file_drops_every_link(db_session) -> None:
    project_id = await _seed_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(project_id=project_id, display_name="To-prune"),
        user_id=None,
    )
    fid = str(uuid.uuid4())
    await assign_tag(db_session, project_id, tag.id, "photo", [fid], user_id=None)

    removed = await remove_assignments_for_file(db_session, "photo", fid)
    assert removed == 1
    assert await tags_for_file(db_session, project_id, "photo", fid) == []


# ── Seed defaults idempotency ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_defaults_first_call_creates_all(db_session) -> None:
    project_id = await _seed_project(db_session)
    result = await seed_default_tags(db_session, project_id, user_id=None)
    assert result.created > 0
    assert result.existing == 0
    assert result.total == result.created
    # We expect at least 4 disciplines + 4 phases.
    assert result.total >= 8


@pytest.mark.asyncio
async def test_seed_defaults_second_call_is_idempotent(db_session) -> None:
    """Calling seed-defaults twice yields the same tags (specified)."""
    project_id = await _seed_project(db_session)
    first = await seed_default_tags(db_session, project_id, user_id=None)
    second = await seed_default_tags(db_session, project_id, user_id=None)

    assert first.total == second.total
    assert second.created == 0
    assert second.existing == first.total
    # The exact same slugs come back.
    first_names = {t.name for t in first.tags}
    second_names = {t.name for t in second.tags}
    assert first_names == second_names
