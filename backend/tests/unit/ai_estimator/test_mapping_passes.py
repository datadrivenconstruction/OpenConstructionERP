# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Mapping recall / sanity harness for the multi-pass mapping pipeline (WP5).

This is design section 8 (the founder test matrix) made literal as an
in-process, deterministic harness. It drives the WHOLE WorkGroup pipeline -
dialogue composition AND measured-source grouping - then the explicit
three-pass mapping (semantic -> unit/scale -> rate sanity, design section 4.3),
across the founder's diverse inputs:

    1. "make me a kitchen estimate"          (dialogue, kitchen_reno)
    2. "house renovation 120 m2"             (dialogue, house_new)
    3. "new house 2 storeys"                 (dialogue, house_new)
    4. "bathroom refurb 5 m2 turnkey"        (dialogue, bathroom_reno)
    5. an uploaded Excel BOQ                 (file, three measured lines)
    6. a converted CAD canonical model       (cad, walls + slabs + doors)

It runs FULLY OFFLINE - no AI key (``use_agent=False``, so ``final_method``
stays deterministic ``vector``) and no live Qdrant (the grounded ``rank()`` is
stubbed to a curated, per-trade candidate set so the harness is hermetic and
runs in CI without any external dependency). The stub returns REAL-shaped
``MatchCandidate`` rows; the passes then reconcile and sanity-check them exactly
as they would over live vectors.

The harness asserts the design's honest floors per case:

    * Cases 1-4 (dialogue): the founder phrase detects the expected type within
      the 3-round cap; the staged volumetric group board is a SUPERSET of the
      type's default packages; every group carries a real quantity and the
      ``dialogue`` source; after matching every group exposes the three named
      passes in its ``mapping_trace`` with ``final_method == "vector"``.
    * Case 5 (Excel BOQ): one signature group per measured line with the row's
      quantity, unit and trade and ``source == "file"``; multi-pass runs per
      group; a dimensionally-incompatible candidate is DEMOTED (not dropped) in
      pass 2.
    * Case 6 (CAD canonical): signature groups by ``ifc_class`` carrying the
      hard filter into pass 1, the summed canonical quantity and ``source ==
      "cad"``; multi-pass runs per group.
    * All cases (the WP5 live-verification metric, design section 8 / WP5): the
      gap-disclosure / outlier-surfacing correctness is 1.0 - every benchmark
      outlier the rate-sanity pass flags is SURFACED on the group's candidate
      list (``rate_outlier``) and counted in the trace, while the real top-1 is
      a plausible (non-outlier) rate; a group with no candidate is an honest
      ``needs_human`` gap, never a fabricated number.

Run:
    cd backend
    python -m pytest tests/unit/ai_estimator/test_mapping_passes.py -q
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
from app.modules.ai_estimator.project_types import default_packages, detect_project_type, get_project_type
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorIntakeRepository,
    AiEstimatorRunRepository,
)
from app.modules.ai_estimator.service import AiEstimatorService
from tests._pg import transactional_session

# ``asyncio_mode = "auto"`` (pyproject) runs ``async def`` tests as asyncio
# without an explicit mark.

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ai_estimator_mapping"


# ── The founder dialogue matrix (design section 8, cases 1-4) ────────────────
#
# The exact founder phrases (translated EN + the original RU two), each with the
# scripted answers that fully specify the request so the machine reaches the
# parameter sheet inside the round cap. Quantities are computed by the pure
# formulas from these answers (offline and AI paths are numerically identical).

_DIALOGUE_CASES: list[dict[str, Any]] = [
    {
        "name": "kitchen_estimate",
        "raw_request": "make me a kitchen estimate",
        "expected_type": "kitchen_reno",
        "answers": {
            "floor_area_m2": 8.0,
            "ceiling_height_m": 2.7,
            "finish_level": "standard",
            "demolition": True,
        },
    },
    {
        "name": "kitchen_estimate_ru",
        # "make me a kitchen estimate" in Russian (the founder's literal phrase).
        "raw_request": "сделай мне смету кухни",
        "expected_type": "kitchen_reno",
        "answers": {
            "floor_area_m2": 10.0,
            "ceiling_height_m": 2.7,
            "finish_level": "standard",
            "demolition": True,
        },
    },
    {
        "name": "house_renovation_120",
        # Design case 2: detect_project_type resolves this to house_new
        # deterministically (a single distinct synonym hit, not ambiguous), so
        # the harness pins the shipped longest-synonym behaviour.
        "raw_request": "house renovation 120 m2",
        "expected_type": "house_new",
        "answers": {
            "gross_floor_area_m2": 120.0,
            "storeys": 1,
            "footprint_m2": 120.0,
            "wall_construction": "masonry",
            "roof_type": "pitched",
            "roof_area_m2": 140.0,
            "pitch_deg": 30.0,
            "ceiling_height_m": 2.7,
            "finish_level": "standard",
            "foundation_type": "strip",
        },
    },
    {
        "name": "new_house_2_storeys",
        "raw_request": "new house 2 storeys",
        "expected_type": "house_new",
        "answers": {
            "gross_floor_area_m2": 180.0,
            "storeys": 2,
            "footprint_m2": 90.0,
            "wall_construction": "masonry",
            "roof_type": "pitched",
            "roof_area_m2": 110.0,
            "pitch_deg": 30.0,
            "ceiling_height_m": 2.7,
            "finish_level": "standard",
            "foundation_type": "strip",
        },
    },
    {
        "name": "bathroom_turnkey",
        "raw_request": "bathroom refurb 5 m2 turnkey",
        "expected_type": "bathroom_reno",
        "answers": {
            "floor_area_m2": 5.0,
            "ceiling_height_m": 2.6,
            "finish_level": "standard",
            "demolition": True,
            "full_tiling": True,
            "waterproofing": True,
            "fixtures_count": 3,
        },
    },
]
_DIALOGUE_IDS = [c["name"] for c in _DIALOGUE_CASES]


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


# ── The deterministic offline stub ranker (no LLM, no Qdrant) ────────────────
#
# A per-trade curated candidate bank so the multi-pass mapping has real work on
# every group without a live vector DB. Rates cluster tightly per trade so the
# rate-sanity pass keeps them, and one trade (``finishes``) additionally carries
# a deliberately-injected dimension-mismatch row and a gross price outlier so the
# harness can prove pass 2 demotion and pass 3 outlier surfacing on the real
# pipeline. Every row is a real-shaped ``MatchCandidate`` (never a fabricated
# rate; the stub stands in for the grounded retrieval the design reuses).

# (description, unit, unit_rate, score) per trade. The leading row is the
# plausible, dimensionally-correct, highest-scoring expected top-1.
_CANDIDATE_BANK: dict[str, list[tuple[str, str, float, float]]] = {
    "demolition": [("Strip out and demolition", "m2", 22.0, 0.82), ("Demolition allowance", "m2", 25.0, 0.74)],
    "finishes": [
        ("Plaster and finish to walls", "m2", 28.0, 0.84),
        ("Finish coat second option", "m2", 31.0, 0.79),
        # A volume rate for an area trade: pass 2 must DEMOTE this out of top-1.
        ("Bagged material by volume", "m3", 120.0, 0.91),
        # A gross ~100x price outlier: pass 3 must FLAG + cap, never drop it.
        ("Mispriced finish line", "m2", 3200.0, 0.88),
    ],
    "earthworks": [("Bulk excavation and cart away", "m3", 38.0, 0.80), ("Excavation alt", "m3", 41.0, 0.72)],
    "foundations": [("Strip foundation in concrete", "m2", 95.0, 0.83), ("Foundation alt", "m2", 102.0, 0.76)],
    "masonry": [("Brick masonry wall 240mm", "m2", 88.0, 0.85), ("Block wall alt", "m2", 92.0, 0.77)],
    "envelope": [("Pitched roof structure", "m2", 130.0, 0.81), ("Waterproof membrane", "m2", 35.0, 0.78)],
    "openings": [("Galvanised steel door supply and fix", "pcs", 480.0, 0.83), ("Door alt", "pcs", 510.0, 0.75)],
    "other": [("Commissioning and testing", "lsum", 1500.0, 0.70)],
}


def _stub_rank_per_trade(monkeypatch) -> None:
    """Stub ``rank()`` to a per-trade curated candidate bank (offline, hermetic).

    The matched group's trade is read off the envelope's synthesised description
    (we tag the description with a trade marker the stub reads), so each group
    gets a plausible candidate set for its own trade. A trade with no bank entry
    yields no candidate (an honest ``needs_human`` gap, exercising the no-rate
    path). No external service is touched; nothing is fabricated beyond the
    curated stand-in for the grounded retrieval the design reuses unchanged.
    """
    from app.core.match_service.envelope import MatchCandidate, MatchRequest, MatchResponse

    def _trade_for(description: str) -> str:
        text = (description or "").lower()
        # The harness threads the trade into the description as a hidden marker
        # so the stub can route without a live classifier; production reads real
        # vectors. Fall back to keyword sniffing for the dialogue descriptions.
        for trade in _CANDIDATE_BANK:
            if f"#trade:{trade}" in text:
                return trade
        if any(w in text for w in ("demolition", "strip out", "debris")):
            return "demolition"
        if any(w in text for w in ("excavation", "earthwork")):
            return "earthworks"
        if "foundation" in text:
            return "foundations"
        if any(w in text for w in ("brick", "block", "masonry")):
            return "masonry"
        if any(w in text for w in ("roof", "waterproof", "facade", "membrane")):
            return "envelope"
        if any(w in text for w in ("door", "window")):
            return "openings"
        if any(w in text for w in ("commission", "testing")):
            return "other"
        return "finishes"

    async def _rank(req, *, db, ai_settings=None):  # noqa: ANN001, ANN202 - match the real signature
        envelope = getattr(req, "envelope", None) or req
        description = str(getattr(envelope, "description", "") or "")
        # An explicit ``#trade:none`` marker forces the no-candidate path (an
        # honest gap / needs_human), independent of the keyword fallback below.
        if "#trade:none" in description.lower():
            return MatchResponse(
                request=req if isinstance(req, MatchRequest) else MatchRequest(envelope=envelope, project_id=None),
                candidates=[],
            )
        trade = _trade_for(description)
        bank = _CANDIDATE_BANK.get(trade, [])
        candidates = [
            MatchCandidate(
                id=str(uuid.uuid4()),
                code=f"{trade.upper()[:4]}-{i}",
                description=desc,
                unit=unit,
                unit_rate=rate,
                currency="EUR",
                score=score,
                confidence_band="high" if score >= 0.78 else "medium",
            )
            for i, (desc, unit, rate, score) in enumerate(bank)
        ]
        return MatchResponse(
            request=req if isinstance(req, MatchRequest) else MatchRequest(envelope=envelope, project_id=None),
            candidates=candidates,
        )

    monkeypatch.setattr("app.core.match_service.ranker_qdrant.rank", _rank)


# ── DB fixtures (function-scoped, transaction-isolated) ──────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project

    proj = Project(name="Mapping harness", owner_id=uuid.uuid4(), currency="EUR", region="DE_BERLIN")
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.fixture(autouse=True)
def _offline_ranker(monkeypatch):
    """Every test runs against the deterministic per-trade stub (no Qdrant)."""
    _stub_rank_per_trade(monkeypatch)


# ── Pipeline drivers (service layer, no HTTP) ────────────────────────────────


async def _compose_dialogue(session: AsyncSession, project_id: uuid.UUID, case: dict[str, Any]):
    """Drive the dialogue path: start -> answer rounds -> confirm parameters."""
    service = IntakeService(session)
    spec = schemas.IntakeCreate(project_id=project_id, text=case["raw_request"], mode_hint="offline")
    run, intake = await service.start(spec, uuid.uuid4())

    for _ in range(MAX_CLARIFY_ROUNDS + 1):
        run = await AiEstimatorRunRepository(session).get_by_id(run.id)
        intake = await AiEstimatorIntakeRepository(session).get_for_run(run.id)
        assert run is not None and intake is not None
        assert intake.round_idx <= MAX_CLARIFY_ROUNDS, "the machine must never open a 4th round"
        if intake.phase == "parameter_sheet":
            break
        intake = await service.answer(
            run, intake, schemas.IntakeAnswerRequest(answers=dict(case["answers"]), advance=True)
        )

    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params=dict(case["answers"]))
    )
    run = await AiEstimatorRunRepository(session).get_by_id(run.id)
    assert run is not None
    return run, intake


async def _build_measured_run(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    source: str,
    envelopes: list[dict[str, Any]],
    currency: str = "EUR",
):
    """Create a measured run, seed its envelopes, and run the grouping pass.

    Bypasses the source-extraction step (which would need live BIM/cost tables)
    by writing the already-normalised envelopes the extractor would emit, then
    calls the REAL ``_build_groups`` signature grouping the measured path uses in
    production. This keeps the harness hermetic while exercising the genuine
    grouping + multi-pass code paths.
    """
    service = AiEstimatorService(session)
    run = await service.create_run(
        schemas.RunCreate(project_id=project_id, source=source, currency=currency),  # type: ignore[arg-type]
        uuid.uuid4(),
    )
    await service.run_repo.update_fields(run.id, metadata_={**(run.metadata_ or {}), "envelopes": envelopes})
    run = await service.run_repo.get_by_id(run.id)
    assert run is not None
    run = await service._build_groups(run)
    return service, run


async def _match(service: AiEstimatorService, run) -> None:
    """Run the matcher offline (no agent) over every group on the run."""
    await service.run_matching(run, schemas.RunMatchRequest(use_agent=False, top_k=5))


def _trace_pass_names(trace: dict[str, Any] | None) -> list[str]:
    return [p["pass"] for p in (trace or {}).get("passes", [])]


# ═════════════════════════════════════════════════════════════════════════
#  Cases 1-4: dialogue -> volumetric work groups -> multi-pass mapping
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("case", _DIALOGUE_CASES, ids=_DIALOGUE_IDS)
async def test_dialogue_phrase_detects_type_within_round_cap(case):
    """Each founder phrase detects the expected project type offline."""
    detected, _count = detect_project_type(case["raw_request"])
    assert detected == case["expected_type"], f"{case['name']} detected {detected}"


@pytest.mark.parametrize("case", _DIALOGUE_CASES, ids=_DIALOGUE_IDS)
async def test_dialogue_composes_sensible_volumetric_groups(session, project_id, case):
    """A founder phrase yields a staged volumetric board that is a SUPERSET of
    the type's default packages; every group has a real quantity and source."""
    run, intake = await _compose_dialogue(session, project_id, case)
    assert intake.phase == "group_board"

    pt = get_project_type(case["expected_type"])
    assert pt is not None
    defaults = {p.key for p in default_packages(pt)}
    composed = {p["package_key"] for p in intake.packages}
    assert composed >= defaults, f"{case['name']} board {sorted(composed)} is not a superset of defaults"

    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert groups, "the dialogue path must persist volumetric groups"
    for g in groups:
        meta = g.metadata_ or {}
        # WorkGroup provenance: a dialogue group is sourced from the dialogue.
        assert meta.get("source") == "dialogue", f"{case['name']} group {g.group_key} source {meta.get('source')}"
        # Every group is staged in the foreman build sequence.
        assert meta.get("foreman_stage"), f"{case['name']} group {g.group_key} missing foreman_stage"
        # Every group carries a real, non-negative quantity (estimated allowed).
        primary = service_primary_quantity(g)
        assert primary >= 0.0
    # At least one group carries a positive measured/derived quantity (not all
    # lump-sum), proving the volumetric derivation actually fired.
    assert any(service_primary_quantity(g) > 0 for g in groups), f"{case['name']} produced no positive quantity"


def service_primary_quantity(grp) -> float:
    """The group's primary quantity for its chosen unit (mirrors the serializer)."""
    from app.modules.ai_estimator.service import _quantity_for_unit

    return float(_quantity_for_unit(grp.quantities or {}, grp.chosen_unit) or 0.0)


@pytest.mark.parametrize("case", _DIALOGUE_CASES, ids=_DIALOGUE_IDS)
async def test_dialogue_multi_pass_yields_traced_candidates(session, project_id, case):
    """After matching, every matched dialogue group exposes the three named
    passes in its mapping_trace, with deterministic vector final_method."""
    run, _intake = await _compose_dialogue(session, project_id, case)
    service = AiEstimatorService(session)
    # Advance through the source checkpoint is not needed for an intake-composed
    # run; the groups already exist, so we match them directly.
    await _match(service, run)

    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    matched = [g for g in groups if g.status in ("suggested", "needs_human")]
    assert matched, f"{case['name']} ran no groups through the matcher"

    traced = 0
    for g in matched:
        detail = service.group_to_detail(g)
        trace = detail.mapping_trace
        if g.candidates:
            # A group that retrieved candidates must carry all three named passes.
            assert trace is not None, f"{case['name']} group {g.group_key} matched without a trace"
            names = [p.pass_ for p in trace.passes]
            assert names == ["semantic", "unit_scale", "rate_sanity"], f"{case['name']} {g.group_key} passes {names}"
            assert trace.final_method == "vector", f"{case['name']} {g.group_key} method {trace.final_method}"
            traced += 1
    assert traced > 0, f"{case['name']} produced no grounded, traced group"


# ═════════════════════════════════════════════════════════════════════════
#  Case 5: uploaded Excel BOQ -> one group per line -> multi-pass mapping
# ═════════════════════════════════════════════════════════════════════════


async def test_excel_boq_groups_per_line_and_maps(session, project_id):
    """Three measured Excel BOQ lines become three signature groups carrying the
    row quantity / unit / trade and source=file; the multi-pass maps each."""
    fixture = _load_fixture("excel_boq.json")
    service = AiEstimatorService(session)
    # The rows path normalises to envelopes exactly as a real Excel upload would.
    envelopes = service._normalise_sources({"rows": fixture["rows"]})
    assert len(envelopes) == len(fixture["rows"])

    service, run = await _build_measured_run(session, project_id, source="excel", envelopes=envelopes)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(groups) == len(fixture["expected_groups"]), "one signature group per measured line"

    by_unit = {g.chosen_unit: g for g in groups}
    for exp in fixture["expected_groups"]:
        g = by_unit[exp["unit"]]
        assert exp["description_contains"] in (g.description or "").lower()
        assert g.trade == exp["trade"], f"line {exp['description_contains']} trade {g.trade}"
        assert service_primary_quantity(g) == pytest.approx(exp["quantity"])
        assert (g.metadata_ or {}).get("source") == exp["source"]

    # Multi-pass maps each line to a grounded rate (or honest needs_human).
    await _match(service, run)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    for g in groups:
        detail = service.group_to_detail(g)
        if g.candidates:
            assert _trace_pass_names(detail.mapping_trace.model_dump(by_alias=True)) == [
                "semantic",
                "unit_scale",
                "rate_sanity",
            ]
            # No fabricated rate: a grounded group's top-1 came from the bank.
            assert g.unit_rate is not None
        else:
            assert g.status == "needs_human" and g.unit_rate is None


# ═════════════════════════════════════════════════════════════════════════
#  Case 6: CAD canonical model -> signature groups by ifc_class -> multi-pass
# ═════════════════════════════════════════════════════════════════════════


def _cad_envelopes(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt canonical CAD elements into the envelopes extract_bim emits.

    Mirrors the BIM extractor's contract (design 4.1): source=bim, the IFC class
    carried as a hard filter, the canonical quantity dict, and a synthesised
    description. The harness adapts the canonical JSON directly so the test stays
    DB-free while exercising the genuine signature grouping + multi-pass code.
    """
    envelopes: list[dict[str, Any]] = []
    for el in fixture["elements"]:
        ifc = str(el.get("ifc_class") or el.get("category") or "")
        envelopes.append(
            {
                "id": str(el["id"]),
                "source": "bim",
                "description": f"{ifc} element",
                "category": ifc,
                "ifc_class": ifc,
                "unit_hint": None,
                "quantities": dict(el.get("quantities") or {}),
                "exact_code": None,
                "properties": dict(el.get("properties") or {}),
            }
        )
    return envelopes


async def test_cad_canonical_groups_by_ifc_class_and_maps(session, project_id):
    """A converted CAD model groups by ifc_class signature, sums canonical
    quantities, carries the hard filter + source=cad, and runs the multi-pass."""
    fixture = _load_fixture("cad_canonical.json")
    envelopes = _cad_envelopes(fixture)
    service, run = await _build_measured_run(session, project_id, source="bim", envelopes=envelopes)

    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(groups) == len(fixture["expected_groups"]), "one signature group per ifc_class"

    by_ifc = {(g.envelope or {}).get("ifc_class"): g for g in groups}
    for exp in fixture["expected_groups"]:
        g = by_ifc[exp["ifc_class"]]
        # The ifc_class hard filter is carried into the matcher envelope (pass 1).
        assert (g.envelope or {}).get("ifc_class") == exp["ifc_class"]
        assert g.chosen_unit == exp["unit"]
        assert g.element_count == exp["element_count"]
        assert service_primary_quantity(g) == pytest.approx(exp["quantity"])
        assert (g.metadata_ or {}).get("source") == "cad"

    await _match(service, run)
    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    for g in groups:
        detail = service.group_to_detail(g)
        if g.candidates:
            names = [p.pass_ for p in detail.mapping_trace.passes]
            assert names == ["semantic", "unit_scale", "rate_sanity"]


# ═════════════════════════════════════════════════════════════════════════
#  All cases: gap-disclosure / outlier-surfacing correctness == 1.0 (WP5)
# ═════════════════════════════════════════════════════════════════════════


async def test_outlier_surfacing_and_demotion_correctness(session, project_id):
    """The WP5 live-verification metric, made deterministic.

    The ``finishes`` candidate bank carries a deliberately-injected dimension
    mismatch (an m3 rate for an m2 group) and a gross ~100x price outlier. After
    the real multi-pass over a finishes group, the harness asserts the design's
    invariants hold with NO leak:

      * the group's CHOSEN (booked) rate is a dimensionally-correct, non-outlier
        rate - pass 2 demoted the m3 row below the m2 ones, and the chosen top-1
        is the first non-outlier survivor (the score-ordered candidate LIST may
        still lead with the suspect-but-real outlier, capped at LOW band, so the
        human can see and override it);
      * every flagged outlier is SURFACED on the candidate list (``rate_outlier``
        True) and counted in the rate-sanity trace (the 1.0 disclosure metric);
      * the flagged outlier's confidence band is capped at LOW;
      * the demoted m3 row and the 100x price row both SURVIVE for human override
        (never dropped);
      * no rate is fabricated - every candidate is a real bank row.
    """
    # A single m2 finishes group (tiling) so the injected finishes bank applies.
    envelopes = [
        {
            "id": "tile_1",
            "source": "boq",
            "description": "Wall tiling to bathroom #trade:finishes",
            "category": "finishes",
            "unit_hint": "m2",
            "quantities": {"area_m2": 30.0},
            "exact_code": None,
        }
    ]
    service, run = await _build_measured_run(session, project_id, source="excel", envelopes=envelopes)
    await _match(service, run)

    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(groups) == 1
    grp = groups[0]
    detail = service.group_to_detail(grp)
    candidates = detail.candidates
    assert candidates, "the finishes group must retrieve the curated bank"

    # The CHOSEN (booked) rate is a plausible, non-outlier rate: pass 2 demoted
    # the dimension-mismatch m3 row and pass 3 skipped the price outlier when
    # picking the top-1, so the group's stored rate is one of the two real m2
    # finish rates (28 / 31), never the m3 (120) or the 3200 outlier.
    assert grp.unit_rate is not None
    assert float(grp.unit_rate) in (28.0, 31.0), f"chosen rate {grp.unit_rate} is not a plausible m2 finish rate"
    chosen = next(c for c in candidates if c.code == grp.chosen_code)
    assert chosen.unit == "m2"
    assert chosen.rate_outlier is False

    # Both the m3 dimension-mismatch row and the 100x price row SURVIVE (never
    # dropped) so the human can still override to a real rate.
    units = {c.unit for c in candidates}
    assert "m3" in units, "the demoted m3 candidate must survive in the override list"
    rates = {float(c.unit_rate) for c in candidates}
    assert 3200.0 in rates, "the real outlier rate must be kept for human override"

    # Outlier-surfacing correctness == 1.0: every candidate flagged as an outlier
    # in the trace is also surfaced (rate_outlier) on the candidate list.
    rs_pass = detail.mapping_trace.passes[2]
    assert rs_pass.pass_ == "rate_sanity"
    flagged_in_trace = rs_pass.benchmark.outliers if rs_pass.benchmark else 0
    surfaced = [c for c in candidates if c.rate_outlier]
    assert len(surfaced) == flagged_in_trace, "every trace-flagged outlier must be surfaced on a candidate"
    assert flagged_in_trace >= 1, "the injected 100x outlier must be flagged"
    # The surfaced outlier is the 3200 row, capped at LOW band, not dropped.
    out = next(c for c in surfaced if float(c.unit_rate) == 3200.0)
    assert out.confidence_band == "low"

    # The trace is the full three named passes (observable multi-pass).
    assert [p.pass_ for p in detail.mapping_trace.passes] == ["semantic", "unit_scale", "rate_sanity"]


async def test_no_candidate_trade_is_honest_needs_human_gap(session, project_id):
    """A group whose trade has no candidate bank entry is an honest needs_human
    gap with a null rate - never a fabricated number (design invariant)."""
    # ``#trade:none`` forces the stub's empty-candidate path (no grounded rate).
    envelopes = [
        {
            "id": "x_1",
            "source": "boq",
            "description": "Exotic widget with no catalogue match #trade:none",
            "category": "",
            "unit_hint": "pcs",
            "quantities": {"count": 3.0},
            "exact_code": None,
        }
    ]
    service, run = await _build_measured_run(session, project_id, source="excel", envelopes=envelopes)
    await _match(service, run)

    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    assert len(groups) == 1
    g = groups[0]
    assert g.status == "needs_human"
    assert g.unit_rate is None
    assert g.confidence is None
    assert g.confidence_band == "none"
