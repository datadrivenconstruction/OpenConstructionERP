"""Tests for the once-per-version boot seeds (``app.core.seed_once``)."""

from __future__ import annotations

import pytest

from app.core.processes import InMemoryProcessStore
from app.core.seed_once import SeedOnce, marker_key


@pytest.fixture(autouse=True)
def _no_fast_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OE_TEST_FAST_STARTUP", raising=False)


def _counting() -> tuple[list[int], object]:
    runs: list[int] = []

    async def seed() -> None:
        runs.append(1)

    return runs, seed


@pytest.mark.asyncio
async def test_a_completed_seed_is_skipped_on_the_next_boot_of_the_same_version() -> None:
    store = InMemoryProcessStore()
    runs, seed = _counting()
    assert await SeedOnce("1.0.0", store).run("i18n", seed, "failed") is True
    assert await SeedOnce("1.0.0", store).run("i18n", seed, "failed") is False
    assert runs == [1]
    assert store.rows[marker_key("i18n", "1.0.0")] is True


@pytest.mark.asyncio
async def test_an_upgrade_runs_the_seed_again() -> None:
    store = InMemoryProcessStore()
    runs, seed = _counting()
    await SeedOnce("1.0.0", store).run("starter", seed, "failed")
    await SeedOnce("1.1.0", store).run("starter", seed, "failed")
    assert runs == [1, 1]


@pytest.mark.asyncio
async def test_a_failed_seed_stamps_nothing_and_retries(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryProcessStore()
    calls: list[int] = []

    async def broken() -> None:
        calls.append(1)
        raise RuntimeError("db hiccup")

    assert await SeedOnce("1.0.0", store).run("regional", broken, "regional seed failed") is False
    assert "regional seed failed" in caplog.text
    assert store.rows == {}
    await SeedOnce("1.0.0", store).run("regional", broken, "regional seed failed")
    assert calls == [1, 1]


@pytest.mark.asyncio
async def test_fast_startup_ignores_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryProcessStore({marker_key("i18n", "1.0.0"): True})
    monkeypatch.setenv("OE_TEST_FAST_STARTUP", "1")
    runs, seed = _counting()
    await SeedOnce("1.0.0", store).run("i18n", seed, "failed")
    assert runs == [1]


@pytest.mark.asyncio
async def test_an_unwritable_marker_does_not_fail_the_seed() -> None:
    class ReadOnly(InMemoryProcessStore):
        async def save(self, process_id: str, enabled: bool, updated_by: str | None = None) -> None:
            raise RuntimeError("read-only")

    runs, seed = _counting()
    assert await SeedOnce("1.0.0", ReadOnly()).run("i18n", seed, "failed") is True
    assert runs == [1]


@pytest.mark.asyncio
async def test_the_demo_pending_flag_survives_until_cleared() -> None:
    from app.core.seed_once import demo_projects_pending, set_demo_projects_pending

    store = InMemoryProcessStore()
    assert await demo_projects_pending(store) is False
    await set_demo_projects_pending(True, store)
    # A boot that died here finds the flag and installs the showcase again.
    assert await demo_projects_pending(store) is True
    await set_demo_projects_pending(False, store)
    assert await demo_projects_pending(store) is False
