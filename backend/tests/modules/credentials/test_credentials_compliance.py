# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may not work today.

The compliance report joins what the project requires to what its people hold.
These tests pin the distinctions that decide whether somebody is stopped at the
gate: missing against expired, blocking against advisory, inside a grace window
against past it, and a future expiry - which is a warning, never a bar, because
a ticket valid until Friday is valid today.
"""

from __future__ import annotations

from app.modules.credentials.service import RequirementService
from tests.modules.credentials.conftest import (
    API_PREFIX,
    build_app,
    day,
    http_client,
    make_credential,
    make_project,
    make_requirement,
    make_user,
)


async def _report(session, project_id):
    return await RequirementService(session).build_compliance_report(project_id)


async def test_a_holder_with_no_matching_credential_is_blocked(session) -> None:
    """The gap that matters most is the credential that was never there."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    # The holder exists on the register through a different credential.
    await make_credential(
        session,
        project.id,
        holder_name="No Licence",
        credential_type="training",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    assert report.holder_count == 1
    assert report.blocked_holder_count == 1
    row = report.holders[0]
    assert row.is_blocked is True
    assert [(g.credential_type, g.reason) for g in row.gaps] == [("professional_license", "missing")]


async def test_a_holder_whose_credential_lapsed_is_blocked(session) -> None:
    """Held once is not held now."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="certification")
    await make_credential(
        session,
        project.id,
        holder_name="Lapsed",
        credential_type="certification",
        valid_until=day(-5),
    )

    report = await _report(session, project.id)
    row = report.holders[0]
    assert row.is_blocked is True
    gap = row.gaps[0]
    assert gap.reason == "expired"
    assert gap.days_until_expiry == -5
    assert gap.within_grace is False


async def test_a_lapse_inside_the_grace_window_does_not_block(session) -> None:
    """A fortnight to get the renewal back is a real site rule.

    The gap is still reported - the register never hides a lapse - but it does
    not stop the holder working.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="certification",
        grace_days=14,
    )
    await make_credential(
        session,
        project.id,
        holder_name="In Grace",
        credential_type="certification",
        valid_until=day(-3),
    )

    report = await _report(session, project.id)
    row = report.holders[0]
    assert row.is_blocked is False
    assert row.gaps[0].reason == "expired"
    assert row.gaps[0].within_grace is True


async def test_a_lapse_past_the_grace_window_blocks_again(session) -> None:
    """The boundary is the point of the setting."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="certification",
        grace_days=14,
    )
    await make_credential(
        session,
        project.id,
        holder_name="Past Grace",
        credential_type="certification",
        valid_until=day(-15),
    )

    report = await _report(session, project.id)
    assert report.holders[0].is_blocked is True
    assert report.holders[0].gaps[0].within_grace is False


async def test_an_upcoming_expiry_warns_but_never_blocks(session) -> None:
    """A credential valid until next week is valid today.

    A register that stopped people for a future date would be switched off
    within a week of being turned on.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="certification")
    await make_credential(
        session,
        project.id,
        holder_name="Renewing",
        credential_type="certification",
        valid_until=day(7),
        notify_days_before=30,
    )

    report = await _report(session, project.id)
    row = report.holders[0]
    assert row.is_blocked is False
    assert row.gaps[0].reason == "expiring_soon"
    assert row.gaps[0].days_until_expiry == 7


async def test_a_non_blocking_requirement_never_blocks(session) -> None:
    """An advisory rule produces a note, not a bar."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="training",
        is_blocking=False,
    )
    await make_credential(
        session,
        project.id,
        holder_name="No Training",
        credential_type="professional_license",
        valid_until=day(200),
    )

    report = await _report(session, project.id)
    row = report.holders[0]
    assert row.is_blocked is False
    assert row.gaps[0].reason == "missing"
    assert row.gaps[0].is_blocking is False


async def test_a_suspended_credential_blocks_even_though_its_dates_are_fine(session) -> None:
    """A suspension is a decision the dates cannot overrule."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Suspended",
        credential_type="professional_license",
        valid_until=day(500),
        status="suspended",
    )

    report = await _report(session, project.id)
    assert report.holders[0].is_blocked is True
    assert report.holders[0].gaps[0].reason == "suspended"


async def test_the_best_credential_of_several_is_the_one_judged(session) -> None:
    """A renewed ticket beside the old one satisfies the requirement.

    Holders accumulate rows: the expired one is history, not a gap.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="certification")
    await make_credential(
        session,
        project.id,
        holder_name="Renewed",
        credential_type="certification",
        valid_until=day(-200),
    )
    await make_credential(
        session,
        project.id,
        holder_name="Renewed",
        credential_type="certification",
        valid_until=day(400),
    )

    report = await _report(session, project.id)
    row = report.holders[0]
    assert row.is_blocked is False
    assert row.gaps == []
    assert row.satisfied_count == 1


async def test_a_requirement_scoped_to_a_discipline_binds_only_that_discipline(session) -> None:
    """'Supervisors need a first-aid ticket' must not bind the whole site."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="training",
        applies_to="supervisor",
    )
    await make_credential(
        session,
        project.id,
        holder_name="Supervisor",
        discipline="supervisor",
        credential_type="professional_license",
        valid_until=day(300),
    )
    await make_credential(
        session,
        project.id,
        holder_name="Bricklayer",
        discipline="bricklayer",
        credential_type="professional_license",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    by_name = {r.holder_name: r for r in report.holders}
    assert by_name["Supervisor"].is_blocked is True
    assert by_name["Bricklayer"].is_blocked is False
    assert by_name["Bricklayer"].gaps == []


async def test_a_requirement_binding_nobody_is_reported_not_counted_as_met(session) -> None:
    """A rule nobody is measured against is a mistake, not a pass."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    ghost = await make_requirement(
        session,
        project.id,
        credential_type="training",
        applies_to="scaffolder",  # nobody on the register has this discipline
    )
    await make_credential(
        session,
        project.id,
        holder_name="Joiner",
        discipline="joiner",
        credential_type="professional_license",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    assert report.unmatched_requirement_ids == [ghost.id]
    assert report.holders[0].is_blocked is False


async def test_a_company_requirement_does_not_bind_a_person(session) -> None:
    """Firm-level cover and a person's ticket are different obligations."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="professional_indemnity",
        holder_kind="company",
    )
    await make_credential(
        session,
        project.id,
        holder_name="A Person",
        holder_kind="person",
        credential_type="professional_license",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    assert report.holders[0].is_blocked is False
    assert report.holders[0].gaps == []


async def test_one_person_recorded_under_two_spellings_is_one_holder(session) -> None:
    """The user link wins over the name when it is present."""
    owner = await make_user(session)
    holder = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Jo Smith",
        holder_user_id=holder.id,
        credential_type="professional_license",
        valid_until=day(300),
    )
    await make_credential(
        session,
        project.id,
        holder_name="Josephine Smith",
        holder_user_id=holder.id,
        credential_type="training",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    assert report.holder_count == 1
    assert report.holders[0].is_blocked is False


async def test_an_inactive_requirement_binds_nobody(session) -> None:
    """Retiring a rule stops it blocking people."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="professional_license",
        is_active=False,
    )
    await make_credential(
        session,
        project.id,
        holder_name="Unlicensed",
        credential_type="training",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    assert report.requirement_count == 0
    assert report.holders[0].is_blocked is False


async def test_the_report_leads_with_the_people_who_cannot_work(session) -> None:
    """Ordering is part of the answer when the list is long."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Aaron Fine",
        credential_type="professional_license",
        valid_until=day(300),
    )
    await make_credential(
        session,
        project.id,
        holder_name="Zoe Blocked",
        credential_type="training",
        valid_until=day(300),
    )

    report = await _report(session, project.id)
    assert [r.holder_name for r in report.holders] == ["Zoe Blocked", "Aaron Fine"]


async def test_an_unverified_credential_still_satisfies_but_is_counted(session) -> None:
    """Nobody is stopped for a missing signature, but the audit can see it."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Unchecked",
        credential_type="professional_license",
        valid_until=day(300),
        verified_at=None,
    )

    report = await _report(session, project.id)
    row = report.holders[0]
    assert row.is_blocked is False
    assert row.satisfied_count == 1
    assert row.unverified_count == 1


async def test_the_compliance_endpoint_answers_over_http(session) -> None:
    """The report the screen actually calls."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, credential_type="professional_license")
    await make_credential(
        session,
        project.id,
        holder_name="Gate Refused",
        credential_type="training",
        valid_until=day(100),
    )

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        response = await client.get(
            f"{API_PREFIX}/compliance/",
            params={"project_id": str(project.id)},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked_holder_count"] == 1
    assert body["holders"][0]["holder_name"] == "Gate Refused"
    assert body["holders"][0]["gaps"][0]["reason"] == "missing"
