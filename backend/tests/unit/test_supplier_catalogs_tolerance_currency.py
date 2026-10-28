# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠supplier_catalogs: a tolerance profile's absolute floor names its currency.

A profile carries two price bands and the wider one wins: a percentage of the
order total, and an absolute floor. The percentage is safe in any currency,
because a percentage of the order is already denominated in the order's own
currency. The floor was a bare number, and a profile is selected by name and
applied to purchase orders in whatever the tenant trades in.

The direction of the failure is the reason this matters
-------------------------------------------------------
A floor that is too small for the order's currency never wins the ``max`` and
changes nothing. A floor that is too large widens the band, so the invoice is
auto-matched and approved for payment with no exception and no message. The
expensive failure is the silent one, which is why the tests below assert on
``auto_matched`` rather than only on the reported numbers.

This is not the currency guard that already exists
--------------------------------------------------
``match_invoice`` already refuses when the invoice and the order disagree on
currency. That compares two documents. An order and its invoice can agree
perfectly and still be measured against a floor written in a third currency,
which that guard never looks at, and every test here keeps invoice and order
in step so the existing guard stays out of the way.

What ships today
----------------
Nothing sets a nonzero floor: no migration inserts a profile row,
``ensure_default_tolerance_profile`` is called by no application code, and its
floor would be zero anyway. So this defect is reachable only by configuration,
through ``POST /tolerance-profiles``. That is why the zero-floor case is
tested as a no-op - it is what every existing installation does - and why the
unlabelled rows here are built through the repository rather than the schema,
which now refuses to create one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.supplier_catalogs.models import (
    ABS_TOLERANCE_APPLIED,
    ABS_TOLERANCE_DROPPED_MISMATCH,
    ABS_TOLERANCE_DROPPED_ORDER_UNLABELLED,
    ABS_TOLERANCE_DROPPED_UNLABELLED,
    ABS_TOLERANCE_NOT_SET,
    TolerianceProfile,
    VendorInvoiceLine,
)
from app.modules.supplier_catalogs.schemas import (
    MatchResult,
    TolerianceProfileCreate,
    TolerianceProfileUpdate,
    normalise_floor_currency,
)
from app.modules.supplier_catalogs.service import (
    SupplierCatalogsService,
    VendorInvoiceCreate,
    _resolve_absolute_floor,
)
from tests._pg import transactional_session

# _build_po_received is reused rather than re-implemented: it is the same "PO
# sent and fully received" helper the rest of the 3-way-match suite matches
# against, so a difference in outcome here is attributable to the profile and
# not to a second, subtly different way of building an order.
from tests.unit.test_supplier_catalogs import _build_po_received

# ── Fixtures ────────────────────────────────────────────────────────────
#
# Both of these are copies of the ones in test_supplier_catalogs, because
# fixtures live in the module that defines them and importing the helper does
# not bring them along. Kept identical on purpose: these tests are a
# continuation of that file's 3-way-match suite and must run under the same
# conditions as the matches they are being compared with.


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _allow_all_project_access(monkeypatch) -> None:
    """Neutralise the cross-project IDOR gate.

    ``_build_po_received`` seeds a random ``project_id`` with no backing
    Project row, so the real gate would 404 every order before any tolerance
    band was ever consulted.
    """

    async def _noop(project_id, user_id, session):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr("app.dependencies.verify_project_access", _noop)


# _build_po_received defaults to qty 10 at 100, so every order below totals
# 1000 of its currency and the stock 2% band is 20.
_PO_TOTAL = Decimal("1000")
_FLOOR = Decimal("200")


async def _profile(
    svc: SupplierCatalogsService,
    *,
    floor: Decimal,
    currency: str | None,
) -> TolerianceProfile:
    """Store a profile straight through the repository.

    Deliberately not ``create_tolerance_profile``: an unlabelled nonzero floor
    is exactly what the schema now rejects, and it is also exactly what a
    database written before this change contains. The repository is the only
    way to reproduce that row, and reproducing it is the point.
    """
    return await svc.tolerance_profiles.create(
        TolerianceProfile(
            name=f"p-{uuid.uuid4().hex[:6]}",
            price_tolerance_pct=Decimal("2.0"),
            price_tolerance_abs=floor,
            currency=currency,
            qty_tolerance_pct=Decimal("0"),
            period_tolerance_days=7,
            require_gr=True,
            is_default=False,
        ),
    )


async def _invoice_over_by(
    svc: SupplierCatalogsService,
    po,
    vendor,
    *,
    over: Decimal,
    currency: str = "EUR",
):
    """An invoice for the order's total plus ``over``, in the order's currency."""
    return await svc.create_invoice(
        VendorInvoiceCreate(
            number=f"INV-{uuid.uuid4().hex[:6]}",
            vendor_id=vendor.id,
            po_id=po.id,
            currency=currency,
            subtotal=po.total + over,
            tax=Decimal("0"),
        ),
    )


# ── The resolver, in isolation ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("floor", "profile_currency", "order_currency", "expected_floor", "expected_state"),
    [
        # Zero needs no label: the same amount of money everywhere. This is the
        # only row that describes shipped data.
        (Decimal("0"), None, "EUR", Decimal("0"), ABS_TOLERANCE_NOT_SET),
        (Decimal("0"), "USD", "EUR", Decimal("0"), ABS_TOLERANCE_NOT_SET),
        # Labelled, and the label is the order's currency: applies, unchanged.
        (_FLOOR, "EUR", "EUR", _FLOOR, ABS_TOLERANCE_APPLIED),
        (_FLOOR, "eur", "EUR", _FLOOR, ABS_TOLERANCE_APPLIED),
        # The three ways it cannot be shown to be the order's currency. Each
        # returns a zero floor, so the caller's max() is untouched.
        (_FLOOR, None, "EUR", Decimal("0"), ABS_TOLERANCE_DROPPED_UNLABELLED),
        (_FLOOR, "  ", "EUR", Decimal("0"), ABS_TOLERANCE_DROPPED_UNLABELLED),
        (_FLOOR, "EUR", "", Decimal("0"), ABS_TOLERANCE_DROPPED_ORDER_UNLABELLED),
        (_FLOOR, "EUR", None, Decimal("0"), ABS_TOLERANCE_DROPPED_ORDER_UNLABELLED),
        (_FLOOR, "EUR", "JPY", Decimal("0"), ABS_TOLERANCE_DROPPED_MISMATCH),
    ],
)
def test_resolve_absolute_floor(
    floor: Decimal,
    profile_currency: str | None,
    order_currency: str | None,
    expected_floor: Decimal,
    expected_state: str,
) -> None:
    """Every drop returns 0, so ``max(percentage, floor)`` is the percentage."""
    profile = TolerianceProfile(
        name="t",
        price_tolerance_pct=Decimal("2.0"),
        price_tolerance_abs=floor,
        currency=profile_currency,
    )

    resolved, state = _resolve_absolute_floor(profile, order_currency)

    assert resolved == expected_floor
    assert state == expected_state


def test_the_three_dropped_states_are_distinct() -> None:
    """Each names a different remedy, so collapsing them would lose the fix.

    ``dropped_unlabelled`` means label the profile, ``dropped_order_unlabelled``
    means label the order, and ``dropped_currency_mismatch`` means nothing is
    wrong at all - a floor in another currency is the design working. A single
    "dropped" value would send all three to the same support answer.
    """
    assert (
        len(
            {
                ABS_TOLERANCE_NOT_SET,
                ABS_TOLERANCE_APPLIED,
                ABS_TOLERANCE_DROPPED_UNLABELLED,
                ABS_TOLERANCE_DROPPED_ORDER_UNLABELLED,
                ABS_TOLERANCE_DROPPED_MISMATCH,
            },
        )
        == 5
    )


# ── The control: a labelled floor still widens the band ──────────────────


@pytest.mark.asyncio
async def test_a_labelled_floor_still_widens_the_band(session) -> None:
    """The feature works. Without this the fix could be "always drop the floor".

    The invoice is 150 over on a 1000 order. The 2% band is 20, so the
    percentage alone would raise an exception; the 200 floor is what lets it
    through, and it is only allowed to because it says it is EUR and the order
    is EUR. This is the assertion that the repair did not quietly delete a
    working feature.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    assert po.total == _PO_TOTAL
    profile = await _profile(svc, floor=_FLOOR, currency="EUR")
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("150"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "auto_matched"
    assert result.absolute_tolerance_state == ABS_TOLERANCE_APPLIED
    assert result.tolerance_used_abs == _FLOOR
    # The percentage is still reported as the percentage; it is simply not the
    # band that decided this match.
    assert result.tolerance_used_pct == Decimal("2.0")


# ── The defect: the same floor, unlabelled ───────────────────────────────


@pytest.mark.asyncio
async def test_an_unlabelled_floor_no_longer_approves_the_invoice(session) -> None:
    """Same order, same invoice, same 200. The only difference is the label.

    Paired with the control above on purpose: identical figures through the
    identical helper in the same session, so the change in outcome is
    attributable to the currency and to nothing else. Before this change the
    unlabelled 200 widened the band exactly as a EUR 200 would have, whatever
    the order was priced in, and the invoice was approved for payment.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    profile = await _profile(svc, floor=_FLOOR, currency=None)
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("150"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "exception"
    assert result.absolute_tolerance_state == ABS_TOLERANCE_DROPPED_UNLABELLED
    # No floor applied, so there is no floor to report. None rather than 0:
    # zero would read as "a floor of nothing was used", which is a claim.
    assert result.tolerance_used_abs is None
    # And the invoice is held rather than approved, which is the whole point.
    refreshed = await svc.invoices.get(invoice.id)
    assert refreshed is not None
    assert refreshed.status != "approved"


@pytest.mark.asyncio
async def test_a_floor_labelled_in_another_currency_is_dropped(session) -> None:
    """A USD floor against a EUR order. Invoice and order agree, so the existing
    document guard never fires and this is the only thing standing in the way.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    profile = await _profile(svc, floor=_FLOOR, currency="USD")
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("150"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "exception"
    assert result.absolute_tolerance_state == ABS_TOLERANCE_DROPPED_MISMATCH
    assert result.tolerance_used_abs is None


@pytest.mark.asyncio
async def test_an_order_with_no_currency_cannot_borrow_the_profiles(session) -> None:
    """The label has to be shown to match, not assumed to.

    The order records no currency, so a EUR floor cannot be proved to be in the
    order's currency. Dropping it narrows the band, which is the safe way to be
    wrong: a human reviews an exception, nobody reviews an approval.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc, currency="")
    profile = await _profile(svc, floor=_FLOOR, currency="EUR")
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("150"), currency="")

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "exception"
    assert result.absolute_tolerance_state == ABS_TOLERANCE_DROPPED_ORDER_UNLABELLED


# ── What every existing installation does ────────────────────────────────


@pytest.mark.asyncio
async def test_a_zero_floor_behaves_exactly_as_before(session) -> None:
    """The shipped configuration, asserted as a no-op.

    Every profile that exists today has ``price_tolerance_abs`` of zero, so
    ``max(percentage, 0)`` was already the percentage and this change must not
    move a single one of those matches. An invoice 15 over on a 1000 order is
    inside the 2% band and still auto-matches.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    profile = await _profile(svc, floor=Decimal("0"), currency=None)
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("15"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "auto_matched"
    assert result.absolute_tolerance_state == ABS_TOLERANCE_NOT_SET
    assert result.tolerance_used_abs is None


@pytest.mark.asyncio
async def test_a_floor_narrower_than_the_percentage_is_not_reported_as_used(session) -> None:
    """A floor only counts as used when it actually beat the percentage.

    The 2% band on a 1000 order is 20 and the floor is 5, so the floor changed
    no outcome. Reporting it as the band that was used would misdescribe the
    match, and this is what separates "the profile has a floor" from "the floor
    is why this passed".
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    profile = await _profile(svc, floor=Decimal("5"), currency="EUR")
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("15"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "auto_matched"
    # The floor was allowed to apply, and simply did not win.
    assert result.absolute_tolerance_state == ABS_TOLERANCE_APPLIED
    assert result.tolerance_used_abs is None


# ── The line-level band, which is a second reader of the same floor ──────


async def _add_invoice_line(svc, invoice, po_line, *, unit_price: Decimal) -> None:
    """Attach one invoice line pointing at a PO line.

    ``VendorInvoiceCreate`` has no ``lines`` field, so nothing reachable from
    ``create_invoice`` ever populates ``line_results``: lines are written only
    by the e-invoice ingest path, which builds them from a parsed document.
    Going through the repository is therefore the only way to make the
    line-level comparison run at all, and without it the floor's second reader
    is never executed by any test.
    """
    await svc.invoice_lines.create_batch(
        invoice.id,
        [
            VendorInvoiceLine(
                invoice_id=invoice.id,
                po_line_id=po_line.id,
                description="x",
                quantity=Decimal("10"),
                unit_of_measure="pcs",
                unit_price=unit_price,
                line_total=unit_price * Decimal("10"),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_the_line_band_also_drops_an_unlabelled_floor(session) -> None:
    """The floor is read twice per match and both readings had the defect.

    The header compares against a percentage of the order total; the line
    compares against a percentage of a unit price. Those are different
    magnitudes, but the currency question is identical in both, so the floor
    has to be resolved once and both readers have to use the resolved value.
    This pins the second reader, which the header tests do not reach.

    The invoice is deliberately kept inside the header band in both halves, so
    the only thing that moves is the line status. A 150 unit price against an
    ordered 100 is a variance of 50, where the line percentage band is 2.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)

    profile = await _profile(svc, floor=_FLOOR, currency=None)
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("10"))
    await _add_invoice_line(svc, invoice, po.lines[0], unit_price=Decimal("150"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.line_results[0]["status"] == "price_variance", (
        "an unlabelled floor of 200 must not widen a line band computed on a "
        "unit price of 100; without a currency the band is the 2% one, and a "
        "variance of 50 is outside it"
    )
    assert result.absolute_tolerance_state == ABS_TOLERANCE_DROPPED_UNLABELLED


@pytest.mark.asyncio
async def test_the_line_band_still_uses_a_labelled_floor(session) -> None:
    """The paired control: same numbers, and only the label differs.

    Without this the test above is satisfied by a change that breaks the line
    band outright rather than one that resolves its currency. It also records,
    on purpose, that a floor is applied whole to the line comparison even
    though the line band is a percentage of a unit price rather than of the
    order total. That the two are different magnitudes predates this change
    and is not addressed by it; what is addressed is that the floor now has to
    be the order's currency before either reader may use it.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)

    profile = await _profile(svc, floor=_FLOOR, currency="EUR")
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("10"))
    await _add_invoice_line(svc, invoice, po.lines[0], unit_price=Decimal("150"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.line_results[0]["status"] == "ok"
    assert result.absolute_tolerance_state == ABS_TOLERANCE_APPLIED


# ── The exception message stops crediting the percentage ─────────────────


@pytest.mark.asyncio
async def test_an_exception_names_the_band_that_actually_set_it(session) -> None:
    """The message used to print the floor and annotate it "(2.0%)".

    With a 200 EUR floor on a 1000 order the band is 200, not the 20 that 2%
    would give. An invoice 300 over breaches it, and the old message read
    "exceeds tolerance 200 (2.0%)" - a number sourced from the absolute floor,
    labelled as a percentage it had nothing to do with.
    """
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    profile = await _profile(svc, floor=_FLOOR, currency="EUR")
    invoice = await _invoice_over_by(svc, po, vendor, over=Decimal("300"))

    result = await svc.match_invoice(invoice.id, tolerance_profile_name=profile.name)

    assert result.status == "exception"
    reason = result.exception_reason or ""
    assert "absolute floor" in reason
    assert "EUR" in reason
    assert "(2.0%)" not in reason
    assert result.tolerance_used_abs == _FLOOR


# ── The write paths, where a new unlabelled floor would be born ──────────


def test_create_refuses_a_floor_with_no_currency() -> None:
    """The migration counts what exists; this stops the next one being made."""
    with pytest.raises(ValidationError) as excinfo:
        TolerianceProfileCreate(name="p", price_tolerance_abs=Decimal("500"))

    assert "currency" in str(excinfo.value)


def test_create_accepts_a_zero_floor_with_no_currency() -> None:
    """Zero is the same everywhere, so demanding a label for it would be noise.

    This is also the shipped default, so rejecting it would refuse every
    profile anyone creates without thinking about currencies at all.
    """
    profile = TolerianceProfileCreate(name="p")

    assert profile.price_tolerance_abs == Decimal("0")
    assert profile.currency is None


def test_create_normalises_the_code() -> None:
    profile = TolerianceProfileCreate(name="p", price_tolerance_abs=Decimal("500"), currency="eur")

    assert profile.currency == "EUR"


@pytest.mark.asyncio
async def test_update_refuses_to_raise_a_floor_on_an_unlabelled_profile(session) -> None:
    """A PATCH is judged on the row it produces, not the fields it carries.

    The floor arrives alone and looks harmless; the profile it lands on has no
    currency, so the result is precisely the unlabelled amount the create path
    refuses - and it would be written after the migration that counted them.
    """
    svc = SupplierCatalogsService(session)
    profile = await _profile(svc, floor=Decimal("0"), currency=None)

    with pytest.raises(HTTPException) as excinfo:
        await svc.update_tolerance_profile(
            profile.id,
            TolerianceProfileUpdate(price_tolerance_abs=Decimal("500")),
        )

    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_update_refuses_to_clear_the_currency_from_under_a_floor(session) -> None:
    """The other direction: the floor stays and the label is taken away."""
    svc = SupplierCatalogsService(session)
    profile = await _profile(svc, floor=Decimal("500"), currency="EUR")

    with pytest.raises(HTTPException) as excinfo:
        await svc.update_tolerance_profile(profile.id, TolerianceProfileUpdate(currency=None))

    assert excinfo.value.status_code == 422


@pytest.mark.asyncio
async def test_update_allows_a_floor_when_the_profile_already_names_a_currency(session) -> None:
    """The guard must not block the ordinary case, or nobody can configure one."""
    svc = SupplierCatalogsService(session)
    profile = await _profile(svc, floor=Decimal("100"), currency="EUR")

    updated = await svc.update_tolerance_profile(
        profile.id,
        TolerianceProfileUpdate(price_tolerance_abs=Decimal("500")),
    )

    assert updated.price_tolerance_abs == Decimal("500")
    assert updated.currency == "EUR"


def test_the_validator_is_one_function_for_both_paths() -> None:
    """Create and update ask the same question, so they ask the same code.

    Two copies of this rule would be two chances to disagree about it, and the
    update path is the one that cannot be expressed in a schema at all.
    """
    assert normalise_floor_currency(Decimal("0"), None) is None
    assert normalise_floor_currency(Decimal("500"), " eur ") == "EUR"
    with pytest.raises(ValueError, match="needs a currency"):
        normalise_floor_currency(Decimal("500"), None)


# ── The mechanism ────────────────────────────────────────────────────────


def test_match_result_cannot_default_its_way_out_of_answering() -> None:
    """Pins what every assertion above is blind to.

    Both fields are required-and-nullable rather than defaulted. Giving either
    one a default is a one-line convenience that lets a construction site which
    forgets it answer "no floor applied" for a match where a floor governed,
    and every other test in this file would stay green because they all go
    through paths that pass the arguments. This is the one that would not.
    """
    fields = MatchResult.model_fields
    for name in ("tolerance_used_abs", "absolute_tolerance_state"):
        assert fields[name].is_required(), (
            f"MatchResult.{name} has a default again. A default here does not make "
            "the schema more convenient, it lets a forgotten argument vouch for a "
            "match nobody measured."
        )
