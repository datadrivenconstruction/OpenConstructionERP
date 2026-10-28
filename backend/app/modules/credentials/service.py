# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic for the professional-credentials registry.

Two services live here.

:class:`CredentialService` owns the individual credential: deriving its
``status`` from its validity window, and firing a ``credentials.expiry.alert``
event the moment a credential *transitions* into an alerting bucket so a
notification subscriber can warn the team before a licence lapses.

The status rule is applied on write *and* on every read. Nothing rewrites a row
as the calendar moves past it, so the stored column is only ever as fresh as the
last edit; treating it as the answer is what let a credential entered a year ago
report itself active forty days after it expired. The column survives as an
index-friendly cache that ``refresh_statuses`` converges when asked, never as a
side effect of a GET. Its SQL twin lives in the repository, and the two are
pinned against each other by test, because a filter and a label that disagree
produce output in which nothing looks wrong.

:class:`RequirementService` owns what the project demands: which credential
types are required of whom, and the compliance report that joins requirements to
holders to answer who may not work today. A missing credential, a lapsed one
past its grace window and a suspended one all block; an upcoming expiry never
does, because a ticket valid until Friday is valid today.

Both are jurisdiction-neutral - the country-specific "notify authority within N
days" content is carried as data on the row, never as logic here.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status

from app.core.events import event_bus
from app.core.validation.engine import validation_engine
from app.dependencies import verify_project_access
from app.modules.credentials.models import Credential, CredentialRequirement
from app.modules.credentials.repository import CredentialRepository, RequirementRepository
from app.modules.credentials.schemas import (
    APPLIES_TO_ALL,
    PERSONNEL_CREDENTIAL_TYPES,
    ComplianceGap,
    ComplianceHolderRow,
    ComplianceReport,
    CredentialCreate,
    CredentialSummary,
    CredentialsValidationFinding,
    CredentialsValidationReport,
    CredentialUpdate,
    CredentialVerifyRequest,
    RequirementCreate,
    RequirementUpdate,
)
from app.modules.credentials.validators import CREDENTIALS_RULE_SET

logger = logging.getLogger(__name__)

# Buckets whose *entry* fires the expiry alert.
_ALERT_STATUSES: frozenset[str] = frozenset({"expiring_soon", "expired"})

# Manual states the date-derive path must never overwrite. ``revoked`` is
# terminal (a revoked credential cannot be reinstated in place - issue a new
# one); ``suspended`` is reversible back to a live state.
_MANUAL_STATUSES: frozenset[str] = frozenset({"suspended", "revoked"})
_TERMINAL_STATUSES: frozenset[str] = frozenset({"revoked"})


def recompute_status(
    today: _date,
    valid_until: _date | None,
    notify_days_before: int,
    *,
    current_status: str | None = None,
) -> str:
    """Derive ``status`` from the validity window.

    Pure function so unit tests drive it without a session.

    Rules:
        - A ``suspended`` / ``revoked`` credential keeps that manual state - the
          auto-derive path never flips it back to active.
        - ``valid_until is None`` → ``active`` (a perpetual credential that
          never expires).
        - ``today > valid_until`` → ``expired``.
        - ``valid_until - today <= notify_days_before`` → ``expiring_soon``
          (inclusive on the boundary day so a reminder is never skipped).
        - Otherwise → ``active``.
    """
    if current_status in _MANUAL_STATUSES:
        return current_status  # type: ignore[return-value]
    if valid_until is None:
        return "active"
    if today > valid_until:
        return "expired"
    delta = (valid_until - today).days
    if delta <= max(0, notify_days_before):
        return "expiring_soon"
    return "active"


class CredentialService:
    """Business logic for the credentials registry."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.repo = CredentialRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _today() -> _date:
        return datetime.now(UTC).date()

    @staticmethod
    def _publish_expiry_alert(
        credential: Credential,
        *,
        previous_status: str | None,
    ) -> None:
        """Fire ``credentials.expiry.alert`` on a status transition.

        Only the *transition* into ``expiring_soon`` / ``expired`` fires - a
        PATCH that leaves the credential in the same alert bucket does not
        re-spam subscribers. ``previous_status=None`` is the create path.
        """
        if credential.status not in _ALERT_STATUSES:
            return
        if previous_status == credential.status:
            return

        try:
            today = datetime.now(UTC).date()
            days = (credential.valid_until - today).days if credential.valid_until else 0
        except TypeError:  # pragma: no cover - defensive
            days = 0

        personnel_document = credential.credential_type in PERSONNEL_CREDENTIAL_TYPES
        # Detached publish so a notifications subscriber opening its own session
        # can't contend with the request's write transaction.
        event_bus.publish_detached(
            "credentials.expiry.alert",
            {
                "credential_id": str(credential.id),
                "project_id": str(credential.project_id),
                "credential_type": credential.credential_type,
                # A personnel document's alert names nobody: the staffing file knows whom to tell.
                "holder_name": None if personnel_document else credential.holder_name,
                "holder_user_id": (
                    str(credential.holder_user_id) if credential.holder_user_id and not personnel_document else None
                ),
                "authority": credential.authority,
                "status": credential.status,
                "valid_until": (credential.valid_until.isoformat() if credential.valid_until else None),
                "days_until_expiry": days,
                "notify_days_before": credential.notify_days_before,
                "previous_status": previous_status,
            },
            source_module="credentials",
        )

    # ── CRUD ────────────────────────────────────────────────────────────

    @staticmethod
    def _guard_personnel(credential_type: str, *, personnel: bool, carries_detail: bool) -> None:
        """Keep personnel documents out of the register, and details out of personnel documents.

        ``personnel`` is passed by the staffing personnel file, the one caller
        that has checked the relationship to the person. No route of this module
        passes it.
        """
        if credential_type not in PERSONNEL_CREDENTIAL_TYPES:
            return
        if not personnel:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="This credential type is a personnel document and is recorded in the personnel file.",
            )
        if carries_detail:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="A personnel document holds its validity window only: no identifier, notes or metadata.",
            )

    async def create_credential(
        self,
        data: CredentialCreate,
        *,
        user_id: str | None = None,
        personnel: bool = False,
    ) -> Credential:
        self._guard_personnel(
            data.credential_type,
            personnel=personnel,
            carries_detail=bool(data.identifier or data.notes or data.metadata),
        )
        derived_status = data.status or recompute_status(
            today=self._today(),
            valid_until=data.valid_until,
            notify_days_before=data.notify_days_before,
        )

        credential = Credential(
            project_id=data.project_id,
            holder_name=data.holder_name,
            holder_kind=data.holder_kind,
            holder_user_id=data.holder_user_id,
            credential_type=data.credential_type,
            discipline=data.discipline,
            authority=data.authority,
            identifier=data.identifier,
            jurisdiction=data.jurisdiction,
            issued_at=data.issued_at,
            valid_until=data.valid_until,
            notify_days_before=data.notify_days_before,
            notification_obligation_days=data.notification_obligation_days,
            notification_trigger=data.notification_trigger,
            status=derived_status,
            notes=data.notes,
            metadata_=data.metadata,
            created_by=user_id,
        )
        credential = await self.repo.create(credential)
        logger.info(
            "Credential created: %s (%s) for project %s",
            credential.id,
            credential.credential_type,
            credential.project_id,
        )
        self._publish_expiry_alert(credential, previous_status=None)
        return credential

    @staticmethod
    def _not_found() -> HTTPException:
        """The single 404 every credential-scoped refusal raises.

        One object, one message, whether the id does not exist or belongs to a
        project the caller cannot see.
        """
        return HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Credential not found.",
        )

    async def get_credential(self, credential_id: uuid.UUID) -> Credential:
        row = await self.repo.get_by_id(credential_id)
        if row is None:
            raise self._not_found()
        return row

    async def get_credential_for_caller(
        self,
        credential_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID,
    ) -> Credential:
        """Resolve a credential the caller is allowed to see, or 404 alike.

        Resolving first and authorising second is what makes an id walkable if
        the two failures are told apart: an id that does not exist answered
        "Credential not found." while one on somebody else's project answered
        "Project not found", which is the existence bit the 404 was chosen to
        withhold. Both now raise the same object.
        """
        credential = await self.get_credential(credential_id)
        # A personnel document is not a register entry: the same 404 as an id that does not exist.
        if credential.credential_type in PERSONNEL_CREDENTIAL_TYPES:
            raise self._not_found()
        try:
            await verify_project_access(credential.project_id, str(actor_id), self.session)  # type: ignore[arg-type]
        except HTTPException:
            raise self._not_found() from None
        return credential

    async def list_credentials(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        credential_type: str | None = None,
        holder_user_id: uuid.UUID | None = None,
    ) -> list[Credential]:
        return await self.repo.list_for_project(
            project_id,
            today=self._today(),
            status=status,
            credential_type=credential_type,
            holder_user_id=holder_user_id,
        )

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> list[Credential]:
        return await self.repo.list_expiring_soon(project_id, today=self._today(), limit=limit)

    async def update_credential(
        self,
        credential_id: uuid.UUID,
        data: CredentialUpdate,
        *,
        user_id: str | None = None,
        personnel: bool = False,
    ) -> Credential:
        credential = await self.get_credential(credential_id)
        previous_status = credential.status

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        carries_detail = bool(fields.get("identifier") or fields.get("notes") or fields.get("metadata"))
        # Neither the row as it is nor the type it would become may be a personnel document here.
        for kind in {credential.credential_type, fields.get("credential_type") or credential.credential_type}:
            self._guard_personnel(kind, personnel=personnel, carries_detail=carries_detail)

        # Date ordering guard if either side moved.
        new_issued = fields.get("issued_at", credential.issued_at)
        new_valid = fields.get("valid_until", credential.valid_until)
        if new_issued is not None and new_valid is not None and new_valid < new_issued:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="valid_until must be on or after issued_at.",
            )

        explicit_status = fields.get("status")
        # Terminal-state contract: a revoked credential cannot be transitioned
        # out of in place - the auto-derive path already preserves it; block the
        # explicit path too so it can't be reinstated by a stray PATCH.
        if (
            explicit_status is not None
            and credential.status in _TERMINAL_STATUSES
            and explicit_status != credential.status
        ):
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot transition out of a terminal status.",
            )
        if explicit_status is None:
            fields["status"] = recompute_status(
                today=self._today(),
                valid_until=new_valid,
                notify_days_before=fields.get("notify_days_before", credential.notify_days_before),
                current_status=credential.status,
            )

        # Apply the mutation on the loaded instance so metadata merge and the
        # metadata column alias are handled cleanly.
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(credential.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        if user_id is not None and credential.credential_type not in PERSONNEL_CREDENTIAL_TYPES:
            merged_meta = dict(fields.get("metadata_") or credential.metadata_ or {})
            merged_meta["updated_by"] = user_id
            merged_meta["updated_at"] = datetime.now(UTC).isoformat()
            fields["metadata_"] = merged_meta

        for key, value in fields.items():
            setattr(credential, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(credential)  # type: ignore[attr-defined]

        self._publish_expiry_alert(credential, previous_status=previous_status)
        return credential

    async def delete_credential(self, credential_id: uuid.UUID) -> None:
        await self.get_credential(credential_id)
        await self.repo.delete(credential_id)

    # ── Derived status, read side ───────────────────────────────────────

    def effective_status(self, credential: Credential, *, today: _date | None = None) -> str:
        """The status this credential actually has now.

        The stored column is only written when someone writes to the row, so it
        lags for exactly the credentials that matter: the ones ageing towards
        expiry. Every read path reports this value instead, which is why a
        response can never carry ``status="active"`` beside a negative
        ``days_until_expiry``.
        """
        return recompute_status(
            today=today or self._today(),
            valid_until=credential.valid_until,
            notify_days_before=credential.notify_days_before,
            current_status=credential.status,
        )

    async def refresh_statuses(self, project_id: uuid.UUID) -> tuple[int, int]:
        """Write the derived status back onto rows that have drifted.

        Reads stay correct without this - they derive the status every time.
        This exists so the stored column, which carries the index, catches up
        with reality, and so the expiry event fires for a credential that
        lapsed while nobody was editing it.

        Returns:
            A ``(examined, updated)`` pair.

        The mutation is applied to loaded ORM instances rather than through a
        bulk UPDATE: a bulk statement would need the caller's identity map
        invalidated afterwards, and doing that in an async session is a
        deferred ``MissingGreenlet`` waiting for the next attribute access.
        """
        today = self._today()
        drifted = await self.repo.list_drifted(project_id, today=today)
        if not drifted:
            return (0, 0)

        updated = 0
        for credential in drifted:
            previous_status = credential.status
            fresh = recompute_status(
                today=today,
                valid_until=credential.valid_until,
                notify_days_before=credential.notify_days_before,
                current_status=credential.status,
            )
            if fresh == previous_status:
                continue
            credential.status = fresh
            updated += 1
            self._publish_expiry_alert(credential, previous_status=previous_status)

        await self.session.flush()  # type: ignore[attr-defined]
        logger.info(
            "Credential status refresh for project %s: %d drifted, %d updated",
            project_id,
            len(drifted),
            updated,
        )
        return (len(drifted), updated)

    # ── Verification ────────────────────────────────────────────────────

    async def verify_credential(
        self,
        credential_id: uuid.UUID,
        data: CredentialVerifyRequest,
        *,
        user_id: str | None = None,
    ) -> Credential:
        """Record (or retract) a human check of a credential.

        Verification says nothing about validity: an expired ticket that was
        genuinely checked is still expired. It only distinguishes "somebody
        confirmed this against the issuing authority" from "somebody typed it
        in", which is the distinction an audit asks about.
        """
        credential = await self.get_credential(credential_id)

        if data.verified:
            verified_on = data.verified_at or self._today()
            if verified_on > self._today():
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="verified_at cannot be in the future.",
                )
            credential.verified_at = verified_on
            credential.verified_by = user_id
        else:
            credential.verified_at = None
            credential.verified_by = None

        if data.note:
            merged = dict(credential.metadata_ or {})
            merged["verification_note"] = data.note
            credential.metadata_ = merged

        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(credential)  # type: ignore[attr-defined]
        return credential

    # ── Summary ─────────────────────────────────────────────────────────

    async def summarise(self, project_id: uuid.UUID) -> CredentialSummary:
        """Counts for the register's dashboard tile, all on derived status."""
        today = self._today()
        by_status = await self.repo.count_by_effective_status(project_id, today=today)
        drifted = await self.repo.list_drifted(project_id, today=today, register_only=True)

        horizon = today + timedelta(days=30)
        expiring_30 = await self.repo.count_matching(
            project_id,
            Credential.valid_until.is_not(None),
            Credential.valid_until >= today,
            Credential.valid_until <= horizon,
            Credential.status.not_in(tuple(_MANUAL_STATUSES)),
        )
        unverified = await self.repo.count_matching(project_id, Credential.verified_at.is_(None))
        perpetual = await self.repo.count_matching(project_id, Credential.valid_until.is_(None))

        return CredentialSummary(
            project_id=project_id,
            as_of=today,
            total=sum(by_status.values()),
            by_status=by_status,
            expiring_within_30_days=expiring_30,
            expired=by_status.get("expired", 0),
            unverified=unverified,
            perpetual=perpetual,
            stale_status_count=len(drifted),
        )


# ── Compliance ──────────────────────────────────────────────────────────

# Gap reasons that stop work when the requirement is a blocking one.
# ``expiring_soon`` is deliberately absent: a credential valid until Friday is
# valid today, and a register that blocks people for a future expiry would be
# ignored within a week.
_BLOCKING_REASONS: frozenset[str] = frozenset({"missing", "expired", "suspended", "revoked"})

# How good a credential is at satisfying a requirement, best first. Used to pick
# which of a holder's several credentials of one type is the one to report on.
_STATUS_RANK: dict[str, int] = {
    "active": 0,
    "expiring_soon": 1,
    "expired": 2,
    "suspended": 3,
    "revoked": 4,
}


def _holder_key(credential: Credential) -> tuple[str, str]:
    """Identity a holder is grouped by.

    The user link wins when present, because two spellings of one name are one
    person. Otherwise the case-folded name plus kind, which is the best the
    register can do for someone who is not a platform user.
    """
    if credential.holder_user_id is not None:
        return ("user", str(credential.holder_user_id))
    return ("name", f"{credential.holder_kind}:{credential.holder_name.strip().casefold()}")


class RequirementService:
    """Requirements, and the compliance report they make possible."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.repo = RequirementRepository(session)  # type: ignore[arg-type]
        self.credential_repo = CredentialRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _today() -> _date:
        return datetime.now(UTC).date()

    # ── CRUD ────────────────────────────────────────────────────────────

    @staticmethod
    def _not_found() -> HTTPException:
        """The single 404 every requirement-scoped refusal raises."""
        return HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Requirement not found.",
        )

    async def get_requirement(self, requirement_id: uuid.UUID) -> CredentialRequirement:
        row = await self.repo.get_by_id(requirement_id)
        if row is None:
            raise self._not_found()
        return row

    async def get_requirement_for_caller(
        self,
        requirement_id: uuid.UUID,
        *,
        actor_id: str | uuid.UUID,
    ) -> CredentialRequirement:
        """Resolve a requirement the caller may see, or 404 indistinguishably.

        Same reasoning as the credential side: "no such requirement" and "not
        your project" must be one answer.
        """
        requirement = await self.get_requirement(requirement_id)
        try:
            await verify_project_access(requirement.project_id, str(actor_id), self.session)  # type: ignore[arg-type]
        except HTTPException:
            raise self._not_found() from None
        return requirement

    async def list_requirements(
        self,
        project_id: uuid.UUID,
        *,
        include_inactive: bool = False,
    ) -> list[CredentialRequirement]:
        return await self.repo.list_for_project(project_id, include_inactive=include_inactive)

    @staticmethod
    def _refuse_personnel_type(credential_type: str) -> None:
        """A register requirement cannot ask for a personnel document: the register never sees those rows,
        so the report would list every holder as missing it. The staffing catalogue states that requirement."""
        if credential_type in PERSONNEL_CREDENTIAL_TYPES:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Personnel documents are required and checked in the personnel file, not in this register.",
            )

    async def create_requirement(
        self,
        data: RequirementCreate,
        *,
        user_id: str | None = None,
    ) -> CredentialRequirement:
        self._refuse_personnel_type(data.credential_type)
        clash = await self.repo.find_conflict(
            data.project_id,
            credential_type=data.credential_type,
            applies_to=data.applies_to,
            holder_kind=data.holder_kind,
        )
        if clash is not None:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="A requirement already covers this credential type and audience.",
            )

        requirement = CredentialRequirement(
            project_id=data.project_id,
            credential_type=data.credential_type,
            applies_to=data.applies_to,
            holder_kind=data.holder_kind,
            is_blocking=data.is_blocking,
            grace_days=data.grace_days,
            description=data.description,
            is_active=data.is_active,
            metadata_=data.metadata,
            created_by=user_id,
        )
        requirement = await self.repo.create(requirement)
        logger.info(
            "Credential requirement created: %s (%s) for project %s",
            requirement.id,
            requirement.credential_type,
            requirement.project_id,
        )
        return requirement

    async def update_requirement(
        self,
        requirement_id: uuid.UUID,
        data: RequirementUpdate,
        *,
        user_id: str | None = None,
    ) -> CredentialRequirement:
        requirement = await self.get_requirement(requirement_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if fields.get("credential_type"):
            self._refuse_personnel_type(fields["credential_type"])

        # Re-check the uniqueness scope if any part of it moved.
        if {"credential_type", "applies_to", "holder_kind"} & fields.keys():
            clash = await self.repo.find_conflict(
                requirement.project_id,
                credential_type=fields.get("credential_type", requirement.credential_type),
                applies_to=fields.get("applies_to", requirement.applies_to),
                holder_kind=fields.get("holder_kind", requirement.holder_kind),
                exclude_id=requirement.id,
            )
            if clash is not None:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="A requirement already covers this credential type and audience.",
                )

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(requirement.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        if user_id is not None:
            merged_meta = dict(fields.get("metadata_") or requirement.metadata_ or {})
            merged_meta["updated_by"] = user_id
            merged_meta["updated_at"] = datetime.now(UTC).isoformat()
            fields["metadata_"] = merged_meta

        for key, value in fields.items():
            setattr(requirement, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(requirement)  # type: ignore[attr-defined]
        return requirement

    async def delete_requirement(self, requirement_id: uuid.UUID) -> None:
        await self.get_requirement(requirement_id)
        await self.repo.delete(requirement_id)

    # ── The report ──────────────────────────────────────────────────────

    @staticmethod
    def _applies(requirement: CredentialRequirement, discipline: str | None, kind: str) -> bool:
        """Whether a requirement binds a holder of this kind and discipline."""
        if requirement.holder_kind != kind:
            return False
        if requirement.applies_to == APPLIES_TO_ALL:
            return True
        if discipline is None:
            return False
        return requirement.applies_to.strip().casefold() == discipline.strip().casefold()

    def _assess(
        self,
        requirement: CredentialRequirement,
        candidates: list[Credential],
        *,
        today: _date,
    ) -> tuple[ComplianceGap | None, Credential | None]:
        """Judge one requirement against one holder's matching credentials.

        Returns:
            A ``(gap, satisfying_credential)`` pair. Exactly one side is set:
            a gap when the requirement is unmet (or met but lapsing), otherwise
            the credential that satisfies it.
        """
        if not candidates:
            return (
                ComplianceGap(
                    requirement_id=requirement.id,
                    credential_type=requirement.credential_type,
                    applies_to=requirement.applies_to,
                    reason="missing",
                    is_blocking=requirement.is_blocking,
                    grace_days=requirement.grace_days,
                ),
                None,
            )

        def rank(cred: Credential) -> tuple[int, int]:
            status = recompute_status(
                today=today,
                valid_until=cred.valid_until,
                notify_days_before=cred.notify_days_before,
                current_status=cred.status,
            )
            # Perpetual credentials beat dated ones at equal status, so a
            # never-expiring licence is never reported as the lapsing one.
            days = 10**6 if cred.valid_until is None else (cred.valid_until - today).days
            return (_STATUS_RANK.get(status, 9), -days)

        best = min(candidates, key=rank)
        status = recompute_status(
            today=today,
            valid_until=best.valid_until,
            notify_days_before=best.notify_days_before,
            current_status=best.status,
        )
        days_left = None if best.valid_until is None else (best.valid_until - today).days

        if status == "active":
            return (None, best)

        reason = status if status in {"expired", "suspended", "revoked", "expiring_soon"} else "missing"
        # A lapse inside the grace window is reported but does not stop work.
        within_grace = reason == "expired" and days_left is not None and -days_left <= requirement.grace_days
        return (
            ComplianceGap(
                requirement_id=requirement.id,
                credential_type=requirement.credential_type,
                applies_to=requirement.applies_to,
                reason=reason,
                is_blocking=requirement.is_blocking,
                grace_days=requirement.grace_days,
                credential_id=best.id,
                valid_until=best.valid_until,
                days_until_expiry=days_left,
                within_grace=within_grace,
            ),
            None,
        )

    async def build_compliance_report(self, project_id: uuid.UUID) -> ComplianceReport:
        """Who may not work today, and what is about to stop them.

        The holder population is the register's own holders - every distinct
        person or firm that appears on a credential for this project. The report
        cannot name somebody it has never been told about, so a site roster held
        in another module is out of its reach by construction; the count of
        holders it did assess is returned so the reader can tell.
        """
        today = self._today()
        requirements = await self.repo.list_for_project(project_id)
        credentials = await self.credential_repo.list_for_project(project_id, today=today)

        holders: dict[tuple[str, str], dict[str, Any]] = {}
        for credential in credentials:
            key = _holder_key(credential)
            entry = holders.setdefault(
                key,
                {
                    "holder_name": credential.holder_name,
                    "holder_kind": credential.holder_kind,
                    "holder_user_id": credential.holder_user_id,
                    "discipline": credential.discipline,
                    "by_type": {},
                },
            )
            # A holder's discipline can be blank on one row and set on another;
            # the first non-empty value wins so a requirement scoped to a
            # discipline still binds them.
            if entry["discipline"] is None and credential.discipline is not None:
                entry["discipline"] = credential.discipline
            entry["by_type"].setdefault(credential.credential_type, []).append(credential)

        rows: list[ComplianceHolderRow] = []
        matched_requirements: set[uuid.UUID] = set()

        for entry in holders.values():
            gaps: list[ComplianceGap] = []
            satisfied = 0
            unverified = 0
            for requirement in requirements:
                if not self._applies(requirement, entry["discipline"], entry["holder_kind"]):
                    continue
                matched_requirements.add(requirement.id)
                gap, satisfying = self._assess(
                    requirement,
                    entry["by_type"].get(requirement.credential_type, []),
                    today=today,
                )
                if gap is not None:
                    gaps.append(gap)
                else:
                    satisfied += 1
                    if satisfying is not None and satisfying.verified_at is None:
                        unverified += 1

            is_blocked = any(g.is_blocking and g.reason in _BLOCKING_REASONS and not g.within_grace for g in gaps)
            rows.append(
                ComplianceHolderRow(
                    holder_name=entry["holder_name"],
                    holder_kind=entry["holder_kind"],
                    holder_user_id=entry["holder_user_id"],
                    discipline=entry["discipline"],
                    is_blocked=is_blocked,
                    gaps=gaps,
                    satisfied_count=satisfied,
                    unverified_count=unverified,
                )
            )

        # Blocked holders first, then by name, so the report opens on the people
        # who cannot work.
        rows.sort(key=lambda r: (not r.is_blocked, r.holder_name.casefold()))

        return ComplianceReport(
            project_id=project_id,
            as_of=today,
            requirement_count=len(requirements),
            holder_count=len(rows),
            blocked_holder_count=sum(1 for r in rows if r.is_blocked),
            holders=rows,
            unmatched_requirement_ids=[r.id for r in requirements if r.id not in matched_requirements],
        )

    # ── Validation ──────────────────────────────────────────────────────

    async def validate_project(self, project_id: uuid.UUID) -> CredentialsValidationReport:
        """Run the ``credentials`` rule set over one project's register.

        The rules read credentials, requirements and the compliance report, so
        the report is built first and handed to them rather than each rule
        re-deriving it.
        """
        today = self._today()
        requirements = await self.repo.list_for_project(project_id)
        credentials = await self.credential_repo.list_for_project(project_id, today=today)
        compliance = await self.build_compliance_report(project_id)

        report = await validation_engine.validate(
            data={
                "today": today,
                "credentials": credentials,
                "requirements": requirements,
                "compliance": compliance,
            },
            rule_sets=[CREDENTIALS_RULE_SET],
            target_type="credentials",
            target_id=str(project_id),
            project_id=str(project_id),
        )

        findings = [
            CredentialsValidationFinding(
                rule_id=result.rule_id,
                severity=str(result.severity),
                message=result.message,
                # Rule ids already carry the module segment, so the raw id would
                # render "credentials.validation.credentials.blocking_gap".
                key=f"credentials.validation.{result.rule_id.removeprefix('credentials.')}",
                context=result.details,
            )
            for result in report.results
            if not result.passed and not result.is_engine_error
        ]

        return CredentialsValidationReport(
            project_id=project_id,
            status=str(report.status),
            score=report.score,
            error_count=len(report.errors),
            warning_count=len(report.warnings),
            findings=findings,
        )
