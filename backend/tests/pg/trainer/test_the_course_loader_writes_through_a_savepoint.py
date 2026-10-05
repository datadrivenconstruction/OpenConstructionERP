# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the course loader writes ``oe_trainer_course`` through ``SqlCourseStore``.

The unit suite proves the loader's decisions against an in-memory store; this
file proves the writes on a real database, where the failure that matters
lives: one failed INSERT leaves an ``AsyncSession`` in pending-rollback, and
without the per-file SAVEPOINT every later file and the boot's final commit
would fail with it. Two workers booting at once both read "no row" for the
same course and version, and the second INSERT hits
``uq_oe_trainer_course_course_key_version``; that race is staged here.

Everything runs inside the per-test transaction ``pg_session`` rolls back.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from app.modules.trainer.loader import SqlCourseStore, StoredCourse, load_courses_dir
from app.modules.trainer.models import TrainerCourse

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "trainer" / "course_fixture_v1.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"), parse_float=Decimal)


def _write(directory: Path, name: str, data: dict[str, Any]) -> None:
    (directory / name).write_text(json.dumps(data, default=str, ensure_ascii=False), encoding="utf-8")


async def _rows(session) -> dict[tuple[str, str], TrainerCourse]:
    result = await session.execute(sa.select(TrainerCourse).execution_options(populate_existing=True))
    return {(r.course_key, r.version): r for r in result.scalars()}


async def test_an_invalid_file_is_stored_and_the_session_goes_on(pg_session, tmp_path: Path) -> None:
    bad = _fixture()
    bad["id"] = "fx-pg-bad"
    bad["title"] = "T" * 400  # wider than the column: must be cut, not overflow
    bad["tasks"][0]["opens"] = "boq.nothing"
    _write(tmp_path, "course_a_v1.json", bad)
    _write(tmp_path, "course_b_v1.json", _fixture())

    outcomes = await load_courses_dir(SqlCourseStore(pg_session), tmp_path)
    assert [o.status for o in outcomes] == ["invalid", "loaded"]

    rows = await _rows(pg_session)
    invalid = rows[("fx-pg-bad", "1.0.0")]
    valid = rows[(_fixture()["id"], "1.0.0")]
    assert invalid.status == "invalid"
    assert invalid.spec == {}
    assert any("trainer.opens_known_lock" in e for e in invalid.validation_report["error_list"])
    assert valid.status == "active"
    assert valid.spec["id"] == _fixture()["id"]
    await pg_session.commit()
    assert (await pg_session.execute(sa.select(sa.func.count()).select_from(TrainerCourse))).scalar_one() >= 2


class RacingStore(SqlCourseStore):
    """A store that never sees the row a parallel boot just wrote."""

    async def get(self, course_key: str, version: str) -> StoredCourse | None:
        return None


async def test_a_lost_insert_race_spoils_only_its_own_file(pg_session, tmp_path: Path) -> None:
    first = _fixture()
    second = _fixture()
    second["title"] = "Same course and version, other bytes"
    other = _fixture()
    other["id"] = "fx-pg-other"
    _write(tmp_path, "course_a_v1.json", first)
    _write(tmp_path, "course_b_v1.json", second)
    _write(tmp_path, "course_c_v1.json", other)

    outcomes = await load_courses_dir(RacingStore(pg_session), tmp_path)

    assert [o.status for o in outcomes] == ["loaded", "failed", "loaded"]
    assert "uq_oe_trainer_course_course_key_version" in outcomes[1].errors[0]
    rows = await _rows(pg_session)
    assert rows[(first["id"], "1.0.0")].title == first["title"]
    assert ("fx-pg-other", "1.0.0") in rows
    await pg_session.commit()


async def test_a_fixed_file_replaces_its_invalid_row_in_place(pg_session, tmp_path: Path) -> None:
    broken = _fixture()
    broken["tasks"][0]["opens"] = "boq.nothing"
    _write(tmp_path, "course_a_v1.json", broken)
    store = SqlCourseStore(pg_session)
    assert [o.status for o in await load_courses_dir(store, tmp_path)] == ["invalid"]

    _write(tmp_path, "course_a_v1.json", _fixture())
    assert [o.status for o in await load_courses_dir(store, tmp_path)] == ["loaded"]

    rows = await _rows(pg_session)
    key = (_fixture()["id"], "1.0.0")
    assert rows[key].status == "active"
    assert rows[key].validation_report["error_list"] == []
    assert len([k for k in rows if k == key]) == 1


async def test_new_bytes_under_a_valid_version_leave_the_row_alone(pg_session, tmp_path: Path) -> None:
    _write(tmp_path, "course_a_v1.json", _fixture())
    store = SqlCourseStore(pg_session)
    await load_courses_dir(store, tmp_path)
    key = (_fixture()["id"], "1.0.0")
    before = (await _rows(pg_session))[key].sha256

    edited = _fixture()
    edited["title"] = "Edited without a bump"
    _write(tmp_path, "course_a_v1.json", edited)
    outcomes = await load_courses_dir(store, tmp_path)

    assert [o.status for o in outcomes] == ["refused"]
    row = (await _rows(pg_session))[key]
    assert row.sha256 == before
    assert row.status == "active"
    assert row.title == _fixture()["title"]


async def test_the_startup_hook_loads_through_one_session_and_commits(pg_session, tmp_path: Path, monkeypatch) -> None:
    """``on_startup`` with the flag on: session factory, load, commit, as the boot runs it."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.config import get_settings
    from app.modules import trainer
    from app.modules.trainer import loader

    bad = _fixture()
    bad["id"] = "fx-pg-start-bad"
    bad["tasks"][0]["opens"] = "boq.nothing"
    _write(tmp_path, "course_a_v1.json", bad)
    _write(tmp_path, "course_b_v1.json", _fixture())

    factory = async_sessionmaker(
        bind=await pg_session.connection(),
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr(loader, "_session_factory", lambda: factory)
    monkeypatch.setenv("OE_ACADEMY_MODE", "true")
    monkeypatch.setenv("OE_TRAINER_COURSES_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        await trainer.on_startup()
    finally:
        get_settings.cache_clear()

    rows = await _rows(pg_session)
    assert rows[("fx-pg-start-bad", "1.0.0")].status == "invalid"
    assert rows[(_fixture()["id"], "1.0.0")].status == "active"
