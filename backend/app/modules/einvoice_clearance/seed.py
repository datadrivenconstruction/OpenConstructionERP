# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo seed for the e-invoice clearance module.

Loaded on demand via ``await seed_einvoice_clearance_demo(session, project_ids)``.

The gap this closes
===================
The module shipped complete and unseeded, so ``/einvoice-clearance`` was empty
on every install: no registration, no document, no trail. A visitor could read
the explainer about what an authority answers and then look at a screen where
nothing had ever been answered.

Seeded through the module's own service
=======================================
The document is not written as rows. It is prepared, checked and submitted
through :mod:`app.modules.einvoice_clearance.service`, the same three calls the
router makes, so the statuses, the ordering and the identifier are produced by
the state machine rather than described by this file. A second description of
the transition sequence is a second thing that can be wrong, and the trail is
only worth showing if it is the trail the machine actually writes.

The payload is likewise the real one: the service renders the invoice with the
EN 16931 engine, so what the screen offers for download is the XRechnung a user
would get from the export route, hashed from the exact bytes.

Nothing is assumed about which invoice
======================================
The invoice is resolved by :func:`showcase_invoices`, which looks up the number
the demo pack declares on the project that pack installed. The country, the
seller and the buyer reference all come off that invoice; the regime, the
platform and the format come from the country registry. When any of it cannot
be resolved the project is skipped with a log line and nothing is written,
because a clearance document pointing at no invoice is a fiscal record of
nothing - worse than the empty screen it was meant to fix.

Sandbox, deliberately
=====================
The registration is a sandbox one and the submission acknowledges the warning
that says so. Both are forced by what the module is: the offline reference
adapter refuses to serve a live registration (it would be minting identifiers no
authority has ever issued), and a sandbox registration on a real invoice raises
a warning that blocks an unacknowledged submission. Turning either off does not
produce a "more realistic" demo - it produces a rejected document.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.einvoice_clearance import repository, service
from app.modules.einvoice_clearance.adapters import (
    REFERENCE_ADAPTER_KEY,
    adapter_registry,
    register_builtin_adapters,
)
from app.modules.einvoice_clearance.models import EInvoiceDocument, EInvoiceProfile
from app.modules.einvoice_clearance.regimes import CountryRegime, get_country_regime
from app.modules.einvoice_clearance.schemas import DocumentCreateRequest, ProfileCreateRequest
from app.modules.finance.einvoice_settings_seed import showcase_invoices
from app.modules.finance.models import Invoice
from app.modules.projects.models import Project

logger = logging.getLogger(__name__)

__all__ = ["seed_einvoice_clearance_demo"]

#: ISO 6523 scheme for a seller's own address on an exchange network, by
#: country. 9930 is a German VAT number - the spelling the supplier catalog's
#: Peppol endpoint parser already reads ("9930:DE123456789"). A country that is
#: not listed leaves the participant id empty and the completeness rule names
#: the gap, which is the honest outcome: inventing a scheme code for a network
#: this file cannot check would put a plausible wrong address on a registration.
_VAT_ADDRESS_SCHEMES: dict[str, str] = {"DE": "9930"}

#: Where each national document field is read from on the invoice's e-invoice
#: metadata. Only aliases live here; a field whose name matches its metadata key
#: needs no entry. The buyer-reference pair mirrors ``build_einvoice``, which
#: resolves BT-10 as ``buyer_reference`` or ``leitweg_id``, so the field carried
#: on the clearance document and the one written into the XML are one value.
_DOCUMENT_FIELD_SOURCES: dict[str, tuple[str, ...]] = {"buyer_reference": ("buyer_reference", "leitweg_id")}


def _einvoice_meta(invoice: Invoice) -> dict[str, Any]:
    """The invoice's own e-invoice metadata block."""
    return dict((invoice.metadata_ or {}).get("einvoice") or {})


def _network_participant_id(country: str, seller: dict[str, Any]) -> str:
    """The seller's address on the exchange network, as far as it is knowable.

    An address the invoice states wins. Otherwise it is derived from the VAT id
    for the countries whose scheme code is known, and left empty for the rest.
    """
    address = str(seller.get("electronic_address") or "").strip()
    if address:
        scheme = str(seller.get("electronic_address_scheme") or "").strip()
        return f"{scheme}:{address}" if scheme and ":" not in address else address
    scheme = _VAT_ADDRESS_SCHEMES.get(country, "")
    vat_id = str(seller.get("vat_id") or "").strip()
    return f"{scheme}:{vat_id}" if scheme and vat_id else ""


def _country_fields(regime: CountryRegime, ei: dict[str, Any]) -> dict[str, str] | None:
    """The national fields this country demands, read off the invoice.

    Returns ``None`` when the invoice cannot answer one of them. That is a
    refusal rather than a partial document: the same field list is what the
    mandatory-fields rule blocks a submission on and what the reference adapter
    rejects, so a document missing one could never leave draft, and a draft
    nobody can send is not what the screen is being seeded to show.
    """
    resolved: dict[str, str] = {}
    for name in regime.document_fields:
        for key in _DOCUMENT_FIELD_SOURCES.get(name, (name,)):
            value = str(ei.get(key) or "").strip()
            if value:
                resolved[name] = value
                break
        else:
            return None
    return resolved


def _ensure_reference_adapter() -> None:
    """Install the shipped offline adapter when the module hook has not.

    Idempotent by design - the registry overwrites by key. The seed can run in a
    context where the module's ``on_startup`` never fired (a test, a partner pack
    applied after boot), and without an adapter every submission is refused for
    a reason that has nothing to do with the data being seeded.
    """
    if adapter_registry.get(REFERENCE_ADAPTER_KEY) is None:
        register_builtin_adapters()


async def _resolve_actor(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    """The project owner, so the trail is attributed to a user who exists."""
    return (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()


def _registration_settings(regime: CountryRegime, seller: dict[str, Any]) -> dict[str, Any]:
    """Settings a country's document builder reads off the registration.

    Saudi Arabia builds its own UBL document from the registration, so the
    seller's commercial register number and national address live here. Every
    other country builds from the invoice alone and needs nothing.
    """
    if regime.document_format != "zatca_phase2":
        return {}
    return {
        "zatca": {
            "seller": {
                "name": str(seller.get("name") or "").strip(),
                "id_scheme": "CRN",
                "id_value": str(seller.get("commercial_register") or "").strip(),
                "address": {
                    "street": str(seller.get("line1") or "").strip(),
                    "building_number": str(seller.get("building_number") or "").strip(),
                    "additional_number": str(seller.get("additional_number") or "").strip(),
                    "district": str(seller.get("district") or "").strip(),
                    "city": str(seller.get("city") or "").strip(),
                    "postal_zone": str(seller.get("postcode") or "").strip(),
                    "country": regime.country,
                },
            }
        }
    }


async def _prepare_registration(session: AsyncSession, regime: CountryRegime, profile: EInvoiceProfile) -> None:
    """Give a registration what it needs before it can build a document.

    A Saudi registration stamps documents from an EGS unit, which a real
    taxpayer onboards against the authority. The demo registration is a
    sandbox one, so its unit signs with the throwaway test key the module
    provides for exactly this, and says so in the document trail.
    """
    if regime.document_format != "zatca_phase2":
        return
    from app.modules.einvoice_clearance.service import register_payload_builder
    from app.modules.einvoice_zatca import service as zatca
    from app.modules.einvoice_zatca.signing import SIGNER_TEST
    from app.modules.einvoice_zatca.validators import ZATCA_FORMAT

    # The builder is registered when the module starts; a seed that runs outside that path needs it too.
    register_payload_builder(ZATCA_FORMAT, zatca.build_from_invoice)

    if await zatca.list_units(session, profile.id):
        return
    await zatca.create_unit(
        session,
        profile=profile,
        unit_key="EGS-RUH-01",
        csr_fields={"organization_name": profile.company_key, "branch_name": "Head office"},
        signer_kind=SIGNER_TEST,
    )


async def _load_vat_onto_lines(session: AsyncSession, invoice: Invoice, ei: dict[str, Any]) -> None:
    """Carry the document's VAT rate onto lines that state none.

    The demo installer writes lines without a rate; a document built from the
    lines (not from the invoice header) needs one per line, and the rate the
    pack declares for the invoice is the honest source.
    """
    from decimal import Decimal, InvalidOperation

    from app.modules.finance.models import InvoiceLineItem

    try:
        rate = Decimal(str(ei.get("vat_rate") or "").strip())
    except (InvalidOperation, ValueError):
        return
    rows = (await session.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice.id))).scalars()
    for row in rows:
        if row.vat_rate is None:
            row.vat_rate = rate
            row.vat_category = "S" if rate > 0 else "Z"
    await session.flush()


async def _profile_for(
    session: AsyncSession,
    regime: CountryRegime,
    seller: dict[str, Any],
) -> tuple[EInvoiceProfile, bool]:
    """The registration this seller holds in this country, created if absent.

    Looked up on ``(company_key, country)``, which is the pair the table is
    unique on, so a re-run reuses the registration instead of colliding with it.
    Built through the module's own create schema and the registry-denormalised
    fields the router writes, so a seeded registration is indistinguishable from
    one somebody entered on the screen.
    """
    company_key = str(seller.get("name") or "").strip()
    existing = await repository.get_profile_for(session, company_key=company_key, country=regime.country)
    if existing is not None:
        return existing, False

    body = ProfileCreateRequest(
        company_key=company_key,
        country=regime.country,
        tax_registration_id=str(seller.get("vat_id") or seller.get("tax_number") or "").strip(),
        network_participant_id=_network_participant_id(regime.country, seller),
        adapter_key=REFERENCE_ADAPTER_KEY,
        certificate_reference=str(seller.get("certificate_reference") or "").strip(),
        settings=_registration_settings(regime, seller),
        # See the module docstring: the offline adapter refuses a live
        # registration outright, so a "live" demo registration would produce a
        # rejection rather than a submission.
        sandbox=True,
        is_active=True,
    )
    profile = EInvoiceProfile(
        company_key=body.company_key,
        country=body.country,
        # Denormalised from the registry, exactly as the router does it: the row
        # records what was registered, not what the code believes today.
        regime=regime.regime,
        platform=regime.platform,
        tax_registration_id=body.tax_registration_id,
        network_participant_id=body.network_participant_id,
        certificate_reference=body.certificate_reference,
        adapter_key=body.adapter_key,
        sandbox=body.sandbox,
        is_active=body.is_active,
        settings=dict(body.settings or {}),
        notes=body.notes,
    )
    await repository.add_profile(session, profile)
    return profile, True


async def _seed_one(
    session: AsyncSession,
    project_id: uuid.UUID,
    invoice: Invoice,
) -> dict[str, int] | None:
    """Register, prepare and submit one invoice. ``None`` when it was skipped."""
    ei = _einvoice_meta(invoice)
    seller = dict(ei.get("seller") or {})
    company_key = str(seller.get("name") or "").strip()
    country = str(seller.get("country_code") or "").strip().upper()
    if not company_key or not country:
        logger.info(
            "e-invoice clearance seed skipped: invoice %s names no seller country to register under",
            invoice.invoice_number,
        )
        return None

    regime = get_country_regime(country)
    if regime is None:
        logger.info(
            "e-invoice clearance seed skipped: no regime is registered for country %s (invoice %s)",
            country,
            invoice.invoice_number,
        )
        return None

    country_fields = _country_fields(regime, ei)
    if country_fields is None:
        logger.info(
            "e-invoice clearance seed skipped: invoice %s carries none of the fields %s requires (%s)",
            invoice.invoice_number,
            country,
            ", ".join(regime.document_fields),
        )
        return None

    _ensure_reference_adapter()
    actor_id = await _resolve_actor(session, project_id)
    profile, profile_created = await _profile_for(session, regime, seller)
    if not regime.en16931_profile:
        await _load_vat_onto_lines(session, invoice, ei)
    await _prepare_registration(session, regime, profile)

    body = DocumentCreateRequest(
        project_id=project_id,
        profile_id=profile.id,
        invoice_id=invoice.id,
        # Every figure is read off the resolved invoice. A literal here would be
        # stale the moment the showcase is repriced, and it would be stale
        # silently, because the document carries its own copy on purpose.
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        currency_code=invoice.currency_code,
        total_amount=str(invoice.amount_total),
        country_fields=country_fields,
        # No payload: the service renders the real EN 16931 document for the
        # countries whose format the engine covers, which is what makes the
        # seeded record downloadable and its hash meaningful.
        payload=None,
    )

    document, _created_findings = await service.create_document(session, profile=profile, body=body, actor_id=actor_id)
    await service.validate_document(session, document=document, profile=profile, actor_id=actor_id)
    document, outcome, _findings = await service.submit_document(
        session,
        document=document,
        profile=profile,
        actor_id=actor_id,
        # The sandbox warning. It is true, it is the point, and leaving it
        # unacknowledged would only mean no document at all.
        accept_warnings=True,
    )
    if not outcome.accepted:
        # Not fatal, and not hidden: the trail carries the rejection with the
        # code on it, which is a legitimate thing for the screen to show.
        logger.warning(
            "e-invoice clearance seed: %s refused invoice %s (%s)",
            regime.platform,
            invoice.invoice_number,
            outcome.rejection_code or "no code",
        )
    events = await repository.list_events(session, document.id)
    return {"profiles": 1 if profile_created else 0, "documents": 1, "events": len(events)}


async def seed_einvoice_clearance_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed a country registration, a submitted document and its trail.

    Idempotent per invoice: an invoice that already has a clearance document is
    left alone, whether this seeder wrote it or a user did, so a re-run never
    files a second submission for one sale.

    Args:
        session: Open async DB session.
        project_ids: Candidate projects. Only demo projects whose pack declares
            an e-invoice showcase are touched.

    Returns:
        Row counts per entity, or an empty dict when nothing was seeded.
    """
    counts = {"profiles": 0, "documents": 0, "events": 0}

    for project_id, invoice in await showcase_invoices(session, project_ids):
        existing = (
            await session.execute(select(EInvoiceDocument.id).where(EInvoiceDocument.invoice_id == invoice.id).limit(1))
        ).scalar_one_or_none()
        if existing is not None:
            continue

        try:
            # One savepoint per invoice. A refusal partway through would
            # otherwise leave a document nobody can submit and nobody will
            # retry, because the idempotency check above would then skip it
            # forever. Rolling back to here keeps the seed re-runnable.
            async with session.begin_nested():
                seeded = await _seed_one(session, project_id, invoice)
        except service.ClearanceError as exc:
            logger.warning(
                "e-invoice clearance seed skipped for invoice %s: %s",
                invoice.invoice_number,
                exc.message,
            )
            continue
        if seeded is None:
            continue
        for key, value in seeded.items():
            counts[key] += value

    await session.flush()
    if any(counts.values()):
        logger.info("e-invoice clearance demo seed inserted: %s", counts)
        return counts
    return {}
