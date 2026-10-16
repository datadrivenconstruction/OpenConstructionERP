# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read a person's name out of the id a register stored for them.

Free-text person columns are everywhere in this codebase - ``assigned_to``,
``created_by``, ``submitted_by``, ``approved_by`` - and three different things
legitimately land in them. Someone types a name. A seeder or a field
integration writes a contact id. An on-screen picker writes a user id. The
register then printed whichever it got, so rows read "Submitted by
3f2b8c1e-9a44-..." with an avatar lettered from a hex digit.

This module started life inside the punch list, which is the one register
somebody had thought about. Every other screen that prints the same kind of
column had no map at all, and a rule written once per caller is only ever
tested at the caller that was already right. So it lives here, and the punch
list reads it like everybody else.

What it deliberately does not do:

- It does not resolve a value that is not an id. Somebody typed a name and
  that name is already the answer; sending it to the database would be a query
  that can only fail.
- It does not invent. An id that answers to no contact and no user is absent
  from the result, and a caller must print the record as having an owner it
  cannot name rather than as unassigned. Telling a site manager a snag is
  unassigned invites a second assignment.
- It does not query per row. A caller collects a whole page of values and asks
  once, which is two queries for any page length.
"""

import logging
import uuid
from collections.abc import Iterable
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def contact_display_name(company: str | None, legal: str | None, first: str | None, last: str | None) -> str:
    """Name a contact the way the contacts register names it.

    Company first, then the person, then the legal entity, which is the order
    the contacts screen itself uses. A record assigned to a firm should read as
    that firm on both screens rather than as its site manager on one and the
    firm on the other.

    Args:
        company: Trading name.
        legal: Registered name, often set when the trading name is not.
        first: Given name of the contact person.
        last: Family name of the contact person.

    Returns:
        The label, or an empty string when the contact has no name at all.
    """
    person = " ".join(part.strip() for part in (first, last) if part and part.strip())
    return (company or "").strip() or person or (legal or "").strip()


def canonical_id(value: object) -> str:
    """The form of ``value`` two ids can be compared in.

    Ids reach this module as a string from a free-text column and as whatever
    the type decorator hands back from a row - a ``uuid.UUID`` today, a string
    on any column it could not parse. Comparing the two shapes directly works
    right up until the day one of them changes, and it fails by resolving
    nothing rather than by raising, so nobody would see it. Both sides go
    through here instead.

    Args:
        value: An id in any of the shapes above.

    Returns:
        The canonical lower-case form, or ``str(value)`` for anything that is
        not an id at all.
    """
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        return str(value)


async def _contact_rows(session: AsyncSession, wanted: dict[str, str]) -> list[Any]:
    """Contacts among ``wanted``, or nothing if the module is not there."""
    try:
        from app.modules.contacts.models import Contact

        async with session.begin_nested():
            return (
                await session.execute(
                    select(
                        Contact.id,
                        Contact.company_name,
                        Contact.legal_name,
                        Contact.first_name,
                        Contact.last_name,
                    ).where(Contact.id.in_(wanted))
                )
            ).all()  # type: ignore[return-value]
    except Exception:
        logger.debug("Contacts unavailable, party ids stay unresolved", exc_info=True)
        return []


async def _user_rows(session: AsyncSession, wanted: dict[str, str]) -> list[Any]:
    """Platform users among ``wanted``.

    An assignment control on a screen is usually a list of platform users, so a
    record assigned through the UI carries a user id where a seeder and the
    field integrations carry a contact id. Both are ids in the same column and
    both have to read as a person.
    """
    try:
        from app.modules.users.models import User

        async with session.begin_nested():
            return (await session.execute(select(User.id, User.full_name, User.email).where(User.id.in_(wanted)))).all()  # type: ignore[return-value]
    except Exception:
        logger.debug("Users unavailable, party ids stay unresolved", exc_info=True)
        return []


async def resolve_party_names(session: AsyncSession, values: Iterable[str | None]) -> dict[str, str]:
    """Map the ids among ``values`` onto readable names.

    Contacts are asked first and users only about what is left over, so a page
    whose rows are all seeded costs one query rather than two. That order is
    also the tie-break: a contact wins a collision with a user, which cannot
    happen with generated ids and would mean the contacts register is the more
    specific answer if it ever did.

    Fail-soft throughout. Contacts is an optional module, a row can be deleted,
    and an id matching nothing resolves to nothing rather than to an invention.
    Each lookup runs in its own savepoint, so a missing table costs a name
    rather than aborting the transaction the caller is still using. A caught
    exception cannot revive a session a failed statement already poisoned,
    which is why the savepoint is required and a bare try/except is not enough.

    Args:
        session: The caller's session. Lookups run inside it, in savepoints.
        values: Raw column values, ids and names mixed, nulls allowed.

    Returns:
        ``{raw value: display name}`` for the ids that resolved. Everything
        else - typed-in names, blanks, ids nobody answers to - is absent.
    """
    wanted: dict[str, str] = {}
    for value in values:
        # Columns declared ``GUID()`` hand Python a ``uuid.UUID``, not a string.
        # ``(value or "").strip()`` therefore raised AttributeError on a real id
        # and 500'd the whole register rather than costing one name, which is
        # what "fail-soft throughout" above promises. Stringify, then trim.
        text = "" if value is None else str(value).strip()
        if not text:
            continue
        try:
            wanted[str(uuid.UUID(text))] = text
        except (AttributeError, TypeError, ValueError):
            continue  # a typed-in name, not an id
    if not wanted:
        return {}
    resolved: dict[str, str] = {}
    for row in await _contact_rows(session, wanted):
        raw = wanted.get(canonical_id(row[0]))
        name = contact_display_name(row[1], row[2], row[3], row[4])
        if raw and name:
            resolved[raw] = name

    # Users are asked only about the ids contacts could not name. A register
    # whose rows all carry seeded contact ids therefore costs one query, and
    # asking about an id that is already answered would be work spent to
    # produce a name that loses the collision anyway.
    remaining = {canon: raw for canon, raw in wanted.items() if raw not in resolved}
    if not remaining:
        return resolved
    for row in await _user_rows(session, remaining):
        raw = remaining.get(canonical_id(row[0]))
        name = (row[1] or "").strip() or (row[2] or "").strip()
        if raw and name:
            resolved[raw] = name
    return resolved


#: Address-line keys in order of preference: ``line1`` (the e-invoice field),
#: ``street`` (how ``Project.address`` stores it) and ``text`` (the single
#: unstructured line older contact forms wrote).
ADDRESS_LINE_KEYS = ("line1", "street", "text")

#: Post code spellings in circulation: ``postcode``, ``postal_code``, ``zip``.
POSTCODE_KEYS = ("postcode", "postal_code", "zip")


class PartyDetails(NamedTuple):
    """What a printed document says about a counterparty beyond its name."""

    tax_id: str
    address: str


def _first_present(address: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def format_party_address(address: Any, country_code: str | None = None) -> str:
    """One printable line from a contact's address dict: street, post code and city, country.

    Args:
        address: The stored address, a dict with free key spellings, or anything else.
        country_code: The contact's ISO country code, printed last when known.

    Returns:
        The parts that carry a value, joined with commas, or an empty string.
    """
    data = address if isinstance(address, dict) else {}
    line = _first_present(data, ADDRESS_LINE_KEYS)
    town = " ".join(part for part in (_first_present(data, POSTCODE_KEYS), _first_present(data, ("city",))) if part)
    if not line and not town:
        # A country on its own is not an address anyone could post to.
        return ""
    country = (country_code or "").strip().upper() or _first_present(data, ("country", "country_code"))
    return ", ".join(part for part in (line, town, country) if part)


async def resolve_party_details(session: AsyncSession, values: Iterable[str | None]) -> dict[str, PartyDetails]:
    """Map the contact ids among ``values`` onto their tax id and address.

    Only contacts answer: a platform user has neither. Fail-soft like
    :func:`resolve_party_names`, in its own savepoint, so a missing contacts
    module costs the details rather than the document.

    Args:
        session: The caller's session.
        values: Raw column values; non-ids and blanks are skipped.

    Returns:
        ``{raw value: PartyDetails}`` for contacts that carry a tax id or an
        address. A contact with neither is absent.
    """
    wanted: dict[str, str] = {}
    for value in values:
        text = "" if value is None else str(value).strip()
        if not text:
            continue
        try:
            wanted[str(uuid.UUID(text))] = text
        except (AttributeError, TypeError, ValueError):
            continue
    if not wanted:
        return {}
    try:
        from app.modules.contacts.models import Contact

        async with session.begin_nested():
            rows = (
                await session.execute(
                    select(Contact.id, Contact.vat_number, Contact.address, Contact.country_code).where(
                        Contact.id.in_(wanted)
                    )
                )
            ).all()
    except Exception:
        logger.debug("Contacts unavailable, party details stay unresolved", exc_info=True)
        return {}
    resolved: dict[str, PartyDetails] = {}
    for row in rows:
        raw = wanted.get(canonical_id(row[0]))
        details = PartyDetails(tax_id=(row[1] or "").strip(), address=format_party_address(row[2], row[3]))
        if raw and (details.tax_id or details.address):
            resolved[raw] = details
    return resolved


def party_detail_pairs(contact_id: Any, parties: Any, tax_label: str, address_label: str) -> list[tuple[str, str]]:
    """The tax id and address rows a printed form adds under a counterparty's name.

    Args:
        contact_id: The counterparty's id as the record stores it.
        parties: ``{str(id): PartyDetails}`` from :func:`resolve_party_details`, or ``None``.
        tax_label: The caption for the tax id, in the document language.
        address_label: The caption for the address, in the document language.

    Returns:
        Only the rows that carry a value; nothing when the party is unknown.
    """
    if contact_id is None or not parties:
        return []
    details = parties.get(str(contact_id).strip())
    if details is None:
        return []
    pairs: list[tuple[str, str]] = []
    if details.tax_id:
        pairs.append((tax_label, details.tax_id))
    if details.address:
        pairs.append((address_label, details.address))
    return pairs
