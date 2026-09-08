# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The project record the completeness rules read has to come out of the database.

The unit tests drive each rule with a record written by hand. That proves the
rules, and proves nothing about the half the product actually runs: the shared
payload builder in ``app.core.validation.project_context`` has to read the
project row, list its bills with their row counts, and count its contracts,
employer parties and tender packages, and every one of those is a query that a
unit test cannot execute. A builder that returned a record with the right shape
and the wrong contents would pass every rule test and still put twenty two
dashboards back where they were, showing a completeness check that ran over
nothing.

So the record is built here against a real database and read back field by
field, the rule set is run over it end to end through the engine, and one of
the twenty two demo templates that ask for the set is installed for real and
its persisted report inspected. The last one is the sentence the change was
made for: the demo's dashboard now runs a completeness check and says so.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.validation.engine import Severity, ValidationStatus, validation_engine
from app.core.validation.project_context import PROJECT_RECORD_KEY, with_project_context
from app.core.validation.rules import register_builtin_rules
from app.core.validation.rules.project_completeness import PROJECT_COMPLETENESS_RULE_SET
from app.modules.boq.models import BOQ, Position
from app.modules.contracts.models import Contract, ContractParty
from app.modules.projects.models import Project
from app.modules.tendering.models import TenderPackage
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

#: One of the twenty two demo templates that declare the set. Japanese, so the
#: bill's base date lives in the template metadata and not on the column, which
#: is the shape most of the twenty two share.
_DEMO_ID = "office-tokyo"


@pytest.fixture
def quiet_validation_events() -> Iterator[None]:
    """Detach the validation subscribers that open a session of their own.

    Same reason as the fixture of the same name in the derived-seed tests: the
    detached handlers build a session from the application factory, which this
    lane never binds to the embedded cluster, and a half-opened connection from
    one of them outlives the test and errors every test after it.
    """
    from app.core.events import event_bus

    names = ("validation.report.created", "validation.results.errors_found")
    saved = {name: list(event_bus._handlers.get(name, [])) for name in names}
    for name, handlers in saved.items():
        for handler in handlers:
            event_bus.unsubscribe(name, handler)
    try:
        yield
    finally:
        for name, handlers in saved.items():
            for handler in handlers:
                event_bus.subscribe(name, handler)


async def _owner(session) -> uuid.UUID:
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"completeness-{uuid.uuid4().hex[:8]}@example.test",
            hashed_password="x",
            full_name="Completeness Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    return owner_id


async def _project(session, **fields) -> uuid.UUID:
    """A project stated in full, so a default never stands in for a choice."""
    project_id = uuid.uuid4()
    values = {
        "name": "Quay wall",
        "description": "",
        "region": "DACH",
        "classification_standard": "din276",
        "currency": "EUR",
        "locale": "en",
        "country_code": "DE",
        "status": "active",
        "validation_rule_sets": [PROJECT_COMPLETENESS_RULE_SET],
        "metadata_": {},
    }
    values.update(fields)
    session.add(Project(id=project_id, owner_id=await _owner(session), **values))
    await session.flush()
    return project_id


async def _bill(session, project_id: uuid.UUID, *, rows: int, **fields) -> uuid.UUID:
    boq_id = uuid.uuid4()
    values = {"name": "Estimate", "description": "", "status": "draft", "metadata_": {}}
    values.update(fields)
    session.add(BOQ(id=boq_id, project_id=project_id, **values))
    await session.flush()
    for index in range(rows):
        session.add(
            Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                ordinal=f"01.{index + 1:02d}",
                reference_code=f"01.{index + 1:02d}",
                description=f"Row {index + 1}",
                unit="m3",
                quantity="10",
                unit_rate="25.50",
                total=str(Decimal("10") * Decimal("25.50")),
                metadata_={},
            )
        )
    await session.flush()
    return boq_id


async def test_the_builder_reads_the_project_and_its_bills(pg_session) -> None:
    project_id = await _project(pg_session, planned_start_date="2026-04-01", planned_end_date="2027-03-31")
    boq_id = await _bill(pg_session, project_id, rows=4, metadata_={"base_date": "2026-Q1"})

    payload = await with_project_context(pg_session, project_id, {"positions": []})

    assert payload["positions"] == []
    assert payload["project_unit_system"] == "metric", "the key the builder already carried must survive"
    record = payload[PROJECT_RECORD_KEY]
    assert record is not None
    assert record["id"] == str(project_id)
    assert record["country_code"] == "DE"
    assert record["currency"] == "EUR"
    assert record["classification_standard"] == "din276"
    assert record["planned_start_date"] == "2026-04-01"
    assert record["planned_end_date"] == "2027-03-31"
    assert record["client_id"] is None
    assert record["phase"] is None
    assert record["bills"] == [
        {
            "id": str(boq_id),
            "name": "Estimate",
            "status": "draft",
            "base_date": None,
            "metadata": {"base_date": "2026-Q1"},
            "position_count": 4,
        }
    ]
    assert record["contract_count"] == 0
    assert record["client_party_count"] == 0
    assert record["tender_count"] == 0


async def test_a_variation_bill_is_not_one_of_the_projects_bills(pg_session) -> None:
    """A bill raised for a variation request prices that request, not the project."""
    project_id = await _project(pg_session)
    own = await _bill(pg_session, project_id, rows=2, name="Main estimate")
    await _bill(pg_session, project_id, rows=3, name="Variation 7", variation_request_id=uuid.uuid4())

    record = (await with_project_context(pg_session, project_id, {}))[PROJECT_RECORD_KEY]

    assert [bill["id"] for bill in record["bills"]] == [str(own)]


async def test_an_unknown_project_yields_a_null_record(pg_session) -> None:
    payload = await with_project_context(pg_session, uuid.uuid4(), {"positions": []})
    assert PROJECT_RECORD_KEY in payload
    assert payload[PROJECT_RECORD_KEY] is None


async def test_the_set_runs_end_to_end_and_names_the_gaps(pg_session) -> None:
    """A project with a country, a currency and a dated bill, but no client and no dates."""
    register_builtin_rules()
    project_id = await _project(pg_session)
    await _bill(pg_session, project_id, rows=3, base_date="2026-03-15")

    payload = await with_project_context(pg_session, project_id, {"positions": []})
    report = await validation_engine.validate(
        data=payload,
        rule_sets=[PROJECT_COMPLETENESS_RULE_SET],
        target_type="boq",
        target_id="test",
        project_id=str(project_id),
    )

    assert report.unsupported_rule_sets == [], "the set must resolve to rules, that is the whole point"
    fired = {result.rule_id for result in report.results}
    assert fired == {
        "project_completeness.country_set",
        "project_completeness.currency_set",
        "project_completeness.priced_bill_present",
        "project_completeness.bill_base_date_set",
        "project_completeness.classification_standard_set",
        "project_completeness.planned_dates_set",
        "project_completeness.client_recorded",
    }, sorted(fired)
    failed = {result.rule_id for result in report.results if not result.passed}
    assert failed == {"project_completeness.planned_dates_set", "project_completeness.client_recorded"}, sorted(failed)
    assert report.status == ValidationStatus.WARNINGS
    assert report.score is not None and 0.0 < report.score < 1.0


async def test_a_missing_country_and_currency_are_errors_that_cap_the_score(pg_session) -> None:
    register_builtin_rules()
    project_id = await _project(pg_session, country_code=None, currency="")
    await _bill(pg_session, project_id, rows=1)

    payload = await with_project_context(pg_session, project_id, {"positions": []})
    report = await validation_engine.validate(data=payload, rule_sets=[PROJECT_COMPLETENESS_RULE_SET])

    errors = {result.rule_id for result in report.errors}
    assert errors == {"project_completeness.country_set", "project_completeness.currency_set"}
    assert report.status == ValidationStatus.ERRORS
    # Two blocking errors cap the headline number at 0.5 / (1 + 2), rounded as
    # the engine rounds it, whatever the other rules passed.
    assert report.score == round(0.5 / 3, 4)


async def test_a_contract_employer_and_a_tender_package_answer_the_two_procurement_rules(pg_session) -> None:
    register_builtin_rules()
    project_id = await _project(pg_session, phase="tender", planned_start_date="2026-04-01")
    await _bill(pg_session, project_id, rows=2, base_date="2026-Q1")
    contract_id = uuid.uuid4()
    pg_session.add(
        Contract(
            id=contract_id,
            code=f"C-{uuid.uuid4().hex[:8]}",
            title="Main works",
            project_id=project_id,
            currency="EUR",
            metadata_={},
        )
    )
    await pg_session.flush()
    pg_session.add(
        ContractParty(
            id=uuid.uuid4(),
            contract_id=contract_id,
            party_role="employer",
            display_name="Port authority",
            contact_details={},
            metadata_={},
        )
    )
    pg_session.add(
        TenderPackage(id=uuid.uuid4(), project_id=project_id, name="Package 1", description="", metadata_={})
    )
    await pg_session.flush()

    payload = await with_project_context(pg_session, project_id, {"positions": []})
    record = payload[PROJECT_RECORD_KEY]
    assert (record["contract_count"], record["client_party_count"], record["tender_count"]) == (1, 1, 1)

    report = await validation_engine.validate(data=payload, rule_sets=[PROJECT_COMPLETENESS_RULE_SET])
    by_rule = {result.rule_id: result for result in report.results}
    assert by_rule["project_completeness.client_recorded"].passed, "an employer party is a recorded client"
    assert by_rule["project_completeness.procurement_started"].passed, "a tender package is procurement"
    assert not by_rule["project_completeness.planned_dates_set"].passed, "the end date is still missing"


async def test_a_demo_that_asks_for_the_set_now_gets_a_verdict_from_it(pg_session, quiet_validation_events) -> None:
    """One of the twenty two: installed for real, its persisted report read back.

    Not a count. The demos seed warnings on purpose so the dashboard is never
    empty, so what is asserted is that the set ran (it is no longer listed as
    unsupported and its rules have rows), that none of its two blocking rules
    fired on a template that states its country and currency, and that the
    headline score is still the score of a healthy demo.
    """
    from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
    from app.modules.validation.models import ValidationReport

    assert _DEMO_ID in DEMO_TEMPLATES, f"{_DEMO_ID} is no longer a registered demo"
    assert PROJECT_COMPLETENESS_RULE_SET in DEMO_TEMPLATES[_DEMO_ID].validation_rule_sets, (
        "the demo this test is built on no longer asks for the set"
    )

    result = await install_demo_project(pg_session, _DEMO_ID, force_reinstall=True)
    project_id = uuid.UUID(str(result["project_id"]))
    reports = (
        (await pg_session.execute(select(ValidationReport).where(ValidationReport.project_id == project_id)))
        .scalars()
        .all()
    )
    assert reports, "the demo install seeded no validation report at all"
    report = next(r for r in reports if PROJECT_COMPLETENESS_RULE_SET in (r.metadata_ or {}).get("rule_sets", []))

    assert PROJECT_COMPLETENESS_RULE_SET not in (report.metadata_ or {}).get("unsupported_rule_sets", [])
    assert PROJECT_COMPLETENESS_RULE_SET in (report.metadata_ or {}).get("supported_rule_sets", [])
    ours = [row for row in report.results if str(row["rule_id"]).startswith(PROJECT_COMPLETENESS_RULE_SET + ".")]
    print(f"\nPOPULATION: {len(report.results)} rows in the report, {len(ours)} from {PROJECT_COMPLETENESS_RULE_SET}")
    assert ours, "the set is listed as supported and produced no rows"
    blocking = [row for row in ours if row["severity"] == Severity.ERROR.value and not row["passed"]]
    assert not blocking, f"a demo that states its country and currency tripped a blocking rule: {blocking}"
    assert report.status in {"passed", "warnings"}, report.status
    assert report.score is not None and float(report.score) >= 0.9, report.score
