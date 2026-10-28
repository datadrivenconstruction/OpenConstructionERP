# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The HTTP surface: requirements, verification, summary, and the access guard.

The authorisation cases are the ones worth being explicit about. A credential
register holds who is qualified and who is not, which is exactly the sort of
list that must not leak sideways. Every route resolves the record first and then
checks project access, and both "no such id" and "not your project" answer 404,
so the endpoint cannot be walked to discover which ids exist.
"""

from __future__ import annotations

import uuid

import pytest

from tests.modules.credentials.conftest import (
    API_PREFIX,
    build_app,
    day,
    http_client,
    make_credential,
    make_project,
    make_requirement,
    make_user,
    today,
)

# ── Requirements ─────────────────────────────────────────────────────────────


async def test_a_requirement_can_be_created_listed_amended_and_retired(session) -> None:
    """The full life of a requirement over HTTP."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)

    # A manager: the delete at the end of the life cycle needs it, and
    # credentials.delete is deliberately a higher bar than create or update.
    async with http_client(build_app(session, caller_id=owner.id, role="manager")) as client:
        created = await client.post(
            f"{API_PREFIX}/requirements/",
            json={
                "project_id": str(project.id),
                "credential_type": "professional_license",
                "applies_to": "all",
                "is_blocking": True,
                "grace_days": 7,
                "description": "Everyone on site holds a current licence",
            },
        )
        assert created.status_code == 201, created.text
        requirement = created.json()
        assert requirement["is_blocking"] is True
        assert requirement["grace_days"] == 7

        listed = await client.get(
            f"{API_PREFIX}/requirements/",
            params={"project_id": str(project.id)},
        )
        assert listed.status_code == 200
        assert [r["id"] for r in listed.json()] == [requirement["id"]]

        amended = await client.patch(
            f"{API_PREFIX}/requirements/{requirement['id']}/",
            json={"is_blocking": False, "grace_days": 0},
        )
        assert amended.status_code == 200, amended.text
        assert amended.json()["is_blocking"] is False

        removed = await client.delete(f"{API_PREFIX}/requirements/{requirement['id']}/")
        assert removed.status_code == 204

        after = await client.get(
            f"{API_PREFIX}/requirements/",
            params={"project_id": str(project.id)},
        )
        assert after.json() == []


async def test_a_duplicate_requirement_answers_409_not_a_database_error(session) -> None:
    """The same rule twice would double every gap it reports."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="professional_license",
        applies_to="all",
        holder_kind="person",
    )

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        clash = await client.post(
            f"{API_PREFIX}/requirements/",
            json={
                "project_id": str(project.id),
                "credential_type": "professional_license",
                "applies_to": "all",
                "holder_kind": "person",
            },
        )

    assert clash.status_code == 409, clash.text


async def test_the_same_type_for_a_different_audience_is_not_a_duplicate(session) -> None:
    """Scope is part of the identity of a rule."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(
        session,
        project.id,
        credential_type="training",
        applies_to="all",
    )

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        created = await client.post(
            f"{API_PREFIX}/requirements/",
            json={
                "project_id": str(project.id),
                "credential_type": "training",
                "applies_to": "supervisor",
            },
        )

    assert created.status_code == 201, created.text


async def test_an_inactive_requirement_is_hidden_unless_asked_for(session) -> None:
    """Retired rules stay readable without cluttering the working list."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_requirement(session, project.id, is_active=False)

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        default = await client.get(
            f"{API_PREFIX}/requirements/",
            params={"project_id": str(project.id)},
        )
        including = await client.get(
            f"{API_PREFIX}/requirements/",
            params={"project_id": str(project.id), "include_inactive": "true"},
        )

    assert default.json() == []
    assert len(including.json()) == 1


# ── Verification ─────────────────────────────────────────────────────────────


async def test_verifying_a_credential_records_who_and_when(session) -> None:
    """And says nothing about whether the credential is valid."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(session, project.id, valid_until=day(200))

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        verified = await client.post(
            f"{API_PREFIX}/{credential.id}/verify/",
            json={"verified": True, "note": "Checked against the register"},
        )

    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["verified_at"] == today().isoformat()
    assert body["verified_by"] == str(owner.id)
    assert body["metadata"]["verification_note"] == "Checked against the register"


async def test_verification_does_not_revive_an_expired_credential(session) -> None:
    """Checking a lapsed ticket confirms it lapsed."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(session, project.id, valid_until=day(-10))

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        verified = await client.post(
            f"{API_PREFIX}/{credential.id}/verify/",
            json={"verified": True},
        )

    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "expired"


async def test_a_verification_can_be_retracted(session) -> None:
    """Somebody checked the wrong document; the record must be removable."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(
        session,
        project.id,
        valid_until=day(200),
        verified_at=day(-1),
        verified_by="someone",
    )

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        cleared = await client.post(
            f"{API_PREFIX}/{credential.id}/verify/",
            json={"verified": False},
        )

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["verified_at"] is None
    assert cleared.json()["verified_by"] is None


async def test_a_verification_cannot_be_dated_in_the_future(session) -> None:
    """A check that has not happened yet is not a check."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(session, project.id, valid_until=day(200))

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        refused = await client.post(
            f"{API_PREFIX}/{credential.id}/verify/",
            json={"verified": True, "verified_at": day(3).isoformat()},
        )

    assert refused.status_code == 400, refused.text


# ── Summary ──────────────────────────────────────────────────────────────────


async def test_the_summary_counts_on_the_derived_status(session) -> None:
    """The dashboard tile must not inherit the stale column's arithmetic."""
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(session, project.id, valid_until=day(-4), status="active")
    await make_credential(session, project.id, valid_until=day(10), status="active")
    await make_credential(session, project.id, valid_until=day(900), status="active")
    await make_credential(session, project.id, valid_until=None, status="active")

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        summary = await client.get(
            f"{API_PREFIX}/summary/",
            params={"project_id": str(project.id)},
        )

    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total"] == 4
    assert body["expired"] == 1
    assert body["by_status"]["expiring_soon"] == 1
    assert body["perpetual"] == 1
    assert body["unverified"] == 4
    # Two rows aged out of the status they were stored with.
    assert body["stale_status_count"] == 2
    assert body["expiring_within_30_days"] == 1


# ── Access control ───────────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
async def test_a_credential_on_another_project_answers_404(session) -> None:
    """Not 403: a distinguishable refusal is an id-existence oracle."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(session, project.id, valid_until=day(100))

    # Manager role, so the delete reaches the access guard instead of being
    # turned away earlier by the permission check - the 404 is what is on trial.
    async with http_client(build_app(session, caller_id=stranger.id, role="manager")) as client:
        got = await client.get(f"{API_PREFIX}/{credential.id}/")
        patched = await client.patch(
            f"{API_PREFIX}/{credential.id}/",
            json={"notes": "should not land"},
        )
        removed = await client.delete(f"{API_PREFIX}/{credential.id}/")
        verified = await client.post(f"{API_PREFIX}/{credential.id}/verify/", json={})

    assert got.status_code == 404, got.text
    assert patched.status_code == 404, patched.text
    assert removed.status_code == 404, removed.text
    assert verified.status_code == 404, verified.text


@pytest.mark.tenant_isolation
async def test_an_unknown_and_a_foreign_credential_answer_alike(session) -> None:
    """The two refusals must be indistinguishable, body included.

    A different detail string between "no such credential" and "not your
    project" hands back exactly the bit the 404 was chosen to withhold.
    """
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    credential = await make_credential(session, project.id, valid_until=day(100))

    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        foreign = await client.get(f"{API_PREFIX}/{credential.id}/")
        unknown = await client.get(f"{API_PREFIX}/{uuid.uuid4()}/")

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json()["detail"] == unknown.json()["detail"]


@pytest.mark.tenant_isolation
async def test_a_requirement_on_another_project_answers_404(session) -> None:
    """Requirements carry the same guard as credentials."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    requirement = await make_requirement(session, project.id)

    async with http_client(build_app(session, caller_id=stranger.id, role="manager")) as client:
        patched = await client.patch(
            f"{API_PREFIX}/requirements/{requirement.id}/",
            json={"grace_days": 90},
        )
        removed = await client.delete(f"{API_PREFIX}/requirements/{requirement.id}/")

    assert patched.status_code == 404, patched.text
    assert removed.status_code == 404, removed.text


@pytest.mark.tenant_isolation
async def test_every_project_scoped_report_refuses_a_foreign_project(session) -> None:
    """The reports are the richest payloads, so they are the worst to leak."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(session, project.id, valid_until=day(-1))

    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        params = {"project_id": str(project.id)}
        listed = await client.get(f"{API_PREFIX}/", params=params)
        expiring = await client.get(f"{API_PREFIX}/expiring-soon/", params=params)
        compliance = await client.get(f"{API_PREFIX}/compliance/", params=params)
        summary = await client.get(f"{API_PREFIX}/summary/", params=params)
        validated = await client.get(f"{API_PREFIX}/validate/", params=params)
        requirements = await client.get(f"{API_PREFIX}/requirements/", params=params)
        refreshed = await client.post(f"{API_PREFIX}/refresh-statuses/", params=params)

    for response in (
        listed,
        expiring,
        compliance,
        summary,
        validated,
        requirements,
        refreshed,
    ):
        assert response.status_code == 404, response.text


@pytest.mark.tenant_isolation
async def test_a_requirement_cannot_be_planted_on_a_foreign_project(session) -> None:
    """Creation takes its project from the body, so it needs the guard too."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)

    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        created = await client.post(
            f"{API_PREFIX}/requirements/",
            json={
                "project_id": str(project.id),
                "credential_type": "professional_license",
            },
        )

    assert created.status_code == 404, created.text


@pytest.mark.tenant_isolation
async def test_a_credential_cannot_be_planted_on_a_foreign_project(session) -> None:
    """The same hole on the credential side."""
    owner = await make_user(session)
    stranger = await make_user(session)
    project = await make_project(session, owner.id)

    async with http_client(build_app(session, caller_id=stranger.id)) as client:
        created = await client.post(
            f"{API_PREFIX}/",
            json={
                "project_id": str(project.id),
                "holder_name": "Planted",
                "credential_type": "professional_license",
            },
        )

    assert created.status_code == 404, created.text


async def test_the_bare_and_trailing_slash_paths_both_answer(session) -> None:
    """The app runs with ``redirect_slashes=False``.

    A collection route registered in only one of the two forms answers 404 on
    the other, and no redirect rescues it.
    """
    owner = await make_user(session)
    project = await make_project(session, owner.id)
    await make_credential(session, project.id, valid_until=day(5))

    async with http_client(build_app(session, caller_id=owner.id)) as client:
        params = {"project_id": str(project.id)}
        for path in (
            "/expiring-soon",
            "/requirements",
            "/compliance",
            "/summary",
            "/validate",
        ):
            bare = await client.get(f"{API_PREFIX}{path}", params=params)
            slashed = await client.get(f"{API_PREFIX}{path}/", params=params)
            assert bare.status_code == 200, f"{path} bare: {bare.text}"
            assert slashed.status_code == 200, f"{path}/ : {slashed.text}"
