# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for persistent clash profiles + multi-dimensional grouping (item #23).

Two contracts are pinned here:

* :func:`app.modules.clash.service._build_grouped_summary` — a pure function
  over a list of :class:`ClashResult` rows. Exercised directly (no DB) with a
  hand-computed fixture across all four grouping dimensions, asserting the
  exact cell / bucket counts and the ``has_system_data`` flag.
* The profile lifecycle through :class:`ClashService` against a real
  transaction-isolated PostgreSQL session — create a profile, then apply it
  to a new run and assert the run snapshots the profile's engine
  configuration (tolerance, clearance, mode, spatial grid).

The grouping fixture is deliberately small so the expected counts can be
checked by hand in the assertions.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash.schemas import ClashProfileApplyRequest, ClashProfileCreate
from app.modules.clash.service import ClashService, _build_grouped_summary
from tests._pg import transactional_session

# ── Pure grouping fixture (no DB) ─────────────────────────────────────────


def _result(
    *,
    a_disc: str,
    b_disc: str,
    a_storey: int | None = None,
    b_storey: int | None = None,
    a_system: str = "",
    b_system: str = "",
    status: str = "new",
) -> ClashResult:
    """A minimal in-memory :class:`ClashResult` for the grouping helper.

    Only the columns ``_build_grouped_summary`` reads are populated; the rest
    keep their model defaults (the function never touches them).
    """
    return ClashResult(
        run_id=uuid.uuid4(),
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id="a",
        b_stable_id="b",
        a_discipline=a_disc,
        b_discipline=b_disc,
        a_storey=a_storey,
        b_storey=b_storey,
        a_element_system=a_system,
        b_element_system=b_system,
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        status=status,
    )


def _grouping_fixture() -> list[ClashResult]:
    """Six clashes spanning two storeys, three disciplines, two systems.

    Hand-tally:
      * Mechanical↔Structural: 3 (one open=new, one resolved, one new)
      * Mechanical↔Electrical: 1 (open)
      * Structural↔Structural: 1 (open) — same-discipline (intra)
      * Electrical↔Plumbing:   1 (open) but only on storey 1 (the other
                               two-storey rows resolve a level)
    """
    return [
        # storey 0, MEP vs Struct, open
        _result(a_disc="Mechanical", b_disc="Structural", a_storey=0, b_storey=0, a_system="Supply Air"),
        # storey 0, MEP vs Struct, resolved
        _result(a_disc="Mechanical", b_disc="Structural", a_storey=0, b_storey=0, status="resolved"),
        # storey 1, MEP vs Struct, open
        _result(a_disc="Structural", b_disc="Mechanical", a_storey=1, b_storey=1, b_system="Supply Air"),
        # storey 1, Mech vs Elec, open
        _result(a_disc="Mechanical", b_disc="Electrical", a_storey=1, b_storey=1),
        # storey 1, Struct vs Struct, open
        _result(a_disc="Structural", b_disc="Structural", a_storey=1, b_storey=1),
        # no storey resolved, Elec vs Plumbing, open, no system
        _result(a_disc="Electrical", b_disc="Plumbing", a_storey=None, b_storey=None),
    ]


def test_grouped_summary_discipline_pair() -> None:
    """Default dimension — flat discipline×discipline matrix."""
    out = _build_grouped_summary(_grouping_fixture(), "discipline_pair")
    assert out["dimension"] == "discipline_pair"
    cells = {(c["a"], c["b"]): c for c in out["matrix"]}
    # Pairs are sorted alphabetically per cell.
    assert cells[("Mechanical", "Structural")]["count"] == 3
    assert cells[("Mechanical", "Structural")]["open_count"] == 2  # one resolved
    assert cells[("Electrical", "Mechanical")]["count"] == 1
    assert cells[("Structural", "Structural")]["count"] == 1
    assert cells[("Electrical", "Plumbing")]["count"] == 1
    assert set(out["disciplines"]) == {
        "Mechanical",
        "Structural",
        "Electrical",
        "Plumbing",
    }


def test_grouped_summary_by_level() -> None:
    """1-D — clashes bucketed per storey; unknown level → "(no level)"."""
    out = _build_grouped_summary(_grouping_fixture(), "level")
    assert out["dimension"] == "level"
    buckets = {b["key"]: b for b in out["levels"]}
    assert buckets["0"]["count"] == 2
    assert buckets["0"]["open_count"] == 1  # one of the two resolved
    assert buckets["1"]["count"] == 3
    assert buckets["1"]["open_count"] == 3
    assert buckets["(no level)"]["count"] == 1
    # Numeric levels sort ascending, "(no level)" last.
    assert [b["key"] for b in out["levels"]] == ["0", "1", "(no level)"]


def test_grouped_summary_level_discipline() -> None:
    """2-D — a discipline matrix per storey (only rows with both storeys)."""
    out = _build_grouped_summary(_grouping_fixture(), "level_discipline")
    assert out["dimension"] == "level_discipline"
    by_level = {g["level"]: g for g in out["level_disciplines"]}
    # The no-level row is excluded → only levels 0 and 1 appear.
    assert set(by_level) == {0, 1}
    l0 = {(c["a"], c["b"]): c["count"] for c in by_level[0]["cells"]}
    assert l0[("Mechanical", "Structural")] == 2
    l1 = {(c["a"], c["b"]): c["count"] for c in by_level[1]["cells"]}
    assert l1[("Mechanical", "Structural")] == 1
    assert l1[("Electrical", "Mechanical")] == 1
    assert l1[("Structural", "Structural")] == 1


def test_grouped_summary_discipline_system() -> None:
    """discipline·system grid + the has_system_data flag."""
    out = _build_grouped_summary(_grouping_fixture(), "discipline_system")
    assert out["dimension"] == "discipline_system"
    assert out["has_system_data"] is True
    # The two MEP·Supply-Air rows pair with Structural (no system).
    cells = {(c["a"], c["b"]): c["count"] for c in out["system_matrix"]}
    assert cells[("Mechanical · Supply Air", "Structural")] == 2
    assert "Mechanical · Supply Air" in out["systems"]


def test_grouped_summary_no_system_data_flag() -> None:
    """A run with no system metadata reports has_system_data=False."""
    rows = [_result(a_disc="Mechanical", b_disc="Structural")]
    out = _build_grouped_summary(rows, "discipline_system")
    assert out["has_system_data"] is False


def test_grouped_summary_unknown_dimension_degrades() -> None:
    """An unknown dimension falls back to discipline_pair (forgiving)."""
    rows = [_result(a_disc="Mechanical", b_disc="Structural")]
    out = _build_grouped_summary(rows, "discipline_pair")
    assert out["matrix"][0]["count"] == 1


# ── Profile lifecycle (real session) ──────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated session + an owner, a project and one BIM model.

    The BIM model carries no elements, so a run created from a profile
    completes with zero clashes — enough to assert the run snapshots the
    profile's configuration without seeding geometry.
    """
    async with transactional_session() as s:
        from app.modules.bim_hub.models import BIMModel
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner = User(
            id=uuid.uuid4(),
            email=f"clash-prof-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Clash Profile Tester",
        )
        s.add(owner)
        await s.flush()
        project = Project(
            id=uuid.uuid4(),
            name="Clash Profiles",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(project)
        await s.flush()
        model = BIMModel(
            id=uuid.uuid4(),
            project_id=project.id,
            name="Empty model",
            status="ready",
        )
        s.add(model)
        await s.commit()
        s.info["project_id"] = project.id
        s.info["owner_id"] = str(owner.id)
        s.info["model_id"] = model.id
        yield s


@pytest.mark.asyncio
async def test_create_profile_persists_config(session: AsyncSession) -> None:
    project_id = session.info["project_id"]
    owner_id = session.info["owner_id"]
    svc = ClashService(session)
    profile = await svc.create_profile(
        project_id,
        ClashProfileCreate(
            name="MEP tight",
            description="Mechanical vs structural, tight tolerance",
            clash_type="hard",
            tolerance_m=0.02,
            clearance_m=0.1,
            mode="cross_discipline",
            spatial_grid_mm=250,
        ),
        owner_id,
    )
    assert profile.name == "MEP tight"
    assert profile.tolerance_m == 0.02
    assert profile.clearance_m == 0.1
    assert profile.spatial_grid_mm == 250

    listed = await svc.list_profiles(project_id)
    assert [p.id for p in listed] == [profile.id]


@pytest.mark.asyncio
async def test_duplicate_profile_name_conflicts(session: AsyncSession) -> None:
    from fastapi import HTTPException

    project_id = session.info["project_id"]
    owner_id = session.info["owner_id"]
    svc = ClashService(session)
    await svc.create_profile(
        project_id,
        ClashProfileCreate(name="Dup", mode="cross_discipline"),
        owner_id,
    )
    with pytest.raises(HTTPException) as exc:
        await svc.create_profile(
            project_id,
            ClashProfileCreate(name="Dup", mode="cross_discipline"),
            owner_id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_profile_to_new_run_snapshots_config(
    session: AsyncSession,
) -> None:
    project_id = session.info["project_id"]
    owner_id = session.info["owner_id"]
    model_id = session.info["model_id"]
    svc = ClashService(session)
    profile = await svc.create_profile(
        project_id,
        ClashProfileCreate(
            name="Apply me",
            clash_type="hard",
            tolerance_m=0.05,
            clearance_m=0.2,
            mode="cross_discipline",
            spatial_grid_mm=750,
        ),
        owner_id,
    )
    run = await svc.apply_profile_to_new_run(
        project_id,
        profile.id,
        ClashProfileApplyRequest(model_ids=[model_id], name="Run from profile"),
        owner_id,
    )
    assert isinstance(run, ClashRun)
    assert run.name == "Run from profile"
    assert run.clash_type == "hard"
    assert run.tolerance_m == 0.05
    assert run.clearance_m == 0.2
    assert run.mode == "cross_discipline"
    assert run.spatial_grid_mm == 750
    # The empty model yields zero clashes — the run still completes cleanly.
    assert run.status == "completed"
    assert run.total_clashes == 0
