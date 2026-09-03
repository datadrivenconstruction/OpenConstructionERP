# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The clearance screen opens on a real trail, tied to the real invoice.

The module shipped complete and unseeded, so ``/einvoice-clearance`` was empty
on every install: no registration, no document, no history. What is pinned here
is that the seed closes that with records the module itself produced - a
registration the country registry answers for, a document whose payload is the
XRechnung the export route would render, and a trail written by the state
machine rather than described by the seeder.

The other half is what it must refuse. The showcase invoice is resolved by the
number the demo pack declares, never by position, so a project that carries
other receivables cannot capture the seed and a project that carries no showcase
invoice gets a log line and nothing written. A clearance document pointing at no
invoice is a fiscal record of nothing, which is worse than the empty screen.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core import demo_enrichment
from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
from app.modules.einvoice_clearance import service
from app.modules.einvoice_clearance.adapters import REFERENCE_ADAPTER_KEY
from app.modules.einvoice_clearance.models import (
    TERMINAL_SUCCESS,
    EInvoiceDocument,
    EInvoiceEvent,
    EInvoiceProfile,
)
from app.modules.einvoice_clearance.regimes import get_country_regime
from app.modules.einvoice_clearance.seed import seed_einvoice_clearance_demo
from app.modules.finance.models import Invoice
from app.modules.projects.models import Project

pytestmark = pytest.mark.asyncio

_DEMO_ID = "office-frankfurt"
_SETTINGS_LOGGER = "app.modules.finance.einvoice_settings_seed"


def _declared_invoice_number() -> str:
    """The invoice number the demo pack itself declares as the showcase."""
    showcase = getattr(DEMO_TEMPLATES[_DEMO_ID], "einvoice_showcase", None) or {}
    number = str((showcase.get("invoice") or {}).get("invoice_number") or "").strip()
    assert number, "the demo pack declares no showcase invoice number"
    return number


async def _install(session) -> uuid.UUID:
    result = await install_demo_project(session, _DEMO_ID)
    await session.flush()
    return uuid.UUID(str(result["project_id"]))


async def _showcase_invoice(session, project_id: uuid.UUID) -> Invoice:
    return (
        await session.execute(
            select(Invoice).where(
                Invoice.project_id == project_id,
                Invoice.invoice_number == _declared_invoice_number(),
            )
        )
    ).scalar_one()


async def _documents(session) -> list[EInvoiceDocument]:
    return list((await session.execute(select(EInvoiceDocument))).scalars().all())


async def _events(session, document_id: uuid.UUID) -> list[EInvoiceEvent]:
    return list(
        (
            await session.execute(
                select(EInvoiceEvent).where(EInvoiceEvent.document_id == document_id).order_by(EInvoiceEvent.sequence)
            )
        )
        .scalars()
        .all()
    )


async def test_the_seeder_is_wired_into_the_boot_backfill() -> None:
    """An unreferenced seeder is exactly the bug this module shipped with.

    The module was complete and nothing called it, so the screen was empty on
    every install. Read from the source of the function that owns the list,
    because the list is built inside it from local imports and cannot be
    inspected as a value.
    """
    source = inspect.getsource(demo_enrichment.enrich_projects)
    assert "seed_einvoice_clearance_demo" in source, "the clearance seeder is not called from the boot backfill"
    assert '"einvoice_clearance"' in source, "the seeder runs but is not named, so its counters log as unknown"
    # Fiscal records on the demo estate only: a customer's live project must
    # never be handed a registration and a submission it never made.
    assert "seed_einvoice_clearance_demo(s, _demo_pids)" in source, "the clearance seeder is not demo-gated"


async def test_the_seed_files_one_submitted_document_with_its_trail(pg_session) -> None:
    """A registration, a delivered document with an identifier, and its history."""
    project_id = await _install(pg_session)
    invoice = await _showcase_invoice(pg_session, project_id)

    counts = await seed_einvoice_clearance_demo(pg_session, [project_id])
    assert counts.get("profiles") == 1, f"expected one country registration, got {counts}"
    assert counts.get("documents") == 1, f"expected one document, got {counts}"

    # ── the registration ────────────────────────────────────────────────
    profile = (await pg_session.execute(select(EInvoiceProfile))).scalar_one()
    einvoice_meta = (invoice.metadata_ or {}).get("einvoice") or {}
    seller = einvoice_meta.get("seller") or {}
    regime = get_country_regime(seller["country_code"])
    assert regime is not None, "the seller's country has no regime, so this test would prove nothing"

    assert profile.company_key == seller["name"], "the registration is not the seller the invoice names"
    assert profile.country == seller["country_code"]
    # Denormalised from the registry rather than guessed by the seeder.
    assert profile.regime == regime.regime
    assert profile.platform == regime.platform
    assert profile.tax_registration_id == seller["vat_id"]
    assert profile.adapter_key == REFERENCE_ADAPTER_KEY
    assert profile.sandbox is True, "a live registration would be refused by the offline adapter"
    assert profile.is_active is True
    # Every field the country demands of a registration is answered, or the
    # submission below could not have happened.
    for field in regime.profile_fields:
        assert str(getattr(profile, field) or "").strip(), f"the registration carries no {field}"

    # ── the document ────────────────────────────────────────────────────
    document = (await pg_session.execute(select(EInvoiceDocument))).scalar_one()
    assert document.project_id == project_id
    assert document.invoice_id == invoice.id, "the document is not tied to the showcase invoice"
    assert document.profile_id == profile.id
    assert document.country == profile.country
    assert document.document_format == regime.document_format
    assert document.invoice_number == invoice.invoice_number
    assert document.invoice_date == invoice.invoice_date
    assert document.currency_code == invoice.currency_code
    assert document.total_amount == invoice.amount_total, "the document restates a total the invoice does not carry"

    # The terminal state is the regime's, not the adapter's: a network delivers,
    # it does not clear.
    assert document.status == TERMINAL_SUCCESS[regime.regime]
    assert document.authority_identifier, f"the platform returned no {regime.identifier_label}"
    assert document.submitted_at is not None
    assert document.rejection_code == ""
    assert document.adapter_key == REFERENCE_ADAPTER_KEY

    # The national field the format cannot do without, taken off the invoice.
    for field in regime.document_fields:
        assert document.country_fields.get(field), f"the document carries no {field}"
    assert document.country_fields["buyer_reference"] == einvoice_meta["leitweg_id"]

    # ── the payload is the real document, and the hash describes it ──────
    assert document.payload.startswith("<?xml"), "the stored payload is not an XML document"
    assert document.payload_size == len(document.payload.encode("utf-8"))
    assert document.payload_hash == service.compute_payload_hash(document.payload.encode("utf-8"))
    assert invoice.invoice_number in document.payload
    assert einvoice_meta["leitweg_id"] in document.payload, "BT-10 is missing from the document that was sent"
    assert seller["vat_id"] in document.payload

    # ── the trail ───────────────────────────────────────────────────────
    events = await _events(pg_session, document.id)
    assert len(events) >= 5, f"a submitted document should carry its whole history, got {len(events)}"
    assert [e.sequence for e in events] == list(range(1, len(events) + 1)), "the trail is not contiguously numbered"
    types = [e.event_type for e in events]
    assert types[0] == "created"
    assert {"validated", "queued", "submitted"} <= set(types), f"the history skips a state: {types}"
    assert types[-1] == document.status
    assert events[-1].to_status == document.status
    assert counts.get("events") == len(events)

    owner_id = (await pg_session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one()
    assert events[0].actor_id == owner_id, "the trail is not attributed to a user who exists"


async def test_the_showcase_invoice_is_found_by_number_not_by_position(pg_session) -> None:
    """An older receivable on the same project must not capture the seed.

    The installer picks its invoice list with ``_INVOICES.get(demo_id) or
    generated...``, so a list added for this pack later would change which
    invoices exist and in what order. A seeder that took "the first receivable"
    would then file the showcase submission against a different document, and
    nothing would report it.
    """
    project_id = await _install(pg_session)
    showcase = await _showcase_invoice(pg_session, project_id)

    decoy = Invoice(
        id=uuid.uuid4(),
        project_id=project_id,
        invoice_direction="receivable",
        invoice_number="AR-2026-001",
        invoice_date="2026-01-31",
        currency_code="EUR",
        amount_subtotal="100000.00",
        tax_amount="19000.00",
        retention_amount="0",
        amount_total="119000.00",
        status="paid",
        notes="1. Abschlagsrechnung Rohbau",
        contact_id=showcase.contact_id,
        metadata_={},
        # Older than the showcase, so it wins every ordering a positional
        # resolver could plausibly use.
        created_at=datetime.now(UTC) - timedelta(days=365),
    )
    pg_session.add(decoy)
    await pg_session.flush()

    counts = await seed_einvoice_clearance_demo(pg_session, [project_id])
    assert counts.get("documents") == 1

    document = (await pg_session.execute(select(EInvoiceDocument))).scalar_one()
    assert document.invoice_id == showcase.id, "the seed filed against the wrong invoice"
    assert document.invoice_number == _declared_invoice_number()


async def test_a_project_without_the_showcase_invoice_writes_nothing(pg_session, caplog) -> None:
    """No invoice, no registration and no document - and it says so."""
    project_id = await _install(pg_session)
    invoice = await _showcase_invoice(pg_session, project_id)
    number = invoice.invoice_number
    await pg_session.delete(invoice)
    await pg_session.flush()

    with caplog.at_level(logging.INFO, logger=_SETTINGS_LOGGER):
        counts = await seed_einvoice_clearance_demo(pg_session, [project_id])

    assert counts == {}, f"nothing may be seeded without the invoice, got {counts}"
    assert await _documents(pg_session) == []
    # A registration without a document is a dangling identity: the seed must
    # not leave one behind either.
    assert (await pg_session.execute(select(func.count()).select_from(EInvoiceProfile))).scalar_one() == 0
    assert (await pg_session.execute(select(func.count()).select_from(EInvoiceEvent))).scalar_one() == 0
    assert any(number in record.getMessage() for record in caplog.records), (
        "the skip has to name the invoice somebody can search for"
    )


async def test_the_seed_never_files_a_second_submission_for_one_invoice(pg_session) -> None:
    """A re-run is a no-op; one sale keeps exactly one submitted document."""
    project_id = await _install(pg_session)

    first = await seed_einvoice_clearance_demo(pg_session, [project_id])
    assert first.get("documents") == 1

    async def _totals() -> tuple[int, int, int]:
        return (
            (await pg_session.execute(select(func.count()).select_from(EInvoiceProfile))).scalar_one(),
            (await pg_session.execute(select(func.count()).select_from(EInvoiceDocument))).scalar_one(),
            (await pg_session.execute(select(func.count()).select_from(EInvoiceEvent))).scalar_one(),
        )

    before = await _totals()
    second = await seed_einvoice_clearance_demo(pg_session, [project_id])
    assert second == {}, f"a re-run must write nothing, got {second}"
    assert await _totals() == before


async def test_a_project_that_is_not_a_demo_is_never_touched(pg_session) -> None:
    """Fiscal records are never invented inside a customer's own project."""
    from app.modules.users.models import User

    owner_id = uuid.uuid4()
    pg_session.add(
        User(
            id=owner_id,
            email=f"clearance-{owner_id.hex[:8]}@example.test",
            hashed_password="x",
            full_name="Clearance Seed Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await pg_session.flush()
    project_id = uuid.uuid4()
    pg_session.add(
        Project(
            id=project_id,
            name="Bürogebäude Frankfurt Europaviertel",
            description="A real project that merely shares the demo's name",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await pg_session.flush()

    assert await seed_einvoice_clearance_demo(pg_session, [project_id]) == {}
    assert await _documents(pg_session) == []
    assert (await pg_session.execute(select(func.count()).select_from(EInvoiceProfile))).scalar_one() == 0
