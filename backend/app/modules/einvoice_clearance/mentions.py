"""Dated invoice and quote mentions, read from ``catalogues/invoice_mentions.json``.

A country adds mentions to an invoice over time, and the same mention binds
different companies on different days: a mention can become mandatory on the
day the *issuer's* e-invoicing wave opens, which depends on the issuer's size.
This module only interprets the catalogue; it knows nothing about any one
country, so a new country is a new block of rows and not new code.

The facts a row is checked against are a flat mapping (the document's country
fields) with the issuer's settings under ``settings``. A row the catalogue flags
``needs_expert_review`` is reported as a warning and never as an error: an
unconfirmed reading of the law may inform a user but must not block an invoice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOGUE = Path(__file__).parent / "catalogues" / "invoice_mentions.json"

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

KEY_COMPANY_SIZE = "company_size"

DATED_BY_ISSUER_PHASE = "issuer_phase"
DATED_BY_FIXED = "fixed"
DATED_BY = (DATED_BY_ISSUER_PHASE, DATED_BY_FIXED)

_FALSY = {"", "0", "false", "no", "off", "none", "null"}


@dataclass(frozen=True)
class MentionFinding:
    """One mention the document should carry and does not."""

    key: str
    country: str
    label: str
    severity: str
    missing: tuple[str, ...]
    effective_date: str
    size_assumed: bool
    needs_expert_review: bool
    legal_basis: str
    source_url: str
    message: str
    # Values for a translated message: for the company size finding, the wave
    # dates keyed by size.
    params: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_catalogue() -> dict[str, Any]:
    """The parsed catalogue. Cached: it ships with the module and never changes at runtime."""
    return json.loads(_CATALOGUE.read_text(encoding="utf-8"))


def issuer_phase_date(
    country: str, company_size: str | None, *, catalogue: dict[str, Any] | None = None
) -> tuple[str | None, bool]:
    """The date the issuer's own wave opens, and whether the size was assumed.

    An unknown size resolves to the earliest wave, flagged as assumed. The
    caller must not block on an assumed date: :func:`check_mentions` reports
    such a row as a warning and asks the user to set the size.
    """
    phases = (catalogue or load_catalogue()).get("phase_by_size", {}).get(country.upper())
    if not phases:
        return None, False
    sizes: dict[str, str] = phases.get("sizes") or {}
    size = (company_size or "").strip().lower()
    if size in sizes:
        return sizes[size], False
    return (min(sizes.values()) if sizes else None), True


def _lookup(facts: dict[str, Any], path: str) -> Any:
    value: Any = facts
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value if value is not None else "").strip().lower() not in _FALSY


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clause_holds(clause: dict[str, Any], facts: dict[str, Any]) -> bool:
    value = _lookup(facts, clause["path"])
    if "present" in clause:
        return bool(_text(value)) == bool(clause["present"])
    if "truthy" in clause:
        return _truthy(value) == bool(clause["truthy"])
    if "equals" in clause:
        return _text(value) == _text(clause["equals"])
    if "in" in clause:
        return _text(value) in {_text(v) for v in clause["in"]}
    if "not_in" in clause:
        return _text(value) not in {_text(v) for v in clause["not_in"]}
    raise ValueError(f"mention clause on {clause['path']!r} names no test")


def _row_date(
    row: dict[str, Any], country: str, company_size: str | None, catalogue: dict[str, Any]
) -> tuple[str | None, bool]:
    if row["dated_by"] == DATED_BY_ISSUER_PHASE:
        return issuer_phase_date(country, company_size, catalogue=catalogue)
    return (row.get("effective_date") or None), False


def check_mentions(
    *,
    country: str,
    document_kind: str,
    issue_date: Any,
    facts: dict[str, Any],
    company_size: str | None = None,
    catalogue: dict[str, Any] | None = None,
) -> list[MentionFinding]:
    """Every mention the document should carry on its issue date and does not.

    ``issue_date`` is a date or an ISO string; only its first ten characters
    are read. A row whose date has not arrived is silent. A row with no
    confirmed date applies at once, which the catalogue allows only for rows
    flagged ``needs_expert_review``.

    When the issuer's size is not set, a row dated by the issuer's wave is
    still evaluated but only as a warning, and one extra finding keyed
    ``company_size`` asks the user to set the size, carrying the wave dates in
    ``params``. Assuming the earliest wave and blocking would stop invoices of a
    company the law does not yet bind. ``catalogue`` replaces the shipped file,
    for tests and for callers that hold their own rows.
    """
    catalogue = catalogue if catalogue is not None else load_catalogue()
    country = (country or "").strip().upper()
    issued = _text(issue_date)[:10]
    found: list[MentionFinding] = []
    ask_size = False
    for row in catalogue.get("mentions", []):
        if row["country"] != country or document_kind not in row["document_kinds"]:
            continue
        starts, assumed = _row_date(row, country, company_size, catalogue)
        if starts and issued < starts:
            continue
        if not all(_clause_holds(c, facts) for c in row.get("when", [])):
            continue
        alternatives = row["satisfied_by"]
        if any(all(_clause_holds(c, facts) for c in alt) for alt in alternatives):
            continue
        missing = tuple(c["path"] for c in alternatives[0] if not _clause_holds(c, facts))
        review = bool(row.get("needs_expert_review"))
        ask_size = ask_size or assumed
        message = f"{row['label']} is required on this {document_kind} ({row['legal_basis']})"
        if starts:
            message += f" from {starts}"
        if assumed:
            message += "; the company size is not set, so this is only a warning until it is"
        if review:
            message += "; this reading awaits expert confirmation"
        found.append(
            MentionFinding(
                key=row["key"],
                country=country,
                label=row["label"],
                severity=SEVERITY_WARNING if (review or assumed) else SEVERITY_ERROR,
                missing=missing,
                effective_date=starts or "",
                size_assumed=assumed,
                needs_expert_review=review,
                legal_basis=row["legal_basis"],
                source_url=row["source_url"],
                message=message + ".",
            )
        )
    if ask_size:
        waves = dict((catalogue.get("phase_by_size", {}).get(country) or {}).get("sizes") or {})
        found.append(
            MentionFinding(
                key=KEY_COMPANY_SIZE,
                country=country,
                label="Company size",
                severity=SEVERITY_WARNING,
                missing=("settings.company_size",),
                effective_date=min(waves.values()) if waves else "",
                size_assumed=True,
                needs_expert_review=False,
                legal_basis=(catalogue.get("phase_by_size", {}).get(country) or {}).get("legal_basis", ""),
                source_url=(catalogue.get("phase_by_size", {}).get(country) or {}).get("source_url", ""),
                message=(
                    "Set the company size on the registration: the invoice mentions apply from a date that depends "
                    "on it (" + ", ".join(f"{k}: {v}" for k, v in waves.items()) + ")."
                ),
                params={"waves": waves},
            )
        )
    return found


def facts_from_context(document: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """The flat facts a clearance document offers: its country fields plus the issuer's settings."""
    fields = document.get("country_fields")
    facts: dict[str, Any] = dict(fields) if isinstance(fields, dict) else {}
    settings = profile.get("settings")
    facts["settings"] = dict(settings) if isinstance(settings, dict) else {}
    return facts


__all__ = [
    "KEY_COMPANY_SIZE",
    "DATED_BY",
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "MentionFinding",
    "check_mentions",
    "facts_from_context",
    "issuer_phase_date",
    "load_catalogue",
]
