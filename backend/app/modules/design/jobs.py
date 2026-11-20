"""Server worker (card R13): generate a revision from the confirmed brief with the operator's `ddc` binary.

The ERP job queue (``app.core.job_runner``) only carries the work. State, progress, log and cancellation live in the
module's own ``oe_design_job`` row, because the queue has no cancel and writes its own result over a cancelled run.
The job holds the project lock for its whole run, so an editor holding the lock means "409" and the finished package
goes through the normal intake as a pending (``shared``) revision.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .auth import Principal, as_aware, now_utc
from .models import DesignJob, DesignRevision
from .settings import get_design_settings
from .worker_guard import require_runner

log = logging.getLogger(__name__)

KIND = "design.generate"
ACTIVE = ("queued", "running")
LOG_LINES = 200  # ddc-job/1 log_tail maxItems
LOG_LINE_CHARS = 500
LOCK_ENTITY = "project"
LOCK_TTL_S = 600
KILL_GRACE_S = 3.0
# The child gets only what a command line tool needs to start; never the ERP's own settings or secrets.
ENV_KEEP = (
    "PATH",
    "SYSTEMROOT",
    "SystemDrive",
    "windir",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
)

_SECRET = re.compile(
    r"(ddcl_[A-Za-z0-9_\-]+|\boe_[A-Za-z0-9]{16,}|\bsk-[A-Za-z0-9_\-]{12,}|Bearer\s+\S+"
    r"|(?i:(?:api[_-]?key|token|secret|password|authorization))\s*[=:]\s*(?:Bearer\s+)?\S+)"
)


class Cancelled(Exception):
    """The person cancelled the job."""


class JobFailed(Exception):
    """The run cannot go on; the message is shown to the person (no secrets, no host paths)."""


def redact(line: str, *hide: str) -> str:
    for text in hide:
        if text:
            line = line.replace(text, "<path>")
    return _SECRET.sub("<hidden>", line)[:LOG_LINE_CHARS]


# ── The binary ──────────────────────────────────────────────────────────────


def cli_state() -> tuple[Path | None, str | None]:
    """(path, None) when generation can run, else (None, reason). Never guessed from PATH."""
    raw = get_design_settings().ddc_cli.strip()
    if not raw:
        return None, "Generation on the server is not set up: OE_DESIGN_DDC_CLI is not set."
    path = Path(raw)
    if not path.is_file():
        return None, "Generation on the server is not available: the file named by OE_DESIGN_DDC_CLI does not exist."
    return path, None


def require_cli() -> Path:
    path, reason = cli_state()
    if path is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, reason)
    return path


# ── Views ───────────────────────────────────────────────────────────────────


def job_view(job: DesignJob) -> dict[str, Any]:
    """ddc-job/1 exactly (the schema allows nothing else)."""
    out: dict[str, Any] = {
        "job_id": str(job.id),
        "status": job.status,
        "progress": min(1.0, max(0.0, float(job.progress or 0))),
        "log_tail": list(job.log or [])[-LOG_LINES:],
        "error": job.error,
    }
    if job.status == "done" and job.revision_id:
        out["revision_id"] = str(job.revision_id)
    return out


async def active_job(session, project_id: uuid.UUID) -> DesignJob | None:
    return (
        await session.execute(select(DesignJob).where(DesignJob.project_id == project_id, DesignJob.slot == "1"))
    ).scalar_one_or_none()


# ── Lock helpers (own sessions: the job outlives the request) ───────────────


async def _release_lock(factory, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    from app.modules.collaboration_locks.service import CollabLockService

    try:
        async with factory() as s:
            svc = CollabLockService(s)
            lock = await svc.get_for_entity(entity_type=LOCK_ENTITY, entity_id=project_id)
            if lock is not None and lock.user_id == user_id:
                await svc.release(lock_id=lock.id, user_id=user_id)
            await s.commit()
    except Exception:  # noqa: BLE001 - the lock expires by itself
        log.warning("design job: could not release the project lock", exc_info=True)


async def sweep_stale(session, project_id: uuid.UUID | None = None) -> int:
    """Active jobs nobody works on any more (ERP restarted, worker killed) fail cleanly and free their slot."""
    from app.database import async_session_factory

    cfg = get_design_settings()
    now = now_utc()
    q = select(DesignJob).where(DesignJob.slot == "1")
    if project_id is not None:
        q = q.where(DesignJob.project_id == project_id)
    lost: list[DesignJob] = []
    for job in (await session.execute(q)).scalars():
        beat = as_aware(job.heartbeat_at or job.created_at)
        limit = cfg.job_queue_wait_seconds if job.status == "queued" else cfg.job_stale_seconds
        if (now - beat).total_seconds() > limit:
            lost.append(job)
    for job in lost:
        done = await session.execute(
            update(DesignJob)
            .where(DesignJob.id == job.id, DesignJob.slot == "1")
            .values(
                status="failed",
                slot=None,
                finished_at=now,
                error="The worker was lost (the ERP restarted or the process was killed). Start the generation again.",
            )
        )
        if done.rowcount == 1:
            await _release_lock(async_session_factory, job.project_id, job.user_id)
    if lost:
        await session.commit()
    return len(lost)


# ── Start / cancel ──────────────────────────────────────────────────────────


def brief_problems(doc: dict) -> dict[str, Any] | None:
    """What stops a brief from being generated from: incomplete or values nobody confirmed."""
    from .brief_doc import schema_errors

    errors = [e for e in schema_errors(doc)]
    unconfirmed = sorted(
        p for p, e in (doc.get("provenance") or {}).items() if isinstance(e, dict) and e.get("status") != "confirmed"
    )
    if errors or unconfirmed:
        return {"message": "The brief is not confirmed", "errors": errors[:20], "unconfirmed": unconfirmed[:50]}
    return None


async def start_generation(project_id: uuid.UUID, user_id: uuid.UUID, brief_version: int) -> DesignJob:
    """Gates, lock, job row, enqueue. Own sessions and commits, so a caller's transaction cannot hide the job."""
    from app.core.job_runner import submit_job
    from app.database import async_session_factory
    from app.modules.collaboration_locks.service import CollabLockService, LockConflictError

    from .brief import current_brief

    require_cli()
    await require_runner()
    async with async_session_factory() as s:
        await sweep_stale(s, project_id)
        if await active_job(s, project_id) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "A generation is already running for this project")
        doc = await current_brief(s, project_id)
        if doc is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "The project has no brief yet")
        if doc.get("version") != brief_version:
            raise HTTPException(
                status.HTTP_409_CONFLICT, {"message": "The brief was changed; reload it", "version": doc.get("version")}
            )
        problems = brief_problems(doc)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problems)
        svc = CollabLockService(s)
        held = await svc.get_for_entity(entity_type=LOCK_ENTITY, entity_id=project_id)
        if held is not None:  # also the caller's own editor: it is editing, nothing may be written under it
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "message": "Project is being edited",
                    "held_by": held.user_name,
                    "expires_at": held.expires_at.isoformat(),
                },
            )
        try:
            lock = await svc.acquire(
                entity_type=LOCK_ENTITY, entity_id=project_id, user_id=user_id, ttl_seconds=LOCK_TTL_S
            )
        except LockConflictError as exc:
            await s.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {"message": "Project is being edited", "held_by": exc.conflict.current_holder_name},
            ) from exc
        job = DesignJob(
            project_id=project_id,
            user_id=user_id,
            brief_version=brief_version,
            status="queued",
            slot="1",
            progress=0.0,
            log=[],
            lock_id=lock.id,
            heartbeat_at=now_utc(),
        )
        s.add(job)
        try:
            await s.commit()
        except IntegrityError as exc:
            await s.rollback()
            await _release_lock(async_session_factory, project_id, user_id)
            raise HTTPException(status.HTTP_409_CONFLICT, "A generation is already running for this project") from exc
        job_id = job.id
    try:
        run = await submit_job(KIND, {"design_job_id": str(job_id)}, idempotency_key=f"design-job-{job_id}")
    except Exception as exc:  # noqa: BLE001
        log.exception("design job: enqueue failed")
        await _finish(job_id, "failed", "The job could not be queued.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The job queue is not available") from exc
    async with async_session_factory() as s:
        await s.execute(update(DesignJob).where(DesignJob.id == job_id).values(job_run_id=run.id))
        await s.commit()
        return await s.get(DesignJob, job_id, populate_existing=True)


async def cancel_generation(session, job: DesignJob) -> DesignJob:
    """Queued: cancelled at once. Running: flagged, the worker stops the process at its next tick."""
    from app.database import async_session_factory

    if job.status not in ACTIVE:
        return job
    done = await session.execute(
        update(DesignJob)
        .where(DesignJob.id == job.id, DesignJob.status == "queued")
        .values(status="cancelled", slot=None, finished_at=now_utc(), cancel_requested=True)
    )
    if done.rowcount == 1:
        await session.commit()
        await _release_lock(async_session_factory, job.project_id, job.user_id)
    else:
        await session.execute(update(DesignJob).where(DesignJob.id == job.id).values(cancel_requested=True))
        await session.commit()
    return await session.get(DesignJob, job.id, populate_existing=True)


# ── The run ─────────────────────────────────────────────────────────────────


class _ThreadStdout:
    def __init__(self, popen: subprocess.Popen):
        self._p = popen

    async def read(self, n: int) -> bytes:
        return await asyncio.to_thread(self._p.stdout.read1, n)


class ThreadProc:
    """A Popen child behind the few calls the runner needs. Plain threads, because the ERP may run on an event loop
    without subprocess support (the Windows selector loop)."""

    def __init__(self, popen: subprocess.Popen):
        self._p = popen
        self.stdout = _ThreadStdout(popen)

    @property
    def returncode(self) -> int | None:
        return self._p.poll()

    async def wait(self) -> int:
        return await asyncio.to_thread(self._p.wait)

    def terminate(self) -> None:
        self._p.terminate()

    def kill(self) -> None:
        self._p.kill()


async def spawn_process(argv: list[str], *, cwd: Path, env: dict[str, str]):
    """argv list, no shell; stdout and stderr merged. Replaced by a fake in the unit tests."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    popen = await asyncio.to_thread(
        lambda: subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
    )
    return ThreadProc(popen)


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in ENV_KEEP}


@dataclass
class _Run:
    job_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    lock_id: uuid.UUID | None
    work: Path
    cli: Path
    deadline: float
    tick: float
    lines: list[str] = field(default_factory=list)
    progress: float = 0.0
    tail: str = ""

    def say(self, text: str) -> None:
        text = redact(text.rstrip("\r\n"), str(self.work), str(self.cli))
        if text.strip():
            self.lines.append(text)
            del self.lines[:-LOG_LINES]


async def _pump(proc, run: _Run) -> None:
    buf = ""
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        *done, buf = buf.split("\n")
        for line in done:
            run.say(line)
    run.say(buf)


async def _housekeeping(run: _Run, factory) -> None:
    """Heartbeat, log flush, cancel flag, project lock renewal. Raises Cancelled / JobFailed."""
    from app.modules.collaboration_locks.service import CollabLockService, NotLockHolderError

    async with factory() as s:
        job = await s.get(DesignJob, run.job_id, populate_existing=True)
        if job is None or job.status != "running":
            raise Cancelled  # swept as lost, or removed: stop quietly
        job.heartbeat_at = now_utc()
        job.log = list(run.lines)
        job.progress = max(float(job.progress or 0), min(run.progress, 0.99))
        cancel = job.cancel_requested
        await s.commit()
    if cancel:
        raise Cancelled
    if run.lock_id is not None:
        try:
            async with factory() as s:
                await CollabLockService(s).heartbeat(
                    lock_id=run.lock_id, user_id=run.user_id, extend_seconds=LOCK_TTL_S
                )
                await s.commit()
        except NotLockHolderError as exc:
            raise JobFailed("The project lock was lost while the model was being generated") from exc


async def _run_cmd(run: _Run, factory, argv: list[str], label: str, lo: float, hi: float) -> None:
    run.say(f"> {label}")
    t0 = time.monotonic()
    run.progress = lo
    proc = await spawn_process(argv, cwd=run.work, env=child_env())
    pump = asyncio.ensure_future(_pump(proc, run))
    waiter = asyncio.ensure_future(proc.wait())
    try:
        while True:
            done, _ = await asyncio.wait({waiter}, timeout=run.tick)
            if done:
                break
            run.progress = lo + (hi - lo) * (1 - math.exp(-(time.monotonic() - t0) / 30.0))
            await _housekeeping(run, factory)
            if time.monotonic() > run.deadline:
                raise JobFailed(f"{label} did not finish in time and was stopped")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(pump, 5)
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                proc.terminate()
            await asyncio.wait({waiter}, timeout=KILL_GRACE_S)
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    proc.kill()
                await asyncio.wait({waiter}, timeout=KILL_GRACE_S)
        for t in (pump, waiter):
            if not t.done():
                t.cancel()
    if proc.returncode != 0:
        last = next((line for line in reversed(run.lines) if not line.startswith(">")), "")
        raise JobFailed(f"{label} failed (exit code {proc.returncode})" + (f": {last}" if last else ""))
    run.progress = hi


async def _parent_package(session, tip: DesignRevision, dest: Path) -> Path:
    """The tip's .ddcrev, rebuilt from the ERP storage (the upload itself is not kept)."""
    from app.core.storage import get_storage_backend

    from .revisions import file_key

    backend = get_storage_backend()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(tip.manifest))
        for item in (tip.manifest or {}).get("files", []):
            with zf.open(item["path"], "w", force_zip64=True) as out:
                async for chunk in backend.open_stream(file_key(tip.storage_prefix, item["path"])):
                    out.write(chunk)
    return dest


async def _finish(
    job_id: uuid.UUID,
    state: str,
    error: str | None = None,
    revision_id: uuid.UUID | None = None,
    lines: list[str] | None = None,
) -> None:
    from app.database import async_session_factory

    async with async_session_factory() as s:
        job = await s.get(DesignJob, job_id, populate_existing=True)
        if job is None or job.slot != "1":
            return
        job.status, job.slot, job.error, job.finished_at = state, None, error, now_utc()
        job.revision_id = revision_id
        if state == "done":
            job.progress = 1.0
        if lines is not None:
            job.log = list(lines)
        project_id, user_id = job.project_id, job.user_id
        await s.commit()
    await _release_lock(async_session_factory, project_id, user_id)


async def run_job(job_id: uuid.UUID, *, tick: float | None = None) -> None:
    """The whole run; never raises. The result is in the job row."""
    from app.database import async_session_factory as factory

    from .brief import current_brief
    from .intake import PackageRejected, verify_package
    from .revisions import design_tip
    from .router import _ingest

    cfg = get_design_settings()
    now = now_utc()
    async with factory() as s:
        started = await s.execute(
            update(DesignJob)
            .where(DesignJob.id == job_id, DesignJob.status == "queued")
            .values(status="running", started_at=now, heartbeat_at=now)
        )
        await s.commit()
        if started.rowcount != 1:
            return  # cancelled or swept before it started
        job = await s.get(DesignJob, job_id, populate_existing=True)
        project_id, user_id, version, lock_id = job.project_id, job.user_id, job.brief_version, job.lock_id
    lines: list[str] = []
    try:
        cli, reason = cli_state()
        if cli is None:
            raise JobFailed(reason)
        with tempfile.TemporaryDirectory(prefix="oe-ddcgen-") as tmp:
            work = Path(tmp)
            run = _Run(
                job_id,
                project_id,
                user_id,
                lock_id,
                work,
                cli,
                deadline=time.monotonic() + cfg.job_timeout_seconds,
                tick=tick if tick is not None else cfg.job_heartbeat_seconds,
                lines=lines,
            )
            async with factory() as s:
                doc = await current_brief(s, project_id)
                if doc is None or doc.get("version") != version:
                    raise JobFailed("The brief was changed after the job was started; start it again")
                tip = await design_tip(s, project_id)
                brief_path = work / "brief.json"
                brief_path.write_text(json.dumps(doc), encoding="utf-8")
                parent = await _parent_package(s, tip, work / "parent.ddcrev") if tip is not None else None
            await _run_cmd(
                run,
                factory,
                [str(cli), "gen", "--brief", str(brief_path), "--out", str(work / "model.ddc"), "--quiet"],
                "ddc gen",
                0.05,
                0.6,
            )
            argv = [
                str(cli),
                "publish",
                str(work / "model.ddc"),
                "--out",
                str(work / "rev.ddcrev"),
                "--brief",
                str(brief_path),
                "--project-id",
                str(project_id),
                "--sheets",
                "--message",
                f"Generated from brief v{version}",
                "--quiet",
            ]
            if parent is not None:
                argv += ["--parent", str(parent)]
            await _run_cmd(run, factory, argv, "ddc publish", 0.6, 0.9)
            package = work / "rev.ddcrev"
            if not package.is_file():
                raise JobFailed("ddc publish finished without writing a package")
            run.say("> intake")
            sha = await asyncio.to_thread(lambda: hashlib.sha256(package.read_bytes()).hexdigest())
            upload = SimpleNamespace(sha256_hex=sha, size=package.stat().st_size, path=package)
            limits = _limits()
            try:
                pkg = await asyncio.to_thread(
                    verify_package, package, work / "pkg", project_id=str(project_id), limits=limits
                )
            except PackageRejected as exc:
                raise JobFailed(f"The package was rejected: {str(exc.detail)[:300]}") from exc
            background = BackgroundTasks()
            async with factory() as s:
                try:
                    rev = await _ingest(s, background, project_id, Principal(user_id, False, None), pkg, upload, work)
                except HTTPException as exc:
                    detail = exc.detail if isinstance(exc.detail, str) else (exc.detail or {}).get("message", "")
                    raise JobFailed(f"The revision could not be stored: {detail}") from exc
                revision_id = rev.id
            await background()
        run.say("done")
        await _finish(job_id, "done", None, revision_id, lines)
    except Cancelled:
        lines.append("cancelled")
        await _finish(job_id, "cancelled", None, None, lines)
    except JobFailed as exc:
        lines.append(redact(str(exc)))
        await _finish(job_id, "failed", redact(str(exc)), None, lines)
    except asyncio.CancelledError:
        await _finish(job_id, "failed", "The ERP stopped while the job was running.", None, lines)
        raise
    except Exception as exc:  # noqa: BLE001
        log.exception("design job %s failed", job_id)
        await _finish(job_id, "failed", f"Unexpected error ({type(exc).__name__}); see the server log.", None, lines)


def _limits():
    from .intake import Limits

    cfg = get_design_settings()
    return Limits(
        max_unpacked=cfg.revision_max_unpacked_bytes,
        max_json=cfg.revision_max_json_bytes,
        max_glb_json=cfg.revision_max_glb_json_bytes,
        max_rows=cfg.revision_max_rows,
    )


async def handle_job(job_run, payload: dict[str, Any]) -> dict[str, Any]:
    """Handler registered on the ERP job queue."""
    await run_job(uuid.UUID(payload["design_job_id"]))
    return {"design_job_id": payload["design_job_id"]}


def register_handler() -> None:
    from app.core.job_runner import register_handler as register

    register(KIND, handle_job)
