"""Cross-database custom column types.

Goals:

* **Dialect-aware storage** — emit PostgreSQL-native ``NUMERIC`` / ``DATE``
  when connected to Postgres so aggregation, range queries and indexes
  work at the SQL layer. Fall back to string storage on SQLite so the
  same models keep round-tripping against the existing ``.db`` dev files
  without a breaking migration.
* **Python-side strictness** — callers always see :class:`decimal.Decimal`
  or :class:`datetime.date`, never strings, regardless of the backend.
  This removes a whole class of ``float("abc")`` / ``ValueError`` bugs
  that used to surface deep inside services.

Why not just ``Numeric`` everywhere? Because the existing SQLite dev
databases store money and dates as strings (``String(50)`` / ``String(20)``)
— swapping column types in place would require a destructive migration
for every contributor. The dialect split lets Postgres get the proper
types going forward while SQLite keeps the existing on-disk format.

Usage:

    from app.core.db_types import MoneyType, SafeDate

    class Invoice(Base):
        amount_total: Mapped[Decimal] = mapped_column(MoneyType(), default=Decimal("0"))
        invoice_date: Mapped[date]    = mapped_column(SafeDate(), nullable=False)

BOTH types normalise inputs — pass a string, a ``Decimal``, an ``int``
or a ``float`` and you always read back a ``Decimal``. Invalid input
raises at bind time, not in downstream code.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Date, Numeric, String, TypeDecorator


class MoneyType(TypeDecorator):
    """Money / signed-decimal column.

    * PostgreSQL → ``NUMERIC(precision, scale)`` (default 18, 2).
    * SQLite     → ``VARCHAR(50)`` holding the canonical string form.

    Always binds and returns :class:`decimal.Decimal`. Unparseable
    values raise :class:`ValueError` at bind time so bad writes never
    reach the DB.
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
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Numeric(self.precision, self.scale))
        return dialect.type_descriptor(String(50))

    def process_bind_param(
        self, value: Decimal | str | int | float | None, dialect: Any
    ) -> Decimal | str | None:
        if value is None:
            return None
        try:
            normalised = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"MoneyType: cannot coerce {value!r} to Decimal") from exc

        if dialect.name == "postgresql":
            return normalised
        # SQLite: canonical string form (no scientific notation, no trailing junk).
        return format(normalised, "f")

    def process_result_value(
        self, value: Decimal | str | None, dialect: Any
    ) -> Decimal | None:
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

    * PostgreSQL → ``DATE``.
    * SQLite     → ``VARCHAR(20)`` holding an ISO-8601 date string.

    Always returns :class:`datetime.date`. Accepts ``date``, ``datetime``,
    or ISO-8601 strings (``"2026-04-19"`` / ``"2026-04-19T10:00:00"``).
    """

    impl = String(20)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Date())
        return dialect.type_descriptor(String(20))

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

    def process_bind_param(
        self, value: date | datetime | str | None, dialect: Any
    ) -> date | str | None:
        if value is None:
            return None
        normalised = self._to_date(value)
        if dialect.name == "postgresql":
            return normalised
        return normalised.isoformat()

    def process_result_value(
        self, value: date | str | None, dialect: Any
    ) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return self._to_date(value)
