"""Risk contingency from the project risk register, and the percentage mode.

Runs the service against an in-memory bill, so no database is needed:

* the register source reserves the whole percentile of the open risks' weighted cost;
  closed, retired and rejected risks are out; mixed or foreign currencies and an empty
  register are refused with a plain 422;
* the run stores a snapshot of the risks behind it, and a changed probability makes the
  line stale;
* percentage mode stores ``amount / direct cost * 100`` (4 dp) and the bill's markup total
  moves with a quantity edit while a fixed line stays put;
* one risk line switches between fixed and percentage in place, and undo restores the
  previous type;
* the export label names the run, and the two new rules fire on their facts only.
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException

from app.core.validation.engine import Severity, ValidationContext
from app.modules.boq import risk_contingency as rc
from app.modules.boq.service import _calculate_markup_amounts
from app.modules.boq.validators import (
    RiskContingencyBelowP50,
    RiskContingencyDoubleCount,
    RiskContingencyFromStaleRun,
)
from app.modules.risk import mc_core

BOQ_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


class FakeBoq:
    """The slice of ``BOQService`` the contingency service touches, held in memory."""

    def __init__(self, quantity: float = 100.0) -> None:
        self.quantity = quantity
        self.markups: list[NS] = []
        self.session = None

    async def get_boq_with_positions(self, _boq_id):
        positions = [
            NS(ordinal="01.001", description="Slab", unit="m3", total=Decimal(str(self.quantity)) * Decimal("400")),
            NS(ordinal="01.002", description="Walls", unit="m2", total=Decimal("30000")),
        ]
        return NS(project_id=PROJECT_ID, positions=positions, direct_cost_total=sum(p.total for p in positions))

    async def list_markups(self, _boq_id):
        return list(self.markups)

    async def get_export_fx(self, _boq_id):
        return "EUR", {}

    async def add_markup(self, _boq_id, data):
        row = NS(
            id=uuid.uuid4(), name=data.name, markup_type=data.markup_type, category=data.category,
            percentage=str(data.percentage), fixed_amount=str(data.fixed_amount), apply_to=data.apply_to,
            sort_order=data.sort_order, is_active=True, scope_position_id=None, overrides_id=None,
            metadata_=dict(data.metadata),
        )  # fmt: skip
        self.markups.append(row)
        return row

    async def update_markup(self, markup_id, data):
        row = next(m for m in self.markups if m.id == markup_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            if key == "metadata":
                row.metadata_ = {**row.metadata_, **value}
            elif key in ("percentage", "fixed_amount"):
                setattr(row, key, str(value))
            else:
                setattr(row, key, value)
        return row

    async def delete_markup(self, markup_id):
        self.markups = [m for m in self.markups if m.id != markup_id]


def _row(i: int, prob: str, cost: str, st: str = "identified", cur: str = "EUR", **kw):
    base = dict(
        id=uuid.UUID(int=i), code=f"R-{i}", title=f"Risk {i}", status=st, probability=prob, probability_score=None,
        impact_cost=cost, currency=cur, cost_p10=None, cost_p50=None, cost_p90=None,
    )  # fmt: skip
    return NS(**{**base, **kw})


@pytest.fixture
def register(monkeypatch):
    rows: list[NS] = [
        _row(1, "0.5", "40000", cost_p10=10000, cost_p50=40000, cost_p90=90000),
        _row(2, "0.3", "25000", cost_p10=5000, cost_p50=25000, cost_p90=60000),
        _row(3, "0.2", "80000"),
    ]

    class FakeRepo:
        def __init__(self, _session):
            pass

        async def all_for_project(self, _pid):
            return rows

    monkeypatch.setattr("app.modules.risk.repository.RiskRepository", FakeRepo)
    return rows


def _svc(boq: FakeBoq) -> rc.RiskContingencyService:
    return rc.RiskContingencyService(boq)


async def _apply(boq: FakeBoq, **kw):
    params = rc.RunParams(
        percentile=kw.pop("percentile", 80), iterations=2000, source=kw.pop("source", "positions"),
        mode=kw.pop("mode", "fixed"),
    )  # fmt: skip
    return await _svc(boq).apply(BOQ_ID, params, user_id="u1", user_email=None, expected_amount=None, name=None)


def _expected_register_amount(rows, pct: int) -> Decimal:
    used = [r for r in rc.register_risks(rows) if r.contributes]
    sim = mc_core.simulate_cost([mc_core.CostItem(*r.triple, r.weight) for r in used], 2000, rc.risk_seed(BOQ_ID))
    return rc.money(sim.percentile(pct))


async def test_register_amount_is_the_whole_percentile_of_open_risks(register):
    boq = FakeBoq()
    status = await _svc(boq).status(BOQ_ID, rc.RunParams(80, 2000, source="register"))
    s = status["suggestion"]
    assert s["source"] == "register"
    assert s["amount"] == _expected_register_amount(register, 80)
    assert s["items_used"] == 3
    assert s["budget"] == s["base_total"] + s["amount"]
    assert s["amount"] > _expected_register_amount(register, 50) > 0


@pytest.mark.parametrize("state", ["closed", "retired", "rejected", "Closed"])
async def test_closed_retired_and_rejected_risks_are_excluded(register, state):
    boq = FakeBoq()
    before = (await _svc(boq).status(BOQ_ID, rc.RunParams(80, 2000, source="register")))["suggestion"]
    register.append(_row(9, "1", "9000000", st=state))
    after = (await _svc(boq).status(BOQ_ID, rc.RunParams(80, 2000, source="register")))["suggestion"]
    assert after["amount"] == before["amount"]
    assert after["items_used"] == 3
    assert after["register_fingerprint"] == before["register_fingerprint"]


async def test_mixed_currencies_are_refused(register):
    register.append(_row(5, "0.5", "1000", cur="USD"))
    with pytest.raises(HTTPException) as err:
        await _svc(FakeBoq()).status(BOQ_ID, rc.RunParams(80, 2000, source="register"))
    assert err.value.status_code == 422
    assert err.value.detail == "Risk items use more than one currency"


async def test_currency_other_than_the_bill_is_refused(register):
    for r in register:
        r.currency = "USD"
    with pytest.raises(HTTPException) as err:
        await _svc(FakeBoq()).status(BOQ_ID, rc.RunParams(80, 2000, source="register"))
    assert err.value.status_code == 422
    assert "differs from the bill currency" in err.value.detail


@pytest.mark.parametrize("zero", ["no_rows", "all_zero", "all_closed"])
async def test_empty_register_is_refused(register, zero):
    if zero == "no_rows":
        register.clear()
    elif zero == "all_zero":
        for r in register:
            r.impact_cost = "0"
            r.cost_p10 = r.cost_p50 = r.cost_p90 = None
    else:
        for r in register:
            r.status = "closed"
    with pytest.raises(HTTPException) as err:
        await _apply(FakeBoq(), source="register")
    assert err.value.status_code == 422
    assert err.value.detail == "The risk register has no open priced risks"


async def test_register_run_stores_the_risks_behind_it_and_goes_stale_when_one_moves(register):
    boq = FakeBoq()
    out = await _apply(boq, source="register")
    assert out["applied"]["source"] == "register"
    assert out["applied"]["items_used"] == 3
    items = out["applied"]["risk_items"]
    assert [i["code"] for i in items] == ["R-1", "R-2", "R-3"]
    assert set(items[0]) == {"id", "code", "title", "probability", "impact_cost", "currency"}
    assert out["stale"] is False
    assert out["applied"]["register_fingerprint"] == out["current_fingerprint"]

    register[1].probability = "0.6"
    moved = await _svc(boq).status(BOQ_ID, None)
    assert moved["stale"] is True
    block = rc.stale_block(boq.markups, [], register_fp=rc.register_fingerprint(rc.register_risks(register)))
    assert block["stale"] is True and block["source"] == "register"


async def test_a_long_register_keeps_ids_only(register, monkeypatch):
    register.extend(_row(100 + i, "0.01", "10") for i in range(rc.MAX_SNAPSHOT_ITEMS))
    out = await _apply(FakeBoq(), source="register")
    assert out["applied"]["items_used"] == 3 + rc.MAX_SNAPSHOT_ITEMS
    assert set(out["applied"]["risk_items"][0]) == {"id"}


async def test_register_fixed_amount_does_not_move_with_quantities(register):
    boq = FakeBoq(100)
    await _apply(boq, source="register")
    line = boq.markups[0]
    assert line.markup_type == "fixed"
    amount = Decimal(line.fixed_amount)
    boq.quantity = 300
    assert (await _svc(boq).status(BOQ_ID, None))["applied"]["line_amount"] == str(amount)


async def test_percentage_mode_stores_the_share_and_the_total_follows_quantities():
    boq = FakeBoq(100)
    out = await _apply(boq, mode="percentage")
    line = boq.markups[0]
    direct = (await boq.get_boq_with_positions(BOQ_ID)).direct_cost_total
    amount = Decimal(out["applied"]["amount"])
    expected = (amount / direct * 100).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    assert line.markup_type == "percentage" and line.apply_to == "direct_cost"
    assert Decimal(line.percentage) == expected
    assert out["applied"]["mode"] == "percentage" and out["applied"]["percentage"] == str(expected)

    def total(direct_cost: Decimal) -> Decimal:
        ((_, amt),) = _calculate_markup_amounts(direct_cost, boq.markups)
        return direct_cost + amt

    first = total(direct)
    boq.quantity = 200
    direct2 = (await boq.get_boq_with_positions(BOQ_ID)).direct_cost_total
    assert direct2 > direct
    second = total(direct2)
    assert (second - direct2) > (first - direct) * Decimal("1.3")
    assert abs((second - direct2) - direct2 * expected / 100) < Decimal("0.01")


async def test_percentage_line_is_stale_on_the_resimulated_amount_not_on_the_fingerprint():
    boq = FakeBoq(100)
    await _apply(boq, mode="percentage")
    still = await _svc(boq).status(BOQ_ID, None)
    assert still["stale"] is False
    block = await _svc(boq).rule_block(BOQ_ID, await boq.get_boq_with_positions(BOQ_ID), boq.markups)
    assert block["stale"] is False and block["mode"] == "percentage"
    # A real change of mix moves the re-simulated amount away from the line's current value.
    boq.quantity = 900
    moved = await _svc(boq).status(BOQ_ID, None)
    assert moved["drift_amount"] is not None
    assert moved["stale"] == (
        abs(Decimal(moved["drift_amount"])) > rc.money(Decimal(moved["applied"]["line_amount"]) * Decimal("0.01"))
    )


async def test_one_line_switches_between_fixed_and_percentage_and_undo_restores_the_type():
    boq = FakeBoq()
    await _apply(boq, percentile=80)
    assert [m.markup_type for m in boq.markups] == ["fixed"]
    fixed_amount = boq.markups[0].fixed_amount
    await _apply(boq, percentile=90, mode="percentage")
    assert len(boq.markups) == 1 and boq.markups[0].markup_type == "percentage"
    await _apply(boq, percentile=95, mode="fixed")
    assert len(boq.markups) == 1 and boq.markups[0].markup_type == "fixed"
    assert boq.markups[0].metadata_[rc.RUN_KEY]["percentile"] == 95

    out = await _svc(boq).undo(BOQ_ID)
    assert boq.markups[0].markup_type == "percentage" and out["applied"]["mode"] == "percentage"
    assert out["applied"]["percentile"] == 90
    out = await _svc(boq).undo(BOQ_ID)
    assert boq.markups[0].markup_type == "fixed" and out["applied"]["percentile"] == 80
    assert Decimal(boq.markups[0].fixed_amount) == Decimal(fixed_amount)
    await _svc(boq).undo(BOQ_ID)
    assert boq.markups == []


async def test_percentage_that_cannot_be_carried_is_refused():
    with pytest.raises(HTTPException) as err:
        rc.percentage_of(Decimal("10"), Decimal("0"))
    assert err.value.status_code == 422
    with pytest.raises(HTTPException):
        rc.percentage_of(Decimal("200"), Decimal("100"))
    assert rc.percentage_of(Decimal("1"), Decimal("3")) == Decimal("33.3333")


async def test_default_run_params_keep_the_old_behaviour():
    p = rc.RunParams(percentile=80)
    assert (p.source, p.mode) == ("positions", "fixed")
    boq = FakeBoq()
    out = await _apply(boq)
    assert boq.markups[0].markup_type == "fixed"
    assert out["applied"]["source"] == "positions" and out["applied"]["mode"] == "fixed"
    assert "risk_items" not in boq.markups[0].metadata_[rc.RUN_KEY]


def test_export_label_names_the_run():
    meta = {rc.RUN_KEY: {"percentile": 80, "seed": 12345, "source": "positions"}}
    assert rc.export_label("Risk contingency", meta) == "Risk contingency (P80 risk allowance, run 12345)"
    reg = {rc.RUN_KEY: {"percentile": 90, "source": "register", "items_used": 7}}
    assert rc.export_label("Reserve", reg) == "Reserve (P90 from risk register, 7 items)"
    assert rc.export_label("Overhead", {}) == "Overhead"
    assert rc.export_label("Overhead", None) == "Overhead"


async def test_below_p50_rule_fires_only_under_the_estimate():
    rule = RiskContingencyBelowP50()
    block = {"markup_id": "m", "name": "Risk P80", "line_amount": "900.00", "p50_amount": "1000.00"}
    hit = await rule.validate(ValidationContext(data={"risk_contingency": block}))
    assert len(hit) == 1 and hit[0].severity == Severity.INFO
    assert "900.00" in hit[0].message and "1000.00" in hit[0].message
    assert await rule.validate(ValidationContext(data={"risk_contingency": {**block, "line_amount": "1000.00"}})) == []
    assert await rule.validate(ValidationContext(data={"risk_contingency": {**block, "p50_amount": None}})) == []
    assert await rule.validate(ValidationContext(data={})) == []


async def test_double_count_rule_fires_per_manual_contingency_line():
    rule = RiskContingencyDoubleCount()
    block = {"markup_id": "m", "name": "Risk P80", "other_contingency": ["Site contingency"]}
    hit = await rule.validate(ValidationContext(data={"risk_contingency": block}))
    assert len(hit) == 1 and hit[0].severity == Severity.WARNING
    assert "Site contingency" in hit[0].message
    assert await rule.validate(ValidationContext(data={"risk_contingency": {**block, "other_contingency": []}})) == []
    assert await rule.validate(ValidationContext(data={})) == []


async def test_rule_block_lists_manual_contingency_beside_the_risk_line(register):
    boq = FakeBoq()
    await _apply(boq)
    boq.markups.append(
        NS(id=uuid.uuid4(), name="Manual reserve", category="contingency", is_active=True, metadata_={},
           markup_type="percentage", percentage="3", fixed_amount="0", scope_position_id=None, sort_order=5)
    )  # fmt: skip
    boq.markups.append(
        NS(id=uuid.uuid4(), name="Off reserve", category="contingency", is_active=False, metadata_={},
           markup_type="percentage", percentage="3", fixed_amount="0", scope_position_id=None, sort_order=6)
    )  # fmt: skip
    block = await _svc(boq).rule_block(BOQ_ID, await boq.get_boq_with_positions(BOQ_ID), boq.markups)
    assert block["other_contingency"] == ["Manual reserve"]
    assert Decimal(block["p50_amount"]) <= Decimal(block["line_amount"])


async def test_stale_message_names_the_source_that_drifted():
    rule = RiskContingencyFromStaleRun()
    base = {"stale": True, "markup_id": "m", "name": "R", "percentile": 80, "applied_at": "2026-11-02T10:00"}
    reg = await rule.validate(ValidationContext(data={"risk_contingency": {**base, "source": "register"}}))
    pos = await rule.validate(ValidationContext(data={"risk_contingency": {**base, "source": "positions"}}))
    assert "risk register" in reg[0].message
    assert "BOQ line totals" in pos[0].message
