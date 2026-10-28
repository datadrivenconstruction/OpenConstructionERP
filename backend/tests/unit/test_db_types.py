"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :mod:`app.core.db_types` — MoneyType + SafeDate.

The app is PostgreSQL-only: binds always normalise to the strict Python
type (``Decimal`` / ``date``) and the columns store native ``NUMERIC`` /
``DATE``. A simple stub dialect lets us exercise the bind/result logic
without a live PG instance; the storage is additionally covered
end-to-end in ``tests/integration`` against the per-session server.

The result-readers stay string-tolerant: rows migrated in from the old
string-storage era hand back a stored string, and the reader must coerce
it back to the strict Python type. A second stub dialect (``_LEGACY``)
stands in for that "string handed back from the driver" case.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.db_types import MoneyType, SafeDate


class _PGDialect:
    name = "postgresql"

    def type_descriptor(self, t: object) -> object:  # noqa: ANN401
        return t


_PG = _PGDialect()
# The reader has to survive a string handed back for a legacy/migrated row;
# the dialect identity is irrelevant to that path, so reuse the PG stub.
_LEGACY = _PGDialect()


# ── MoneyType ──────────────────────────────────────────────────────────────


def test_money_bind_always_returns_decimal() -> None:
    m = MoneyType()
    # Every input form binds to a Decimal for NUMERIC storage, never a string.
    out = m.process_bind_param("1000.50", _PG)
    assert isinstance(out, Decimal)
    assert out == Decimal("1000.50")
    assert m.process_bind_param(Decimal("1000.50"), _PG) == Decimal("1000.50")
    assert m.process_bind_param(1000.5, _PG) == Decimal("1000.5")
    # Negatives round-trip cleanly.
    assert m.process_bind_param("-250.00", _PG) == Decimal("-250.00")


def test_money_bind_none_is_none() -> None:
    m = MoneyType()
    assert m.process_bind_param(None, _PG) is None


def test_money_bind_garbage_raises() -> None:
    m = MoneyType()
    with pytest.raises(ValueError, match="cannot coerce"):
        m.process_bind_param("not a number", _PG)
    with pytest.raises(ValueError, match="cannot coerce"):
        m.process_bind_param("abc", _PG)


def test_money_result_always_returns_decimal() -> None:
    m = MoneyType()
    assert m.process_result_value(Decimal("99.99"), _PG) == Decimal("99.99")
    # A legacy/migrated row may hand back a string → still recoverable.
    assert m.process_result_value("1250.75", _LEGACY) == Decimal("1250.75")
    assert m.process_result_value("42.00", _PG) == Decimal("42.00")


def test_money_result_none_stays_none() -> None:
    m = MoneyType()
    assert m.process_result_value(None, _PG) is None


def test_money_precision_scale_reach_postgres_type() -> None:
    """Non-default precision must propagate into the PG type_descriptor."""
    m = MoneyType(precision=20, scale=4)
    pg_type = m.load_dialect_impl(_PG)
    # Numeric exposes precision/scale as attributes.
    assert getattr(pg_type, "precision", None) == 20
    assert getattr(pg_type, "scale", None) == 4


# ── SafeDate ───────────────────────────────────────────────────────────────


def test_safedate_bind_accepts_iso_string() -> None:
    d = SafeDate()
    # Bind always returns a date object for native DATE storage.
    out = d.process_bind_param("2026-04-19", _PG)
    assert isinstance(out, date)
    assert out == date(2026, 4, 19)


def test_safedate_bind_accepts_datetime_and_strips_time() -> None:
    d = SafeDate()
    now = datetime(2026, 4, 19, 15, 30, 45)
    assert d.process_bind_param(now, _PG) == date(2026, 4, 19)


def test_safedate_bind_accepts_datetime_iso_string() -> None:
    d = SafeDate()
    assert d.process_bind_param("2026-04-19T10:00:00", _PG) == date(2026, 4, 19)
    assert d.process_bind_param("2026-04-19 10:00:00", _PG) == date(2026, 4, 19)


def test_safedate_bind_none_is_none() -> None:
    d = SafeDate()
    assert d.process_bind_param(None, _PG) is None


def test_safedate_bind_garbage_raises() -> None:
    d = SafeDate()
    with pytest.raises(ValueError):
        d.process_bind_param("not-a-date", _PG)
    with pytest.raises(ValueError):
        d.process_bind_param(123, _PG)  # ints are explicitly rejected


def test_safedate_result_always_returns_date() -> None:
    d = SafeDate()
    assert d.process_result_value(date(2026, 4, 19), _PG) == date(2026, 4, 19)
    # A legacy/migrated row may hand back an ISO string → still coerced.
    assert d.process_result_value("2026-04-19", _LEGACY) == date(2026, 4, 19)
    # datetime returned by driver → coerced to pure date
    assert d.process_result_value(datetime(2026, 4, 19, 12, 0), _PG) == date(2026, 4, 19)


def test_safedate_result_none_stays_none() -> None:
    d = SafeDate()
    assert d.process_result_value(None, _PG) is None
