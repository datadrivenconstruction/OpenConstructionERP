# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Persistence-backed unit tests for the conversational intake (v2) FSM.

These drive the real :class:`IntakeService` against a function-scoped,
transaction-isolated PostgreSQL session (``tests._pg.transactional_session``,
never a module-scoped app fixture, per the Windows event-loop gotcha). They run
fully OFFLINE - no AI key, no Qdrant - so they pin the founder-locked
invariants of the dialogue machine:

    * Offline path: free text -> deterministic type detection -> curated
      questionnaire rounds -> confirmed parameter sheet -> composed group board.
    * Max 3 clarification rounds, enforced in the machine (a fourth advance
      always lands on the parameter sheet).
    * Confidence-driven round skipping: a fully-specified request reaches the
      sheet fast.
    * The composer persists one AiEstimatorGroup per (package x stage) cell,
      never silently drops a package, and surfaces honest coverage from the
      real probe score (grounded / weak / gap).
    * The finish bridge advances the run to ``grouping`` with the composed
      groups intact and the ``intake_composed`` flag set.

The grounded ranker (``rank``) is stubbed so the suite is hermetic; a probe
returning no candidates is the honest no-vectors path and exercises the gap
disclosure.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_intake_fsm.py -q
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.intake import MAX_CLARIFY_ROUNDS, IntakeService
from app.modules.ai_estimator.models import AiEstimatorIntake, AiEstimatorRun
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorIntakeRepository,
    AiEstimatorRunRepository,
)
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


# ── Fixtures (function-scoped, transaction-isolated) ─────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A throwaway session; FK triggers off so we can insert a bare project."""
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    """Insert a minimal project row (FKs disabled, so owner_id can be random)."""
    from app.modules.projects.models import Project

    proj = Project(name="Intake FSM test", owner_id=uuid.uuid4(), currency="EUR", region="DE_BERLIN")
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.fixture(autouse=True)
def _stub_rank_gap(monkeypatch):
    """Default stub: the ranker returns no candidates (the no-vectors path).

    A probe with no candidate is an honest gap; individual tests override this
    to return a grounded score where they assert green coverage.
    """
    from app.core.match_service.envelope import MatchResponse

    async def _empty_rank(req, *, db, ai_settings=None):
        return MatchResponse(request=req, candidates=[], status="ok")

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _empty_rank)


def _stub_rank_score(monkeypatch, score: float) -> None:
    """Make every probe return a single candidate at ``score`` (controls band)."""
    from app.core.match_service.envelope import MatchCandidate, MatchResponse

    async def _rank(req, *, db, ai_settings=None):
        return MatchResponse(
            request=req,
            candidates=[
                MatchCandidate(
                    code="RC1", description="probe hit", unit="m2", unit_rate=12.0, currency="EUR", score=score
                )
            ],
            status="ok",
        )

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _rank)


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _start(
    session: AsyncSession, project_id: uuid.UUID, text: str, **kw
) -> tuple[AiEstimatorRun, AiEstimatorIntake]:
    service = IntakeService(session)
    spec = schemas.IntakeCreate(project_id=project_id, text=text, mode_hint="offline", **kw)
    return await service.start(spec, uuid.uuid4())


async def _reload(session: AsyncSession, run_id: uuid.UUID) -> tuple[AiEstimatorRun, AiEstimatorIntake]:
    run = await AiEstimatorRunRepository(session).get_by_id(run_id)
    intake = await AiEstimatorIntakeRepository(session).get_for_run(run_id)
    assert run is not None and intake is not None
    return run, intake


# ── Start + extract (offline) ────────────────────────────────────────────────


async def test_start_offline_detects_type_and_opens_round_1(session, project_id):
    run, intake = await _start(session, project_id, "сделай мне смету кухни")
    assert run.status == "intake"
    assert intake.mode == "offline"
    assert intake.detected_type == "kitchen_reno"
    # Deterministic detection is honest: no fabricated confidence.
    assert intake.type_confidence is None
    assert intake.phase == "clarify_round_1"
    assert intake.round_idx == 1
    assert intake.questions, "round 1 should carry curated questions"
    # The offline questions are i18n keys, not hardcoded English prose.
    assert all(q["prompt"].startswith("aiest.q.") for q in intake.questions)
    assert all(q["why"].startswith("aiest.why.") for q in intake.questions)


async def test_start_seeds_explicit_quantity_from_text(session, project_id):
    """ "ремонт квартиры 120 м2" pre-fills floor_area_m2 from the free text."""
    _run, intake = await _start(session, project_id, "ремонт квартиры 120 м2")
    assert intake.detected_type == "apartment_reno"
    assert intake.params.get("floor_area_m2") == pytest.approx(120.0)
    # The seeded area question is not re-asked in round 1.
    assert "floor_area_m2" not in {q["param_key"] for q in intake.questions}


async def test_start_unknown_type_stays_at_extract(session, project_id):
    _run, intake = await _start(session, project_id, "please help me plan something")
    assert intake.detected_type is None
    assert intake.phase == "extract"
    assert intake.questions == []


async def test_manual_type_pick_overrides_detection(session, project_id):
    _run, intake = await _start(session, project_id, "no clear type here", project_type="roof")
    assert intake.detected_type == "roof"
    assert intake.phase == "clarify_round_1"


# ── Round advancement + the 3-round cap ──────────────────────────────────────


async def test_round_cap_never_exceeds_three(session, project_id):
    """A house build needs several rounds; the machine never opens a fourth."""
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "build a new house")
    assert intake.detected_type == "house_new"

    seen_rounds = set()
    for _ in range(6):  # more iterations than the cap, on purpose
        run, intake = await _reload(session, run.id)
        if intake.phase == "parameter_sheet":
            break
        assert intake.round_idx <= MAX_CLARIFY_ROUNDS
        seen_rounds.add(intake.round_idx)
        # Answer nothing substantive, but keep advancing to push the cap.
        intake = await service.answer(run, intake, schemas.IntakeAnswerRequest(answers={}, advance=True))

    run, intake = await _reload(session, run.id)
    assert intake.round_idx <= MAX_CLARIFY_ROUNDS
    assert intake.phase == "parameter_sheet"
    assert max(seen_rounds) <= MAX_CLARIFY_ROUNDS


async def test_fully_specified_request_reaches_sheet_in_one_round(session, project_id):
    """ "ремонт ванной 4 м2 под ключ" + the round-1 answers reach the sheet fast."""
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "ремонт ванной 4 м2 под ключ")
    assert intake.detected_type == "bathroom_reno"
    assert intake.round_idx == 1

    # Answer every required round-1 question; readiness should clear the skip
    # threshold and jump to the sheet without a round 2/3.
    answers = {
        "floor_area_m2": 4.0,
        "ceiling_height_m": 2.6,
        "finish_level": "standard",
        "demolition": True,
        "full_tiling": True,
    }
    intake = await service.answer(run, intake, schemas.IntakeAnswerRequest(answers=answers, advance=True))
    run, intake = await _reload(session, run.id)
    assert intake.phase == "parameter_sheet"
    assert intake.round_idx == 1


async def test_answer_records_and_marks_confirmed(session, project_id):
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation")
    intake = await service.answer(
        run, intake, schemas.IntakeAnswerRequest(answers={"floor_area_m2": 9.5}, advance=False)
    )
    assert intake.params["floor_area_m2"] == pytest.approx(9.5)
    assert intake.param_status["floor_area_m2"] == "confirmed"
    # Junk values are dropped, not stored as a fabricated number.
    intake = await service.answer(
        run, intake, schemas.IntakeAnswerRequest(answers={"floor_area_m2": "not-a-number"}, advance=False)
    )
    assert intake.params["floor_area_m2"] == pytest.approx(9.5)


# ── Parameter sheet -> compose group board ───────────────────────────────────


async def test_confirm_parameters_composes_gap_board_when_no_vectors(session, project_id):
    """No vectors -> every package is an honest gap, none silently dropped."""
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    assert intake.phase == "group_board"
    assert intake.packages, "the board must list packages"
    # No vectors => all gaps (honest disclosure), but groups still exist.
    assert all(p["coverage"] == "gap" for p in intake.packages)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert groups, "composed groups must be persisted"
    # Every persisted group carries the intake provenance metadata.
    assert all((g.metadata_ or {}).get("intake") for g in groups)


async def test_confirm_parameters_grounded_when_probe_scores_high(session, project_id, monkeypatch):
    _stub_rank_score(monkeypatch, 0.83)
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    assert intake.phase == "group_board"
    assert any(p["coverage"] == "grounded" for p in intake.packages)
    # The best probe score is a real float, never a placeholder.
    grounded = [p for p in intake.packages if p["coverage"] == "grounded"]
    assert all(isinstance(p["best_score"], float) for p in grounded)


async def test_weak_coverage_band_between_floor_and_medium(session, project_id, monkeypatch):
    _stub_rank_score(monkeypatch, 0.5)  # above the LOW floor, below MEDIUM (0.62)
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "bathroom renovation 5 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 5.0, "finish_level": "standard"})
    )
    assert any(p["coverage"] == "weak" for p in intake.packages)


# ── WorkGroup provenance metadata (design 3.1) ───────────────────────────────


async def test_composed_groups_carry_source_derivation_assumptions(session, project_id):
    """Every dialogue-composed group persists source=dialogue + derivation."""
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert groups
    for g in groups:
        meta = g.metadata_ or {}
        # The standardised WorkGroup provenance is present on every group.
        assert meta.get("source") == "dialogue"
        assert meta.get("derivation"), "a composed group must carry a derivation sentence"
        assert meta.get("qty_formula"), "the formula id is recorded for traceability"
        # assumptions is always a list (empty when no proxy was used).
        assert isinstance(meta.get("assumptions"), list)


async def test_group_detail_surfaces_workgroup_provenance(session, project_id):
    """GroupDetail exposes source / derivation / assumptions read from metadata_."""
    from app.modules.ai_estimator.service import AiEstimatorService

    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    detail = AiEstimatorService(session).group_to_detail(groups[0])
    assert detail.source == "dialogue"
    assert detail.derivation
    assert isinstance(detail.assumptions, list)
    # mapping_trace is unset until the matcher runs (WP3 owns it).
    assert detail.mapping_trace is None


async def test_custom_group_carries_dialogue_source(session, project_id):
    """A user-added custom work line is also a dialogue-sourced WorkGroup."""
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    intake = await service.edit_packages(
        run,
        intake,
        schemas.IntakePackagesRequest(
            add=[schemas.WorkPackageSelection(custom_description="Install splashback glass panel", unit="m2")]
        ),
    )
    custom_key = next(p["package_key"] for p in intake.packages if p["package_key"].startswith("custom_"))
    custom_group_id = intake.packages[[p["package_key"] for p in intake.packages].index(custom_key)]["group_ids"][0]
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    custom = next(g for g in groups if str(g.id) == custom_group_id)
    meta = custom.metadata_ or {}
    assert meta.get("source") == "dialogue"
    assert meta.get("derivation") == "single lump-sum line"


# ── Measured-path WorkGroup source (file / cad) ──────────────────────────────


async def test_measured_groups_tag_source_from_envelope(session, project_id):
    """_build_groups tags metadata_.source as file/cad from the envelope source."""
    from app.modules.ai_estimator.service import AiEstimatorService

    run = AiEstimatorRun(
        project_id=project_id,
        user_id=uuid.uuid4(),
        name="Measured source test",
        status="grouping",
        current_stage="grouping",
        source_inputs={"source": "bim"},
        group_by=["category", "unit"],
        # The measured envelopes the grouping pass buckets by signature.
        metadata_={
            "envelopes": [
                {
                    "id": "e1",
                    "source": "bim",
                    "description": "Reinforced concrete wall",
                    "category": "walls",
                    "ifc_class": "IfcWall",
                    "unit_hint": "m2",
                    "quantities": {"area_m2": 37.5},
                },
                {
                    "id": "e2",
                    "source": "boq",
                    "description": "Cement screed floor finish",
                    "category": "finishes",
                    "unit_hint": "m2",
                    "quantities": {"area_m2": 80.0},
                },
            ]
        },
    )
    run = await AiEstimatorRunRepository(session).create(run)

    run = await AiEstimatorService(session)._build_groups(run)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    by_desc = {g.description: g for g in groups}
    # A BIM-sourced group is cad; a BOQ-sourced group is file. Never dialogue.
    assert (by_desc["Reinforced concrete wall"].metadata_ or {}).get("source") == "cad"
    assert (by_desc["Cement screed floor finish"].metadata_ or {}).get("source") == "file"


# ── Package board editing ────────────────────────────────────────────────────


async def test_remove_package_deletes_its_groups(session, project_id):
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    target = intake.packages[0]["package_key"]
    removed_group_ids = {g for g in intake.packages[0]["group_ids"]}
    before = len(await AiEstimatorGroupRepository(session).list_for_run(run.id))

    intake = await service.edit_packages(run, intake, schemas.IntakePackagesRequest(remove=[target]))
    keys = {p["package_key"] for p in intake.packages}
    assert target not in keys
    after_groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(after_groups) < before
    assert removed_group_ids.isdisjoint({str(g.id) for g in after_groups})


async def test_add_custom_work_creates_a_probed_group(session, project_id):
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    before = len(await AiEstimatorGroupRepository(session).list_for_run(run.id))
    intake = await service.edit_packages(
        run,
        intake,
        schemas.IntakePackagesRequest(
            add=[schemas.WorkPackageSelection(custom_description="Install splashback glass panel", unit="m2")]
        ),
    )
    after = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(after) == before + 1
    assert any(p["package_key"].startswith("custom_") for p in intake.packages)


# ── Finish bridge to the run pipeline ────────────────────────────────────────


async def test_finish_advances_run_to_grouping_keeping_groups(session, project_id):
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    composed = len(await AiEstimatorGroupRepository(session).list_for_run(run.id))
    assert composed > 0

    run = await service.finish(run, intake, uuid.uuid4())
    assert run.status == "grouping"
    assert run.current_stage == "grouping"
    assert (run.checkpoints or {}).get("source", {}).get("accepted_at")
    assert (run.metadata_ or {}).get("intake_composed") is True
    # The composed groups survive the bridge (the run FSM must not re-derive).
    still = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(still) == composed


async def test_confirm_stage_source_does_not_wipe_composed_groups(session, project_id):
    """The run service skips _build_groups for an intake-composed run."""
    from app.modules.ai_estimator.service import AiEstimatorService

    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation 8 m2")
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params={"floor_area_m2": 8.0, "finish_level": "standard"})
    )
    run = await service.finish(run, intake, uuid.uuid4())
    composed = len(await AiEstimatorGroupRepository(session).list_for_run(run.id))

    # Re-confirming the source checkpoint must not re-derive/wipe groups.
    run_service = AiEstimatorService(session)
    run = await run_service.confirm_stage(run, schemas.StageConfirmRequest(stage="source", edits={}), uuid.uuid4())
    after = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(after) == composed


# ── State serialisation ──────────────────────────────────────────────────────


async def test_to_state_reports_offline_degradation(session, project_id):
    service = IntakeService(session)
    run, intake = await _start(session, project_id, "kitchen renovation")
    state = await service.to_state(run, intake)
    assert state.mode == "offline"
    assert state.ai_connected is False
    assert state.degraded_reason == "no_ai_key"
    assert state.rounds_remaining == MAX_CLARIFY_ROUNDS - state.round_idx
    assert state.detected_type == "kitchen_reno"
