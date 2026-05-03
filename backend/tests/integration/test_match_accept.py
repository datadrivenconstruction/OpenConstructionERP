# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for the consolidated ``POST /api/v1/match/accept`` flow.

Phase 4 of the v2.8.0 vector match feature wires the ``Accept`` button on
``MatchSuggestionsPanel`` to a single backend endpoint that creates /
updates a BOQ position with the matched CWICR cost item, optionally
links the BIM element, and records feedback into the audit log.

Tests are hermetic: temp SQLite per test (per ``feedback_test_isolation.md``),
no real LanceDB / LLM / network. They drive
``app.modules.match.service.accept_match`` directly so we exercise the
business logic without spinning up a full ASGI app — the router is a
trivial pass-through that's covered separately by the existing match
service tests.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Shared fixtures ──────────────────────────────────────────────────────


def _register_minimal_models() -> None:
    """Pull every module that owns a Base.metadata table the tests touch."""
    import app.core.audit  # noqa: F401  — AuditEntry
    import app.modules.boq.models  # noqa: F401
    import app.modules.costs.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "match_accept.db"
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
async def project_and_boq(temp_engine_and_factory):
    """Create a real Project + BOQ + owner user.

    Returns ``(project_id, boq_id, owner_id_str)``. The owner user is
    used as the acting caller in every happy-path test so
    ``_verify_project_access`` short-circuits.
    """
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"accept-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Accept Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Accept Test Project",
        owner_id=user.id,
        region="DACH",
        status="active",
    )
    boq = BOQ(
        id=uuid.uuid4(),
        project_id=project.id,
        name="Phase 1",
        description="",
        status="draft",
        metadata_={},
    )
    async with factory() as session:
        session.add(user)
        await session.flush()
        session.add(project)
        await session.flush()
        session.add(boq)
        await session.commit()
    return project.id, boq.id, str(user.id)


def _make_envelope(
    *,
    quantities: dict[str, float] | None = None,
    description: str = "Reinforced concrete wall, 240mm",
    category: str = "wall",
) -> Any:
    """Build a real ElementEnvelope for the accept call.

    Distinguishes ``None`` (caller wants the default 37.5 m² envelope)
    from ``{}`` (caller wants an empty quantities map for fallback tests).
    """
    from app.core.match_service import ElementEnvelope

    if quantities is None:
        resolved: dict[str, float] = {"area_m2": 37.5}
    else:
        resolved = quantities

    return ElementEnvelope(
        source="bim",
        source_lang="en",
        category=category,
        description=description,
        properties={},
        quantities=resolved,
        unit_hint=None,
        classifier_hint=None,
    )


def _make_candidate(
    *,
    code: str = "330.10.020",
    description: str = "Stahlbetonwand C30/37, 24cm",
    unit: str = "m2",
    unit_rate: float = 145.0,
    score: float = 0.84,
    confidence_band: str = "high",
) -> Any:
    from app.core.match_service import MatchCandidate

    return MatchCandidate(
        code=code,
        description=description,
        unit=unit,
        unit_rate=unit_rate,
        currency="EUR",
        score=score,
        vector_score=score - 0.05,
        boosts_applied={"classifier_match": 0.05, "unit_match": 0.0},
        confidence_band=confidence_band,
        region_code="DE",
        source="cwicr",
        language="de",
        classification={"din276": "330.10.020"},
        reasoning=None,
    )


# ── Happy paths ──────────────────────────────────────────────────────────


class TestAcceptMatchHappyPath:
    @pytest.mark.asyncio
    async def test_creates_new_boq_position_with_matched_cost_item(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id=None,
            )
            await session.commit()

        assert result["created"] is True
        assert result["cost_link_created"] is True
        assert result["bim_link_created"] is False
        assert result["position_ordinal"].startswith("AI-")

        # Position row carries the match metadata trail.
        from app.modules.boq.models import Position

        async with factory() as session:
            pos = await session.get(Position, result["position_id"])
            assert pos is not None
            assert pos.source == "ai_match"
            assert pos.unit == "m2"
            assert float(pos.unit_rate) == 145.0
            assert float(pos.quantity) == 37.5  # area_m2 from envelope
            meta = pos.metadata_
            assert meta["cost_item_code"] == "330.10.020"
            assert meta["match_confidence_band"] == "high"
            assert meta["match_score"] == pytest.approx(0.84)
            assert meta["match_vector_score"] == pytest.approx(0.79)
            assert "classifier_match" in meta["match_boosts_applied"]
            assert meta["matched_at"]
            assert meta["matched_by_user_id"] == user_id

    @pytest.mark.asyncio
    async def test_audit_entry_written(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[_make_candidate(code="ALT-1", score=0.4)],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id=None,
            )
            await session.commit()

        # The audit row should be present with action="match_feedback".
        from sqlalchemy import select

        from app.core.audit import AuditEntry

        async with factory() as session:
            entries = (
                await session.execute(
                    select(AuditEntry).where(
                        AuditEntry.action == "match_feedback",
                        AuditEntry.entity_id == str(project_id),
                    ),
                )
            ).scalars().all()
            assert len(entries) == 1
            row = entries[0]
            assert row.details["accepted"]["code"] == "330.10.020"
            assert [r["code"] for r in row.details["rejected"]] == ["ALT-1"]

    @pytest.mark.asyncio
    async def test_updates_existing_position_when_id_provided(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        # Pre-create a manual position the accept call will overwrite.
        from app.modules.boq.models import Position

        existing_id = uuid.uuid4()
        async with factory() as session:
            pos = Position(
                id=existing_id,
                boq_id=boq_id,
                ordinal="MAN-001",
                description="placeholder",
                unit="m2",
                quantity="10",
                unit_rate="0",
                total="0",
                classification={},
                source="manual",
                cad_element_ids=[],
                metadata_={"existing_key": "preserved"},
                sort_order=1,
            )
            session.add(pos)
            await session.commit()

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(unit_rate=200.0),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=existing_id,
                quantity_override=None,
                bim_element_id=None,
            )
            await session.commit()

        assert result["created"] is False
        assert result["position_id"] == existing_id

        async with factory() as session:
            updated = await session.get(Position, existing_id)
            assert updated is not None
            assert updated.source == "ai_match"
            assert float(updated.unit_rate) == 200.0
            # Pre-existing metadata key survived the merge.
            assert updated.metadata_["existing_key"] == "preserved"
            assert updated.metadata_["cost_item_code"] == "330.10.020"

    @pytest.mark.asyncio
    async def test_quantity_override_wins_over_envelope(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(quantities={"area_m2": 37.5}),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=999.0,
                bim_element_id=None,
            )
            await session.commit()

        from app.modules.boq.models import Position

        async with factory() as session:
            pos = await session.get(Position, result["position_id"])
            assert pos is not None
            assert float(pos.quantity) == 999.0


class TestQuantityInferenceOrder:
    """``area_m2`` > ``volume_m3`` > ``length_m`` > 1.0 fallback."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("quantities", "expected"),
        [
            ({"area_m2": 37.5}, 37.5),
            ({"volume_m3": 9.0}, 9.0),
            ({"length_m": 12.5}, 12.5),
            ({}, 1.0),
            # Multiple present — area wins.
            ({"area_m2": 37.5, "volume_m3": 9.0, "length_m": 12.5}, 37.5),
            # Area absent but volume + length present — volume wins.
            ({"volume_m3": 9.0, "length_m": 12.5}, 9.0),
            # Zero / negative are skipped — fall through to next.
            ({"area_m2": 0, "volume_m3": 9.0}, 9.0),
        ],
    )
    async def test_quantity_inference(
        self, temp_engine_and_factory, project_and_boq, quantities, expected,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(quantities=quantities),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id=None,
            )
            await session.commit()

        from app.modules.boq.models import Position

        async with factory() as session:
            pos = await session.get(Position, result["position_id"])
            assert pos is not None
            assert float(pos.quantity) == expected


# ── BIM link path ────────────────────────────────────────────────────────


class TestBIMLink:
    @pytest.mark.asyncio
    async def test_bim_element_link_created_when_element_exists(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        # Bring the bim_hub models into Base.metadata so the link table
        # is created; create a minimal BIMModel + BIMElement.
        import app.modules.bim_hub.models  # noqa: F401
        from app.database import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        from app.modules.bim_hub.models import BIMElement, BIMModel

        model_id = uuid.uuid4()
        elem_id = uuid.uuid4()
        async with factory() as session:
            session.add(
                BIMModel(
                    id=model_id,
                    project_id=project_id,
                    name="Model A",
                    discipline="arch",
                    status="ready",
                    element_count=1,
                    metadata_={},
                ),
            )
            await session.flush()
            session.add(
                BIMElement(
                    id=elem_id,
                    model_id=model_id,
                    stable_id=str(elem_id),
                    element_type="wall",
                    name="W-01",
                    properties={},
                    quantities={},
                    metadata_={},
                ),
            )
            await session.commit()

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id=str(elem_id),
            )
            await session.commit()

        assert result["bim_link_created"] is True

        # The link row exists.
        from sqlalchemy import select

        from app.modules.bim_hub.models import BOQElementLink

        async with factory() as session:
            links = (
                await session.execute(
                    select(BOQElementLink).where(
                        BOQElementLink.boq_position_id == result["position_id"],
                    ),
                )
            ).scalars().all()
            assert len(links) == 1
            assert str(links[0].bim_element_id) == str(elem_id)

    @pytest.mark.asyncio
    async def test_bim_link_skipped_for_unknown_element_id(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        """Position still created; BIM link best-effort returns False."""
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id="not-a-uuid",
            )
            await session.commit()

        # Position created; BIM link not.
        assert result["created"] is True
        assert result["bim_link_created"] is False


# ── Error paths ──────────────────────────────────────────────────────────


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_permission_denied_for_non_member(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, _user_id = project_and_boq

        # Use a different acting user (not the project owner, not admin).
        other_user_id = str(uuid.uuid4())

        from app.modules.match.service import accept_match

        async with factory() as session:
            with pytest.raises(HTTPException) as ctx:
                await accept_match(
                    db=session,
                    project_id=project_id,
                    user_id=other_user_id,
                    user_role="",
                    element_envelope=_make_envelope(),
                    accepted_candidate=_make_candidate(),
                    rejected_candidates=[],
                    boq_id=boq_id,
                    parent_section_id=None,
                    existing_position_id=None,
                    quantity_override=None,
                    bim_element_id=None,
                )
            assert ctx.value.status_code == 403

    @pytest.mark.asyncio
    async def test_boq_id_mismatch_with_project(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, _boq_id, user_id = project_and_boq

        # Create a second project + BOQ; the second BOQ doesn't belong
        # to the first project.
        from app.modules.boq.models import BOQ
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        other_user = User(
            id=uuid.uuid4(),
            email=f"other-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x" * 60,
            full_name="Other",
            role="estimator",
            locale="en",
            is_active=True,
            metadata_={},
        )
        other_project = Project(
            id=uuid.uuid4(),
            name="Other",
            owner_id=other_user.id,
            region="DACH",
            status="active",
        )
        other_boq = BOQ(
            id=uuid.uuid4(),
            project_id=other_project.id,
            name="X",
            description="",
            status="draft",
            metadata_={},
        )
        async with factory() as session:
            session.add(other_user)
            await session.flush()
            session.add(other_project)
            await session.flush()
            session.add(other_boq)
            await session.commit()

        from app.modules.match.service import accept_match

        async with factory() as session:
            with pytest.raises(HTTPException) as ctx:
                await accept_match(
                    db=session,
                    project_id=project_id,
                    user_id=user_id,
                    user_role="",
                    element_envelope=_make_envelope(),
                    accepted_candidate=_make_candidate(),
                    rejected_candidates=[],
                    boq_id=other_boq.id,
                    parent_section_id=None,
                    existing_position_id=None,
                    quantity_override=None,
                    bim_element_id=None,
                )
            assert ctx.value.status_code == 400

    @pytest.mark.asyncio
    async def test_existing_position_id_not_found(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            with pytest.raises(HTTPException) as ctx:
                await accept_match(
                    db=session,
                    project_id=project_id,
                    user_id=user_id,
                    user_role="",
                    element_envelope=_make_envelope(),
                    accepted_candidate=_make_candidate(),
                    rejected_candidates=[],
                    boq_id=boq_id,
                    parent_section_id=None,
                    existing_position_id=uuid.uuid4(),
                    quantity_override=None,
                    bim_element_id=None,
                )
            assert ctx.value.status_code == 404


class TestCatalogIndependence:
    """Accept must succeed even when the candidate's CWICR ``code``
    has no matching ``CostItem`` row — the matcher's catalog and the
    project's BOQ catalog can be different shipments. We persist the
    candidate's data verbatim, no FK gating."""

    @pytest.mark.asyncio
    async def test_accept_succeeds_for_unknown_catalog_code(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, user_id = project_and_boq

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=user_id,
                user_role="",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(code="NOT-IN-CATALOG-9999"),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id=None,
            )
            await session.commit()

        assert result["created"] is True

        from app.modules.boq.models import Position

        async with factory() as session:
            pos = await session.get(Position, result["position_id"])
            assert pos is not None
            assert pos.metadata_["cost_item_code"] == "NOT-IN-CATALOG-9999"


class TestAdminRoleBypass:
    """Admin role bypasses owner check — useful for cross-project tooling."""

    @pytest.mark.asyncio
    async def test_admin_can_accept_against_other_owner(
        self, temp_engine_and_factory, project_and_boq,
    ) -> None:
        _engine, factory, _tmp = temp_engine_and_factory
        project_id, boq_id, _owner_id = project_and_boq
        admin_id = str(uuid.uuid4())

        from app.modules.match.service import accept_match

        async with factory() as session:
            result = await accept_match(
                db=session,
                project_id=project_id,
                user_id=admin_id,
                user_role="admin",
                element_envelope=_make_envelope(),
                accepted_candidate=_make_candidate(),
                rejected_candidates=[],
                boq_id=boq_id,
                parent_section_id=None,
                existing_position_id=None,
                quantity_override=None,
                bim_element_id=None,
            )
            await session.commit()

        assert result["created"] is True
