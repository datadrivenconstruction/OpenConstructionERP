"""Pure-function tests for the procurement service helpers + ORM money math.

These pin the small, side-effect-free helpers the procurement service leans
on. They are pure unit tests - no DB, no fixtures, no event loop required -
so they run locally and in CI regardless of the PostgreSQL harness.

Covered:
    * ``_safe_decimal_str``      - lenient Decimal-string coercion.
    * ``_parse_decimal``         - strict parse that 400s on garbage.
    * ``_compute_po_total``      - subtotal + tax, Decimal-exact.
    * ``_to_decimal`` / ``_fmt_qty`` - quantity coercion + display normalisation.
    * ``_latest_order_date`` - required_date - lead_time_days, the latest ordering date.
    * ``_mr_assert_transition``  - requisition FSM allowlist (409 on illegal).
    * ``_mr_reconcile``          - requisition quantity rollup, clamped at 0.
    * ``_validate_3way_match``   - the qty-exceeds-received / over-invoice path
                                   (the ``no_confirmed_grs`` path is pinned in
                                   ``test_create_invoice_3way_match``).
    * ``PurchaseOrder.retainage_amount`` / ``retainage_held`` - the withheld
      and floored-held money computations the release path caps against.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.procurement.models import PurchaseOrder
from app.modules.procurement.service import (
    _compute_po_total,
    _fmt_qty,
    _latest_order_date,
    _mr_assert_transition,
    _mr_reconcile,
    _parse_decimal,
    _safe_decimal_str,
    _to_decimal,
    _validate_3way_match,
)

D = Decimal


# ── _safe_decimal_str ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100", "100"),
        ("100.50", "100.50"),
        (Decimal("3.14"), "3.14"),
        (5, "5"),
        # Non-scientific rendering for large values.
        ("1000000", "1000000"),
        # Garbage / None coerce to "0" rather than raising.
        ("not-a-number", "0"),
        (None, "0"),
        ("", "0"),
        ([], "0"),
    ],
)
def test_safe_decimal_str(value: object, expected: str) -> None:
    assert _safe_decimal_str(value) == expected


# ── _parse_decimal (strict, 400 on garbage) ───────────────────────────────


def test_parse_decimal_valid() -> None:
    assert _parse_decimal("12.34") == Decimal("12.34")


def test_parse_decimal_rejects_garbage_with_400() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("xyz", "amount_subtotal")
    assert exc_info.value.status_code == 400
    # The field name is surfaced so the caller knows which field failed.
    assert "amount_subtotal" in str(exc_info.value.detail)


# ── _compute_po_total ─────────────────────────────────────────────────────


def test_compute_po_total_is_decimal_exact() -> None:
    """100.10 + 9.90 must be exactly 110.00 (no float drift)."""
    assert Decimal(_compute_po_total("100.10", "9.90")) == Decimal("110.00")


def test_compute_po_total_zero_tax() -> None:
    assert Decimal(_compute_po_total("250", "0")) == Decimal("250")


def test_compute_po_total_rejects_garbage_subtotal() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _compute_po_total("oops", "0")
    assert exc_info.value.status_code == 400


# ── _to_decimal / _fmt_qty ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("100", D("100")),
        (None, D("0")),
        ("", D("0")),
        ("garbage", D("0")),
        (Decimal("2.5"), D("2.5")),
        (3, D("3")),
    ],
)
def test_to_decimal(value: object, expected: Decimal) -> None:
    assert _to_decimal(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Plain integer-valued strings keep their bare form.
        ("100", "100"),
        # A SQL SUM hands back a float (100.0) - trailing zero stripped so the
        # same logical quantity does not render two ways in one response.
        (100.0, "100"),
        ("100.50", "100.5"),
        # Large values stay out of scientific notation (normalize alone -> 1E+2).
        (1000.0, "1000"),
        ("1000000", "1000000"),
        (None, "0"),
    ],
)
def test_fmt_qty_normalises_uniformly(value: object, expected: str) -> None:
    assert _fmt_qty(value) == expected


# ── _latest_order_date ────────────────────────────────────────────────


def test_latest_order_date_subtracts_lead_time() -> None:
    # 2026-05-20 minus a 10-day lead time -> 2026-05-10.
    assert _latest_order_date("2026-05-20", 10) == "2026-05-10"


def test_latest_order_date_crosses_month_boundary() -> None:
    assert _latest_order_date("2026-05-05", 10) == "2026-04-25"


@pytest.mark.parametrize(
    ("required", "lead"),
    [
        (None, 10),  # no required date
        ("2026-05-20", 0),  # zero lead -> no meaningful pre-order window
        ("2026-05-20", -5),  # negative lead is nonsensical
        ("not-a-date", 10),  # unparseable date
    ],
)
def test_latest_order_date_returns_none_on_invalid(required: str | None, lead: int) -> None:
    assert _latest_order_date(required, lead) is None


# ── _mr_assert_transition (requisition FSM) ───────────────────────────────


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "submitted"),
        ("submitted", "approved"),
        ("approved", "ordered"),
        ("ordered", "received"),
        ("received", "consumed"),
        ("submitted", "rejected"),
        ("rejected", "draft"),
        ("draft", "cancelled"),
        # Self-transition is always a legal no-op (idempotent writes).
        ("consumed", "consumed"),
        ("draft", "draft"),
    ],
)
def test_mr_assert_transition_allows_legal(current: str, target: str) -> None:
    # Should not raise.
    _mr_assert_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("draft", "approved"),  # cannot skip submission
        ("draft", "received"),  # cannot skip the whole chain
        ("approved", "draft"),  # no back-transition once approved
        ("consumed", "draft"),  # terminal - no exit
        ("cancelled", "submitted"),  # terminal - no exit
        ("received", "ordered"),  # no back-transition
        ("draft", "bogus-status"),  # unknown target
    ],
)
def test_mr_assert_transition_rejects_illegal_with_409(current: str, target: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _mr_assert_transition(current, target)
    assert exc_info.value.status_code == 409


def test_mr_assert_transition_terminal_message_is_clear() -> None:
    """A transition out of a terminal state names it as terminal."""
    with pytest.raises(HTTPException) as exc_info:
        _mr_assert_transition("consumed", "draft")
    assert "terminal" in str(exc_info.value.detail).lower()


# ── _mr_reconcile ─────────────────────────────────────────────────────────


def _mr_item(req: str, ordered: str, received: str, consumed: str) -> SimpleNamespace:
    return SimpleNamespace(
        quantity_requested=req,
        quantity_ordered=ordered,
        quantity_received=received,
        quantity_consumed=consumed,
    )


def test_mr_reconcile_single_item_is_wrapped() -> None:
    """A single item (not a list) is accepted and reconciled."""
    item = _mr_item("100", "80", "60", "40")
    out = _mr_reconcile(item)
    assert out["requested"] == D("100")
    assert out["ordered"] == D("80")
    assert out["received"] == D("60")
    assert out["consumed"] == D("40")
    assert out["undelivered"] == D("20")  # ordered - received
    assert out["unconsumed"] == D("20")  # received - consumed


def test_mr_reconcile_sums_across_items() -> None:
    items = [
        _mr_item("100", "100", "100", "50"),
        _mr_item("50", "50", "30", "0"),
    ]
    out = _mr_reconcile(items)
    assert out["requested"] == D("150")
    assert out["ordered"] == D("150")
    assert out["received"] == D("130")
    assert out["consumed"] == D("50")
    assert out["undelivered"] == D("20")
    assert out["unconsumed"] == D("80")


def test_mr_reconcile_clamps_negative_counters_to_zero() -> None:
    """undelivered / unconsumed never go negative even when data is dirty
    (e.g. received > ordered, or consumed > received)."""
    item = _mr_item("10", "10", "20", "30")  # over-received, over-consumed
    out = _mr_reconcile(item)
    assert out["undelivered"] == D("0")  # max(10 - 20, 0)
    assert out["unconsumed"] == D("0")  # max(20 - 30, 0)


def test_mr_reconcile_treats_garbage_quantities_as_zero() -> None:
    item = _mr_item("garbage", None, "", "5")
    out = _mr_reconcile(item)
    assert out["requested"] == D("0")
    assert out["ordered"] == D("0")
    assert out["received"] == D("0")
    assert out["consumed"] == D("5")


def test_mr_reconcile_empty_list() -> None:
    out = _mr_reconcile([])
    assert all(v == D("0") for v in out.values())


# ── _validate_3way_match: qty / over-invoice path ─────────────────────────


def _po_with_confirmed_gr(received: str = "100") -> SimpleNamespace:
    """PO with one line and one CONFIRMED GR receiving ``received`` units."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, description="Rebar", quantity="100")
    gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received=received)
    gr = SimpleNamespace(status="confirmed", items=[gr_item])
    return SimpleNamespace(items=[po_item], goods_receipts=[gr])


def test_validate_3way_match_clean_when_within_received() -> None:
    """Invoicing exactly the received quantity is a clean match."""
    po = _po_with_confirmed_gr("100")
    proposed = [
        {
            "ordinal": 0,
            "po_item_id": po.items[0].id,
            "quantity": "100",
            "description": "Rebar",
        }
    ]
    assert _validate_3way_match(po, proposed) == []


def test_validate_3way_match_flags_qty_exceeds_received() -> None:
    """Invoicing MORE than the confirmed received quantity is a violation
    carrying reason ``qty_exceeds_received`` (router maps it to 422)."""
    po = _po_with_confirmed_gr("60")  # only 60 received
    proposed = [
        {
            "ordinal": 0,
            "po_item_id": po.items[0].id,
            "quantity": "100",  # invoicing 100 against 60 received
            "description": "Rebar",
        }
    ]
    violations = _validate_3way_match(po, proposed)
    assert len(violations) == 1
    v = violations[0]
    assert v["reason"] == "qty_exceeds_received"
    assert v["requested_qty"] == "100"
    assert v["received_qty"] == "60"
    assert v["ordinal"] == 0


def test_validate_3way_match_skips_unmatched_freetext_lines() -> None:
    """Invoice lines without a po_item_id (free-text additions) are out of
    scope and never produce a violation."""
    po = _po_with_confirmed_gr("60")
    proposed = [
        {"ordinal": 0, "po_item_id": None, "quantity": "9999", "description": "freight"},
    ]
    assert _validate_3way_match(po, proposed) == []


def test_validate_3way_match_sums_quantity_across_confirmed_grs() -> None:
    """Two confirmed GRs for the same PO line are summed; invoicing up to the
    combined received quantity is clean."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, description="Rebar", quantity="100")
    gr1 = SimpleNamespace(
        status="confirmed",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="40")],
    )
    gr2 = SimpleNamespace(
        status="confirmed",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="60")],
    )
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr1, gr2])
    proposed = [
        {"ordinal": 0, "po_item_id": po_item_id, "quantity": "100", "description": "Rebar"},
    ]
    assert _validate_3way_match(po, proposed) == []


def test_validate_3way_match_ignores_draft_gr_quantities() -> None:
    """A DRAFT GR's quantities do not count toward the matched received total;
    with only draft GRs the special no_confirmed_grs gate fires instead of a
    qty violation."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, description="Rebar", quantity="100")
    gr = SimpleNamespace(
        status="draft",
        items=[SimpleNamespace(po_item_id=po_item_id, quantity_received="100")],
    )
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])
    proposed = [
        {"ordinal": 0, "po_item_id": po_item_id, "quantity": "100", "description": "Rebar"},
    ]
    violations = _validate_3way_match(po, proposed)
    assert len(violations) == 1
    assert violations[0]["reason"] == "no_confirmed_grs"
    assert violations[0]["has_draft_grs"] is True


# ── PurchaseOrder retainage money math ────────────────────────────────────


def test_retainage_amount_is_percent_of_total() -> None:
    """5% retention on a 10,000 total -> 500.0000 withheld (quantised to 4dp)."""
    po = PurchaseOrder(amount_total="10000", retention_percent=Decimal("5.00"))
    assert po.retainage_amount() == Decimal("500.0000")


def test_retainage_amount_zero_when_no_retention() -> None:
    po = PurchaseOrder(amount_total="10000", retention_percent=Decimal("0.00"))
    assert po.retainage_amount() == Decimal("0.0000")


def test_retainage_amount_garbage_total_is_zero() -> None:
    po = PurchaseOrder(amount_total="not-money", retention_percent=Decimal("5.00"))
    assert po.retainage_amount() == Decimal("0.0000")


def test_retainage_held_nets_off_released() -> None:
    """held = withheld - released. 500 withheld, 200 released -> 300 held."""
    po = PurchaseOrder(
        amount_total="10000",
        retention_percent=Decimal("5.00"),
        retainage_released_amount="200",
    )
    assert po.retainage_held() == Decimal("300.0000")


def test_retainage_held_floors_at_zero_on_over_release() -> None:
    """If somehow more was released than withheld (e.g. total edited DOWN
    after a release), held floors at 0 - never negative."""
    po = PurchaseOrder(
        amount_total="1000",  # withheld now only 50
        retention_percent=Decimal("5.00"),
        retainage_released_amount="200",  # already released 200
    )
    assert po.retainage_held() == Decimal("0")


def test_retainage_held_garbage_released_is_treated_as_zero() -> None:
    po = PurchaseOrder(
        amount_total="10000",
        retention_percent=Decimal("5.00"),
        retainage_released_amount="garbage",
    )
    # Released coerces to 0, so held == full withheld.
    assert po.retainage_held() == Decimal("500.0000")
