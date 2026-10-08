"""Tests for the schedulers and warm-ups declared in ``app.core.processes.builtin``."""

from __future__ import annotations

import asyncio

import pytest

from app.core.processes import InMemoryProcessStore, ProcessRegistry, ProcessStatus, builtin

PERIODIC = [
    "kpi_scheduler",
    "reports_scheduler",
    "approval_sla_monitor",
    "deadline_sweeper",
    "risk_escalation",
    "phonelog_retention",
    "file_trash_purge",
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OE_TEST_FAST_STARTUP", raising=False)
    # Not a demo deployment: the demo sweeper must stay off.
    monkeypatch.setattr("app.core.demo_retention.demo_retention_enabled", lambda: False)


async def _registry(fresh: bool) -> ProcessRegistry:
    reg = ProcessRegistry(store=InMemoryProcessStore())
    await reg.load(fresh_install=lambda: fresh)
    builtin.register_builtin_processes(reg)
    builtin.register_notification_worker(reg)
    builtin.register_collab_lock_sweeper(reg)
    return reg


async def _until(cond: object, timeout: float = 10.0) -> None:
    """Poll ``cond`` until true; generous so a loaded CI box does not flake."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():  # type: ignore[operator]
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


def _own_tasks() -> set[asyncio.Task[object]]:
    return {t for t in asyncio.all_tasks() if (t.get_name() or "").startswith("process:")}


@pytest.mark.asyncio
async def test_boot_runs_no_tick_on_the_boot_path(monkeypatch: pytest.MonkeyPatch) -> None:
    ticked: list[str] = []

    async def spy() -> None:
        ticked.append("x")

    for name in ("kpi_tick", "reports_tick", "risk_tick", "phonelog_tick", "sla_tick", "deadline_tick"):
        monkeypatch.setattr(builtin, name, spy)
    reg = await _registry(fresh=False)
    try:
        await reg.start_boot()
        await asyncio.sleep(0.05)
        for pid in PERIODIC:
            assert reg.status(pid) is ProcessStatus.RUNNING, pid
        # Every loop sleeps before its first pass, so the boot does no work.
        assert ticked == []
    finally:
        await reg.stop_all()
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_fresh_install_leaves_disabled_items_unstarted() -> None:
    reg = await _registry(fresh=True)
    try:
        await reg.start_boot()
        assert reg.status("ai_agent_scheduler") is ProcessStatus.DISABLED
        assert reg.ensure_for_module("ai_agents")["disabled"] == ["ai_agent_scheduler"]
        assert reg.status("cost_cache_prewarm") is ProcessStatus.DISABLED
        assert reg.status("demo_retention") is ProcessStatus.DISABLED
        assert reg.status("kpi_scheduler") is ProcessStatus.RUNNING
    finally:
        await reg.stop_all()


@pytest.mark.asyncio
async def test_fast_startup_keeps_every_process_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_TEST_FAST_STARTUP", "1")
    reg = await _registry(fresh=False)
    await reg.start_boot()
    assert not _own_tasks()
    for pid in [*PERIODIC, "notification_worker", "collab_lock_sweeper", "cost_cache_prewarm"]:
        assert reg.status(pid) is ProcessStatus.DISABLED, pid


@pytest.mark.asyncio
async def test_cost_prewarm_is_lazy_and_runs_once_on_module_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    runs: list[int] = []

    async def fake_prewarm() -> None:
        runs.append(1)

    monkeypatch.setattr(builtin, "prewarm_cost_caches", fake_prewarm)
    reg = await _registry(fresh=False)
    try:
        await reg.start_boot()
        await asyncio.sleep(0.02)
        assert runs == []
        # Opening the cost module twice runs the warm-up once.
        reg.ensure_for_module("costs")
        await _until(lambda: runs == [1] and reg.status("cost_cache_prewarm") is ProcessStatus.IDLE)
        reg.ensure_for_module("costs")
        await asyncio.sleep(0.1)
        assert runs == [1]
    finally:
        await reg.stop_all()


@pytest.mark.asyncio
async def test_restart_replaces_the_loop_without_leaking_a_task() -> None:
    reg = await _registry(fresh=False)
    try:
        await reg.start_boot()
        before = {t for t in _own_tasks() if t.get_name() == "process:kpi_scheduler"}
        await reg.restart("kpi_scheduler")
        after = {t for t in _own_tasks() if t.get_name() == "process:kpi_scheduler"}
        assert len(after) == 1
        assert after.isdisjoint(before)
        assert all(t.done() for t in before)
        assert reg.status("kpi_scheduler") is ProcessStatus.RUNNING
    finally:
        await reg.stop_all()
        await reg.stop_all()  # idempotent
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_a_failing_prewarm_sets_error_and_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken() -> None:
        raise RuntimeError("catalog unreachable")

    monkeypatch.setattr(builtin, "prewarm_cost_caches", broken)
    reg = await _registry(fresh=False)
    try:
        await reg.ensure_started("cost_cache_prewarm")
        await _until(lambda: reg.status("cost_cache_prewarm") is ProcessStatus.ERROR)
        info = reg.describe("cost_cache_prewarm")
        assert info["status"] == ProcessStatus.ERROR
        assert "catalog unreachable" in info["last_error"]["message"]
    finally:
        await reg.stop_all()


@pytest.mark.asyncio
async def test_a_failing_tick_keeps_the_loop_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def broken() -> None:
        calls.append(1)
        raise RuntimeError("db down")

    monkeypatch.setattr(builtin, "risk_tick", broken)
    monkeypatch.setattr(builtin, "HOUR_S", 0.01)
    reg = await _registry(fresh=False)
    try:
        await reg.start("risk_escalation")
        await _until(lambda: len(calls) >= 2)
        assert reg.status("risk_escalation") in {ProcessStatus.RUNNING, ProcessStatus.DEGRADED}
    finally:
        await reg.stop_all()


@pytest.mark.asyncio
async def test_notification_worker_stop_leaves_no_task() -> None:
    from app.modules.notifications import notification_worker

    reg = await _registry(fresh=False)
    await reg.start("notification_worker")
    assert notification_worker._is_scheduler_running()
    await reg.stop_all()
    assert not notification_worker._is_scheduler_running()


def test_openapi_prime_follows_its_env_decision() -> None:
    reg = ProcessRegistry(store=InMemoryProcessStore())

    async def prime() -> None:
        return None

    builtin.register_builtin_processes(reg, openapi_prime=prime, openapi_env=lambda: None)
    assert reg.is_enabled("openapi_prime") is False
    builtin.register_builtin_processes(reg, openapi_prime=prime, openapi_env=lambda: True)
    assert reg.is_enabled("openapi_prime") is True
