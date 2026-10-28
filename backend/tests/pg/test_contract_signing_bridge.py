# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Contracts put up for signature: the reference, the gate and the re-hash.

Everything here needs two modules' tables at once, which is why it is in the
PostgreSQL lane rather than beside the pure-function tests.

The reference. A signing session is filed under ``contract:{id}`` and nothing
else knows how to find it. If the reference the writer builds and the reference
the reader queries ever drift apart, every screen goes quietly empty rather than
failing, so the round trip is asserted through the service rather than assumed
from the constant.

The gate. Running the compliance gate at session initiation is the point of the
whole endpoint: the same gate also guards ``draft -> active``, but by then
everyone has signed. A test that only proved the transition is gated would pass
on a version where the initiation check was deleted.

There are two gates at initiation, and the second one is why these tests carry
a rule registration of their own. The schedule of values is checked by the
project's compliance packs; the contract itself - who is on the register, what
the template pin says - is checked by this module's own ``contracts`` rule set,
which a contract with nobody who signs fails. That rule set is registered from
the module package's startup hook, and a test process starts no application, so
without the fixture below the gate would find no rules and refuse everything as
uncheckable.

The re-hash. ``signing.delta_by_hash`` can only ever report a stale signature if
somebody pushes a new content hash when the paper changes, and the signing module
cannot do that because it has no way to look at a contract. So the duty sits on
``update_contract``, and this file is what proves the machinery can actually
fire. Delete the ``refresh_signing_content_hash`` call and only this test goes
red; every other check on both modules stays green while the staleness feature
is structurally dead.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.contracts import signing_bridge
from app.modules.contracts.models import ContractParty
from app.modules.contracts.schemas import ContractCreate, ContractUpdate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.signing.schemas import AttestationCreate
from app.modules.signing.service import SigningService
from app.modules.users.models import User


@pytest.fixture(autouse=True)
def _contracts_rules_registered() -> None:
    """Register this module's rule set, as the module loader does on boot.

    Per test rather than per module: the registry is process-global and a
    suite that empties it would otherwise leave every test after it grading
    contracts against nothing. Registration overwrites, so repeating it costs
    a dict write.
    """
    register_contracts_validation_rules()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _project(session) -> tuple[uuid.UUID, str]:
    owner = User(
        email=f"sign-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Signing Owner",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Contract signing", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project.id, str(owner.id)


async def _contract_with_parties(session, service: ContractsService, user_id: str, project_id: uuid.UUID):
    """A draft contract with an employer and a contractor on its party register."""
    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Signing bridge",
            contract_type="lump_sum",
            project_id=project_id,
            total_value=Decimal("250000.00"),
            currency="EUR",
        ),
        user_id,
    )
    await session.flush()
    session.add_all(
        [
            ContractParty(
                contract_id=contract.id,
                party_role="employer",
                party_type="external",
                display_name="Northlake Estates",
                is_primary=True,
            ),
            ContractParty(
                contract_id=contract.id,
                party_role="contractor",
                party_type="external",
                display_name="Bramwell Civil Works",
            ),
        ]
    )
    await session.flush()
    return contract


# ── The reference and the derived map ─────────────────────────────────────


@pytest.mark.asyncio
async def test_a_session_is_filed_under_the_contract_and_signatories_come_from_the_parties(
    pg_session,
) -> None:
    """Opening a session and finding it again have to agree on one reference."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await _contract_with_parties(pg_session, service, user_id, project_id)

    row = await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()

    assert row.document_ref == signing_bridge.contract_document_ref(contract.id)
    assert signing_bridge.parse_contract_document_ref(row.document_ref) == contract.id
    assert row.project_id == contract.project_id

    # Derived from the register, in signature-block order, both required.
    roles = [entry["role"] for entry in row.signatory_map]
    names = [entry["name"] for entry in row.signatory_map]
    assert roles == ["employer", "contractor"]
    assert names == ["Northlake Estates", "Bramwell Civil Works"]
    assert all(entry["required"] for entry in row.signatory_map)

    # The read path finds it by the same reference the write path built.
    found = await service.list_signing_sessions(contract.id)
    assert [s.id for s in found] == [row.id]


@pytest.mark.asyncio
async def test_a_contract_with_nobody_on_its_party_register_is_refused(pg_session) -> None:
    """No parties means no signatories, and a session without those is theatre.

    Every other test in this file builds a contract *with* parties, which is
    exactly how an earlier version shipped a fallback that invented one: it
    named the signatory after the contract's own title, so the register would
    have recorded that a party named "Signing bridge" executed the paper called
    "Signing bridge". Nothing in the suite touched the branch, and the screen
    showed the invented name as though it were a company.

    The refusal is now the rule set's answer rather than prose written at the
    call site, which is what the assertions below are really about: the body
    names the rule, so the same finding is on the completeness panel before
    anybody presses anything, and the toast still reads as a sentence.
    """
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Signing bridge",
            contract_type="lump_sum",
            project_id=project_id,
            total_value=Decimal("250000.00"),
            currency="EUR",
        ),
        user_id,
    )
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.open_signing_session(contract.id, actor_id=user_id)
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert detail["error"] == "compliance_gate_failed"
    assert [e["rule_id"] for e in detail["errors"]] == ["contracts.parties_complete"]
    assert all(e["suggestion"] for e in detail["errors"])
    # The toast has to say what is wrong, not only that something is. A message
    # naming the rule set and nothing else sends the reader back to the panel to
    # find out what they were stopped for.
    assert "parties that sign it" in detail["message"]

    # The same rules, run through the endpoint the screen polls, say the same
    # thing. This is the half that makes it a compliance rule rather than a
    # wall: a user who never presses the button still sees it.
    report = await service.validate_contract_completeness(contract.id)
    assert report["status"] == "errors"
    assert [e["rule_id"] for e in report["errors"]] == ["contracts.parties_complete"]

    # And nothing was filed: a refused attempt leaves no session behind.
    assert await service.list_signing_sessions(contract.id) == []


@pytest.mark.asyncio
async def test_a_party_who_does_not_sign_does_not_make_a_contract_signable(pg_session) -> None:
    """A consultant on the register is not a signatory to the contract."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Consultant only",
            contract_type="lump_sum",
            project_id=project_id,
            total_value=Decimal("10000.00"),
            currency="EUR",
        ),
        user_id,
    )
    await pg_session.flush()
    pg_session.add(
        ContractParty(
            contract_id=contract.id,
            party_role="consultant",
            party_type="external",
            display_name="Harkness Cost Consultancy",
        )
    )
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.open_signing_session(contract.id, actor_id=user_id)
    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["error"] == "compliance_gate_failed"


@pytest.mark.asyncio
async def test_a_subcontract_is_signable_without_an_employer(pg_session) -> None:
    """The register shape the gate must not refuse.

    A subcontract is executed by the main contractor buying the work and the
    firm selling it. The employer is not a party to it. Every signing test in
    this file until now built a main contract, so a party rule that asked for a
    named employer looked correct here while refusing the press on every
    subcontract in the product - including the draft the demo seeds so the
    signing path can be shown at all.
    """
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Groundworks subcontract",
            contract_type="remeasurement",
            project_id=project_id,
            total_value=Decimal("75000.00"),
            currency="EUR",
        ),
        user_id,
    )
    await pg_session.flush()
    pg_session.add_all(
        [
            ContractParty(
                contract_id=contract.id,
                party_role="contractor",
                party_type="external",
                display_name="Bramwell Civil Works",
                is_primary=True,
            ),
            ContractParty(
                contract_id=contract.id,
                party_role="subcontractor",
                party_type="external",
                display_name="Ferrow Groundworks",
            ),
        ]
    )
    await pg_session.flush()

    row = await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()

    assert [entry["role"] for entry in row.signatory_map] == ["contractor", "subcontractor"]
    assert [entry["name"] for entry in row.signatory_map] == ["Bramwell Civil Works", "Ferrow Groundworks"]


@pytest.mark.asyncio
async def test_a_party_entered_as_a_link_signs_under_the_name_it_links_to(pg_session) -> None:
    """A party row can be a link instead of typed text, and then it has no name.

    The signature block used to read the stored field alone, so a register that
    named the employer on screen through the linked row was empty to signing.
    The rule that guards the press reads the same resolved name the block does,
    which is the only reason it can be trusted to decide the press: a rule and a
    bridge that disagree about who is on the register would either refuse a
    signable contract or wave through a session naming nobody.
    """
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await service.create_contract(
        ContractCreate(
            code=_unique("C"),
            title="Linked party",
            contract_type="lump_sum",
            project_id=project_id,
            total_value=Decimal("75000.00"),
            currency="EUR",
        ),
        user_id,
    )
    await pg_session.flush()
    pg_session.add_all(
        [
            ContractParty(
                contract_id=contract.id,
                party_role="employer",
                party_type="user",
                party_id=uuid.UUID(user_id),
                display_name="",
            ),
            ContractParty(
                contract_id=contract.id,
                party_role="contractor",
                party_type="external",
                display_name="Bramwell Civil Works",
            ),
        ]
    )
    await pg_session.flush()

    row = await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()

    assert [entry["role"] for entry in row.signatory_map] == ["employer", "contractor"]
    assert [entry["name"] for entry in row.signatory_map] == ["Signing Owner", "Bramwell Civil Works"]


@pytest.mark.asyncio
async def test_a_second_session_is_refused_while_one_is_outstanding(pg_session) -> None:
    """Two open sessions would give one contract two hashes and no tie-break."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await _contract_with_parties(pg_session, service, user_id, project_id)

    await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.open_signing_session(contract.id, actor_id=user_id)
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_a_contract_that_has_left_draft_cannot_be_put_up_for_signature(pg_session) -> None:
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    contract = await _contract_with_parties(pg_session, service, user_id, project_id)

    await service.transition_contract(contract.id, "active", user_id)
    await pg_session.flush()

    with pytest.raises(HTTPException) as excinfo:
        await service.open_signing_session(contract.id, actor_id=user_id)
    assert excinfo.value.status_code == 400


# ── The re-hash ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_editing_the_contract_makes_the_signatures_collected_so_far_stale(pg_session) -> None:
    """The one check that proves delta-by-hash can fire on a contract at all.

    A signature is recorded against the session's hash, so it starts current.
    Editing the contract has to move the session's hash, and only then does the
    signing module have anything to compare against and report.
    """
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    signing = SigningService(pg_session)
    contract = await _contract_with_parties(pg_session, service, user_id, project_id)

    row = await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()
    hash_at_issue = row.document_content_hash

    await signing.record_attestation(
        row.id,
        AttestationCreate(
            signatory_name="Northlake Estates",
            signatory_role="employer",
            content_hash=hash_at_issue,
        ),
        user_id=user_id,
    )
    await pg_session.flush()

    view = await service.signing_session_view(contract, row)
    assert view["content_hash_current"] is True
    assert view["stale_signatories"] == []
    assert view["signed_roles"] == ["employer"]

    # The paper moves. Title is not a financial field, so a draft accepts it.
    #
    # Asserted in two steps on purpose. The first says the hash function saw the
    # edit at all; the second says the session was moved onto it. Collapsing them
    # into one comparison against the stale ``row`` would blame the bridge for a
    # failure that is really about when the updated contract becomes visible to
    # the nested read, and it would do it three lines away from the cause.
    before = await service.contract_content_hash(contract)
    assert before == hash_at_issue
    await service.update_contract(contract.id, ContractUpdate(title="Signing bridge, revised scope"))
    await pg_session.flush()
    after = await service.contract_content_hash(contract)
    assert after != before
    await pg_session.refresh(row)

    assert row.document_content_hash == after
    assert row.document_content_hash != hash_at_issue
    view = await service.signing_session_view(contract, row)
    assert view["content_hash_current"] is True  # session moved with the contract
    assert view["stale_signatories"] == ["Northlake Estates"]


@pytest.mark.asyncio
async def test_a_closed_session_is_not_re_hashed_by_a_later_edit(pg_session) -> None:
    """A declined session is history and must keep the hash it was declined on."""
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    signing = SigningService(pg_session)
    contract = await _contract_with_parties(pg_session, service, user_id, project_id)

    row = await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()
    hash_at_issue = row.document_content_hash

    from app.modules.signing.schemas import DeclineCreate

    await signing.record_decline(
        row.id,
        DeclineCreate(
            signatory_name="Bramwell Civil Works",
            signatory_role="contractor",
            reason="Programme dates not agreed.",
        ),
        user_id=user_id,
    )
    await pg_session.flush()
    assert row.status == "declined"

    moved = await service.refresh_signing_content_hash(contract.id)
    await pg_session.flush()
    assert moved == 0
    assert row.document_content_hash == hash_at_issue


# ── The outcome drives the contract ───────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_holds_a_partly_signed_contract_and_activates_a_fully_signed_one(
    pg_session,
) -> None:
    project_id, user_id = await _project(pg_session)
    service = ContractsService(pg_session)
    signing = SigningService(pg_session)
    contract = await _contract_with_parties(pg_session, service, user_id, project_id)

    row = await service.open_signing_session(contract.id, actor_id=user_id)
    await pg_session.flush()

    await signing.record_attestation(
        row.id,
        AttestationCreate(
            signatory_name="Northlake Estates",
            signatory_role="employer",
            content_hash=row.document_content_hash,
        ),
        user_id=user_id,
    )
    await pg_session.flush()
    assert row.status == "partially_signed"

    held = await service.sync_contract_from_signing(contract.id, user_id)
    assert held.status == "draft"

    await signing.record_attestation(
        row.id,
        AttestationCreate(
            signatory_name="Bramwell Civil Works",
            signatory_role="contractor",
            content_hash=row.document_content_hash,
        ),
        user_id=user_id,
    )
    await pg_session.flush()
    assert row.status == "fully_signed"

    activated = await service.sync_contract_from_signing(contract.id, user_id)
    await pg_session.flush()
    assert activated.status == "active"
    # The transition stamped its own audit, so the gate really ran on the way
    # through rather than being skipped because signing had already happened.
    assert "compliance_validation" in (activated.metadata_ or {})
    assert activated.signed_at

    # Idempotent: calling again on an active contract changes nothing.
    again = await service.sync_contract_from_signing(contract.id, user_id)
    assert again.status == "active"
