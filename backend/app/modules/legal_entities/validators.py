# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for legal entities and branches. Pure, no database.

Each rule returns a list of :class:`Issue`. ``error`` blocks the write and
``warning`` is returned beside a successful one, so a person sees it without
being stopped by it.

Rules:
    legal_entities.country_code_shape    error   two letters, ISO 3166-1 alpha-2
    legal_entities.currency_shape        error   three letters, ISO 4217
    legal_entities.subdivision_country   error   an ISO 3166-2 code under the same country
    legal_entities.code_shape            error   letters, digits, dot, dash, underscore
    legal_entities.branch_abroad         warning a branch in another country than its entity
    entity.duplicate_code                error   an entity code, or a site code within its entity, is taken
    entity.tax_id_format                 warning a tax id does not look like the country data expects
    entity.inactive_on_new_project       error   an inactive entity cannot take a project
    entity.site_wrong_entity             error   the project's site belongs to another entity
    entity.project_without_entity        error   no entity answers for the project, none named and no default
    entity.invoice_seller_incomplete     error   the invoicing entity lacks a name, address or required tax id
    entity.cross_entity_reference        warning a record links projects of two entities

The ``entity.*`` rules are also registered with the validation engine (rule set
``legal_entities``) so the project validation panel shows them.

Codes are checked for shape, not against a closed list: the product is global
and a closed enum would refuse a legitimate code the list has not caught up
with, the same reasoning the project currency field follows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.legal_entities.tax_ids import normalise, schemes_for, value_of

_ALPHA2 = re.compile(r"^[A-Z]{2}$")
_ALPHA3 = re.compile(r"^[A-Z]{3}$")
_SUBDIVISION = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")
_CODE = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


@dataclass(frozen=True)
class Issue:
    """One finding of a rule, in the shape the API returns."""

    rule_id: str
    severity: Literal["error", "warning"]
    field: str
    message: str


def check_country(value: str, field: str = "country_code") -> list[Issue]:
    if _ALPHA2.match(value or ""):
        return []
    return [Issue("legal_entities.country_code_shape", "error", field, "Use a two-letter ISO 3166-1 country code.")]


def check_currency(value: str, field: str = "functional_currency") -> list[Issue]:
    if _ALPHA3.match(value or ""):
        return []
    return [Issue("legal_entities.currency_shape", "error", field, "Use a three-letter ISO 4217 currency code.")]


def check_subdivision(country: str, subdivision: str | None) -> list[Issue]:
    if subdivision is None:
        return []
    if _SUBDIVISION.match(subdivision) and subdivision.split("-", 1)[0] == country:
        return []
    return [
        Issue(
            "legal_entities.subdivision_country",
            "error",
            "subdivision_code",
            f"Use an ISO 3166-2 code under {country}, for example {country}-XX.",
        )
    ]


def check_code(value: str) -> list[Issue]:
    if _CODE.match(value or ""):
        return []
    return [
        Issue(
            "legal_entities.code_shape",
            "error",
            "code",
            "Use up to 32 letters, digits, dots, dashes or underscores.",
        )
    ]


def validate_entity(
    *, code: str, country_code: str, subdivision_code: str | None, functional_currency: str
) -> list[Issue]:
    """Every rule that applies to a legal entity as it would be stored."""
    return [
        *check_code(code),
        *check_country(country_code),
        *check_subdivision(country_code, subdivision_code),
        *check_currency(functional_currency),
    ]


def validate_branch(
    *, code: str, country_code: str, subdivision_code: str | None, entity_country_code: str
) -> list[Issue]:
    """Every rule that applies to a branch as it would be stored, given its entity's country."""
    issues = [
        *check_code(code),
        *check_country(country_code),
        *check_subdivision(country_code, subdivision_code),
    ]
    if not issues and country_code != entity_country_code:
        issues.append(
            Issue(
                "legal_entities.branch_abroad",
                "warning",
                "country_code",
                f"This branch is in {country_code} and its entity is registered in {entity_country_code}. "
                "A foreign branch can have its own registration and tax duties there.",
            )
        )
    return issues


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


# ── Group of companies: entity.* rules ───────────────────────────────────────


def check_duplicate_code(code: str, *, taken: bool, site: bool = False) -> list[Issue]:
    """``entity.duplicate_code`` when *code* is already used."""
    if not taken:
        return []
    what = "site" if site else "company"
    return [Issue("entity.duplicate_code", "error", "code", f"The {what} code {code} is already used.")]


def check_tax_ids(country_code: str, tax_ids: list[dict[str, Any]] | None) -> list[Issue]:
    """``entity.tax_id_format``: a warning per identifier whose shape the country data does not expect.

    Only schemes the country data names are checked; an identifier under a
    scheme it does not know, or for a country it does not list, is accepted.
    """
    issues: list[Issue] = []
    for scheme in schemes_for(country_code):
        value = value_of(tax_ids, scheme.scheme)
        if value and not scheme.matches(value):
            hint = f" Expected like {scheme.example}." if scheme.example else ""
            issues.append(
                Issue(
                    "entity.tax_id_format",
                    "warning",
                    f"tax_ids.{scheme.scheme}",
                    f"{normalise(value)} does not match the {scheme.scheme} format for {country_code}.{hint}",
                )
            )
    return issues


def check_active_for_new_project(*, code: str, is_active: bool) -> list[Issue]:
    """``entity.inactive_on_new_project``."""
    if is_active:
        return []
    return [
        Issue(
            "entity.inactive_on_new_project",
            "error",
            "legal_entity_id",
            f"Company {code} is inactive and cannot take new projects.",
        )
    ]


def check_site_entity(*, site_entity_id: Any, entity_id: Any) -> list[Issue]:
    """``entity.site_wrong_entity``: the site must belong to the project's entity."""
    if site_entity_id is None or str(site_entity_id) == str(entity_id):
        return []
    return [
        Issue(
            "entity.site_wrong_entity",
            "error",
            "legal_entity_branch_id",
            "Site belongs to another legal entity than the project.",
        )
    ]


def check_project_has_entity(*, assigned: bool, default_exists: bool, entities_exist: bool) -> list[Issue]:
    """``entity.project_without_entity``.

    Fires only where it means something: entities exist, the project names
    none and no default entity answers for it. An install without entities,
    and a project that falls back to the default, are fine.
    """
    if assigned or default_exists or not entities_exist:
        return []
    return [
        Issue(
            "entity.project_without_entity",
            "error",
            "legal_entity_id",
            "Project has no legal entity. Assign one before issuing documents.",
        )
    ]


def missing_seller_fields(seller: dict[str, Any], country_code: str | None) -> list[str]:
    """Which identity fields an invoice needs from the seller and does not have.

    Name and address always; a tax id where the country data marks a scheme
    mandatory on invoices (EU: the VAT id), otherwise none.
    """
    missing = [f for f in ("name", "line1", "city") if not str(seller.get(f) or "").strip()]
    for scheme in schemes_for(country_code):
        if not scheme.mandatory_on_invoice:
            continue
        key = "vat_id" if scheme.scheme == "vat" else scheme.scheme
        if not str(seller.get(key) or "").strip():
            missing.append(key)
    return missing


def check_seller_complete(seller: dict[str, Any], country_code: str | None, *, entity_code: str = "") -> list[Issue]:
    """``entity.invoice_seller_incomplete``."""
    missing = missing_seller_fields(seller, country_code)
    if not missing:
        return []
    who = f" for {entity_code}" if entity_code else ""
    return [
        Issue(
            "entity.invoice_seller_incomplete",
            "error",
            ",".join(missing),
            f"Seller name, address or tax id missing{who}: {', '.join(missing)}.",
        )
    ]


def check_cross_entity(entity_ids: list[Any]) -> list[Issue]:
    """``entity.cross_entity_reference``: one record links projects of two entities."""
    distinct = {str(e) for e in entity_ids if e is not None}
    if len(distinct) < 2:
        return []
    return [
        Issue(
            "entity.cross_entity_reference",
            "warning",
            "legal_entity_id",
            "Document links records of two legal entities; intercompany billing is not supported yet.",
        )
    ]
