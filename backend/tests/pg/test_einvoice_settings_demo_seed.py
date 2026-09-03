# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The E-Rechnung settings screen is filled on the install whose invoice passes.

The German showcase preflight found the two halves disagreeing: the seeded
invoice exports a green XRechnung because it carries the seller in its own
``metadata["einvoice"]``, while /settings shows an empty form because the
standing configuration is created lazily and starts blank. A visitor is then
told the document is complete and shown nothing behind it.

What is pinned here is the join, not the values: the settings must hold the
seller the invoice actually names, resolved from that invoice rather than
restated in the seeder, so the screen and the document cannot drift into naming
two different companies. Plus the two properties that make it safe to run on
every boot - a field a user typed survives, and a project whose showcase invoice
is missing gets a log line instead of a half-filled configuration.
"""

from __future__ import annotations

import inspect
import logging
import uuid

import pytest
from sqlalchemy import select

from app.core import demo_enrichment
from app.core.demo_projects import install_demo_project
from app.modules.finance.einvoice_settings_models import DEFAULT_SCOPE, EInvoiceSettings
from app.modules.finance.einvoice_settings_schemas import EInvoiceSettingsRead
from app.modules.finance.einvoice_settings_seed import seed_einvoice_settings_demo, showcase_invoices
from app.modules.finance.einvoice_settings_service import get_settings
from app.modules.finance.models import Invoice

pytestmark = pytest.mark.asyncio

_DEMO_ID = "office-frankfurt"
_SEED_LOGGER = "app.modules.finance.einvoice_settings_seed"


async def _install(session) -> uuid.UUID:
    """Install the German demo project and return its id."""
    result = await install_demo_project(session, _DEMO_ID)
    await session.flush()
    return result["project_id"]


async def _settings_row(session) -> EInvoiceSettings | None:
    return (
        await session.execute(select(EInvoiceSettings).where(EInvoiceSettings.scope == DEFAULT_SCOPE))
    ).scalar_one_or_none()


async def test_the_seeder_is_wired_into_the_boot_backfill() -> None:
    """A seeder nobody calls leaves the screen exactly as empty as before.

    Read from the source of the function that owns the list, because the list is
    built inside it from local imports and cannot be inspected as a value.
    """
    source = inspect.getsource(demo_enrichment.enrich_projects)
    assert "seed_einvoice_settings_demo" in source, "the settings seeder is not called from the boot backfill"
    assert '"einvoice_settings"' in source, "the seeder runs but is not named, so its counters log as unknown"
    # The configuration is instance-wide, so it is filled from the demo estate
    # only: a fictional VAT id in a customer's e-invoice settings is worse than
    # an empty form.
    assert "seed_einvoice_settings_demo(s, _demo_pids)" in source, "the settings seeder is not demo-gated"


async def test_the_settings_hold_the_seller_the_showcase_invoice_names(pg_session) -> None:
    """Every seeded field is read back out of the invoice, never out of a literal."""
    project_id = await _install(pg_session)

    resolved = await showcase_invoices(pg_session, [project_id])
    assert len(resolved) == 1, "the showcase invoice must resolve by its number"
    resolved_project_id, invoice = resolved[0]
    # The resolver answers in the database's own type, whatever spelling it was
    # asked in, so a caller can hand the id straight to a UUID column.
    assert isinstance(resolved_project_id, uuid.UUID)
    assert resolved_project_id == uuid.UUID(str(project_id))
    # The dangling-reference guard: the invoice the resolver hands back belongs
    # to the project it was asked about, not to a neighbour with the same number.
    assert invoice.project_id == uuid.UUID(str(project_id))
    assert invoice.invoice_direction == "receivable"

    # Both spellings of the same id have to resolve the same project.
    # ``install_demo_project`` returns ``str(project.id)`` while the demo
    # enrichment passes a ``uuid.UUID`` from a select, so a resolver that
    # matched on the object would answer "no showcase here" to one of its two
    # real callers and look exactly like an install that has none.
    again = await showcase_invoices(pg_session, [uuid.UUID(str(project_id))])
    assert [p for p, _ in again] == [resolved_project_id]

    counts = await seed_einvoice_settings_demo(pg_session, [project_id])
    assert counts == {"einvoice_settings": 1}, f"expected one configuration written, got {counts}"

    row = await _settings_row(pg_session)
    assert row is not None, "no configuration row was written"

    einvoice_meta = (invoice.metadata_ or {}).get("einvoice") or {}
    seller = einvoice_meta.get("seller") or {}
    assert seller, "the fixture invoice carries no seller, so this test would prove nothing"
    for field, value in seller.items():
        assert getattr(row, f"seller_{field}", None) == value, f"seller_{field} does not match the invoice"
    for field in ("payee_iban", "payee_account_name", "payment_terms"):
        assert getattr(row, field) == einvoice_meta.get(field), f"{field} does not match the invoice"

    # The screen's own verdict, not ours: a German seller needs BG-6 contact
    # details and a tax registration on top of the EN 16931 minimum, and the
    # point of seeding is that the form opens finished rather than half done.
    view = EInvoiceSettingsRead.from_row(row)
    assert view.missing == [], f"the settings form still reports gaps: {view.missing}"
    assert view.complete is True

    # And the configuration reaches a document through the merge the export path
    # uses, which is the only way it is ever read.
    defaults = row.as_defaults()
    assert defaults["seller"]["name"] == seller["name"]
    assert defaults["payee_iban"] == einvoice_meta["payee_iban"]


async def test_a_value_the_user_typed_survives_the_seed(pg_session) -> None:
    """Gap-fill, never overwrite - and the second run is a no-op."""
    project_id = await _install(pg_session)

    typed = await get_settings(pg_session)
    typed.seller_name = "Kestner Hoch- und Tiefbau GmbH"
    typed.payee_iban = "DE02120300000000202051"
    await pg_session.flush()

    counts = await seed_einvoice_settings_demo(pg_session, [project_id])
    assert counts == {"einvoice_settings": 1}

    row = await _settings_row(pg_session)
    assert row is not None
    assert row.seller_name == "Kestner Hoch- und Tiefbau GmbH", "the seed overwrote a name the user had typed"
    assert row.payee_iban == "DE02120300000000202051", "the seed overwrote an account the user had typed"
    # The gaps beside them were filled from the invoice all the same.
    assert row.seller_city == "Frankfurt am Main"
    assert row.seller_vat_id
    assert row.payment_terms

    # Nothing is empty any more, so a re-run has nothing to do.
    second = await seed_einvoice_settings_demo(pg_session, [project_id])
    assert second == {}, f"a re-run must write nothing, got {second}"


async def test_a_project_without_the_showcase_invoice_is_skipped_out_loud(pg_session, caplog) -> None:
    """A missing invoice leaves no configuration behind, and says so."""
    project_id = await _install(pg_session)

    invoice = (
        await pg_session.execute(
            select(Invoice).where(
                Invoice.project_id == project_id,
                Invoice.invoice_direction == "receivable",
            )
        )
    ).scalar_one()
    number = invoice.invoice_number
    await pg_session.delete(invoice)
    await pg_session.flush()

    with caplog.at_level(logging.INFO, logger=_SEED_LOGGER):
        assert await showcase_invoices(pg_session, [project_id]) == []
        counts = await seed_einvoice_settings_demo(pg_session, [project_id])

    assert counts == {}, f"nothing may be seeded without the invoice, got {counts}"
    assert await _settings_row(pg_session) is None, "an unresolved seed must not leave a configuration row"
    assert any(number in record.getMessage() for record in caplog.records), (
        "the skip has to be reported by the invoice number somebody can search for"
    )


async def test_a_project_that_is_not_a_demo_is_never_read(pg_session) -> None:
    """The instance-wide configuration is not filled from a customer's project."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner_id = uuid.uuid4()
    pg_session.add(
        User(
            id=owner_id,
            email=f"einvoice-{owner_id.hex[:8]}@example.test",
            hashed_password="x",
            full_name="Settings Seed Owner",
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

    assert await showcase_invoices(pg_session, [project_id]) == []
    assert await seed_einvoice_settings_demo(pg_session, [project_id]) == {}
    assert await _settings_row(pg_session) is None
