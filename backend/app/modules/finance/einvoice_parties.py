# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The buyer of one invoice, resolved from the contact that invoice already names.

EN 16931 wants the buyer's postal address (BG-8), and XRechnung makes the city
and the post code of it mandatory (BR-DE-8, BR-DE-9). None of that is invoice
data. It describes the counterparty, which this platform already stores once in
the contacts directory, so an invoice that names a contact should not have to be
told again who is being invoiced and where they are.

The result is handed to ``build_einvoice`` inside ``defaults`` and never as its
``buyer`` argument. ``defaults`` is the floor the document overrides; the
argument is a ceiling it cannot. A buyer typed onto one invoice has to keep
winning over the standing record, which is what makes a one-off recipient still
expressible.

Nothing here parses a free-text address. A contact whose address was captured
before this existed holds a single unstructured line under ``text``, and that
line becomes the address line as written. Splitting a city or a post code out of
it would work on the addresses we happen to have and mis-file the ones we do
not, and a wrongly split post code is worse than an absent one: the absent one
is reported to the user by BR-DE-9, the wrong one is silently exported.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact

__all__ = [
    "buyer_party_from_contact",
    "contact_display_name",
    "einvoice_defaults_for_invoice",
]

#: The direction in which the linked contact is the party being invoiced. On a
#: payable invoice the same column names our supplier, so mapping it to the
#: buyer would file the counterparty as the recipient of their own invoice.
_CONTACT_IS_BUYER = "receivable"

#: Address-line keys in order of preference. ``line1`` is what the e-invoice
#: engine itself calls the field, ``street`` is the key the rest of the platform
#: stores an address under (``Project.address``), and ``text`` is the single
#: unstructured line the contacts form wrote before it had separate fields.
_ADDRESS_LINE_KEYS = ("line1", "street", "text")

#: Post code spellings this codebase already has in circulation: ``postcode`` in
#: the demo project addresses, ``postal_code`` accepted by the geocoder.
_POSTCODE_KEYS = ("postcode", "postal_code", "zip")


def contact_display_name(contact: Contact) -> str:
    """Return the label a person would recognise the counterparty by.

    Company first, because an invoice is addressed to an organisation and the
    person is an attribute of it.

    The ordering is not decided here. :func:`app.core.party_names.contact_display_name`
    holds it, and the registers, the punch list and global search read the same
    function, so one party carries one label wherever it appears. This wrapper
    adds the one step an invoice needs beyond a register: an address as the last
    resort, because a document has to name its buyer and BT-44 cannot be blank.

    Two answers used to differ from the register's, and both showed up on an
    invoice. A contact with a registered name but no trading name and no person
    was billed to its email address, because this copy fell through to the email
    without ever consulting ``legal_name``. And a ``company_name`` of nothing but
    spaces is truthy, so it was returned, stripped, and the buyer name came out
    empty on a record that had a perfectly good person in it.

    Args:
        contact: the counterparty record.

    Returns:
        The trading name, else the person's full name, else the registered name,
        else the primary email, else an empty string when the record answers
        none of them.
    """
    from app.core.party_names import contact_display_name as register_display_name  # noqa: PLC0415

    label = register_display_name(
        contact.company_name,
        contact.legal_name,
        contact.first_name,
        contact.last_name,
    )
    return label or str(contact.primary_email or "").strip()


def _first_present(address: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _person_names(contact: Contact) -> dict[str, str]:
    """First and family name, only for a contact recorded as a natural person.

    A company's contact person also has a first and a last name on the record;
    printing those as the party's own name would address a company's invoice
    to its employee.
    """
    if str(contact.party_kind or "") != "natural_person":
        return {}
    return {
        "first_name": str(contact.first_name or "").strip(),
        "family_name": str(contact.last_name or "").strip(),
    }


def buyer_party_from_contact(contact: Contact) -> dict[str, str]:
    """Return the buyer-party fields a contact can answer.

    Shaped for ``build_einvoice``'s party dict, and sparse on purpose: a key
    this contact has nothing to say about is left out rather than set empty, so
    the merge treats it as unanswered and the invoice can still answer it.

    Args:
        contact: the counterparty record.

    Returns:
        A party dict holding only the fields that carry a value.
    """
    address = contact.address if isinstance(contact.address, dict) else {}

    fields = {
        "name": contact_display_name(contact),
        "country_code": str(contact.country_code or "").strip(),
        "vat_id": str(contact.vat_number or "").strip(),
        "line1": _first_present(address, _ADDRESS_LINE_KEYS),
        "postcode": _first_present(address, _POSTCODE_KEYS),
        "city": _first_present(address, ("city",)),
        # Read by formats that print them (UBL-TR: the tax office beside the
        # tax number, the district as CitySubdivisionName, a natural person
        # by first and family name). The EN 16931 party ignores them.
        "tax_office": str(contact.tax_office or "").strip(),
        "district": _first_present(address, ("district",)),
        "building_number": _first_present(address, ("building_number",)),
        **_person_names(contact),
    }
    return {key: value for key, value in fields.items() if value}


async def einvoice_defaults_for_invoice(
    session: AsyncSession,
    *,
    contact_id: str | None,
    invoice_direction: str | None,
) -> dict[str, Any]:
    """Return the standing configuration for one invoice, buyer included.

    The seller half comes from the instance settings and the buyer half from the
    invoice's own counterparty, so both render paths get one resolved view
    instead of each assembling its own. A document cleared for export by one and
    refused by the other would be the same invoice in two states.

    Args:
        session: an open database session.
        contact_id: the invoice's ``contact_id``, if it names one.
        invoice_direction: ``receivable`` or ``payable``.

    Returns:
        The defaults dict, carrying ``buyer`` only when the contact is the party
        being invoiced and actually answered something.
    """
    from app.modules.finance.einvoice_settings_service import einvoice_defaults

    defaults = await einvoice_defaults(session)
    if not contact_id or (invoice_direction or "") != _CONTACT_IS_BUYER:
        return defaults

    contact = (await session.execute(select(Contact).where(Contact.id == contact_id))).scalar_one_or_none()
    if contact is None:
        return defaults

    buyer = buyer_party_from_contact(contact)
    if not buyer:
        return defaults
    return {**defaults, "buyer": buyer}
