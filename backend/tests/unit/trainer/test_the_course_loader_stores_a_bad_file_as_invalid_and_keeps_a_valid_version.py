# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The course loader, with the database replaced by an in-memory store.

Decision 26: an invalid course file is stored with ``status="invalid"`` and its
error list, so an admin sees why, and it is never offered to learners. The boot
never crashes on a file. Same bytes again change nothing; changed bytes under a
version that is stored valid are refused with ``trainer.version_not_bumped`` and
the valid row stays. The PostgreSQL half (``SqlCourseStore``, the savepoint) is
``tests/pg/trainer/test_the_course_loader_writes_through_a_savepoint.py``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.modules.trainer import validators
from app.modules.trainer.loader import (
    CourseRecord,
    StoredCourse,
    load_courses_dir,
    parse_course_bytes,
    resolve_courses_dir,
    validate_course,
)
from app.modules.trainer.spec import COLUMN_LIMITS

BACKEND_DIR = Path(__file__).resolve().parents[3]
FIXTURE = BACKEND_DIR / "tests" / "fixtures" / "trainer" / "course_fixture_v1.json"


class FakeStore:
    """In-memory :class:`app.modules.trainer.loader.CourseStore`."""

    def __init__(self, rows: dict[tuple[str, str], StoredCourse] | None = None, fail_on: str | None = None) -> None:
        self.rows = dict(rows or {})
        self.records: dict[tuple[str, str], CourseRecord] = {}
        self.writes: list[tuple[str, CourseRecord]] = []
        self.fail_on = fail_on

    async def get(self, course_key: str, version: str) -> StoredCourse | None:
        if course_key == self.fail_on:
            msg = "store unavailable"
            raise RuntimeError(msg)
        return self.rows.get((course_key, version))

    async def insert(self, record: CourseRecord) -> None:
        key = (record.course_key, record.version)
        assert key not in self.rows, "insert over an existing row"
        self._put("insert", record)

    async def replace(self, record: CourseRecord) -> None:
        key = (record.course_key, record.version)
        assert self.rows[key].status == "invalid", "only an invalid row may be replaced"
        self._put("replace", record)

    def _put(self, kind: str, record: CourseRecord) -> None:
        key = (record.course_key, record.version)
        self.rows[key] = StoredCourse(record.sha256, record.status)
        self.records[key] = record
        self.writes.append((kind, record))


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"), parse_float=Decimal)


def _write(directory: Path, name: str, data: Any) -> Path:
    path = directory / name
    text = data if isinstance(data, str) else json.dumps(data, default=str, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Pure part ────────────────────────────────────────────────────────────────


def test_parsing_hashes_the_raw_bytes_and_keeps_only_the_basename() -> None:
    raw = FIXTURE.read_bytes()
    parsed = parse_course_bytes(raw, str(FIXTURE))
    assert parsed.sha256 == hashlib.sha256(raw).hexdigest()
    assert parsed.source_file == FIXTURE.name
    assert parsed.errors == []
    assert parsed.spec is not None
    assert "authoring" not in parsed.spec


def test_bytes_that_are_not_json_give_an_error_not_an_exception() -> None:
    parsed = parse_course_bytes(b"{not json", "course_x_v1.json")
    assert parsed.spec is None and parsed.data is None
    assert parsed.errors


def test_a_shape_error_keeps_the_dict_so_the_rules_still_run() -> None:
    data = _fixture()
    data["tasks"][0]["colour"] = "blue"
    parsed = parse_course_bytes(json.dumps(data, default=str).encode(), "course_x_v1.json")
    assert parsed.spec is None
    assert parsed.data is not None
    assert any("colour" in e for e in parsed.errors)


async def test_the_fixture_is_valid() -> None:
    verdict = await validate_course(parse_course_bytes(FIXTURE.read_bytes(), FIXTURE.name))
    assert verdict.valid, verdict.errors
    assert verdict.report["engine_errors"] == 0


async def test_a_rule_that_crashes_makes_the_course_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self: Any, data: Any, context: Any) -> Any:
        msg = "rule bug"
        raise RuntimeError(msg)

    validators.register_trainer_rules()
    monkeypatch.setattr(validators.GradedItemsNonzero, "findings", boom)
    verdict = await validate_course(parse_course_bytes(FIXTURE.read_bytes(), FIXTURE.name))
    assert not verdict.valid
    assert any("trainer.graded_items_nonzero" in e and "crashed" in e for e in verdict.errors)


async def test_a_warning_alone_does_not_make_a_course_invalid() -> None:
    data = _fixture()
    data["seed"]["project"]["validation_rule_sets"] = ["nrm", "nmr"]
    verdict = await validate_course(parse_course_bytes(json.dumps(data, default=str).encode(), "c.json"))
    assert verdict.valid, verdict.errors
    assert verdict.report["warnings"] >= 1


# ── Decision 26: invalid files are stored, not skipped ───────────────────────


async def test_an_invalid_file_is_stored_as_invalid_with_its_errors(tmp_path: Path) -> None:
    bad_rule = _fixture()
    bad_rule["id"] = "fx-bad-rule"
    bad_rule["tasks"][0]["opens"] = "boq.nothing"
    bad_shape = _fixture()
    bad_shape["id"] = "fx-bad-shape"
    bad_shape["seed"]["progress_readings_valuation_1"] = {}
    _write(tmp_path, "course_b_v1.json", bad_rule)
    _write(tmp_path, "course_c_v1.json", bad_shape)
    _write(tmp_path, "course_d_v1.json", _fixture())
    _write(tmp_path, "notes.json", _fixture())  # not a course file name: ignored
    stray = _fixture()
    stray["id"] = "fx-stray"
    _write(tmp_path, "course_notes.json", stray)  # no _v<n>: not a course file, never a row

    store = FakeStore()
    outcomes = await load_courses_dir(store, tmp_path)

    assert [(o.source_file, o.status) for o in outcomes] == [
        ("course_b_v1.json", "invalid"),
        ("course_c_v1.json", "invalid"),
        ("course_d_v1.json", "loaded"),
    ]
    assert ("fx-stray", "1.0.0") not in store.rows
    rule_row = store.records[("fx-bad-rule", "1.0.0")]
    shape_row = store.records[("fx-bad-shape", "1.0.0")]
    good_row = store.records[(_fixture()["id"], "1.0.0")]
    assert rule_row.status == shape_row.status == "invalid"
    assert good_row.status == "active"
    assert any("trainer.opens_known_lock" in e for e in rule_row.validation_report["error_list"])
    assert any("seed.progress_readings[]" in e for e in shape_row.validation_report["error_list"])
    assert good_row.validation_report["error_list"] == []
    assert rule_row.spec == {}, "an invalid course keeps no spec anyone could seed from"
    assert "authoring" not in good_row.spec


async def test_a_file_with_no_id_is_logged_but_cannot_be_stored(tmp_path: Path) -> None:
    _write(tmp_path, "course_a_v1.json", "{broken")
    store = FakeStore()
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["invalid"]
    assert outcomes[0].errors
    assert store.writes == []


async def test_an_invalid_row_never_overflows_its_columns(tmp_path: Path) -> None:
    data = _fixture()
    data["title"] = "T" * 400
    data["country"] = "GBR"
    data["language"] = "en-GB-oxendict"
    _write(tmp_path, "course_a_v1.json", data)
    store = FakeStore()
    await load_courses_dir(store, tmp_path)
    (_, record), *_ = store.writes
    assert record.status == "invalid"
    assert len(record.title) <= COLUMN_LIMITS["title"]
    assert len(record.language) <= COLUMN_LIMITS["language"]
    assert len(record.country) <= 2


async def test_the_same_bytes_again_are_unchanged_valid_or_invalid(tmp_path: Path) -> None:
    good = _write(tmp_path, "course_a_v1.json", FIXTURE.read_text(encoding="utf-8"))
    data = _fixture()
    data["id"] = "fx-bad"
    data["tasks"][0]["opens"] = "boq.nothing"
    bad = _write(tmp_path, "course_b_v1.json", data)
    store = FakeStore(
        {
            (_fixture()["id"], "1.0.0"): StoredCourse(_sha(good), "active"),
            ("fx-bad", "1.0.0"): StoredCourse(_sha(bad), "invalid"),
        }
    )
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["unchanged", "unchanged"]
    assert store.writes == []


async def test_new_content_under_a_valid_version_is_refused_and_the_row_stays(tmp_path: Path) -> None:
    data = _fixture()
    data["title"] = "Edited without a version bump"
    _write(tmp_path, "course_a_v1.json", data)
    key = (data["id"], data["version"])
    store = FakeStore({key: StoredCourse("0" * 64, "active")})
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["refused"]
    assert any("trainer.version_not_bumped" in e for e in outcomes[0].errors)
    assert store.rows[key] == StoredCourse("0" * 64, "active")
    assert store.writes == []


async def test_a_fixed_file_replaces_its_invalid_row_without_a_bump(tmp_path: Path) -> None:
    """An invalid row was never offered, so nobody pinned it; the fix may land in place."""
    _write(tmp_path, "course_a_v1.json", _fixture())
    key = (_fixture()["id"], "1.0.0")
    store = FakeStore({key: StoredCourse("0" * 64, "invalid")})
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["loaded"]
    assert [kind for kind, _ in store.writes] == ["replace"]
    assert store.rows[key].status == "active"


async def test_a_still_broken_file_replaces_its_invalid_row_with_the_new_errors(tmp_path: Path) -> None:
    data = _fixture()
    data["tasks"][0]["opens"] = "boq.nothing"
    _write(tmp_path, "course_a_v1.json", data)
    key = (data["id"], "1.0.0")
    store = FakeStore({key: StoredCourse("0" * 64, "invalid")})
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["invalid"]
    assert [kind for kind, _ in store.writes] == ["replace"]
    assert not any("version_not_bumped" in e for e in store.records[key].validation_report["error_list"])


async def test_a_bumped_version_loads_beside_the_old_one(tmp_path: Path) -> None:
    data = _fixture()
    data["version"] = "1.0.1"
    _write(tmp_path, "course_a_v1.json", data)
    store = FakeStore({(data["id"], "1.0.0"): StoredCourse("0" * 64, "active")})
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["loaded"]
    assert set(store.rows) == {(data["id"], "1.0.0"), (data["id"], "1.0.1")}


async def test_an_unexpected_error_on_one_file_does_not_stop_the_others(tmp_path: Path) -> None:
    first = _fixture()
    first["id"] = "fx-store-breaks"
    _write(tmp_path, "course_a_v1.json", first)
    _write(tmp_path, "course_b_v1.json", _fixture())
    store = FakeStore(fail_on="fx-store-breaks")
    outcomes = await load_courses_dir(store, tmp_path)
    assert [o.status for o in outcomes] == ["failed", "loaded"]
    assert "store unavailable" in outcomes[0].errors[0]


async def test_no_directory_configured_means_no_courses(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        trainer_courses_dir = "  "

    monkeypatch.setattr("app.config.get_settings", lambda: _Settings())
    assert resolve_courses_dir() is None
    assert await load_courses_dir(FakeStore()) == []


async def test_a_missing_directory_means_no_courses(tmp_path: Path) -> None:
    assert await load_courses_dir(FakeStore(), tmp_path / "absent") == []


def test_parsing_and_validating_never_import_the_database() -> None:
    """The check script runs with no database configured."""
    code = "\n".join(
        [
            "import asyncio, sys",
            "from pathlib import Path",
            "from app.modules.trainer import loader",
            f"raw = Path({str(FIXTURE)!r}).read_bytes()",
            "verdict = asyncio.run(loader.validate_course(loader.parse_course_bytes(raw, 'x.json')))",
            "print(verdict.valid, 'app.database' in sys.modules)",
        ]
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, timeout=300, check=True
    )
    assert out.stdout.strip().splitlines()[-1] == "True False"


# ── Startup hook ─────────────────────────────────────────────────────────────


@pytest.fixture
def academy(monkeypatch: pytest.MonkeyPatch):
    """Set the academy flag for one test, through the real settings object."""
    from app.config import get_settings

    def set_flag(on: bool) -> None:
        monkeypatch.setenv("OE_ACADEMY_MODE", "true" if on else "false")
        monkeypatch.setenv("ACADEMY_MODE", "true" if on else "false")
        get_settings.cache_clear()

    yield set_flag
    get_settings.cache_clear()


async def test_startup_loads_the_courses_only_with_the_flag_on(academy, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules import trainer
    from app.modules.trainer import loader

    calls: list[str] = []

    async def fake_load() -> list[Any]:
        calls.append("load")
        return []

    monkeypatch.setattr(loader, "load_courses_at_startup", fake_load)
    academy(False)
    await trainer.on_startup()
    assert calls == []
    academy(True)
    await trainer.on_startup()
    assert calls == ["load"]


async def test_startup_survives_a_loader_that_raises(academy, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules import trainer
    from app.modules.trainer import loader

    async def broken() -> list[Any]:
        msg = "database gone"
        raise RuntimeError(msg)

    monkeypatch.setattr(loader, "load_courses_at_startup", broken)
    academy(True)
    await trainer.on_startup()


async def test_the_startup_load_never_raises_when_the_session_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.trainer import loader

    class _Broken:
        def __call__(self) -> Any:
            msg = "no database"
            raise RuntimeError(msg)

    monkeypatch.setattr(loader, "_session_factory", lambda: _Broken())
    assert await loader.load_courses_at_startup() == []
