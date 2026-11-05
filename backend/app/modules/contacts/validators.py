# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contact validation rules (rule set ``contacts``).

Rules run over a plain dict context built by the caller::

    {"contact": {"id", "contact_type", "first_name", "last_name", "company_name", "legal_name",
                 "vat_number", "country_code", "prequalification_status", "qualified_until",
                 "payment_terms_days"}}

``metadata["today"]`` (ISO date) overrides the reference day for the prequalification check.
"""

from __future__ import annotations

import re

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

CONTACTS_RULE_SET = "contacts"

#: Payment terms beyond a year are a unit slip (months or dates typed as days).
MAX_PAYMENT_TERMS_DAYS = 365

#: Leading letters of a VAT number that name a country other than its ISO code.
_VAT_PREFIX_ALIASES = {"EL": "GR", "XI": "GB"}
_VAT_PREFIX = re.compile(r"^([A-Za-z]{2})[0-9A-Za-z]")


class _ContactRule(QualityRule):
    standard = CONTACTS_RULE_SET
    message_section = "contacts"


class ContactIdentityRule(_ContactRule):
    """A contact is a someone: a company, a legal name or a person's name."""

    rule_id = "contacts.identity_present"
    name = "Contact has a name"
    description = "company_name, legal_name, or first_name/last_name must be filled"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contact")
        ref = str(c.get("id", ""))
        if all(blank(c.get(f)) for f in ("company_name", "legal_name", "first_name", "last_name")):
            return [self.fail(context, "identity_missing", ref=ref)]
        return [self.ok(ref)]


class ContactQualifiedUntilRule(_ContactRule):
    """The prequalification expiry is a real calendar date."""

    rule_id = "contacts.qualified_until_valid"
    name = "Prequalification expiry is a real date"
    description = "qualified_until, when given, must be an ISO date such as 2027-03-31"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contact")
        ref = str(c.get("id", ""))
        value = c.get("qualified_until")
        if not blank(value) and parse_day(value) is None:
            return [self.fail(context, "date_invalid", ref=ref, field="qualified_until", value=value)]
        return [self.ok(ref)]


class ContactPaymentTermsRule(_ContactRule):
    """Payment terms are a whole number of days, not longer than a year."""

    rule_id = "contacts.payment_terms_valid"
    name = "Payment terms are a sane number of days"
    description = "payment_terms_days must be a whole number between 0 and 365"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contact")
        ref = str(c.get("id", ""))
        value = c.get("payment_terms_days")
        if blank(value):
            return [self.ok(ref)]
        text = str(value).strip()
        if not (text.isascii() and text.isdigit()) or int(text) > MAX_PAYMENT_TERMS_DAYS:
            return [self.fail(context, "payment_terms_invalid", ref=ref, value=text, max=MAX_PAYMENT_TERMS_DAYS)]
        return [self.ok(ref)]


class ContactPrequalificationCurrentRule(_ContactRule):
    """An approved prequalification has not run out."""

    rule_id = "contacts.prequalification_current"
    name = "Approved prequalification is still valid"
    severity = Severity.WARNING
    description = "status approved with a qualified_until in the past is a lapsed prequalification"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contact")
        ref = str(c.get("id", ""))
        until = parse_day(c.get("qualified_until"))
        if c.get("prequalification_status") == "approved" and until is not None and until < today_of(context):
            return [self.fail(context, "prequalification_lapsed", ref=ref, date=until.isoformat())]
        return [self.ok(ref)]


class ContactVatCountryRule(_ContactRule):
    """A VAT number's country prefix agrees with the contact's country."""

    rule_id = "contacts.vat_matches_country"
    name = "VAT number agrees with the country"
    severity = Severity.WARNING
    description = "a VAT number that starts with a country prefix must match country_code"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "contact")
        ref = str(c.get("id", ""))
        vat = str(c.get("vat_number") or "").strip().replace(" ", "")
        country = str(c.get("country_code") or "").strip().upper()
        match = _VAT_PREFIX.match(vat)
        if match and country:
            prefix = match.group(1).upper()
            if _VAT_PREFIX_ALIASES.get(prefix, prefix) != country:
                return [self.fail(context, "vat_country_mismatch", ref=ref, vat=vat, prefix=prefix, country=country)]
        return [self.ok(ref)]


CONTACTS_RULES = (
    ContactIdentityRule,
    ContactQualifiedUntilRule,
    ContactPaymentTermsRule,
    ContactPrequalificationCurrentRule,
    ContactVatCountryRule,
)


def register_contacts_validation_rules() -> None:
    """Register the contact rules with the platform rule registry."""
    for rule_class in CONTACTS_RULES:
        rule_registry.register(rule_class(), [CONTACTS_RULE_SET])


__all__ = ["CONTACTS_RULES", "CONTACTS_RULE_SET", "register_contacts_validation_rules"]
