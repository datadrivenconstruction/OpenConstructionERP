# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic for the e-signature registry.

The heart of this module is a set of pure, jurisdiction-neutral functions that a
data model alone cannot express and that unit tests drive without a session:

    recompute_session_status  - derive the workflow status from the recorded
                                attestations, the signatory map and the expiry.
    all_required_signatories_signed - the ``all_required_signatories_signed``
                                validation rule as a pure predicate.
    delta_by_hash             - which recorded signatures are now stale because
                                the session's content hash moved on since they
                                signed (a re-sign is needed).
    cert_expiry_flags         - which signatures carry certificate metadata that
                                is expired or expiring within N days.
    issued_set_manifest       - the {document_ref: content_hash} manifest of an
                                issued set of sessions.

None of this performs cryptography. Certificate fields are descriptive metadata;
the content hashes are opaque strings the caller supplies.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from datetime import date as _date
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status

from app.modules.signing.models import Signature, SigningSession
from app.modules.signing.providers import get_provider
from app.modules.signing.repository import SigningRepository
from app.modules.signing.schemas import (
    AttestationCreate,
    DeclineCreate,
    SigningSessionCreate,
    SigningSessionUpdate,
)

logger = logging.getLogger(__name__)

# Terminal states the recompute path must never silently leave.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"declined"})


# ── Pure attribute reader (works for ORM rows and plain dicts/namespaces) ──


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _required_roles(signatory_map: list) -> set[str]:
    """Roles in the map that must sign for the session to be fully signed."""
    roles: set[str] = set()
    for entry in signatory_map or []:
        role = _field(entry, "role")
        required = _field(entry, "required")
        if role and (required is None or bool(required)):
            roles.add(role)
    return roles


def _signed_roles(signatures: Any) -> set[str]:
    return {
        _field(s, "signatory_role")
        for s in signatures
        if _field(s, "status") == "signed" and _field(s, "signatory_role")
    }


# ── Validation rule: all_required_signatories_signed ───────────────────────


def all_required_signatories_signed(signatory_map: list, signatures: Any) -> bool:
    """Return True when every *required* signatory has a ``signed`` attestation.

    This is the ``all_required_signatories_signed`` validation rule expressed as
    a pure predicate. A session with no required signatories is not considered
    "fully signed" by this rule (there is nothing whose completion to assert).
    """
    required = _required_roles(signatory_map)
    if not required:
        return False
    return required <= _signed_roles(signatures)


# ── Status recompute ───────────────────────────────────────────────────────


def recompute_session_status(
    signatory_map: list,
    signatures: Any,
    *,
    expires_at: datetime | None = None,
    now: datetime | None = None,
    current_status: str | None = None,
) -> str:
    """Derive the session status from its attestations, map and expiry.

    Pure function so unit tests drive it without a session.

    Precedence:
        1. A declined attestation (or a session already ``declined``) is terminal
           -> ``declined``.
        2. All required signatories signed -> ``fully_signed`` (wins over
           expiry: a fully executed document is not retroactively "expired").
        3. Past ``expires_at`` -> ``expired``.
        4. At least one signed attestation -> ``partially_signed``.
        5. An explicit ``draft`` with nothing signed stays ``draft``; otherwise
           ``awaiting_signatures``.
    """
    if current_status in _TERMINAL_STATUSES:
        return "declined"
    if any(_field(s, "status") == "declined" for s in signatures):
        return "declined"

    if all_required_signatories_signed(signatory_map, signatures):
        return "fully_signed"

    if expires_at is not None and now is not None and now > expires_at:
        return "expired"

    signed = _signed_roles(signatures)
    if signed:
        return "partially_signed"
    if current_status == "draft":
        return "draft"
    return "awaiting_signatures"


# ── Delta by hash ──────────────────────────────────────────────────────────


def delta_by_hash(session: Any, new_content_hash: str) -> set[str]:
    """Signatory names whose signatures are stale under ``new_content_hash``.

    A signature is stale when it was ``signed`` against a content hash different
    from ``new_content_hash`` - the content moved on since they signed, so a
    re-sign is required. ``session`` may be a session-like object exposing
    ``signatures`` or a plain iterable of signatures.
    """
    signatures = _field(session, "signatures")
    if signatures is None:
        signatures = session  # allow passing an iterable of signatures directly
    return {
        _field(s, "signatory_name")
        for s in signatures
        if _field(s, "status") == "signed" and _field(s, "content_hash") != new_content_hash
    }


# ── Certificate expiry ─────────────────────────────────────────────────────


def cert_expiry_flags(
    signatures: Any,
    *,
    today: _date,
    within_days: int = 30,
) -> list[dict[str, Any]]:
    """Flag signatures whose certificate metadata is expired or expiring soon.

    Considers only ``signed`` attestations that carry a ``cert_valid_until``.
    Includes already-expired certificates (negative ``days_until_expiry``).
    """
    flagged: list[dict[str, Any]] = []
    for s in signatures:
        if _field(s, "status") != "signed":
            continue
        valid_until = _field(s, "cert_valid_until")
        if valid_until is None:
            continue
        days = (valid_until - today).days
        if days <= within_days:
            flagged.append(
                {
                    "session_id": _field(s, "session_id"),
                    "signature_id": _field(s, "id"),
                    "signatory_name": _field(s, "signatory_name"),
                    "signatory_role": _field(s, "signatory_role"),
                    "cert_subject": _field(s, "cert_subject"),
                    "cert_valid_until": valid_until,
                    "days_until_expiry": days,
                    "expired": days < 0,
                }
            )
    flagged.sort(key=lambda f: f["days_until_expiry"])
    return flagged


# ── Issued-set manifest ────────────────────────────────────────────────────


def issued_set_manifest(sessions: Any) -> dict[str, str]:
    """Compute the ``{document_ref: content_hash}`` manifest of a set of sessions.

    The "issued-set hash manifest": a compact, verifiable fingerprint of what was
    issued for signature. When two sessions share a ``document_ref`` the later
    content hash wins, so the manifest reflects the current issued content.
    """
    manifest: dict[str, str] = {}
    for s in sessions:
        ref = _field(s, "document_ref")
        content_hash = _field(s, "document_content_hash")
        if ref and content_hash:
            manifest[ref] = content_hash
    return manifest


# ── Service ────────────────────────────────────────────────────────────────


class SigningService:
    """Business logic for the e-signature registry."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.repo = SigningRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    # ── Sessions ────────────────────────────────────────────────────────

    async def create_session(
        self,
        data: SigningSessionCreate,
        *,
        user_id: str | None = None,
    ) -> SigningSession:
        signatory_map = [s.model_dump() for s in data.signatory_map]
        # Status derivation goes through the provider interface (see
        # app.modules.signing.providers) rather than calling
        # recompute_session_status directly, so a registered adapter could
        # override it later without a call-site change here. The built-in
        # NullProvider delegates straight back to recompute_session_status,
        # so behaviour is unchanged.
        provider = get_provider(data.provider_capability)
        status = provider.check_status(
            SimpleNamespace(
                signatory_map=signatory_map,
                expires_at=data.expires_at,
                # Only honour an *explicit* draft; a session opened without a
                # status and with signatories to collect is awaiting_signatures,
                # not draft.
                status=data.status,
            ),
            [],
        ).status
        session_row = SigningSession(
            project_id=data.project_id,
            document_ref=data.document_ref,
            document_content_hash=data.document_content_hash,
            provider_capability=data.provider_capability,
            # What the registry actually resolved to, which is not necessarily
            # what the caller asked for: get_provider falls back to the
            # built-in provider for any capability no adapter has claimed.
            delivered_capability=provider.capability,
            signatory_map=signatory_map,
            status=status,
            expires_at=data.expires_at,
            metadata_=data.metadata,
            created_by=user_id,
        )
        session_row = await self.repo.create_session(session_row)

        # Best-effort provider initiation: for the built-in provider this is
        # a no-op acceptance (nothing external to dispatch); for a real
        # adapter this is where a signing request would go out. Never blocks
        # session creation - a provider hiccup here must not lose the
        # session the caller just asked to open.
        try:
            initiation = provider.initiate(session_row)
            merged_metadata = dict(session_row.metadata_ or {})
            merged_metadata["provider_initiation"] = initiation.as_dict()
            session_row.metadata_ = merged_metadata
            await self.session.flush()  # type: ignore[attr-defined]
        except Exception:
            logger.warning(
                "Signing provider initiate() failed for session %s; continuing without it",
                session_row.id,
                exc_info=True,
            )

        logger.info(
            "Signing session created: %s (%s) for project %s",
            session_row.id,
            session_row.provider_capability,
            session_row.project_id,
        )
        return session_row

    async def get_session(self, session_id: uuid.UUID) -> SigningSession:
        row = await self.repo.get_session(session_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Signing session not found.",
            )
        return row

    async def list_sessions(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        capability: str | None = None,
    ) -> list[SigningSession]:
        return await self.repo.list_sessions(project_id, status=status, capability=capability)

    async def list_signatures(self, session_id: uuid.UUID) -> list[Signature]:
        return await self.repo.list_signatures_for_session(session_id)

    async def update_session(
        self,
        session_id: uuid.UUID,
        data: SigningSessionUpdate,
        *,
        user_id: str | None = None,
    ) -> SigningSession:
        session_row = await self.get_session(session_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        if "signatory_map" in fields and fields["signatory_map"] is not None:
            fields["signatory_map"] = [s.model_dump() if hasattr(s, "model_dump") else s for s in data.signatory_map]

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(session_row.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        for key, value in fields.items():
            setattr(session_row, key, value)

        # Re-derive status from the (possibly changed) map / expiry against the
        # existing attestations, unless the caller pinned draft/awaiting. Goes
        # through the provider interface (see create_session for why).
        signatures = await self.repo.list_signatures_for_session(session_id)
        explicit_status = fields.get("status")
        provider = get_provider(session_row.provider_capability)
        # The required capability is editable, so re-resolve and re-stamp:
        # otherwise raising the requirement would leave the old delivered
        # value standing beside the new requirement.
        session_row.delivered_capability = provider.capability
        session_row.status = provider.check_status(
            SimpleNamespace(
                signatory_map=session_row.signatory_map,
                expires_at=session_row.expires_at,
                status=explicit_status or session_row.status,
            ),
            signatures,
        ).status

        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(session_row)  # type: ignore[attr-defined]
        return session_row

    async def delete_session(self, session_id: uuid.UUID) -> None:
        await self.get_session(session_id)
        await self.repo.delete_session(session_id)

    # ── Attestations ────────────────────────────────────────────────────

    async def record_attestation(
        self,
        session_id: uuid.UUID,
        data: AttestationCreate,
        *,
        user_id: str | None = None,
    ) -> SigningSession:
        session_row = await self.get_session(session_id)
        self._reject_if_terminal(session_row)

        signature = Signature(
            session_id=session_row.id,
            project_id=session_row.project_id,
            signatory_name=data.signatory_name,
            signatory_role=data.signatory_role,
            signed_at=data.signed_at or self._now(),
            cert_subject=data.cert_subject,
            cert_valid_until=data.cert_valid_until,
            content_hash=data.content_hash,
            status="signed",
            notes=data.notes,
            created_by=user_id,
        )
        await self.repo.add_signature(signature)
        return await self._recompute_and_save(session_row)

    async def record_decline(
        self,
        session_id: uuid.UUID,
        data: DeclineCreate,
        *,
        user_id: str | None = None,
    ) -> SigningSession:
        session_row = await self.get_session(session_id)
        self._reject_if_terminal(session_row)

        signature = Signature(
            session_id=session_row.id,
            project_id=session_row.project_id,
            signatory_name=data.signatory_name,
            signatory_role=data.signatory_role,
            signed_at=self._now(),
            content_hash="",
            status="declined",
            notes=data.reason,
            created_by=user_id,
        )
        await self.repo.add_signature(signature)
        return await self._recompute_and_save(session_row)

    def _reject_if_terminal(self, session_row: SigningSession) -> None:
        if session_row.status in _TERMINAL_STATUSES:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot record against a declined signing session.",
            )

    async def _recompute_and_save(self, session_row: SigningSession) -> SigningSession:
        signatures = await self.repo.list_signatures_for_session(session_row.id)
        provider = get_provider(session_row.provider_capability)
        session_row.delivered_capability = provider.capability
        session_row.status = provider.check_status(
            SimpleNamespace(
                signatory_map=session_row.signatory_map,
                expires_at=session_row.expires_at,
                status=session_row.status,
            ),
            signatures,
        ).status
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(session_row)  # type: ignore[attr-defined]
        return session_row

    # ── Views: stale, certs, manifest ───────────────────────────────────

    async def stale_signatories(
        self,
        session_id: uuid.UUID,
        *,
        content_hash: str | None = None,
    ) -> set[str]:
        session_row = await self.get_session(session_id)
        target_hash = content_hash or session_row.document_content_hash
        signatures = await self.repo.list_signatures_for_session(session_id)
        return delta_by_hash(signatures, target_hash)

    async def expiring_certs(
        self,
        project_id: uuid.UUID,
        *,
        within_days: int = 30,
    ) -> list[dict[str, Any]]:
        signatures = await self.repo.list_signatures_for_project(project_id)
        return cert_expiry_flags(signatures, today=self._now().date(), within_days=within_days)

    async def session_manifest(self, session_id: uuid.UUID) -> dict[str, Any]:
        session_row = await self.get_session(session_id)
        signatures = await self.repo.list_signatures_for_session(session_id)
        current = session_row.document_content_hash
        provider = get_provider(session_row.provider_capability)
        artifact = provider.fetch_artifact(session_row, signatures)
        return {
            "session_id": str(session_row.id),
            "document_ref": session_row.document_ref,
            "document_content_hash": current,
            "provider_capability": session_row.provider_capability,
            # The manifest is the closest thing this module has to a legal
            # record, so it carries what was delivered next to what was
            # required. NULL stays NULL: a session last derived before this
            # field existed does not get to borrow the required value.
            "delivered_capability": session_row.delivered_capability,
            "status": session_row.status,
            "manifest": issued_set_manifest([session_row]),
            # Provider-reported view of the same manifest plus (when a
            # provider produces one) certificate metadata. Additive - the
            # top-level "manifest" key above is unchanged for existing
            # callers.
            "provider_artifact": artifact.as_dict(),
            "signatures": [
                {
                    "signatory_name": s.signatory_name,
                    "signatory_role": s.signatory_role,
                    "status": s.status,
                    "content_hash": s.content_hash,
                    "matches_current": s.status == "signed" and s.content_hash == current,
                    "signed_at": s.signed_at.isoformat() if s.signed_at else None,
                }
                for s in signatures
            ],
        }
