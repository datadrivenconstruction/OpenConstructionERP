# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The process registry: one place that knows every background process.

Each process is declared once with a :class:`ProcessSpec`. The registry decides
whether it should run (env override, then persisted choice, then the default
for this kind of installation), starts boot processes, starts lazy ones on
first use, and lets an admin enable, disable or restart any of them without
restarting the platform. A process that crashes is marked ``error`` and is
retried with exponential backoff; it never takes the app down.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import inspect
import logging
import time
import traceback
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.core.processes.base import ManagedProcess
from app.core.processes.store import FIRST_RUN_KEY, FRESH_KEY, InMemoryProcessStore, ProcessStore

logger = logging.getLogger(__name__)

Category = Literal["ai_model", "vector_index", "scheduler", "cache_warmup", "sync", "maintenance"]
StartMode = Literal["boot", "lazy", "manual"]
RestartPolicy = Literal["never", "on_failure"]

LOG_BUFFER_LINES = 200
_RECONCILE_EVERY_S = 5.0


class ProcessStatus(enum.StrEnum):
    """Lifecycle state of one process."""

    DISABLED = "disabled"
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    ERROR = "error"
    STOPPING = "stopping"


_ACTIVE = {ProcessStatus.STARTING, ProcessStatus.RUNNING, ProcessStatus.DEGRADED}


class ProcessError(Exception):
    """An admin action that is not allowed for this process."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ProcessSpec:
    """Declaration of one background process.

    Attributes:
        id: Stable snake_case id, also the i18n key stem ``processes.<id>``.
        factory: Builds a fresh :class:`ManagedProcess` for every start.
        modules: Module ids that need this process; empty means core.
        category: Kind of process, drives grouping in the UI.
        start_mode: ``boot`` starts at startup, ``lazy`` on first use,
            ``manual`` only when an admin asks.
        default_enabled: Desired state on a fresh installation.
        legacy_enabled: Desired state on an installation that predates the
            processes center and has no saved choice, so an upgrade keeps
            today's behaviour.
        required: Core needs it; it cannot be disabled.
        stoppable: False for things that can only be reported (no stop path).
        estimated_ram_mb: Rough resident cost while running.
        dependencies: Process ids that must run first.
        restart_policy: ``on_failure`` retries a crash with backoff.
        max_retries: Retries before the process stays in ``error``.
        backoff_base_s: First retry delay, doubled each time.
        backoff_max_s: Retry delay cap.
        env_override: Returns True/False when an explicit environment setting
            decides, or None to let the admin decide.
        logger_names: Loggers whose records go to this process's log buffer.
        state_get: Reads the desired state from an existing switch instead of
            the registry's table (the semantic-search switch, for example).
            Returning None hands the decision back to the table and defaults,
            so a process can follow a switch on some installations only.
        state_set: Writes that switch; required together with ``state_get``.
    """

    id: str
    factory: Callable[[], ManagedProcess]
    modules: list[str] = field(default_factory=list)
    category: Category = "maintenance"
    start_mode: StartMode = "boot"
    default_enabled: bool = True
    legacy_enabled: bool = True
    required: bool = False
    stoppable: bool = True
    estimated_ram_mb: int = 0
    dependencies: list[str] = field(default_factory=list)
    restart_policy: RestartPolicy = "on_failure"
    max_retries: int = 5
    backoff_base_s: float = 2.0
    backoff_max_s: float = 300.0
    env_override: Callable[[], bool | None] | None = None
    logger_names: list[str] = field(default_factory=list)
    state_get: Callable[[], bool | None] | None = None
    state_set: Callable[[bool], object] | None = None


class _BufferHandler(logging.Handler):
    def __init__(self, buffer: deque[str]) -> None:
        super().__init__(level=logging.INFO)
        self.buffer = buffer
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append(self.format(record))
        except Exception:  # pragma: no cover - a log line must never break the caller
            self.handleError(record)


class _Entry:
    """Runtime state the registry keeps for one process."""

    def __init__(self, spec: ProcessSpec) -> None:
        self.spec = spec
        self.status = ProcessStatus.DISABLED
        self.process: ManagedProcess | None = None
        self.last_error: dict[str, str] | None = None
        self.restart_count = 0
        self.next_retry_at: datetime | None = None
        self.started_at: datetime | None = None
        self.last_run_ok: bool | None = None
        self.retry_task: asyncio.Task[None] | None = None
        self.lock = asyncio.Lock()
        self.logs: deque[str] = deque(maxlen=LOG_BUFFER_LINES)
        self.handler = _BufferHandler(self.logs)
        self.attached: list[str] = []
        self.generation = 0
        self.booted = False
        self.queued = False


class _Reporter:
    """Routes callbacks from one started process back to its entry."""

    def __init__(self, registry: ProcessRegistry, entry: _Entry, generation: int) -> None:
        self.registry = registry
        self.entry = entry
        self.generation = generation

    def _current(self) -> bool:
        return self.entry.generation == self.generation

    def tick_ok(self) -> None:
        if self._current() and self.entry.status is ProcessStatus.DEGRADED:
            self.registry._set(self.entry, ProcessStatus.RUNNING)

    def tick_failed(self, exc: BaseException) -> None:
        if not self._current():
            return
        self.registry._record_error(self.entry, exc)
        if self.entry.status is ProcessStatus.RUNNING:
            self.registry._set(self.entry, ProcessStatus.DEGRADED)

    def finished(self) -> None:
        if not self._current():
            return
        self.entry.last_run_ok = True
        self.entry.restart_count = 0
        self.registry._set(self.entry, ProcessStatus.IDLE)

    def crashed(self, exc: BaseException) -> None:
        if not self._current():
            return
        self.entry.last_run_ok = False
        self.registry._fail(self.entry, exc)

    def ready(self) -> None:
        if self._current() and self.entry.status is ProcessStatus.STARTING:
            self.entry.started_at = datetime.now(UTC)
            self.registry._set(self.entry, ProcessStatus.RUNNING)


class ProcessRegistry:
    """Registry of background processes for this OS process.

    Args:
        store: Where desired state is persisted.
        publish: Async callback receiving ``processes.state_changed`` payloads.
    """

    def __init__(
        self,
        store: ProcessStore | None = None,
        publish: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.store: ProcessStore = store or InMemoryProcessStore()
        self._publish = publish
        self._entries: dict[str, _Entry] = {}
        self._rows: dict[str, bool] = {}
        self._fresh = False
        self._loaded = False
        self._last_reconcile = 0.0
        self._bg: set[asyncio.Task[Any]] = set()
        self._queue: list[str] = []
        self._queue_wakeup: asyncio.Event | None = None
        self._worker: asyncio.Task[None] | None = None
        self._boot_task: asyncio.Task[None] | None = None
        #: Pause between two queued starts, so heavy loads never overlap.
        self.stagger_s = 1.0
        #: Longest a queued start may stay ``starting`` before the queue moves on.
        self.settle_timeout_s = 600.0

    # -- declaration -------------------------------------------------------

    def register(self, spec: ProcessSpec) -> None:
        """Declare a process. Registering the same id again replaces the spec."""
        entry = self._entries.get(spec.id)
        if entry is None:
            entry = _Entry(spec)
            self._entries[spec.id] = entry
        else:
            entry.spec = spec
        for name in entry.attached:
            logging.getLogger(name).removeHandler(entry.handler)
        entry.attached = [*spec.logger_names, f"app.processes.{spec.id}"]
        for name in entry.attached:
            logging.getLogger(name).addHandler(entry.handler)
        if entry.status not in _ACTIVE and entry.status is not ProcessStatus.STOPPING:
            entry.status = self._resting_status(entry)

    def ids(self) -> list[str]:
        """Return every registered process id."""
        return list(self._entries)

    async def load(self, fresh_install: Callable[[], bool | Awaitable[bool]] | None = None) -> None:
        """Read persisted state and classify the installation once.

        Args:
            fresh_install: Answers whether this is a brand new installation.
                Asked only the first time, then remembered in the store.
        """
        self._rows = await self.store.load()
        if FRESH_KEY not in self._rows:
            fresh = False
            if fresh_install is not None:
                answer = fresh_install()
                fresh = bool(await answer) if inspect.isawaitable(answer) else bool(answer)
            await self._save(FRESH_KEY, fresh)
        self._fresh = self._rows[FRESH_KEY]
        self._loaded = True
        self._last_reconcile = time.monotonic()
        for entry in self._entries.values():
            if entry.status not in _ACTIVE:
                entry.status = self._resting_status(entry)

    @property
    def first_run_done(self) -> bool:
        """Whether the first-run wizard was answered (always true on upgrades)."""
        return self._rows.get(FIRST_RUN_KEY, not self._fresh)

    # -- desired state -----------------------------------------------------

    def _env(self, entry: _Entry) -> bool | None:
        if entry.spec.env_override is None:
            return None
        try:
            return entry.spec.env_override()
        except Exception:
            logger.warning("env_override of %s failed", entry.spec.id, exc_info=True)
            return None

    def _desired(self, entry: _Entry) -> bool:
        spec = entry.spec
        env = self._env(entry)
        if env is not None:
            return env
        if spec.required:
            return True
        switch = self._switch_value(entry)
        if switch is not None:
            return switch
        if spec.id in self._rows:
            return self._rows[spec.id]
        return spec.default_enabled if self._fresh else spec.legacy_enabled

    def _switch_value(self, entry: _Entry) -> bool | None:
        """The external switch's answer, or None when the table decides."""
        if entry.spec.state_get is None:
            return None
        try:
            value = entry.spec.state_get()
        except Exception:
            logger.warning("state_get of %s failed", entry.spec.id, exc_info=True)
            return False
        return None if value is None else bool(value)

    def _resting_status(self, entry: _Entry) -> ProcessStatus:
        return ProcessStatus.IDLE if self._desired(entry) else ProcessStatus.DISABLED

    def _get(self, process_id: str) -> _Entry:
        entry = self._entries.get(process_id)
        if entry is None:
            raise ProcessError(f"Unknown process '{process_id}'", status_code=404)
        return entry

    def is_enabled(self, process_id: str) -> bool:
        """Return whether the process should run (lazy ones may not be loaded yet)."""
        return self._desired(self._get(process_id))

    def status(self, process_id: str) -> ProcessStatus:
        """Return the current status."""
        return self._get(process_id).status

    @property
    def fresh_install(self) -> bool:
        """Whether this installation started with the processes center."""
        return self._fresh

    async def _persist(self, entry: _Entry, enabled: bool, updated_by: str | None) -> None:
        if entry.spec.state_set is not None and self._switch_value(entry) is not None:
            await asyncio.to_thread(entry.spec.state_set, enabled)
        else:
            await self._save(entry.spec.id, enabled, updated_by)

    async def _save(self, key: str, enabled: bool, updated_by: str | None = None) -> None:
        self._rows[key] = enabled
        try:
            await self.store.save(key, enabled, updated_by)
        except Exception:
            logger.warning("Could not persist process setting %s", key, exc_info=True)

    # -- events and errors -------------------------------------------------

    def _set(self, entry: _Entry, new: ProcessStatus) -> None:
        old = entry.status
        if old is new:
            return
        entry.status = new
        if self._publish is None:
            return
        payload: dict[str, Any] = {"process_id": entry.spec.id, "old": old.value, "new": new.value}
        if new is ProcessStatus.ERROR and entry.last_error:
            payload["error"] = entry.last_error["message"]
        try:
            task = asyncio.get_running_loop().create_task(self._publish(payload), name="process-event")
        except RuntimeError:
            return
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    def _record_error(self, entry: _Entry, exc: BaseException) -> None:
        tb_id = uuid.uuid4().hex[:12]
        entry.last_error = {
            "message": f"{type(exc).__name__}: {exc}",
            "at": datetime.now(UTC).isoformat(),
            "traceback_id": tb_id,
        }
        trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        logging.getLogger(f"app.processes.{entry.spec.id}").error("[%s] %s", tb_id, trace.rstrip())

    def _fail(self, entry: _Entry, exc: BaseException, retry: bool = True) -> None:
        self._record_error(entry, exc)
        self._set(entry, ProcessStatus.ERROR)
        spec = entry.spec
        if not retry or spec.restart_policy != "on_failure" or entry.restart_count >= spec.max_retries:
            entry.next_retry_at = None
            return
        delay = min(spec.backoff_base_s * (2**entry.restart_count), spec.backoff_max_s)
        entry.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
        generation = entry.generation
        try:
            entry.retry_task = asyncio.get_running_loop().create_task(
                self._retry(entry, delay, generation), name=f"process-retry:{spec.id}"
            )
        except RuntimeError:
            entry.next_retry_at = None

    async def _retry(self, entry: _Entry, delay: float, generation: int) -> None:
        await asyncio.sleep(delay)
        if entry.generation != generation or entry.status is not ProcessStatus.ERROR or not self._desired(entry):
            return
        entry.retry_task = None
        entry.next_retry_at = None
        entry.restart_count += 1
        async with entry.lock:
            await self._stop_locked(entry, final=None)
            await self._start_locked(entry)

    # -- lifecycle ---------------------------------------------------------

    async def _start_locked(self, entry: _Entry) -> None:
        if entry.status in _ACTIVE:
            return
        for dep in entry.spec.dependencies:
            dep_entry = self._entries.get(dep)
            if dep_entry is None or not self._desired(dep_entry):
                self._fail(entry, RuntimeError(f"dependency '{dep}' is disabled"), retry=False)
                return
            await self.ensure_started(dep)
            # A resident dependency (a model, a store) is still ``starting``
            # while it loads; judging it then would fail a process whose
            # dependency is healthy, just not ready yet.
            waited = 0.0
            while dep_entry.status is ProcessStatus.STARTING and waited < self.settle_timeout_s:
                await asyncio.sleep(0.05)
                waited += 0.05
            if dep_entry.status not in {ProcessStatus.RUNNING, ProcessStatus.DEGRADED}:
                self._fail(entry, RuntimeError(f"dependency '{dep}' failed to start"))
                return
        entry.generation += 1
        self._set(entry, ProcessStatus.STARTING)
        try:
            process = entry.spec.factory()
            process.bind(entry.spec.id, _Reporter(self, entry, entry.generation))
            entry.process = process
            await process.start()
        except Exception as exc:
            entry.last_run_ok = False
            self._fail(entry, exc)
            return
        if process.reports_ready:
            return
        entry.started_at = datetime.now(UTC)
        if entry.status is ProcessStatus.STARTING:
            self._set(entry, ProcessStatus.RUNNING)

    async def _stop_locked(self, entry: _Entry, final: ProcessStatus | None) -> None:
        entry.generation += 1
        retry, entry.retry_task = entry.retry_task, None
        entry.next_retry_at = None
        if retry is not None and retry is not asyncio.current_task() and not retry.done():
            retry.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await retry
        process, entry.process = entry.process, None
        if process is not None:
            if entry.status in _ACTIVE:
                self._set(entry, ProcessStatus.STOPPING)
            try:
                await process.stop()
            except Exception as exc:
                self._record_error(entry, exc)
        entry.started_at = None
        if final is not None:
            self._set(entry, final)

    async def start(self, process_id: str) -> None:
        """Start one process now if it is enabled."""
        entry = self._get(process_id)
        if not self._desired(entry):
            return
        async with entry.lock:
            await self._start_locked(entry)

    async def ensure_started(self, process_id: str) -> bool:
        """Start a lazy process on first use.

        Returns:
            True when the process is running (or degraded) afterwards.
        """
        entry = self._get(process_id)
        if not self._desired(entry):
            return False
        if entry.status not in _ACTIVE:
            async with entry.lock:
                await self._start_locked(entry)
        return entry.status in {ProcessStatus.RUNNING, ProcessStatus.DEGRADED}

    async def start_boot(self) -> None:
        """Start every enabled ``boot`` process not booted yet. Never raises.

        Safe to call again after more processes were registered: a process is
        booted once, so a finished one-shot job does not run twice.
        """
        for entry in list(self._entries.values()):
            if entry.booted or entry.spec.start_mode != "boot" or not self._desired(entry):
                continue
            entry.booted = True
            try:
                await self.start(entry.spec.id)
            except Exception as exc:  # pragma: no cover - _start_locked already contains failures
                self._fail(entry, exc)

    # -- start queue -------------------------------------------------------

    def enqueue(self, process_ids: list[str]) -> list[str]:
        """Queue processes to start one after another in the background.

        Starts are serial: the next one begins only when the previous one has
        finished loading (or failed), so two models never load at once. Safe
        to call repeatedly; a process already running or queued is skipped.

        Returns:
            The ids actually added to the queue.
        """
        added: list[str] = []
        for pid in process_ids:
            entry = self._get(pid)
            if entry.queued or entry.status in _ACTIVE or not self._desired(entry):
                continue
            # A one-shot job that already finished this run stays done; an
            # explicit restart is the way to run it again.
            if entry.last_run_ok:
                continue
            entry.queued = True
            self._queue.append(pid)
            added.append(pid)
        if added:
            self._ensure_worker()
        return added

    def _ensure_worker(self) -> None:
        if self._queue_wakeup is None:
            self._queue_wakeup = asyncio.Event()
        self._queue_wakeup.set()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._drain(), name="process-queue")

    async def _drain(self) -> None:
        while self._queue:
            pid = self._queue.pop(0)
            entry = self._entries[pid]
            try:
                await self.ensure_started(pid)
                waited = 0.0
                while entry.status is ProcessStatus.STARTING and waited < self.settle_timeout_s:
                    await asyncio.sleep(0.05)
                    waited += 0.05
            except Exception as exc:  # pragma: no cover - ensure_started contains failures
                self._fail(entry, exc)
            finally:
                entry.queued = False
            if self._queue:
                await asyncio.sleep(self.stagger_s)

    def schedule_boot(self, delay_s: float = 2.0) -> asyncio.Task[None]:
        """Queue every enabled ``boot`` process after ``delay_s`` seconds.

        Called from startup instead of awaiting :meth:`start_boot`, so the
        server answers health checks and logins before any background
        process loads.
        """

        async def later() -> None:
            await asyncio.sleep(delay_s)
            pending = []
            for entry in self._entries.values():
                if entry.booted or entry.spec.start_mode != "boot" or not self._desired(entry):
                    continue
                entry.booted = True
                pending.append(entry.spec.id)
            self.enqueue(pending)

        self._boot_task = asyncio.get_running_loop().create_task(later(), name="process-boot")
        return self._boot_task

    def processes_for_module(self, module_id: str) -> list[str]:
        """Ids of the processes that declare ``module_id`` among their modules."""
        return [e.spec.id for e in self._entries.values() if module_id in e.spec.modules]

    def ensure_for_module(self, module_id: str) -> dict[str, Any]:
        """Warm up what a module needs, in the background. Idempotent.

        The frontend calls this when the user opens a module, so its processes
        load while the first screen renders instead of at platform start.

        Returns:
            ``queued`` (just added), ``running``, ``loading`` and ``disabled`` ids.
        """
        ids = self.processes_for_module(module_id)
        startable = [pid for pid in ids if self._entries[pid].spec.start_mode in ("boot", "lazy")]
        queued = self.enqueue(startable)
        out: dict[str, list[str]] = {"queued": queued, "running": [], "loading": [], "disabled": []}
        for pid in ids:
            entry = self._entries[pid]
            if not self._desired(entry):
                out["disabled"].append(pid)
            elif entry.status in {ProcessStatus.RUNNING, ProcessStatus.DEGRADED}:
                out["running"].append(pid)
            elif entry.queued or entry.status is ProcessStatus.STARTING:
                out["loading"].append(pid)
        return {"module": module_id, **out}

    # -- flags -------------------------------------------------------------

    def get_flag(self, key: str) -> bool:
        """Read a persisted installation flag (seed markers and the like)."""
        return self._rows.get(f"flag:{key}", False)

    async def set_flag(self, key: str, value: bool = True) -> None:
        """Persist an installation flag under ``flag:<key>``."""
        await self._save(f"flag:{key}", value)

    async def stop_all(self) -> None:
        """Stop everything (shutdown). Idempotent."""
        self._queue.clear()
        for task in (self._boot_task, self._worker):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._boot_task = self._worker = None
        for entry in self._entries.values():
            entry.queued = False
        for entry in reversed(list(self._entries.values())):
            async with entry.lock:
                await self._stop_locked(entry, final=self._resting_status(entry))
        if self._bg:
            await asyncio.gather(*list(self._bg), return_exceptions=True)

    # -- admin actions -----------------------------------------------------

    def _check_mutable(self, entry: _Entry) -> None:
        if self._env(entry) is not None:
            raise ProcessError(f"'{entry.spec.id}' is controlled by an environment setting")
        if entry.spec.required:
            raise ProcessError(f"'{entry.spec.id}' is required by the core")
        if not entry.spec.stoppable:
            raise ProcessError(f"'{entry.spec.id}' cannot be controlled at runtime")

    async def enable(self, process_id: str, updated_by: str | None = None) -> None:
        """Persist "on" and start the process unless it is lazy."""
        entry = self._get(process_id)
        self._check_mutable(entry)
        await self._persist(entry, True, updated_by)
        entry.restart_count = 0
        if entry.spec.state_set is not None:
            await self.reconcile(force=True)
        async with entry.lock:
            if entry.spec.start_mode == "lazy":
                if entry.status not in _ACTIVE:
                    self._set(entry, ProcessStatus.IDLE)
                return
            await self._start_locked(entry)

    async def disable(self, process_id: str, updated_by: str | None = None) -> None:
        """Persist "off" and stop the process."""
        entry = self._get(process_id)
        self._check_mutable(entry)
        await self._persist(entry, False, updated_by)
        async with entry.lock:
            await self._stop_locked(entry, final=ProcessStatus.DISABLED)
        if entry.spec.state_set is not None:
            await self.reconcile(force=True)

    async def restart(self, process_id: str) -> None:
        """Stop and start the process again, resetting its retry counter."""
        entry = self._get(process_id)
        if not entry.spec.stoppable:
            raise ProcessError(f"'{process_id}' cannot be controlled at runtime")
        if not self._desired(entry):
            raise ProcessError(f"'{process_id}' is disabled")
        entry.restart_count = 0
        async with entry.lock:
            await self._stop_locked(entry, final=None)
            entry.status = ProcessStatus.IDLE
            await self._start_locked(entry)

    async def reconcile(self, force: bool = False) -> None:
        """Re-read desired state (another worker may have changed it) and apply it."""
        now = time.monotonic()
        if not self._loaded or (not force and now - self._last_reconcile < _RECONCILE_EVERY_S):
            return
        self._last_reconcile = now
        self._rows = await self.store.load() or self._rows
        for entry in list(self._entries.values()):
            desired = self._desired(entry)
            if not desired and entry.status is not ProcessStatus.DISABLED:
                async with entry.lock:
                    await self._stop_locked(entry, final=ProcessStatus.DISABLED)
            elif desired and entry.status is ProcessStatus.DISABLED:
                self._set(entry, ProcessStatus.IDLE)
                if entry.spec.start_mode == "boot":
                    entry.booted = True
                    self.enqueue([entry.spec.id])

    # -- first run and presets ---------------------------------------------

    def _wanted_for(self, module_ids: list[str]) -> list[_Entry]:
        wanted = set(module_ids)
        out: list[_Entry] = []
        for entry in self._entries.values():
            spec = entry.spec
            core_default = not spec.modules and (spec.default_enabled or spec.required)
            if core_default or wanted.intersection(spec.modules):
                out.append(entry)
        return out

    def recommendations(self, module_ids: list[str]) -> dict[str, Any]:
        """Processes to switch on for the given modules, plus their RAM estimate."""
        entries = self._wanted_for(module_ids)
        return {
            "process_ids": [e.spec.id for e in entries],
            "total_ram_mb_estimate": sum(e.spec.estimated_ram_mb for e in entries),
        }

    async def _apply_set(self, wanted: set[str], start_now: bool, updated_by: str | None) -> None:
        to_start: list[str] = []
        for entry in list(self._entries.values()):
            spec = entry.spec
            if self._env(entry) is not None or spec.required or not spec.stoppable:
                continue
            on = spec.id in wanted
            if on == self._desired(entry) and (spec.id in self._rows or self._switch_value(entry) is not None):
                continue
            if on:
                await self._persist(entry, True, updated_by)
                if entry.status is ProcessStatus.DISABLED:
                    self._set(entry, ProcessStatus.IDLE)
                if start_now and spec.start_mode == "boot":
                    entry.booted = True
                    to_start.append(spec.id)
            else:
                await self.disable(spec.id, updated_by)
        if to_start:
            self.enqueue(to_start)

    async def first_run(self, module_ids: list[str], start_now: bool, updated_by: str | None = None) -> None:
        """Answer the first-run wizard: run exactly what the chosen modules need."""
        wanted = {e.spec.id for e in self._wanted_for(module_ids)}
        await self._apply_set(wanted, start_now, updated_by)
        await self._save(FIRST_RUN_KEY, True, updated_by)

    async def apply_preset(self, preset: str, updated_by: str | None = None) -> None:
        """Apply ``minimal`` (core defaults), ``recommended`` (fresh defaults) or ``all``."""
        if preset == "minimal":
            wanted = {e.spec.id for e in self._wanted_for([])}
        elif preset == "recommended":
            wanted = {e.spec.id for e in self._entries.values() if e.spec.default_enabled}
        elif preset == "all":
            wanted = set(self._entries)
        else:
            raise ProcessError(f"Unknown preset '{preset}'", status_code=422)
        await self._apply_set(wanted, True, updated_by)

    # -- reporting ---------------------------------------------------------

    def logs(self, process_id: str, limit: int = LOG_BUFFER_LINES) -> list[str]:
        """Return the last ``limit`` captured log lines of a process."""
        lines = list(self._get(process_id).logs)
        return lines[-limit:] if limit > 0 else []

    def describe(self, process_id: str, log_lines: int = 20) -> dict[str, Any]:
        """Serialise one process for the API."""
        entry = self._get(process_id)
        spec = entry.spec
        return {
            "id": spec.id,
            "name_key": f"processes.{spec.id}.name",
            "purpose_key": f"processes.{spec.id}.purpose",
            "off_impact_key": f"processes.{spec.id}.off_impact",
            "category": spec.category,
            "modules": list(spec.modules),
            "start_mode": spec.start_mode,
            "default_enabled": spec.default_enabled,
            "enabled": self._desired(entry),
            "required": spec.required,
            "stoppable": spec.stoppable,
            "env_locked": self._env(entry) is not None,
            "status": entry.status.value,
            "queued": entry.queued,
            "ram_mb_estimate": spec.estimated_ram_mb,
            "ram_mb_actual": None,
            "dependencies": list(spec.dependencies),
            "last_error": dict(entry.last_error) if entry.last_error else None,
            "last_run_ok": entry.last_run_ok,
            "restart_count": entry.restart_count,
            "next_retry_at": entry.next_retry_at.isoformat() if entry.next_retry_at else None,
            "started_at": entry.started_at.isoformat() if entry.started_at else None,
            "log_tail": self.logs(spec.id, log_lines),
        }

    def describe_all(self) -> dict[str, Any]:
        """Serialise the whole registry for ``GET /api/v1/processes``."""
        items = [self.describe(pid) for pid in self._entries]
        return {
            "processes": items,
            "total_ram_mb_estimate": sum(
                i["ram_mb_estimate"] for i in items if i["status"] in {s.value for s in _ACTIVE}
            ),
            "process_rss_mb": process_rss_mb(),
            "first_run_done": self.first_run_done,
        }


def process_rss_mb() -> int | None:
    """Resident memory of this OS process in MB, or None when not measurable."""
    try:
        import psutil  # type: ignore[import-untyped]

        return int(psutil.Process().memory_info().rss / (1024 * 1024))
    except Exception:
        pass
    try:
        import os

        with open("/proc/self/statm", encoding="ascii") as fh:
            pages = int(fh.read().split()[1])
        return int(pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
    except Exception:
        return None
