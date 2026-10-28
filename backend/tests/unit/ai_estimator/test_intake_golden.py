# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Golden-fixture composition tests for the intake v2 element-group composer.

Twelve fixtures (RU / EN / DE x kitchen / bathroom / full apartment / new
house) under ``tests/fixtures/ai_estimator_intake/`` drive the REAL composer
through a function-scoped, transaction-isolated PostgreSQL session, fully
OFFLINE (no AI key, and the grounded ranker stubbed to return no candidates so
the suite is hermetic and does not need Qdrant). Each fixture asserts the
deterministic, design-locked properties of the composer:

    * the raw request detects the expected project type offline;
    * the curated round answers reach the parameter sheet within the 3-round
      cap and produce the expected confirmed sheet;
    * the composer persists exactly the expected default-on work packages, never
      silently dropping one (a no-vectors probe is an honest gap, still created);
    * the composed groups read in foreman build-stage order
      (demo -> structure -> rough -> close -> finish -> commission), the
      sort_order monotonic within the expected stage sequence;
    * the per-package quantities match the pure-formula expectations exactly for
      confirmed values (the offline path uses the same formulas as the AI path);
    * the stage-dependency DAG surfaces an advisory warning when a successor
      package is selected without its prerequisite, and stays silent when the
      foreman sequence is satisfied.

The live-Qdrant recall metrics are a SEPARATE, skippable harness
(``test_intake_recall.py``); this file is the deterministic floor that always
runs in CI.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_intake_golden.py -q
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.intake import MAX_CLARIFY_ROUNDS, IntakeService
from app.modules.ai_estimator.models import AiEstimatorIntake, AiEstimatorRun
from app.modules.ai_estimator.project_types import (
    FOREMAN_STAGES,
    detect_project_type,
    get_project_type,
)
from app.modules.ai_estimator.quantities import compute_quantity
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorIntakeRepository,
    AiEstimatorRunRepository,
)
from tests._pg import transactional_session

# ``asyncio_mode = "auto"`` (pyproject) runs ``async def`` tests as asyncio
# without an explicit mark, so the module carries no ``pytestmark`` - that keeps
# the one synchronous detection test below from being (wrongly) marked asyncio.

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ai_estimator_intake"


def _load_fixtures() -> list[dict[str, Any]]:
    """Load every golden fixture JSON (sorted for stable parametrisation ids)."""
    return [json.loads(fp.read_text(encoding="utf-8")) for fp in sorted(_FIXTURE_DIR.glob("*.json"))]


_FIXTURES = _load_fixtures()
_FIXTURE_IDS = [f["name"] for f in _FIXTURES]


# ── Fixtures (function-scoped, transaction-isolated) ─────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A throwaway session; FK triggers off so we can insert a bare project."""
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project

    proj = Project(name="Intake golden test", owner_id=uuid.uuid4(), currency="EUR", region="DE_BERLIN")
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.fixture(autouse=True)
def _stub_rank_gap(monkeypatch):
    """Stub the grounded ranker to return no candidates (the no-vectors path).

    Keeps the golden composition suite hermetic: composition, stage ordering and
    quantities are deterministic and independent of whether Qdrant is up. The
    coverage band is then always ``gap`` (honest disclosure), which the suite
    relies on to prove no package is silently dropped.
    """
    from app.core.match_service.envelope import MatchResponse

    async def _empty_rank(req, *, db, ai_settings=None, caller_id=None):
        return MatchResponse(request=req, candidates=[], status="ok")

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _empty_rank)


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _compose_fixture(
    session: AsyncSession, project_id: uuid.UUID, fixture: dict[str, Any]
) -> tuple[AiEstimatorRun, AiEstimatorIntake]:
    """Drive a fixture: start -> answer round 1 -> confirm parameters -> board."""
    service = IntakeService(session)
    spec = schemas.IntakeCreate(project_id=project_id, text=fixture["raw_request"], mode_hint="offline")
    run, intake = await service.start(spec, uuid.uuid4())

    # Record the scripted answers and advance toward the parameter sheet (the
    # round cap is asserted separately; here we just need the sheet populated).
    for _ in range(MAX_CLARIFY_ROUNDS + 1):
        run = await AiEstimatorRunRepository(session).get_by_id(run.id)
        intake = await AiEstimatorIntakeRepository(session).get_for_run(run.id)
        assert run is not None and intake is not None
        if intake.phase == "parameter_sheet":
            break
        intake = await service.answer(
            run, intake, schemas.IntakeAnswerRequest(answers=dict(fixture["answers"]), advance=True)
        )

    run = await AiEstimatorRunRepository(session).get_by_id(run.id)
    intake = await AiEstimatorIntakeRepository(session).get_for_run(run.id)
    assert run is not None and intake is not None

    # Confirm the parameter sheet -> compose the board.
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params=dict(fixture["answers"]))
    )
    run = await AiEstimatorRunRepository(session).get_by_id(run.id)
    assert run is not None
    return run, intake


# ── Offline detection (10.2) ─────────────────────────────────────────────────


def test_every_fixture_detects_its_expected_type_offline():
    """Each fixture's raw request detects the expected project type offline.

    A single (non-async) test over all fixtures keeps it out of the module-level
    asyncio mark while still pinning section 10.2's detection requirement.
    """
    for fixture in _FIXTURES:
        detected, _count = detect_project_type(fixture["raw_request"])
        assert detected == fixture["expected_type"], f"{fixture['name']} detected {detected}"


# ── Round cap (10.2) ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_fixture_reaches_sheet_within_round_cap(session, project_id, fixture):
    """No fixture ever opens a fourth clarification round."""
    service = IntakeService(session)
    spec = schemas.IntakeCreate(project_id=project_id, text=fixture["raw_request"], mode_hint="offline")
    run, intake = await service.start(spec, uuid.uuid4())
    for _ in range(MAX_CLARIFY_ROUNDS + 2):
        run = await AiEstimatorRunRepository(session).get_by_id(run.id)
        intake = await AiEstimatorIntakeRepository(session).get_for_run(run.id)
        assert run is not None and intake is not None
        assert intake.round_idx <= MAX_CLARIFY_ROUNDS
        if intake.phase == "parameter_sheet":
            break
        intake = await service.answer(
            run, intake, schemas.IntakeAnswerRequest(answers=dict(fixture["answers"]), advance=True)
        )
    intake = await AiEstimatorIntakeRepository(session).get_for_run(run.id)
    assert intake is not None
    assert intake.phase == "parameter_sheet"
    assert intake.round_idx <= MAX_CLARIFY_ROUNDS


# ── Package composition (10.2) ───────────────────────────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_fixture_composes_expected_default_packages(session, project_id, fixture):
    """The composer persists exactly the curated default-on package set."""
    _run, intake = await _compose_fixture(session, project_id, fixture)
    assert intake.phase == "group_board"
    composed = {p["package_key"] for p in intake.packages}
    expected = set(fixture["expected_selected_packages"])
    assert composed == expected, f"{fixture['name']} composed {sorted(composed)} != {sorted(expected)}"


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_fixture_never_silently_drops_a_package(session, project_id, fixture):
    """Every default package becomes a board entry AND at least one group.

    With the ranker stubbed to no candidates every package is an honest gap, but
    a gap is still created (the design's no-silent-drop invariant).
    """
    run, intake = await _compose_fixture(session, project_id, fixture)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert groups, "composed groups must be persisted"
    # Each expected package owns at least one persisted group.
    persisted_keys = {(g.metadata_ or {}).get("package_key") for g in groups}
    for key in fixture["expected_selected_packages"]:
        assert key in persisted_keys, f"{fixture['name']} dropped package {key}"
    # Coverage is honest (no vectors -> gap), never a fabricated placeholder.
    assert all(p["coverage"] == "gap" for p in intake.packages)
    assert all(p["best_score"] is None for p in intake.packages)


# ── Stage ordering (the foreman sequence, section 4) ─────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_fixture_groups_read_in_foreman_stage_order(session, project_id, fixture):
    """Persisted groups are sorted in the universal build sequence."""
    run, _intake = await _compose_fixture(session, project_id, fixture)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    # list_for_run orders by sort_order; the stage of each group must be
    # non-decreasing in the foreman sequence.
    stage_indices = [FOREMAN_STAGES.index((g.metadata_ or {})["foreman_stage"]) for g in groups]
    assert stage_indices == sorted(stage_indices), f"{fixture['name']} groups out of build order"

    # The distinct stages present, in order, match the fixture's expectation.
    seen: list[str] = []
    for g in groups:
        st = (g.metadata_ or {})["foreman_stage"]
        if st not in seen:
            seen.append(st)
    assert seen == fixture["expected_stage_order"], f"{fixture['name']} stage order {seen}"


# ── Quantities (10.2, exact for confirmed values) ────────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_fixture_quantities_match_pure_formulas(session, project_id, fixture):
    """The board quantity per package matches the pure formula on the sheet."""
    _run, intake = await _compose_fixture(session, project_id, fixture)
    pt = get_project_type(fixture["expected_type"])
    assert pt is not None
    by_key = {p["package_key"]: p for p in intake.packages}
    for key, expected_qty in fixture["expected_quantities"].items():
        pkg = next(pkg for pkg in pt.packages if pkg.key == key)
        formula_qty = compute_quantity(pkg.qty_formula, dict(intake.params), pkg.unit).quantity
        # The board echoes the formula result.
        assert by_key[key]["quantity"] == pytest.approx(formula_qty), f"{fixture['name']}.{key} board vs formula"
        # And both match the curated golden expectation.
        assert formula_qty == pytest.approx(expected_qty, rel=1e-3), f"{fixture['name']}.{key} != {expected_qty}"


# ── Stage-dependency DAG (section 4.2) ───────────────────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_dependency_warnings_are_advisory_dicts(session, project_id, fixture):
    """Whatever warnings the default board raises are well-formed advisories."""
    run, intake = await _compose_fixture(session, project_id, fixture)
    service = IntakeService(session)
    state = await service.to_state(run, intake)
    for w in state.dependency_warnings:
        assert set(w) >= {"code", "successor", "prerequisite", "successor_stage", "prerequisite_stage"}
        assert w["code"] == "aiest.dep.missing_prereq"
        # A warning never names a package the type does not offer.
        offered = {pkg.key for pkg in get_project_type(fixture["expected_type"]).packages}
        assert w["successor"] in offered
        assert w["prerequisite"] in offered


async def test_dependency_warning_fires_when_prereq_deselected(session, project_id):
    """Toggling plaster off leaves tiling without its substrate -> a warning."""
    fixture = next(f for f in _FIXTURES if f["name"] == "ru_bathroom")
    run, intake = await _compose_fixture(session, project_id, fixture)
    service = IntakeService(session)

    # Bathroom defaults carry both wall_plaster and wall_tiling; with both on,
    # the plaster->tiling sequence is satisfied (no plaster-substrate warning).
    before = await service.to_state(run, intake)
    assert not any(
        w["successor"] == "wall_tiling" and w["prerequisite"] == "wall_plaster" for w in before.dependency_warnings
    )

    # Deselect the plaster: tiling now lacks its substrate.
    intake = await service.edit_packages(run, intake, schemas.IntakePackagesRequest(toggle={"wall_plaster": False}))
    after = await service.to_state(run, intake)
    assert any(
        w["successor"] == "wall_tiling" and w["prerequisite"] == "wall_plaster" for w in after.dependency_warnings
    ), "expected an advisory tiling-without-plaster warning after deselecting plaster"


# ── Offline / AI parity at the sheet level (10.2) ────────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_confirmed_sheet_matches_fixture(session, project_id, fixture):
    """The confirmed parameter sheet carries every expected (answered) value."""
    _run, intake = await _compose_fixture(session, project_id, fixture)
    for key, value in fixture["expected_params"].items():
        actual = intake.params.get(key)
        if isinstance(value, float):
            assert actual == pytest.approx(value), f"{fixture['name']}.{key}"
        else:
            assert actual == value, f"{fixture['name']}.{key}"
