# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An obligation written before ``detail_key`` existed must still be readable.

``detail_key`` and ``detail_params`` are newer than ``oe_funding_obligation``.
Every installation upgrading to this version has rows that predate them, and
on one that reaches the columns through the boot heal rather than the
migration the two do not arrive alike. Measured on such a database:
``detail_key`` is NOT NULL with ``DEFAULT ''`` and ``detail_params`` is
nullable with no default. ``default=""`` on the model is a scalar the heal can
render into DDL; ``default=dict`` is a callable it cannot, so that column
arrives with no default and is therefore nullable. An old row reads back with
an empty ``detail_key`` and a ``None`` ``detail_params``.

``ObligationOut`` declares ``detail_params`` as a ``dict``. Without a coercion
``model_validate`` raises on the first such row, and because the endpoint
builds the whole list in one comprehension, one old row takes the entire
deadline list to a 500.

It failed silently in a way worth remembering: the page still rendered. The
summary endpoint counts open obligations with its own query and answered 200,
so the KPI said two deadlines were open while the list directly beneath it
said there were none. Only one of the two reads rows through this model. A
disagreement between two numbers on one screen was the only symptom, and no
test noticed because every test builds its rows through the service, which
has always written both columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.funding.schemas import ApplicationSummary, ObligationOut


def _row(**overrides: object) -> SimpleNamespace:
    """A row shaped like the ORM object the router validates."""
    now = datetime.now(UTC)
    fields: dict[str, object] = {
        "id": "11111111-1111-1111-1111-111111111111",
        "application_id": "22222222-2222-2222-2222-222222222222",
        "kind": "final_report",
        "title": "Final report",
        "detail": "Due 90 days after the award period ends.",
        "detail_key": "funding.obligation_detail.final_report",
        "detail_params": {"days": 90, "programme": "KFW-261"},
        "due_on": "2027-12-29",
        "status": "open",
        "source": "programme_rule",
        "source_reference": "",
        "responsible_user_id": None,
        "completed_on": "",
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize("field", ["detail_key", "detail_params"])
def test_a_row_written_before_the_column_existed_still_validates(field: str) -> None:
    """``None`` in either new column reads as empty rather than raising."""
    out = ObligationOut.model_validate(_row(**{field: None}))

    assert out.detail_key == "" if field == "detail_key" else out.detail_key
    assert out.detail_params == {} if field == "detail_params" else out.detail_params
    # The prose is what such a row has, and it has to survive untouched:
    # it is the only thing a caller can show for an obligation with no key.
    assert out.detail == "Due 90 days after the award period ends."


def test_the_shape_an_upgraded_row_actually_has() -> None:
    """An empty ``detail_key`` beside a ``None`` ``detail_params``.

    This is the row that produced the 500, copied from the live table rather
    than imagined: every pre-existing obligation there reads back exactly so,
    because the two columns were added with different defaults. It earns its
    own case because the pairing, not either column alone, is what upgrading
    installations will meet.
    """
    out = ObligationOut.model_validate(_row(detail_key="", detail_params=None))

    assert out.detail_key == ""
    assert out.detail_params == {}


def test_both_columns_none_at_once_is_tolerated_too() -> None:
    """Defensive: a database where neither column got a default.

    Not the shape measured on the healed database, where ``detail_key``
    arrives NOT NULL. It is here because nothing in the model guarantees that
    asymmetry - it follows from one default being a scalar and the other a
    callable, which a later edit could change without touching this schema.
    """
    out = ObligationOut.model_validate(_row(detail_key=None, detail_params=None))

    assert out.detail_key == ""
    assert out.detail_params == {}


def test_a_row_written_by_the_current_service_is_not_rewritten() -> None:
    """The coercion must not touch a row that has real values.

    Guarding the direction that matters: a validator that returned the empty
    default unconditionally would make every test above pass and would throw
    away every derived sentence in the product.
    """
    out = ObligationOut.model_validate(_row())

    assert out.detail_key == "funding.obligation_detail.final_report"
    assert out.detail_params == {"days": 90, "programme": "KFW-261"}


def test_the_summary_tolerates_a_next_deadline_whose_values_were_never_stored() -> None:
    """The rollup carries the same values, and inherits the same hazard.

    ``next_due_title_params`` is filled from the next obligation's
    ``detail_params``, the column that reads back ``None`` on an installation
    upgraded through the boot heal. The service already guards that, so this
    is the second of two guards rather than the only one - and it is the one
    that matters, because the service and the schema are different files and
    the endpoint that builds this object is the one that stayed up while the
    deadline list beside it answered 500.
    """
    summary = ApplicationSummary(
        application_id="33333333-3333-3333-3333-333333333333",  # type: ignore[arg-type]
        next_due_on="2026-11-19",
        next_due_title="Spend the funds drawn in request 1",
        next_due_kind="spend_window",
        next_due_title_key="funding.obligation_kind.spend_window",
        next_due_title_params=None,  # type: ignore[arg-type]
    )

    assert summary.next_due_title_params == {}
    # The key and the prose are what such a caller has left, and both survive.
    assert summary.next_due_title_key == "funding.obligation_kind.spend_window"
    assert summary.next_due_title == "Spend the funds drawn in request 1"


def test_a_summary_that_has_its_values_keeps_them() -> None:
    """The guard must not empty a parameter set that is really there.

    Guarding the direction that matters: a coercion returning the default
    unconditionally would satisfy the test above and throw away the only thing
    that tells two spend windows on one award apart.
    """
    summary = ApplicationSummary(
        application_id="33333333-3333-3333-3333-333333333333",  # type: ignore[arg-type]
        next_due_title_key="funding.obligation_kind.spend_window",
        next_due_title_params={"sequence": 2},
    )

    assert summary.next_due_title_params == {"sequence": 2}


def test_an_empty_dict_is_not_turned_into_something_else() -> None:
    """``{}`` is a legitimate stored value and stays ``{}``.

    A manual obligation carries no parameters, so it is written with an empty
    dict rather than ``None``. Distinguishing the two matters only to the
    coercion, and both have to land on ``{}``.
    """
    out = ObligationOut.model_validate(_row(detail_key="", detail_params={}))

    assert out.detail_key == ""
    assert out.detail_params == {}
