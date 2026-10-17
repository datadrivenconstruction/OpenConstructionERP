# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A refused subcontractor row is answered by what the database refused.

Nothing makes ``tax_id`` unique in the database (``v3099`` builds a plain,
non-unique index), so an ``IntegrityError`` on create is never a tax number
clash. The PG lane proves the end to end path in
``tests/pg/test_a_refused_subcontractor_names_the_real_conflict.py``; this file
pins the mapping itself for both drivers' error shapes, without a database.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.modules.subcontractors.service import _refused_subcontractor

_FK = "fk_oe_subcontractors_subcontractor_contact_id_oe_contacts_contact"


class _AsyncpgShaped(Exception):
    """asyncpg: the SQLSTATE and the constraint name sit on the error."""

    def __init__(self, sqlstate: str, constraint_name: str | None) -> None:
        super().__init__("refused")
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


class _AdaptedError(Exception):
    """SQLAlchemy's asyncpg adapter wraps the driver error as ``__cause__``."""


def _asyncpg_error(sqlstate: str, constraint: str | None) -> IntegrityError:
    adapted = _AdaptedError("refused")
    adapted.__cause__ = _AsyncpgShaped(sqlstate, constraint)
    return IntegrityError("INSERT ...", {}, adapted)


class _PsycopgShaped(Exception):
    """psycopg: the SQLSTATE on the error, the constraint name on ``diag``."""

    def __init__(self, sqlstate: str, constraint_name: str | None) -> None:
        super().__init__("refused")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=constraint_name)


def test_a_missing_contact_is_a_422_naming_the_contact() -> None:
    answer = _refused_subcontractor(_asyncpg_error("23503", _FK))
    assert answer.status_code == 422
    assert "contact" in answer.detail.lower()
    assert "tax" not in answer.detail.lower()


def test_the_psycopg_shape_is_read_the_same_way() -> None:
    exc = IntegrityError("INSERT ...", {}, _PsycopgShaped("23503", _FK))
    answer = _refused_subcontractor(exc)
    assert answer.status_code == 422
    assert "contact" in answer.detail.lower()


def test_another_foreign_key_is_a_plain_conflict() -> None:
    answer = _refused_subcontractor(_asyncpg_error("23503", "fk_oe_subcontractors_subcontractor_tenant_id"))
    assert answer.status_code == 409
    assert answer.detail == "This subcontractor conflicts with an existing record."


def test_a_unique_violation_never_blames_the_tax_id() -> None:
    answer = _refused_subcontractor(_asyncpg_error("23505", "uq_some_future_constraint"))
    assert answer.status_code == 409
    assert "tax" not in answer.detail.lower()


def test_an_error_without_driver_detail_is_a_plain_conflict() -> None:
    answer = _refused_subcontractor(IntegrityError("INSERT ...", {}, Exception("UNIQUE constraint failed")))
    assert answer.status_code == 409
    assert "tax" not in answer.detail.lower()
