# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A contact records whether it is a natural person or a legal entity.

Nothing told a sole trader from a GmbH, so a supplier rating could be
personal data without anyone knowing. The field is optional: an old contact
reads as "not stated", never as a guess.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.contacts.models import Contact
from app.modules.contacts.schemas import ContactCreate, ContactResponse, ContactUpdate


def test_both_kinds_are_accepted() -> None:
    for kind in ("natural_person", "legal_entity"):
        assert ContactCreate(contact_type="subcontractor", party_kind=kind).party_kind == kind
        assert ContactUpdate(party_kind=kind).party_kind == kind


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValidationError):
        ContactCreate(contact_type="subcontractor", party_kind="company")


def test_not_stated_stays_empty() -> None:
    assert ContactCreate(contact_type="subcontractor").party_kind is None
    assert "party_kind" not in ContactUpdate().model_dump(exclude_unset=True)


def test_the_column_is_nullable_and_returned() -> None:
    column = Contact.__table__.c.party_kind
    assert column.nullable
    assert "party_kind" in ContactResponse.model_fields


def test_a_subcontractor_carries_the_same_field() -> None:
    from app.modules.subcontractors.models import Subcontractor
    from app.modules.subcontractors.schemas import SubcontractorCreate, SubcontractorResponse, SubcontractorUpdate

    assert Subcontractor.__table__.c.party_kind.nullable
    assert SubcontractorCreate(legal_name="Jan Kowalski", party_kind="natural_person").party_kind == "natural_person"
    assert SubcontractorUpdate(party_kind="legal_entity").party_kind == "legal_entity"
    with pytest.raises(ValidationError):
        SubcontractorUpdate(party_kind="sole_trader")
    assert "party_kind" in SubcontractorResponse.model_fields
