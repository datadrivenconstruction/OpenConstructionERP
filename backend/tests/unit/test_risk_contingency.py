"""Monte Carlo cost risk turned into a contingency line: the pure parts.

* The suggestion is ``P(target) - base``, never negative, reproducible by seed.
* The fingerprint moves when a line total moves and not when nothing changed.
* Re-applying keeps the previous run for undo; undo of the first run removes the line.
* ``boq.risk.contingency_stale`` fires only on a stale block.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.validation.engine import Severity, ValidationContext
from app.modules.boq import cost_risk_engine as cre
from app.modules.boq import risk_contingency as rc
from app.modules.boq.validators import RiskContingencyFromStaleRun


def _inputs(*totals: float) -> list[cre.PositionInput]:
    return [cre.PositionInput(ordinal=f"01.{i:03d}", description="", base=t) for i, t in enumerate(totals, 1)]


def test_suggestion_lifts_the_base_to_the_percentile_and_is_reproducible():
    inputs = _inputs(10_000, 25_000, 4_000, 61_000)
    p80 = rc.suggest(inputs, rc.RunParams(percentile=80, iterations=2000), seed=7)
    again = rc.suggest(inputs, rc.RunParams(percentile=80, iterations=2000), seed=7)
    p50 = rc.suggest(inputs, rc.RunParams(percentile=50, iterations=2000), seed=7)
    assert p80.amount == again.amount
    assert p80.base_total == Decimal("100000.00")
    assert p80.amount == p80.budget - p80.base_total
    assert p80.amount > p50.amount >= 0
    assert p80.pct_of_base == pytest.approx(float(p80.amount / p80.base_total * 100), abs=0.01)
    assert 0.0 < p80.confidence <= 1.0
    assert p80.fingerprint == rc.risk_fingerprint(inputs)


def test_suggestion_is_zero_when_the_base_already_sits_above_the_percentile():
    # A wide optimistic band and no upside puts P50 below the deterministic base.
    s = rc.suggest(_inputs(50_000, 50_000), rc.RunParams(50, 2000, 40.0, 0.0, 0.0), seed=3)
    assert s.amount == Decimal("0.00")
    assert s.below_base


@pytest.mark.parametrize("pct", [49, 100])
def test_percentile_outside_the_band_is_refused(pct: int):
    with pytest.raises(HTTPException) as err:
        rc.suggest(_inputs(1000), rc.RunParams(percentile=pct), seed=1)
    assert err.value.status_code == 422


def test_fingerprint_follows_line_totals_only():
    a = rc.risk_fingerprint(_inputs(100.0, 200.0))
    assert a == rc.risk_fingerprint(list(reversed(_inputs(100.0, 200.0))))
    assert a == rc.risk_fingerprint(_inputs(100.001, 200.0))
    assert a != rc.risk_fingerprint(_inputs(100.0, 250.0))


def test_risk_inputs_skip_sections():
    rows = [
        SimpleNamespace(ordinal="01", description="Section", unit="", total=Decimal("0")),
        SimpleNamespace(ordinal="01.001", description="Wall", unit="m2", total=Decimal("120.50")),
    ]
    assert [p.ordinal for p in rc.risk_inputs(rows)] == ["01.001"]


def test_reapply_keeps_previous_and_undo_steps_back_then_removes():
    first = {"percentile": 80, "amount": "1000.00", "name": "Risk P80"}
    meta = rc.next_metadata(None, first, None)
    assert meta["source"] == rc.RISK_CONTINGENCY_SOURCE
    assert meta[rc.PREVIOUS_KEY] == []
    second = {"percentile": 90, "amount": "1500.00", "name": "Risk P90"}
    meta = rc.next_metadata(meta, second, "1000.00")
    assert meta[rc.RUN_KEY] == second
    assert meta[rc.PREVIOUS_KEY][-1]["percentile"] == 80

    restored, amount = rc.undo_metadata(meta)
    assert amount == "1000.00"
    assert restored[rc.RUN_KEY]["percentile"] == 80
    assert restored[rc.PREVIOUS_KEY] == []
    assert rc.undo_metadata(restored) == (None, None)


def test_drift_is_signed_and_relative():
    delta, pct = rc.drift({"amount": "1000.00"}, Decimal("1100.004"))
    assert delta == Decimal("100.00")
    assert pct == 10.0
    assert rc.drift({"amount": "0"}, Decimal("5"))[1] is None


def _line(fingerprint: str, *, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Risk contingency P80",
        is_active=active,
        scope_position_id=None,
        fixed_amount="1000.00",
        metadata_={
            "source": rc.RISK_CONTINGENCY_SOURCE,
            rc.RUN_KEY: {"percentile": 80, "amount": "1000.00", "fingerprint": fingerprint, "applied_at": "2026-11-02"},
        },
    )


def test_stale_block_compares_fingerprints():
    inputs = _inputs(100.0, 200.0)
    fresh = rc.stale_block([_line(rc.risk_fingerprint(inputs))], inputs)
    assert fresh is not None and not fresh["stale"]
    assert rc.stale_block([_line("old")], inputs)["stale"]
    assert rc.stale_block([_line("old", active=False)], inputs) is None
    assert rc.stale_block([], inputs) is None


@pytest.mark.asyncio
async def test_stale_rule_warns_only_on_a_stale_block():
    rule = RiskContingencyFromStaleRun()
    block = {"stale": True, "markup_id": "m1", "name": "Risk P80", "percentile": 80, "applied_at": "2026-11-02T10:00"}
    results = await rule.validate(ValidationContext(data={"risk_contingency": block}))
    assert len(results) == 1
    assert results[0].severity == Severity.WARNING
    assert "P80" in results[0].message and "2026-11-02" in results[0].message
    assert await rule.validate(ValidationContext(data={"risk_contingency": {**block, "stale": False}})) == []
    assert await rule.validate(ValidationContext(data={})) == []
