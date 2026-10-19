# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ETA adapter: the clearance module's interface, spoken to ETA.

Submit signs the stored document (unless it is already signed), submits it,
and reads ETA's answer:

* the document is in ``rejectedDocuments``: a rejection with ETA's error code;
* it is in ``acceptedDocuments``: ETA has a UUID for it and validates it
  asynchronously. The adapter polls Get Submission a few times (as configured)
  and returns the verdict if it arrives, otherwise a *pending* outcome carrying
  the UUID, which leaves the document ``submitted`` until a refresh;
* ``422 DuplicateSubmission``: ETA already holds an identical submission from
  the last 10 minutes. That is raised, not returned, so the document stays
  ``submitted`` with an unknown outcome instead of becoming a rejection that
  invites a second send.

Poll reads Get Document Details for one document: ``Valid`` clears it,
``Invalid`` rejects it with the failing validation steps as the message.

Cancel reads the cancellation window ETA publishes for the document type (Get
Document Type, workflow parameters), refuses locally when it can see the window
has passed, and otherwise asks ETA, whose answer is final.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.einvoice_clearance.adapters import (
    CancellationRequest,
    PollRequest,
    SubmissionOutcome,
    SubmissionRequest,
)
from app.modules.einvoice_eta.client import (
    EtaApiError,
    EtaClient,
    EtaDuplicateSubmission,
    EtaEnvironment,
    EtaUrlRefused,
)
from app.modules.einvoice_eta.serialization import SIGNATURES_KEY, canonical_bytes, parse_preserving
from app.modules.einvoice_eta.signing import (
    SIGNATURE_TYPE_ISSUER,
    SIGNER_PRESIGNED,
    EtaSigningError,
    resolve_signer,
    verify_cades,
)

logger = logging.getLogger(__name__)

ETA_ADAPTER_KEY = "eta_eg"

ENV_PREPROD = "preprod"
ENV_PROD = "prod"
ENVIRONMENTS: tuple[str, ...] = (ENV_PREPROD, ENV_PROD)

# Codes this adapter returns on its own account, prefixed so nobody takes one
# for a code ETA issued.
CODE_NOT_CONFIGURED = "ETA-NOT-CONFIGURED"
CODE_SIGNING = "ETA-SIGNING"
CODE_NOT_IN_ANSWER = "ETA-NOT-IN-ANSWER"
CODE_WINDOW_CLOSED = "OperationPeriodOver"  # ETA's own code for the same refusal

# ETA's document statuses (Get Submission, Get Document Details).
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_SUBMITTED = "submitted"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"


def environment_hosts(environment: str) -> dict[str, str]:
    """ETA's published hosts for ``preprod`` or ``prod``, from the regime row.

    Read from the registry rather than repeated here, so the hosts and their
    source live in one place. Empty for any other environment name.
    """
    from app.modules.einvoice_clearance.regimes import COUNTRY_REGIMES

    entry = COUNTRY_REGIMES.get("EG")
    environments = (entry.extra or {}).get("environments", {}) if entry else {}
    hosts = environments.get(environment) if isinstance(environments, dict) else None
    return {k: str(v) for k, v in hosts.items()} if isinstance(hosts, dict) else {}


@dataclass(frozen=True)
class EtaSettings:
    """The ``settings["eta"]`` block of a registration, read once."""

    environment: str = ""
    identity_base_url: str = ""
    api_base_url: str = ""
    client_id_env: str = ""
    client_secret_env: str = ""
    on_behalf_of: str = ""
    signer: dict[str, Any] = field(default_factory=dict)
    poll_attempts: int = 3
    poll_interval_seconds: float = 2.0

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> EtaSettings:
        settings = profile.get("settings") if isinstance(profile.get("settings"), dict) else {}
        raw = settings.get("eta") if isinstance(settings.get("eta"), dict) else {}

        def text(name: str) -> str:
            return str(raw.get(name) or "").strip()

        try:
            attempts = int(raw.get("poll_attempts", 3))
        except (TypeError, ValueError):
            attempts = 3
        try:
            interval = float(raw.get("poll_interval_seconds", 2))
        except (TypeError, ValueError):
            interval = 2.0
        environment = text("environment").lower()
        hosts = environment_hosts(environment)
        return cls(
            environment=environment,
            identity_base_url=text("identity_base_url") or hosts.get("identity_base_url", ""),
            api_base_url=text("api_base_url") or hosts.get("api_base_url", ""),
            client_id_env=text("client_id_env"),
            client_secret_env=text("client_secret_env"),
            on_behalf_of=text("on_behalf_of"),
            signer=dict(raw.get("signer") or {}) if isinstance(raw.get("signer"), dict) else {},
            poll_attempts=max(0, min(attempts, 10)),
            poll_interval_seconds=max(0.0, min(interval, 30.0)),
        )


def settings_problems(profile: dict[str, Any]) -> list[str]:
    """What is missing or contradictory in a registration's ETA settings.

    The same list gates submission (the ``eta_profile`` rule) and is checked
    again here, so neither can let through what the other refuses.
    """
    settings = EtaSettings.from_profile(profile)
    sandbox = bool(profile.get("sandbox", True))
    problems: list[str] = []
    if settings.environment not in ENVIRONMENTS:
        problems.append("settings.eta.environment must be preprod or prod")
    elif settings.environment == ENV_PROD and sandbox:
        problems.append("the environment is prod but the registration is in sandbox mode")
    elif settings.environment == ENV_PREPROD and not sandbox:
        problems.append("the registration is live but the environment is preprod")
    for name in ("identity_base_url", "api_base_url"):
        value = getattr(settings, name)
        if not value:
            problems.append(f"settings.eta.{name} is not set and the environment gives no default")
        elif not value.startswith("https://"):
            problems.append(f"settings.eta.{name} must be an https URL")
    for name in ("client_id_env", "client_secret_env"):
        if not getattr(settings, name):
            problems.append(f"settings.eta.{name} must name the environment variable that holds the value")
    if not str(settings.signer.get("kind") or "").strip():
        problems.append("settings.eta.signer.kind is not set (pkcs11, external_http, presigned or test)")
    elif settings.signer.get("kind") == "test" and not sandbox:
        problems.append("a test signer cannot sign for a live registration")
    return problems


def insert_signatures(document_text: str, signatures: list[dict[str, str]]) -> str:
    """The stored document with ``signatures`` added before its closing brace.

    Every other byte stays as stored. The canonical form ignores formatting and
    leaves the signatures out, so the signature computed over the stored text
    is valid for the text sent.
    """
    body = document_text.rstrip()
    if not body.endswith("}"):
        raise EtaSigningError("The stored document is not a JSON object.")
    head = body[:-1].rstrip()
    separator = "" if head.endswith("{") else ","
    return f"{head}{separator}\n  {json.dumps(SIGNATURES_KEY)}: {json.dumps(signatures)}\n}}"


def has_signatures(document_text: str) -> bool:
    return any(name == SIGNATURES_KEY and value for name, value in parse_preserving(document_text))


def _internal_id(document_text: str) -> str:
    for name, value in parse_preserving(document_text):
        if name.lower() == "internalid":
            return str(value)
    return ""


def _errors_text(error: Any) -> str:
    """ETA's error object, flattened to the messages an accountant can act on."""
    if not isinstance(error, dict):
        return str(error or "")
    parts = [str(error.get("message") or error.get("code") or "")]
    for detail in error.get("details") or []:
        if isinstance(detail, dict):
            target = f" ({detail.get('target')})" if detail.get("target") else ""
            parts.append(f"{detail.get('message') or detail.get('code') or ''}{target}")
    return "; ".join(p for p in parts if p)


def _validation_errors(details: dict[str, Any]) -> str:
    results = details.get("validationResults") if isinstance(details.get("validationResults"), dict) else {}
    messages: list[str] = []
    for step in results.get("validationSteps") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("status") or "").lower() not in ("invalid", "failed"):
            continue
        error = step.get("error")
        text = _errors_text(error) if error else ""
        messages.append(f"{step.get('name') or 'validation step'}: {text}".rstrip(": "))
    return "; ".join(messages) or "ETA marked the document invalid without naming the step."


ClientFactory = Callable[[EtaSettings], EtaClient]


def default_client_factory(settings: EtaSettings) -> EtaClient:
    """An ETA client from the settings, credentials read from the environment."""
    return EtaClient(
        EtaEnvironment(settings.identity_base_url, settings.api_base_url),
        client_id=os.environ.get(settings.client_id_env, ""),
        client_secret=os.environ.get(settings.client_secret_env, ""),
        on_behalf_of=settings.on_behalf_of,
    )


class EtaAdapter:
    """``ClearanceAdapter`` for Egypt, plus the optional ``poll``."""

    key = ETA_ADAPTER_KEY
    label = "Egyptian Tax Authority (ETA) e-invoicing"
    countries: tuple[str, ...] = ("EG",)

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._client_factory = client_factory or default_client_factory
        self._sleep = sleep
        self._now = now

    # ── Submit ───────────────────────────────────────────────────────────────

    async def _signed_text(self, text: str, settings: EtaSettings, *, sandbox: bool) -> str:
        if has_signatures(text):
            return text
        if settings.signer.get("kind") == SIGNER_PRESIGNED:
            raise EtaSigningError("The registration expects signed documents and this one carries no signature.")
        signer = resolve_signer(settings.signer, sandbox=sandbox)
        canonical = canonical_bytes(text)
        value = await signer.sign(canonical)
        # Catch a token that signed something else before ETA does.
        verify_cades(value, canonical)
        return insert_signatures(text, [{"signatureType": SIGNATURE_TYPE_ISSUER, "value": value}])

    async def submit(self, request: SubmissionRequest) -> SubmissionOutcome:
        problems = settings_problems(request.profile)
        if problems:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_CONFIGURED,
                rejection_message="The ETA registration is not ready: " + "; ".join(problems) + ".",
                raw_response={"adapter": self.key, "problems": problems},
            )
        settings = EtaSettings.from_profile(request.profile)
        text = request.payload.decode("utf-8")
        try:
            signed = await self._signed_text(text, settings, sandbox=bool(request.profile.get("sandbox", True)))
        except EtaSigningError as exc:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_SIGNING,
                rejection_message=str(exc),
                raw_response={"adapter": self.key, "stage": "signing"},
            )

        client = self._client_factory(settings)
        try:
            answer = await client.submit([signed])
        except EtaUrlRefused as exc:
            # Refused before anything left, so the document was not sent.
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_CONFIGURED,
                rejection_message=str(exc),
                raw_response={"adapter": self.key, "stage": "url_safety"},
            )
        except EtaDuplicateSubmission:
            # ETA holds an identical submission from the last 10 minutes. Raised
            # so the document stays submitted with an unknown outcome.
            raise
        except EtaApiError as exc:
            if 400 <= exc.status < 500 and exc.status != 401:
                return SubmissionOutcome(
                    accepted=False,
                    rejection_code=exc.code or f"HTTP{exc.status}",
                    rejection_message=str(exc),
                    raw_response={"adapter": self.key, "status": exc.status, "details": exc.details},
                )
            raise

        internal_id = _internal_id(text)
        submission_uuid = str(answer.get("submissionUUID") or answer.get("submissionId") or "")
        for rejected in answer.get("rejectedDocuments") or []:
            if isinstance(rejected, dict) and str(rejected.get("internalId") or "") == internal_id:
                error = rejected.get("error") if isinstance(rejected.get("error"), dict) else {}
                return SubmissionOutcome(
                    accepted=False,
                    rejection_code=str(error.get("code") or "Rejected"),
                    rejection_message=_errors_text(error) or "ETA did not accept the document.",
                    raw_response={"adapter": self.key, "submissionUUID": submission_uuid, "rejected": rejected},
                )
        accepted = next(
            (
                row
                for row in answer.get("acceptedDocuments") or []
                if isinstance(row, dict) and str(row.get("internalId") or "") == internal_id
            ),
            None,
        )
        if accepted is None:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_IN_ANSWER,
                rejection_message=(
                    f"ETA's answer lists neither as accepted nor as rejected the document {internal_id!r}. "
                    "Check the submission on the ETA portal before sending again."
                ),
                raw_response={"adapter": self.key, "answer": answer},
            )

        document_uuid = str(accepted.get("uuid") or "")
        raw = {
            "adapter": self.key,
            "submissionUUID": submission_uuid,
            "uuid": document_uuid,
            "longId": str(accepted.get("longId") or ""),
            "internalId": internal_id,
            "environment": settings.environment,
        }
        verdict = await self._wait_for_verdict(client, submission_uuid, document_uuid, settings)
        if verdict == STATUS_VALID:
            return SubmissionOutcome(
                accepted=True,
                authority_identifier=document_uuid,
                message=f"ETA validated the document; UUID {document_uuid}.",
                raw_response={**raw, "status": verdict},
            )
        if verdict == STATUS_INVALID:
            return await self._invalid(client, document_uuid, raw)
        return SubmissionOutcome(
            accepted=True,
            pending=True,
            authority_identifier=document_uuid,
            message=(
                f"ETA took the document in as {document_uuid} and is validating it. Its verdict is read on refresh, "
                "or recorded by hand from the ETA portal."
            ),
            raw_response={**raw, "status": verdict or STATUS_SUBMITTED},
        )

    async def _wait_for_verdict(
        self,
        client: EtaClient,
        submission_uuid: str,
        document_uuid: str,
        settings: EtaSettings,
    ) -> str:
        """Ask Get Submission a few times; ``""`` when no verdict came in time."""
        if not submission_uuid:
            return ""
        for _attempt in range(settings.poll_attempts):
            await self._sleep(settings.poll_interval_seconds)
            try:
                submission = await client.get_submission(submission_uuid)
            except EtaApiError:
                logger.info("ETA submission %s not readable yet", submission_uuid, exc_info=True)
                continue
            for row in submission.get("documentSummary") or []:
                if isinstance(row, dict) and str(row.get("uuid") or "") == document_uuid:
                    status = str(row.get("status") or "").strip().lower()
                    if status in (STATUS_VALID, STATUS_INVALID):
                        return status
        return ""

    async def _invalid(self, client: EtaClient, document_uuid: str, raw: dict[str, Any]) -> SubmissionOutcome:
        try:
            details = await client.get_document_details(document_uuid)
            message = _validation_errors(details)
        except EtaApiError as exc:
            message = f"ETA marked the document invalid; its details could not be read ({exc})."
        return SubmissionOutcome(
            accepted=False,
            authority_identifier=document_uuid,
            rejection_code="Invalid",
            rejection_message=message,
            raw_response={**raw, "status": STATUS_INVALID},
        )

    # ── Poll ─────────────────────────────────────────────────────────────────

    async def poll(self, request: PollRequest) -> SubmissionOutcome:
        settings = EtaSettings.from_profile(request.profile)
        client = self._client_factory(settings)
        document_uuid = request.authority_identifier
        details = await client.get_document_details(document_uuid)
        status = str(details.get("status") or "").strip().lower()
        raw = {
            "adapter": self.key,
            "uuid": document_uuid,
            "status": status,
            "longId": str(details.get("longId") or ""),
            "submissionUUID": str(details.get("submissionUUID") or ""),
        }
        if status == STATUS_VALID:
            return SubmissionOutcome(
                accepted=True,
                authority_identifier=document_uuid,
                message=f"ETA validated the document; UUID {document_uuid}.",
                raw_response=raw,
            )
        if status == STATUS_INVALID:
            return SubmissionOutcome(
                accepted=False,
                authority_identifier=document_uuid,
                rejection_code="Invalid",
                rejection_message=_validation_errors(details),
                raw_response=raw,
            )
        if status in (STATUS_REJECTED, STATUS_CANCELLED):
            return SubmissionOutcome(
                accepted=False,
                authority_identifier=document_uuid,
                rejection_code=status.capitalize(),
                rejection_message=f"ETA shows the document as {status}.",
                raw_response=raw,
            )
        return SubmissionOutcome(
            accepted=True,
            pending=True,
            authority_identifier=document_uuid,
            message=f"ETA is still validating {document_uuid}.",
            raw_response=raw,
        )

    # ── Cancel ───────────────────────────────────────────────────────────────

    async def _cancel_deadline(self, client: EtaClient, document_uuid: str) -> tuple[datetime | None, str]:
        """When ETA stops accepting a cancellation, read from ETA. ``None`` if not knowable."""
        try:
            details = await client.get_document_details(document_uuid)
            document = details.get("document") if isinstance(details.get("document"), dict) else {}
            type_name = str(details.get("typeName") or document.get("documentType") or "").strip().lower()
            received_raw = str(details.get("dateTimeReceived") or "")
            received = datetime.fromisoformat(received_raw.replace("Z", "+00:00")) if received_raw else None
            if received is not None and received.tzinfo is None:
                received = received.replace(tzinfo=UTC)
            types = await client.get_document_types()
            type_id = next((t.get("id") for t in types if str(t.get("name") or "").lower() == type_name), None)
            if type_id is None or received is None:
                return None, ""
            spec = await client.get_document_type(type_id)
        except (EtaApiError, ValueError, TypeError):
            logger.info("ETA cancellation window for %s not readable", document_uuid, exc_info=True)
            return None, ""
        now = self._now()
        for parameter in spec.get("workflowParameters") or []:
            if not isinstance(parameter, dict):
                continue
            name = str(parameter.get("parameter") or "")
            if "cancel" not in name.lower():
                continue
            active_to = str(parameter.get("activeTo") or "")
            if active_to:
                try:
                    if datetime.fromisoformat(active_to.replace("Z", "+00:00")) < now:
                        continue
                except ValueError:
                    pass
            try:
                value = float(parameter.get("value"))
            except (TypeError, ValueError):
                continue
            span = timedelta(days=value) if "day" in name.lower() else timedelta(hours=value)
            return received + span, name
        return None, ""

    async def cancel(self, request: CancellationRequest) -> SubmissionOutcome:
        problems = settings_problems(request.profile)
        if problems:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_CONFIGURED,
                rejection_message="The ETA registration is not ready: " + "; ".join(problems) + ".",
                raw_response={"adapter": self.key, "problems": problems},
            )
        settings = EtaSettings.from_profile(request.profile)
        client = self._client_factory(settings)
        document_uuid = request.authority_identifier
        deadline, parameter = await self._cancel_deadline(client, document_uuid)
        if deadline is not None and self._now() > deadline:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_WINDOW_CLOSED,
                rejection_message=(
                    f"ETA's cancellation window ({parameter}) closed at {deadline.isoformat()}. "
                    "Issue a credit note referencing the invoice instead."
                ),
                raw_response={"adapter": self.key, "uuid": document_uuid, "deadline": deadline.isoformat()},
            )
        try:
            await client.cancel_document(document_uuid, request.reason)
        except EtaUrlRefused as exc:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_CONFIGURED,
                rejection_message=str(exc),
                raw_response={"adapter": self.key, "uuid": document_uuid, "stage": "url_safety"},
            )
        except EtaApiError as exc:
            if 400 <= exc.status < 500 and exc.status != 401:
                return SubmissionOutcome(
                    accepted=False,
                    rejection_code=exc.code or f"HTTP{exc.status}",
                    rejection_message=str(exc),
                    raw_response={"adapter": self.key, "uuid": document_uuid, "status": exc.status},
                )
            raise
        return SubmissionOutcome(
            accepted=True,
            authority_identifier=document_uuid,
            message=(
                f"ETA accepted the cancellation of {document_uuid}. The receiver can still decline it on the "
                "portal within ETA's window."
            ),
            raw_response={
                "adapter": self.key,
                "uuid": document_uuid,
                "deadline": deadline.isoformat() if deadline else "",
            },
        )


__all__ = [
    "CODE_NOT_CONFIGURED",
    "CODE_NOT_IN_ANSWER",
    "CODE_SIGNING",
    "CODE_WINDOW_CLOSED",
    "ENVIRONMENTS",
    "ETA_ADAPTER_KEY",
    "EtaAdapter",
    "EtaSettings",
    "default_client_factory",
    "has_signatures",
    "insert_signatures",
    "settings_problems",
]
