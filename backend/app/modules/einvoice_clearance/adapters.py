# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The government-platform boundary.

Core does not talk to a tax authority. Every platform in the registry has its
own transport, its own certificate handling and its own SOAP or REST dialect,
and shipping eight of those would put eight client stacks and their transitive
dependencies inside a core that has to run on a 3 GB server. So the boundary is an
interface: this module owns the state, the validation and the trail, and an
adapter owns the wire.

An adapter is asked one of two questions and answers with a
:class:`SubmissionOutcome`. It never touches the database, never decides what
status a document lands in - the regime decides that - and never sees an ORM
object. It is handed plain data and returns plain data, which is what makes the
whole state machine testable without a network.

Shipped adapters
================
One: :class:`ReferenceAdapter`, offline and deterministic. It exists so the
round trip is exercisable end to end - submit, clear, cancel, reject - and so a
deployment can see the module work before anybody has bought a provider
account. It refuses to serve a live profile, which is the one property that
matters about it: an offline adapter that could mint an identifier for a
production invoice would be a way to produce fiscal records that no authority
has ever seen.

Real adapters register themselves the same way, from their own package's
``on_startup``. Nothing in this file needs to change to add one.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.modules.einvoice_clearance.regimes import (
    REGIME_CLEARANCE,
    REGIME_NETWORK,
    REGIME_REPORTING,
)

logger = logging.getLogger(__name__)

# The key the shipped offline adapter registers under.
REFERENCE_ADAPTER_KEY = "reference"

# Codes the reference adapter returns. They are its own, prefixed so nobody can
# mistake one for a code a real authority issued.
CODE_NOT_LIVE = "REF-NOT-LIVE"
CODE_MISSING_FIELD = "REF-MISSING-FIELD"
CODE_NOT_CANCELLABLE = "REF-NOT-CANCELLABLE"


@dataclass(frozen=True)
class SubmissionRequest:
    """Everything an adapter needs to put one document on the wire."""

    country: str
    regime: str
    document_format: str
    # The exact bytes to submit. Hashed by the caller; the adapter must send
    # these and not re-serialise them, or the hash on the record stops
    # describing what the authority received.
    payload: bytes
    payload_hash: str
    payload_media_type: str
    # Flattened profile: tax_registration_id, network_participant_id,
    # certificate_reference, sandbox, settings. Never a credential.
    profile: dict[str, Any] = field(default_factory=dict)
    # Invoice number, date, currency, total, and the national fields.
    document: dict[str, Any] = field(default_factory=dict)
    # The country registry entry, flattened. Carries the mandatory field list
    # and the cancellation window so an adapter does not have to import the
    # registry to answer.
    regime_spec: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CancellationRequest:
    """A request to withdraw a document the platform has already accepted."""

    country: str
    regime: str
    authority_identifier: str
    reason: str
    profile: dict[str, Any] = field(default_factory=dict)
    document: dict[str, Any] = field(default_factory=dict)
    regime_spec: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubmissionOutcome:
    """What the platform said.

    ``accepted`` is the adapter's whole verdict. It deliberately does not carry
    a status: the service asks the regime what an acceptance means, so a Peppol
    delivery cannot end up recorded as a tax clearance because an adapter author
    picked the wrong constant.
    """

    accepted: bool
    authority_identifier: str = ""
    rejection_code: str = ""
    rejection_message: str = ""
    message: str = ""
    raw_response: dict[str, Any] = field(default_factory=dict)
    # The platform took the document in but has not decided about it yet. Some
    # platforms answer in two steps: a receipt with an identifier first, the
    # verdict later. ``accepted`` is then true about the receipt only, and the
    # document stays ``submitted`` with the identifier stored, until a poll
    # reads the verdict. Defaults to false, so every adapter written before
    # this field keeps meaning exactly what it meant.
    pending: bool = False
    # The act this answer is about, for a country that does more than one. A
    # hybrid country (see ``CountryRegime.additional_regimes``) puts different
    # documents through different acts, and only the adapter that read the
    # document's own subtype knows which one it went through. ``None`` means the
    # regime's deciding act, which is every adapter written before this field.
    # A value the country's regime does not declare is ignored, so an adapter
    # cannot record a delivery receipt as a tax clearance by naming it.
    act: str | None = None


@dataclass(frozen=True)
class PollRequest:
    """A request to read the platform's verdict on a document it took in."""

    country: str
    regime: str
    authority_identifier: str
    profile: dict[str, Any] = field(default_factory=dict)
    document: dict[str, Any] = field(default_factory=dict)
    regime_spec: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ClearanceAdapter(Protocol):
    """What a government-platform client has to provide.

    Both methods are async because every real implementation does network I/O.
    Neither may raise for a business rejection - a rejection is an outcome with
    ``accepted=False`` and the authority's code, because that is a fact about
    the invoice that has to be stored, not an error in this process. Raising is
    reserved for a transport failure the operator should retry.
    """

    key: str
    label: str
    countries: tuple[str, ...]

    async def submit(self, request: SubmissionRequest) -> SubmissionOutcome:
        """Put the document to the platform and report what it said."""
        ...

    async def cancel(self, request: CancellationRequest) -> SubmissionOutcome:
        """Withdraw a document the platform has already accepted."""
        ...


# An adapter whose platform answers in two steps also provides
#
#     async def poll(self, request: PollRequest) -> SubmissionOutcome
#
# returning ``accepted=True`` for a cleared document, ``accepted=False`` with
# the platform's code for a refused one, and ``pending=True`` while the platform
# is still deciding. It is not part of the Protocol on purpose: the adapters
# that answer in one step have nothing to poll, and a required method they
# would all implement as "not supported" is a method nobody can rely on.


def supports_polling(adapter: object) -> bool:
    """Whether an adapter can read a verdict after the submission returned."""
    return callable(getattr(adapter, "poll", None))


class AdapterRegistry:
    """The adapters this deployment has installed.

    Lookup is by explicit key only. There is no "closest match" and no default:
    a profile that names no adapter, or names one that is not installed, gets a
    refusal that says so. Falling back to something plausible is how a live
    Mexican invoice would end up stamped by a test double.
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ClearanceAdapter] = {}

    def register(self, adapter: ClearanceAdapter) -> None:
        """Register an adapter under its own key. Overwrites by key."""
        self._adapters[adapter.key] = adapter
        logger.debug("Registered e-invoice clearance adapter %s", adapter.key)

    def get(self, key: str) -> ClearanceAdapter | None:
        """The adapter registered under ``key``, or ``None``."""
        return self._adapters.get((key or "").strip())

    def list_all(self) -> dict[str, ClearanceAdapter]:
        """Every installed adapter, keyed by its key."""
        return dict(self._adapters)

    def for_country(self, country: str) -> tuple[ClearanceAdapter, ...]:
        """Installed adapters that claim to serve ``country``."""
        code = (country or "").strip().upper()
        return tuple(a for a in self._adapters.values() if code in a.countries or "*" in a.countries)


adapter_registry = AdapterRegistry()


def _deterministic_identifier(country: str, regime: str, payload_hash: str) -> str:
    """An identifier shaped like the one that country's platform returns.

    Shaped, not faked: the shapes are the interesting part of each platform and
    getting them wrong in a demo teaches the wrong thing. A Mexican UUID is a
    UUID, a Brazilian chave de acesso is 44 digits, an Indian IRN is a 64
    character hash - which is what ``payload_hash`` already is, because that is
    genuinely how an IRN is built.

    Derived from the payload hash, so the same payload always produces the same
    identifier and a test can assert on it.
    """
    digest = payload_hash or hashlib.sha256(country.encode("utf-8")).hexdigest()
    code = (country or "").upper()
    if code == "MX":
        return str(uuid.UUID(hex=digest[:32])).upper()
    if code == "BR":
        return f"{int(digest[:32], 16) % (10**44):044d}"
    if code == "IN":
        return digest.upper()
    if regime == REGIME_REPORTING:
        return f"ACK-{code}-{digest[:16].upper()}"
    if regime == REGIME_NETWORK:
        return f"TX-{code}-{str(uuid.UUID(hex=digest[:32]))}"
    return f"{code}-{digest[:24].upper()}"


class ReferenceAdapter:
    """An offline, deterministic stand-in for a government platform.

    What it is for: making the state machine real. Every branch this module
    owns - queued to submitted, submitted to cleared, submitted to rejected,
    cleared to cancelled, and the cancellation a platform does not allow - is
    reachable through this adapter with no network and no clock dependence.

    What it will not do: serve a live profile. Asked to submit for a profile
    with ``sandbox`` false it returns a rejection rather than an identifier, and
    the document lands in ``rejected`` with a code an operator can read. That is
    the honest answer to "you have configured a production registration against
    a reference implementation", and it is a rejection rather than an exception
    because it is a fact about the submission, not a crash.
    """

    key = REFERENCE_ADAPTER_KEY
    label = "Offline reference adapter"
    # ``*`` - it answers for any country in the registry, in sandbox only.
    countries: tuple[str, ...] = ("*",)

    async def submit(self, request: SubmissionRequest) -> SubmissionOutcome:
        """Accept a sandbox submission; refuse a live one."""
        if not bool(request.profile.get("sandbox", True)):
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_LIVE,
                rejection_message=(
                    "The offline reference adapter cannot submit for a live profile. Install the "
                    f"adapter for {request.country} or set this profile back to sandbox."
                ),
                raw_response={"adapter": self.key, "sandbox": False},
            )

        missing = self._missing_fields(request)
        if missing:
            # A real platform validates server-side and rejects with its own
            # code even when the sender thought the document was complete. This
            # models that, so the rejection path is exercised by the same rules
            # the module enforces rather than by a special test hook.
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_MISSING_FIELD,
                rejection_message=f"Missing mandatory field(s) for {request.country}: {', '.join(missing)}",
                raw_response={"adapter": self.key, "missing": missing},
            )

        identifier = _deterministic_identifier(request.country, request.regime, request.payload_hash)
        return SubmissionOutcome(
            accepted=True,
            authority_identifier=identifier,
            message=self._acceptance_message(request),
            raw_response={
                "adapter": self.key,
                "sandbox": True,
                "country": request.country,
                "regime": request.regime,
                "format": request.document_format,
                "identifier": identifier,
                "payload_hash": request.payload_hash,
                "payload_bytes": len(request.payload),
            },
        )

    async def cancel(self, request: CancellationRequest) -> SubmissionOutcome:
        """Accept a cancellation the platform allows; refuse one it does not."""
        if not bool(request.profile.get("sandbox", True)):
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_LIVE,
                rejection_message=("The offline reference adapter cannot cancel for a live profile."),
                raw_response={"adapter": self.key, "sandbox": False},
            )
        cancellable = request.regime_spec.get("is_cancellable")
        if cancellable is None:
            cancellable = request.regime_spec.get("cancellation_window_days") is not None
        if not cancellable:
            correction = request.regime_spec.get("correction_mechanism") or "a correcting document"
            return SubmissionOutcome(
                accepted=False,
                rejection_code=CODE_NOT_CANCELLABLE,
                rejection_message=(
                    f"{request.country} has no cancellation flow. Correct the document with {correction}."
                ),
                raw_response={"adapter": self.key, "cancellable": False},
            )
        return SubmissionOutcome(
            accepted=True,
            authority_identifier=request.authority_identifier,
            message=f"Cancellation accepted for {request.authority_identifier}.",
            raw_response={
                "adapter": self.key,
                "cancelled": request.authority_identifier,
                "reason": request.reason,
            },
        )

    @staticmethod
    def _missing_fields(request: SubmissionRequest) -> list[str]:
        """National fields the country requires that the payload does not carry."""
        required = request.regime_spec.get("document_fields") or ()
        carried = request.document.get("country_fields") or {}
        if not isinstance(carried, dict):
            return list(required)
        return [name for name in required if not str(carried.get(name) or "").strip()]

    @staticmethod
    def _acceptance_message(request: SubmissionRequest) -> str:
        if request.regime == REGIME_CLEARANCE:
            label = request.regime_spec.get("identifier_label") or "identifier"
            return f"Cleared in sandbox; {label} issued."
        if request.regime == REGIME_REPORTING:
            return "Report acknowledged in sandbox."
        return "Routed in sandbox; the network accepted the document."


def register_builtin_adapters() -> None:
    """Install the adapters that ship with the platform.

    Idempotent - the registry overwrites by key, so a hot reload re-registers
    cleanly. Called from the module ``on_startup`` hook.
    """
    adapter_registry.register(ReferenceAdapter())


__all__ = [
    "CODE_MISSING_FIELD",
    "CODE_NOT_CANCELLABLE",
    "CODE_NOT_LIVE",
    "REFERENCE_ADAPTER_KEY",
    "AdapterRegistry",
    "CancellationRequest",
    "ClearanceAdapter",
    "PollRequest",
    "ReferenceAdapter",
    "SubmissionOutcome",
    "SubmissionRequest",
    "adapter_registry",
    "register_builtin_adapters",
    "supports_polling",
]
