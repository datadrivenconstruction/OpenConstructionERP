# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The clearance adapter for KSeF (key ``ksef_pl``).

Submit authenticates, opens an interactive session, sends the encrypted FA(3)
document and reads its status for a short while. KSeF usually assigns the KSeF
number at once; when it has not yet, the outcome is ``pending`` and the document
keeps a handle (``ksef-ref:<session>/<invoice>``) that :meth:`KsefAdapter.poll`
reads later. On success the UPO (the official receipt) is fetched and kept in
the event trail with the KSeF answer.

KSeF has no cancellation: an invoice with a KSeF number is corrected with a
corrective invoice. :meth:`KsefAdapter.cancel` says so instead of trying.

Credentials never sit in the registration. ``settings["ksef"]`` names the
environment variable that holds a KSeF token, or the signer that performs XAdES
authentication.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import httpx

from app.core.url_safety import UnsafeUrlError, resolve_and_validate_ai_provider_url
from app.modules.einvoice_clearance.adapters import (
    CancellationRequest,
    PollRequest,
    SubmissionOutcome,
    SubmissionRequest,
)
from app.modules.einvoice_ksef import ksef_number
from app.modules.einvoice_ksef.client import (
    AccessTokens,
    InvoiceStatus,
    KsefApiError,
    KsefClient,
    XadesSigner,
    environment,
)
from app.modules.einvoice_ksef.facts import ENVIRONMENTS, OFFLINE_MODES, OFFLINE_TOTAL_FAILURE, TOKEN_AUTH_LAST_DAY

logger = logging.getLogger(__name__)

KSEF_ADAPTER_KEY = "ksef_pl"

AUTH_TOKEN = "token"
AUTH_XADES = "xades"

CODE_NOT_CONFIGURED = "KSEF-NOT-CONFIGURED"
CODE_NO_CANCELLATION = "KSEF-NO-CANCELLATION"
CODE_BAD_HANDLE = "KSEF-BAD-HANDLE"


@dataclass(frozen=True)
class KsefSettings:
    """The ``settings["ksef"]`` block of a registration."""

    environment: str = ""
    auth: str = AUTH_TOKEN
    context_type: str = "Nip"
    context_value: str = ""
    token_env: str = ""
    xades_signer: dict[str, Any] = field(default_factory=dict)
    poll_attempts: int = 5
    poll_interval_seconds: float = 1.0

    @classmethod
    def from_profile(cls, profile: dict[str, Any]) -> KsefSettings:
        settings = profile.get("settings") if isinstance(profile.get("settings"), dict) else {}
        raw = settings.get("ksef") if isinstance(settings.get("ksef"), dict) else {}

        def text(name: str, default: str = "") -> str:
            return str(raw.get(name) or default).strip()

        try:
            attempts = int(raw.get("poll_attempts", 5))
        except (TypeError, ValueError):
            attempts = 5
        try:
            interval = float(raw.get("poll_interval_seconds", 1))
        except (TypeError, ValueError):
            interval = 1.0
        return cls(
            environment=text("environment").lower(),
            auth=text("auth", AUTH_TOKEN).lower(),
            context_type=text("context_type", "Nip"),
            context_value=text("context_value") or str(profile.get("tax_registration_id") or "").strip(),
            token_env=text("token_env"),
            xades_signer=dict(raw.get("xades_signer") or {}) if isinstance(raw.get("xades_signer"), dict) else {},
            poll_attempts=max(1, min(attempts, 20)),
            poll_interval_seconds=max(0.0, min(interval, 30.0)),
        )


def settings_problems(profile: dict[str, Any], *, today: date | None = None) -> list[str]:
    """What is missing or contradictory in a registration's KSeF settings.

    The ``pl.ksef_registration_ready`` rule and the adapter both call this, so
    the gate cannot let through what the adapter would refuse.
    """
    settings = KsefSettings.from_profile(profile)
    sandbox = bool(profile.get("sandbox", True))
    day = today or datetime.now(UTC).date()
    problems: list[str] = []
    env = ENVIRONMENTS.get(settings.environment)
    if env is None:
        problems.append(f"settings.ksef.environment must be one of {', '.join(ENVIRONMENTS)}")
    elif env.is_production and sandbox:
        problems.append("the environment is prod but the registration is in sandbox mode")
    elif not env.is_production and not sandbox:
        problems.append(f"the registration is live but the environment is {env.key}")
    if not settings.context_value:
        problems.append("the context identifier (the NIP) is missing")
    if settings.auth == AUTH_TOKEN:
        if not settings.token_env:
            problems.append("settings.ksef.token_env must name the environment variable that holds the KSeF token")
        if day > date.fromisoformat(TOKEN_AUTH_LAST_DAY.effective_date):
            problems.append(
                f"KSeF tokens stopped authenticating after {TOKEN_AUTH_LAST_DAY.effective_date}; "
                "switch the registration to certificate (xades) authentication"
            )
    elif settings.auth == AUTH_XADES:
        if not str(settings.xades_signer.get("kind") or "").strip():
            problems.append("settings.ksef.xades_signer.kind is not set")
    else:
        problems.append("settings.ksef.auth must be token or xades")
    return problems


# ── XAdES signers ───────────────────────────────────────────────────────────

XadesSignerFactory = Callable[[dict[str, Any]], XadesSigner]
_xades_factories: dict[str, XadesSignerFactory] = {}


def register_xades_signer(kind: str, factory: XadesSignerFactory) -> None:
    """Register how to build a XAdES signer of one kind. Overwrites by kind."""
    _xades_factories[kind] = factory


def _external_http_signer(config: dict[str, Any]) -> XadesSigner:
    """A signing service: the unsigned request goes in, the signed XML comes back.

    The service holds the certificate (a qualified seal, or a KSeF certificate
    on an HSM). ``config``: ``url`` (https), and optionally ``token_env`` naming
    the environment variable with a bearer token for the service. The URL comes
    from a registration, so it passes the self-hosted endpoint policy of
    :mod:`app.core.url_safety` before every call.
    """
    url = str(config.get("url") or "").strip()
    if not url.startswith("https://"):
        raise KsefApiError("the XAdES signing service needs an https URL")
    token_env = str(config.get("token_env") or "").strip()

    async def sign(unsigned: str) -> str:
        try:
            await resolve_and_validate_ai_provider_url(url)
        except UnsafeUrlError as exc:
            raise KsefApiError(f"the XAdES signing service URL is refused: {exc}") from exc
        headers = {"Content-Type": "application/xml"}
        if token_env and os.environ.get(token_env):
            headers["Authorization"] = f"Bearer {os.environ[token_env]}"
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.post(url, content=unsigned.encode("utf-8"), headers=headers)
        if response.status_code >= 400:
            raise KsefApiError(f"the XAdES signing service answered {response.status_code}")
        return response.text

    return sign


register_xades_signer("external_http", _external_http_signer)


ClientFactory = Callable[[KsefSettings], KsefClient]


def default_client_factory(settings: KsefSettings) -> KsefClient:
    return KsefClient(
        environment(settings.environment),
        poll_attempts=settings.poll_attempts,
        poll_interval=settings.poll_interval_seconds,
    )


def _ksef_fields(document: dict[str, Any]) -> dict[str, Any]:
    fields = document.get("country_fields") if isinstance(document.get("country_fields"), dict) else {}
    ksef = fields.get("ksef") if isinstance(fields.get("ksef"), dict) else {}
    return ksef


class KsefAdapter:
    """``ClearanceAdapter`` for Poland, plus the optional ``poll``."""

    key = KSEF_ADAPTER_KEY
    label = "KSeF national e-invoicing system (Poland)"
    countries: tuple[str, ...] = ("PL",)

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        env: Callable[[str], str | None] = os.environ.get,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ) -> None:
        self._client_factory = client_factory or default_client_factory
        self._env = env
        self._today = today

    async def _authenticate(self, client: KsefClient, settings: KsefSettings) -> AccessTokens:
        if settings.auth == AUTH_XADES:
            kind = str(settings.xades_signer.get("kind") or "")
            factory = _xades_factories.get(kind)
            if factory is None:
                raise KsefApiError(f"no XAdES signer of kind {kind!r} is installed")
            return await client.authenticate_with_xades(
                signer=factory(settings.xades_signer),
                context_type=settings.context_type,
                context_value=settings.context_value,
            )
        token = self._env(settings.token_env) or ""
        if not token:
            raise KsefApiError(f"the environment variable {settings.token_env} holds no KSeF token")
        return await client.authenticate_with_token(
            token=token, context_type=settings.context_type, context_value=settings.context_value
        )

    def _not_configured(self, problems: list[str]) -> SubmissionOutcome:
        return SubmissionOutcome(
            accepted=False,
            rejection_code=CODE_NOT_CONFIGURED,
            rejection_message="The KSeF registration is not ready: " + "; ".join(problems) + ".",
            raw_response={"adapter": self.key, "problems": problems},
        )

    async def _outcome(
        self,
        client: KsefClient,
        tokens: AccessTokens,
        session_reference: str,
        invoice_reference: str,
        status: InvoiceStatus,
        raw: dict[str, Any],
    ) -> SubmissionOutcome:
        raw = {
            **raw,
            "status": {"code": status.code, "description": status.description, "details": list(status.details)},
        }
        if status.succeeded and status.ksef_number:
            upo = ""
            try:
                upo = await client.invoice_upo(tokens, session_reference, invoice_reference)
            except KsefApiError:
                # The number is what makes the invoice valid; a UPO that is not
                # ready yet is fetched again from the session later.
                logger.info("KSeF UPO for %s not available yet", status.ksef_number, exc_info=True)
            return SubmissionOutcome(
                accepted=True,
                authority_identifier=status.ksef_number,
                message=f"KSeF accepted the invoice; KSeF number {status.ksef_number}.",
                raw_response={
                    **raw,
                    "ksefNumber": status.ksef_number,
                    "invoicingMode": status.invoicing_mode,
                    "upo": upo,
                },
            )
        if status.in_progress:
            return SubmissionOutcome(
                accepted=True,
                pending=True,
                authority_identifier=ksef_number.pending_handle(session_reference, invoice_reference),
                message=(
                    "KSeF took the invoice in and is processing it. The KSeF number is read on refresh, or recorded by "
                    "hand from the KSeF application."
                ),
                raw_response=raw,
            )
        return SubmissionOutcome(
            accepted=False,
            rejection_code=f"KSEF-{status.code}",
            rejection_message="; ".join([status.description, *status.details]).strip("; ")
            or "KSeF did not accept the invoice.",
            raw_response=raw,
        )

    async def submit(self, request: SubmissionRequest) -> SubmissionOutcome:
        problems = settings_problems(request.profile, today=self._today())
        if problems:
            return self._not_configured(problems)
        settings = KsefSettings.from_profile(request.profile)
        fields = _ksef_fields(request.document)
        offline_key = str(fields.get("offline_mode") or "").strip().lower()
        if offline_key == OFFLINE_TOTAL_FAILURE:
            return SubmissionOutcome(
                accepted=False,
                rejection_code="KSEF-TOTAL-FAILURE",
                rejection_message=(
                    "An invoice issued during a total KSeF failure is not sent to KSeF. Record it as delivered "
                    "outside KSeF."
                ),
                raw_response={"adapter": self.key},
            )
        offline = offline_key in OFFLINE_MODES
        client = self._client_factory(settings)
        raw: dict[str, Any] = {"adapter": self.key, "environment": settings.environment, "offlineMode": offline}
        try:
            tokens = await self._authenticate(client, settings)
            session = await client.open_session(tokens)
            raw["sessionReference"] = session.reference
            try:
                invoice_reference = await client.send_invoice(
                    tokens,
                    session,
                    request.payload,
                    offline_mode=offline,
                    hash_of_corrected_invoice=str(fields.get("corrected_invoice_hash") or "").strip(),
                )
                raw["invoiceReference"] = invoice_reference
                status = await client.wait_for_status(tokens, session.reference, invoice_reference)
            finally:
                try:
                    await client.close_session(tokens, session.reference)
                except KsefApiError:
                    logger.info("KSeF session %s did not close cleanly", session.reference, exc_info=True)
        except KsefApiError as exc:
            if 400 <= exc.status < 500 and exc.status != 401:
                return SubmissionOutcome(
                    accepted=False,
                    rejection_code=f"KSEF-{exc.code or exc.status}",
                    rejection_message=str(exc),
                    raw_response={**raw, "httpStatus": exc.status, "details": exc.details},
                )
            raise
        return await self._outcome(client, tokens, session.reference, invoice_reference, status, raw)

    async def poll(self, request: PollRequest) -> SubmissionOutcome:
        parsed = ksef_number.parse_pending_handle(request.authority_identifier)
        if parsed is None:
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_BAD_HANDLE,
                rejection_message=(
                    f"{request.authority_identifier!r} is not a KSeF processing reference, so there is nothing to ask "
                    "KSeF about. Record the outcome by hand."
                ),
                raw_response={"adapter": self.key},
            )
        problems = settings_problems(request.profile, today=self._today())
        if problems:
            return self._not_configured(problems)
        session_reference, invoice_reference = parsed
        settings = KsefSettings.from_profile(request.profile)
        client = self._client_factory(settings)
        tokens = await self._authenticate(client, settings)
        status = await client.invoice_status(tokens, session_reference, invoice_reference)
        raw = {
            "adapter": self.key,
            "sessionReference": session_reference,
            "invoiceReference": invoice_reference,
        }
        return await self._outcome(client, tokens, session_reference, invoice_reference, status, raw)

    async def cancel(self, request: CancellationRequest) -> SubmissionOutcome:
        correction = request.regime_spec.get("correction_mechanism") or "a corrective invoice"
        return SubmissionOutcome(
            accepted=False,
            rejection_code=CODE_NO_CANCELLATION,
            rejection_message=f"KSeF has no cancellation. Correct the invoice with {correction}.",
            raw_response={"adapter": self.key, "cancellable": False},
        )


__all__ = [
    "AUTH_TOKEN",
    "AUTH_XADES",
    "CODE_BAD_HANDLE",
    "CODE_NOT_CONFIGURED",
    "CODE_NO_CANCELLATION",
    "KSEF_ADAPTER_KEY",
    "KsefAdapter",
    "KsefSettings",
    "default_client_factory",
    "register_xades_signer",
    "settings_problems",
]
