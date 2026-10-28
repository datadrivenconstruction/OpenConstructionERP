# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Authored clause templates: the union, the freeze, and the pinned version.

Three things here can only be checked against a database, which is why this
file lives in the PostgreSQL lane rather than beside the pure-function tests.

The union. The catalogue a user picks from has two halves that are stored
completely differently: eleven built-in standard forms that are module
constants, and the tenant's own paper, which is rows. They meet in exactly one
method, ``ContractTemplateRepository.list_all``, and the invariant that matters
is that no code ever appears twice across the two. No unique index can enforce
that, because half the namespace is not in the database, so it is checked here.

The freeze. Publishing a version makes it immutable and the next edit opens
N+1. That is a rule about rows in two states plus a real unique constraint on
(code, version), and a stub cannot tell you whether the constraint exists.

The pin. A contract stores which template version it was drawn from, and has to
keep saying that after a later version is published. Testing it needs a
contract row, a template row and a second template row.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.contracts.models import TEMPLATE_STATUSES, ContractTemplate
from app.modules.contracts.schemas import ContractCreate, ContractTemplateCreate, TemplateClauseInput
from app.modules.contracts.service import CONTRACT_CLAUSE_TEMPLATES, ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User


def _unique(prefix: str) -> str:
    """A code no other test in this session can collide with."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _project(session) -> tuple[uuid.UUID, str]:
    owner = User(
        email=f"tpl-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Template Owner",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Template versioning", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project.id, str(owner.id)


def _draft(code: str, *, clauses: int = 2) -> ContractTemplateCreate:
    return ContractTemplateCreate(
        code=code,
        name="Site works, own paper",
        family="own",
        description="",
        retention_release_event="practical_completion",
        clauses=[
            TemplateClauseInput(
                number=f"{index + 1}.0",
                title=f"Clause {index + 1}",
                body="Body text.",
                risk_level="none",
            )
            for index in range(clauses)
        ],
    )


# ── The union ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalogue_carries_every_builtin_before_anything_is_authored(pg_session) -> None:
    """With an empty table the catalogue is exactly the built-in constants.

    This is the half that has no rows. If a future change seeds the constants
    into the table, this test still passes on count but the source flag flips,
    which is the point of asserting it.
    """
    service = ContractsService(pg_session)
    entries = await service.list_templates()

    builtin = [entry for entry in entries if entry["source"] == "builtin"]
    assert {entry["code"] for entry in builtin} == set(CONTRACT_CLAUSE_TEMPLATES)
    for entry in builtin:
        assert entry["editable"] is False, f"{entry['code']} is a constant and cannot be edited"
        # Zero rather than null, so a caller can sort and compare the field
        # without branching on its type.
        assert entry["version"] == 0
        assert entry["clause_count"] > 0


@pytest.mark.asyncio
async def test_catalogue_never_carries_one_code_twice(pg_session) -> None:
    """The invariant no database constraint can express.

    Built-in codes are constants, authored codes are rows, and nothing can
    index across the two. The check that keeps them apart is a function every
    write path calls; this asserts the property that function exists for.
    """
    service = ContractsService(pg_session)
    await service.create_template(_draft(_unique("own-a")), "u1")
    await service.create_template(_draft(_unique("own-b")), "u1")
    await pg_session.flush()

    codes = [entry["code"] for entry in await service.list_templates()]
    assert len(codes) == len(set(codes)), f"duplicate code in the catalogue: {codes}"


@pytest.mark.asyncio
async def test_authored_template_may_not_shadow_a_builtin_code(pg_session) -> None:
    service = ContractsService(pg_session)
    builtin_code = next(iter(CONTRACT_CLAUSE_TEMPLATES))

    with pytest.raises(HTTPException) as excinfo:
        await service.create_template(_draft(builtin_code), "u1")
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "template_code_is_builtin"


@pytest.mark.asyncio
async def test_authored_code_cannot_be_taken_twice(pg_session) -> None:
    service = ContractsService(pg_session)
    code = _unique("own-dup")
    await service.create_template(_draft(code), "u1")
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.create_template(_draft(code), "u1")
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "template_code_taken"


@pytest.mark.asyncio
async def test_forking_a_builtin_yields_an_editable_copy_with_its_clause_numbers(pg_session) -> None:
    """A built-in is changed by forking it, never in place.

    The shipped clause map is numbers and titles with no body text, so the
    fork starts with headings and empty bodies. Asserting the empty body is
    deliberate: filling it would mean we invented contract language.
    """
    service = ContractsService(pg_session)
    builtin_code = "fidic_red_1999"
    new_code = _unique("house-red")

    forked = await service.fork_builtin_template(builtin_code, new_code, "u1")
    await pg_session.flush()

    assert forked["derived_from_builtin"] == builtin_code
    assert forked["editable"] is True
    assert forked["version"] == 1
    numbers = {clause["number"] for clause in forked["clauses"]}
    assert numbers == set(CONTRACT_CLAUSE_TEMPLATES[builtin_code]["key_clauses"])
    assert all(clause["body"] == "" for clause in forked["clauses"])


# ── The freeze ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_empty_template_cannot_be_published(pg_session) -> None:
    """A contract must not be able to say it came from a document that says nothing."""
    service = ContractsService(pg_session)
    code = _unique("own-empty")
    await service.create_template(_draft(code, clauses=0), "u1")
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.publish_template(code, 1, "u1")
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["error"] == "template_has_no_clauses"


@pytest.mark.asyncio
async def test_published_version_refuses_edits_and_opens_the_next_one(pg_session) -> None:
    service = ContractsService(pg_session)
    code = _unique("own-freeze")
    await service.create_template(_draft(code), "u1")
    await pg_session.flush()
    await service.publish_template(code, 1, "u1")
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.update_template(code, 1, {"name": "Renamed after publishing"})
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "template_version_frozen"

    second = await service.open_next_template_version(code, "u1")
    await pg_session.flush()
    assert second["version"] == 2
    assert second["status"] == "draft"


@pytest.mark.asyncio
async def test_next_version_copies_clauses_by_value(pg_session) -> None:
    """Editing v2 must not rewrite what v1 says.

    Sharing clause rows between versions would make the published version
    follow its successor, which is the exact failure versioning exists to
    prevent, and it would look correct in every list view.
    """
    service = ContractsService(pg_session)
    code = _unique("own-copy")
    await service.create_template(_draft(code), "u1")
    await pg_session.flush()
    v1 = await service.publish_template(code, 1, "u1")
    await pg_session.flush()

    await service.open_next_template_version(code, "u1")
    await pg_session.flush()
    await service.replace_template_clauses(
        code,
        2,
        [TemplateClauseInput(number="1.0", title="Rewritten in v2", body="New body.")],
    )
    await pg_session.flush()

    v1_again = await service.get_template(code, version=1)
    assert [clause["title"] for clause in v1_again["clauses"]] == [clause["title"] for clause in v1["clauses"]], (
        "publishing froze v1, so editing v2 must leave it untouched"
    )

    v1_ids = {clause["id"] for clause in v1_again["clauses"]}
    v2 = await service.get_template(code, version=2)
    assert v1_ids.isdisjoint({clause["id"] for clause in v2["clauses"]})


@pytest.mark.asyncio
async def test_a_second_open_draft_is_refused(pg_session) -> None:
    """One open draft per lineage, or there is no answer to "the next version"."""
    service = ContractsService(pg_session)
    code = _unique("own-onedraft")
    await service.create_template(_draft(code), "u1")
    await pg_session.flush()
    await service.publish_template(code, 1, "u1")
    await pg_session.flush()
    await service.open_next_template_version(code, "u1")
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.open_next_template_version(code, "u1")
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "template_draft_already_open"


@pytest.mark.asyncio
async def test_code_and_version_are_unique_together_in_the_database(pg_session) -> None:
    """The half of the rule that IS a constraint, asserted against the constraint.

    A service-level check would pass this test whether or not the index was
    ever created, which is why the row is inserted straight into the table.
    """
    service = ContractsService(pg_session)
    code = _unique("own-uq")
    created = await service.create_template(_draft(code), "u1")
    await pg_session.flush()

    pg_session.add(
        ContractTemplate(
            code=code,
            version=1,
            lineage_id=uuid.UUID(created["lineage_id"]),
            name="Collides with version 1",
            family="own",
            retention_release_event="practical_completion",
            status="draft",
        )
    )
    with pytest.raises(IntegrityError):
        await pg_session.flush()
    await pg_session.rollback()


@pytest.mark.asyncio
async def test_current_version_is_the_latest_published_not_the_open_draft(pg_session) -> None:
    """A draft in progress must not be what new contracts are drawn from."""
    service = ContractsService(pg_session)
    code = _unique("own-current")
    await service.create_template(_draft(code), "u1")
    await pg_session.flush()
    await service.publish_template(code, 1, "u1")
    await pg_session.flush()
    await service.open_next_template_version(code, "u1")
    await pg_session.flush()

    entry = next(e for e in await service.list_templates() if e["code"] == code)
    assert entry["version"] == 1
    assert entry["status"] == "published"

    await service.publish_template(code, 2, "u1")
    await pg_session.flush()
    entry = next(e for e in await service.list_templates() if e["code"] == code)
    assert entry["version"] == 2


@pytest.mark.asyncio
async def test_archiving_takes_a_lineage_out_of_the_catalogue(pg_session) -> None:
    """Retiring paper has to be visible, so an archived version is never current."""
    service = ContractsService(pg_session)
    code = _unique("own-archive")
    await service.create_template(_draft(code), "u1")
    await pg_session.flush()
    await service.publish_template(code, 1, "u1")
    await pg_session.flush()
    await service.archive_template_version(code, 1)
    await pg_session.flush()

    assert all(entry["code"] != code for entry in await service.list_templates())
    # Archived is not deleted: a contract drawn from it still has to resolve.
    assert (await service.get_template(code, version=1))["status"] == "archived"


# ── The pin ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contract_pins_the_version_it_was_drawn_from(pg_session) -> None:
    """Publishing v2 must not change what an existing contract says it used."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    code = _unique("own-pin")
    await service.create_template(_draft(code), user_id)
    await pg_session.flush()
    await service.publish_template(code, 1, user_id)
    await pg_session.flush()

    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Drawn from version 1",
            contract_type="lump_sum",
            project_id=project_id,
            template_code=code,
        ),
        user_id,
    )
    await pg_session.flush()
    assert contract.template_code == code
    assert contract.template_version == 1

    await service.open_next_template_version(code, user_id)
    await pg_session.flush()
    await service.publish_template(code, 2, user_id)
    await pg_session.flush()

    stored = (
        (
            await pg_session.execute(
                select(ContractTemplate.version).where(
                    ContractTemplate.code == code, ContractTemplate.status == "published"
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(stored) == [1, 2]
    reread = await service.get_contract(contract.id)
    assert reread.template_version == 1, "the contract must keep naming the version its author saw"


@pytest.mark.asyncio
async def test_a_builtin_pins_version_zero_so_the_pair_is_never_half_filled(pg_session) -> None:
    """Built-ins have no versions, and a null there would mean "whatever is current"."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)

    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Drawn from a standard form",
            contract_type="lump_sum",
            project_id=project_id,
            template_code="jct_standard_2016",
        ),
        user_id,
    )
    await pg_session.flush()
    assert contract.template_code == "jct_standard_2016"
    assert contract.template_version == 0


@pytest.mark.asyncio
async def test_a_contract_cannot_be_drawn_from_an_unpublished_draft(pg_session) -> None:
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    code = _unique("own-unpub")
    await service.create_template(_draft(code), user_id)
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.create_contract(
            ContractCreate(
                code=_unique("C"),
                title="Drawn from a draft",
                contract_type="lump_sum",
                project_id=project_id,
                template_code=code,
            ),
            user_id,
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["error"] == "template_not_published"


@pytest.mark.asyncio
async def test_a_contract_without_a_template_stores_neither_half(pg_session) -> None:
    """Most contracts are written from scratch, and that has to stay legal."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)

    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="No template",
            contract_type="lump_sum",
            project_id=project_id,
        ),
        user_id,
    )
    await pg_session.flush()
    assert contract.template_code is None
    assert contract.template_version is None


# ── The declared domain ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_status_the_api_yields_is_inside_the_declared_domain(pg_session) -> None:
    """``TEMPLATE_STATUSES`` is the domain of the column; this is what reads it.

    A status is never accepted from a request, so no schema pattern guards it.
    It is written by creating, publishing, opening the next version and
    archiving, and read back by three endpoints. Walking a lineage through all
    four writes and collecting what comes out of all three reads is the only
    place the constant and the code that sets it actually meet.
    """
    _, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    code = _unique("own-domain")

    seen: set[str] = set()

    def _collect(payload) -> None:
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            status_value = row["status"]
            assert status_value in TEMPLATE_STATUSES, (code, status_value)
            # A built-in reports "published" and is never editable; an authored
            # row is editable exactly while it is a draft. Checking the pair
            # together is what stops a published version being offered with a
            # pencil on it.
            assert row["editable"] is (row["source"] == "authored" and status_value == "draft")
            seen.add(status_value)

    _collect(await service.create_template(_draft(code), user_id))
    await pg_session.flush()
    _collect(await service.list_templates())

    _collect(await service.publish_template(code, 1, user_id))
    await pg_session.flush()
    _collect(await service.open_next_template_version(code, user_id))
    await pg_session.flush()
    _collect(await service.list_template_versions(code))
    _collect(await service.get_template(code))

    _collect(await service.archive_template_version(code, 2))
    await pg_session.flush()
    _collect(await service.list_template_versions(code))

    # All three were reached, so the assertion above was not vacuous on any of
    # them: a set that only ever held "draft" would pass just as quietly.
    assert seen == set(TEMPLATE_STATUSES)
