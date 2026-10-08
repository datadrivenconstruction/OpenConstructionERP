"""Tests for the background process registry (``app.core.processes``)."""

from __future__ import annotations

import asyncio
import logging
import threading

import pytest

from app.core.processes import (
    InMemoryProcessStore,
    LoopProcess,
    ManagedProcess,
    OneShotProcess,
    ProcessError,
    ProcessRegistry,
    ProcessSpec,
    ProcessStatus,
    ResidentProcess,
    ThreadLoopProcess,
)


def _spec(pid: str = "p1", **kw: object) -> ProcessSpec:
    counter = kw.pop("counter", None)

    async def tick() -> None:
        if counter is not None:
            counter.append(1)  # type: ignore[attr-defined]

    defaults: dict[str, object] = {
        "id": pid,
        "modules": ["mod"],
        "category": "scheduler",
        "start_mode": "boot",
        "default_enabled": True,
        "legacy_enabled": True,
        "estimated_ram_mb": 5,
        "factory": lambda: LoopProcess(interval_s=0.01, tick=tick),
    }
    defaults.update(kw)
    return ProcessSpec(**defaults)  # type: ignore[arg-type]


async def _registry(fresh: bool = False, **store_kw: object) -> ProcessRegistry:
    reg = ProcessRegistry(store=InMemoryProcessStore(**store_kw))  # type: ignore[arg-type]
    reg.stagger_s = 0
    await reg.load(fresh_install=lambda: fresh)
    return reg


def _own_tasks() -> set[asyncio.Task[object]]:
    return {t for t in asyncio.all_tasks() if (t.get_name() or "").startswith("process:")}


@pytest.mark.asyncio
async def test_boot_starts_enabled_and_skips_lazy() -> None:
    reg = await _registry()
    calls: list[int] = []
    reg.register(_spec("a", counter=calls))
    reg.register(_spec("b", start_mode="lazy"))
    await reg.start_boot()
    await asyncio.sleep(0.05)
    assert reg.status("a") is ProcessStatus.RUNNING
    assert reg.status("b") is ProcessStatus.IDLE
    assert calls
    await reg.stop_all()
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_fresh_install_uses_default_enabled_upgrade_uses_legacy() -> None:
    fresh = await _registry(fresh=True)
    fresh.register(_spec("heavy", default_enabled=False, legacy_enabled=True))
    assert fresh.status("heavy") is ProcessStatus.DISABLED
    assert fresh.first_run_done is False

    upgraded = await _registry(fresh=False)
    upgraded.register(_spec("heavy", default_enabled=False, legacy_enabled=True))
    assert upgraded.is_enabled("heavy") is True
    assert upgraded.first_run_done is True


@pytest.mark.asyncio
async def test_persisted_state_beats_defaults_and_env_beats_persisted() -> None:
    store = InMemoryProcessStore(rows={"a": False, "b": True})
    reg = ProcessRegistry(store=store)
    await reg.load(fresh_install=lambda: False)
    reg.register(_spec("a"))
    reg.register(_spec("b", default_enabled=False, legacy_enabled=False, env_override=lambda: False))
    assert reg.is_enabled("a") is False
    assert reg.is_enabled("b") is False
    assert reg.describe("b")["env_locked"] is True
    with pytest.raises(ProcessError):
        await reg.enable("b")


@pytest.mark.asyncio
async def test_disable_enable_restart_do_not_leak_tasks() -> None:
    reg = await _registry()
    reg.register(_spec("a"))
    await reg.start_boot()
    for _ in range(5):
        await reg.restart("a")
    assert len(_own_tasks()) == 1
    await reg.disable("a")
    assert reg.status("a") is ProcessStatus.DISABLED
    assert not _own_tasks()
    assert reg.store.rows["a"] is False  # type: ignore[attr-defined]
    await reg.enable("a")
    assert reg.status("a") is ProcessStatus.RUNNING
    await reg.stop_all()
    await reg.stop_all()  # idempotent
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_crashing_start_sets_error_and_does_not_raise() -> None:
    class Boom(ManagedProcess):
        async def start(self) -> None:
            raise RuntimeError("kaboom")

        async def stop(self) -> None:
            return None

    reg = await _registry()
    reg.register(_spec("x", factory=Boom, restart_policy="never"))
    await reg.start_boot()
    assert reg.status("x") is ProcessStatus.ERROR
    err = reg.describe("x")["last_error"]
    assert err is not None
    assert "kaboom" in err["message"]
    assert err["traceback_id"]
    await reg.stop_all()


@pytest.mark.asyncio
async def test_oneshot_crash_retries_with_backoff_then_gives_up() -> None:
    attempts: list[int] = []

    async def run() -> None:
        attempts.append(1)
        raise ValueError("nope")

    reg = await _registry()
    reg.register(
        _spec(
            "o",
            factory=lambda: OneShotProcess(run=run),
            restart_policy="on_failure",
            max_retries=2,
            backoff_base_s=0.01,
        )
    )
    await reg.start_boot()
    for _ in range(100):
        await asyncio.sleep(0.02)
        if len(attempts) >= 3 and reg.status("o") is ProcessStatus.ERROR and reg.describe("o")["next_retry_at"] is None:
            break
    assert len(attempts) == 3
    assert reg.describe("o")["restart_count"] == 2
    assert reg.status("o") is ProcessStatus.ERROR
    await reg.stop_all()
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_oneshot_success_becomes_idle_done() -> None:
    async def run() -> None:
        return None

    reg = await _registry()
    reg.register(_spec("o", factory=lambda: OneShotProcess(run=run)))
    await reg.start_boot()
    await asyncio.sleep(0.05)
    assert reg.status("o") is ProcessStatus.IDLE
    assert reg.describe("o")["last_run_ok"] is True


@pytest.mark.asyncio
async def test_loop_tick_exception_degrades_but_keeps_running() -> None:
    n: list[int] = []

    async def tick() -> None:
        n.append(1)
        raise RuntimeError("tick failed")

    reg = await _registry()
    reg.register(_spec("l", factory=lambda: LoopProcess(interval_s=0.01, tick=tick)))
    await reg.start_boot()
    await asyncio.sleep(0.08)
    assert len(n) >= 2
    assert reg.status("l") is ProcessStatus.DEGRADED
    assert "tick failed" in reg.describe("l")["last_error"]["message"]
    await reg.stop_all()


@pytest.mark.asyncio
async def test_lazy_ensure_started_loads_on_demand() -> None:
    reg = await _registry()
    reg.register(_spec("z", start_mode="lazy"))
    await reg.start_boot()
    assert reg.status("z") is ProcessStatus.IDLE
    assert await reg.ensure_started("z") is True
    assert reg.status("z") is ProcessStatus.RUNNING
    await reg.disable("z")
    assert await reg.ensure_started("z") is False
    await reg.stop_all()


@pytest.mark.asyncio
async def test_required_and_unstoppable_cannot_be_disabled() -> None:
    reg = await _registry()
    reg.register(_spec("r", required=True))
    reg.register(_spec("u", stoppable=False))
    for pid in ("r", "u"):
        with pytest.raises(ProcessError):
            await reg.disable(pid)


@pytest.mark.asyncio
async def test_dependencies_start_first_and_block_when_disabled() -> None:
    reg = await _registry(rows={"dep": False})
    reg.register(_spec("dep", start_mode="lazy"))
    reg.register(_spec("child", dependencies=["dep"]))
    await reg.start_boot()
    assert reg.status("child") is ProcessStatus.ERROR
    assert "dep" in reg.describe("child")["last_error"]["message"]
    await reg.enable("dep")
    await reg.restart("child")
    assert reg.status("dep") is ProcessStatus.RUNNING
    assert reg.status("child") is ProcessStatus.RUNNING
    await reg.stop_all()


@pytest.mark.asyncio
async def test_logs_are_captured_per_process() -> None:
    reg = await _registry()
    reg.register(_spec("a", logger_names=["oe.test.proc_a"]))
    logging.getLogger("oe.test.proc_a").warning("hello from a")
    logging.getLogger("oe.test.other").warning("not mine")
    lines = reg.logs("a")
    assert any("hello from a" in ln for ln in lines)
    assert not any("not mine" in ln for ln in lines)


@pytest.mark.asyncio
async def test_state_change_events_published() -> None:
    seen: list[tuple[str, str]] = []

    async def publish(data: dict[str, object]) -> None:
        seen.append((str(data["old"]), str(data["new"])))

    reg = ProcessRegistry(store=InMemoryProcessStore(), publish=publish)
    await reg.load(fresh_install=lambda: False)
    reg.register(_spec("a"))
    await reg.start_boot()
    await reg.disable("a")
    await asyncio.sleep(0.01)
    assert ("idle", "starting") in seen
    assert ("running", "stopping") in seen
    assert seen[-1][1] == "disabled"


@pytest.mark.asyncio
async def test_recommendations_and_first_run() -> None:
    reg = await _registry(fresh=True)
    reg.register(_spec("core_sched", modules=[], default_enabled=True))
    reg.register(_spec("emb", modules=["search", "costs"], default_enabled=False, estimated_ram_mb=300))
    reg.register(_spec("kpi", modules=["reporting"], default_enabled=True))
    rec = reg.recommendations(["search"])
    assert rec["process_ids"] == ["core_sched", "emb"]
    assert rec["total_ram_mb_estimate"] == 305
    await reg.first_run(["search"], start_now=False)
    assert reg.first_run_done is True
    assert reg.is_enabled("emb") is True
    assert reg.is_enabled("kpi") is False
    await reg.apply_preset("minimal")
    assert reg.is_enabled("emb") is False
    assert reg.is_enabled("core_sched") is True


@pytest.mark.asyncio
async def test_thread_loop_process_joins_thread_on_stop() -> None:
    hits: list[int] = []

    def work() -> None:
        hits.append(1)

    reg = await _registry()
    reg.register(_spec("t", factory=lambda: ThreadLoopProcess(interval_s=0.01, work=work)))
    await reg.start_boot()
    await asyncio.sleep(0.05)
    await reg.restart("t")
    assert [t.name for t in threading.enumerate()].count("process:t") == 1
    await reg.stop_all()
    assert hits
    assert "process:t" not in [t.name for t in threading.enumerate()]


@pytest.mark.asyncio
async def test_register_twice_replaces_spec_without_losing_state() -> None:
    reg = await _registry(rows={"a": False})
    reg.register(_spec("a"))
    reg.register(_spec("a", estimated_ram_mb=99))
    assert reg.describe("a")["ram_mb_estimate"] == 99
    assert reg.is_enabled("a") is False


@pytest.mark.asyncio
async def test_shared_switch_flips_whole_group_and_external_change_reconciles() -> None:
    switch = {"on": False}
    started: list[str] = []

    def make(pid: str) -> ProcessSpec:
        async def load() -> None:
            started.append(pid)

        return _spec(
            pid,
            default_enabled=False,
            legacy_enabled=False,
            state_get=lambda: switch["on"],
            state_set=lambda v: switch.__setitem__("on", v),
            factory=lambda: ResidentProcess(load=load),
        )

    reg = await _registry()
    reg.register(make("m1"))
    reg.register(make("m2"))
    await reg.start_boot()
    assert reg.status("m1") is ProcessStatus.DISABLED
    await reg.enable("m1")
    await asyncio.sleep(0.2)
    assert switch["on"] is True
    assert reg.status("m2") is ProcessStatus.RUNNING
    assert sorted(started) == ["m1", "m2"]
    switch["on"] = False  # flipped elsewhere (Settings page)
    await reg.reconcile(force=True)
    assert reg.status("m1") is ProcessStatus.DISABLED
    assert reg.status("m2") is ProcessStatus.DISABLED
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_start_boot_twice_does_not_rerun_finished_oneshot() -> None:
    runs: list[int] = []

    async def run() -> None:
        runs.append(1)

    reg = await _registry()
    reg.register(_spec("o", factory=lambda: OneShotProcess(run=run)))
    await reg.start_boot()
    await asyncio.sleep(0.02)
    reg.register(_spec("late"))
    await reg.start_boot()
    await asyncio.sleep(0.02)
    assert runs == [1]
    assert reg.status("late") is ProcessStatus.RUNNING
    await reg.stop_all()


def test_router_admin_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.core.processes.router as router_mod
    from app.dependencies import get_current_user_payload

    reg = ProcessRegistry(store=InMemoryProcessStore())
    reg.register(_spec("a", modules=["reporting"]))
    reg.register(_spec("core_req", modules=[], required=True))
    monkeypatch.setattr(router_mod, "process_registry", reg)

    api = FastAPI()
    api.include_router(router_mod.router)
    api.dependency_overrides[get_current_user_payload] = lambda: {"sub": "u1", "role": "admin"}
    from app.dependencies import RequireRole

    async def _no_check(
        self: object, payload: object = None
    ) -> None:  # admin gate is covered by test_router_requires_admin
        return None

    monkeypatch.setattr(RequireRole, "__call__", _no_check)

    with TestClient(api) as client:
        asyncio.run(reg.load(fresh_install=lambda: False))
        body = client.get("/api/v1/processes/").json()
        ids = [p["id"] for p in body["processes"]]
        assert ids == ["a", "core_req"]
        assert body["first_run_done"] is True
        assert body["processes"][0]["name_key"] == "processes.a.name"
        assert client.post("/api/v1/processes/a/disable").json()["status"] == "disabled"
        assert client.post("/api/v1/processes/core_req/disable").status_code == 409
        assert client.post("/api/v1/processes/nope/enable").status_code == 404
        assert client.post("/api/v1/processes/a/bogus").status_code == 422
        assert "lines" in client.get("/api/v1/processes/a/logs").json()
        rec = client.get("/api/v1/processes/recommendations", params={"modules": "reporting"}).json()
        assert rec["process_ids"] == ["a", "core_req"]
        assert client.post("/api/v1/processes/preset", json={"preset": "nope"}).status_code == 422
        ens = client.post("/api/v1/processes/ensure", params={"module": "reporting"}).json()
        assert ens["module"] == "reporting"
        assert ens["disabled"] == ["a"]


def test_router_requires_admin() -> None:
    from app.core.processes.router import router as proc_router

    guarded = {
        (route.path, tuple(sorted(route.methods)))  # type: ignore[attr-defined]
        for route in proc_router.routes
        if any(type(d.dependency).__name__ == "RequireRole" for d in route.dependencies)  # type: ignore[attr-defined]
    }
    paths = {p for p, _ in guarded}
    assert "/api/v1/processes/{process_id}/{action}" in paths
    assert "/api/v1/processes/{process_id}/logs" in paths
    assert "/api/v1/processes/preset" in paths
    assert "/api/v1/processes/first-run" in paths
    assert "/api/v1/processes/" not in paths
    assert "/api/v1/processes/ensure" not in paths


def test_non_admin_listing_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.processes.router as router_mod

    reg = ProcessRegistry(store=InMemoryProcessStore())
    reg.register(_spec("a"))
    monkeypatch.setattr(router_mod, "process_registry", reg)
    entry = reg._entries["a"]
    reg._record_error(entry, RuntimeError("secret path C:/x"))
    body = router_mod._listing({"role": "viewer"})
    item = body["processes"][0]
    assert item["log_tail"] == []
    assert item["last_error"]["message"] is None
    assert router_mod._listing({"role": "admin"})["processes"][0]["last_error"]["message"]


@pytest.mark.asyncio
async def test_queue_starts_heavy_processes_one_at_a_time() -> None:
    active: list[int] = []
    peak: list[int] = []

    def make(pid: str) -> ProcessSpec:
        async def load() -> None:
            active.append(1)
            peak.append(len(active))
            await asyncio.sleep(0.05)
            active.pop()

        return _spec(pid, modules=["costs"], start_mode="lazy", factory=lambda: ResidentProcess(load=load))

    reg = await _registry()
    for pid in ("h1", "h2", "h3"):
        reg.register(make(pid))
    reg.register(_spec("other", modules=["boq"], start_mode="lazy"))
    first = reg.ensure_for_module("costs")
    again = reg.ensure_for_module("costs")
    assert first["queued"] == ["h1", "h2", "h3"]
    assert again["queued"] == []
    assert sorted(again["loading"]) == ["h1", "h2", "h3"]
    assert reg.describe("h3")["queued"] is True
    for _ in range(100):
        await asyncio.sleep(0.02)
        if all(reg.status(p) is ProcessStatus.RUNNING for p in ("h1", "h2", "h3")):
            break
    assert max(peak) == 1
    assert reg.status("other") is ProcessStatus.IDLE
    assert reg.ensure_for_module("costs")["running"] == ["h1", "h2", "h3"]
    await reg.stop_all()
    assert not _own_tasks()


@pytest.mark.asyncio
async def test_ensure_skips_disabled_and_manual() -> None:
    reg = await _registry(rows={"off": False})
    reg.register(_spec("off", modules=["m"], start_mode="lazy"))
    reg.register(_spec("man", modules=["m"], start_mode="manual"))
    out = reg.ensure_for_module("m")
    assert out["queued"] == []
    assert out["disabled"] == ["off"]


@pytest.mark.asyncio
async def test_schedule_boot_is_deferred_and_cancellable() -> None:
    reg = await _registry()
    reg.register(_spec("a"))
    reg.schedule_boot(delay_s=0.05)
    assert reg.status("a") is ProcessStatus.IDLE  # nothing on the startup path
    await asyncio.sleep(0.2)
    assert reg.status("a") is ProcessStatus.RUNNING
    await reg.stop_all()
    reg2 = await _registry()
    reg2.register(_spec("b"))
    reg2.schedule_boot(delay_s=10)
    await reg2.stop_all()  # must not wait for the delay
    assert reg2.status("b") is ProcessStatus.IDLE


@pytest.mark.asyncio
async def test_flags_persist() -> None:
    reg = await _registry()
    assert reg.get_flag("seeds/demo@1") is False
    await reg.set_flag("seeds/demo@1")
    assert reg.get_flag("seeds/demo@1") is True
    assert reg.store.rows["flag:seeds/demo@1"] is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_ensure_does_not_rerun_finished_oneshot() -> None:
    runs: list[int] = []

    async def run() -> None:
        runs.append(1)

    reg = await _registry()
    reg.register(_spec("warm", modules=["costs"], start_mode="lazy", factory=lambda: OneShotProcess(run=run)))
    assert reg.ensure_for_module("costs")["queued"] == ["warm"]
    await asyncio.sleep(0.1)
    assert reg.ensure_for_module("costs")["queued"] == []
    await asyncio.sleep(0.05)
    assert runs == [1]
    await reg.restart("warm")
    await asyncio.sleep(0.05)
    assert runs == [1, 1]
    await reg.stop_all()
