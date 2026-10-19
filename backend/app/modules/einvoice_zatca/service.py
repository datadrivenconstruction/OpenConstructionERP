# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EGS units: onboarding, the chain, and building a stamped document.

Two jobs that share one table.

**Building.** :func:`build_from_invoice` is the payload builder the clearance
service calls when a Saudi document is created from a finance invoice. It takes
the unit's row ``FOR UPDATE``, allocates the next counter (ICV) and the previous
hash (PIH), builds the UBL document, stamps it and writes the chain entry, all in
the caller's transaction. The stored payload is therefore the final signed XML
and the clearance service sends exactly those bytes later.

**Onboarding.** The unit walks a fixed path, and :data:`TRANSITIONS` is the only
description of it::

    new --csr--> csr_ready --otp--> compliance_issued --checks--> compliance_passed
    compliance_passed --production csid--> active --renew--> active
    any --revoke--> revoked

Every function here checks the state it needs before it talks to ZATCA and
changes the unit only after ZATCA answered, so a refused call leaves the unit
exactly as it was.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.modules.einvoice_zatca import builder, c14n, checks, csr, data, signing
from app.modules.einvoice_zatca.client import Credentials, FatooraClient, FatooraError
from app.modules.einvoice_zatca.codes import (
    FIRST_PREVIOUS_HASH,
    TAX_CURRENCY,
    TYPE_CREDIT_NOTE,
    TYPE_DEBIT_NOTE,
    TYPE_INVOICE,
    Subtype,
)
from app.modules.einvoice_zatca.models import (
    STATE_ACTIVE,
    STATE_COMPLIANCE_ISSUED,
    STATE_COMPLIANCE_PASSED,
    STATE_CSR_READY,
    STATE_NEW,
    STATE_REVOKED,
    ZatcaChainEntry,
    ZatcaEgsUnit,
)
from app.modules.einvoice_zatca.stamp import apply_stamp

logger = logging.getLogger(__name__)

# Riyadh has no daylight saving, so a fixed offset is exact and needs no tz database.
RIYADH = dt.timezone(dt.timedelta(hours=3))

# What each state may move to. Anything not listed is refused.
TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_NEW: frozenset({STATE_CSR_READY, STATE_REVOKED}),
    STATE_CSR_READY: frozenset({STATE_COMPLIANCE_ISSUED, STATE_REVOKED}),
    STATE_COMPLIANCE_ISSUED: frozenset({STATE_COMPLIANCE_PASSED, STATE_REVOKED}),
    STATE_COMPLIANCE_PASSED: frozenset({STATE_ACTIVE, STATE_REVOKED}),
    STATE_ACTIVE: frozenset({STATE_ACTIVE, STATE_REVOKED}),
    STATE_REVOKED: frozenset(),
}

# The documents a unit has to get through before ZATCA issues a production CSID
# (the SDK's compliance set), per kind of invoice the unit is configured for.
COMPLIANCE_DOCUMENTS: tuple[tuple[str, str], ...] = (
    ("invoice", TYPE_INVOICE),
    ("credit_note", TYPE_CREDIT_NOTE),
    ("debit_note", TYPE_DEBIT_NOTE),
)


class ZatcaServiceError(ValueError):
    """A refusal about a unit or a document. ``conflict`` marks a refusal about state."""

    def __init__(self, message: str, *, conflict: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.conflict = conflict


def can_transition(source: str, target: str) -> bool:
    return target in TRANSITIONS.get(source, frozenset())


def _move(unit: ZatcaEgsUnit, target: str) -> None:
    if not can_transition(unit.state, target):
        raise ZatcaServiceError(
            f"A unit that is {unit.state} cannot become {target}. The path is new, csr_ready, compliance_issued, "
            "compliance_passed, active.",
            conflict=True,
        )
    unit.state = target


def _now() -> dt.datetime:
    return dt.datetime.now(RIYADH)


def _zatca_settings(profile: Any) -> dict[str, Any]:
    settings = (profile.settings or {}) if isinstance(profile.settings, dict) else {}
    value = settings.get("zatca")
    return dict(value) if isinstance(value, dict) else {}


# ── Reading units ────────────────────────────────────────────────────────────


def unit_as_dict(unit: ZatcaEgsUnit) -> dict[str, Any]:
    """A unit for the API and the rules. Never carries a key or a secret."""
    return {
        "id": str(unit.id),
        "profile_id": str(unit.profile_id),
        "unit_key": unit.unit_key,
        "csr_fields": dict(unit.csr_fields or {}),
        "state": unit.state,
        "environment": unit.environment,
        "signer_kind": unit.signer_kind,
        "signer_config": {k: v for k, v in dict(unit.signer_config or {}).items() if k != "headers"},
        "has_private_key": bool(unit.private_key_encrypted),
        "csr_pem": unit.csr_pem,
        "compliance_request_id": unit.compliance_request_id,
        "production_request_id": unit.production_request_id,
        "certificate_not_after": unit.certificate_not_after.isoformat() if unit.certificate_not_after else None,
        "compliance_results": dict(unit.compliance_results or {}),
        "last_icv": unit.last_icv,
        "last_hash": unit.last_hash,
        "last_error": unit.last_error,
    }


async def get_unit(session: AsyncSession, unit_id: uuid.UUID, *, lock: bool = False) -> ZatcaEgsUnit | None:
    query = select(ZatcaEgsUnit).where(ZatcaEgsUnit.id == unit_id)
    if lock:
        query = query.with_for_update()
    return (await session.execute(query)).scalar_one_or_none()


async def list_units(session: AsyncSession, profile_id: uuid.UUID) -> list[ZatcaEgsUnit]:
    result = await session.execute(
        select(ZatcaEgsUnit).where(ZatcaEgsUnit.profile_id == profile_id).order_by(ZatcaEgsUnit.created_at)
    )
    return list(result.scalars())


async def page_units(
    session: AsyncSession, profile_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[list[ZatcaEgsUnit], int]:
    """One page of a registration's units and how many it holds in all."""
    total = (
        await session.execute(
            select(func.count()).select_from(ZatcaEgsUnit).where(ZatcaEgsUnit.profile_id == profile_id)
        )
    ).scalar_one()
    result = await session.execute(
        select(ZatcaEgsUnit)
        .where(ZatcaEgsUnit.profile_id == profile_id)
        .order_by(ZatcaEgsUnit.created_at)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars()), total


async def unit_for_document_uuid(session: AsyncSession, invoice_uuid: str) -> ZatcaEgsUnit | None:
    """The unit that built the document with this UUID, from the chain."""
    entry = (
        await session.execute(select(ZatcaChainEntry).where(ZatcaChainEntry.invoice_uuid == invoice_uuid))
    ).scalar_one_or_none()
    if entry is None:
        return None
    return await get_unit(session, entry.unit_id)


def _environment_problem(environment: str, *, sandbox: bool) -> str:
    env = data.ENVIRONMENTS.get(environment)
    if env is None:
        return f"Unknown environment {environment!r}; use one of {', '.join(data.ENVIRONMENTS)}."
    if env.live and sandbox:
        return "A sandbox registration cannot onboard on the production gateway."
    if not env.live and not sandbox:
        return f"A live registration cannot onboard on {env.label}; use the production gateway."
    return ""


# ── Creating and onboarding ──────────────────────────────────────────────────


async def create_unit(
    session: AsyncSession,
    *,
    profile: Any,
    unit_key: str,
    csr_fields: dict[str, Any],
    signer_kind: str,
    signer_config: dict[str, Any] | None = None,
    environment: str = "",
) -> ZatcaEgsUnit:
    if profile.country != "SA":
        raise ZatcaServiceError("EGS units belong to a Saudi registration.", conflict=True)
    key = unit_key.strip()
    if not key:
        raise ZatcaServiceError("A unit needs a key.")
    if signer_kind not in signing.SIGNER_KINDS:
        raise ZatcaServiceError(f"Unknown signer kind {signer_kind!r}; use one of {', '.join(signing.SIGNER_KINDS)}.")
    sandbox = bool(profile.sandbox)
    if signer_kind == signing.SIGNER_TEST and not sandbox:
        raise ZatcaServiceError("A test signer cannot stamp documents for a live registration.")
    environment = environment or ("developer_portal" if sandbox else "production")
    problem = _environment_problem(environment, sandbox=sandbox)
    if problem:
        raise ZatcaServiceError(problem)
    existing = [u for u in await list_units(session, profile.id) if u.unit_key == key]
    if existing:
        raise ZatcaServiceError(f"This registration already has a unit {key!r}.", conflict=True)
    fields = {"vat_number": profile.tax_registration_id, "common_name": key, **dict(csr_fields)}
    unit = ZatcaEgsUnit(
        profile_id=profile.id,
        unit_key=key,
        csr_fields=fields,
        state=STATE_NEW,
        environment=environment,
        signer_kind=signer_kind,
        signer_config=dict(signer_config or {}),
    )
    session.add(unit)
    await session.flush()
    return unit


async def prepare_csr(session: AsyncSession, unit: ZatcaEgsUnit, *, csr_pem: str = "") -> ZatcaEgsUnit:
    """Make the unit's CSR: new -> csr_ready.

    A unit whose key the platform holds (``stored_key``, ``test``) gets a fresh
    key pair here and the CSR is built from its fields. A unit stamped by a
    signing service (``external_http``) brings the CSR the service made, because
    the key never reaches this system.
    """
    if unit.state != STATE_NEW:
        raise ZatcaServiceError(
            f"The CSR is made once, when the unit is new; this unit is {unit.state}. Renew it to rotate the key.",
            conflict=True,
        )
    if unit.signer_kind == signing.SIGNER_EXTERNAL_HTTP:
        if not csr_pem.strip():
            raise ZatcaServiceError("A unit stamped by a signing service needs the CSR that service made.")
        try:
            csr.read_csr(csr_pem)
        except csr.CsrError as exc:
            raise ZatcaServiceError(str(exc)) from exc
        unit.csr_pem = csr_pem.strip()
    else:
        key = signing.generate_key()
        try:
            unit.csr_pem = csr.build_csr(
                csr.CsrFields.from_dict(dict(unit.csr_fields or {})), key, environment=unit.environment
            )
        except csr.CsrError as exc:
            raise ZatcaServiceError(str(exc)) from exc
        unit.private_key_encrypted = encrypt_secret(signing.private_key_pem(key)) or ""
    _move(unit, STATE_CSR_READY)
    unit.last_error = ""
    await session.flush()
    return unit


def _certificate_expiry(token: str) -> dt.datetime | None:
    try:
        return signing.certificate_info(token).not_after
    except Exception:  # noqa: BLE001 - an unreadable certificate is reported when it is first used
        return None


async def request_compliance_csid(
    session: AsyncSession, unit: ZatcaEgsUnit, *, otp: str, client: FatooraClient
) -> ZatcaEgsUnit:
    """csr_ready -> compliance_issued, with the one-time password from the taxpayer's portal."""
    if unit.state != STATE_CSR_READY:
        raise ZatcaServiceError(
            f"A compliance CSID is requested for a unit with a CSR; this one is {unit.state}.", conflict=True
        )
    if not otp.strip():
        raise ZatcaServiceError("The one-time password from the FATOORA portal is required.")
    try:
        response = await client.compliance_csid(csr.csr_for_api(unit.csr_pem), otp)
    except FatooraError as exc:
        unit.last_error = str(exc)
        await session.flush()
        raise ZatcaServiceError(str(exc)) from exc
    unit.compliance_request_id = response.request_id
    unit.compliance_token = response.token
    unit.compliance_secret_encrypted = encrypt_secret(response.secret) or ""
    unit.certificate_not_after = _certificate_expiry(response.token)
    unit.compliance_results = {}
    unit.last_error = ""
    _move(unit, STATE_COMPLIANCE_ISSUED)
    await session.flush()
    return unit


def _required_documents(unit: ZatcaEgsUnit) -> list[tuple[str, str, bool]]:
    """(label, type code, simplified) for each document the unit's invoice types call for."""
    flags = str((unit.csr_fields or {}).get("invoice_type") or "1100")
    wanted: list[tuple[str, str, bool]] = []
    for simplified, flag in ((False, flags[:1]), (True, flags[1:2])):
        if flag != "1":
            continue
        for label, type_code in COMPLIANCE_DOCUMENTS:
            wanted.append((f"{'simplified' if simplified else 'standard'}_{label}", type_code, simplified))
    return wanted


def _sample_input(
    unit: ZatcaEgsUnit,
    profile: Any,
    *,
    type_code: str,
    simplified: bool,
    icv: int,
    previous_hash: str,
    now: dt.datetime,
) -> builder.ZatcaInvoiceInput:
    settings = _zatca_settings(profile)
    seller = builder.seller_from(settings, str(profile.tax_registration_id or ""))
    buyer = None
    if not simplified:
        buyer = builder.Party(
            name="Compliance sample buyer",
            vat_number="399999999800003",
            id_scheme="NAT",
            id_value="1010101010",
            address=seller.address,
        )
    number = f"CHK-{icv:04d}"
    return builder.ZatcaInvoiceInput(
        number=number,
        uuid=str(uuid.uuid4()),
        issue_date=now.date().isoformat(),
        issue_time=now.strftime("%H:%M:%S"),
        type_code=type_code,
        subtype=Subtype(simplified=simplified),
        currency=TAX_CURRENCY,
        seller=seller,
        buyer=buyer,
        lines=(builder.Line("Compliance sample line", Decimal("1"), "PCE", Decimal("100.00")),),
        icv=icv,
        previous_hash=previous_hash,
        billing_reference="CHK-0000" if type_code != TYPE_INVOICE else "",
        reason="Compliance sample" if type_code != TYPE_INVOICE else "",
        supply_date=now.date().isoformat() if not simplified else "",
    )


def unit_signer(unit: ZatcaEgsUnit, *, sandbox: bool, transport: Any = None) -> signing.Signer:
    """The signer the unit stamps with, from its current certificate."""
    if unit.state == STATE_REVOKED:
        raise ZatcaServiceError("This unit is revoked and cannot stamp documents.", conflict=True)
    certificate = (
        unit.production_token if unit.state == STATE_ACTIVE and unit.production_token else unit.compliance_token
    )
    key_pem = decrypt_secret(unit.private_key_encrypted) if unit.private_key_encrypted else ""
    try:
        return signing.resolve_signer(
            unit.signer_kind,
            sandbox=sandbox,
            certificate=certificate,
            private_key_pem_text=key_pem or "",
            config=dict(unit.signer_config or {}),
            transport=transport,
        )
    except signing.SigningError as exc:
        raise ZatcaServiceError(str(exc)) from exc


def unit_credentials(unit: ZatcaEgsUnit) -> Credentials | None:
    """The CSID the unit authenticates with, or ``None`` before it has one."""
    if unit.state == STATE_ACTIVE and unit.production_token:
        return Credentials(unit.production_token, decrypt_secret(unit.production_secret_encrypted) or "")
    if unit.compliance_token:
        return Credentials(unit.compliance_token, decrypt_secret(unit.compliance_secret_encrypted) or "")
    return None


async def run_compliance_checks(
    session: AsyncSession,
    unit: ZatcaEgsUnit,
    *,
    profile: Any,
    client: FatooraClient,
    signer_transport: Any = None,
) -> ZatcaEgsUnit:
    """Send ZATCA one sample of each document the unit will issue; all must pass.

    compliance_issued -> compliance_passed. The samples use a counter of their
    own, so they never consume the unit's real chain.
    """
    if unit.state != STATE_COMPLIANCE_ISSUED:
        raise ZatcaServiceError(
            f"Compliance checks run on a unit with a compliance CSID; this one is {unit.state}.", conflict=True
        )
    credentials = unit_credentials(unit)
    if credentials is None:
        raise ZatcaServiceError("The unit has no compliance CSID.", conflict=True)
    signer = unit_signer(unit, sandbox=bool(profile.sandbox), transport=signer_transport)
    wanted = _required_documents(unit)
    if not wanted:
        raise ZatcaServiceError("The unit's invoice types select neither standard nor simplified invoices.")
    results: dict[str, Any] = {}
    previous = FIRST_PREVIOUS_HASH
    now = _now()
    for icv, (label, type_code, simplified) in enumerate(wanted, start=1):
        try:
            sample = _sample_input(
                unit, profile, type_code=type_code, simplified=simplified, icv=icv, previous_hash=previous, now=now
            )
            root = builder.build_unsigned(sample)
            stamp = await apply_stamp(
                root, signer, signing_time=now, qr_fields=builder.qr_fields(sample), simplified=simplified
            )
            text = c14n.serialize(root)
            response = await client.compliance_invoice(credentials, text, stamp.invoice_hash, sample.uuid)
        except builder.ZatcaBuildError as exc:
            raise ZatcaServiceError(f"The {label.replace('_', ' ')} sample cannot be built: {exc}") from exc
        except FatooraError as exc:
            unit.last_error = str(exc)
            await session.flush()
            raise ZatcaServiceError(str(exc)) from exc
        previous = stamp.invoice_hash
        results[label] = {
            "accepted": response.accepted,
            "http_status": response.http_status,
            "status": response.status,
            "errors": [{"code": m.code, "message": m.message} for m in response.errors],
            "warnings": [{"code": m.code, "message": m.message} for m in response.warnings],
        }
    unit.compliance_results = results
    if all(r["accepted"] for r in results.values()):
        unit.last_error = ""
        _move(unit, STATE_COMPLIANCE_PASSED)
    else:
        failed = ", ".join(k.replace("_", " ") for k, r in results.items() if not r["accepted"])
        unit.last_error = f"ZATCA refused: {failed}."
    await session.flush()
    return unit


async def request_production_csid(session: AsyncSession, unit: ZatcaEgsUnit, *, client: FatooraClient) -> ZatcaEgsUnit:
    """compliance_passed -> active."""
    if unit.state != STATE_COMPLIANCE_PASSED:
        raise ZatcaServiceError(
            f"The production CSID is issued after the compliance checks passed; this unit is {unit.state}.",
            conflict=True,
        )
    credentials = unit_credentials(unit)
    if credentials is None:
        raise ZatcaServiceError("The unit has no compliance CSID.", conflict=True)
    try:
        response = await client.production_csid(credentials, unit.compliance_request_id)
    except FatooraError as exc:
        unit.last_error = str(exc)
        await session.flush()
        raise ZatcaServiceError(str(exc)) from exc
    unit.production_request_id = response.request_id
    unit.production_token = response.token
    unit.production_secret_encrypted = encrypt_secret(response.secret) or ""
    unit.certificate_not_after = _certificate_expiry(response.token)
    unit.last_error = ""
    _move(unit, STATE_ACTIVE)
    await session.flush()
    return unit


async def renew(
    session: AsyncSession, unit: ZatcaEgsUnit, *, otp: str, client: FatooraClient, csr_pem: str = ""
) -> ZatcaEgsUnit:
    """active -> active, with a new key, a new CSR and a new one-time password.

    The old key keeps stamping until ZATCA has answered, and the new one replaces
    it only then.
    """
    if unit.state != STATE_ACTIVE:
        raise ZatcaServiceError(f"Only an active unit is renewed; this one is {unit.state}.", conflict=True)
    if not otp.strip():
        raise ZatcaServiceError("The one-time password from the FATOORA portal is required.")
    credentials = unit_credentials(unit)
    if credentials is None:
        raise ZatcaServiceError("The unit has no production CSID.", conflict=True)
    new_key_pem = ""
    if unit.signer_kind == signing.SIGNER_EXTERNAL_HTTP:
        if not csr_pem.strip():
            raise ZatcaServiceError("A unit stamped by a signing service needs the new CSR that service made.")
        try:
            csr.read_csr(csr_pem)
        except csr.CsrError as exc:
            raise ZatcaServiceError(str(exc)) from exc
        new_csr = csr_pem.strip()
    else:
        key = signing.generate_key()
        try:
            new_csr = csr.build_csr(
                csr.CsrFields.from_dict(dict(unit.csr_fields or {})), key, environment=unit.environment
            )
        except csr.CsrError as exc:
            raise ZatcaServiceError(str(exc)) from exc
        new_key_pem = signing.private_key_pem(key)
    try:
        response = await client.renew_csid(credentials, csr.csr_for_api(new_csr), otp)
    except FatooraError as exc:
        unit.last_error = str(exc)
        await session.flush()
        raise ZatcaServiceError(str(exc)) from exc
    unit.csr_pem = new_csr
    if new_key_pem:
        unit.private_key_encrypted = encrypt_secret(new_key_pem) or ""
    unit.production_request_id = response.request_id or unit.production_request_id
    unit.production_token = response.token
    unit.production_secret_encrypted = encrypt_secret(response.secret) or ""
    unit.certificate_not_after = _certificate_expiry(response.token)
    unit.last_error = ""
    _move(unit, STATE_ACTIVE)
    await session.flush()
    return unit


async def revoke(session: AsyncSession, unit: ZatcaEgsUnit) -> ZatcaEgsUnit:
    """Any state -> revoked. Terminal: the chain stays, a new unit is onboarded."""
    _move(unit, STATE_REVOKED)
    await session.flush()
    return unit


# ── Building a document ──────────────────────────────────────────────────────


def usable_for_building(unit: ZatcaEgsUnit, *, sandbox: bool, today: dt.date) -> str:
    """Why the unit cannot stamp a document now, or an empty string.

    A live registration stamps only from an active unit whose certificate has
    not expired. A sandbox registration may stamp from the compliance CSID on,
    and a test signer needs no certificate at all.
    """
    if unit.state == STATE_REVOKED:
        return "the unit is revoked"
    if sandbox:
        if unit.signer_kind == signing.SIGNER_TEST:
            return ""
        if unit.state in (STATE_COMPLIANCE_ISSUED, STATE_COMPLIANCE_PASSED, STATE_ACTIVE):
            return ""
        return f"the unit is {unit.state} and has no certificate yet"
    if unit.state != STATE_ACTIVE:
        return f"a live registration stamps only from an active unit, and this one is {unit.state}"
    if unit.certificate_not_after is not None and unit.certificate_not_after.date() < today:
        return f"the unit's certificate expired on {unit.certificate_not_after.date().isoformat()}; renew it"
    return ""


async def _pick_unit(session: AsyncSession, profile: Any, requested: str) -> ZatcaEgsUnit:
    units = [u for u in await list_units(session, profile.id) if u.state != STATE_REVOKED]
    if requested:
        chosen = [u for u in units if u.unit_key == requested or str(u.id) == requested]
        if not chosen:
            raise ZatcaServiceError(f"This registration has no unit {requested!r}.")
        return chosen[0]
    if len(units) == 1:
        return units[0]
    if not units:
        raise ZatcaServiceError("This registration has no EGS unit. Onboard one before issuing invoices.")
    raise ZatcaServiceError(
        "This registration has several EGS units. Name the one that issues this invoice in the document's "
        "ZATCA fields (egs_unit)."
    )


async def build_document(
    session: AsyncSession,
    *,
    profile: Any,
    invoice: dict[str, Any],
    lines: list[dict[str, Any]],
    buyer: dict[str, Any] | None,
    zatca_fields: dict[str, Any],
    invoice_id: uuid.UUID | None,
    signer_transport: Any = None,
    now: dt.datetime | None = None,
) -> tuple[str, str]:
    """The stamped document and its media type, with the chain advanced by one.

    Separate from :func:`build_from_invoice` so it can be exercised with plain
    dicts. Raises :class:`ZatcaServiceError` before the chain moves if anything
    is wrong, so a refusal never costs a counter.
    """
    now = now or _now()
    picked = await _pick_unit(session, profile, str(zatca_fields.get("egs_unit") or "").strip())
    blocked = usable_for_building(picked, sandbox=bool(profile.sandbox), today=now.date())
    if blocked:
        raise ZatcaServiceError(f"Unit {picked.unit_key} cannot issue: {blocked}.", conflict=True)

    type_code = str(zatca_fields.get("document_type") or TYPE_INVOICE).strip()
    blocking = [
        i for i in checks.construction_issues(zatca_fields, type_code=type_code) if i.severity == checks.SEVERITY_ERROR
    ]
    if blocking:
        raise ZatcaServiceError(" ".join(i.message for i in blocking))

    # Lock the head of the chain, then read it. Everything above can still fail without costing a counter.
    unit = await get_unit(session, picked.id, lock=True)
    if unit is None:
        raise ZatcaServiceError("The unit disappeared while the document was being built.", conflict=True)
    icv = unit.last_icv + 1
    previous_hash = unit.last_hash or FIRST_PREVIOUS_HASH
    settings = _zatca_settings(profile)
    try:
        spec = builder.input_from_invoice(
            invoice=invoice,
            lines=lines,
            vat_number=str(profile.tax_registration_id or ""),
            settings=settings,
            zatca_fields=zatca_fields,
            buyer=buyer,
            icv=icv,
            previous_hash=previous_hash,
            unit_code_for=_unit_code,
            now=now,
        )
        root = builder.build_unsigned(spec)
        signer = unit_signer(unit, sandbox=bool(profile.sandbox), transport=signer_transport)
        stamp = await apply_stamp(
            root,
            signer,
            signing_time=now,
            qr_fields=builder.qr_fields(spec),
            simplified=spec.subtype.simplified,
        )
    except builder.ZatcaBuildError as exc:
        raise ZatcaServiceError(str(exc)) from exc
    except signing.SigningError as exc:
        raise ZatcaServiceError(str(exc)) from exc

    unit.last_icv = icv
    unit.last_hash = stamp.invoice_hash
    session.add(
        ZatcaChainEntry(
            unit_id=unit.id,
            icv=icv,
            invoice_uuid=spec.uuid,
            invoice_number=spec.number,
            invoice_id=invoice_id,
            previous_hash=previous_hash,
            invoice_hash=stamp.invoice_hash,
            type_code=spec.type_code,
            subtype=spec.subtype.code,
            issued_at=now,
        )
    )
    await session.flush()
    return c14n.serialize(root), builder.MEDIA_TYPE


def _unit_code(unit: Any) -> str:
    from app.modules.einvoice.cii import unece_unit

    return unece_unit(str(unit) if unit is not None else None)


async def build_from_invoice(
    session: AsyncSession,
    *,
    invoice_id: uuid.UUID,
    profile: Any,
    country_fields: dict[str, Any],
) -> tuple[str, str]:
    """The payload builder registered for ``zatca_phase2``."""
    from app.modules.einvoice_clearance.service import ClearanceError
    from app.modules.finance.einvoice_parties import einvoice_defaults_for_invoice
    from app.modules.finance.models import Invoice, InvoiceLineItem

    invoice = (await session.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one_or_none()
    if invoice is None:
        raise ClearanceError(f"Invoice {invoice_id} was not found, so there is nothing to prepare.")
    rows = (
        (
            await session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.sort_order, InvoiceLineItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    defaults = await einvoice_defaults_for_invoice(
        session, contact_id=invoice.contact_id, invoice_direction=invoice.invoice_direction
    )
    fields = country_fields.get("zatca") if isinstance(country_fields.get("zatca"), dict) else {}
    try:
        return await build_document(
            session,
            profile=profile,
            invoice={
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "currency_code": invoice.currency_code,
            },
            lines=[
                {
                    "description": row.description,
                    "quantity": row.quantity,
                    "unit": row.unit,
                    "unit_rate": row.unit_rate,
                    "amount": row.amount,
                    "vat_rate": row.vat_rate,
                    "vat_category": row.vat_category,
                }
                for row in rows
            ],
            buyer=defaults.get("buyer") if isinstance(defaults, dict) else None,
            zatca_fields=dict(fields),
            invoice_id=invoice_id,
        )
    except ZatcaServiceError as exc:
        raise ClearanceError(f"The ZATCA document cannot be built: {exc.message}", conflict=exc.conflict) from exc


__all__ = [
    "COMPLIANCE_DOCUMENTS",
    "RIYADH",
    "TRANSITIONS",
    "ZatcaServiceError",
    "build_document",
    "build_from_invoice",
    "can_transition",
    "create_unit",
    "get_unit",
    "list_units",
    "prepare_csr",
    "renew",
    "request_compliance_csid",
    "request_production_csid",
    "revoke",
    "run_compliance_checks",
    "unit_as_dict",
    "unit_credentials",
    "unit_for_document_uuid",
    "unit_signer",
    "usable_for_building",
]
