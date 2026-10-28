# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# The back-charge status field accepted any string. Both the create and the
# update schema declared it as ``str``, and the update applies a blind setattr
# loop over the payload, so a typo was written straight onto the row. Two things
# then went wrong quietly: the record sat in a state no filter or analytics
# bucket matches, and the agreed / recovered timestamps are stamped by comparing
# the incoming value against the module constants, so neither was set.
#
# These tests pin the closed enumeration and, just as importantly, pin that the
# wire type and the constants cannot drift apart. A future status added to one
# and not the other is exactly how this class of hole reopens.

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.modules.cost_recovery.back_charge import (
    ALL_STATUSES,
    CLOSED_STATUSES,
    OPEN_STATUSES,
    BackChargeStatus,
)
from app.modules.cost_recovery.schemas import BackChargeCreate, BackChargeUpdate


def test_the_wire_type_and_the_constants_cannot_drift() -> None:
    """Adding a status to one place and not the other must fail here."""
    assert set(get_args(BackChargeStatus)) == set(ALL_STATUSES)


def test_every_status_is_classified_as_open_or_closed() -> None:
    """A status in neither bucket disappears from the recovery analytics."""
    assert set(ALL_STATUSES) == (OPEN_STATUSES | CLOSED_STATUSES)
    assert not (OPEN_STATUSES & CLOSED_STATUSES), "a status cannot be both"


@pytest.mark.parametrize("status", ALL_STATUSES)
def test_every_valid_status_is_accepted(status: str) -> None:
    assert BackChargeCreate(status=status).status == status
    assert BackChargeUpdate(status=status).status == status


@pytest.mark.parametrize("bad", ["Proposed", "agreeed", "closed", "", "recovered "])
def test_an_invalid_status_is_rejected_rather_than_stored(bad: str) -> None:
    """Includes the near-misses: wrong case, a typo, a plausible-but-wrong word."""
    with pytest.raises(ValidationError):
        BackChargeCreate(status=bad)
    with pytest.raises(ValidationError):
        BackChargeUpdate(status=bad)


def test_the_update_schema_still_allows_omitting_status() -> None:
    """Partial updates must not be forced to restate the status."""
    payload = BackChargeUpdate(gross_amount=None)

    assert payload.status is None
    assert "status" not in payload.model_dump(exclude_unset=True)
