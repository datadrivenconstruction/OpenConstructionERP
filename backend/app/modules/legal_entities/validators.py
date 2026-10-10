# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for legal entities and branches. Pure, no database.

Each rule returns a list of :class:`Issue`. ``error`` blocks the write and
``warning`` is returned beside a successful one, so a person sees it without
being stopped by it.

Rules:
    legal_entities.country_code_shape    error   two letters, ISO 3166-1 alpha-2
    legal_entities.currency_shape        error   three letters, ISO 4217
    legal_entities.subdivision_country   error   an ISO 3166-2 code under the same country
    legal_entities.code_shape            error   letters, digits, dot, dash, underscore
    legal_entities.branch_abroad         warning a branch in another country than its entity

Codes are checked for shape, not against a closed list: the product is global
and a closed enum would refuse a legitimate code the list has not caught up
with, the same reasoning the project currency field follows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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
