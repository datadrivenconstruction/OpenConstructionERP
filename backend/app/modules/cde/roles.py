# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ISO 19650 functional roles for the Common Data Environment.

Information management under ISO 19650 is organised around a small set of
functional roles that a project fixes once and reuses across every discipline:
Author, Reviewer, Approver and Viewer. They are *responsibilities* in the
document workflow, not job titles - one person can be an Author on their own
discipline and a Viewer on someone else's.

Each functional role maps onto the CDE state machine (see
``app.core.cde_states``): the Reviewer owns Gate A (WIP -> SHARED), the Approver
owns Gate B (SHARED -> PUBLISHED), the Author produces content in WIP, and the
Viewer consumes shared and published information. Keeping the mapping declarative
here (rather than scattered through the UI) means the responsibility model is one
source of truth, surfaced through ``GET /v1/cde/functional-roles``.

Reference: ISO 19650-2:2018 - information management roles and responsibilities.
Labels here are English defaults; the frontend runs them through i18n keyed by the
role key (``cde.role_<key>_*``).
"""

from __future__ import annotations

from typing import Any

# Ordered CDE lifecycle states - the columns of the responsibility matrix.
CDE_STATE_ORDER: list[str] = ["wip", "shared", "published", "archived"]


# The four functional roles, in workflow order (content flows author -> reviewer
# -> approver, viewer reads throughout). ``cde_role`` is the role name the state
# machine checks at each gate (see ``app.core.cde_states._ROLE_RANK``); ``gate``
# is the transition this role is accountable for, if any.
FUNCTIONAL_ROLES: list[dict[str, Any]] = [
    {
        "key": "author",
        "name": "Author",
        "cde_role": "editor",
        "gate": None,
        "acts_on": ["wip"],
        "permissions": ["cde.create", "cde.update"],
        "summary": (
            "Creates and develops information in the work-in-progress area, then "
            "submits it for review. Owns the content until it is fit to share."
        ),
    },
    {
        "key": "reviewer",
        "name": "Reviewer",
        "cde_role": "task_team_manager",
        "gate": "A",
        "acts_on": ["wip", "shared"],
        "permissions": ["cde.read", "cde.transition"],
        "summary": (
            "Checks work for coordination and quality, returns comments, and "
            "promotes accepted information into the shared area (Gate A)."
        ),
    },
    {
        "key": "approver",
        "name": "Approver",
        "cde_role": "lead_ap",
        "gate": "B",
        "acts_on": ["shared", "published"],
        "permissions": ["cde.read", "cde.transition"],
        "summary": (
            "Authorises information for publication - the accountable sign-off "
            "before it leaves the shared area for use (Gate B)."
        ),
    },
    {
        "key": "viewer",
        "name": "Viewer",
        "cde_role": "viewer",
        "gate": None,
        "acts_on": ["shared", "published", "archived"],
        "permissions": ["cde.read"],
        "summary": (
            "Reads shared and published information - clients, stakeholders and "
            "downstream teams who consume documents without changing them."
        ),
    },
]


# What each functional role does in each CDE state. Short verbs so the frontend
# can render a responsibility grid (state rows x role columns). A dash means the
# role has no active part in that state.
RESPONSIBILITY_MATRIX: dict[str, dict[str, str]] = {
    "wip": {
        "author": "Create and edit",
        "reviewer": "Check and promote",
        "approver": "-",
        "viewer": "-",
    },
    "shared": {
        "author": "Revise on comment",
        "reviewer": "Review and return",
        "approver": "Authorise",
        "viewer": "Read",
    },
    "published": {
        "author": "-",
        "reviewer": "-",
        "approver": "Owns the release",
        "viewer": "Read",
    },
    "archived": {
        "author": "-",
        "reviewer": "-",
        "approver": "-",
        "viewer": "Read (superseded)",
    },
}


def role_keys() -> list[str]:
    """Return the functional-role keys in workflow order."""
    return [r["key"] for r in FUNCTIONAL_ROLES]


def role_by_key(key: str) -> dict[str, Any] | None:
    """Return a single functional role by key, or ``None`` if unknown."""
    for role in FUNCTIONAL_ROLES:
        if role["key"] == key:
            return role
    return None
