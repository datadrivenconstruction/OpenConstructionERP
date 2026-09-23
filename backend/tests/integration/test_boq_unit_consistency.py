# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration test: BOQUnitSystemConsistencyRule fires WARNING for mismatched units.

Wave 24 (#167) — task: seed an imperial project, create a BOQ position with a
metric unit, assert the validation rule fires a WARNING.

Repointed at the shipped mechanism. The first test used to create a project
with ``unit_system='imperial'`` and assert the API echoed it back. No such
field was ever implemented — not on the model, not in the schema — so the
assertion could not pass, and the test then went on to validate a hand-built
context that ignored the project and BOQ it had just created. It proved the
rule could be called, not that anything reaches it.

The unit system now comes from the project's regional pack: the project
carries ``country_code``, ``app.core.regional_packs`` resolves that to the
pack claiming the country, and the pack's declared ``measurement_system``
becomes ``project_unit_system`` for the run. So the imperial project below is
created by setting ``country_code='US'`` — us_pack declares imperial — and the
assertion runs through ``POST /validation/run/`` against the stored BOQ rather
than against a dict written in the test. The behaviour being asserted is
unchanged: a metric unit in an imperial project is exactly one WARNING, not an
ERROR and not a pass.

Open question, deliberately not settled here: whether a project should also be
able to override its pack's measurement system directly. The abandoned
``unit_system`` field was that design. Repointing these tests at the pack is
not a decision against the override — it is only a statement of what ships
today. If a per-project override lands later, this file is where its
precedence over the pack belongs.

Pattern mirrors test_boq_bim_qty_source_roundtrip.py: register + promote +
login + project + BOQ + position + validate.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

#: The field the suggestion is allowed to send a reader to, and the one it is
#: not. ``unit_system`` is the name the advice used to give: a column the
#: migration chain adds and no supported install has, absent from ``Project``,
#: from ``ProjectCreate`` and ``ProjectUpdate``, and from every screen. What
#: actually decides the answer is the project's country, through the regional
#: pack that claims it. Both halves are pinned because only the second one was
#: ever wrong, and an unpinned field name is free to go wrong again.
#:
#: The banned spelling is the underscored column name. Prose that says a
#: project has no "unit-system field" is the opposite claim and is welcome; it
#: is the identifier that must not come back.
_DECIDING_FIELD = "country"
_ABANDONED_FIELD = "unit_system"


def _names_the_deciding_field(suggestion: str | None) -> bool:
    """True when ``suggestion`` sends the reader to the country, not to a phantom field."""
    if not suggestion:
        return False
    lowered = suggestion.lower()
    return _DECIDING_FIELD in lowered and _ABANDONED_FIELD not in lowered


@pytest_asyncio.fixture(scope="module")
async def shared_client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(shared_client: AsyncClient) -> dict[str, str]:
    """Register + promote-to-admin + login."""
    unique = uuid.uuid4().hex[:8]
    email = f"unitcons-{unique}@test.io"
    password = f"UnitCons{unique}9!"
    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "UnitConsistency Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    login = await shared_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_boq_unit_system_consistency_rule_fires_warning(
    shared_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Seed an imperial project, add a m³ BOQ position, run validation over the
    stored BOQ; assert WARNING is returned (not ERROR, not pass).

    The project is imperial because ``country_code='US'`` resolves to us_pack,
    which declares ``measurement_system: "imperial"``. Nothing in this test
    tells the engine which system to use — that is the point. The request body
    carries only the project, the BOQ and the rule set.
    """
    # ── Create an imperial project ────────────────────────────────────────────
    # Imperial by country, not by a per-project flag: us_pack claims "US" and
    # declares imperial, and that is what the run below has to pick up.
    proj = await shared_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Imperial Project {uuid.uuid4().hex[:6]}",
            "country_code": "US",
        },
        headers=auth_headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_data = proj.json()
    project_id = project_data["id"]

    # The stored country is what the resolver reads, so a silently dropped
    # country_code would make the rest of this test vacuous.
    assert project_data.get("country_code") == "US", (
        f"Expected country_code='US', got: {project_data.get('country_code')}"
    )

    # ── Create a BOQ for the project ─────────────────────────────────────────
    boq = await shared_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Imperial BOQ"},
        headers=auth_headers,
    )
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]

    # ── Create a position with metric unit m³ (wrong for imperial project) ───
    pos = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete pour (should be ft³ not m³)",
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 0.0,
        },
        headers=auth_headers,
    )
    assert pos.status_code in (200, 201), pos.text

    # ── Validate the stored BOQ through the real endpoint ────────────────────
    # Note what is NOT in this body: no unit system. The service derives it
    # from the project's country via the regional pack.
    run = await shared_client.post(
        "/api/v1/validation/run/",
        json={"project_id": project_id, "boq_id": boq_id, "rule_sets": ["boq_quality"]},
        headers=auth_headers,
    )
    assert run.status_code in (200, 201), run.text

    # ── Assertions ────────────────────────────────────────────────────────────
    results = [r for r in run.json()["results"] if r["rule_id"] == "boq_quality.unit_system_consistency"]
    assert len(results) == 1, f"Expected 1 unit-system result, got {len(results)}"
    result = results[0]
    # The endpoint reports one ``status`` per result: "pass" when the rule
    # passed, otherwise the severity. So "warning" asserts both halves of what
    # this test is for - it fired, and it fired as a WARNING rather than an
    # ERROR that would block the bill.
    assert result["status"] == "warning", f"Expected a WARNING, got status={result['status']}: {result['message']}"
    # Both system names, plus the offending unit. The rule's own comment claims
    # exactly this of its message, and until now the claim was unbacked: the
    # assertion here read "imperial OR metric", which a message naming only one
    # of the two would have satisfied. An unbacked claim about a string is what
    # let the suggestion beside it name a field that does not exist.
    lowered = result["message"].lower()
    assert "imperial" in lowered and "metric" in lowered, (
        f"Expected both unit system names in message: {result['message']}"
    )
    assert "m3" in lowered or "01.001" in lowered, (
        f"Expected the offending unit or its ordinal in message: {result['message']}"
    )
    assert result["details"].get("mismatch_count") == 1, f"Expected 1 mismatch, got: {result['details']}"
    # The pack's declared value, not anything this test sent.
    assert result["details"].get("project_unit_system") == "imperial", (
        f"Unit system should have come from us_pack, got: {result['details']}"
    )
    # The advice travels to the caller too, and it has to name something the
    # caller can go and look at - see test_suggestion_names_the_field_that
    # _decides_the_unit_system below for why this is asserted at all.
    assert _names_the_deciding_field(result.get("suggestion")), (
        f"Suggestion must name the project's country, not a unit_system field: {result.get('suggestion')}"
    )


@pytest.mark.asyncio
async def test_imperial_project_imperial_units_passes(shared_client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Imperial project with sqft unit must not trigger the rule."""
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules import BOQUnitSystemConsistencyRule

    rule = BOQUnitSystemConsistencyRule()
    ctx = ValidationContext(
        data={
            "positions": [
                {"ordinal": "01.001", "unit": "sqft"},
                {"ordinal": "01.002", "unit": "ft"},
                {"ordinal": "01.003", "unit": "lb"},
            ],
            "project_unit_system": "imperial",
        }
    )
    results = await rule.validate(ctx)
    assert results[0].passed is True, f"Should pass for imperial units in imperial project: {results[0].message}"


@pytest.mark.asyncio
async def test_metric_project_metric_units_passes(shared_client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Metric project with m², m³, kg must not trigger the rule."""
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules import BOQUnitSystemConsistencyRule

    rule = BOQUnitSystemConsistencyRule()
    ctx = ValidationContext(
        data={
            "positions": [
                {"ordinal": "01.001", "unit": "m2"},
                {"ordinal": "01.002", "unit": "m3"},
                {"ordinal": "01.003", "unit": "kg"},
            ],
            "project_unit_system": "metric",
        }
    )
    results = await rule.validate(ctx)
    assert results[0].passed is True, f"Should pass for metric units in metric project: {results[0].message}"


@pytest.mark.asyncio
async def test_suggestion_names_the_field_that_decides_the_unit_system() -> None:
    """The advice on a mismatch must name the country, never a ``unit_system`` field.

    No database and no client: the rule is handed a payload directly, so this
    runs wherever pytest does and can be proved before the change is pushed.

    What it guards is a defect that no verdict-level assertion can see. The
    rule fired correctly the whole time it was telling readers to "update the
    project's unit_system", because a suggestion changes no verdict - it is
    read by a person, who then goes looking for a field that is on no screen,
    in no schema and, on every supported install, in no table either.
    """
    from app.core.validation.engine import Severity, ValidationContext
    from app.core.validation.rules import BOQUnitSystemConsistencyRule

    rule = BOQUnitSystemConsistencyRule()
    ctx = ValidationContext(
        data={
            "positions": [{"ordinal": "01.001", "unit": "m3"}],
            "project_unit_system": "imperial",
        }
    )
    results = await rule.validate(ctx)
    assert len(results) == 1, f"Expected one result, got {len(results)}"
    result = results[0]
    # The verdict half is asserted here as well, so a later edit to the wording
    # cannot quietly arrive with a changed severity or a flipped pass.
    assert result.passed is False, "a metric unit on an imperial project is a mismatch"
    assert result.severity is Severity.WARNING, f"must stay a WARNING, got {result.severity}"
    assert _names_the_deciding_field(result.suggestion), (
        f"Suggestion must name the project's country, not a unit_system field: {result.suggestion}"
    )
    # Naming the country is not enough on its own: the reader also has to be
    # told the conversion is the move that is always open to them, because the
    # country is picked when the project is created and no settings screen
    # offers it afterwards.
    assert "convert" in (result.suggestion or "").lower(), (
        f"Suggestion must lead with the action the reader can always take: {result.suggestion}"
    )


def _verdicts(results: list[dict]) -> dict[str, bool]:
    """Rule id to pass/fail, whichever shape the surface returns it in.

    The two endpoints render a verdict differently - one sends ``passed`` as a
    boolean, the other a ``status`` string that is ``"pass"`` or the severity
    of the failure. That is a presentation difference and not the subject
    here, so it is normalised rather than asserted on.
    """
    verdicts: dict[str, bool] = {}
    for row in results:
        if "passed" in row:
            verdicts[row["rule_id"]] = bool(row["passed"])
        else:
            verdicts[row["rule_id"]] = row["status"] == "pass"
    return verdicts


@pytest.mark.asyncio
async def test_both_bill_validation_surfaces_agree_on_the_same_bill(
    shared_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """One bill, two shipped surfaces, one verdict.

    ``POST /validation/run/`` and ``POST /boq/boqs/{id}/validate/`` are both
    ways a user validates the same bill, and they built their engine payloads
    separately. Only one of them carried the project's measurement system, so
    the same imperial project answered "one warning" through the estimate audit
    and "clean" behind the Validate button - a difference no report showed,
    because a rule that is not given its input returns nothing rather than
    failing.

    The two resolve their rule sets differently on purpose (this endpoint takes
    the caller's list, that one derives it from the project's configuration), so
    what is asserted is the part that is comparable: every rule both reports
    carry must reach the same verdict, and the measurement-system rule must be
    one of them.
    """
    proj = await shared_client.post(
        "/api/v1/projects/",
        json={"name": f"Two Surfaces {uuid.uuid4().hex[:6]}", "country_code": "US"},
        headers=auth_headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    boq = await shared_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Two Surfaces BOQ"},
        headers=auth_headers,
    )
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]

    pos = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete pour in the wrong measurement system",
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 0.0,
        },
        headers=auth_headers,
    )
    assert pos.status_code in (200, 201), pos.text

    run = await shared_client.post(
        "/api/v1/validation/run/",
        json={"project_id": project_id, "boq_id": boq_id, "rule_sets": ["boq_quality"]},
        headers=auth_headers,
    )
    assert run.status_code in (200, 201), run.text
    through_service = _verdicts(run.json()["results"])

    endpoint = await shared_client.post(f"/api/v1/boq/boqs/{boq_id}/validate/", json={}, headers=auth_headers)
    assert endpoint.status_code in (200, 201), endpoint.text
    through_endpoint = _verdicts(endpoint.json()["results"])

    rule_id = "boq_quality.unit_system_consistency"
    assert rule_id in through_service, f"the service run lost the rule: {sorted(through_service)}"
    assert rule_id in through_endpoint, (
        "the Validate button reached the engine without the project's measurement system, "
        f"so the rule was silent there: {sorted(through_endpoint)}"
    )

    shared = sorted(set(through_service) & set(through_endpoint))
    assert len(shared) > 1, f"the two surfaces share too few rules to compare: {shared}"
    disagreeing = {
        name: {"service": through_service[name], "endpoint": through_endpoint[name]}
        for name in shared
        if through_service[name] != through_endpoint[name]
    }
    assert not disagreeing, f"the same bill got two different verdicts: {disagreeing}"
    assert through_endpoint[rule_id] is False, "the metric position in a US project must be flagged on both surfaces"
