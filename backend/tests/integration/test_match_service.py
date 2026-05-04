# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for ``app.core.match_service``.

Uses a temp SQLite DB (per ``feedback_test_isolation.md`` — never the
production ``openestimate.db``) and monkeypatches the LanceDB cost
vector adapter to return fixed hits so the suite stays deterministic
and fast (no real embedding model required).
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.match_service import (
    ElementEnvelope,
    MatchCandidate,
    MatchRequest,
    build_envelope,
    match_element,
    match_envelope,
    rank,
    record_feedback,
)
from app.core.match_service.boosts import classifier as classifier_boost
from app.core.match_service.boosts import lex as lex_boost
from app.core.match_service.boosts import unit as unit_boost
from app.core.match_service.config import BOOST_WEIGHTS

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _bypass_catalog_gate(monkeypatch):
    """v2.8.2 — short-circuit the per-project catalogue gate.

    These tests predate the ``cost_database_id`` binding and exercise the
    ranker's *post-gate* behaviour (translation, vector search, boosts).
    Stub the resolver to ``ok`` so they keep covering what they were
    written for; the binding itself is exercised in
    ``test_match_catalog_binding``.
    """
    async def _ok(*_args, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(
        "app.core.match_service.ranker._resolve_catalog_status",
        _ok,
        raising=True,
    )


def _register_minimal_models() -> None:
    """Pull projects + users + audit models into Base.metadata."""
    import app.core.audit  # noqa: F401  — AuditEntry table
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "match_service.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest_asyncio.fixture
async def project_id(temp_engine_and_factory) -> uuid.UUID:
    """Create a real Project row so MatchProjectSettings can FK to it."""
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"match-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Match Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Match Test Project",
        owner_id=user.id,
        region="DACH",
        status="active",
    )
    async with factory() as session:
        session.add(user)
        await session.flush()
        session.add(project)
        await session.commit()
    return project.id


# ── Mock cost vector adapter ─────────────────────────────────────────────


def _fixed_hits() -> list[dict]:
    """Three deterministic CWICR-shaped hits used across most tests."""
    return [
        {
            "id": "hit-1",
            "score": 0.82,
            "text": "Stahlbetonwand C30/37, 24cm",
            "payload": {
                "code": "330.10.020",
                "description": "Stahlbetonwand C30/37, 24cm",
                "unit": "m2",
                "unit_cost": 145.0,
                "currency": "EUR",
                "region_code": "DE_BERLIN",
                "source": "cwicr",
                "language": "de",
                "classification_din276": "330.10.020",
                "classification_nrm": "",
                "classification_masterformat": "",
            },
        },
        {
            "id": "hit-2",
            "score": 0.75,
            "text": "Mauerwerk Kalksandstein 17.5cm",
            "payload": {
                "code": "331.20.010",
                "description": "Mauerwerk Kalksandstein 17.5cm",
                "unit": "m2",
                "unit_cost": 88.0,
                "currency": "EUR",
                "region_code": "DE_MUNICH",
                "source": "cwicr",
                "language": "de",
                "classification_din276": "331.20.010",
                "classification_nrm": "",
                "classification_masterformat": "",
            },
        },
        {
            "id": "hit-3",
            "score": 0.71,
            "text": "Reinforced concrete column",
            "payload": {
                "code": "340.10.011",
                "description": "Reinforced concrete column C30/37",
                "unit": "m3",
                "unit_cost": 260.0,
                "currency": "EUR",
                "region_code": "GB_LONDON",
                "source": "cwicr",
                "language": "en",
                "classification_din276": "340.10.011",
                "classification_nrm": "",
                "classification_masterformat": "",
            },
        },
    ]


@pytest.fixture
def patch_vector_search(monkeypatch):
    """Replace cost_vector.search with a deterministic stub.

    Returns the list-of-hits handle so tests can mutate it before the
    matcher runs.
    """
    state: dict[str, list[dict]] = {"hits": _fixed_hits()}

    async def _stub_search(query: str, *, limit: int, language: str | None = None, **kwargs):
        return list(state["hits"])[:limit]

    from app.modules.costs import vector_adapter

    monkeypatch.setattr(vector_adapter, "search", _stub_search)
    return state


# ── End-to-end ranker tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bim_to_envelope_to_ranked_candidates(
    temp_engine_and_factory, project_id, patch_vector_search,
) -> None:
    """BIM element flows through translation, vector search, boosts."""
    _engine, factory, _tmp = temp_engine_and_factory

    raw = {
        "category": "wall",
        "name": "Stahlbetonwand",
        "properties": {"material": "Concrete C30/37", "fire_rating": "F90"},
        "geometry": {"thickness_m": 0.24, "area_m2": 37.5},
        "classification": {"din276": "330.10.020"},
        "language": "de",
    }
    envelope = build_envelope("bim", raw)

    async with factory() as session:
        # Bootstrap default settings then flip classifier to din276 so
        # the classifier boost has a non-"none" hint to match against.
        from app.modules.projects.service import get_or_create_match_settings

        settings = await get_or_create_match_settings(session, project_id)
        settings.classifier = "din276"
        settings.target_language = "de"
        await session.commit()

        request = MatchRequest(envelope=envelope, project_id=project_id, top_k=5)
        response = await rank(request, db=session)

    assert response.candidates, "expected at least one ranked candidate"
    top = response.candidates[0]
    # Top candidate is the exact-classifier match.
    assert top.code == "330.10.020"
    # The classifier full-match boost actually fired.
    assert "classifier_match" in top.boosts_applied
    # The unit_match boost should have fired (m2 == m2).
    assert "unit_match" in top.boosts_applied
    # vector_score was preserved separately from final score.
    assert top.vector_score == pytest.approx(0.82)
    assert top.score >= top.vector_score


@pytest.mark.asyncio
async def test_translation_skipped_when_languages_match(
    temp_engine_and_factory, project_id, patch_vector_search,
) -> None:
    """No translation fires when source_lang == target_language."""
    _engine, factory, _tmp = temp_engine_and_factory

    envelope = ElementEnvelope(
        source="bim",
        source_lang="en",  # default target_language is "en"
        category="wall",
        description="Reinforced concrete wall",
    )

    async with factory() as session:
        request = MatchRequest(envelope=envelope, project_id=project_id, top_k=3)
        response = await rank(request, db=session)

    # ``translation_used`` is None when the cascade didn't run.
    assert response.translation_used is None


@pytest.mark.asyncio
async def test_auto_link_only_when_threshold_and_enabled(
    temp_engine_and_factory, project_id, patch_vector_search,
) -> None:
    """Auto-link populates only when both gates pass."""
    _engine, factory, _tmp = temp_engine_and_factory

    # Boost the best hit's vector score so the boosted final clears 0.85.
    patch_vector_search["hits"][0]["score"] = 0.95

    envelope = ElementEnvelope(
        source="bim",
        source_lang="en",
        category="wall",
        description="Reinforced concrete wall, C30/37",
        classifier_hint={"din276": "330.10.020"},
    )

    # Default settings: auto_link_enabled=False — auto_linked must be None.
    async with factory() as session:
        # Bootstrap settings + enable classifier so the boost stack
        # actually pushes the top hit above 0.85.
        from app.modules.projects.service import get_or_create_match_settings

        settings = await get_or_create_match_settings(session, project_id)
        settings.classifier = "din276"
        settings.target_language = "en"
        settings.auto_link_enabled = False
        settings.auto_link_threshold = 0.85
        await session.commit()

        request = MatchRequest(envelope=envelope, project_id=project_id, top_k=3)
        response = await rank(request, db=session)
        assert response.auto_linked is None
        assert response.candidates[0].score >= 0.85

        # Flip enabled=True (threshold already 0.85, classifier already set).
        from sqlalchemy import update

        from app.modules.projects.models import MatchProjectSettings

        await session.execute(
            update(MatchProjectSettings)
            .where(MatchProjectSettings.project_id == project_id)
            .values(auto_link_enabled=True),
        )
        await session.commit()

        response2 = await rank(request, db=session)
        assert response2.auto_linked is not None
        assert response2.auto_linked.code == response2.candidates[0].code


@pytest.mark.asyncio
async def test_reranker_off_by_default(
    temp_engine_and_factory, project_id, patch_vector_search, monkeypatch,
) -> None:
    """The LLM reranker only runs when use_reranker=True."""
    _engine, factory, _tmp = temp_engine_and_factory

    rerank_calls: list[int] = []

    async def _spy(*args, **kwargs):
        rerank_calls.append(1)
        # Return inputs unchanged so the rest of the pipeline is sane.
        return args[0] if args else kwargs.get("candidates", []), 0.0

    monkeypatch.setattr(
        "app.core.match_service.reranker_ai.rerank_top_k", _spy,
    )

    envelope = ElementEnvelope(
        source="bim",
        source_lang="en",
        category="wall",
        description="Reinforced concrete wall",
    )

    async with factory() as session:
        # Default — reranker off.
        request = MatchRequest(envelope=envelope, project_id=project_id, top_k=3)
        await rank(request, db=session)
        assert rerank_calls == [], "reranker fired despite use_reranker=False"

        # Opt in — reranker should run.
        request_on = MatchRequest(envelope=envelope, project_id=project_id, top_k=3, use_reranker=True)
        await rank(request_on, db=session)
        assert rerank_calls == [1], "reranker did not fire despite use_reranker=True"


# ── Boost unit tests ──────────────────────────────────────────────────────


def test_classifier_full_match_returns_full_weight() -> None:
    envelope = ElementEnvelope(
        source="bim",
        category="wall",
        description="x",
        classifier_hint={"din276": "330.10.020"},
    )
    candidate = MatchCandidate(code="x", classification={"din276": "330.10.020"})

    class _Settings:
        classifier = "din276"

    deltas = classifier_boost.boost(envelope, candidate, _Settings())
    assert deltas == {"classifier_match": BOOST_WEIGHTS.classifier_full_match}


def test_classifier_group_prefix_match_returns_partial_weight() -> None:
    envelope = ElementEnvelope(
        source="bim",
        category="wall",
        description="x",
        classifier_hint={"din276": "330"},
    )
    candidate = MatchCandidate(code="x", classification={"din276": "330.10.020"})

    class _Settings:
        classifier = "din276"

    deltas = classifier_boost.boost(envelope, candidate, _Settings())
    assert deltas == {"classifier_group_match": BOOST_WEIGHTS.classifier_group_match}


def test_unit_mismatch_applies_penalty() -> None:
    envelope = ElementEnvelope(
        source="bim",
        category="wall",
        description="x",
        unit_hint="m3",
    )
    candidate = MatchCandidate(code="x", unit="m2")

    deltas = unit_boost.boost(envelope, candidate, None)
    assert deltas == {"unit_mismatch": BOOST_WEIGHTS.unit_mismatch_penalty}
    assert deltas["unit_mismatch"] < 0


def test_unit_match_returns_positive_delta() -> None:
    envelope = ElementEnvelope(
        source="bim",
        category="wall",
        description="x",
        unit_hint="m2",
    )
    candidate = MatchCandidate(code="x", unit="m²")  # superscript should fold
    deltas = unit_boost.boost(envelope, candidate, None)
    assert deltas == {"unit_match": BOOST_WEIGHTS.unit_match}


def test_lex_boost_only_fires_above_high_cutoff() -> None:
    envelope = ElementEnvelope(
        source="bim",
        description="reinforced concrete wall C30/37",
    )
    candidate = MatchCandidate(
        code="x",
        description="reinforced concrete wall C30/37 24cm",
    )
    deltas = lex_boost.boost(envelope, candidate, None)
    assert "lex_high" in deltas

    candidate_low = MatchCandidate(code="x", description="brick masonry partition")
    deltas_low = lex_boost.boost(envelope, candidate_low, None)
    assert deltas_low == {}


# ── Source extractor round-trip ───────────────────────────────────────────


def test_bim_extractor_round_trip() -> None:
    raw = {
        "category": "wall",
        "name": "Concrete Wall",
        "properties": {"material": "Concrete C30/37", "fire_rating": "F90"},
        "geometry": {"area_m2": 37.5, "thickness_m": 0.24},
        "classification": {"din276": "330"},
        "language": "en",
    }
    envelope = build_envelope("bim", raw)
    assert envelope.source == "bim"
    assert envelope.category == "wall"
    assert envelope.quantities.get("area_m2") == 37.5
    assert envelope.classifier_hint == {"din276": "330"}
    assert "Concrete C30/37" in envelope.description


def test_pdf_extractor_round_trip() -> None:
    raw = {
        "description": "Wall tiles ceramic 30x60 cm",
        "unit": "m2",
        "quantity": 65.0,
        "language": "en",
    }
    envelope = build_envelope("pdf", raw)
    assert envelope.source == "pdf"
    assert envelope.unit_hint == "m2"
    # ``quantity`` flows to canonical ``count`` (since unit is m2 it's
    # mapped to area below).
    assert envelope.quantities.get("area_m2") == 65.0


def test_dwg_extractor_round_trip() -> None:
    raw = {
        "description": "Drywall partition, 12.5 mm gypsum",
        "layer": "A-WALL-PRTN",
        "language": "en",
    }
    envelope = build_envelope("dwg", raw)
    assert envelope.source == "dwg"
    assert envelope.category == "wall"  # derived from layer
    assert envelope.properties.get("layer") == "A-WALL-PRTN"


def test_photo_extractor_round_trip() -> None:
    raw = {
        "description": "Cast-in-place concrete column visible",
        "estimated_area_m2": 0.0,
        "estimated_quantity": 1,
        "estimated_unit": "pcs",
        "cv_confidence": 0.78,
        "language": "en",
    }
    envelope = build_envelope("photo", raw)
    assert envelope.source == "photo"
    assert envelope.unit_hint == "pcs"
    assert envelope.quantities.get("quantity") == 1
    assert envelope.properties.get("cv_confidence") == 0.78


def test_unknown_source_raises() -> None:
    with pytest.raises(ValueError):
        build_envelope("ifc", {})


# ── Eval-harness contract ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_match_element_returns_dicts_with_code_and_unit_rate(
    temp_engine_and_factory, project_id, patch_vector_search,
) -> None:
    """Eval contract: ``async match_element(element_info, top_k) -> list[dict]``."""
    _engine, factory, _tmp = temp_engine_and_factory
    async with factory() as session:
        results = await match_element(
            {
                "source": "bim",
                "category": "wall",
                "material": "Concrete C30/37",
                "thickness_m": 0.24,
                "language": "en",
            },
            top_k=3,
            project_id=project_id,
            db=session,
        )
    assert isinstance(results, list)
    assert results, "expected at least one result"
    for entry in results:
        assert "code" in entry
        assert "unit_rate" in entry


# ── Feedback loop ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_feedback_writes_audit_entry(
    temp_engine_and_factory, project_id,
) -> None:
    """Feedback persists an AuditEntry with kind=match_feedback."""
    _engine, factory, _tmp = temp_engine_and_factory

    envelope = ElementEnvelope(
        source="bim",
        source_lang="en",
        category="wall",
        description="Concrete wall",
    )
    accepted = MatchCandidate(code="330.10.020", score=0.91)
    rejected = [MatchCandidate(code="331.20.010", score=0.62)]

    async with factory() as session:
        await record_feedback(
            db=session,
            project_id=project_id,
            element_envelope=envelope,
            accepted_candidate=accepted,
            rejected_candidates=rejected,
            user_chose_code=None,
        )
        await session.commit()

        from sqlalchemy import select

        from app.core.audit import AuditEntry

        rows = (
            await session.execute(
                select(AuditEntry).where(AuditEntry.action == "match_feedback")
            )
        ).scalars().all()
        assert len(rows) == 1
        details = rows[0].details
        assert details["accepted"]["code"] == "330.10.020"
        assert details["rejected"][0]["code"] == "331.20.010"
        assert details["envelope"]["category"] == "wall"


# ── match_envelope direct entrypoint ─────────────────────────────────────


@pytest.mark.asyncio
async def test_match_envelope_direct_entrypoint(
    temp_engine_and_factory, project_id, patch_vector_search,
) -> None:
    _engine, factory, _tmp = temp_engine_and_factory
    envelope = ElementEnvelope(
        source="bim",
        source_lang="en",
        category="wall",
        description="Concrete wall",
        classifier_hint={"din276": "330.10.020"},
    )
    async with factory() as session:
        response = await match_envelope(
            envelope, project_id=project_id, top_k=3, db=session,
        )
    assert response.candidates
    assert response.took_ms >= 0
