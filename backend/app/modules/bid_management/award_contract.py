# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What an award hands to the contract draft it creates.

Two award paths draft a contract: ``bid_management.package.awarded`` (the
subscriber in ``notifications/_wave5_cross_module_subscribers.py``) and
``tendering.package.awarded`` (``bid_management/events.py``). Both need the
same three answers, and they live here so the two paths cannot drift apart:

* whether a contract for this award already exists, keyed on metadata rather
  than on the contract code, so a hand-made contract that happens to use the
  code does not swallow the award, and so the two paths converge on one
  contract when a bid package is linked to a tender package;
* a contract code that is free, since ``oe_contracts_contract.code`` is
  unique across the whole install;
* who the counterparty is. A bidder is a snapshot row that no contracts or
  finance reader can resolve, so the counterparty is the directory entry the
  bidder was linked to, or nothing, and never the bidder row itself.

Imports of the contracts and subcontractors models stay inside the functions:
this module is imported by bid_management at load time, and those modules are
plugins that may not be installed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: ``oe_contracts_contract.code`` is String(80).
CONTRACT_CODE_MAX = 80

#: A contract in this status no longer stands for the award, so a re-award
#: drafts a new one instead of finding the old one and skipping.
_RETIRED_CONTRACT_STATUSES = frozenset({"terminated"})


async def find_award_contract(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    keys: dict[str, str | None],
) -> Any | None:
    """Return the project contract an award already drafted, or ``None``.

    ``keys`` maps a metadata field to the value that identifies the award,
    for example ``{"bid_package_id": ..., "tender_package_id": ...}``. A match
    on any non-empty key counts, which is what lets the tender path and the
    bid_management path find each other's contract for one logical award.
    """
    from app.modules.contracts.models import Contract  # noqa: PLC0415

    wanted = {field: value for field, value in keys.items() if value}
    if not wanted:
        return None
    rows = (await session.execute(select(Contract).where(Contract.project_id == project_id))).scalars().all()
    for contract in rows:
        if contract.status in _RETIRED_CONTRACT_STATUSES:
            continue
        md = contract.metadata_ if isinstance(contract.metadata_, dict) else {}
        for field, value in wanted.items():
            if md.get(field) == value:
                return contract
    return None


async def free_contract_code(session: AsyncSession, base: str) -> str:
    """Return ``base`` when no contract uses it, else the first free ``base-N``.

    A taken code is not an idempotency signal: a person may have typed it on a
    contract of their own, and returning there used to drop the award without a
    word. It is logged, because the draft then carries a code the user did not
    expect.
    """
    from app.modules.contracts.models import Contract  # noqa: PLC0415

    base = base[:CONTRACT_CODE_MAX]

    async def _taken(code: str) -> bool:
        found = await session.execute(select(Contract.id).where(Contract.code == code).limit(1))
        return found.scalar_one_or_none() is not None

    if not await _taken(base):
        return base
    for n in range(2, 1000):
        suffix = f"-{n}"
        candidate = base[: CONTRACT_CODE_MAX - len(suffix)] + suffix
        if not await _taken(candidate):
            logger.warning(
                "Contract code %s is already used by another contract; the award draft is coded %s",
                base,
                candidate,
            )
            return candidate
    candidate = base[: CONTRACT_CODE_MAX - 9] + "-" + uuid.uuid4().hex[:8]
    logger.warning("Contract code %s and its numbered variants are taken; using %s", base, candidate)
    return candidate


@dataclass(frozen=True)
class AwardCounterparty:
    """Who a contract drafted from an award is with.

    ``counterparty_id`` is what goes on ``Contract.counterparty_id``: the
    subcontractor when the bidder was invited from the directory, else the
    contact, else ``None``. ``party_type`` / ``party_id`` describe the same
    firm as a structured contract party, and ``display_name`` is the free-text
    company that party falls back to when nothing is linked. ``contact_id`` is
    the contact that stands for the firm, when one is known.
    """

    counterparty_id: uuid.UUID | None
    contact_id: uuid.UUID | None
    party_type: str
    party_id: uuid.UUID | None
    display_name: str


async def resolve_award_counterparty(
    session: AsyncSession,
    *,
    subcontractor_id: uuid.UUID | None,
    contact_id: uuid.UUID | None,
    company_name: str,
) -> AwardCounterparty:
    """Map an awarded bidder's links onto a contract counterparty.

    A subcontractor link wins because ``counterparty_type`` is
    ``subcontractor`` and the contracts UI resolves that type against the
    subcontractor directory. Its contact is taken from the bidder when set,
    else from the subcontractor's own ``contact_id``. A link that no longer
    resolves (the row was deleted) is dropped, so the contract never points at
    a row nobody can read.
    """
    sub_id: uuid.UUID | None = None
    derived_contact: uuid.UUID | None = None
    if subcontractor_id is not None:
        try:
            from app.modules.subcontractors.models import Subcontractor  # noqa: PLC0415

            sub = await session.get(Subcontractor, subcontractor_id)
        except ImportError:
            sub = None
        if sub is not None:
            sub_id = sub.id
            derived_contact = sub.contact_id

    resolved_contact: uuid.UUID | None = None
    if contact_id is not None:
        try:
            from app.modules.contacts.models import Contact  # noqa: PLC0415

            contact = await session.get(Contact, contact_id)
        except ImportError:
            contact = None
        if contact is not None:
            resolved_contact = contact.id
    if resolved_contact is None:
        resolved_contact = derived_contact

    name = (company_name or "").strip()
    if sub_id is not None:
        return AwardCounterparty(sub_id, resolved_contact, "subcontractor", sub_id, name)
    if resolved_contact is not None:
        return AwardCounterparty(resolved_contact, resolved_contact, "contact", resolved_contact, name)
    return AwardCounterparty(None, None, "external", None, name)


def add_award_party(session: AsyncSession, contract_id: uuid.UUID, cp: AwardCounterparty) -> None:
    """Record the awarded firm as the contract's primary subcontractor party.

    The party carries the free-text company as its ``display_name``, which is
    what the parties panel shows when the linked row does not resolve, so a
    bidder that was never linked to the directory still reads as its company
    and never as an id.
    """
    from app.modules.contracts.models import ContractParty  # noqa: PLC0415

    session.add(
        ContractParty(
            contract_id=contract_id,
            party_role="subcontractor",
            party_type=cp.party_type,
            party_id=cp.party_id,
            display_name=cp.display_name[:500],
            is_primary=True,
        ),
    )
