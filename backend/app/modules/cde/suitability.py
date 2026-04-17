"""ISO 19650 suitability-code lookup table.

Exposes the fixed set of ISO 19650-1 suitability codes grouped by CDE state,
plus a helper that validates whether a given code is allowed for a given
lifecycle state.

Reference: ISO 19650-1:2018 — Tables A.1 and A.2.

The frontend fetches ``GET /v1/cde/suitability-codes`` and drives the
container-create dropdown from this table, so codes must not be invented
here. Adding new codes is a deliberate, spec-driven change.
"""

from __future__ import annotations

from typing import Literal

CDEStateKey = Literal["wip", "shared", "published", "archived"]


SUITABILITY_CODES: dict[CDEStateKey, list[tuple[str, str]]] = {
    "wip": [
        ("S0", "Initial status or WIP"),
    ],
    "shared": [
        ("S1", "Suitable for coordination"),
        ("S2", "Suitable for information"),
        ("S3", "Suitable for internal review and comment"),
        ("S4", "Suitable for stage approval"),
        ("S6", "Suitable for PIM authorisation"),
        ("S7", "Suitable for AIM authorisation"),
    ],
    "published": [
        ("A1", "Approved for construction"),
        ("A2", "Approved for manufacture"),
        ("A3", "Approved for use"),
        ("A4", "Approved for regulatory submission"),
        ("A5", "Approved for delivery"),
    ],
    "archived": [
        ("AR", "Archived / superseded"),
    ],
}


def codes_for_state(state: str) -> list[tuple[str, str]]:
    """Return the list of (code, label) tuples valid for a CDE state.

    Unknown states return an empty list so the validator can reject the
    combination cleanly.
    """
    return SUITABILITY_CODES.get(state.lower(), [])  # type: ignore[arg-type]


def validate_suitability_for_state(code: str | None, state: str) -> tuple[bool, str]:
    """Validate that ``code`` is allowed for the given CDE ``state``.

    A blank / None code is always valid — suitability is optional at
    container-create time (the UI surfaces the picker but users can defer).

    Returns ``(True, "ok")`` or ``(False, "<reason>")``.
    """
    if code is None or not code.strip():
        return True, "ok"
    allowed = {c for c, _ in codes_for_state(state)}
    if not allowed:
        return False, f"Unknown CDE state {state!r}"
    if code not in allowed:
        allowed_sorted = sorted(allowed)
        return False, (
            f"Suitability code {code!r} is not allowed in state {state!r}. "
            f"Allowed codes: {allowed_sorted}"
        )
    return True, "ok"


def all_codes_flat() -> list[tuple[str, str, CDEStateKey]]:
    """Return every code as (code, label, state) — used by the API response."""
    flat: list[tuple[str, str, CDEStateKey]] = []
    for state, entries in SUITABILITY_CODES.items():
        for code, label in entries:
            flat.append((code, label, state))
    return flat
