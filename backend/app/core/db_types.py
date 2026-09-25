# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Custom column types (PostgreSQL-only).

The app runs on PostgreSQL exclusively, so money and dates are stored in
their native SQL types (``NUMERIC`` / ``DATE``) and aggregation, range
queries and indexes work at the SQL layer.

Goals:

* **Native storage** - money is ``NUMERIC(precision, scale)`` and a
  calendar date is ``DATE``.
* **Python-side strictness** - callers always see :class:`decimal.Decimal`
  or :class:`datetime.date`, never strings. This removes a whole class of
  ``float("abc")`` / ``ValueError`` bugs that used to surface deep inside
  services.
* **Read tolerance for migrated rows** - the result-readers still accept a
  stored string and coerce it back to the strict Python type. Older rows
  migrated in from the previous string-storage SQLite era (``String(50)``
  / ``String(20)``) keep round-tripping without a data fixup.

Usage:

    from app.core.db_types import MoneyType, SafeDate

    class Invoice(Base):
        amount_total: Mapped[Decimal] = mapped_column(MoneyType(), default=Decimal("0"))
        invoice_date: Mapped[date]    = mapped_column(SafeDate(), nullable=False)

BOTH types normalise inputs - pass a string, a ``Decimal``, an ``int``
or a ``float`` and you always read back a ``Decimal``. Invalid input
raises at bind time, not in downstream code.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Date, DateTime, Numeric, String, TypeDecorator

from app.core.calendar_day import calendar_day_utc


class MoneyType(TypeDecorator):
    """Money / signed-decimal column.

    Stored as ``NUMERIC(precision, scale)`` (default 18, 2) on PostgreSQL.

    Always binds and returns :class:`decimal.Decimal`. Unparseable
    values raise :class:`ValueError` at bind time so bad writes never
    reach the DB. The result-reader also tolerates a stored string for
    rows migrated in from the old string-storage era.
    """

    impl = String(50)
    cache_ok = True

    def __init__(
        self,
        precision: int = 18,
        scale: int = 2,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self.precision = precision
        self.scale = scale
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect: Any) -> Any:
        return dialect.type_descriptor(Numeric(self.precision, self.scale))

    def process_bind_param(self, value: Decimal | str | int | float | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"MoneyType: cannot coerce {value!r} to Decimal") from exc

    def process_result_value(self, value: Decimal | str | None, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"MoneyType: corrupt DB value {value!r}") from exc


class SafeDate(TypeDecorator):
    """Calendar-date column (no time component, no timezone).

    Stored as ``DATE`` on PostgreSQL.

    Always returns :class:`datetime.date`. Accepts ``date``, ``datetime``,
    or ISO-8601 strings (``"2026-04-19"`` / ``"2026-04-19T10:00:00"``). The
    result-reader also tolerates a stored ISO string for rows migrated in
    from the old string-storage era.
    """

    impl = String(20)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        return dialect.type_descriptor(Date())

    @staticmethod
    def _to_date(value: date | datetime | str) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            # ``date.fromisoformat`` accepts "YYYY-MM-DD" directly and
            # tolerates the "YYYY-MM-DDTHH:MM:SS" form by stripping the
            # time component before parsing.
            head = value.split("T", 1)[0].split(" ", 1)[0]
            return date.fromisoformat(head)
        raise ValueError(f"SafeDate: cannot coerce {value!r} to date")

    def process_bind_param(self, value: date | datetime | str | None, dialect: Any) -> date | None:
        if value is None:
            return None
        return self._to_date(value)

    def process_result_value(self, value: date | str | None, dialect: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return self._to_date(value)


class AwareDateTime(TypeDecorator):
    """Timezone-aware timestamp column that tolerates loose inputs.

    Stores ``TIMESTAMP WITH TIME ZONE`` (``DateTime(timezone=True)``) on both
    backends, but coerces the bound value to a timezone-aware ``datetime`` first:

    * an ISO-8601 *string* (``"2026-05-30T00:00:00Z"`` / ``"...+05:30"`` / a bare
      ``"2026-05-30T00:00:00"``) is parsed;
    * a *naive* ``datetime`` is assumed UTC.

    This matters on PostgreSQL: asyncpg refuses to bind a naive ``datetime`` - or
    any ``str`` - to a ``TIMESTAMPTZ`` parameter and raises ``DataError``. SQLite
    silently stored whatever it was given, so loose callers (weather auto-fetch
    writing ISO strings, API payloads with offset-less timestamps) only broke on
    PG. Normalising at bind time keeps those call sites working on both dialects.

    Always reads back a timezone-aware ``datetime`` (or ``None``).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    @staticmethod
    def _to_aware(value: datetime | str) -> datetime:
        if isinstance(value, str):
            text = value.strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            value = datetime.fromisoformat(text)
        if not isinstance(value, datetime):
            raise ValueError(f"AwareDateTime: cannot coerce {value!r} to datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_bind_param(self, value: datetime | str | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return self._to_aware(value)

    def process_result_value(self, value: datetime | str | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        # SQLite may hand back a stored ISO string for legacy rows.
        return self._to_aware(value)


class CalendarDayDateTime(TypeDecorator):
    """A calendar day kept in a ``TIMESTAMP WITH TIME ZONE`` column.

    For date-only fields whose column is a timestamp. The column type is
    unchanged; only what is bound and read back is normalised, through
    :mod:`app.core.calendar_day`:

    * **bind**: any date, ``YYYY-MM-DD`` string or datetime becomes midnight
      UTC of its calendar day, so asyncpg never reads a naive value in the
      server's local zone (which stored a day typed at UTC+2 as 22:00 UTC of
      the day before);
    * **read**: a row written before that, at local midnight of the server
      zone, comes back as midnight UTC of the day that was meant.

    Also used on the comparison side of a query: binding ``now`` through this
    type yields midnight UTC of today, which is what a due-date comparison wants.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> datetime | None:
        return calendar_day_utc(value)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        return calendar_day_utc(value)
