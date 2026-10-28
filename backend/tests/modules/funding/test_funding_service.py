# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Awards, draws and rollups against a real database (PostgreSQL).

The interesting behaviour of this module is not the CRUD. It is that
recording an award writes down dates nobody typed, that re-recording one
replaces those dates without touching anything a person entered, and that
every total on the screen is derived from rows rather than stored. All three
are about what is in the table afterwards, so they are tested against a
database rather than against a stand-in for one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funding.models import FundingApplication, FundingProgramme
from app.modules.funding.service import FundingService
from app.modules.funding.validators import register_funding_rules
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _rules() -> None:
    """The rule set is registered by the module's startup hook in production."""
    register_funding_rules()


async def make_project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"funding-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Funding",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Funding {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def make_programme(service: FundingService, **overrides: Any) -> FundingProgramme:
    """A programme whose terms imply every deadline the module derives."""
    values: dict[str, Any] = {
        "code": f"PROG-{uuid.uuid4().hex[:6]}",
        "name": "Energy efficient refurbishment",
        "authority_name": "Federal funding bank",
        "country": "DE",
        "instrument": "grant",
        "funding_rate_percent": Decimal("40"),
        "own_share_percent": Decimal("20"),
        "aid_intensity_cap_percent": Decimal("40"),
        "proof_of_use_due_days": 180,
        "disbursement_spend_days": 60,
        "retention_years": 10,
        "requires_application_before_start": True,
        "status": "open",
    }
    values.update(overrides)
    return await service.programmes.create(**values)


async def make_application(
    service: FundingService,
    project_id: uuid.UUID,
    programme: FundingProgramme,
    **overrides: Any,
) -> FundingApplication:
    values: dict[str, Any] = {
        "project_id": project_id,
        "programme_id": programme.id,
        "code": f"A-{uuid.uuid4().hex[:6]}",
        "title": "Envelope and heating",
        "eligible_cost_base": Decimal("1000000"),
        "requested_amount": Decimal("400000"),
        "own_share_amount": Decimal("200000"),
        "currency": "EUR",
        "status": "submitted",
        "submitted_on": "2026-02-01",
    }
    values.update(overrides)
    return await service.applications.create(**values)


def by_kind(rows: list[Any]) -> dict[str, Any]:
    return {row.kind: row for row in rows}


# ── Recording an award writes down the dates it implies ─────────────────


async def test_recording_an_award_derives_the_deadlines_the_programme_implies(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)

    await service.record_award(
        application,
        approved=True,
        decided_on="2026-03-15",
        award_reference="Az. 2026/4711",
        approved_amount=Decimal("350000"),
        award_period_start="2026-04-01",
        award_period_end="2026-12-31",
    )

    assert application.status == "approved"
    assert application.approved_amount == Decimal("350000")

    obligations = by_kind(await service.obligations.list_for_application(application.id))
    assert set(obligations) == {"final_report", "retention_end"}
    # 180 days after the award period ends, and ten years after it.
    assert obligations["final_report"].due_on == "2027-06-29"
    assert obligations["retention_end"].due_on == "2036-12-31"
    for row in obligations.values():
        assert row.source == "programme_rule"
        assert row.source_reference == programme.code
        assert row.status == "open"
        # The detail says which programme imposed it, so a reader can check
        # the deadline against the notice rather than trusting the screen.
        assert programme.code in row.detail


async def test_a_programme_that_names_no_deadline_has_none_invented_for_it(session: AsyncSession) -> None:
    """An invented deadline is worse than a missing one, because people plan to it."""
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service, proof_of_use_due_days=0, retention_years=0)
    application = await make_application(service, project_id, programme)

    await service.record_award(
        application,
        approved=True,
        approved_amount=Decimal("350000"),
        award_period_end="2026-12-31",
    )

    assert await service.obligations.list_for_application(application.id) == []


async def test_re_recording_an_award_replaces_its_own_dates_and_leaves_a_persons_alone(
    session: AsyncSession,
) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)

    await service.record_award(
        application, approved=True, approved_amount=Decimal("350000"), award_period_end="2026-12-31"
    )
    typed = await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="Display the funding sign on the hoarding",
        due_on="2026-05-01",
        source="manual",
        status="open",
    )

    # The authority extends the period, and the derived dates have to move.
    await service.record_award(
        application, approved=True, approved_amount=Decimal("350000"), award_period_end="2027-06-30"
    )

    obligations = by_kind(await service.obligations.list_for_application(application.id))
    assert set(obligations) == {"final_report", "retention_end", "condition"}
    assert obligations["final_report"].due_on == "2027-12-27"
    assert obligations["retention_end"].due_on == "2037-06-30"
    assert obligations["condition"].id == typed.id
    assert obligations["condition"].due_on == "2026-05-01"


async def test_a_rejection_cancels_the_derived_dates_and_keeps_what_someone_typed(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)

    await service.record_award(
        application, approved=True, approved_amount=Decimal("350000"), award_period_end="2026-12-31"
    )
    await service.obligations.create(
        application_id=application.id,
        kind="condition",
        title="Appeal deadline",
        due_on="2026-04-30",
        source="manual",
        status="open",
    )

    await service.record_award(application, approved=False, decided_on="2026-03-15", rejection_reason="Budget spent")

    assert application.status == "rejected"
    assert application.approved_amount == Decimal("0")
    assert application.rejection_reason == "Budget spent"
    remaining = by_kind(await service.obligations.list_for_application(application.id))
    assert set(remaining) == {"condition"}


# ── Money arriving starts a clock ───────────────────────────────────────


async def test_money_arriving_stamps_the_spend_deadline_onto_the_draw(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)
    draw = await service.disbursements.create(
        application_id=application.id,
        sequence=1,
        code="MA-1",
        status="submitted",
        amount_requested=Decimal("100000"),
    )

    await service.on_funds_received(application, draw, "2027-01-15")

    assert draw.status == "paid"
    assert draw.received_on == "2027-01-15"
    # Sixty days from receipt, written onto the draw so that editing the
    # programme afterwards cannot move a date already communicated.
    assert draw.spend_deadline_on == "2027-03-16"

    obligations = by_kind(await service.obligations.list_for_application(application.id))
    assert obligations["spend_window"].due_on == "2027-03-16"
    assert obligations["spend_window"].source == "programme_rule"


async def test_a_programme_with_no_spend_window_starts_no_clock(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service, disbursement_spend_days=0)
    application = await make_application(service, project_id, programme)
    draw = await service.disbursements.create(application_id=application.id, sequence=1, status="submitted")

    await service.on_funds_received(application, draw, "2027-01-15")

    assert draw.spend_deadline_on == ""
    assert "spend_window" not in by_kind(await service.obligations.list_for_application(application.id))


async def test_accepting_the_proof_of_use_moves_retention_onto_the_acceptance_date(
    session: AsyncSession,
) -> None:
    """Until acceptance the date cannot be computed, so it is counted from the period end."""
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)
    await service.record_award(
        application, approved=True, approved_amount=Decimal("350000"), award_period_end="2026-12-31"
    )
    proof = await service.proofs.create(application_id=application.id, kind="final", submitted_on="2027-06-01")

    await service.on_proof_accepted(application, proof, "2027-07-10")

    assert proof.status == "accepted"
    assert proof.retention_until == "2037-07-10"
    rows = await service.obligations.list_for_application(application.id)
    retention = [row for row in rows if row.kind == "retention_end"]
    # Exactly one: the earlier estimate is replaced, not joined.
    assert len(retention) == 1
    assert retention[0].due_on == "2037-07-10"


# ── Rollups are derived, never stored ───────────────────────────────────


async def test_an_application_summary_is_built_from_the_rows_beneath_it(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)
    await service.record_award(
        application, approved=True, approved_amount=Decimal("400000"), award_period_end="2026-12-31"
    )
    await service.disbursements.create(
        application_id=application.id,
        sequence=1,
        status="paid",
        amount_requested=Decimal("150000"),
        amount_received=Decimal("150000"),
    )
    await service.disbursements.create(
        application_id=application.id,
        sequence=2,
        status="submitted",
        amount_requested=Decimal("100000"),
    )

    summary = await service.application_summary(application, today="2027-01-01")

    assert summary["approved_amount"] == Decimal("400000")
    assert summary["drawn_amount"] == Decimal("250000")
    assert summary["received_amount"] == Decimal("150000")
    assert summary["outstanding_amount"] == Decimal("250000")
    assert summary["own_share_required"] == Decimal("200000.00")
    assert summary["own_share_recorded"] == Decimal("200000")
    assert summary["effective_funding_rate_percent"] == Decimal("40.00")
    assert summary["next_due_on"] == "2027-06-29"


async def test_an_overpayment_is_not_shown_as_something_left_to_draw(session: AsyncSession) -> None:
    """A negative claim would invite somebody to draw it; the conversation is a different one."""
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)
    await service.record_award(
        application, approved=True, approved_amount=Decimal("100000"), award_period_end="2026-12-31"
    )
    await service.disbursements.create(
        application_id=application.id, sequence=1, status="paid", amount_received=Decimal("120000")
    )

    summary = await service.application_summary(application, today="2027-01-01")

    assert summary["received_amount"] == Decimal("120000")
    assert summary["outstanding_amount"] == Decimal("0")


async def test_a_deadline_is_overdue_against_the_readers_date_not_the_servers(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)
    await service.record_award(
        application, approved=True, approved_amount=Decimal("400000"), award_period_end="2026-12-31"
    )

    before = await service.application_summary(application, today="2027-01-01")
    after = await service.application_summary(application, today="2027-07-01")
    blind = await service.application_summary(application, today="")

    assert before["obligations_open"] == 2
    assert before["obligations_overdue"] == 0
    assert after["obligations_overdue"] == 1
    # Without a date nothing can be late, which is the honest answer rather
    # than a count taken from whichever machine happened to answer.
    assert blind["obligations_overdue"] == 0


async def test_two_programmes_funding_one_building_look_at_the_same_costs(session: AsyncSession) -> None:
    """The base is the largest any application declares, never the sum.

    Adding the bases would halve the intensity exactly where the ceiling is
    about to bind, which is the one place the number has to be right.
    """
    service = FundingService(session)
    project_id = await make_project(session)
    national = await make_programme(service, aid_intensity_cap_percent=Decimal("40"))
    regional = await make_programme(service, aid_intensity_cap_percent=Decimal("60"))

    first = await make_application(service, project_id, national, eligible_cost_base=Decimal("1000000"))
    second = await make_application(service, project_id, regional, eligible_cost_base=Decimal("1000000"))
    await service.record_award(first, approved=True, approved_amount=Decimal("300000"), award_period_end="2026-12-31")
    await service.record_award(second, approved=True, approved_amount=Decimal("200000"), award_period_end="2026-12-31")

    summary = await service.project_summary(project_id, today="2026-06-01")

    assert summary["application_count"] == 2
    assert summary["approved_count"] == 2
    assert summary["approved_amount"] == Decimal("500000")
    assert summary["eligible_cost_base"] == Decimal("1000000")
    assert summary["aid_intensity_percent"] == Decimal("50.00")
    # The lowest ceiling binds, so the project reads as over it.
    assert summary["aid_intensity_cap_percent"] == Decimal("40")


async def test_a_project_with_no_applications_answers_with_zeroes_rather_than_failing(
    session: AsyncSession,
) -> None:
    service = FundingService(session)
    project_id = await make_project(session)

    summary = await service.project_summary(project_id, today="2026-06-01")

    assert summary["application_count"] == 0
    assert summary["approved_amount"] == Decimal("0")
    assert summary["aid_intensity_percent"] == Decimal("0")
    assert summary["aid_intensity_cap_percent"] == Decimal("0")


# ── Validation travels with the record ──────────────────────────────────


async def test_reading_an_application_carries_its_findings(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(
        service,
        project_id,
        programme,
        submitted_on="2026-02-01",
        measure_start_on="2026-01-10",
        own_share_amount=Decimal("50000"),
    )

    findings = await service.validate_application(application, today="2026-06-01")

    failed = {row["rule_id"] for row in findings if not row["passed"]}
    assert "funding.measure_starts_after_application" in failed
    assert "funding.own_share_is_covered" in failed
    # Sorted by rule id, so a list that refreshes does not reshuffle itself
    # and read as though the data changed.
    assert [row["rule_id"] for row in findings] == sorted(row["rule_id"] for row in findings)


async def test_a_clean_application_comes_back_with_nothing_failing(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(
        service,
        project_id,
        programme,
        submitted_on="2026-02-01",
        measure_start_on="2026-04-01",
        own_share_amount=Decimal("200000"),
    )
    await service.record_award(
        application,
        approved=True,
        approved_amount=Decimal("400000"),
        award_period_start="2026-04-01",
        award_period_end="2026-12-31",
    )

    findings = await service.validate_application(application, today="2026-06-01")

    assert findings, "the rules ran but reported nothing at all"
    assert [row for row in findings if not row["passed"]] == []


async def test_the_findings_reach_the_reader_in_their_own_language(session: AsyncSession) -> None:
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(
        service, project_id, programme, submitted_on="2026-02-01", measure_start_on="2026-01-10"
    )

    english = await service.validate_application(application, locale="en", today="2026-06-01")
    german = await service.validate_application(application, locale="de", today="2026-06-01")

    def message(rows: list[dict[str, Any]], rule_id: str) -> str:
        return next(row["message"] for row in rows if row["rule_id"] == rule_id)

    rule_id = "funding.measure_starts_after_application"
    assert message(german, rule_id) != message(english, rule_id)
    assert not message(german, rule_id).startswith("funding.")


async def test_a_finding_says_which_currency_its_amounts_are_in(session: AsyncSession) -> None:
    """The rule can only name the currency if the payload carries it.

    The rule reads the currency off the application section, and the service
    is what puts it there. Tested here rather than against a hand-built
    context, because a context assembled by a test proves nothing about the
    one the service assembles in production.
    """
    service = FundingService(session)
    project_id = await make_project(session)
    programme = await make_programme(service)
    application = await make_application(
        service,
        project_id,
        programme,
        currency="GBP",
        eligible_cost_base=Decimal("1000000"),
        own_share_amount=Decimal("0"),
    )

    findings = await service.validate_application(application, today="2026-06-01")
    message = next(row["message"] for row in findings if row["rule_id"] == "funding.own_share_is_covered")

    assert "200,000.00 GBP" in message
