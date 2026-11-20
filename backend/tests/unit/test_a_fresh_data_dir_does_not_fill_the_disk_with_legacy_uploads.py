"""A fresh data dir does not receive a copy of a legacy store the disk cannot hold.

The legacy home-state migration records what it copied in a marker inside the
data dir, so every NEW data dir (each test run, each temp dir) copied the whole
legacy upload store again. On a developer machine that store held 16 GB of demo
project documents, and test app starts filled the system drive with it. The same
copy carried the developer's applied pack into every test, which made each start
look like a pack seeding demo projects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import home_state


@pytest.fixture
def legacy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_home = tmp_path / "home"
    uploads = fake_home / ".openestimator" / "uploads" / "project-a"
    uploads.mkdir(parents=True)
    (uploads / "drawing.pdf").write_bytes(b"x" * 4096)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: fake_home))
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path / "data"))
    return fake_home


_UPLOADS = (home_state.LegacyEntry(home_state.LEGACY_HOME_ROOT, ("uploads",)),)


def test_a_store_that_would_leave_too_little_space_is_not_copied(
    legacy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(home_state, "_free_bytes", lambda _path: home_state.COPY_FREE_RESERVE_BYTES + 1024)

    assert home_state.migrate_legacy_home_state(_UPLOADS) == []
    assert not (tmp_path / "data" / "uploads").exists()
    # Not recorded as done, so it is tried again once there is room.
    assert not (tmp_path / "data" / home_state.MIGRATION_MARKER).exists()


def test_a_store_that_fits_is_copied_once(legacy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(home_state, "_free_bytes", lambda _path: home_state.COPY_FREE_RESERVE_BYTES + 10**6)

    assert home_state.migrate_legacy_home_state(_UPLOADS) == [".openestimator/uploads"]
    assert (tmp_path / "data" / "uploads" / "project-a" / "drawing.pdf").stat().st_size == 4096
    assert home_state.migrate_legacy_home_state(_UPLOADS) == []


def test_the_suite_never_reads_the_developers_real_home() -> None:
    """The suite's legacy home is a temp dir, so a test app start copies nothing of the developer's."""
    real = Path.home().joinpath(home_state.LEGACY_HOME_ROOT, "uploads")
    resolved = home_state.legacy_home_dir(home_state.LEGACY_HOME_ROOT, "uploads")

    assert resolved != real
    assert not resolved.exists()


@pytest.mark.parametrize("var", ["OE_TEST_FAST_STARTUP", "OE_SKIP_SHOWCASE"])
def test_boot_skips_pack_and_generic_showcase_alike(var: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import _boot_showcase_skip_reason

    monkeypatch.delenv("OE_TEST_FAST_STARTUP", raising=False)
    monkeypatch.delenv("OE_SKIP_SHOWCASE", raising=False)
    assert _boot_showcase_skip_reason() is None

    monkeypatch.setenv(var, "1")
    assert _boot_showcase_skip_reason() == var
