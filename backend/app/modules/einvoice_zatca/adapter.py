# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The clearance adapter for ZATCA FATOORA (key ``zatca_fatoora``).

Saudi Arabia runs two acts, and the document decides which: a standard tax
invoice (KSA-2 ``01xxxxx``) goes to ``/invoices/clearance/single`` and comes
back stamped by ZATCA; a simplified one (``02xxxxx``) was stamped by the seller
and is *reported* to ``/invoices/reporting/single``. The adapter reads the
subtype from the payload and says which act the answer is about in
``SubmissionOutcome.act``, so the clearance service records ``cleared`` or
``reported`` accordingly.

The adapter never writes the database. The credentials of the unit that built
the document come from an injectable loader (by default one that reads the unit
row), found through the document's UUID in the chain, so a document can only be
sent with the CSID of the unit that stamped it.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.modules.einvoice_clearance.adapters import (
    CancellationRequest,
    SubmissionOutcome,
    SubmissionRequest,
)
from app.modules.einvoice_clearance.regimes import REGIME_CLEARANCE, REGIME_REPORTING
from app.modules.einvoice_zatca import c14n, checks, data, hashing
from app.modules.einvoice_zatca.client import Credentials, FatooraClient, FatooraResponse
from app.modules.einvoice_zatca.codes import parse_subtype
from app.modules.einvoice_zatca.models import STATE_ACTIVE

logger = logging.getLogger(__name__)

ZATCA_ADAPTER_KEY = "zatca_fatoora"

CODE_UNREADABLE = "ZATCA-UNREADABLE"
CODE_NO_UNIT = "ZATCA-NO-UNIT"
CODE_NOT_ONBOARDED = "ZATCA-NOT-ONBOARDED"
CODE_ENVIRONMENT = "ZATCA-ENVIRONMENT"
CODE_NO_CANCELLATION = "ZATCA-NO-CANCELLATION"
CODE_NOT_ACCEPTED = "ZATCA-NOT-ACCEPTED"


@dataclass(frozen=True)
class UnitAccess:
    """What the adapter needs to know about the unit that built a document."""

    unit_key: str
    state: str
    environment: str
    credentials: Credentials | None


CredentialLoader = Callable[[str], Awaitable["UnitAccess | None"]]
ClientFactory = Callable[[str], FatooraClient]


async def database_loader(invoice_uuid: str) -> UnitAccess | None:
    """Read the unit from the database, through the chain entry of the document."""
    from app.database import async_session_factory
    from app.modules.einvoice_zatca import service

    async with async_session_factory() as session:
        unit = await service.unit_for_document_uuid(session, invoice_uuid)
        if unit is None:
            return None
        return UnitAccess(
            unit_key=unit.unit_key,
            state=unit.state,
            environment=unit.environment,
            credentials=service.unit_credentials(unit),
        )


def default_client_factory(environment: str) -> FatooraClient:
    return FatooraClient(environment)


def _rejected(code: str, message: str, **raw: Any) -> SubmissionOutcome:
    return SubmissionOutcome(
        accepted=False,
        rejection_code=code,
        rejection_message=message,
        raw_response={"adapter": ZATCA_ADAPTER_KEY, **raw},
    )


class ZatcaAdapter:
    """``ClearanceAdapter`` for Saudi Arabia. No ``poll``: ZATCA answers in one step."""

    key = ZATCA_ADAPTER_KEY
    label = "ZATCA FATOORA phase 2 (Saudi Arabia)"
    countries: tuple[str, ...] = ("SA",)

    def __init__(
        self,
        *,
        credential_loader: CredentialLoader | None = None,
        client_factory: ClientFactory | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._load = credential_loader or database_loader
        if client_factory is not None:
            self._client_factory = client_factory
        elif transport is not None:

            def with_transport(environment: str) -> FatooraClient:
                return FatooraClient(environment, transport=transport)

            self._client_factory = with_transport
        else:
            self._client_factory = default_client_factory

    async def submit(self, request: SubmissionRequest) -> SubmissionOutcome:
        text = request.payload.decode("utf-8", errors="replace")
        try:
            invoice_uuid, subtype_code = checks.read_identity(text)
            root = checks.parse(text)
        except c14n.XmlError as exc:
            return _rejected(CODE_UNREADABLE, f"The payload is not a readable UBL invoice: {exc}")
        subtype = parse_subtype(subtype_code)
        if subtype is None or not invoice_uuid:
            return _rejected(
                CODE_UNREADABLE,
                "The document carries no valid KSA-2 invoice subtype or no UUID, so it is not known whether to "
                "clear or to report it.",
            )
        act = REGIME_REPORTING if subtype.simplified else REGIME_CLEARANCE

        access = await self._load(invoice_uuid)
        if access is None:
            return _rejected(
                CODE_NO_UNIT,
                "No EGS unit of this system built this document, so there is no CSID to send it with. "
                "Documents are sent with the CSID of the unit that stamped them.",
                uuid=invoice_uuid,
            )
        env = data.ENVIRONMENTS.get(access.environment)
        sandbox = bool(request.profile.get("sandbox", True))
        if env is None or env.live == sandbox:
            return _rejected(
                CODE_ENVIRONMENT,
                f"The unit is onboarded on {access.environment or 'no environment'}, which does not fit a "
                f"{'sandbox' if sandbox else 'live'} registration.",
                unit=access.unit_key,
            )
        if access.credentials is None or (env.live and access.state != STATE_ACTIVE):
            return _rejected(
                CODE_NOT_ONBOARDED,
                f"Unit {access.unit_key} has no usable CSID ({access.state}). Finish onboarding before sending.",
                unit=access.unit_key,
            )

        client = self._client_factory(access.environment)
        invoice_hash = hashing.invoice_hash(root)
        send = client.report if act == REGIME_REPORTING else client.clear
        response = await send(access.credentials, text, invoice_hash, invoice_uuid)
        return self._outcome(response, act=act, invoice_uuid=invoice_uuid, unit=access.unit_key)

    def _outcome(self, response: FatooraResponse, *, act: str, invoice_uuid: str, unit: str) -> SubmissionOutcome:
        raw: dict[str, Any] = {
            "adapter": self.key,
            "act": act,
            "unit": unit,
            "httpStatus": response.http_status,
            "status": response.status,
            "warnings": [{"code": m.code, "message": m.message} for m in response.warnings],
            "errors": [{"code": m.code, "message": m.message} for m in response.errors],
        }
        if response.accepted:
            if act == REGIME_CLEARANCE and response.status and response.status.upper() != "CLEARED":
                return _rejected(
                    CODE_NOT_ACCEPTED,
                    f"ZATCA answered {response.http_status} without clearing the invoice (status {response.status}).",
                    **{k: v for k, v in raw.items() if k != "adapter"},
                )
            if act == REGIME_CLEARANCE:
                # The cleared XML carries ZATCA's stamp and QR; it is the document the buyer receives (D4).
                raw["cleared_invoice"] = response.cleared_invoice
            verb = "cleared" if act == REGIME_CLEARANCE else "reported"
            warned = f" with {len(response.warnings)} warning(s)" if response.warnings else ""
            return SubmissionOutcome(
                accepted=True,
                authority_identifier=invoice_uuid,
                act=act,
                message=f"ZATCA {verb} the invoice{warned}.",
                raw_response=raw,
            )
        first = response.errors[0] if response.errors else None
        return SubmissionOutcome(
            accepted=False,
            rejection_code=first.code if first and first.code else f"ZATCA-{response.http_status}",
            rejection_message="; ".join(m.message for m in response.errors if m.message)
            or "ZATCA refused the invoice.",
            act=act,
            raw_response=raw,
        )

    async def cancel(self, request: CancellationRequest) -> SubmissionOutcome:
        mechanism = request.regime_spec.get("correction_mechanism") or "a credit note (381)"
        return _rejected(
            CODE_NO_CANCELLATION,
            f"ZATCA has no cancellation. Reverse the invoice with {mechanism}.",
            cancellable=False,
        )


__all__ = [
    "CODE_ENVIRONMENT",
    "CODE_NOT_ACCEPTED",
    "CODE_NOT_ONBOARDED",
    "CODE_NO_CANCELLATION",
    "CODE_NO_UNIT",
    "CODE_UNREADABLE",
    "ZATCA_ADAPTER_KEY",
    "UnitAccess",
    "ZatcaAdapter",
    "database_loader",
    "default_client_factory",
]
