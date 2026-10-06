# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Three write paths stop guessing which bill of quantities they act on.

A project may hold any number of bills. Three modules used to answer "which
one" with ``ORDER BY created_at LIMIT 1``: the oldest bill won, the lock was
never consulted, and nothing but a log line recorded the choice. On a project
holding one bill that guess is always right, which is why it survived. On a
project holding two it wrote real money into a bill nobody named.

Every case here comes in both polarities, because the fix is only worth having
if the ordinary project is untouched:

* **positive control** - a project with a single unlocked bill behaves exactly
  as it did before, and the assertion is that the write *happened*, not merely
  that nothing raised. A resolver that returned ``None`` would pass a
  "did not raise" test.
* **negative control** - a project with two unlocked bills gets a refusal the
  caller can see and act on, and nothing is written. A 409 that still wrote
  would be worse than the guess it replaced.

Two further polarities the two-bill matrix cannot reach:

* a project whose only bill is **locked** - the write paths refuse it (they
  used to rewrite approved money), while the read paths still accept it,
  because validating or scheduling from an approved estimate is the normal
  case and not an error;
* **naming the bill** answers the refusal, which is what makes it a question
  rather than a dead end.

Covers ``bim_hub.apply_quantity_maps``, the three
``project_intelligence.actions`` that operate on "the project's main BOQ", and
``match_elements.apply_to_boq``. The shared rule they all now ask lives in
``app.core.boq_target``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


# ════════════════════════════════════════════════════════════════════════
# Fixtures - projects, bills, BIM models, rules, match sessions
# ════════════════════════════════════════════════════════════════════════


async def _mk_project(s: AsyncSession, *, currency: str = "EUR") -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"o-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="O",
    )
    s.add(owner)
    await s.flush()
    project = Project(
        id=uuid.uuid4(),
        name="P",
        description="",
        owner_id=owner.id,
        currency=currency,
    )
    s.add(project)
    await s.flush()
    return project.id


async def _mk_boq(s: AsyncSession, project_id: uuid.UUID, *, name: str, locked: bool = False):
    from app.modules.boq.models import BOQ

    boq = BOQ(
        project_id=project_id,
        name=name,
        description="",
        status="approved" if locked else "draft",
        is_locked=locked,
    )
    s.add(boq)
    await s.flush()
    return boq


async def _mk_position(s: AsyncSession, boq, *, unit_rate: str = "0"):
    from app.modules.boq.models import Position

    pos = Position(
        boq_id=boq.id,
        ordinal="1",
        description="Concrete wall C30/37",
        unit="m3",
        quantity="10",
        unit_rate=unit_rate,
        total="0",
        source="manual",
    )
    s.add(pos)
    await s.flush()
    return pos


async def _count_positions(s: AsyncSession, *boqs) -> int:
    from app.modules.boq.models import Position

    return int(
        (await s.execute(select(func.count(Position.id)).where(Position.boq_id.in_([b.id for b in boqs])))).scalar_one()
    )


async def _mk_model_with_wall(s: AsyncSession, project_id: uuid.UUID):
    from app.modules.bim_hub.models import BIMElement, BIMModel

    model = BIMModel(project_id=project_id, name="m.ifc", status="ready")
    s.add(model)
    await s.flush()
    s.add(
        BIMElement(
            model_id=model.id,
            stable_id=uuid.uuid4().hex,
            element_type="Wall",
            quantities={"area_m2": 12.0},
        )
    )
    await s.flush()
    return model


async def _mk_auto_create_rule(s: AsyncSession, project_id: uuid.UUID, *, name: str = "Auto wall rule"):
    from app.modules.bim_hub.models import BIMQuantityMap

    rule = BIMQuantityMap(
        project_id=project_id,
        name=name,
        quantity_source="area_m2",
        multiplier="1",
        waste_factor_pct="0",
        unit="m2",
        boq_target={"auto_create": True, "unit_rate": "42"},
        is_active=True,
    )
    s.add(rule)
    await s.flush()
    return rule


async def _mk_match_session_with_custom_group(s: AsyncSession, project_id: uuid.UUID):
    """A match session carrying one confirmed, custom-priced group."""
    from app.modules.match_elements.models import MatchGroup, MatchSession

    sess = MatchSession(project_id=project_id, source="bim")
    s.add(sess)
    await s.flush()
    group = MatchGroup(
        session_id=sess.id,
        group_key="ifc_class:IfcWall",
        element_ids=[],
        element_count=3,
        quantities={"volume_m3": 30.0, "area_m2": 120.0, "count": 3.0},
        status="confirmed",
        chosen_method="custom",
        chosen_unit="m3",
        metadata_={"custom_position": {"description": "Rammed earth wall", "unit": "m3", "rate": "145.50"}},
    )
    s.add(group)
    await s.flush()
    return sess


# ════════════════════════════════════════════════════════════════════════
# bim_hub.apply_quantity_maps - auto-created positions
# ════════════════════════════════════════════════════════════════════════


async def _apply_request(session: AsyncSession, model_id: uuid.UUID, **over):
    from app.modules.bim_hub.schemas import QuantityMapApplyRequest
    from app.modules.bim_hub.service import BIMHubService

    request = QuantityMapApplyRequest(**{"model_id": model_id, "dry_run": False, **over})
    if not request.dry_run:
        preview = await BIMHubService(session).apply_quantity_maps(request.model_copy(update={"dry_run": True}))
        request.preview_fingerprint = preview.preview_fingerprint
    return request


@pytest.mark.asyncio
async def test_bim_hub_still_auto_creates_into_a_lone_unlocked_bill(session) -> None:
    """Positive control: one bill, and the position lands in it as before."""
    from app.modules.bim_hub.service import BIMHubService
    from app.modules.boq.models import Position

    project_id = await _mk_project(session)
    boq = await _mk_boq(session, project_id, name="Main bill")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    result = await BIMHubService(session).apply_quantity_maps(await _apply_request(session, model.id))

    assert result.target_boq_ambiguous is False
    assert result.positions_created == 1
    rows = (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].description == "Auto wall rule"
    assert Decimal(rows[0].unit_rate) == Decimal("42")
    assert Decimal(rows[0].quantity) == Decimal("12")


@pytest.mark.asyncio
async def test_bim_hub_refuses_two_unlocked_bills_instead_of_taking_the_oldest(session) -> None:
    """Negative control: the caller sees a 409 and nothing is written."""
    from app.modules.bim_hub.service import BIMHubService

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).apply_quantity_maps(await _apply_request(session, model.id))

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "ambiguous_boq"
    assert "more than one" in exc.value.detail["message"]
    # The refusal names the bills, so the question can be answered where it
    # was asked rather than by looking ids up elsewhere.
    named = {c["name"] for c in exc.value.detail["candidates"]}
    assert named == {"Base estimate", "Variation 04"}
    # A 409 that still wrote would be worse than the guess it replaced.
    assert await _count_positions(session, older, newer) == 0


@pytest.mark.asyncio
async def test_bim_hub_writes_into_the_bill_the_caller_names(session) -> None:
    """The refusal is answerable: name a bill and the apply goes through."""
    from app.modules.bim_hub.service import BIMHubService
    from app.modules.boq.models import Position

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    result = await BIMHubService(session).apply_quantity_maps(
        await _apply_request(session, model.id, target_boq_id=newer.id)
    )

    assert result.positions_created == 1
    assert await _count_positions(session, older) == 0
    rows = (await session.execute(select(Position).where(Position.boq_id == newer.id))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_bim_hub_rejects_a_bill_that_belongs_to_another_project(session) -> None:
    """The picker sends an id; a stale one must not redirect the write.

    The rules page keeps the chosen bill in component state, so a project
    switch can leave a foreign id in hand. It is refused by project, not
    accepted because it happens to be a valid bill somewhere.
    """
    from app.modules.bim_hub.service import BIMHubService
    from app.modules.boq.models import Position

    project_id = await _mk_project(session)
    mine = await _mk_boq(session, project_id, name="Base estimate")
    other_project = await _mk_project(session)
    foreign = await _mk_boq(session, other_project, name="Someone else's estimate")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).apply_quantity_maps(
            await _apply_request(session, model.id, target_boq_id=foreign.id)
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "boq_project_mismatch"
    assert await _count_positions(session, mine) == 0
    written = (await session.execute(select(Position).where(Position.boq_id == foreign.id))).scalars().all()
    assert written == []


@pytest.mark.asyncio
async def test_bim_hub_refuses_to_auto_create_inside_a_locked_bill(session) -> None:
    """A project whose only bill is approved gets a refusal, not a write."""
    from app.modules.bim_hub.service import BIMHubService

    project_id = await _mk_project(session)
    locked = await _mk_boq(session, project_id, name="Approved estimate", locked=True)
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await BIMHubService(session).apply_quantity_maps(await _apply_request(session, model.id))

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "boq_locked"
    # The refusal names the bill that is in the way, not an empty picker.
    assert [c["name"] for c in exc.value.detail["candidates"]] == ["Approved estimate"]
    assert await _count_positions(session, locked) == 0


@pytest.mark.asyncio
async def test_bim_hub_preview_says_it_cannot_name_a_bill(session) -> None:
    """A dry run creates nothing, so it reports the ambiguity instead of 409."""
    from app.modules.bim_hub.service import BIMHubService

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    result = await BIMHubService(session).apply_quantity_maps(await _apply_request(session, model.id, dry_run=True))

    # The preview still shows the matched population - it just refuses to
    # promise a destination it cannot keep.
    assert result.matched_elements == 1
    assert result.target_boq_ambiguous is True
    assert result.positions_created == 0
    assert await _count_positions(session, older, newer) == 0


@pytest.mark.asyncio
async def test_bim_hub_preview_with_a_named_bill_is_answered_not_flagged(session) -> None:
    """The picker answers the preview too, and answering still writes nothing.

    The rules page sends the chosen bill on the dry run as well as on the
    apply, so this pair - dry run plus an explicit bill - is what a user hits
    the moment they touch the picker.
    """
    from app.modules.bim_hub.service import BIMHubService
    from app.modules.boq.models import Position

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    result = await BIMHubService(session).apply_quantity_maps(
        await _apply_request(session, model.id, dry_run=True, target_boq_id=newer.id)
    )

    assert result.target_boq_ambiguous is False
    # Resolving the target is not writing through it: a preview still writes
    # nothing, into the named bill least of all.
    written = (await session.execute(select(Position).where(Position.boq_id.in_([older.id, newer.id])))).scalars().all()
    assert written == []


@pytest.mark.asyncio
async def test_bim_hub_preview_on_a_single_bill_is_not_flagged(session) -> None:
    """Control for the flag itself: the ordinary project never sets it."""
    from app.modules.bim_hub.service import BIMHubService

    project_id = await _mk_project(session)
    await _mk_boq(session, project_id, name="Main bill")
    model = await _mk_model_with_wall(session, project_id)
    await _mk_auto_create_rule(session, project_id)

    result = await BIMHubService(session).apply_quantity_maps(await _apply_request(session, model.id, dry_run=True))

    assert result.target_boq_ambiguous is False
    assert result.matched_elements == 1


@pytest.mark.asyncio
async def test_an_ordinal_that_matches_two_bills_resolves_to_nothing(session) -> None:
    """``position_ordinal`` picked between bills by raw row order; now it doesn't."""
    from app.modules.bim_hub.service import BIMHubService

    project_id = await _mk_project(session)
    first = await _mk_boq(session, project_id, name="Base estimate")
    second = await _mk_boq(session, project_id, name="Variation 04")
    await _mk_position(session, first)
    await _mk_position(session, second)

    svc = BIMHubService(session)
    assert (await svc._resolve_boq_target_position(target={"position_ordinal": "1"}, project_id=project_id)) is None

    # One bill holding the ordinal still resolves - the rule is about the
    # ambiguity, not about the lookup key.
    other_project = await _mk_project(session)
    only = await _mk_boq(session, other_project, name="Main bill")
    pos = await _mk_position(session, only)
    resolved = await svc._resolve_boq_target_position(target={"position_ordinal": "1"}, project_id=other_project)
    assert resolved is not None
    assert resolved.id == pos.id


# ════════════════════════════════════════════════════════════════════════
# project_intelligence.actions - the three "project's main BOQ" actions
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_price_matching_still_targets_a_lone_unlocked_bill(session) -> None:
    """Positive control: one bill, and the action runs against it."""
    from app.modules.project_intelligence.actions import _match_cwicr_prices

    project_id = await _mk_project(session)
    boq = await _mk_boq(session, project_id, name="Main bill")
    await _mk_position(session, boq)

    result = await _match_cwicr_prices(session, str(project_id))

    assert result.success is True, result.message
    assert result.data is not None
    assert result.data["boq_id"] == str(boq.id)
    # One zero-priced candidate was considered; the empty catalogue is why it
    # was skipped rather than priced.
    assert result.data["count_total"] == 1


@pytest.mark.asyncio
async def test_price_matching_refuses_two_bills_and_leaves_the_rates_alone(session) -> None:
    """Negative control: the caller is told, and no rate is rewritten."""
    from app.modules.project_intelligence.actions import _match_cwicr_prices

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    pos = await _mk_position(session, older)

    result = await _match_cwicr_prices(session, str(project_id))

    assert result.success is False
    assert "more than one" in result.message
    assert result.data is not None
    assert result.data["error"] == "ambiguous_boq"
    assert {c["name"] for c in result.data["candidates"]} == {"Base estimate", "Variation 04"}
    await session.refresh(pos)
    assert Decimal(pos.unit_rate) == Decimal("0")
    assert newer is not None


@pytest.mark.asyncio
async def test_price_matching_refuses_to_reprice_a_locked_bill(session) -> None:
    """Rewriting rates inside an approved estimate is the defect, not the feature."""
    from app.modules.project_intelligence.actions import _match_cwicr_prices

    project_id = await _mk_project(session)
    locked = await _mk_boq(session, project_id, name="Approved estimate", locked=True)
    await _mk_position(session, locked)

    result = await _match_cwicr_prices(session, str(project_id))

    assert result.success is False
    assert result.data is not None
    assert result.data["error"] == "boq_locked"


@pytest.mark.asyncio
async def test_a_writable_only_predicate_would_break_validation_on_a_locked_bill(session) -> None:
    """The lock filter is the caller's: a read path must not inherit it.

    This is the regression the two-bill matrix cannot catch. Validating an
    approved, locked estimate is the ordinary case; a uniform "unlocked only"
    rule would have made every such project unvalidatable.
    """
    from app.modules.project_intelligence.actions import _run_validation

    project_id = await _mk_project(session)
    locked = await _mk_boq(session, project_id, name="Approved estimate", locked=True)

    svc_instance = MagicMock()
    svc_instance.run_validation = AsyncMock(
        return_value={
            "report_id": str(uuid.uuid4()),
            "status": "passed",
            "passed_count": 3,
            "warning_count": 0,
            "error_count": 0,
        }
    )
    with patch("app.modules.validation.service.ValidationModuleService", return_value=svc_instance):
        result = await _run_validation(session, str(project_id))

    assert result.success is True, result.message
    assert result.data is not None
    assert result.data["boq_id"] == str(locked.id)


@pytest.mark.asyncio
async def test_validation_refuses_two_bills_rather_than_reporting_on_one(session) -> None:
    """A report about a bill nobody named is a report about the wrong bill."""
    from app.modules.project_intelligence.actions import _run_validation

    project_id = await _mk_project(session)
    await _mk_boq(session, project_id, name="Base estimate")
    await _mk_boq(session, project_id, name="Variation 04")

    svc_instance = MagicMock()
    svc_instance.run_validation = AsyncMock(return_value={})
    with patch("app.modules.validation.service.ValidationModuleService", return_value=svc_instance):
        result = await _run_validation(session, str(project_id))

    assert result.success is False
    assert result.data is not None
    assert result.data["error"] == "ambiguous_boq"
    assert len(result.data["candidates"]) == 2
    svc_instance.run_validation.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_writable_only_predicate_would_break_scheduling_on_a_locked_bill(session) -> None:
    """Second read path, same control: a master schedule off an approved bill."""
    from app.modules.project_intelligence.actions import _generate_schedule

    project_id = await _mk_project(session)
    locked = await _mk_boq(session, project_id, name="Approved estimate", locked=True)
    await _mk_position(session, locked)

    result = await _generate_schedule(session, str(project_id))

    assert result.success is True, result.message
    assert result.data is not None
    assert result.data["boq_id"] == str(locked.id)


@pytest.mark.asyncio
async def test_schedule_generation_refuses_two_bills(session) -> None:
    """A schedule derived from an unnamed bill is a schedule for the wrong scope."""
    from app.modules.project_intelligence.actions import _generate_schedule
    from app.modules.schedule.models import Schedule

    project_id = await _mk_project(session)
    await _mk_boq(session, project_id, name="Base estimate")
    await _mk_boq(session, project_id, name="Variation 04")

    result = await _generate_schedule(session, str(project_id))

    assert result.success is False
    assert result.data is not None
    assert result.data["error"] == "ambiguous_boq"
    schedules = (
        await session.execute(select(func.count(Schedule.id)).where(Schedule.project_id == project_id))
    ).scalar_one()
    assert int(schedules) == 0


# ════════════════════════════════════════════════════════════════════════
# match_elements.apply_to_boq
# ════════════════════════════════════════════════════════════════════════


def _apply_spec(**over):
    from app.modules.match_elements import schemas

    return schemas.ApplyToBoqRequest(**{"dry_run": False, **over})


@pytest.mark.asyncio
async def test_match_apply_still_writes_into_a_lone_unlocked_bill(session) -> None:
    """Positive control: one bill, and the priced line lands in it."""
    from app.modules.boq.models import Position
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    boq = await _mk_boq(session, project_id, name="Main bill")
    sess = await _mk_match_session_with_custom_group(session, project_id)

    result = await get_service().apply_to_boq(session, sess.id, _apply_spec(), None)

    assert result.positions_created == 1
    assert result.boq_id == boq.id
    rows = (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].description == "Rammed earth wall"
    assert Decimal(rows[0].unit_rate) == Decimal("145.5000")


@pytest.mark.asyncio
async def test_match_apply_refuses_two_unlocked_bills_and_writes_nothing(session) -> None:
    """Negative control: 409 with the candidates, and both bills stay empty."""
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    sess = await _mk_match_session_with_custom_group(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await get_service().apply_to_boq(session, sess.id, _apply_spec(), None)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "ambiguous_boq"
    assert {c["name"] for c in exc.value.detail["candidates"]} == {"Base estimate", "Variation 04"}
    assert await _count_positions(session, older, newer) == 0


@pytest.mark.asyncio
async def test_match_apply_preview_refuses_two_bills_too(session) -> None:
    """A preview that cannot reveal the ambiguity is a promise, not a preview."""
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    await _mk_boq(session, project_id, name="Base estimate")
    await _mk_boq(session, project_id, name="Variation 04")
    sess = await _mk_match_session_with_custom_group(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await get_service().apply_to_boq(session, sess.id, _apply_spec(dry_run=True), None)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "ambiguous_boq"


@pytest.mark.asyncio
async def test_match_apply_writes_into_the_bill_the_caller_names(session) -> None:
    """The explicit path that ``design_options`` already uses still decides."""
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    older = await _mk_boq(session, project_id, name="Base estimate")
    newer = await _mk_boq(session, project_id, name="Variation 04")
    sess = await _mk_match_session_with_custom_group(session, project_id)

    result = await get_service().apply_to_boq(session, sess.id, _apply_spec(target_boq_id=newer.id), None)

    assert result.boq_id == newer.id
    assert result.positions_created == 1
    assert await _count_positions(session, older) == 0


@pytest.mark.asyncio
async def test_match_apply_still_creates_the_bill_a_bare_project_lacks(session) -> None:
    """No bill at all is a deliberate answer here, not an ambiguity."""
    from app.modules.boq.models import BOQ
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    sess = await _mk_match_session_with_custom_group(session, project_id)

    result = await get_service().apply_to_boq(session, sess.id, _apply_spec(), None)

    assert result.boq_id is not None
    assert result.positions_created == 1
    bills = (await session.execute(select(BOQ).where(BOQ.project_id == project_id))).scalars().all()
    assert len(bills) == 1
    assert bills[0].id == result.boq_id


@pytest.mark.asyncio
async def test_match_apply_refuses_a_project_whose_only_bill_is_locked(session) -> None:
    """It used to append into the locked bill; a second bill is not the answer either."""
    from app.modules.boq.models import BOQ
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    locked = await _mk_boq(session, project_id, name="Approved estimate", locked=True)
    sess = await _mk_match_session_with_custom_group(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await get_service().apply_to_boq(session, sess.id, _apply_spec(), None)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "boq_locked"
    assert await _count_positions(session, locked) == 0
    # And it did not quietly create a second bill to get around the lock.
    bills = (await session.execute(select(func.count(BOQ.id)).where(BOQ.project_id == project_id))).scalar_one()
    assert int(bills) == 1


@pytest.mark.asyncio
async def test_match_apply_rejects_a_bill_belonging_to_another_project(session) -> None:
    """The cross-tenant guard survives the move to the shared resolver."""
    from app.modules.match_elements.service import get_service

    project_id = await _mk_project(session)
    await _mk_boq(session, project_id, name="Main bill")
    other_project = await _mk_project(session)
    foreign = await _mk_boq(session, other_project, name="Someone else's bill")
    sess = await _mk_match_session_with_custom_group(session, project_id)

    with pytest.raises(HTTPException) as exc:
        await get_service().apply_to_boq(session, sess.id, _apply_spec(target_boq_id=foreign.id), None)

    # 404, not 409: we do not leak whether the foreign bill exists.
    assert exc.value.status_code == 404
