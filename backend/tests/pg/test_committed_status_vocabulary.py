"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The decision-impact engine and the service must agree on what is committed.

``decision_impact`` is deliberately a pure module: no ORM, no ``app.*`` imports,
stdlib and ``Decimal`` only. The price of that is a duplicated copy of the
committed-status vocabulary, and a duplicate nobody checks is a divergence
waiting to happen. It already happened once. The engine held a single set,
``{"approved", "executed"}``, and applied it to change orders and variation
orders alike. A variation order's FSM is ``issued -> in_progress -> completed |
voided`` and never passes through either word, so no variation order could ever
count. The decision-impact panel understated committed cost and days by the
whole value of every agreed VO, and the "resulting" figures inherited it.

These tests pin the two copies together and pin each copy to the FSM it claims
to describe, so the next divergence fails here instead of quietly shrinking a
number on a panel.

No database is involved. They live in the PG lane because that lane is a merge
gate and the default unit lane is only run by a job that is chronically red for
unrelated reasons.
"""

from __future__ import annotations

import pytest

from app.modules.change_intelligence import decision_impact as engine
from app.modules.change_intelligence import service as ci_service
from app.modules.variations.service import VO_TRANSITIONS


def test_change_order_vocabulary_matches_the_service() -> None:
    """The engine's change-order set is the service's set."""
    assert engine.COMMITTED_STATUSES_BY_KIND[engine.KIND_CHANGE_ORDER] == ci_service._CO_APPROVED_STATUSES


def test_variation_order_vocabulary_matches_the_service() -> None:
    """The engine's variation-order set is the service's set.

    This is the assertion that was false. The engine had no variation-order
    entry at all.
    """
    assert engine.COMMITTED_STATUSES_BY_KIND[engine.KIND_VARIATION_ORDER] == ci_service._VO_AGREED_STATUSES


def test_variation_order_vocabulary_is_reachable_in_the_real_fsm() -> None:
    """Every committed VO status must be a state the VO FSM can actually be in.

    Equality with the service proves the two agree; this proves they agree
    about something real. A pair of copies can be identical and both wrong.
    """
    reachable = set(VO_TRANSITIONS) | {t for ts in VO_TRANSITIONS.values() for t in ts}
    committed = engine.COMMITTED_STATUSES_BY_KIND[engine.KIND_VARIATION_ORDER]
    assert committed <= reachable, f"not VO states: {sorted(committed - reachable)}"
    assert "voided" not in committed, "a voided variation order is not committed cost"


def test_change_order_statuses_are_not_variation_order_statuses() -> None:
    """The two vocabularies must not overlap.

    If they ever did, a single shared set would look correct again and the
    original defect could be reintroduced without any test noticing.
    """
    co = engine.COMMITTED_STATUSES_BY_KIND[engine.KIND_CHANGE_ORDER]
    vo = engine.COMMITTED_STATUSES_BY_KIND[engine.KIND_VARIATION_ORDER]
    assert not (co & vo)


def test_is_committed_reads_the_kind() -> None:
    """The same status must answer differently for different families."""
    assert engine.is_committed("completed", engine.KIND_VARIATION_ORDER)
    assert not engine.is_committed("completed", engine.KIND_CHANGE_ORDER)
    assert engine.is_committed("executed", engine.KIND_CHANGE_ORDER)
    assert not engine.is_committed("executed", engine.KIND_VARIATION_ORDER)


@pytest.mark.parametrize("raw", ["  Completed ", "COMPLETED", "completed"])
def test_is_committed_normalises_the_stored_string(raw: str) -> None:
    """Raw stored values carry whitespace and case; the test is on the value."""
    assert engine.is_committed(raw, engine.KIND_VARIATION_ORDER)


def test_unknown_kind_raises_rather_than_answering_false() -> None:
    """A kind with no vocabulary must be loud.

    Answering False would let a family added to the baseline query contribute
    a silent zero, which is exactly the shape of the defect being fixed.
    """
    with pytest.raises(ValueError, match="COMMITTED_STATUSES_BY_KIND"):
        engine.is_committed("approved", "variation_request")


def test_every_kind_in_the_baseline_query_has_a_vocabulary() -> None:
    """Whatever the service gathers as the baseline, the engine can judge.

    The service builds the committed baseline from a fixed pair of kinds. If a
    third is ever added there, this fails until its vocabulary is written.
    """
    for kind in (ci_service.KIND_CHANGE_ORDER, ci_service.KIND_VARIATION_ORDER):
        assert kind in engine.COMMITTED_STATUSES_BY_KIND
