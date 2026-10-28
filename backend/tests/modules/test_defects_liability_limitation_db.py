# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database tests for the opt-in limitation regime on a warranty entry.

The pure tests in ``tests/unit/test_defects_liability_limitation.py`` drive the
derivation helper directly. These drive the two service methods that actually
write - ``create_warranty`` and ``update_warranty`` - through a real session,
because the whole opt-in turns on which fields a payload set, and
``exclude_unset`` only means anything on a real Pydantic payload going through
the real method.

The question every test here asks is the same one: does an entry that never chose
a limitation regime behave exactly as it did before the column existed. The
regime-free cases are written with a start date present and a period already
recorded, so an implementation that started deriving whenever the arithmetic was
possible would fail them rather than pass them by accident.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.defects_liability.schemas import WarrantyCreate, WarrantyUpdate
from app.modules.defects_liability.service import DefectsLiabilityService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import isolated_engine

# A fixed acceptance date so every derived date below is exact.
ACCEPTANCE = date(2026, 3, 1)
# What a hand-entered register looks like before anybody hears of a regime.
HAND_ENTERED_MONTHS = 24
HAND_ENTERED_END = date(2028, 3, 1)
DLP_END = date(2027, 3, 1)


@pytest.fixture(autouse=True)
def _rules_registered():
    """Put the module's rules in the process-global registry before each test.

    The registry is populated by the application's startup hooks, which no test
    process runs. Without this the engine reports the rule set as unsupported and
    returns a clean report, which reads exactly like the rules having run and
    found nothing.
    """
    from app.modules.defects_liability.validators import register_defects_liability_rules

    register_defects_liability_rules()


@pytest_asyncio.fixture
async def session_and_project():
    """A throwaway database with one project to hang warranty entries on."""
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            owner = User(
                email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
                hashed_password="x",
                role="admin",
            )
            session.add(owner)
            await session.flush()
            project = Project(name=f"P-{uuid.uuid4().hex[:6]}", owner_id=owner.id)
            session.add(project)
            await session.flush()
            yield session, project.id


def _hand_entered(reference: str = "DLP-001", **overrides) -> WarrantyCreate:
    """A payload a team with no legal regime would send: dates typed by hand."""
    payload: dict = {
        "reference": reference,
        "title": "Curtain wall, Level 3 to 8",
        "warranty_start_date": ACCEPTANCE,
        "handover_date": ACCEPTANCE,
        "warranty_months": HAND_ENTERED_MONTHS,
        "warranty_end_date": HAND_ENTERED_END,
        "dlp_end_date": DLP_END,
    }
    payload.update(overrides)
    return WarrantyCreate(**payload)


@pytest.mark.asyncio
async def test_an_entry_created_without_a_regime_stores_exactly_what_was_sent(session_and_project):
    """Everything needed to derive a date is present except the choice to."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)

    warranty = await service.create_warranty(project_id, _hand_entered(), created_by=None)

    assert warranty.limitation_regime is None
    assert warranty.warranty_months == HAND_ENTERED_MONTHS
    assert warranty.warranty_end_date == HAND_ENTERED_END
    assert warranty.dlp_end_date == DLP_END


@pytest.mark.asyncio
async def test_patching_an_unrelated_field_on_a_regime_free_entry_moves_no_date(session_and_project):
    """Renaming an entry must not be the moment a statutory period appears on it."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)
    warranty = await service.create_warranty(project_id, _hand_entered(), created_by=None)

    patched = await service.update_warranty(
        project_id,
        warranty.id,
        WarrantyUpdate(title="Curtain wall, Level 3 to 9"),
    )

    assert patched.title == "Curtain wall, Level 3 to 9"
    assert patched.limitation_regime is None
    assert patched.warranty_months == HAND_ENTERED_MONTHS
    assert patched.warranty_end_date == HAND_ENTERED_END
    assert patched.dlp_end_date == DLP_END


@pytest.mark.asyncio
async def test_choosing_a_regime_is_what_replaces_the_hand_entered_period(session_and_project):
    """The one moment a derived date is allowed to overwrite a typed one."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)
    warranty = await service.create_warranty(project_id, _hand_entered(), created_by=None)

    patched = await service.update_warranty(
        project_id,
        warranty.id,
        WarrantyUpdate(limitation_regime="de_vob_b"),
    )

    assert patched.limitation_regime == "de_vob_b"
    assert patched.warranty_months == 48
    assert patched.warranty_end_date == date(2030, 3, 1)
    # The retention clock is contractual, not statutory, and never moves.
    assert patched.dlp_end_date == DLP_END


@pytest.mark.asyncio
async def test_clearing_the_regime_leaves_the_dates_where_they_were(session_and_project):
    """Dropping the reason drops the reason, not the period the entry runs on."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)
    warranty = await service.create_warranty(
        project_id,
        _hand_entered(limitation_regime="de_bgb"),
        created_by=None,
    )
    assert warranty.limitation_regime == "de_bgb"

    patched = await service.update_warranty(
        project_id,
        warranty.id,
        WarrantyUpdate(limitation_regime=None),
    )

    assert patched.limitation_regime is None
    assert patched.warranty_months == HAND_ENTERED_MONTHS
    assert patched.warranty_end_date == HAND_ENTERED_END


@pytest.mark.asyncio
async def test_a_regime_named_at_creation_fills_only_what_the_payload_left_open(session_and_project):
    """A period typed in the same breath as the choice is kept, not overruled."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)

    derived = await service.create_warranty(
        project_id,
        WarrantyCreate(
            reference="DLP-002",
            title="Roof membrane",
            warranty_start_date=ACCEPTANCE,
            limitation_regime="de_bgb",
        ),
        created_by=None,
    )
    assert derived.warranty_months == 60
    assert derived.warranty_end_date == date(2031, 3, 1)

    typed = await service.create_warranty(
        project_id,
        WarrantyCreate(
            reference="DLP-003",
            title="Roof membrane, agreed period",
            warranty_start_date=ACCEPTANCE,
            limitation_regime="de_bgb",
            warranty_months=36,
            warranty_end_date=date(2029, 3, 1),
        ),
        created_by=None,
    )
    assert typed.warranty_months == 36
    assert typed.warranty_end_date == date(2029, 3, 1)


@pytest.mark.asyncio
async def test_correcting_the_acceptance_date_alone_does_not_re_derive(session_and_project):
    """Only picking a regime derives. A later date correction is reported, not applied."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)
    warranty = await service.create_warranty(
        project_id,
        WarrantyCreate(
            reference="DLP-004",
            title="Mechanical plant",
            warranty_start_date=ACCEPTANCE,
            limitation_regime="de_vob_b",
        ),
        created_by=None,
    )
    assert warranty.warranty_end_date == date(2030, 3, 1)

    patched = await service.update_warranty(
        project_id,
        warranty.id,
        WarrantyUpdate(warranty_start_date=date(2026, 6, 1)),
    )
    assert patched.warranty_end_date == date(2030, 3, 1)

    review = await service.review_limitation_periods(project_id)
    assert review["reviewed_count"] == 1
    assert [f["rule_id"] for f in review["findings"]] == [
        "defects_liability.limitation_period_matches_regime",
    ]


@pytest.mark.asyncio
async def test_a_register_with_no_regimes_is_reviewed_by_nothing(session_and_project):
    """The no-nag proof at the endpoint the screen would call."""
    session, project_id = session_and_project
    service = DefectsLiabilityService(session)
    await service.create_warranty(project_id, _hand_entered("DLP-001"), created_by=None)
    await service.create_warranty(project_id, _hand_entered("DLP-002", warranty_months=999), created_by=None)

    review = await service.review_limitation_periods(project_id)

    assert review["total"] == 2
    assert review["reviewed_count"] == 0
    assert review["regimes_in_use"] == []
    assert review["findings"] == []
