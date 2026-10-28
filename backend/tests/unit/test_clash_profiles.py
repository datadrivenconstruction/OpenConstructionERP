"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Clash profile + multi-dimensional grouping tests (item #23).

Two layers (same isolation discipline as ``test_clash_triage_delta.py``):

* **Pure** (no DB) — :func:`_build_grouped_summary` for every grouping
  dimension (discipline_pair / level / level_discipline /
  discipline_system) and :func:`_system_of` extraction, driven through
  tiny ``ClashResult`` stand-ins so no engine / geometry is needed.
* **DB-backed** — :class:`ClashService` profile lifecycle (create, dup
  name, update, delete) + ``apply_profile_to_new_run`` over the
  PostgreSQL engine provisioned by ``conftest.py``.
"""

from __future__ import annotations

import uuid

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app.modules.clash.schemas import (  # noqa: E402
    ClashProfileApplyRequest,
    ClashProfileCreate,
    ClashProfileUpdate,
)
from app.modules.clash.service import (  # noqa: E402
    ClashService,
    _build_grouped_summary,
    _system_of,
)

# ── Pure: _system_of extraction ───────────────────────────────────────────


class _Elem:
    """Minimal stand-in for a BIMElement carrying a ``properties`` dict."""

    def __init__(self, properties: object) -> None:
        self.properties = properties


def test_system_of_prefers_explicit_system_key():
    assert _system_of(_Elem({"system": "Supply Air"})) == "Supply Air"
    assert _system_of(_Elem({"System": "Chilled Water"})) == "Chilled Water"


def test_system_of_falls_back_to_family_then_empty():
    # No system key but a family → family is used.
    assert _system_of(_Elem({"family": "Round Duct"})) == "Round Duct"
    # No usable key at all → empty (grouping selector hides the dimension).
    assert _system_of(_Elem({"unrelated": "x"})) == ""
    assert _system_of(_Elem(None)) == ""
    assert _system_of(_Elem("not-a-dict")) == ""
    # Non-scalar value never used.
    assert _system_of(_Elem({"system": {"nested": 1}})) == ""


# ── Pure: _build_grouped_summary across every dimension ────────────────────


class _Row:
    """Tiny ClashResult stand-in for the grouping aggregator."""

    def __init__(
        self,
        a_disc: str,
        b_disc: str,
        *,
        status: str = "new",
        a_storey: int | None = None,
        b_storey: int | None = None,
        a_system: str = "",
        b_system: str = "",
    ) -> None:
        self.a_discipline = a_disc
        self.b_discipline = b_disc
        self.status = status
        self.a_storey = a_storey
        self.b_storey = b_storey
        self.a_element_system = a_system
        self.b_element_system = b_system


def test_grouped_summary_discipline_pair_default():
    rows = [
        _Row("Mechanical", "Structural", status="new"),
        _Row("Structural", "Mechanical", status="resolved"),  # same pair, reversed
        _Row("Architectural", "Mechanical", status="new"),
    ]
    out = _build_grouped_summary(rows, "discipline_pair")
    assert out["dimension"] == "discipline_pair"
    cells = {(c["a"], c["b"]): c for c in out["matrix"]}
    # Symmetric collapse: (Mechanical, Structural) carries both rows.
    ms = cells[("Mechanical", "Structural")]
    assert ms["count"] == 2
    assert ms["open_count"] == 1  # only the "new" one is open
    am = cells[("Architectural", "Mechanical")]
    assert am["count"] == 1 and am["open_count"] == 1
    assert "Mechanical" in out["disciplines"]


def test_grouped_summary_by_level_buckets_and_no_level():
    rows = [
        _Row("M", "S", a_storey=1, b_storey=1, status="new"),
        _Row("M", "S", a_storey=2, b_storey=3, status="resolved"),  # → level 2
        _Row("M", "S"),  # no storey → "(no level)"
    ]
    out = _build_grouped_summary(rows, "level")
    by_key = {b["key"]: b for b in out["levels"]}
    assert by_key["1"]["count"] == 1 and by_key["1"]["open_count"] == 1
    assert by_key["2"]["count"] == 1 and by_key["2"]["open_count"] == 0
    assert by_key["(no level)"]["count"] == 1
    # "(no level)" sorts last.
    assert out["levels"][-1]["key"] == "(no level)"


def test_grouped_summary_level_discipline_matrix_per_storey():
    rows = [
        _Row("M", "S", a_storey=1, b_storey=1, status="new"),
        _Row("A", "S", a_storey=1, b_storey=1, status="new"),
        _Row("M", "S", a_storey=2, b_storey=2, status="resolved"),
        _Row("M", "S"),  # unknown storey → excluded from level_discipline
    ]
    out = _build_grouped_summary(rows, "level_discipline")
    groups = {g["level"]: g for g in out["level_disciplines"]}
    assert set(groups) == {1, 2}
    lvl1_pairs = {(c["a"], c["b"]) for c in groups[1]["cells"]}
    assert ("M", "S") in lvl1_pairs
    assert ("A", "S") in lvl1_pairs


def test_grouped_summary_discipline_system():
    rows = [
        _Row("Mechanical", "Structural", a_system="Supply Air", b_system="Beams", status="new"),
        _Row("Mechanical", "Structural", a_system="Supply Air", b_system="Beams", status="resolved"),
    ]
    out = _build_grouped_summary(rows, "discipline_system")
    assert out["has_system_data"] is True
    cells = out["system_matrix"]
    assert len(cells) == 1
    c = cells[0]
    assert {c["a"], c["b"]} == {"Mechanical · Supply Air", "Structural · Beams"}
    assert c["count"] == 2 and c["open_count"] == 1


def test_grouped_summary_has_system_data_false_when_no_systems():
    rows = [_Row("M", "S")]
    out = _build_grouped_summary(rows, "discipline_system")
    assert out["has_system_data"] is False


# ── DB-backed: profile lifecycle + apply ──────────────────────────────────


@pytest_asyncio.fixture
async def db_session():
    """Function-scoped, transaction-isolated AsyncSession (see ``tests/_pg.py``).

    A module-scoped session reuses one asyncpg connection across the per-test
    event loops pytest-asyncio creates, which fails with "Future attached to a
    different loop". The shared transactional session is loop-correct and fast
    (the schema is materialised once per session, each test rolls back).
    """
    from tests._pg import transactional_session

    async with transactional_session() as session:
        yield session


async def _seed_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal user + project + BIM model → ``(project_id, model_id)``."""
    from app.modules.bim_hub.models import BIMModel
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"clash-prof-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Clash Profile Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Clash Profile Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    model = BIMModel(project_id=project.id, name="Profile Model", status="ready")
    session.add(model)
    await session.flush()
    return project.id, model.id


@pytest.mark.asyncio
async def test_create_profile_persists_config(db_session):
    project_id, _ = await _seed_project(db_session)
    svc = ClashService(db_session)
    data = ClashProfileCreate(
        name="MEP-Struct",
        description="MEP against structure",
        tolerance_m=0.02,
        clearance_m=0.1,
        mode="cross_discipline",
        spatial_grid_mm=750,
    )
    profile = await svc.create_profile(project_id, data, str(uuid.uuid4()))
    assert profile.name == "MEP-Struct"
    assert profile.tolerance_m == 0.02
    assert profile.clearance_m == 0.1
    assert profile.spatial_grid_mm == 750
    # Listed in the project library.
    listed = await svc.list_profiles(project_id)
    assert any(p.id == profile.id for p in listed)


@pytest.mark.asyncio
async def test_duplicate_name_rejected(db_session):
    project_id, _ = await _seed_project(db_session)
    svc = ClashService(db_session)
    await svc.create_profile(project_id, ClashProfileCreate(name="Dup"), str(uuid.uuid4()))
    with pytest.raises(HTTPException) as exc:
        await svc.create_profile(project_id, ClashProfileCreate(name="Dup"), str(uuid.uuid4()))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_update_profile_changes_fields(db_session):
    project_id, _ = await _seed_project(db_session)
    svc = ClashService(db_session)
    profile = await svc.create_profile(project_id, ClashProfileCreate(name="Tune", tolerance_m=0.01), str(uuid.uuid4()))
    updated = await svc.update_profile(
        project_id,
        profile.id,
        ClashProfileUpdate(tolerance_m=0.05, description="bumped"),
        str(uuid.uuid4()),
    )
    assert updated.tolerance_m == 0.05
    assert updated.description == "bumped"
    # Name untouched (not in the patch).
    assert updated.name == "Tune"


@pytest.mark.asyncio
async def test_delete_profile_removes_it(db_session):
    project_id, _ = await _seed_project(db_session)
    svc = ClashService(db_session)
    profile = await svc.create_profile(project_id, ClashProfileCreate(name="Trash"), str(uuid.uuid4()))
    await svc.delete_profile(project_id, profile.id)
    with pytest.raises(HTTPException) as exc:
        await svc.get_profile(project_id, profile.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_apply_profile_to_new_run_uses_config(db_session, monkeypatch):
    """A profile launches a run that snapshots its tolerance + grid."""
    project_id, model_id = await _seed_project(db_session)
    svc = ClashService(db_session)

    # No geometry — the run completes with zero clashes; we only assert
    # the run config was taken from the profile.
    async def _no_geom(self, model_ids):  # noqa: ANN001, ARG001
        return {}

    monkeypatch.setattr(ClashService, "_load_geometry", _no_geom)

    profile = await svc.create_profile(
        project_id,
        ClashProfileCreate(
            name="Apply Me",
            tolerance_m=0.05,
            clearance_m=0.1,
            mode="all",
            spatial_grid_mm=250,
        ),
        str(uuid.uuid4()),
    )
    run = await svc.apply_profile_to_new_run(
        project_id,
        profile.id,
        ClashProfileApplyRequest(model_ids=[model_id], name="Run from profile"),
        str(uuid.uuid4()),
    )
    assert run.status == "completed"
    assert run.name == "Run from profile"
    assert run.tolerance_m == 0.05
    assert run.clearance_m == 0.1
    assert run.mode == "all"
    assert run.spatial_grid_mm == 250
    assert [str(m) for m in run.model_ids] == [str(model_id)]


@pytest.mark.asyncio
async def test_grouped_summary_endpoint_path_idor_guarded(db_session):
    """grouped_summary 404s for a run that isn't in the project."""
    project_id, _ = await _seed_project(db_session)
    svc = ClashService(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.grouped_summary(project_id, uuid.uuid4(), "discipline_pair")
    assert exc.value.status_code == 404
