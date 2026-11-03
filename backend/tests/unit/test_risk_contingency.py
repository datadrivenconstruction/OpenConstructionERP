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


# ── Service behaviour over an in-memory bill ────────────────────────────────


class _FakeBoq:
    """Just enough of BOQService for RiskContingencyService, with real markup schemas applied."""

    def __init__(self, positions: list[SimpleNamespace]) -> None:
        self.positions = positions
        self.markups: list[SimpleNamespace] = []

    async def get_boq_with_positions(self, boq_id):
        return SimpleNamespace(positions=self.positions)

    async def list_markups(self, boq_id):
        return list(self.markups)

    async def add_markup(self, boq_id, data):
        row = SimpleNamespace(id=uuid.uuid4(), **data.model_dump())
        row.metadata_ = row.metadata
        self.markups.append(row)
        return row

    async def update_markup(self, markup_id, data):
        row = next(m for m in self.markups if m.id == markup_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, "metadata_" if key == "metadata" else key, value)
        return row

    async def delete_markup(self, markup_id):
        self.markups = [m for m in self.markups if m.id != markup_id]


def _bill():
    section_a, section_b = uuid.uuid4(), uuid.uuid4()

    def pos(ordinal, total, parent=None, unit="m2", pid=None):
        return SimpleNamespace(
            id=pid or uuid.uuid4(), ordinal=ordinal, description="", unit=unit, total=Decimal(total), parent_id=parent
        )

    rows = [
        pos("01", "0", unit="", pid=section_a),
        pos("01.001", "40000", section_a),
        pos("01.002", "20000", section_a),
        pos("02", "0", unit="", pid=section_b),
        pos("02.001", "50000", section_b),
    ]
    return rows, section_a, section_b


def _apply(svc, **kw):
    return svc.apply(
        uuid.uuid4(),
        rc.RunParams(80, iterations=1000),
        user_id="u",
        user_email=None,
        expected_amount=None,
        name=None,
        **kw,
    )


@pytest.mark.asyncio
async def test_percentage_mode_follows_a_quantity_edit_and_fixed_does_not():
    rows, _a, _b = _bill()
    boq = _FakeBoq(rows)
    svc = rc.RiskContingencyService(boq)
    await _apply(svc, mode="percentage")
    line = boq.markups[0]
    assert line.markup_type == "percentage" and line.fixed_amount == 0 and line.percentage > 0
    before = rc.line_amount(line, rc.money(sum(p.base for p in rc.risk_inputs(rows))))
    rows[1].total = Decimal("80000")  # quantity edit on one line
    after = rc.line_amount(line, rc.money(sum(p.base for p in rc.risk_inputs(rows))))
    assert after > before

    boq_fixed = _FakeBoq(_bill()[0])
    await _apply(rc.RiskContingencyService(boq_fixed))
    fixed = boq_fixed.markups[0]
    assert fixed.markup_type == "fixed"
    assert rc.line_amount(fixed, Decimal("999999")) == fixed.fixed_amount


@pytest.mark.asyncio
async def test_section_line_overrides_the_bill_wide_one_and_undo_restores_it():
    rows, section_a, _b = _bill()
    boq = _FakeBoq(rows)
    svc = rc.RiskContingencyService(boq)
    await _apply(svc)
    wide = boq.markups[0]
    await _apply(svc, scope_position_id=section_a)
    scoped = next(m for m in boq.markups if m.scope_position_id == section_a)
    assert scoped.overrides_id == wide.id and scoped.sort_order == wide.sort_order
    assert rc.find_risk_line(boq.markups, section_a) is scoped and rc.find_risk_line(boq.markups) is wide
    assert scoped.metadata_[rc.RUN_KEY]["scope_position_id"] == str(section_a)

    first_amount = scoped.fixed_amount
    await svc.apply(
        uuid.uuid4(),
        rc.RunParams(95, iterations=1000),
        user_id="u",
        user_email=None,
        expected_amount=None,
        name=None,
        scope_position_id=section_a,
    )
    assert scoped.fixed_amount != first_amount
    await svc.undo(uuid.uuid4(), section_a)
    assert scoped.fixed_amount == first_amount and scoped.metadata_[rc.RUN_KEY]["percentile"] == 80
    await svc.undo(uuid.uuid4(), section_a)
    assert rc.find_risk_line(boq.markups, section_a) is None and rc.find_risk_line(boq.markups) is wide


@pytest.mark.asyncio
async def test_undo_restores_the_previous_mode():
    boq = _FakeBoq(_bill()[0])
    svc = rc.RiskContingencyService(boq)
    await _apply(svc)
    await _apply(svc, mode="percentage")
    line = boq.markups[0]
    assert line.markup_type == "percentage"
    await svc.undo(uuid.uuid4())
    assert line.markup_type == "fixed" and line.fixed_amount > 0


@pytest.mark.asyncio
async def test_expected_amount_mismatch_is_refused_with_409():
    boq = _FakeBoq(_bill()[0])
    with pytest.raises(HTTPException) as exc:
        await rc.RiskContingencyService(boq).apply(
            uuid.uuid4(),
            rc.RunParams(80, iterations=1000),
            user_id="u",
            user_email=None,
            expected_amount=Decimal("0.01"),
            name=None,
        )
    assert exc.value.status_code == 409 and boq.markups == []


@pytest.mark.asyncio
async def test_unknown_section_is_404_and_manual_contingency_is_reported():
    rows, _a, _b = _bill()
    boq = _FakeBoq(rows)
    svc = rc.RiskContingencyService(boq)
    with pytest.raises(HTTPException) as exc:
        await _apply(svc, scope_position_id=uuid.uuid4())
    assert exc.value.status_code == 404
    boq.markups.append(
        SimpleNamespace(
            id=uuid.uuid4(),
            name="Contingency 5%",
            category="contingency",
            is_active=True,
            metadata_={},
            sort_order=3,
            scope_position_id=None,
        )
    )
    out = await _apply(svc)
    assert out["other_contingency"] == ["Contingency 5%"]


@pytest.mark.asyncio
async def test_below_p50_and_double_count_rules():
    from app.modules.boq.validators import RiskContingencyBelowP50, RiskContingencyDoubleCount

    below = {"below_p50": True, "line_amount": "10.00", "p50_amount": "500.00", "name": "Risk P80"}
    res = await RiskContingencyBelowP50().validate(ValidationContext(data={"risk_contingency": below}))
    assert len(res) == 1 and res[0].severity == Severity.INFO
    assert (
        await RiskContingencyBelowP50().validate(ValidationContext(data={"risk_contingency": {"below_p50": False}}))
        == []
    )
    dbl = {"other_contingency": ["Contingency 5%"], "name": "Risk P80"}
    res = await RiskContingencyDoubleCount().validate(ValidationContext(data={"risk_contingency": dbl}))
    assert len(res) == 1 and res[0].severity == Severity.WARNING and "Contingency 5%" in res[0].message
    assert await RiskContingencyDoubleCount().validate(ValidationContext(data={})) == []


def test_export_label_names_the_percentile_and_run_only_for_risk_lines():
    from app.modules.boq.pdf_export import _markup_label

    lb = {"risk_allowance": "P{percentile} risk allowance (run {run})"}
    risk = SimpleNamespace(
        name="x",
        metadata_={
            "source": rc.RISK_CONTINGENCY_SOURCE,
            rc.RUN_KEY: {"percentile": 80, "fingerprint": "abcdef0123456789"},
        },
    )
    assert _markup_label(risk, lb) == "P80 risk allowance (run abcdef01)"
    assert _markup_label(SimpleNamespace(name="Overhead", metadata_={}), lb) == "Overhead"
