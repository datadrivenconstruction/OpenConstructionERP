"""R13: server worker. State machine, timeout, cancel, lock and one-job-per-project against a fake `ddc`;
one run against the real binary (skipped when it is not on this machine)."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import uuid
import zipfile
from pathlib import Path

import pytest

from .conftest import LINK, make_project, make_user
from .ddcrev import example_rows, package
from .test_design_brief import EXAMPLE
from .test_edge_cases import _valid
from .test_mcp import (  # noqa: F401  (autouse _mcp_on comes with the import below)
    _apply_path,
    _call,
    _mcp_on,  # noqa: F401
    _mcp_token,
)

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"
SECRET = "ddcl_" + "a1B2c3D4e5F6g7H8"
REAL_CLI = Path(os.environ.get("DDC_CLI", "ddc.exe"))  # a built editor CLI; the test using it skips when missing


# ── fake binary ─────────────────────────────────────────────────────────────


class _Out:
    def __init__(self, chunks, hang: asyncio.Event | None):
        self.chunks, self.hang = list(chunks), hang

    async def read(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        if self.hang is not None:
            await self.hang.wait()
        return b""


class FakeProc:
    def __init__(self, argv, script):
        self.argv, self.returncode = argv, None
        self.exit = asyncio.Event()
        self.terminated = self.killed = False
        self.ignore_terminate = script.get("ignore_terminate", False)
        self.hang = script.get("hang", False)
        self._rc = script.get("rc", 0)
        self.stdout = _Out(script.get("lines", []), self.exit if self.hang else None)
        if not self.hang:
            self.returncode = self._rc
            self.exit.set()

    async def wait(self):
        await self.exit.wait()
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = -15
            self.exit.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.exit.set()


class Fake:
    """Scripts per command (`gen` / `publish`); records every process started."""

    def __init__(self):
        self.scripts: dict[str, dict] = {}
        self.procs: list[FakeProc] = []
        self.packages: dict[str, bytes] = {}
        self.project_id: str | None = None

    async def spawn(self, argv, *, cwd, env):
        assert isinstance(argv, list) and "shell" not in env
        cmd = argv[1]
        script = self.scripts.get(cmd, {})
        if cmd == "publish" and "--parent" in argv:
            with zipfile.ZipFile(argv[argv.index("--parent") + 1]) as zf:
                if "elements.parquet" not in zf.namelist():  # what the real `ddc publish` refuses
                    script = {"rc": 1, "lines": [b"parent: no elements.parquet\n"]}
        proc = FakeProc(argv, script)
        self.procs.append(proc)
        if cmd == "publish" and script.get("rc", 0) == 0 and not script.get("hang") and script.get("write", True):
            out = Path(argv[argv.index("--out") + 1])
            parent_id = None
            if "--parent" in argv:
                with zipfile.ZipFile(argv[argv.index("--parent") + 1]) as zf:
                    parent_id = json.loads(zf.read("manifest.json"))["revision_id"]
                    self.packages["parent_members"] = json.dumps(sorted(zf.namelist())).encode()
                    self.packages["parent_id"] = parent_id.encode()
            data, _ = package(
                self.project_id, example_rows(), parent_id=parent_id, parent_rows=example_rows() if parent_id else None
            )
            out.write_bytes(data)
        return proc


@pytest.fixture
def fake(monkeypatch, tmp_path):
    from app.core import job_runner
    from app.modules.design import jobs
    from app.modules.design.settings import get_design_settings

    exe = tmp_path / "ddc.exe"
    exe.write_text("fake")
    monkeypatch.setenv("OE_DESIGN_DDC_CLI", str(exe))
    get_design_settings.cache_clear()
    cfg = get_design_settings()
    cfg.job_heartbeat_seconds = 0.05
    f = Fake()
    f.tasks: list[asyncio.Task] = []
    monkeypatch.setattr(jobs, "spawn_process", f.spawn)

    async def submit(kind, payload, **_kw):
        assert kind == jobs.KIND
        job_id = uuid.UUID(payload["design_job_id"])
        if not getattr(f, "hold_queue", False):
            f.tasks.append(asyncio.ensure_future(jobs.run_job(job_id)))
        f.queued = job_id
        return type("Run", (), {"id": uuid.uuid4()})()

    monkeypatch.setattr(job_runner, "submit_job", submit)
    yield f
    for t in f.tasks:
        t.cancel()
    get_design_settings.cache_clear()


async def _settle(f: Fake) -> None:
    """Wait for the worker tasks; a stuck one fails the test instead of hanging the run."""
    await asyncio.wait_for(asyncio.gather(*f.tasks, return_exceptions=True), 60)


async def _project_with_brief(client, *, confirm: bool = True):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    url = f"{BASE}/projects/{pid}/brief"
    doc = (await client.put(url, json=copy.deepcopy(EXAMPLE), headers=h)).json()
    if confirm:
        doc = (
            await client.post(
                f"{url}/confirm",
                json={"pointers": list(doc["provenance"])},
                headers={**h, "If-Match": f'"{doc["version"]}"'},
            )
        ).json()
    return uid, h, pid, doc["version"]


async def _start(client, h, pid, version):
    return await client.post(f"{BASE}/projects/{pid}/generate", json={"brief_version": version}, headers=h)


def _check_job(body: dict) -> None:
    """ddc-job/1 by the schema when jsonschema is installed, else by its plain rules (never a skip)."""
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        assert set(body) <= {"job_id", "status", "progress", "log_tail", "revision_id", "error"}
        assert {"job_id", "status", "progress", "log_tail"} <= set(body)
        assert body["status"] in ("queued", "running", "done", "failed", "cancelled")
        assert 0 <= body["progress"] <= 1 and len(body["log_tail"]) <= 200
        assert body["status"] != "done" or body.get("revision_id")
        return
    assert _valid("job.schema.json", body) == []


async def _job(client, h, job_id) -> dict:
    r = await client.get(f"{BASE}/jobs/{job_id}", headers=h)
    assert r.status_code == 200, r.text
    _check_job(r.json())
    return r.json()


async def _lock_holder(client, h, pid):
    r = await client.get(f"{BASE}/projects/{pid}/context", headers=h)
    return r.json().get("lock")


async def _until(client, h, job_id, states, seconds=10, every=0.05):
    for _ in range(int(seconds / every)):
        j = await _job(client, h, job_id)
        if j["status"] in states:
            return j
        await asyncio.sleep(every)
    raise AssertionError(f"job stayed {j['status']}")


# ── availability and gates ──────────────────────────────────────────────────


async def test_disabled_without_binary_says_why(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h, pid, version = await _project_with_brief(client)
    monkeypatch.delenv("OE_DESIGN_DDC_CLI", raising=False)
    get_design_settings.cache_clear()
    state = (await client.get(f"{BASE}/projects/{pid}/generation", headers=h)).json()
    assert state["enabled"] is False and "OE_DESIGN_DDC_CLI" in state["reason"] and state["job"] is None
    r = await _start(client, h, pid, version)
    assert r.status_code == 503 and "OE_DESIGN_DDC_CLI" in r.text
    monkeypatch.setenv("OE_DESIGN_DDC_CLI", "/no/such/ddc")
    get_design_settings.cache_clear()
    assert "does not exist" in (await client.get(f"{BASE}/projects/{pid}/generation", headers=h)).json()["reason"]
    get_design_settings.cache_clear()


async def test_start_gates(client, fake):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    assert (await _start(client, h, pid, 1)).status_code == 409  # no brief
    _, h2, pid2, version = await _project_with_brief(client, confirm=False)
    r = await _start(client, h2, pid2, version)
    assert r.status_code == 422 and r.json()["detail"]["unconfirmed"]
    uid3, h3, pid3, v3 = await _project_with_brief(client)
    assert (await _start(client, h3, pid3, v3 + 1)).status_code == 409  # stale version
    assert (await client.post(f"{BASE}/projects/{pid3}/generate", json={}, headers=h3)).status_code == 422
    other, h_other = await make_user(client)
    assert (await _start(client, h_other, pid3, v3)).status_code in (403, 404)
    viewer, h_view = await make_user(client, role="viewer")
    assert (await _start(client, h_view, pid3, v3)).status_code in (403, 404)
    assert fake.procs == []


async def test_link_token_cannot_start(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    code = await client.post(f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers={**h, **LINK})
    tok = await client.post(f"{BASE}/link/exchange", json={"code": code.json()["code"]}, headers=LINK)
    r = await _start(client, {"Authorization": f"Bearer {tok.json()['token']}", **LINK}, pid, version)
    assert r.status_code == 403


# ── runs ────────────────────────────────────────────────────────────────────


async def test_happy_path_two_revisions_secrets_hidden(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    fake.project_id = str(pid)
    fake.scripts = {
        "gen": {
            "lines": [
                f"loading brief token={SECRET}\n".encode(),
                b"Authorization: Bearer abc.def\n",
                b"built 12 elements\n",
            ]
        },
        "publish": {"lines": [b"wrote package\n"]},
    }
    r = await _start(client, h, pid, version)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    await _settle(fake)
    j = await _job(client, h, job_id)
    assert j["status"] == "done" and j["progress"] == 1 and j["error"] is None and j["revision_id"], j
    text = "\n".join(j["log_tail"])
    assert SECRET not in text and "abc.def" not in text and "<hidden>" in text and "built 12 elements" in text
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"]
    assert [(x["status"], x["revision_id"]) for x in revs] == [("shared", j["revision_id"])]
    assert await _lock_holder(client, h, pid) is None  # lock freed
    gen, pub = fake.procs[0].argv, fake.procs[1].argv
    assert gen[1] == "gen" and "--brief" in gen and "--parent" not in pub and str(pid) in pub
    assert "--sheets" in pub and "--sheets" not in gen

    # Second run builds on the pending revision: --parent is a package rebuilt from storage.
    r2 = await _start(client, h, pid, version)
    assert r2.status_code == 202, r2.text
    await _settle(fake)
    j2 = await _job(client, h, r2.json()["job_id"])
    assert j2["status"] == "done", j2
    assert "--parent" in fake.procs[3].argv
    assert {"manifest.json", "model.ddc", "geometry.glb", "elements.parquet"} <= set(
        json.loads(fake.packages["parent_members"])
    )
    state = (await client.get(f"{BASE}/projects/{pid}/generation", headers=h)).json()
    assert state["enabled"] and state["job"]["job_id"] == r2.json()["job_id"]


async def test_failed_command_reports_and_frees_the_project(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    fake.project_id = str(pid)
    fake.scripts = {"gen": {"rc": 2, "lines": [b"brief value /massing/floors_above is not confirmed\n"]}}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _settle(fake)
    j = await _job(client, h, job_id)
    assert j["status"] == "failed" and "exit code 2" in j["error"] and "not confirmed" in j["error"]
    assert len(fake.procs) == 1  # publish never ran
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"] == []
    assert await _lock_holder(client, h, pid) is None
    fake.scripts = {}
    again = await _start(client, h, pid, version)
    assert again.status_code == 202  # slot freed


async def test_publish_without_package_and_rejected_package_fail_cleanly(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    fake.project_id = str(pid)
    fake.scripts = {"publish": {"write": False}}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _settle(fake)
    assert "without writing a package" in (await _job(client, h, job_id))["error"]
    fake.project_id = str(uuid.uuid4())  # a package for another project is refused by the normal intake
    fake.scripts = {}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _settle(fake)
    j = await _job(client, h, job_id)
    assert j["status"] == "failed" and "rejected" in j["error"]


async def test_timeout_kills_the_process(client, fake):
    from app.modules.design.settings import get_design_settings

    get_design_settings().job_timeout_seconds = 0.3
    uid, h, pid, version = await _project_with_brief(client)
    fake.scripts = {"gen": {"hang": True, "lines": [b"working\n"]}}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _settle(fake)
    j = await _job(client, h, job_id)
    assert j["status"] == "failed" and "in time" in j["error"] and "working" in j["log_tail"]
    assert fake.procs[0].terminated and fake.procs[0].returncode is not None
    assert await _lock_holder(client, h, pid) is None


async def test_cancel_running_stops_the_process(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    fake.scripts = {"gen": {"hang": True}}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _until(client, h, job_id, {"running"})
    assert (await _start(client, h, pid, version)).status_code == 409  # one job per project
    c = await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h)
    assert c.status_code == 200
    await _settle(fake)
    j = await _job(client, h, job_id)
    assert j["status"] == "cancelled" and "revision_id" not in j
    assert fake.procs[0].terminated and len(fake.procs) == 1
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"] == []
    assert await _lock_holder(client, h, pid) is None


async def test_cancel_escalates_to_kill(client, fake, monkeypatch):
    from app.modules.design import jobs

    monkeypatch.setattr(jobs, "KILL_GRACE_S", 0.1)
    uid, h, pid, version = await _project_with_brief(client)
    fake.scripts = {"gen": {"hang": True, "ignore_terminate": True}}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _until(client, h, job_id, {"running"})
    await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h)
    await _settle(fake)
    assert fake.procs[0].terminated and fake.procs[0].killed
    assert (await _job(client, h, job_id))["status"] == "cancelled"


async def test_cancel_queued_is_immediate_and_the_worker_then_skips_it(client, fake):
    from app.modules.design import jobs

    fake.hold_queue = True
    uid, h, pid, version = await _project_with_brief(client)
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    assert (await _job(client, h, job_id))["status"] == "queued"
    assert (await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h)).json()["status"] == "cancelled"
    await jobs.run_job(uuid.UUID(job_id))
    assert fake.procs == [] and (await _job(client, h, job_id))["status"] == "cancelled"
    assert await _lock_holder(client, h, pid) is None


# ── lock, rights, restart ───────────────────────────────────────────────────


async def test_editor_holding_the_lock_blocks_the_start_and_job_holds_it_while_running(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    tok_code = await client.post(
        f"{BASE}/link/code", json={"project_id": str(pid), "action": "new"}, headers={**h, **LINK}
    )
    tok = (await client.post(f"{BASE}/link/exchange", json={"code": tok_code.json()["code"]}, headers=LINK)).json()
    lh = {"Authorization": f"Bearer {tok['token']}", **LINK}
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=lh)).status_code == 200
    r = await _start(client, h, pid, version)  # even the same person's editor
    assert r.status_code == 409 and "being edited" in r.text
    assert (await client.delete(f"{BASE}/projects/{pid}/lock", headers=h)).status_code == 204
    fake.scripts = {"gen": {"hang": True}}
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    await _until(client, h, job_id, {"running"})
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=lh)).status_code == 409  # editor locked out
    await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h)
    await _settle(fake)


async def test_foreign_job_looks_missing_and_only_manager_or_starter_cancels(client, fake):
    uid, h, pid, version = await _project_with_brief(client)
    fake.hold_queue = True
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    other, h_other = await make_user(client)
    assert (await client.get(f"{BASE}/jobs/{job_id}", headers=h_other)).status_code in (403, 404)
    assert (await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h_other)).status_code in (403, 404)
    assert (await client.get(f"{BASE}/jobs/{uuid.uuid4()}", headers=h)).status_code == 404
    await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h)


async def test_job_lost_in_a_restart_fails_and_frees_the_project(client, fake):
    from datetime import timedelta

    from app.database import async_session_factory
    from app.modules.design.auth import now_utc
    from app.modules.design.models import DesignJob

    uid, h, pid, version = await _project_with_brief(client)
    fake.hold_queue = True
    job_id = (await _start(client, h, pid, version)).json()["job_id"]
    # The ERP died with the job running: nobody writes heartbeats any more.
    async with async_session_factory() as s:
        job = await s.get(DesignJob, uuid.UUID(job_id))
        job.status, job.heartbeat_at = "running", now_utc() - timedelta(minutes=5)
        await s.commit()
    j = await _job(client, h, job_id)
    assert j["status"] == "failed" and "worker was lost" in j["error"]
    assert await _lock_holder(client, h, pid) is None
    fake.hold_queue = False
    assert (await _start(client, h, pid, version)).status_code == 202
    await _settle(fake)


async def test_handler_is_registered_on_the_job_queue(client):
    from app.core import job_runner
    from app.modules.design import jobs

    assert job_runner.get_handler(jobs.KIND) is not None


# ── MCP ─────────────────────────────────────────────────────────────────────


async def test_mcp_proposal_starts_nothing_until_a_person_applies(client, app_instance, fake):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.design.models import DesignJob

    uid, h, pid, version = await _project_with_brief(client)
    fake.project_id = str(pid)
    token = await _mcp_token(uid)
    res = await _call(
        client,
        token,
        "propose_design_generation",
        project_id=str(pid),
        brief_version=version,
        confidence=0.9,
        rationale="Brief is confirmed.",
    )
    assert not res["isError"], res
    async with async_session_factory() as s:
        assert (await s.execute(select(DesignJob).where(DesignJob.project_id == pid))).first() is None
    state = await _call(client, token, "design_get_job", project_id=str(pid))
    assert state["structuredContent"]["enabled"] is True and state["structuredContent"]["job"] is None
    r = await client.post(_apply_path(app_instance, res["structuredContent"]["action_id"]), headers=h)
    assert r.status_code == 200 and r.json()["status"] == "applied", r.text
    await _settle(fake)
    job = (await _call(client, token, "design_get_job", project_id=str(pid)))["structuredContent"]["job"]
    assert job["status"] == "done" and job["revision_id"]
    stale = await _call(
        client,
        token,
        "propose_design_generation",
        project_id=str(pid),
        brief_version=version + 3,
        confidence=0.9,
        rationale="x",
    )
    assert stale["isError"]


async def test_mcp_proposal_refused_when_disabled(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h, pid, version = await _project_with_brief(client)
    monkeypatch.delenv("OE_DESIGN_DDC_CLI", raising=False)
    get_design_settings.cache_clear()
    token = await _mcp_token(uid)
    res = await _call(
        client,
        token,
        "propose_design_generation",
        project_id=str(pid),
        brief_version=version,
        confidence=0.9,
        rationale="x",
    )
    assert res["isError"] and "OE_DESIGN_DDC_CLI" in json.dumps(res)
    get_design_settings.cache_clear()


# ── the real binary ─────────────────────────────────────────────────────────


async def test_real_ddc_generates_a_revision_and_a_second_one_on_top(client, monkeypatch):
    if not REAL_CLI.is_file():
        pytest.skip(f"real ddc binary not found: {REAL_CLI}")
    from app.modules.design import revisions as rv
    from app.modules.design.settings import get_design_settings

    # Bulk import of a full-size model opens hundreds of database connections at once, which overflows the
    # test harness's selector loop (512 descriptors). The package, its files and the revision row are still
    # real; the BIM-hub import of real packages is covered by tools/e2e.
    async def _no_bim(*_a, **_kw):
        return uuid.uuid4()

    async def _no_artifacts(*_a, **_kw):
        return None

    monkeypatch.setattr(rv, "register_bim_model", _no_bim)
    monkeypatch.setattr(rv, "ensure_model_artifacts", _no_artifacts)
    monkeypatch.setenv("OE_DESIGN_DDC_CLI", str(REAL_CLI))
    get_design_settings.cache_clear()
    get_design_settings().job_timeout_seconds = 600
    example = json.loads(
        (Path(__file__).resolve().parent / "contract" / "examples" / "brief.de-residential.json").read_text("utf-8")
    )
    uid, h = await make_user(client)
    pid = await make_project(uid)
    url = f"{BASE}/projects/{pid}/brief"
    example["project_id"] = str(pid)
    for entry in (example.get("provenance") or {}).values():
        entry["status"] = "proposed"
        entry.pop("confirmed_by", None)
        entry.pop("confirmed_at", None)
    saved = await client.put(url, json=example, headers=h)
    assert saved.status_code == 200, saved.text
    doc = saved.json()
    doc = (
        await client.post(
            f"{url}/confirm",
            json={"pointers": list(doc["provenance"])},
            headers={**h, "If-Match": f'"{doc["version"]}"'},
        )
    ).json()
    ids = []
    for _ in range(2):
        r = await _start(client, h, pid, doc["version"])
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        try:  # slow polling: every request opens database connections
            j = await _until(client, h, job_id, {"done", "failed", "cancelled"}, seconds=420, every=1.0)
        finally:  # never leave a child process behind
            await client.post(f"{BASE}/jobs/{job_id}/cancel", headers=h)
        assert j["status"] == "done", j
        ids.append(j["revision_id"])
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"]
    assert {x["revision_id"] for x in revs} == set(ids)
    second = next(x for x in revs if x["revision_id"] == ids[1])
    assert second["parent_revision_id"] == ids[0] and second["source_kind"] == "generated"
    assert second["brief_version"] == doc["version"]
    get_design_settings.cache_clear()


async def test_job_on_an_imported_tip_builds_on_the_last_design(client, fake):
    """An import has no element table: a job bases on the newest design, or on nothing over a published import."""
    from .test_imported_revisions import _converter_model

    uid, h, pid, version = await _project_with_brief(client)
    fake.project_id = str(pid)

    async def run() -> dict:
        r = await _start(client, h, pid, version)
        assert r.status_code == 202, r.text
        await _settle(fake)
        j = await _job(client, h, r.json()["job_id"])
        assert j["status"] == "done", j
        return (await client.get(f"{BASE}/revisions/{j['revision_id']}", headers=h)).json()

    async def accept(rid) -> int:
        return (await client.post(f"{BASE}/revisions/{rid}/accept", headers=h)).status_code

    r1 = await run()
    assert await accept(r1["revision_id"]) == 200
    mid = await _converter_model(pid)
    imp = await client.post(f"{BASE}/projects/{pid}/revisions/import", json={"bim_model_id": str(mid)}, headers=h)
    assert imp.status_code == 201, imp.text
    imp = imp.json()
    assert imp["parent_revision_id"] == r1["revision_id"]

    # the import waits on top: the job diffs against the accepted design, not the file-less record
    r3 = await run()
    assert r3["parent_revision_id"] == r1["revision_id"] and r3["number"] == 3
    assert "--parent" in fake.procs[-1].argv and fake.packages["parent_id"] == r1["revision_id"].encode()

    # once the import is accepted, r3 is stale and the next job starts a new line without a parent
    assert await accept(imp["revision_id"]) == 200
    assert await accept(r3["revision_id"]) == 409
    r4 = await run()
    assert "--parent" not in fake.procs[-1].argv
    assert r4["parent_revision_id"] is None and r4["number"] == 4
    assert await accept(r4["revision_id"]) == 200
    revs = {
        x["number"]: x["status"]
        for x in (await client.get(f"{BASE}/projects/{pid}/revisions", headers=h)).json()["items"]
    }
    assert revs == {1: "archived", 2: "archived", 3: "shared", 4: "published"}
