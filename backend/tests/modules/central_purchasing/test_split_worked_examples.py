"""Central purchasing: the three worked examples of the spec (DE, US, UK), pure arithmetic and rules."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.modules.central_purchasing import validators as v
from app.modules.central_purchasing.split import (
    LineIn,
    budget_check,
    document_rate,
    headroom,
    round2,
    share_gaps,
    split_award,
)

P1, P2, P3 = "P1", "P2", "P3"


def _de_lines() -> list[LineIn]:
    return [
        LineIn("L1", "L1", "m2", D("12000"), D("28.50"), {P1: D("5200"), P2: D("2800"), P3: D("4000")}),
        LineIn("L2", "L2", "m2", D("4500"), D("41.20"), {P1: D("2000"), P2: D("1000"), P3: D("1500")}),
    ]


class TestGermanDrywallPerProjectContracts:
    """Example 1: drywall over three projects, 2 % discount, three contracts."""

    def test_shares_are_complete(self) -> None:
        assert share_gaps(_de_lines(), [P1, P2, P3]) == []

    def test_gross_per_project_and_total(self) -> None:
        r = split_award(_de_lines(), [P1, P2, P3], discount_pct=D("2"))
        assert r.cells[("L1", P1)].gross == D("148200.00")
        assert r.cells[("L2", P1)].gross == D("82400.00")
        assert [r.projects[p].gross for p in (P1, P2, P3)] == [D("230600.00"), D("121000.00"), D("175800.00")]
        assert r.gross == D("527400.00")

    def test_net_per_project_reconciles(self) -> None:
        r = split_award(_de_lines(), [P1, P2, P3], discount_pct=D("2"))
        assert [r.projects[p].net for p in (P1, P2, P3)] == [D("225988.00"), D("118580.00"), D("172284.00")]
        assert r.net == D("516852.00") == round2(D("527400.00") * D("0.98"))
        assert r.reconciles

    def test_document_lines_of_a_project_add_up_to_its_net(self) -> None:
        r = split_award(_de_lines(), [P1, P2, P3], discount_pct=D("2"))
        for p in (P1, P2, P3):
            assert r.cells[("L1", p)].net + r.cells[("L2", p)].net == r.projects[p].net

    def test_p2_over_budget_by_6580(self) -> None:
        r = split_award(_de_lines(), [P1, P2, P3], discount_pct=D("2"))
        check = budget_check(r.projects[P2].net, D("112000.00"))
        assert check.over
        assert check.delta == D("6580.00")
        found = v.project_over_budget(
            {"currency": "EUR", "projects": [{"name": "P2", "net": "118580.00", "budget": "112000.00"}]}
        )
        assert len(found) == 1
        assert found[0][1]["project"] == "P2"
        assert "6,580" in found[0][1]["delta"]

    def test_within_tolerance_does_not_warn(self) -> None:
        assert not budget_check(D("118580.00"), D("112000.00"), D("6")).over


class TestUsReadyMixFramework:
    """Example 2: supply, framework call-off, one entity."""

    lines = [
        LineIn("C", "concrete", "CY", D("3000"), D("168.00"), {"TX-118": D("1800"), "TX-122": D("1200")}),
        LineIn("P", "pump", "CY", D("3000"), D("14.50"), {"TX-118": D("1800"), "TX-122": D("1200")}),
    ]

    def test_cap_is_the_awarded_net(self) -> None:
        r = split_award(self.lines, ["TX-118", "TX-122"])
        assert r.net == D("547500.00") == D("3000") * D("182.50")

    def test_call_off_tx118_240_cy(self) -> None:
        r = split_award(self.lines, ["TX-118", "TX-122"])
        concrete = round2(D("240") * document_rate(D("168.00"), r.factor))
        pump = round2(D("240") * document_rate(D("14.50"), r.factor))
        assert (concrete, pump, concrete + pump) == (D("40320.00"), D("3480.00"), D("43800.00"))

    def test_tx122_called_off_past_its_share(self) -> None:
        assert round2(D("150") * D("168.00")) + round2(D("150") * D("14.50")) == D("27375.00")
        used = D("1100") + D("150")
        assert headroom(D("1200"), used) == D("-50")
        found = v.calloff_over_share(
            {
                "call_off": {
                    "project": "TX-122",
                    "in_bundle": True,
                    "lines": [{"code": "concrete", "unit": "CY", "used": str(used), "share": "1200"}],
                }
            }
        )
        assert found == [
            (
                "line:concrete",
                {"project": "TX-122", "used": "1,250", "share": "1,200", "unit": "CY", "code": "concrete"},
            )
        ]

    def test_project_outside_the_bundle_is_refused(self) -> None:
        found = v.calloff_project_not_in_bundle({"call_off": {"project": "TX-999", "in_bundle": False}})
        assert found == [("project:TX-999", {"project": "TX-999"})]


class TestUkCableContainmentLumpSum:
    """Example 3: two entities, a blank share first, then a lump sum."""

    def _lines(self, pb_trunking: D | None) -> list[LineIn]:
        return [
            LineIn("L1", "L1", "m", D("2400"), D("18.40"), {"P-A": D("1500"), "P-B": D("900")}),
            LineIn("L2", "L2", "m", D("1100"), D("9.85"), {"P-A": D("600"), "P-B": pb_trunking}),
        ]

    def test_blank_share_blocks_the_award(self) -> None:
        gaps = share_gaps(self._lines(None), ["P-A", "P-B"])
        assert [(g.kind, g.line_code, g.project) for g in gaps if g.kind == "missing"] == [("missing", "L2", "P-B")]
        mismatch = next(g for g in gaps if g.kind == "mismatch")
        assert (mismatch.total, mismatch.quantity) == (D("600"), D("1100"))
        payload = {
            "lines": [
                {
                    "code": "L2",
                    "quantity": "1100",
                    "shares": [{"project": "P-A", "quantity": "600"}, {"project": "P-B", "quantity": None}],
                }
            ]
        }
        assert v.project_share_missing(payload) == [("line:L2", {"code": "L2", "project": "P-B"})]
        assert v.share_sum_mismatch(payload) == [("line:L2", {"code": "L2", "sum": "600", "qty": "1,100"})]

    def test_lump_sum_split_remainder_to_last_cell(self) -> None:
        r = split_award(self._lines(D("500")), ["P-A", "P-B"], lump_sum=D("52000.00"))
        grosses = [r.cells[k].gross for k in (("L1", "P-A"), ("L1", "P-B"), ("L2", "P-A"), ("L2", "P-B"))]
        assert grosses == [D("27600.00"), D("16560.00"), D("5910.00"), D("4925.00")]
        assert r.gross == D("54995.00")
        nets = [r.cells[k].net for k in (("L1", "P-A"), ("L1", "P-B"), ("L2", "P-A"), ("L2", "P-B"))]
        assert nets == [D("26096.92"), D("15658.15"), D("5588.14"), D("4656.79")]
        assert r.projects["P-A"].net == D("31685.06")
        assert r.projects["P-B"].net == D("20314.94")
        assert r.net == D("52000.00")
        assert r.reconciles


class TestRuleEdges:
    def test_zero_share_is_an_answer_not_a_gap(self) -> None:
        lines = [LineIn("L", "L", "m", D("10"), D("1"), {"A": D("10"), "B": D("0")})]
        assert share_gaps(lines, ["A", "B"]) == []

    def test_cost_line_missing_only_for_a_real_share(self) -> None:
        payload = {
            "lines": [
                {
                    "code": "L",
                    "shares": [
                        {"project": "A", "quantity": "10", "cost_line_id": None},
                        {"project": "B", "quantity": "0", "cost_line_id": None},
                    ],
                }
            ]
        }
        assert v.share_cost_line_missing(payload) == [("line:L", {"code": "L", "project": "A"})]

    def test_entity_missing_only_when_entities_are_in_use(self) -> None:
        projects = [{"name": "P2", "legal_entity_id": None}]
        assert v.entity_missing({"projects": projects}) == []
        assert v.entity_missing({"entities_exist": True, "projects": projects}) == [("project:P2", {"project": "P2"})]

    def test_unreconciled_award(self) -> None:
        found = v.award_split_unreconciled({"currency": "EUR", "award": {"total": "100.00", "split_sum": "99.99"}})
        assert len(found) == 1
        assert v.award_split_unreconciled({"award": {"total": "100.00", "split_sum": "100.00"}}) == []

    @pytest.mark.parametrize("pct", ["0", "2", "3.5", "12.125"])
    def test_discount_split_always_reconciles(self, pct: str) -> None:
        lines = [
            LineIn("A", "A", "m", D("3"), D("0.335"), {"x": D("1"), "y": D("1"), "z": D("1")}),
            LineIn("B", "B", "m", D("7.5"), D("19.99"), {"x": D("2.5"), "y": D("2.5"), "z": D("2.5")}),
        ]
        r = split_award(lines, ["x", "y", "z"], discount_pct=D(pct))
        assert r.reconciles
        for p in ("x", "y", "z"):
            assert r.cells[("A", p)].net + r.cells[("B", p)].net == r.projects[p].net

    def test_every_rule_has_messages_in_every_locale(self) -> None:
        from app.core.validation.messages import available_locales, is_key_present

        locales = available_locales()
        assert "de" in locales
        for key, *_ in v.CHECKS:
            for loc in locales:
                assert is_key_present(f"bundle.{key}.fail", loc), (key, loc)
                assert is_key_present(f"bundle.{key}.suggestion", loc), (key, loc)
