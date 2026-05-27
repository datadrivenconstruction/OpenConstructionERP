"""Clash triage-delta tests: severity, signature, carry-forward, compare.

Two layers:

* **Pure** (no DB) — :func:`_severity_for` tier boundaries (hard +
  clearance) and :func:`_signature` determinism / order-independence /
  stability across two independent engine runs, driven through the same
  hand-built ``ElementGeom`` fakes the narrow-phase suite uses.
* **DB-backed** — a self-isolated SQLite (booted exactly like
  ``test_bcf_api.py``) exercising :meth:`ClashService.create_run`
  carry-forward (status / assignee / due_date / comments persist across
  a re-run, matched by signature) and :meth:`ClashService.compare_runs`
  (new / resolved / persistent partition).

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
fresh temp SQLite file BEFORE ``app`` is first imported.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-triage-"))
_TMP_DB = _TMP_DIR / "clash_triage.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.modules.clash.schemas import ClashRunCreate  # noqa: E402
from app.modules.clash.service import (  # noqa: E402
    ClashService,
    _severity_for,
    _signature,
)
from tests.unit.test_clash_narrow_phase import (  # noqa: E402
    _box_geom,
    _FakeRun,
    _run_detect,
)

# ── Pure: severity tiers ──────────────────────────────────────────────────


def test_severity_hard_tiers():
    """Hard-clash penetration tiers exactly on the documented boundaries."""
    assert _severity_for("hard", 0.10, 0.0, 0.0) == "critical"
    assert _severity_for("hard", 0.25, 0.0, 0.0) == "critical"
    assert _severity_for("hard", 0.099, 0.0, 0.0) == "high"
    assert _severity_for("hard", 0.03, 0.0, 0.0) == "high"
    assert _severity_for("hard", 0.029, 0.0, 0.0) == "medium"
    assert _severity_for("hard", 0.005, 0.0, 0.0) == "medium"
    assert _severity_for("hard", 0.0049, 0.0, 0.0) == "low"
    assert _severity_for("hard", 0.0, 0.0, 0.0) == "low"


def test_severity_clearance_tiers_never_critical():
    """Clearance keyed off gap/clearance ratio; never escalates to critical."""
    # clearance_m = 1.0 → ratio == distance.
    assert _severity_for("clearance", 0.0, 0.20, 1.0) == "high"  # 0.20 ≤ .25
    assert _severity_for("clearance", 0.0, 0.25, 1.0) == "high"
    assert _severity_for("clearance", 0.0, 0.40, 1.0) == "medium"  # ≤ .50
    assert _severity_for("clearance", 0.0, 0.50, 1.0) == "medium"
    assert _severity_for("clearance", 0.0, 0.80, 1.0) == "low"
    # No clearance value ever yields "critical".
    for g in (0.0, 0.1, 0.25, 0.5, 0.9, 1.0):
        assert _severity_for("clearance", 0.0, g, 1.0) != "critical"
    # Guard: clearance_m <= 0 degrades to "medium", never raises.
    assert _severity_for("clearance", 0.0, 0.3, 0.0) == "medium"


def test_severity_set_on_engine_rows():
    """The engine stamps a real severity (deep overlap → critical)."""
    a = _box_geom("A", (0, 0, 0), (1, 1, 1), "Structural")
    # 0.5 m overlap on X (well past the 0.10 m critical threshold).
    b = _box_geom("B", (0.5, 0, 0), (1, 1, 1), "Mechanical")
    res = _run_detect(_FakeRun(tolerance_m=0.01, mode="cross_discipline"), [a, b])
    assert len(res) == 1
    assert res[0].clash_type == "hard"
    assert res[0].severity == "critical"


# ── Pure: signature determinism & stability ───────────────────────────────


def test_signature_is_order_independent_and_deterministic():
    s1 = _signature("ELEM-A", "ELEM-B", "hard")
    s2 = _signature("ELEM-B", "ELEM-A", "hard")  # swapped order
    assert s1 == s2
    assert len(s1) == 16
    # Distinct clash_type → distinct signature for the same pair.
    assert _signature("ELEM-A", "ELEM-B", "clearance") != s1
    # Fully deterministic across calls.
    assert _signature("ELEM-A", "ELEM-B", "hard") == s1


def test_signature_stable_across_two_independent_runs():
    """Same physical pair → identical signature in two separate runs."""
    a = _box_geom("STBL-A", (0, 0, 0), (1, 1, 1), "Structural")
    b = _box_geom("STBL-B", (0.7, 0, 0), (1, 1, 1), "Mechanical")

    res1 = _run_detect(_FakeRun(tolerance_m=0.01, mode="cross_discipline"), [a, b])
    res2 = _run_detect(_FakeRun(tolerance_m=0.01, mode="cross_discipline"), [a, b])
    assert len(res1) == len(res2) == 1
    assert res1[0].signature == res2[0].signature
    assert res1[0].signature != ""


# ── DB-backed: carry-forward + compare ────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def db_session():
    """A real AsyncSession over a freshly create_all'd temp SQLite."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, async_session_factory, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_session_factory() as session:
            yield session


async def _seed_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal user + project + BIM model.

    Returns ``(project_id, model_id)``.
    """
    from app.modules.bim_hub.models import BIMModel
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"clash-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Clash Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Clash Triage Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    model = BIMModel(
        project_id=project.id,
        name="Triage Model",
        status="ready",
    )
    session.add(model)
    await session.flush()
    return project.id, model.id


def _patch_engine_geometry(monkeypatch, geoms_by_eid: dict):
    """Make ClashService._detect see hand-built geometry for our elements."""

    async def _fake_load(self, model_ids):  # noqa: ANN001, ARG001
        return dict(geoms_by_eid)

    monkeypatch.setattr(ClashService, "_load_geometry", _fake_load)


@pytest.mark.asyncio
async def test_carry_forward_persists_triage_by_signature(db_session, monkeypatch):
    """status / assignee / due_date / comments survive a re-run."""
    from app.modules.bim_hub.models import BIMElement

    project_id, model_id = await _seed_project(db_session)

    # Two overlapping elements (a real hard clash).
    ga = _box_geom("CF-A", (0, 0, 0), (1, 1, 1), "Structural")
    gb = _box_geom("CF-B", (0.6, 0, 0), (1, 1, 1), "Mechanical")
    elems = []
    geoms = {}
    for g in (ga, gb):
        el = BIMElement(
            model_id=model_id,
            stable_id=g.stable_id,
            name=g.name,
            element_type="Generic",
            discipline=g.discipline,
            bounding_box={
                "min_x": g.aabb[0],
                "min_y": g.aabb[1],
                "min_z": g.aabb[2],
                "max_x": g.aabb[3],
                "max_y": g.aabb[4],
                "max_z": g.aabb[5],
            },
        )
        db_session.add(el)
        elems.append((el, g))
    await db_session.flush()
    for el, g in elems:
        geoms[str(el.id)] = g
    _patch_engine_geometry(monkeypatch, geoms)

    svc = ClashService(db_session)
    create = ClashRunCreate(model_ids=[model_id], tolerance_m=0.01, mode="all")

    run1 = await svc.create_run(project_id, create, str(uuid.uuid4()))
    assert run1.status == "completed"
    rows1, _ = await svc.repo.list_results(run1.id, limit=100)
    assert len(rows1) == 1
    r1 = rows1[0]
    sig = r1.signature
    assert sig != ""

    # Triage it: assign, set status + due date + a comment.
    await svc.update_result(
        project_id,
        run1.id,
        r1.id,
        new_status="reviewed",
        assigned_to="Alice",
        due_date="2026-06-30",
        add_comment={"text": "Coordinate with MEP", "author": "Bob"},
    )

    # Re-run: a new run over the same model → triage must carry forward.
    run2 = await svc.create_run(project_id, create, str(uuid.uuid4()))
    assert run2.status == "completed"
    rows2, _ = await svc.repo.list_results(run2.id, limit=100)
    assert len(rows2) == 1
    r2 = rows2[0]
    assert r2.signature == sig  # stable identity
    assert r2.status == "reviewed"  # status carried
    assert r2.assigned_to == "Alice"  # assignee carried
    assert r2.due_date == "2026-06-30"  # due date carried
    assert [c["text"] for c in r2.comments] == ["Coordinate with MEP"]
    assert r2.comments[0]["author"] == "Bob"


@pytest.mark.asyncio
async def test_compare_partitions_new_resolved_persistent(db_session, monkeypatch):
    """compare_runs splits clashes into new / resolved / persistent."""
    from app.modules.bim_hub.models import BIMElement

    project_id, model_id = await _seed_project(db_session)

    def _mk(eid: str, origin) -> tuple:
        g = _box_geom(eid, origin, (1, 1, 1), "Structural")
        el = BIMElement(
            model_id=model_id,
            stable_id=g.stable_id,
            name=g.name,
            element_type="Generic",
            discipline="Structural",
            bounding_box={
                "min_x": g.aabb[0],
                "min_y": g.aabb[1],
                "min_z": g.aabb[2],
                "max_x": g.aabb[3],
                "max_y": g.aabb[4],
                "max_z": g.aabb[5],
            },
        )
        db_session.add(el)
        return el, g

    # Base run pair: P ∩ Q overlap.
    p_el, p_g = _mk("CMP-P", (0, 0, 0))
    q_el, q_g = _mk("CMP-Q", (0.6, 0, 0))
    # Extra element R that will only clash in the second run.
    r_el, r_g = _mk("CMP-R", (50, 0, 0))  # far away initially
    await db_session.flush()

    svc = ClashService(db_session)
    create = ClashRunCreate(
        model_ids=[model_id],
        tolerance_m=0.01,
        mode="all",
        carry_forward=False,
    )

    # Base run: only P∩Q clash (R is far away).
    _patch_engine_geometry(
        monkeypatch,
        {
            str(p_el.id): p_g,
            str(q_el.id): q_g,
            str(r_el.id): r_g,
        },
    )
    base = await svc.create_run(project_id, create, str(uuid.uuid4()))
    base_rows, _ = await svc.repo.list_results(base.id, limit=100)
    assert len(base_rows) == 1
    base_sig = base_rows[0].signature

    # Current run: move R onto Q so Q∩R now clashes and P moves away so
    # P∩Q resolves → exactly one NEW + one RESOLVED, zero persistent.
    p_g2 = _box_geom("CMP-P", (90, 0, 0), (1, 1, 1), "Structural")
    r_g2 = _box_geom("CMP-R", (0.6, 0, 0), (1, 1, 1), "Structural")
    _patch_engine_geometry(
        monkeypatch,
        {
            str(p_el.id): p_g2,
            str(q_el.id): q_g,
            str(r_el.id): r_g2,
        },
    )
    current = await svc.create_run(project_id, create, str(uuid.uuid4()))
    cur_rows, _ = await svc.repo.list_results(current.id, limit=100)
    assert len(cur_rows) == 1
    cur_sig = cur_rows[0].signature
    assert cur_sig != base_sig

    diff = await svc.compare_runs(project_id, current.id, base.id)
    assert diff["stats"]["new"] == 1
    assert diff["stats"]["resolved"] == 1
    assert diff["stats"]["persistent"] == 0
    assert diff["stats"]["base_total"] == 1
    assert diff["stats"]["current_total"] == 1
    assert diff["new"][0]["a_name"] or diff["new"][0]["b_name"]
    assert diff["resolved"][0]["status"] in ("new", "active", "reviewed", "approved", "resolved", "ignored")

    # Now a run identical to base → that clash is PERSISTENT (same sig).
    _patch_engine_geometry(
        monkeypatch,
        {str(p_el.id): p_g, str(q_el.id): q_g, str(r_el.id): r_g},
    )
    same = await svc.create_run(project_id, create, str(uuid.uuid4()))
    diff2 = await svc.compare_runs(project_id, same.id, base.id)
    assert diff2["stats"]["persistent"] == 1
    assert diff2["stats"]["new"] == 0
    assert diff2["stats"]["resolved"] == 0
    assert diff2["persistent"][0]["current"]["a_name"] == (diff2["persistent"][0]["base"]["a_name"])
