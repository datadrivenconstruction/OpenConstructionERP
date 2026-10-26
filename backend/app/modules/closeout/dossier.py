# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Handover dossier: checklist configuration and scope matching (pure).

A handover dossier is the closeout package assembled for one recipient in one
action: the bound evidence of the package, the resolved punch list with its
photos and their evidence, the commissioning certificates, the signed
acceptance, an index PDF and a ZIP. What a complete dossier must contain is a
per-package checklist kept in ``package.metadata["dossier"]``; the defaults
below are a neutral starting point that every market can edit, and nothing
here names a national form.

This module holds the parts that need no database: the checklist defaults and
their normalisation, and the scope rule that decides whether a punch item, a
commissioning system or a condition record belongs to an area or asset dossier.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "CATEGORY_ACCEPTANCE",
    "DEFAULT_DOSSIER_CONFIG",
    "DELIVERY_CHANNELS",
    "DOSSIER_RULE_SET",
    "SCOPE_KINDS",
    "matches_scope",
    "normalise_config",
    "normalise_scope",
    "scope_label",
    "scope_slug",
]

#: Rule set the dossier completeness rules register under.
DOSSIER_RULE_SET = "closeout_dossier"

#: Closeout slot category of the signed acceptance / taking-over certificate.
CATEGORY_ACCEPTANCE = "acceptance"

#: Scope kinds: the whole project, one area (zone, floor, building part) or one asset.
SCOPE_KINDS = ("project", "area", "asset")

#: Ways a built dossier can leave the platform.
DELIVERY_CHANNELS = ("download", "webhook", "connector", "email")

#: The checklist a new package starts from. Every key is editable per package.
DEFAULT_DOSSIER_CONFIG: dict[str, Any] = {
    # Slot categories that must carry evidence (bound document, external
    # reference, or a generated artifact the build produces).
    "required_categories": [
        "as_built",
        "om_manual",
        "warranty",
        "commissioning",
        "punch_closure",
        CATEGORY_ACCEPTANCE,
    ],
    # Every punch item in scope is closed out (resolved, verified or closed).
    "require_punch_resolved": True,
    # Every closed-out punch item in scope carries at least one photo.
    "require_punch_photos": True,
    # Every commissioning system in scope is commissioned, no open critical issue.
    "require_commissioning_complete": True,
    # The acceptance document is bound and fully signed in the signing registry.
    "require_signed_acceptance": True,
    # Bound evidence of required categories is verified by a manager.
    "require_verified_evidence": False,
    # Lifetime of the share link a webhook, connector or email delivery carries.
    "share_expires_in_days": 30,
}

_BOOL_KEYS = (
    "require_punch_resolved",
    "require_punch_photos",
    "require_commissioning_complete",
    "require_signed_acceptance",
    "require_verified_evidence",
)
_CATEGORY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def normalise_config(raw: Any) -> dict[str, Any]:
    """Merge a stored or submitted checklist over the defaults, dropping junk.

    Unknown keys are ignored, booleans are coerced, categories are kept only
    when they look like slot category keys (deduplicated, order kept), and the
    share lifetime is clamped to 1..365 days.
    """
    out = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_DOSSIER_CONFIG.items()}
    if not isinstance(raw, dict):
        return out
    cats = raw.get("required_categories")
    if isinstance(cats, list):
        seen: list[str] = []
        for c in cats:
            key = str(c).strip().lower()
            if _CATEGORY_RE.match(key) and key not in seen:
                seen.append(key)
        out["required_categories"] = seen
    for key in _BOOL_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    days = raw.get("share_expires_in_days")
    if days is not None:
        try:
            out["share_expires_in_days"] = max(1, min(365, int(days)))
        except (TypeError, ValueError):
            pass
    return out


def normalise_scope(kind: str | None, value: str | None) -> dict[str, Any]:
    """A clean ``{"kind", "value"}`` scope; anything unusable falls back to the project."""
    k = (kind or "project").strip().lower()
    v = (value or "").strip()
    if k not in SCOPE_KINDS or k == "project" or not v:
        return {"kind": "project", "value": None}
    return {"kind": k, "value": v[:255]}


def scope_label(scope: dict[str, Any]) -> str:
    """Short human label of a scope for file names and the index header."""
    if scope.get("kind") in ("area", "asset") and scope.get("value"):
        return f"{scope['kind']}: {scope['value']}"
    return "project"


def scope_slug(scope: dict[str, Any]) -> str:
    """Filesystem-safe slug of a scope."""
    base = "project" if scope.get("kind") == "project" else f"{scope.get('kind')}-{scope.get('value')}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return slug[:60] or "project"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def matches_scope(scope: dict[str, Any], *, area: Any = None, asset_refs: tuple[Any, ...] = ()) -> bool:
    """Whether a record with this area and these asset references is in scope.

    A project scope takes everything. An area scope matches the record's area
    text case-insensitively, exactly or as a path prefix (``Level 2`` takes
    ``Level 2 / Room 2.14``). An asset scope matches any of the record's asset
    references exactly (a BIM element id, a plant item id or a tag).
    """
    kind = scope.get("kind")
    want = _norm(scope.get("value"))
    if kind not in ("area", "asset") or not want:
        return True
    if kind == "area":
        have = _norm(area)
        if not have:
            return False
        return have == want or have.startswith(want + " /") or have.startswith(want + "/")
    return any(_norm(ref) == want for ref in asset_refs if ref)
