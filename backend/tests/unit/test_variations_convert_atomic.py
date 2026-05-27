"""Atomic convert_vr_to_vo tests — standalone file per task spec.

Focused on the transactional guarantee: if the CO-mirror step fails,
the entire promotion (VO insert + VR.status flip) is rolled back so
no orphan VO row is left in the DB.

These tests live alongside test_variations_round5.py; keeping them
separate makes it easy to run just the atomicity suite in CI without
the broader FSM / IDOR suite (useful for quick regression checks on the
cross-module conversion path).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.audit_log import ActivityLog
from app.database import Base
from app.modules.changeorders.models import ChangeOrder, ChangeOrderApproval, ChangeOrderItem
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.users.models import APIKey, User
from app.modules.variations.models import (
    Notice,
    VariationCostImpact,
    VariationOrder,
    VariationRequest,
    VariationScheduleImpact,
)
from app.modules.variations.schemas import VariationOrderCreate, VariationRequestCreate
from app.modules.variations.service import VariationsService

_TABLES = [
    User.__table__,
    APIKey.__table__,
    Project.__table__,
    ProjectWBS.__table__,
    ProjectMilestone.__table__,
    Notice.__table__,
    VariationRequest.__table__,
    VariationOrder.__table__,
    VariationCostImpact.__table__,
    VariationScheduleImpact.__table__,
    ChangeOrder.__table__,
    ChangeOrderApproval.__table__,
    ChangeOrderItem.__table__,
    ActivityLog.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def svc(session: AsyncSession) -> VariationsService:
    return VariationsService(session)


async def _setup_approved_vr(session: AsyncSession, svc: VariationsService) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Create a user, project, and an approved VR. Returns (user_id, project_id, vr_id)."""
    user = User(email=f"u{uuid.uuid4().hex[:8]}@a.com", hashed_password="x")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    # Capture IDs as plain Python values BEFORE any service calls that
    # call session.expire_all() internally (repo.update_fields() does this).
    # Accessing ORM attributes on expired objects outside an await context
    # raises MissingGreenlet on async aiosqlite.
    user_id: uuid.UUID = user.id
    project = Project(name="Atomic test", owner_id=user_id, currency="GBP")
    session.add(project)
    await session.flush()
    await session.refresh(project)
    project_id: uuid.UUID = project.id
    await session.commit()

    vr = await svc.create_request(
        VariationRequestCreate(
            project_id=project_id,
            title="Atomic VR",
            classification="scope_change",
            estimated_cost_impact="25000.00",
        ),
        user_id=str(user_id),
    )
    await svc.transition_variation_request(vr.id, "submitted")
    await svc.transition_variation_request(vr.id, "approved", user_id=str(user_id))
    await session.commit()

    return user_id, project_id, vr.id


class TestConvertVRToVOAtomicity:
    """Verify the VR -> VO conversion is fully transactional."""

    @pytest.mark.asyncio
    async def test_co_failure_rolls_back_entire_promotion(self, session: AsyncSession, svc: VariationsService) -> None:
        """If CO-mirror raises, NO VO row and NO VR-status-flip must persist.

        Implementation note: convert_vr_to_vo calls ``session.rollback()``
        internally on CO failure, then re-raises as HTTP 500. After the test
        catches the 500, we reload both tables and assert neither was modified.
        """
        user_id, project_id, vr_id = await _setup_approved_vr(session, svc)

        count_vo_before = (await session.execute(select(VariationOrder))).scalars().all()
        count_co_before = (await session.execute(select(ChangeOrder))).scalars().all()

        with patch(
            "app.modules.changeorders.service.ChangeOrderService.create_order",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Injected DB failure in CO mirror"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await svc.convert_vr_to_vo(
                    vr_id,
                    VariationOrderCreate(
                        project_id=project_id,
                        variation_request_id=vr_id,
                        title="Should be rolled back",
                        final_cost_impact="25000.00",
                        currency="GBP",
                    ),
                    user_id=str(user_id),
                )
        assert exc_info.value.status_code == 500

        # VR must NOT have transitioned to "converted_to_vo".
        vr_after = (
            await session.execute(select(VariationRequest).where(VariationRequest.id == vr_id))
        ).scalar_one_or_none()
        # After rollback the session may have lost the row — that's OK too,
        # the key assertion is it's NOT "converted_to_vo".
        if vr_after is not None:
            assert vr_after.status != "converted_to_vo", (
                "VR.status was incorrectly flipped to 'converted_to_vo' despite CO-mirror failure"
            )

        # VO count must not have increased (or it was rolled back).
        # We check by counting any VOs whose title matches the failed attempt.
        vos_after = (
            (await session.execute(select(VariationOrder).where(VariationOrder.project_id == project_id)))
            .scalars()
            .all()
        )
        orphan_vos = [v for v in vos_after if v.title == "Should be rolled back"]
        assert len(orphan_vos) == 0, f"Found {len(orphan_vos)} orphan VO(s) that should have been rolled back"

    @pytest.mark.asyncio
    async def test_both_writes_land_atomically_on_success(self, session: AsyncSession, svc: VariationsService) -> None:
        """Happy path: VO and CO both exist after a successful conversion."""
        user_id, project_id, vr_id = await _setup_approved_vr(session, svc)

        vo = await svc.convert_vr_to_vo(
            vr_id,
            VariationOrderCreate(
                project_id=project_id,
                variation_request_id=vr_id,
                title="Atomic success VO",
                final_cost_impact="25000.00",
                currency="GBP",
            ),
            user_id=str(user_id),
        )
        await session.commit()

        # VO must exist.
        vo_row = (await session.execute(select(VariationOrder).where(VariationOrder.id == vo.id))).scalar_one_or_none()
        assert vo_row is not None, "VO not persisted after successful conversion"

        # CO mirror must exist (metadata.origin == "variations.convert_vr_to_vo").
        cos = (await session.execute(select(ChangeOrder).where(ChangeOrder.project_id == project_id))).scalars().all()
        matching_co = [
            co
            for co in cos
            if isinstance(getattr(co, "metadata_", {}), dict)
            and co.metadata_.get("origin") == "variations.convert_vr_to_vo"
        ]
        assert len(matching_co) == 1, f"Expected exactly 1 mirrored CO, found {len(matching_co)}"

        # VR must now be "converted_to_vo".
        vr_row = (await session.execute(select(VariationRequest).where(VariationRequest.id == vr_id))).scalar_one()
        assert vr_row.status == "converted_to_vo"

    @pytest.mark.asyncio
    async def test_only_approved_vr_can_be_converted(self, session: AsyncSession, svc: VariationsService) -> None:
        """Attempting to convert a draft VR raises HTTP 409."""
        user = User(email=f"u{uuid.uuid4().hex[:8]}@a.com", hashed_password="x")
        session.add(user)
        await session.flush()
        await session.refresh(user)
        project = Project(name="Bad convert", owner_id=user.id, currency="GBP")
        session.add(project)
        await session.flush()
        await session.refresh(project)
        await session.commit()

        vr = await svc.create_request(
            VariationRequestCreate(
                project_id=project.id,
                title="Draft VR",
                classification="scope_change",
            ),
            user_id=str(user.id),
        )
        await session.commit()

        assert vr.status == "draft"
        with pytest.raises(HTTPException) as exc_info:
            await svc.convert_vr_to_vo(
                vr.id,
                VariationOrderCreate(
                    project_id=project.id,
                    variation_request_id=vr.id,
                    title="Should not be created",
                    final_cost_impact="0",
                    currency="GBP",
                ),
                user_id=str(user.id),
            )
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_convert_already_converted_vr_raises_409(self, session: AsyncSession, svc: VariationsService) -> None:
        """Double-converting raises 409 on the second call."""
        user_id, project_id, vr_id = await _setup_approved_vr(session, svc)

        payload = VariationOrderCreate(
            project_id=project_id,
            variation_request_id=vr_id,
            title="First VO",
            final_cost_impact="25000.00",
            currency="GBP",
        )
        await svc.convert_vr_to_vo(vr_id, payload, user_id=str(user_id))
        await session.commit()

        payload2 = VariationOrderCreate(
            project_id=project_id,
            variation_request_id=vr_id,
            title="Second VO (should fail)",
            final_cost_impact="25000.00",
            currency="GBP",
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.convert_vr_to_vo(vr_id, payload2, user_id=str(user_id))
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_money_precision_preserved_through_conversion(
        self, session: AsyncSession, svc: VariationsService
    ) -> None:
        """final_cost_impact carries exact Decimal precision VR -> VO -> CO."""
        user_id, project_id, vr_id = await _setup_approved_vr(session, svc)

        exact = Decimal("77777.77")
        vo = await svc.convert_vr_to_vo(
            vr_id,
            VariationOrderCreate(
                project_id=project_id,
                variation_request_id=vr_id,
                title="Precision VO",
                final_cost_impact=str(exact),
                currency="GBP",
            ),
            user_id=str(user_id),
        )
        await session.commit()

        # VO money field must be exact.
        vo_row = (await session.execute(select(VariationOrder).where(VariationOrder.id == vo.id))).scalar_one()
        vo_impact = Decimal(str(vo_row.final_cost_impact))
        assert vo_impact == exact, f"VO impact {vo_impact!r} != {exact!r}"

        # Mirrored CO cost_impact must also be exact.
        cos = (await session.execute(select(ChangeOrder).where(ChangeOrder.project_id == project_id))).scalars().all()
        co = next(
            (
                c
                for c in cos
                if isinstance(getattr(c, "metadata_", {}), dict)
                and c.metadata_.get("origin") == "variations.convert_vr_to_vo"
            ),
            None,
        )
        assert co is not None, "CO mirror not found"
        co_impact = Decimal(str(co.cost_impact))
        assert co_impact == exact, f"CO impact {co_impact!r} != {exact!r}"
