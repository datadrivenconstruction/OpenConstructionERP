"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The rating provenance record must not leave the process.

A subcontractor rating stores a ``basis`` column describing how each score was
arrived at. Part of that record, under the ``sources`` key, is a per-metric
{"event": n, "direct": n} pair. The ``direct`` half is a COUNT(*) over the NCR,
safety-incident and schedule tables filtered only by subcontractor and month,
with no project or tenant predicate. Those tables are gated by
verify_project_access when they are read through their own modules.

``basis`` is returned by GET /ratings/, which asks only for subcontractors.read,
the viewer role. So the pair let a viewer read an exact tally of another
tenant's non-conformances and safety incidents.

These tests pin the response schema, not the endpoint, because all three routes
that return a rating go through the same schema and a rule written in one
router would leave the other two open.

Scope, stated so a later reader does not mistake this for the whole fix: the
counters beside ``sources`` are max(accumulated, direct) and the scores are
computed from them, so a narrowed signal remains. Closing that needs a decision
on whether a rating is per project, per tenant or deliberately shared.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.modules.subcontractors.schemas import RatingResponse


def _basis_with_sources() -> dict[str, Any]:
    """A basis exactly as compute_monthly_rating writes it."""
    return {
        "ncr_count": 4,
        "hse_incidents": 1,
        "schedule_deviations_days": 12,
        "cost_variance_percent": "3.5",
        "weights": {"quality": "0.4", "hse": "0.3", "schedule": "0.2", "cost": "0.1"},
        "sources": {
            "ncr_count": {"event": 0, "direct": 4},
            "hse_incidents": {"event": 0, "direct": 1},
            "schedule_deviations_days": {"event": 2, "direct": 12},
        },
    }


def _response(basis: dict[str, Any]) -> RatingResponse:
    now = datetime.now(UTC)
    return RatingResponse.model_validate(
        {
            "id": uuid.uuid4(),
            "subcontractor_id": uuid.uuid4(),
            "period": "2026-07",
            "quality_score": Decimal("82"),
            "hse_score": Decimal("90"),
            "schedule_score": Decimal("64"),
            "cost_score": Decimal("89"),
            "overall_score": Decimal("80"),
            "basis": basis,
            "created_at": now,
            "updated_at": now,
        }
    )


def test_the_source_breakdown_does_not_reach_the_serialised_response() -> None:
    """The regression. Assert on the dumped payload, not on the attribute.

    Serialising is what actually crosses the wire, and a field could be
    dropped from the model and still be emitted by a custom serialiser.
    """
    dumped = _response(_basis_with_sources()).model_dump()

    assert "sources" not in dumped["basis"]
    # The nested counts must not survive under any other key either.
    assert "direct" not in repr(dumped["basis"]), dumped["basis"]


def test_the_input_really_did_carry_the_breakdown() -> None:
    """Control, and the reason the test above means anything.

    Without this the first test passes just as happily against a fixture that
    never had a ``sources`` key, which would make it a test of nothing.
    """
    assert "sources" in _basis_with_sources()
    assert _basis_with_sources()["sources"]["ncr_count"]["direct"] == 4


def test_the_rest_of_the_basis_still_reaches_the_client() -> None:
    """This is a redaction of one key, not of the whole audit record.

    The counters and the weights are what let a user see why a score is what
    it is, and removing them would trade a leak for an unexplainable number.
    """
    basis = _response(_basis_with_sources()).model_dump()["basis"]

    assert basis["ncr_count"] == 4
    assert basis["hse_incidents"] == 1
    assert basis["schedule_deviations_days"] == 12
    assert basis["cost_variance_percent"] == "3.5"
    assert basis["weights"]["quality"] == "0.4"


def test_a_basis_without_the_key_passes_through_unchanged() -> None:
    """Ratings written by the event path and by the seeder have no sources."""
    basis = {"source": "seed"}

    assert _response(basis).model_dump()["basis"] == {"source": "seed"}


def test_an_empty_basis_is_still_an_empty_dict() -> None:
    """The filter must not turn absence into None and break from_attributes."""
    assert _response({}).model_dump()["basis"] == {}
