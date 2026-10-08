"""Lifecycle edges of the processes center that the registry tests leave open.

The sibling module pins each action on its own. These tests pin what happens
when actions overlap or arrive at the wrong moment: restarts fired together,
a module opened twice at once, a disable while a model is still loading or a
retry is waiting, and a dependency that is still loading when the process that
needs it starts.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.processes import (
    InMemoryProcessStore,
    LoopProcess,
    OneShotProcess,
    ProcessRegistry,
    ProcessSpec,
    ProcessStatus,
    ResidentProcess,
)

pytestmark = pytest.mark.asyncio


async def _registry() -> ProcessRegistry:
    reg = ProcessRegistry(store=InMemoryProcessStore())
    reg.stagger_s = 0
    await reg.load(fresh_install=lambda: False)
    return reg


def _spec(pid: str, factory: object, **kw: object) -> ProcessSpec:
    fields: dict[str, object] = {
        "id": pid,
        "modules": ["mod"],
        "category": "scheduler",
        "start_mode": "boot",
        "default_enabled": True,
        "legacy_enabled": True,
        "factory": factory,
    }
    fields.update(kw)
    return ProcessSpec(**fields)  # type: ignore[arg-type]


async def _until(cond: object, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():  # type: ignore[operator]
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


def _own_tasks() -> set[asyncio.Task[object]]:
    return {t for t in asyncio.all_tasks() if (t.get_name() or "").startswith("process:")}


def _retry_tasks() -> set[asyncio.Task[object]]:
    return {t for t in asyncio.all_tasks() if (t.get_name() or "").startswith("process-retry:") and not t.done()}


async def test_restarts_fired_together_leave_one_running_process() -> None:
    built: list[int] = []

    async def tick() -> None:
        return None

    def factory() -> LoopProcess:
        built.append(1)
        return LoopProcess(interval_s=0.01, tick=tick)

    reg = await _registry()
    reg.register(_spec("a", factory))
    await reg.start_boot()
    await asyncio.gather(*(reg.restart("a") for _ in range(8)))
    assert reg.status("a") is ProcessStatus.RUNNING
    assert len(_own_tasks()) == 1
    assert len(built) == 9
    await reg.stop_all()
    assert not _own_tasks()


async def test_a_module_opened_twice_at_once_loads_its_model_once() -> None:
    loads: list[int] = []
    gate = asyncio.Event()

    async def load() -> None:
        loads.append(1)
        await gate.wait()

    reg = await _registry()
    reg.register(_spec("model", lambda: ResidentProcess(load=load), start_mode="lazy"))
    first = reg.ensure_for_module("mod")
    second = reg.ensure_for_module("mod")
    assert first["queued"] == ["model"]
    assert second["queued"] == []
    assert second["loading"] == ["model"]
    await _until(lambda: reg.status("model") is ProcessStatus.STARTING)
    assert await reg.ensure_started("model") is False
    gate.set()
    await _until(lambda: reg.status("model") is ProcessStatus.RUNNING)
    assert reg.ensure_for_module("mod")["running"] == ["model"]
    assert len(loads) == 1
    await reg.stop_all()


async def test_disable_while_a_model_is_loading_leaves_nothing_behind() -> None:
    unloaded: list[int] = []

    async def load() -> None:
        await asyncio.sleep(30)

    reg = await _registry()
    reg.register(_spec("model", lambda: ResidentProcess(load=load, unload=lambda: unloaded.append(1))))
    await reg.start_boot()
    assert reg.status("model") is ProcessStatus.STARTING
    await reg.disable("model")
    assert reg.status("model") is ProcessStatus.DISABLED
    assert not _own_tasks()
    assert unloaded == [1]
    # Opening the module afterwards must not bring it back.
    assert reg.ensure_for_module("mod")["disabled"] == ["model"]
    await asyncio.sleep(0.05)
    assert not _own_tasks()
    await reg.stop_all()


async def test_disable_cancels_a_pending_retry() -> None:
    attempts: list[int] = []

    async def run() -> None:
        attempts.append(1)
        raise RuntimeError("down")

    reg = await _registry()
    reg.register(_spec("job", lambda: OneShotProcess(run=run), backoff_base_s=0.2, max_retries=5))
    await reg.start_boot()
    await _until(lambda: reg.status("job") is ProcessStatus.ERROR and _retry_tasks())
    await reg.disable("job")
    assert not _retry_tasks()
    await asyncio.sleep(0.4)
    assert len(attempts) == 1
    assert reg.status("job") is ProcessStatus.DISABLED
    assert not _own_tasks()
    await reg.stop_all()


async def test_a_finished_one_shot_is_not_run_again_by_boot_or_module_open() -> None:
    runs: list[int] = []

    async def run() -> None:
        runs.append(1)

    reg = await _registry()
    reg.register(_spec("job", lambda: OneShotProcess(run=run)))
    reg.schedule_boot(delay_s=0)
    await _until(lambda: runs and reg.status("job") is ProcessStatus.IDLE)
    await reg.start_boot()
    reg.ensure_for_module("mod")
    reg.schedule_boot(delay_s=0)
    await asyncio.sleep(0.1)
    assert len(runs) == 1
    # An explicit restart is the one way to run it again.
    await reg.restart("job")
    await _until(lambda: len(runs) == 2)
    await reg.stop_all()


async def test_a_one_shot_with_no_restart_policy_is_not_retried() -> None:
    attempts: list[int] = []

    async def run() -> None:
        attempts.append(1)
        raise RuntimeError("down")

    reg = await _registry()
    reg.register(_spec("job", lambda: OneShotProcess(run=run), restart_policy="never", backoff_base_s=0.01))
    await reg.start_boot()
    await _until(lambda: reg.status("job") is ProcessStatus.ERROR)
    await asyncio.sleep(0.1)
    assert len(attempts) == 1
    assert not _retry_tasks()
    await reg.stop_all()


async def test_a_dependency_still_loading_does_not_fail_the_process_that_needs_it() -> None:
    """vector_backfill needs vector_db, and vector_db is a resident load.

    Starting the dependent while its dependency is still loading must wait for
    it, not record an error and fall back on the retry timer.
    """
    gate = asyncio.Event()
    runs: list[int] = []

    async def load() -> None:
        await gate.wait()

    async def run() -> None:
        runs.append(1)

    reg = await _registry()
    reg.register(_spec("store", lambda: ResidentProcess(load=load)))
    reg.register(_spec("backfill", lambda: OneShotProcess(run=run), dependencies=["store"], backoff_base_s=60))
    starting = asyncio.create_task(reg.start_boot())
    await _until(lambda: reg.status("store") is ProcessStatus.STARTING)
    gate.set()
    await starting
    await _until(lambda: runs or reg.status("backfill") is ProcessStatus.ERROR)
    assert reg.describe("backfill")["last_error"] is None, reg.describe("backfill")["last_error"]
    assert runs == [1]
    await reg.stop_all()
