# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""DB-backed integration tests for the Schedule Intelligence governance stack.

Exercises the E5.2 locked-figure and E5.3 confidence workflows end-to-end
against a real PostgreSQL database (the session template carries every module's
schema), driving them through the *service* layer so the ORM models,
repositories, guard, and confidence engine are all proven to integrate — not
just the pure units.

FK triggers are disabled for the session (``disable_fks=True``) so we can lock
figures against a synthetic ``project_id`` without standing up the full
projects/users graph; the governance logic under test never depends on those
rows existing.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Import the module's models so its tables are registered in Base.metadata.
import app.modules.schedule_intelligence.models  # noqa: F401
from app.modules.schedule_intelligence import service
from app.modules.schedule_intelligence.enums import ConfidenceBand, LockedFigureType
from app.modules.schedule_intelligence.schemas import (
    ConfidenceConfigUpsert,
    ConfidencePreviewRequest,
    LockFigureRequest,
    VerifyWritesRequest,
)
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


# ─────────────────────────────────────────────────────────────────────────────
# E5.2 — locked figures through the real DB + service + guard
# ─────────────────────────────────────────────────────────────────────────────
async def test_lock_figure_persists_canonical_value_and_hash(
    session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()
    row = await service.lock_figure(
        session,
        project_id,
        LockFigureRequest(
            path="decision.1.impact_days",
            figure_type=LockedFigureType.IMPACT_DAYS,
            value=42,
            reason="director confirmed",
        ),
        uuid.uuid4(),
    )
    assert row.value == "42"  # canonicalised
    assert row.value_hash and len(row.value_hash) == 64  # sha256 hex
    assert row.active is True
    assert row.figure_type == LockedFigureType.IMPACT_DAYS.value


async def test_relock_same_value_is_idempotent(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    req = LockFigureRequest(path="p.impact_days", figure_type=LockedFigureType.IMPACT_DAYS, value=42)
    first = await service.lock_figure(session, project_id, req, None)
    # Numeric-equivalent value → same canonical form → same row, no conflict.
    again = await service.lock_figure(
        session,
        project_id,
        LockFigureRequest(path="p.impact_days", figure_type=LockedFigureType.IMPACT_DAYS, value=42.0),
        None,
    )
    assert first.id == again.id


async def test_relock_different_value_conflicts(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    await service.lock_figure(
        session,
        project_id,
        LockFigureRequest(path="p.impact_days", figure_type=LockedFigureType.IMPACT_DAYS, value=42),
        None,
    )
    with pytest.raises(HTTPException) as exc:
        await service.lock_figure(
            session,
            project_id,
            LockFigureRequest(
                path="p.impact_days",
                figure_type=LockedFigureType.IMPACT_DAYS,
                value=43,
            ),
            None,
        )
    assert exc.value.status_code == 409


async def test_verify_writes_flags_mutation_but_allows_identical(
    session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()
    await service.lock_figure(
        session,
        project_id,
        LockFigureRequest(
            path="decision.7.entitlement_days",
            figure_type=LockedFigureType.ENTITLEMENT_DAYS,
            value=15,
        ),
        None,
    )

    # A mutating write is reported as a violation.
    bad = await service.verify_writes(
        session,
        project_id,
        VerifyWritesRequest(writes={"decision.7.entitlement_days": 20}),
    )
    assert len(bad) == 1
    assert bad[0].path == "decision.7.entitlement_days"
    assert bad[0].locked_value == "15"
    assert bad[0].attempted_value == "20"

    # An identical (numeric-equivalent) write is allowed.
    ok = await service.verify_writes(
        session,
        project_id,
        VerifyWritesRequest(writes={"decision.7.entitlement_days": 15.0}),
    )
    assert ok == []


async def test_unlock_releases_the_guard(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    row = await service.lock_figure(
        session,
        project_id,
        LockFigureRequest(
            path="p.lds_avoided",
            figure_type=LockedFigureType.LDS_AVOIDED,
            value="90000.00",
        ),
        None,
    )
    # Locked → mutation blocked.
    assert await service.verify_writes(session, project_id, VerifyWritesRequest(writes={"p.lds_avoided": "0"}))

    unlocked = await service.unlock_figure(session, project_id, row.id, None)
    assert unlocked.active is False
    assert unlocked.unlocked_at is not None

    # Released → the path is writable again (no violation).
    assert await service.verify_writes(session, project_id, VerifyWritesRequest(writes={"p.lds_avoided": "0"})) == []


async def test_unlock_foreign_project_is_404(session: AsyncSession) -> None:
    row = await service.lock_figure(
        session,
        uuid.uuid4(),
        LockFigureRequest(path="p.impact_days", figure_type=LockedFigureType.IMPACT_DAYS, value=1),
        None,
    )
    with pytest.raises(HTTPException) as exc:
        await service.unlock_figure(session, uuid.uuid4(), row.id, None)
    assert exc.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# E5.3 — confidence config through the real DB
# ─────────────────────────────────────────────────────────────────────────────
async def test_confidence_policy_resolves_default_then_project(
    session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()

    # No row yet → built-in default policy.
    policy, source = await service.resolve_policy(session, project_id)
    assert source == "default"
    assert policy.version is None

    # Upsert a project override → resolves to it, versioned.
    await service.upsert_confidence_config(
        session,
        project_id,
        ConfidenceConfigUpsert(
            description="tighter caps for pilot",
            schedule_quality_caps={"poor": 0.2, "fair": 0.6, "good": 1.0},
        ),
        None,
    )
    policy, source = await service.resolve_policy(session, project_id)
    assert source == "project"
    assert policy.version == 1
    assert policy.schedule_quality_caps["poor"] == 0.2


async def test_confidence_upsert_bumps_version_and_deactivates_prior(
    session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()
    await service.upsert_confidence_config(session, project_id, ConfidenceConfigUpsert(description="v1"), None)
    await service.upsert_confidence_config(session, project_id, ConfidenceConfigUpsert(description="v2"), None)
    policy, source = await service.resolve_policy(session, project_id)
    assert source == "project"
    assert policy.version == 2  # exactly one active row, the newest version


async def test_confidence_preview_applies_project_caps(
    session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()
    await service.upsert_confidence_config(
        session,
        project_id,
        ConfidenceConfigUpsert(schedule_quality_caps={"poor": 0.2}),
        None,
    )
    result = await service.preview_confidence(
        session,
        project_id,
        ConfidencePreviewRequest(base_score=0.95, schedule_quality="poor"),
    )
    assert result.score == 0.2  # capped by the project's poor-quality ceiling
    assert result.band == ConfidenceBand.LOW
    # The cap is recorded, never silent.
    assert any(r["step"] == "cap:schedule_quality" for r in result.rationale)
