# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠In-process recall harness for the intake v2 element-group composer.

This is design section 10.3 made literal: the "look hard at our vector DB and
pull as many real positions as possible" MEASUREMENT. It runs IN the backend
process so the warm BGE-M3 encoder and the live Qdrant are reachable (the
standalone encode-and-query loop segfaults when the model is loaded a second
time outside the warm server, per design section 2.6).

For each golden fixture it:

  1. binds the USA_USD catalogue (the only CWICR collection on this install,
     ``cwicr_en_v3``) to the project's match settings;
  2. composes the run's element groups with the REAL composer (real curated
     probes, real ranker), exactly as ``confirm_parameters`` does;
  3. for each composed package, reads the best-probe candidate the composer
     already grounded (its top-1 grounded score and the candidate text), and
     checks whether the top candidate's ``collection_name`` / MasterFormat
     division is in that package's ``golden_positions`` set.

Metrics reported per fixture and in aggregate (design section 10.3):

  * package_grounding_rate - packages with coverage in {grounded, weak} / total.
  * top1_in_golden_rate    - packages whose top candidate is in golden_positions
                             / packages with any candidate.
  * gap_disclosure_correctness - every package the harness marks a gap is ALSO
                             surfaced as a gap in the intake state (no silent
                             gaps). Asserted == 1.0.
  * recall_at_5            - packages with at least one golden position in their
                             top-5 candidates / total. The headline number the
                             composer is optimised to raise.

IMPORTANT: this harness is SKIPPABLE, never failing, when Qdrant is unreachable
or the catalogue is not vectorised. The deterministic composition floor lives in
``test_intake_golden.py`` and always runs. Here we assert only the design's
honest floors (gap-disclosure correctness == 1.0, and a soft grounding floor for
the residential finishes packages) AND print a per-package recall table so a
human can read exactly where recall leaks and add a better curated probe.

Run (with the live backend's Qdrant up on :6333):
    cd backend
    python -m pytest tests/unit/ai_estimator/test_intake_recall.py -q -s
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai_estimator import schemas
from app.modules.ai_estimator.intake import MAX_CLARIFY_ROUNDS, IntakeService
from app.modules.ai_estimator.repository import (
    AiEstimatorGroupRepository,
    AiEstimatorIntakeRepository,
    AiEstimatorRunRepository,
)
from tests._pg import transactional_session

# The catalogue id that maps to the only English CWICR collection present
# (``cwicr_en_v3``, US-only). country_to_collection("USA_USD") -> cwicr_en_v3.
_CATALOGUE_ID = os.environ.get("OE_INTAKE_RECALL_CATALOGUE", "USA_USD")
_TOP_K = 5

_FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ai_estimator_intake"


def _qdrant_url() -> str:
    return os.environ.get("QDRANT_URL", "http://localhost:6333").rstrip("/")


def _qdrant_http_reachable() -> bool:
    """True when the live Qdrant answers ``/collections`` over HTTP quickly."""
    try:
        with urlopen(f"{_qdrant_url()}/collections", timeout=3) as resp:  # noqa: S310 - localhost health probe
            return resp.status == 200
    except (URLError, OSError, ValueError):
        return False


def _semantic_stack_available() -> bool:
    """True only when the IN-PROCESS recall path can actually run.

    The harness runs the REAL ranker in-process, which needs (a) the live Qdrant
    answering HTTP, AND (b) the optional ``[semantic]`` stack importable in this
    process so ``qdrant_adapter._get_client`` can connect to the server (rather
    than raising ``ModuleNotFoundError`` or opening an empty embedded store). If
    either is missing the harness SKIPS - the deterministic composition floor in
    ``test_intake_golden.py`` still runs, and a CI box with the [semantic] extra
    + a live Qdrant will exercise the real recall numbers (design section 10.3:
    skippable, never failing, when the live vector path is unavailable).
    """
    if not _qdrant_http_reachable():
        return False
    try:
        import qdrant_client  # noqa: F401
    except ImportError:
        return False
    return True


_SKIP_REASON = (
    "in-process recall path unavailable (live Qdrant on QDRANT_URL + the "
    "[semantic] extra are both required); recall harness is skippable by design"
)

# Skip the ENTIRE module when the in-process recall path is unavailable - the
# harness is informational and must never fail CI on a missing live dependency
# (design section 10.3).
pytestmark = pytest.mark.skipif(not _semantic_stack_available(), reason=_SKIP_REASON)


def _load_fixtures() -> list[dict[str, Any]]:
    return [json.loads(fp.read_text(encoding="utf-8")) for fp in sorted(_FIXTURE_DIR.glob("*.json"))]


_FIXTURES = _load_fixtures()
_FIXTURE_IDS = [f["name"] for f in _FIXTURES]


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True, scope="module")
def _point_cwicr_at_live_qdrant():
    """Point the CWICR Qdrant client at the live server for this module.

    ``qdrant_adapter._get_client`` prefers ``settings.cwicr_qdrant_url`` (server
    mode) and otherwise opens an EMBEDDED on-disk store that is empty in a test
    process - which is why a naive in-process probe finds zero vectors. The live
    backend holds its data in the server on :6333, so we set the settings URL to
    it (and reset the cached client + the catalog-status cache) so the real
    ranker searches the live collection. The setting is restored afterwards so we
    do not leak module state into the rest of the suite.
    """
    from app.config import get_settings
    from app.modules.costs import qdrant_adapter

    settings = get_settings()
    prev_url = settings.cwicr_qdrant_url
    prev_client = qdrant_adapter._client
    settings.cwicr_qdrant_url = _qdrant_url()
    qdrant_adapter._client = None
    qdrant_adapter._catalog_status_cache.clear() if hasattr(qdrant_adapter, "_catalog_status_cache") else None
    # The catalog-status cache lives on the ranker module.
    try:
        from app.core.match_service import ranker_qdrant

        ranker_qdrant._catalog_status_cache.clear()
    except Exception:
        pass
    yield
    settings.cwicr_qdrant_url = prev_url
    qdrant_adapter._client = prev_client


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    from app.modules.projects.models import Project

    proj = Project(name="Intake recall", owner_id=uuid.uuid4(), currency="USD", region="USA_USD")
    session.add(proj)
    await session.flush()
    # Bind the catalogue to the project's match settings so rank() searches the
    # live collection (it resolves the catalogue from cost_database_id).
    from app.modules.projects.service import get_or_create_match_settings

    settings = await get_or_create_match_settings(session, proj.id)
    settings.cost_database_id = _CATALOGUE_ID
    session.add(settings)
    await session.flush()
    return proj.id


# ── Golden matching helpers ──────────────────────────────────────────────────


def _candidate_text(candidate: Any) -> str:
    """The searchable text a golden position is matched against (case-folded).

    The canonical ``cwicr_en_v3`` payload has no human description, so the
    ranker synthesises one from the categorical axes (``collection_name`` /
    ``category_type`` / ``masterformat_division`` etc.). We match the golden
    ``collection_name`` substrings against that synthesised description, and the
    golden MasterFormat divisions against the candidate's classification.
    """
    parts = [str(getattr(candidate, "description", "") or "")]
    cls = getattr(candidate, "classification", None) or {}
    parts.append(str(cls.get("masterformat", "")))
    return " ".join(parts).lower()


def _golden_hit(candidate: Any, golden: dict[str, list[str]]) -> bool:
    """True when a candidate matches any golden collection_name OR masterformat."""
    text = _candidate_text(candidate)
    for name in golden.get("collection_name", []):
        if name.lower() in text:
            return True
    cls = getattr(candidate, "classification", None) or {}
    mf = str(cls.get("masterformat", "")).strip()
    for div in golden.get("masterformat", []):
        if div and mf.startswith(div):
            return True
    return False


async def _rank_package(session: AsyncSession, run: Any, group: Any, top_k: int = _TOP_K) -> list[Any]:
    """Run the real ranker over a composed group's envelope; return candidates."""
    from app.core.match_service.envelope import ElementEnvelope, MatchRequest
    from app.core.match_service.ranker_qdrant import rank

    env_data = dict(group.envelope or {})
    envelope = ElementEnvelope(
        source="text",
        description=str(env_data.get("description") or group.description or "")[:2000],
        unit_hint=env_data.get("unit_hint"),
        project_currency=str(env_data.get("project_currency") or run.currency or "USD"),
        project_region=str(env_data.get("project_region") or run.region or ""),
        construction_stage_hint=env_data.get("construction_stage_hint"),
    )
    resp = await rank(
        MatchRequest(envelope=envelope, project_id=run.project_id, top_k=top_k, use_reranker=True),
        db=session,
    )
    return list(getattr(resp, "candidates", None) or [])


async def _compose(session: AsyncSession, project_id: uuid.UUID, fixture: dict[str, Any]) -> tuple[Any, Any]:
    """Compose a fixture's groups with the real probes against live Qdrant."""
    service = IntakeService(session)
    spec = schemas.IntakeCreate(
        project_id=project_id,
        text=fixture["raw_request"],
        mode_hint="offline",
        catalogue_id=_CATALOGUE_ID,
        currency="USD",
        region="USA_USD",
    )
    run, intake = await service.start(spec, uuid.uuid4())
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
    intake = await service.confirm_parameters(
        run, intake, schemas.ConfirmParametersRequest(params=dict(fixture["answers"]))
    )
    run = await AiEstimatorRunRepository(session).get_by_id(run.id)
    return run, intake


# ── The recall harness ───────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture", _FIXTURES, ids=_FIXTURE_IDS)
async def test_recall_against_live_qdrant(session, project_id, fixture):
    """Compose against the live ranker and report recall vs golden positions.

    Bind the USA_USD catalogue, compose the groups, run the real ranker per
    package, and compute the design's four metrics. We assert only the honest
    floors (gap-disclosure correctness, and a soft grounding floor for the
    residential finishes packages); the recall numbers are PRINTED so a human can
    read where recall leaks. The US/civil-heavy synthetic catalogue means top-1
    accuracy is honestly modest, exactly as the design predicts.
    """
    run, intake = await _compose(session, project_id, fixture)
    golden = fixture["golden_positions"]

    groups = await AiEstimatorGroupRepository(session).list_for_run(run.id)
    # One representative group per package (the package's first/lowest cell).
    by_package: dict[str, Any] = {}
    for g in groups:
        key = (g.metadata_ or {}).get("package_key")
        if key and key not in by_package:
            by_package[key] = g

    board = {p["package_key"]: p for p in intake.packages}

    rows: list[dict[str, Any]] = []
    grounded_or_weak = 0
    top1_in_golden = 0
    with_candidate = 0
    recall_at_5 = 0
    total_with_golden = 0
    gap_disclosure_ok = True

    for key, group in by_package.items():
        gold = golden.get(key)
        coverage = board.get(key, {}).get("coverage", "gap")
        candidates = await _rank_package(session, run, group)
        top = candidates[0] if candidates else None

        if coverage in ("grounded", "weak"):
            grounded_or_weak += 1
        # Gap-disclosure correctness: a package with NO live candidate must be a
        # disclosed gap on the board (never a silent gap).
        if not candidates and coverage != "gap":
            gap_disclosure_ok = False

        hit_top1 = bool(top and gold and _golden_hit(top, gold))
        hit_at5 = bool(gold and any(_golden_hit(c, gold) for c in candidates))
        if top is not None:
            with_candidate += 1
            if hit_top1:
                top1_in_golden += 1
        if gold is not None:
            total_with_golden += 1
            if hit_at5:
                recall_at_5 += 1

        rows.append(
            {
                "package": key,
                "coverage": coverage,
                "best_score": board.get(key, {}).get("best_score"),
                "top_desc": (str(getattr(top, "description", "")) if top else "")[:60],
                "top1_golden": "yes" if hit_top1 else ("no" if gold else "-"),
                "in_top5": "yes" if hit_at5 else ("no" if gold else "-"),
            }
        )

    total = max(len(by_package), 1)
    grounding_rate = grounded_or_weak / total
    top1_rate = (top1_in_golden / with_candidate) if with_candidate else 0.0
    recall5 = (recall_at_5 / total_with_golden) if total_with_golden else 0.0

    # Per-package table (printed with -s) so a human can read recall leaks.
    print(f"\n=== recall: {fixture['name']} (catalogue {_CATALOGUE_ID}) ===")
    print(f"{'package':24s} {'coverage':9s} {'score':>7s} {'t1':>4s} {'@5':>4s}  top candidate")
    for r in rows:
        score = f"{r['best_score']:.3f}" if isinstance(r["best_score"], float) else "  -  "
        print(
            f"{r['package']:24s} {r['coverage']:9s} {score:>7s} "
            f"{r['top1_golden']:>4s} {r['in_top5']:>4s}  {r['top_desc']}"
        )
    print(
        f"grounding_rate={grounding_rate:.2f} top1_in_golden={top1_rate:.2f} "
        f"recall_at_5={recall5:.2f} gap_disclosure_ok={gap_disclosure_ok}"
    )

    # ── Asserted floors (honest; the rest is informational) ──────────────
    # 1. No silent gaps - every package with no live candidate is a disclosed
    #    gap (design section 10.3, must be 1.0).
    assert gap_disclosure_ok, f"{fixture['name']} has a silent gap (no candidate but coverage != gap)"

    # 2. A soft grounding floor for the residential finishes types: the curated
    #    probes must keep the catalogue reachable for most packages. The
    #    US/civil catalogue makes this honest, not perfect (design floor 0.7 for
    #    kitchen/bathroom/apartment finishes); house_new is structure-heavy and
    #    not floored (the US catalogue is thin on residential structure).
    if fixture["expected_type"] in ("kitchen_reno", "bathroom_reno", "apartment_reno"):
        assert grounding_rate >= 0.7, (
            f"{fixture['name']} grounding_rate {grounding_rate:.2f} below the 0.70 floor - "
            "add or improve curated probe phrasings"
        )
