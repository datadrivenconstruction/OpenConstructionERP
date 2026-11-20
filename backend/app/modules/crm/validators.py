# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""CRM validation rules shared by the schemas and the service.

Pure functions, no I/O. Each rule has a stable code so the API and the UI can
name the rule that refused a value.

Rules:
    crm.currency_iso4217      a deal currency is blank or a 3-letter ISO 4217 code
    crm.lead_source_known     a lead / deal source is one of ``LEAD_SOURCES``
    crm.convert_needs_account a lead converts only with an account (given or on the lead)
    crm.period_ordered        a reporting period starts on or before it ends
    crm.account_contact_unique a contact links to an account once
"""

from __future__ import annotations

import re
from datetime import date

LEAD_SOURCES: tuple[str, ...] = ("web", "referral", "event", "trade_show", "cold_outreach", "inbound")
LEAD_SOURCE_PATTERN = r"^(" + "|".join(LEAD_SOURCES) + r")$"

_ISO_CCY = re.compile(r"^[A-Z]{3}$")


def normalize_currency(value: str | None) -> str:
    """Return an upper-case ISO 4217 code, or ``""`` when none was given.

    Never substitutes a default: a blank currency stays blank so the UI can
    ask for it instead of silently pricing a deal in some market's currency.

    Raises:
        ValueError: when the value is non-blank and not three letters.
    """
    code = (value or "").strip().upper()
    if code and not _ISO_CCY.match(code):
        raise ValueError("crm.currency_iso4217: currency must be a 3-letter ISO 4217 code")
    return code


def is_known_source(value: str) -> bool:
    """True when ``value`` is a supported lead / deal source."""
    return value in LEAD_SOURCES


def check_period(date_from: date | None, date_to: date | None) -> None:
    """Raise ``ValueError`` when the period ends before it starts."""
    if date_from and date_to and date_from > date_to:
        raise ValueError("crm.period_ordered: date_from must not be after date_to")
