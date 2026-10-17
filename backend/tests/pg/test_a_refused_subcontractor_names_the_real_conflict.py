# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: a subcontractor the database refuses names the real conflict.

``create_subcontractor`` answered every ``IntegrityError`` with "A
subcontractor with this tax_id already exists.", but nothing in the database
makes ``tax_id`` unique (the duplicate check is a service read), so that
sentence was never the reason. On a migrated install the table carries a
foreign key from ``contact_id`` to the contacts table, and a contact deleted
between picking it and saving the firm trips that key. The answer now names
what the database actually refused when it is a constraint we know, and
otherwise says the record conflicts with an existing one, never ``tax_id``.

The constraints are added inside the test transaction, as a migrated install
has them; the create-all test schema does not declare the foreign key.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, MetaData, Table, Uuid, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint

from app.database import Base
from app.modules.subcontractors.schemas import SubcontractorCreate
from app.modules.subcontractors.service import SubcontractorService

pytestmark = pytest.mark.asyncio

_TABLE = "oe_subcontractors_subcontractor"


def _contact_key_as_migrated() -> str:
    """The ``ALTER TABLE`` for the contact key under the name a migrated install gives it.

    v3011 declares the key inline, so Alembic names it by the metadata naming
    convention, and the result runs past PostgreSQL's 63 characters and is
    truncated with a hash. Compiled here rather than spelled out, so the test
    follows the convention if it changes.
    """
    md = MetaData(naming_convention=Base.metadata.naming_convention)
    Table("oe_contacts_contact", md, Column("id", Uuid, primary_key=True))
    subs = Table(_TABLE, md, Column("contact_id", Uuid, ForeignKey("oe_contacts_contact.id")))
    (key,) = subs.foreign_key_constraints
    return str(AddConstraint(key).compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize("named", ["by_postgres", "as_migrated"])
async def test_a_missing_contact_is_named_as_the_contact(pg_session, named: str) -> None:
    if named == "as_migrated":
        ddl = _contact_key_as_migrated()
        assert "fk_" in ddl, ddl
    else:
        ddl = f"ALTER TABLE {_TABLE} ADD FOREIGN KEY (contact_id) REFERENCES oe_contacts_contact (id)"
    await pg_session.execute(text(ddl))

    with pytest.raises(HTTPException) as caught:
        await SubcontractorService(pg_session).create_subcontractor(
            SubcontractorCreate(legal_name="Rheinbeton GmbH", tax_id="DE811111111", contact_id=uuid.uuid4())
        )

    assert caught.value.status_code == 422
    assert "contact" in caught.value.detail.lower()
    assert "tax" not in caught.value.detail.lower()


async def test_an_unknown_constraint_is_a_plain_conflict(pg_session) -> None:
    await pg_session.execute(text(f"CREATE UNIQUE INDEX uq_probe_legal_name ON {_TABLE} (legal_name)"))
    svc = SubcontractorService(pg_session)
    await svc.create_subcontractor(SubcontractorCreate(legal_name="Moselstahl GmbH", tax_id="DE822222222"))

    with pytest.raises(HTTPException) as caught:
        await svc.create_subcontractor(SubcontractorCreate(legal_name="Moselstahl GmbH", tax_id="DE833333333"))

    assert caught.value.status_code == 409
    assert caught.value.detail == "This subcontractor conflicts with an existing record."
