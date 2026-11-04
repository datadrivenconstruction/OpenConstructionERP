# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""US billing forms: the G702/G703 payment application and state lien-waiver law.

Registered with the core hook :mod:`app.modules.contracts.pay_application_forms`
on import. The figures come from the neutral payment-application builder; this
pack only decides who may use the form, draws it, and says which statutory
waiver form a state prescribes.

The G702/G703 layout is also the usual progress-billing form in Canada and
Australia, so the project gate admits US, CA and AU as it always has.
"""

from __future__ import annotations

from typing import Any

from app.modules.contracts.pay_application_forms import (
    LienWaiverRules,
    PayApplicationForm,
    register_form,
    register_lien_waiver_rules,
)

#: ISO 3166-1 alpha-2 codes whose projects may use the G702/G703 form.
AIA_COUNTRY_CODES: frozenset[str] = frozenset({"US", "CA", "AU"})

#: URL segment the form has always been served under; kept for existing clients.
AIA_FORM_SLUG = "aia-application"

#: Full-name aliases (project.address["country"] stores display names like
#: "United States"). Lower-cased keys; lookup lower-cases the input.
_AIA_COUNTRY_ALIASES: dict[str, str] = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "united states of america": "US",
    "ca": "CA",
    "can": "CA",
    "canada": "CA",
    "au": "AU",
    "aus": "AU",
    "australia": "AU",
}


def normalise_country(value: str | None) -> str | None:
    """Map a country code or display name to its ISO alpha-2 code.

    Accepts an alpha-2 code (``"US"``), a three-letter code (``"USA"``) or a
    display name (``"United States"``). Returns the alpha-2 code, or ``None``
    when the input is empty or unrecognised.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    upper = raw.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    return _AIA_COUNTRY_ALIASES.get(raw.lower())


def _project_country(country_code: str | None, address: Any) -> str | None:
    resolved = normalise_country(country_code)
    if resolved is None and isinstance(address, dict):
        resolved = normalise_country(address.get("country"))
    return resolved


def is_aia_eligible(country_code: str | None, address: Any = None) -> bool:
    """Return True when a project may use G702/G703.

    The project's ``country_code`` column is checked first; when it is empty
    or not a clean alpha-2 the fallback is ``address["country"]`` (a display
    name). Eligible only when the resolved country is US, CA or AU.
    """
    return _project_country(country_code, address) in AIA_COUNTRY_CODES


def is_us_project(country_code: str | None, address: Any = None) -> bool:
    """True for a project in the United States (lien-waiver law is state law)."""
    return _project_country(country_code, address) == "US"


# ── State lien-waiver law ───────────────────────────────────────────────────

#: States whose statute prescribes the wording of a lien waiver (some accept
#: substantial compliance). The record carries the citation so a reviewer can
#: check the signed form against it; this is not legal advice.
STATUTORY_WAIVER_STATES: dict[str, dict[str, Any]] = {
    "US-AZ": {"citation": "A.R.S. § 33-1008"},
    "US-CA": {
        "citation": "Cal. Civ. Code §§ 8132-8138",
        "by_type": {
            "conditional_partial": "Cal. Civ. Code § 8132",
            "unconditional_partial": "Cal. Civ. Code § 8134",
            "conditional_final": "Cal. Civ. Code § 8136",
            "unconditional_final": "Cal. Civ. Code § 8138",
        },
    },
    "US-FL": {"citation": "Fla. Stat. § 713.20"},
    "US-GA": {"citation": "O.C.G.A. § 44-14-366"},
    "US-MI": {"citation": "MCL 570.1115"},
    "US-MS": {"citation": "Miss. Code Ann. § 85-7-433"},
    "US-NV": {"citation": "NRS 108.2457"},
    "US-TX": {"citation": "Tex. Prop. Code § 53.284"},
    "US-UT": {"citation": "Utah Code § 38-1a-802"},
    "US-WY": {"citation": "Wyo. Stat. § 29-10-101"},
}

_STATE_NAMES: dict[str, str] = {
    "arizona": "US-AZ",
    "california": "US-CA",
    "florida": "US-FL",
    "georgia": "US-GA",
    "michigan": "US-MI",
    "mississippi": "US-MS",
    "nevada": "US-NV",
    "texas": "US-TX",
    "utah": "US-UT",
    "wyoming": "US-WY",
}

WAIVER_TYPES: tuple[str, ...] = (
    "conditional_partial",
    "unconditional_partial",
    "conditional_final",
    "unconditional_final",
)


def normalise_state(jurisdiction: str | None) -> str | None:
    """``"CA"``, ``"US-CA"`` or ``"California"`` -> ``"US-CA"``; None when empty."""
    raw = (jurisdiction or "").strip()
    if not raw:
        return None
    named = _STATE_NAMES.get(raw.lower())
    if named:
        return named
    code = raw.upper().removeprefix("US-").removeprefix("US ")
    if len(code) == 2 and code.isalpha():
        return f"US-{code}"
    return None


def statutory_waiver_form(jurisdiction: str | None, waiver_type: str) -> dict[str, Any] | None:
    """The statutory waiver form a state prescribes for ``waiver_type``, or None."""
    state = normalise_state(jurisdiction)
    entry = STATUTORY_WAIVER_STATES.get(state or "")
    if entry is None:
        return None
    citation = (entry.get("by_type") or {}).get(waiver_type) or entry["citation"]
    return {
        "state": state,
        "citation": citation,
        "template_id": f"{state.lower()}-{waiver_type}",
        "statutory": True,
    }


def waiver_templates() -> tuple[dict[str, Any], ...]:
    """One template descriptor per statutory state and waiver type, plus a common one per type."""
    out: list[dict[str, Any]] = [
        {"id": f"us-common-{t}", "waiver_type": t, "jurisdiction": None, "statutory": False} for t in WAIVER_TYPES
    ]
    for state in sorted(STATUTORY_WAIVER_STATES):
        for t in WAIVER_TYPES:
            form = statutory_waiver_form(state, t)
            if form:
                out.append({"id": form["template_id"], "waiver_type": t, "jurisdiction": state, **form})
    return tuple(out)


def _render_pdf(payload: dict[str, Any]) -> bytes:
    from app.modules.us_pack.aia_pdf import render_aia_application_pdf  # noqa: PLC0415 - reportlab is heavy

    return render_aia_application_pdf(payload)


def register() -> None:
    """Register the G702/G703 form and US lien-waiver rules with core."""
    register_form(
        PayApplicationForm(
            slug=AIA_FORM_SLUG,
            module="oe_us_pack",
            title="Application and Certificate for Payment (G702/G703)",
            markets=tuple(sorted(AIA_COUNTRY_CODES)),
            is_eligible=is_aia_eligible,
            render_pdf=_render_pdf,
            filename_prefix="AIA_G702",
            language="en",
        )
    )
    register_lien_waiver_rules(
        LienWaiverRules(
            module="oe_us_pack",
            markets=("US",),
            is_eligible=is_us_project,
            statutory_form=statutory_waiver_form,
            templates=waiver_templates(),
        )
    )


register()
