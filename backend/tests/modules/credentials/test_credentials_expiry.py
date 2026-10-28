# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The register's whole reason to exist: a credential that ages out.

Nothing writes to a credential row as it ages. It is created once, and then the
calendar moves. Every query that trusts the stored ``status`` column therefore
misses exactly the rows the register exists to surface - the ones that quietly
became someone else's problem overnight.

These tests plant rows whose stored status is what it would have been on the day
they were entered, then ask the register what it says today. A stored status is
never used as the expected value; the expectation is always derived from the
dates, because the dates are the thing that is true.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.modules.credentials import repository as repository_module
from app.modules.credentials import service as service_module
from app.modules.credentials.models import Credential
from app.modules.credentials.repository import CredentialRepository, effective_status_expr
from app.modules.credentials.service import CredentialService, recompute_status
from tests.modules.credentials.conftest import (
    API_PREFIX,
    build_app,
    day,
    http_client,
    make_credential,
    make_project,
    make_user,
    today,
)


async def test_a_credential_that_aged_into_its_window_is_reported_as_expiring(session) -> None:
    """Entered a year ago as active, now 10 days from expiry.

    This is the failure the module shipped with: nothing rewrites the row as it
    ages, so the stored column still says ``active`` while the credential is
    inside its reminder window.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(
        session,
        project.id,
        holder_name="Aged Row",
        issued_at=day(-355),
        valid_until=day(10),
        notify_days_before=30,
        status="active",  # what the row was written with, a year ago
    )

    service = CredentialService(session)
    assert credential.status == "active", "the stored column should still be stale"
    assert service.effective_status(credential) == "expiring_soon"

    expiring = await service.list_expiring_soon(project.id)
    assert [c.id for c in expiring] == [credential.id]


async def test_a_credential_that_aged_past_its_expiry_is_reported_as_expired(session) -> None:
    """Expired three days ago, never touched since."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(
        session,
        project.id,
        valid_until=day(-3),
        status="active",
    )

    service = CredentialService(session)
    assert service.effective_status(credential) == "expired"
    expiring = await service.list_expiring_soon(project.id)
    assert [c.id for c in expiring] == [credential.id]


async def test_the_response_never_contradicts_its_own_expiry_date(session) -> None:
    """``status`` and ``days_until_expiry`` come from one calculation.

    The payload used to be able to say ``status="active"`` next to
    ``days_until_expiry=-40``, which is not a stale reading but a self-
    contradictory one.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(session, project.id, valid_until=day(-40), status="active")

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        listed = await client.get(f"{API_PREFIX}/", params={"project_id": str(project.id)})

    assert listed.status_code == 200, listed.text
    row = listed.json()[0]
    assert row["days_until_expiry"] == -40
    assert row["status"] == "expired"
    # The stored column has not been rewritten, and the payload says so rather
    # than pretending the register is tidy.
    assert row["status_is_stale"] is True


async def test_a_manual_status_survives_the_passage_of_time(session) -> None:
    """A revoked credential does not become 'expired' because a date passed.

    Manual states are decisions, not derivations; the date arithmetic must not
    overwrite one.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    revoked = await make_credential(
        session,
        project.id,
        valid_until=day(-10),
        status="revoked",
    )
    suspended = await make_credential(
        session,
        project.id,
        valid_until=day(5),
        status="suspended",
    )

    service = CredentialService(session)
    assert service.effective_status(revoked) == "revoked"
    assert service.effective_status(suspended) == "suspended"

    # And they stay out of the renewal widget, which is about lapsing dates.
    expiring = await service.list_expiring_soon(project.id)
    assert expiring == []


async def test_a_perpetual_credential_never_enters_an_expiry_bucket(session) -> None:
    """No ``valid_until`` means nothing to expire."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(session, project.id, valid_until=None, status="active")

    service = CredentialService(session)
    assert await service.list_expiring_soon(project.id) == []

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        listed = await client.get(f"{API_PREFIX}/", params={"project_id": str(project.id)})

    row = listed.json()[0]
    assert row["days_until_expiry"] is None
    assert row["status"] == "active"
    assert row["status_is_stale"] is False


async def test_the_status_filter_finds_rows_that_aged_into_the_bucket(session) -> None:
    """``?status=expired`` must not consult the stale stored column."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    aged = await make_credential(session, project.id, valid_until=day(-1), status="active")
    await make_credential(session, project.id, valid_until=day(400), status="active")

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        listed = await client.get(
            f"{API_PREFIX}/",
            params={"project_id": str(project.id), "status": "expired"},
        )

    assert listed.status_code == 200, listed.text
    assert [r["id"] for r in listed.json()] == [str(aged.id)]


async def test_refresh_writes_the_derived_status_back(session) -> None:
    """The stored column catches up, and says how many rows moved."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    drifted = await make_credential(session, project.id, valid_until=day(-2), status="active")
    settled = await make_credential(session, project.id, valid_until=day(900), status="active")

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        refreshed = await client.post(
            f"{API_PREFIX}/refresh-statuses/",
            params={"project_id": str(project.id)},
        )

    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["examined"] == 1
    assert body["updated"] == 1

    await session.refresh(drifted)
    await session.refresh(settled)
    assert drifted.status == "expired"
    assert settled.status == "active"

    # Running it again is a no-op: the register has converged.
    service = CredentialService(session)
    assert await service.refresh_statuses(project.id) == (0, 0)


async def test_refresh_leaves_a_manual_status_alone(session) -> None:
    """A suspended credential is not 'drifted', whatever its dates say."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    suspended = await make_credential(session, project.id, valid_until=day(-30), status="suspended")

    service = CredentialService(session)
    assert await service.refresh_statuses(project.id) == (0, 0)
    await session.refresh(suspended)
    assert suspended.status == "suspended"


# ── The two rules must be one rule ───────────────────────────────────────────


async def test_both_sides_agree_on_which_statuses_are_manual() -> None:
    """The SQL and Python copies of the manual-status set must match.

    ``_STORED`` below is a hand-written list, so a sixth manual status added to
    one constant and not the other would slip through the boundary matrix
    untested: no parametrisation would ever carry it. Comparing the constants
    directly is what makes the matrix's coverage claim true.
    """
    assert set(repository_module._MANUAL_STATUSES) == set(service_module._MANUAL_STATUSES)
    # And every manual status is actually exercised by the matrix below.
    assert set(service_module._MANUAL_STATUSES) <= set(_STORED)


# Offsets either side of every boundary the rule has: the expiry day itself, the
# reminder threshold, and one day beyond each.
_OFFSETS = (-400, -31, -30, -1, 0, 1, 7, 29, 30, 31, 60, 400)
_NOTIFY = (0, 1, 30, 90)
_STORED = ("active", "expiring_soon", "expired", "suspended", "revoked")


@pytest.mark.parametrize("stored", _STORED)
async def test_sql_and_python_agree_on_every_boundary(session, stored: str) -> None:
    """The SQL expression and the Python function are the same rule.

    ``effective_status_expr`` decides which rows a query returns and
    ``recompute_status`` decides what each row is labelled. If they ever
    disagree the register filters by one rule and reports by another, and
    nothing in the output would reveal it. This drives both over every boundary
    the rule has, including the inclusive reminder edge and the expiry day
    itself, and compares them value by value.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    planted: dict[uuid.UUID, tuple[int, int]] = {}
    for offset in _OFFSETS:
        for notify in _NOTIFY:
            credential = await make_credential(
                session,
                project.id,
                valid_until=day(offset),
                notify_days_before=notify,
                status=stored,
            )
            planted[credential.id] = (offset, notify)

    # A perpetual row belongs in the matrix too: NULL is a distinct branch on
    # both sides and the one most likely to be forgotten in SQL.
    perpetual = await make_credential(
        session,
        project.id,
        valid_until=None,
        notify_days_before=30,
        status=stored,
    )

    as_of = today()
    rows = await session.execute(
        sa.select(Credential.id, effective_status_expr(as_of)).where(Credential.project_id == project.id)
    )
    from_sql = {row[0]: row[1] for row in rows.all()}

    assert len(from_sql) == len(planted) + 1

    for credential_id, (offset, notify) in planted.items():
        expected = recompute_status(
            today=as_of,
            valid_until=day(offset),
            notify_days_before=notify,
            current_status=stored,
        )
        assert from_sql[credential_id] == expected, (
            f"SQL and Python disagree for offset={offset} notify={notify} stored={stored!r}: "
            f"SQL said {from_sql[credential_id]!r}, Python said {expected!r}"
        )

    assert from_sql[perpetual.id] == recompute_status(
        today=as_of,
        valid_until=None,
        notify_days_before=30,
        current_status=stored,
    )


async def test_the_expiring_query_returns_exactly_the_alerting_rows(session) -> None:
    """The repository's bucket filter agrees with the per-row rule.

    Guards the filter itself rather than the expression: a correct expression
    used with the wrong set of buckets would still select the wrong rows.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    for offset in (-100, -1, 0, 1, 29, 30, 31, 200):
        await make_credential(
            session,
            project.id,
            valid_until=day(offset),
            notify_days_before=30,
            status="active",
        )
    await make_credential(session, project.id, valid_until=None, status="active")

    repo = CredentialRepository(session)
    as_of = today()
    alerting = await repo.list_expiring_soon(project.id, today=as_of, limit=200)
    every = await repo.list_for_project(project.id, today=as_of)

    expected = {
        c.id
        for c in every
        if recompute_status(
            today=as_of,
            valid_until=c.valid_until,
            notify_days_before=c.notify_days_before,
            current_status=c.status,
        )
        in {"expiring_soon", "expired"}
    }
    assert {c.id for c in alerting} == expected
    assert expected, "the fixture must produce at least one alerting row"
