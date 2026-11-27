# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests - requisition approval routed on value.

Worked example: bands ``5 000 EUR -> [PM]`` and ``50 000 EUR -> [Director]``.
Concrete 71.4 m3 at 95.50 EUR is 6 818.70 EUR and goes to the PM; 72 000 EUR
goes to the PM, then the Director; 4 999.99 EUR keeps the one-step approval.
Each check is shown failing on its case and passing on its neighbour.

Pure-Python, no database.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.validation.engine import Severity, ValidationContext
from app.core.validation.rules import (
    ProcurementRequisitionUnpricedUnderBands,
    ProcurementRequisitionValueBandCurrency,
)
from app.modules.procurement import validators as po_checks
from app.modules.procurement.approval_bands import (
    Band,
    BandError,
    banded_chain,
    parse_bands,
    requisition_value,
    role_of,
)
from app.modules.procurement.models import MaterialRequisition
from app.modules.procurement.permissions import register_procurement_permissions
from app.modules.procurement.requisition_service import (
    APPROVAL_VALUE_KEY,
    RequisitionWorkflowService,
    ResponseContext,
    _approval_view,
)

PM = "00000000-0000-4000-8000-0000000000a1"
DIRECTOR = "00000000-0000-4000-8000-0000000000a2"
BUYER = "00000000-0000-4000-8000-0000000000a3"
REQUESTER = "00000000-0000-4000-8000-0000000000a4"

BANDS = [Band(Decimal("5000"), (PM,)), Band(Decimal("50000"), (DIRECTOR,))]


class TestWorkedExample:
    def test_the_concrete_requisition_is_worth_its_priced_lines(self) -> None:
        value = requisition_value([Decimal("71.4") * Decimal("95.50"), Decimal("0"), None, ""])
        assert value == Decimal("6818.700")

    def test_above_the_first_band_the_pm_approves(self) -> None:
        out = banded_chain([], BANDS, Decimal("6818.70"), excluded={REQUESTER})
        assert out.chain == [PM]
        assert out.added == {PM: "5000"}
        assert out.applied == ["5000"]
        assert out.unmet == []

    def test_above_both_bands_the_pm_then_the_director_approve_after_the_buyer(self) -> None:
        out = banded_chain([BUYER], BANDS, Decimal("72000"), excluded={REQUESTER})
        assert out.chain == [BUYER, PM, DIRECTOR]
        assert out.added == {PM: "5000", DIRECTOR: "50000"}

    def test_below_the_first_band_nothing_is_added(self) -> None:
        out = banded_chain([], BANDS, Decimal("4999.99"), excluded={REQUESTER})
        assert out.chain == [] and out.applied == []

    def test_a_band_starts_at_its_amount_inclusive(self) -> None:
        assert banded_chain([], BANDS, Decimal("5000.00"), excluded=()).chain == [PM]

    def test_an_approver_already_designated_is_not_added_twice(self) -> None:
        out = banded_chain([PM], BANDS, Decimal("6818.70"), excluded=())
        assert out.chain == [PM]
        assert out.added == {}

    def test_the_requester_is_never_their_own_band_approver(self) -> None:
        bands = [Band(Decimal("5000"), (PM, DIRECTOR))]
        out = banded_chain([], bands, Decimal("6000"), excluded={PM})
        assert out.chain == [DIRECTOR]

    def test_a_band_left_without_anyone_else_is_unmet(self) -> None:
        out = banded_chain([BUYER], BANDS, Decimal("72000"), excluded={DIRECTOR})
        assert out.unmet == ["50000"]


class TestParse:
    def test_stored_bands_parse_in_order(self) -> None:
        bands = parse_bands(
            [{"from_amount": "5000", "approvers": [PM]}, {"from_amount": "50000.00", "approvers": [DIRECTOR]}]
        )
        assert [b.from_amount for b in bands] == [Decimal("5000"), Decimal("50000.00")]

    @pytest.mark.parametrize(
        ("raw", "code"),
        [
            ([{"from_amount": "0", "approvers": [PM]}], "band_amount_not_positive"),
            ([{"from_amount": "abc", "approvers": [PM]}], "band_amount_invalid"),
            ([{"from_amount": "5000", "approvers": []}], "band_approvers_count"),
            (
                [{"from_amount": "5000", "approvers": [PM]}, {"from_amount": "5000", "approvers": [DIRECTOR]}],
                "band_amounts_not_ascending",
            ),
            (
                [{"from_amount": "5000", "approvers": [PM]}, {"from_amount": "9000", "approvers": [PM]}],
                "band_approver_repeated",
            ),
        ],
    )
    def test_an_ambiguous_band_list_is_refused(self, raw: list[dict[str, Any]], code: str) -> None:
        with pytest.raises(BandError) as err:
            parse_bands(raw)
        assert err.value.code == code


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "req_number": "MR-0012",
        "operation": "submit",
        "value_bands": {"currency": "EUR", "from_amounts": ["5000", "50000"]},
        "items": [
            {"description": "Concrete C30/37", "currency_code": "EUR", "extended_cost": "6818.700", "sources": []},
            {"description": "Rebar B500", "currency_code": "", "extended_cost": "0", "sources": []},
        ],
    }
    payload.update(overrides)
    return payload


class TestRules:
    def test_a_line_in_the_band_currency_passes(self) -> None:
        assert po_checks.check_requisition_value_band_currency(_payload()) == []

    def test_a_line_priced_in_another_currency_fails(self) -> None:
        items = [{"description": "Formwork", "currency_code": "usd", "extended_cost": "900", "sources": []}]
        findings = po_checks.check_requisition_value_band_currency(_payload(items=items))
        assert len(findings) == 1
        assert findings[0].params["currency"] == "USD"
        assert findings[0].params["band_currency"] == "EUR"

    def test_without_bands_neither_value_rule_speaks(self) -> None:
        items = [{"description": "Formwork", "currency_code": "USD", "extended_cost": "0", "sources": []}]
        assert po_checks.check_requisition_value_band_currency(_payload(value_bands=None, items=items)) == []
        assert po_checks.check_requisition_unpriced_under_bands(_payload(value_bands=None, items=items)) == []

    def test_the_unpriced_rebar_line_is_flagged(self) -> None:
        findings = po_checks.check_requisition_unpriced_under_bands(_payload())
        assert [f.params["line"] for f in findings] == [findings[0].element_ref]
        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_the_registered_rules_report_through_the_engine(self) -> None:
        ctx = ValidationContext(data=_payload(), metadata={"locale": "en"})
        currency = await ProcurementRequisitionValueBandCurrency().validate(ctx)
        unpriced = await ProcurementRequisitionUnpricedUnderBands().validate(ctx)
        assert [r.passed for r in currency] == [True]
        assert [(r.passed, r.severity) for r in unpriced] == [(False, Severity.WARNING)]
        assert "zero" in unpriced[0].message


def test_the_approval_view_names_the_band_that_added_an_approver() -> None:
    req = MaterialRequisition(status="submitted", approval_chain=[BUYER, PM], approval_step=0)
    req.metadata_ = {APPROVAL_VALUE_KEY: {"value": "6818.700", "currency": "EUR", "added": {PM: "5000"}}}
    steps = _approval_view(req, ResponseContext())
    assert [(s.user_id, s.band_from) for s in steps] == [(BUYER, None), (PM, "5000")]


class TestRoleApprovers:
    """A band may name a role, as a purchase order approval route step can."""

    def test_a_role_band_adds_a_role_step_after_its_people(self) -> None:
        bands = parse_bands(
            [
                {"from_amount": "5000", "approvers": [PM]},
                {"from_amount": "50000", "approvers": [], "roles": ["Manager"]},
            ]
        )
        assert bands[1].approvers == ("role:manager",)
        out = banded_chain([BUYER], bands, Decimal("72000"), excluded={REQUESTER})
        assert out.chain == [BUYER, PM, "role:manager"]
        assert out.added == {PM: "5000", "role:manager": "50000"}
        assert role_of(out.chain[2]) == "manager"
        assert role_of(PM) is None

    def test_a_role_band_is_never_unmet_by_the_requester(self) -> None:
        bands = parse_bands([{"from_amount": "5000", "approvers": [REQUESTER], "roles": ["manager"]}])
        out = banded_chain([], bands, Decimal("6818.70"), excluded={REQUESTER})
        assert out.chain == ["role:manager"]
        assert out.unmet == []

    def test_a_role_in_two_bands_is_refused(self) -> None:
        with pytest.raises(BandError) as err:
            parse_bands(
                [
                    {"from_amount": "5000", "roles": ["manager"]},
                    {"from_amount": "50000", "roles": ["manager"]},
                ]
            )
        assert err.value.code == "band_approver_repeated"

    def test_a_band_counts_people_and_roles_together(self) -> None:
        five = [f"00000000-0000-4000-8000-00000000010{n}" for n in range(5)]
        with pytest.raises(BandError) as err:
            parse_bands([{"from_amount": "5000", "approvers": five, "roles": ["manager"]}])
        assert err.value.code == "band_approvers_count"
        with pytest.raises(BandError) as err:
            parse_bands([{"from_amount": "5000", "roles": [" "]}])
        assert err.value.code == "band_role_invalid"

    def test_settings_accept_roles_that_may_approve_and_refuse_the_rest(self) -> None:
        register_procurement_permissions()
        assert RequisitionWorkflowService._validated_roles([" Manager", "admin"]) == ["manager", "admin"]
        for bad in (["viewer"], ["editor"], ["no_such_role"], ["manager", "manager"]):
            with pytest.raises(HTTPException) as err:
                RequisitionWorkflowService._validated_roles(bad)
            assert err.value.status_code == 422

    @pytest.mark.parametrize(
        ("actor", "role", "allowed"),
        [
            (PM, "manager", True),
            (PM, "admin", True),
            (PM, "editor", False),
            (REQUESTER, "manager", False),
            (BUYER, "manager", False),
        ],
    )
    async def test_a_role_step_is_decided_by_a_holder_other_than_the_requester_or_an_earlier_approver(
        self, actor: str, role: str, allowed: bool
    ) -> None:
        req = MaterialRequisition(
            status="submitted", approval_chain=[BUYER, "role:manager"], approval_step=1, requester_id=REQUESTER
        )
        req.metadata_ = {"approval_round": [{"user_id": BUYER, "step": 1}]}
        service = RequisitionWorkflowService.__new__(RequisitionWorkflowService)

        async def actor_role(_user_id: str | None) -> str:
            return role

        service._actor_role = actor_role  # type: ignore[method-assign]
        if allowed:
            await service._assert_designated(req, actor, "approve")
        else:
            with pytest.raises(HTTPException) as err:
                await service._assert_designated(req, actor, "approve")
            assert err.value.status_code == 403

    def test_the_view_shows_who_decided_a_role_step_and_the_role_still_open(self) -> None:
        req = MaterialRequisition(
            status="submitted", approval_chain=["role:manager", "role:admin"], approval_step=1, requester_id=REQUESTER
        )
        req.metadata_ = {
            "approval_round": [{"user_id": PM, "step": 1, "at": "2026-11-27T10:00:00+00:00"}],
            APPROVAL_VALUE_KEY: {"currency": "EUR", "added": {"role:manager": "5000", "role:admin": "50000"}},
        }
        steps = _approval_view(req, ResponseContext(user_names={PM: "Project manager"}))
        assert [(s.role, s.name, s.state, s.band_from) for s in steps] == [
            ("manager", "Project manager", "approved", "5000"),
            ("admin", None, "next", "50000"),
        ]
