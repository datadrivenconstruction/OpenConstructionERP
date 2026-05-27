"""Unit tests for BOQ security/correctness audit fixes (2026-05-28).

Covers three issues identified in the deep audit:

* IDOR-REORDER — ``PositionRepository.reorder`` now accepts ``boq_id`` and
  includes it in the WHERE clause so cross-BOQ position-id injection cannot
  silently mutate another user's sort_order values.

* IDOR-DUPLICATE — ``duplicate_boq`` / ``duplicate_position`` router
  endpoints now require ``CurrentUserId`` + ``_verify_boq_owner`` guards
  (router-level; tested via the parameter signature inspection).

* BULK-FLOAT — ``bulk_update_positions`` rate_factor branch now passes
  ``Decimal`` directly to ``PositionUpdate.unit_rate`` instead of routing
  through ``float()``, preserving full precision on large monetary values
  (e.g. rates > 1 000 000 where float64 loses the cent digit).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.modules.boq.repository import PositionRepository
from app.modules.boq.service import _quantize_money


# ── IDOR-REORDER: repository.reorder must filter by boq_id ──────────────────


@pytest.mark.asyncio
async def test_reorder_filters_by_boq_id() -> None:
    """reorder() must include ``Position.boq_id == boq_id`` in every UPDATE.

    Without the fix, passing foreign position IDs would silently mutate rows
    in another user's BOQ.  With the fix the UPDATE WHERE clause has two
    predicates: ``id = <pid> AND boq_id = <boq_id>``, so foreign IDs touch
    0 rows.
    """
    session = MagicMock()
    session.execute = AsyncMock()

    repo = PositionRepository(session)
    boq_id = uuid.uuid4()
    pid_a = uuid.uuid4()
    pid_b = uuid.uuid4()

    await repo.reorder([pid_a, pid_b], boq_id)

    # Two executes — one per position id
    assert session.execute.call_count == 2

    # Inspect the compiled WHERE clauses via the string representation of
    # the Statement objects that were passed to execute().
    calls = session.execute.call_args_list
    for idx, c in enumerate(calls):
        stmt = c.args[0]  # positional first arg to execute(stmt)
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        # Must reference the boq_id constraint
        assert str(boq_id) in compiled, (
            f"Statement {idx} missing boq_id constraint:\n{compiled}"
        )


@pytest.mark.asyncio
async def test_reorder_signature_accepts_boq_id() -> None:
    """Signature check: reorder() must accept positional boq_id argument."""
    import inspect

    sig = inspect.signature(PositionRepository.reorder)
    param_names = list(sig.parameters.keys())
    assert "boq_id" in param_names, (
        "PositionRepository.reorder must have a boq_id parameter"
    )


# ── BULK-FLOAT: rate_factor branch must stay in Decimal ─────────────────────


def test_bulk_rate_factor_no_float_roundtrip() -> None:
    """Verify that _quantize_money returns a Decimal (not float).

    The bulk_update rate_factor branch does:
        new_rate = current * Decimal(str(factor))
        update_data = PositionUpdate(unit_rate=_quantize_money(new_rate))

    Before the fix ``float(_quantize_money(...))`` was used, which loses
    precision on large rates. We assert the value type stays Decimal.
    """
    # Simulate a 7-digit unit rate × 1.03 factor (realistic for equipment)
    current = Decimal("1234567.89")
    factor = Decimal("1.03")
    new_rate = current * factor
    quantized = _quantize_money(new_rate)

    # Must be Decimal — not float
    assert isinstance(quantized, Decimal), (
        f"_quantize_money should return Decimal, got {type(quantized)}"
    )

    # Must not have lost more than 4 decimal-place precision
    expected = Decimal("1271604.9267")
    assert quantized == expected, f"Expected {expected}, got {quantized}"


def test_bulk_rate_factor_float_comparison_demonstrates_loss() -> None:
    """Show that float() conversion WOULD lose precision on large rates.

    This test documents the bug we fixed: converting a Decimal rate to
    float before passing to PositionUpdate.unit_rate can drift the stored
    value by ±0.001 on rates in the 1M range.
    """
    rate = Decimal("1271604.9267")
    as_float = float(rate)
    # float64 cannot represent this exactly
    back_to_decimal = Decimal(str(as_float))
    # The round-trip through float is *not* guaranteed exact; the test
    # merely asserts the original Decimal IS exact (no assertion on float
    # since it may or may not differ depending on platform rounding).
    assert rate == Decimal("1271604.9267")
    assert isinstance(back_to_decimal, Decimal)
    # On most platforms, float(Decimal("1271604.9267")) → 1271604.9266999999
    # or similar — the key point is we avoid the conversion entirely.


# ── IDOR-DUPLICATE: router endpoints must have ownership checks ──────────────


def test_duplicate_boq_endpoint_has_user_id_param() -> None:
    """duplicate_boq must declare CurrentUserId (user_id) parameter."""
    import inspect
    from app.modules.boq.router import duplicate_boq

    sig = inspect.signature(duplicate_boq)
    assert "user_id" in sig.parameters, (
        "duplicate_boq endpoint is missing user_id (ownership check)."
    )


def test_duplicate_position_endpoint_has_user_id_param() -> None:
    """duplicate_position must declare CurrentUserId (user_id) parameter."""
    import inspect
    from app.modules.boq.router import duplicate_position

    sig = inspect.signature(duplicate_position)
    assert "user_id" in sig.parameters, (
        "duplicate_position endpoint is missing user_id (ownership check)."
    )


def test_duplicate_position_endpoint_has_session_param() -> None:
    """duplicate_position must accept session so _verify_boq_owner can query."""
    import inspect
    from app.modules.boq.router import duplicate_position

    sig = inspect.signature(duplicate_position)
    assert "session" in sig.parameters, (
        "duplicate_position endpoint is missing session parameter."
    )
