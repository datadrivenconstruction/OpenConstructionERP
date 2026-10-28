# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The rule that decides whether a contract has anybody who can sign it.

``contracts.parties_complete`` used to apply only to a contract that was
already active or completed, while the only moment its answer matters is the
press of "put up for signature", which only ever happens on a draft. The two
conditions were mutually exclusive, so the rule could not fire at the moment it
was written for, and what actually stopped the press was a refusal hardcoded in
the service: no rule id, no suggestion, and nothing on screen beforehand.

The rule also used to ask for a named employer and a named contractor. That is
one contract's shape. A subcontract is executed by the main contractor and the
firm selling the work, and the employer is deliberately not a party to it, so
the old wording reported every subcontract in the register as missing a party
it should never have had. The rule now asks for two *distinct signing roles*,
which is true of both shapes and of neither's vocabulary in particular.

These are pure dict-context checks with no database and no engine, which is the
level the mistake lived at: every test that exercised signing built a contract
with parties, and it built them as a main contract, so nothing ever asked the
rule about a draft and nothing ever asked it about a subcontract.

Two of them are about what the rule must NOT do. A context carrying positions
and no contract is the compliance gate's payload, and a rule that fired there
would report a missing party against a schedule of values. And a party entered
as a link rather than as typed text has an empty stored name, which is why the
service resolves the name before the context is built - a rule reading the
stored field alone would call a register empty while the screen names the
employer.

The last one is the invariant the service leans on. Deleting the hardcoded
refusal is only safe if this rule passing means the signature block has
somebody to address, so it is asserted against the real function rather than
argued in a comment.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.contracts.signing_bridge import (
    SIGNING_PARTY_ROLES,
    SigningParty,
    signatory_map_from_parties,
)
from app.modules.contracts.validators import REQUIRED_SIGNATORY_COUNT, ContractPartyRolesRule

CONTRACT_ID = "6f1c9d80-0f4b-4a5d-9c2a-3f9b6f2f77aa"

#: The main contract and the subcontract, as the demo register builds them.
MAIN_CONTRACT_PARTIES = [
    {"party_role": "employer", "display_name": "Northlake Estates"},
    {"party_role": "contractor", "display_name": "Bramwell Civil Works"},
]
SUBCONTRACT_PARTIES = [
    {"party_role": "contractor", "display_name": "Bramwell Civil Works"},
    {"party_role": "subcontractor", "display_name": "Ferrow Groundworks"},
]


def _context(*, status: str = "draft", parties: list[dict] | None = None) -> ValidationContext:
    return ValidationContext(
        data={
            "contract": {"id": CONTRACT_ID, "status": status, "contract_type": "lump_sum", "terms": {}},
            "parties": parties or [],
        }
    )


def _party(role: str, name: str = "Northlake Estates", party_type: str = "external") -> dict:
    return {"party_role": role, "party_type": party_type, "display_name": name}


@pytest.mark.asyncio
async def test_a_draft_with_nobody_on_its_register_is_reported_not_refused() -> None:
    """The state that used to be a refusal at the button is now a finding."""
    results = await ContractPartyRolesRule().validate(_context())

    assert [r.passed for r in results] == [False]
    assert [r.severity for r in results] == [Severity.ERROR]
    assert results[0].message == "Contract names 0 of the 2 parties that sign it"
    # The finding carries the fix, which is the half a hardcoded raise could
    # never give a screen.
    assert results[0].suggestion
    assert results[0].element_ref == CONTRACT_ID


@pytest.mark.asyncio
async def test_a_main_contract_naming_both_sides_passes() -> None:
    results = await ContractPartyRolesRule().validate(_context(parties=MAIN_CONTRACT_PARTIES))

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_a_subcontract_passes_without_an_employer() -> None:
    """The regression this rule's previous wording would have caused.

    A subcontract is between the contractor buying the work and the firm
    selling it. The employer is not a party to it and is deliberately absent
    from the register. Asking for an employer by name here would refuse the
    press on every subcontract in the product, including the one the demo seeds
    as a draft precisely so the signing path can be demonstrated.
    """
    results = await ContractPartyRolesRule().validate(_context(parties=SUBCONTRACT_PARTIES))

    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_a_register_holding_only_a_consultant_is_still_incomplete() -> None:
    """A full register that signs nothing is the case that reads as fine."""
    results = await ContractPartyRolesRule().validate(
        _context(parties=[_party("consultant", "Harkness Cost Consultancy")])
    )

    assert [r.passed for r in results] == [False]


@pytest.mark.asyncio
async def test_two_rows_in_one_role_are_one_signatory() -> None:
    """Not a contract: one side, entered twice.

    The signature block takes one party per role, so a second contractor row is
    dropped rather than becoming a second signatory. Counting rows here instead
    of roles would pass a document nobody on the other side has agreed to.
    """
    results = await ContractPartyRolesRule().validate(
        _context(
            parties=[
                _party("contractor", "Bramwell Civil Works"),
                _party("contractor", "Bramwell Civil Works (Southern)"),
            ]
        )
    )

    assert [r.passed for r in results] == [False]


@pytest.mark.asyncio
async def test_a_party_row_with_no_name_is_reported_as_nameless_not_absent() -> None:
    """The register is full and the signature block still cannot address it."""
    results = await ContractPartyRolesRule().validate(
        _context(parties=[_party("employer", ""), _party("contractor", "   ")])
    )

    assert [r.passed for r in results] == [False]
    assert results[0].message == (
        "Contract names 0 of the 2 parties that sign it, and the register carries no name for: contractor, employer"
    )


@pytest.mark.asyncio
async def test_a_context_with_no_contract_produces_nothing() -> None:
    """The compliance gate validates a schedule of values through this engine.

    Its payload is positions and nothing else. A rule that answered there would
    put "contract names 0 of the 2 parties" in the middle of a report about
    quantities and rates, on every contract, forever.
    """
    results = await ContractPartyRolesRule().validate(
        ValidationContext(data={"positions": [{"id": "1", "quantity": "10", "unit_rate": "5"}]})
    )

    assert results == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["draft", "active", "completed", "suspended", "terminated"])
async def test_the_rule_answers_at_every_status(status: str) -> None:
    """No status makes an unexecutable contract acceptable.

    A draft is on its way to signature, and everything past it has been
    executed. The old status filter is gone rather than widened, because a list
    of statuses to check is a list somebody has to remember to extend.
    """
    results = await ContractPartyRolesRule().validate(_context(status=status))

    assert len(results) == 1
    assert not results[0].passed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parties",
    [
        pytest.param([], id="empty-register"),
        pytest.param(MAIN_CONTRACT_PARTIES, id="main-contract"),
        pytest.param(SUBCONTRACT_PARTIES, id="subcontract"),
        pytest.param([_party("employer"), _party("subcontractor", "Ferrow Groundworks")], id="direct-package"),
        pytest.param([_party("consultant", "Harkness Cost Consultancy")], id="consultant-only"),
        pytest.param([_party("contractor", "A"), _party("contractor", "B")], id="one-role-twice"),
        pytest.param([_party("employer", ""), _party("contractor", "B")], id="one-side-nameless"),
        pytest.param(
            [_party("employer"), _party("contractor", "B"), _party("subcontractor", "C")],
            id="three-sides",
        ),
    ],
)
async def test_passing_this_rule_means_the_signature_block_has_two_names(parties: list[dict]) -> None:
    """The invariant that let the hardcoded refusal be deleted.

    The service no longer checks for an empty signatory map before opening a
    session, because this rule has already run and blocked. That is only sound
    if "rule passed" implies "the map has both sides in it", so it is asserted
    against the real bridge function over every register shape above rather
    than kept true by two pieces of code being written on the same afternoon.
    """
    results = await ContractPartyRolesRule().validate(_context(parties=parties))
    signatories = signatory_map_from_parties(
        [SigningParty(party_role=p["party_role"], display_name=p["display_name"]) for p in parties]
    )

    assert results[0].passed is (len(signatories) >= REQUIRED_SIGNATORY_COUNT)


def test_the_rule_reads_the_signing_bridges_role_list() -> None:
    """One list, not two that agree.

    A copy of the signing roles in the validators module would keep this rule
    and the signature block in step only until somebody edits one of them, and
    the failure mode is a contract that passes validation and then produces an
    empty signature block.
    """
    from app.modules.contracts import validators

    assert validators.SIGNING_PARTY_ROLES is SIGNING_PARTY_ROLES
