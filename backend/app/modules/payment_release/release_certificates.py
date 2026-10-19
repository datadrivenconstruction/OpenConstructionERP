# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Certificates a payee must hold before a payment to it is released.

Some laws stop a payment until the payee shows a certificate: Egypt suspends
each interim and the final payment on a construction contract until the
contractor shows that its social insurance dues for the contract are paid.
The national packs already say which certificates a payee must hold before
being paid (``progress_billing.sub_payment_requirements.requirements``, the
same list the subcontractor claim rollup reads). A requirement takes part in
the payment release gate only when it says so::

    {"code": "social_insurance_clearance", "evidence": "certificate",
     "cert_type": "social_security_clearance",
     "gates": ["payment_release"],            # opt in to this gate
     "release_effect": "block" | "warn",      # what a missing certificate does
     "applies_to_kinds": ["interim", "final"],
     "needs_expert_review": true, "statute_reference": "...", ...}

Opt-in keeps a pack that wrote its requirements for the claim rollup from
blocking releases it never meant to. A contract may override the pack through
its payment terms (:data:`ENFORCEMENT_VALUES`): ``block`` or ``warn`` for
every gated requirement, ``off`` to switch the gate off, ``pack`` (the
default) to follow each requirement's own ``release_effect``.

The evidence is the payee's certificate on its subcontractor record
(``oe_subcontractors_certificate``), found from the contract's counterparty:
the subcontractor itself, or the subcontractor that links the counterparty's
contact. The rule (V19, :class:`app.modules.payment_release.validators.
ReleaseCertificatesRule`) judges each certificate on the release date.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The gate name a requirement lists in ``gates`` to take part here.
GATE = "payment_release"

#: How a contract enforces the gated requirements.
ENFORCEMENT_VALUES: tuple[str, ...] = ("pack", "block", "warn", "off")

#: Where a contract keeps its choice, in ``PaymentTerms.metadata``.
ENFORCEMENT_KEY = "release_certificates_enforcement"

#: What a missing certificate does when the requirement says nothing.
DEFAULT_EFFECT = "warn"

#: The invoice kinds a requirement covers when it names none.
DEFAULT_KINDS: tuple[str, ...] = ("interim", "final")


def gated_requirements(progress_billing: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The requirements of a pack's progress billing block that take part in the payment release gate.

    Each is returned in a plain shape the rule reads: ``code``, ``cert_type``,
    ``release_effect`` (``block`` or ``warn``), ``applies_to_kinds``,
    ``statute_reference`` and ``needs_expert_review``.
    """
    block = progress_billing.get("sub_payment_requirements") if isinstance(progress_billing, Mapping) else None
    raw = block.get("requirements") if isinstance(block, Mapping) else None
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, Mapping) or item.get("evidence") != "certificate":
            continue
        gates = item.get("gates")
        if not isinstance(gates, list | tuple) or GATE not in gates:
            continue
        cert_type = str(item.get("cert_type") or "").strip()
        if not cert_type:
            continue
        effect = str(item.get("release_effect") or DEFAULT_EFFECT)
        kinds = item.get("applies_to_kinds")
        out.append(
            {
                "code": str(item.get("code") or cert_type),
                "cert_type": cert_type,
                "release_effect": effect if effect in ("block", "warn") else DEFAULT_EFFECT,
                "applies_to_kinds": [str(k) for k in kinds] if isinstance(kinds, list | tuple) else list(DEFAULT_KINDS),
                "statute_reference": str(item.get("statute_reference") or ""),
                "needs_expert_review": item.get("needs_expert_review") is True,
            }
        )
    return out


def normalise_enforcement(value: Any) -> str:
    """One of :data:`ENFORCEMENT_VALUES`; anything else reads as ``pack``."""
    text = str(value or "").strip().lower()
    return text if text in ENFORCEMENT_VALUES else "pack"


def effective_severity(requirement: Mapping[str, Any], enforcement: str) -> str | None:
    """``"error"``, ``"warning"`` or ``None`` (not checked) for a requirement under a contract's enforcement."""
    if enforcement == "off":
        return None
    effect = enforcement if enforcement in ("block", "warn") else str(requirement.get("release_effect") or "")
    return "error" if effect == "block" else "warning"


async def counterparty_certificates(
    session: AsyncSession, counterparty_ids: Iterable[str | None]
) -> dict[str, list[dict[str, Any]]]:
    """The certificates each counterparty holds as a subcontractor, keyed by the counterparty id.

    A counterparty id may be a subcontractor's own id or the id of the contact
    a subcontractor links. A counterparty with no subcontractor record holds
    nothing here. Returns plain dicts: ``cert_type``, ``issue_date``,
    ``valid_until`` (ISO strings or ``""``), ``status`` and ``revoked``.
    """
    wanted: list[uuid.UUID] = []
    for raw in counterparty_ids:
        try:
            wanted.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not wanted:
        return {}
    try:
        from app.modules.subcontractors.models import Certificate, Subcontractor  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        if exc.name not in ("app.modules.subcontractors", "app.modules.subcontractors.models"):
            raise
        return {}
    subs = (
        await session.execute(
            select(Subcontractor).where(or_(Subcontractor.id.in_(wanted), Subcontractor.contact_id.in_(wanted)))
        )
    ).scalars()
    owner_by_sub: dict[uuid.UUID, list[str]] = {}
    for sub in subs:
        for key in (sub.id, sub.contact_id):
            if key in wanted:
                owner_by_sub.setdefault(sub.id, []).append(str(key))
    if not owner_by_sub:
        return {}
    certs = (
        await session.execute(select(Certificate).where(Certificate.subcontractor_id.in_(list(owner_by_sub))))
    ).scalars()
    out: dict[str, list[dict[str, Any]]] = {}
    for cert in certs:
        row = {
            "cert_type": cert.cert_type,
            "issue_date": cert.issue_date.isoformat() if cert.issue_date else "",
            "valid_until": cert.valid_until.isoformat() if cert.valid_until else "",
            "status": cert.status,
            "revoked": bool(cert.revoked),
        }
        for owner in owner_by_sub.get(cert.subcontractor_id, []):
            out.setdefault(owner, []).append(row)
    return out


__all__ = [
    "DEFAULT_KINDS",
    "ENFORCEMENT_KEY",
    "ENFORCEMENT_VALUES",
    "GATE",
    "counterparty_certificates",
    "effective_severity",
    "gated_requirements",
    "normalise_enforcement",
]
