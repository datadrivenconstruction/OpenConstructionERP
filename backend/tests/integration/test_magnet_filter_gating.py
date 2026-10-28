# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration test: magnet_filter env-var gating end-to-end.

Drives the ``rank()`` entrypoint with a stub Qdrant adapter (so the
real BGE encoder + Qdrant don't need to be running) and verifies:

* With ``OE_MATCH_MAGNET_FILTER`` UNSET / OFF, the magnet candidate
  survives into the final response.
* With ``OE_MATCH_MAGNET_FILTER=1``, the magnet candidate is removed
  before the candidates list is returned.

The fixtures use the same pattern as ``test_match_service.py`` - a
throwaway PostgreSQL database + monkeypatched vector adapter - so we
never touch production data and the test stays fast.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from app.core.match_service import (
    ElementEnvelope,
    MatchRequest,
    rank,
)
from tests._pg import isolated_engine


@pytest.fixture(autouse=True)
def _bypass_catalog_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(*_args, **_kwargs):
        return "ok", 1, 1

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant._resolve_catalog_status",
        _ok,
        raising=True,
    )


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Per-test throwaway PostgreSQL database, cloned from the schema-loaded template.

    ``rank()`` opens its own work via the handed-in session and writes a row to
    ``oe_match_elements_search_log`` after returning the response, and the test
    seeds the project through a separate session, so the two must see each
    other's commits - hence a real throwaway database.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield engine, factory


@pytest_asyncio.fixture
async def project_id(temp_engine_and_factory) -> uuid.UUID:
    _engine, factory = temp_engine_and_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"magnet-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Magnet Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    project = Project(
        id=uuid.uuid4(),
        name="Magnet Filter Test",
        owner_id=user.id,
        region="US",
        status="active",
    )
    async with factory() as session:
        session.add(user)
        await session.flush()
        session.add(project)
        await session.commit()
    return project.id


@pytest.fixture
def patch_vector_search_with_magnet(monkeypatch: pytest.MonkeyPatch):
    """Stub the Qdrant adapter to return one magnet + one legitimate hit.

    The magnet is a verbatim copy of the worst offender from the bench
    (``KAME_KAPU_KAMEDX_KAME``, mf=26, IfcElectricDistributionBoard,
    Count) — irrelevant to a concrete wall query but consistently
    pulled into the top-10 by the cross-encoder.
    """
    from app.modules.costs.qdrant_adapter import QdrantHit

    def _hits():
        return [
            QdrantHit(
                rate_code="KAME_KAPU_KAMEDX_KAME",  # the magnet
                country="US",
                score=0.50,
                payload={
                    "rate_code": "KAME_KAPU_KAMEDX_KAME",
                    "country": "US",
                    "masterformat_division": "26 20 00",
                    "ifc_class": "IfcElectricDistributionBoard",
                    "unit_type": "Count",
                    "rate_unit": "pcs",
                    "is_abstract": False,
                },
            ),
            QdrantHit(
                rate_code="VALID_CONCRETE_WALL",  # legitimate concrete wall
                country="US",
                score=0.40,
                payload={
                    "rate_code": "VALID_CONCRETE_WALL",
                    "country": "US",
                    "masterformat_division": "03 30 00",
                    "ifc_class": "IfcWall",
                    "unit_type": "Area",
                    "rate_unit": "m2",
                    "is_abstract": False,
                },
            ),
        ]

    async def _stub_search_with_fallback(*, country, limit, **_kwargs):  # noqa: ANN001
        return _hits()[:limit], 0

    async def _stub_lookup_full_rows(*_args, **_kwargs):
        return [
            {"rate_code": "KAME_KAPU_KAMEDX_KAME", "rate_unit": "pcs"},
            {"rate_code": "VALID_CONCRETE_WALL", "rate_unit": "m2"},
        ]

    async def _stub_substitute_abstract_parents(*, country, core_query, hits, **_kwargs):  # noqa: ANN001
        return hits

    def _noop_bge_rerank(candidates, envelope, **_kwargs):  # noqa: ANN001
        return list(candidates)

    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.qdrant_search_with_fallback",
        _stub_search_with_fallback,
    )
    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.lookup_full_rows",
        _stub_lookup_full_rows,
    )
    monkeypatch.setattr(
        "app.core.match_service.ranker_qdrant.substitute_abstract_parents",
        _stub_substitute_abstract_parents,
    )
    monkeypatch.setattr(
        "app.core.match_service.reranker_bge.rerank",
        _noop_bge_rerank,
    )


def _concrete_wall_envelope() -> ElementEnvelope:
    """High-conf envelope that should drop the magnet when filter is ON."""
    return ElementEnvelope(
        source="bim",
        category="wall",
        description="Cast-in-place reinforced concrete wall, 240 mm thick, C30/37",
        properties={"material": "concrete C30/37", "thickness_mm": 240},
        quantities={"area_m2": 37.5},
        unit_hint="m2",
        ifc_class="IfcWall",
        material_class="concrete",
        nominal_size_mm=240,
        is_structural=True,
        is_loadbearing=True,
        source_lang="en",
    )


@pytest.mark.asyncio
async def test_magnet_filter_disabled_keeps_magnet(
    temp_engine_and_factory,
    project_id,
    patch_vector_search_with_magnet,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without OE_MATCH_MAGNET_FILTER=1, the magnet survives the pipeline."""
    monkeypatch.delenv("OE_MATCH_MAGNET_FILTER", raising=False)
    _engine, factory = temp_engine_and_factory

    envelope = _concrete_wall_envelope()
    async with factory() as session:
        request = MatchRequest(envelope=envelope, project_id=project_id, top_k=5)
        response = await rank(request, db=session)

    codes = [c.code for c in response.candidates]
    # Both hits should be present — the filter is OFF.
    assert "KAME_KAPU_KAMEDX_KAME" in codes
    assert "VALID_CONCRETE_WALL" in codes


@pytest.mark.asyncio
async def test_magnet_filter_enabled_drops_magnet(
    temp_engine_and_factory,
    project_id,
    patch_vector_search_with_magnet,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With OE_MATCH_MAGNET_FILTER=1, the magnet is suppressed end-to-end."""
    monkeypatch.setenv("OE_MATCH_MAGNET_FILTER", "1")
    _engine, factory = temp_engine_and_factory

    envelope = _concrete_wall_envelope()
    async with factory() as session:
        request = MatchRequest(envelope=envelope, project_id=project_id, top_k=5)
        response = await rank(request, db=session)

    codes = [c.code for c in response.candidates]
    # The magnet must NOT be in the final candidates.
    assert "KAME_KAPU_KAMEDX_KAME" not in codes
    # The legitimate candidate must still be present.
    assert "VALID_CONCRETE_WALL" in codes
