# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Contracts of the plant register that need no database.

Each test pins one way the module once let something through: a write route
that took the clock from the caller, a subscription to an event nobody
publishes, a state assigned around the state machine, an error code with no
message, a null stored in a column that cannot hold one, a slot fee bound on
the strength of an id.
"""

from __future__ import annotations

import ast
import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.plant_register import calc
from app.modules.plant_register.errors import PlantError
from app.modules.plant_register.fsm import ITEM_FSM, MANUAL_TARGETS, READ_STATES
from app.modules.plant_register.ports import CommitmentRef
from app.modules.plant_register.schemas import (
    ItemCreate,
    ItemUpdate,
    ItServiceIn,
    PaperIn,
    PaperOption,
    SlotIn,
    SpareIn,
)
from app.modules.plant_register.service import PlantService

_MODULE = Path(__file__).resolve().parents[2] / "app" / "modules" / "plant_register"

# ── the clock belongs to the server ───────────────────────────────────────


def test_no_write_route_takes_a_date_from_the_caller() -> None:
    from app.modules.plant_register.router import router

    writes = [r for r in router.routes if getattr(r, "methods", set()) & {"POST", "PUT", "PATCH", "DELETE"}]
    assert len(writes) > 20, "the scan found too few write routes to mean anything"
    offenders = [
        f"{sorted(r.methods)} {r.path}" for r in writes if any(p.name == "today" for p in r.dependant.query_params)
    ]
    assert offenders == []


def test_read_routes_still_offer_today() -> None:
    from app.modules.plant_register.router import router

    reads = {r.path for r in router.routes if "GET" in getattr(r, "methods", set())}
    with_today = {
        r.path
        for r in router.routes
        if "GET" in getattr(r, "methods", set()) and any(p.name == "today" for p in r.dependant.query_params)
    }
    assert {"/projects/{project_id}/items", "/projects/{project_id}/readiness"} <= with_today <= reads


# ── events that exist ─────────────────────────────────────────────────────


def test_every_subscribed_procurement_event_is_one_procurement_publishes() -> None:
    from app.modules.plant_register.events import PO_EVENTS
    from app.modules.procurement.events import PUBLISHED_EVENTS

    assert set(PO_EVENTS) <= set(PUBLISHED_EVENTS)
    # The goods receipt is what delivers; cancel and revert are what take an order away.
    assert {"procurement.gr.confirmed", "procurement.po.cancelled", "procurement.po.reverted"} <= set(PO_EVENTS)


def test_the_goods_receipt_event_carries_the_key_the_handler_reads() -> None:
    source = (_MODULE.parent / "procurement" / "service.py").read_text(encoding="utf-8")
    at = source.index('"procurement.gr.confirmed"')
    assert '"po_id"' in source[at : at + 300]


# ── the state machine is the only way to move ─────────────────────────────


def _status_assignments(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute) and target.attr == "status"
    ]


def test_the_service_never_assigns_a_status_around_the_fsm() -> None:
    assert _status_assignments(_MODULE / "service.py") == []
    assert _status_assignments(_MODULE / "sweeper.py") == []


def test_a_read_state_can_move_to_every_other_read_state() -> None:
    for a in (*READ_STATES, "manufactured"):
        for b in READ_STATES:
            if a != b:
                assert ITEM_FSM.has_transition(a, b), (a, b)


def test_a_reading_cannot_reach_states_that_are_acts() -> None:
    assert not ITEM_FSM.has_transition("route_set", "handed_over")
    assert not ITEM_FSM.has_transition("handed_over", "route_set")
    assert not ITEM_FSM.has_transition("cancelled", "route_set")
    assert "ordered" not in MANUAL_TARGETS and "delivered" not in MANUAL_TARGETS


def test_transitions_are_audited_once() -> None:
    """``fsm.apply`` writes the audit row of a transition; a second ``_audit`` with states duplicated it."""
    tree = ast.parse((_MODULE / "service.py").read_text(encoding="utf-8"))
    doubled = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_audit"
        and any(kw.arg == "from_status" for kw in node.keywords)
    ]
    assert doubled == []


# ── every refusal has a code with a message ───────────────────────────────

_RAISERS = {"PlantError", "conflict", "forbidden", "not_found"}


def _constants(node: ast.AST) -> list[str]:
    elts = node.elts if isinstance(node, ast.List | ast.Tuple) else [node]
    return [str(e.value).split(":")[0] for e in elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _codes_in(path: Path) -> set[str]:
    """Every error code a file can produce: raised directly, listed as a blocker, or returned by a rule."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in _RAISERS:
                codes.update(_constants(node.args[0])[:1])
            elif name in {"blocked", "append"}:
                codes.update(_constants(node.args[0]))
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.List):
            for element in node.value.elts:
                if not isinstance(element, ast.Starred):
                    codes.update(_constants(element))
    return {c for c in codes if c and c.replace("_", "").isalpha() and c.islower() and "_" in c}


def _leaves(node: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        out |= _leaves(value, path) if isinstance(value, dict) else {path}
    return out


@pytest.mark.parametrize("locale", sorted(p.stem for p in (_MODULE / "messages").glob("*.json")))
def test_every_error_code_has_a_message_in_every_shipped_locale(locale: str) -> None:
    codes: set[str] = set()
    for name in ("service.py", "router.py", "calc.py"):
        codes |= _codes_in(_MODULE / name)
    assert len(codes) > 80, "the scan found too few codes to mean anything"
    assert {"commitment_release_unavailable", "null_not_allowed", "lead_time_without_enquiry_date"} <= codes
    keys = _leaves(json.loads((_MODULE / "messages" / f"{locale}.json").read_text(encoding="utf-8")))
    assert sorted(c for c in codes if f"plant.errors.{c}" not in keys) == []


# ── an explicit null is a 422 unless the field can be cleared ─────────────


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (SpareIn, {"description": None}),
        (SpareIn, {"quantity": None}),
        (SpareIn, {"unit": None}),
        (SpareIn, {"supply_by": None}),
        (SpareIn, {"handover_target": None}),
        (SlotIn, {"fee_credited_to_order": None}),
        (SlotIn, {"currency": None}),
        (SlotIn, {"terms": None}),
        (ItServiceIn, {"description": None}),
        (ItServiceIn, {"responsible_party": None}),
        (ItServiceIn, {"access_roles": None}),
        (ItemUpdate, {"title": None}),
        (ItemUpdate, {"quantity": None}),
        (ItemUpdate, {"order_buffers": None}),
        (PaperIn, {"options": None}),
        (PaperIn, {"rationale": None}),
    ],
)
def test_a_null_on_a_field_that_cannot_be_null_is_refused_by_the_schema(model, body) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(body)


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (SpareIn, {"supply_package_id": None}),
        (SlotIn, {"reservation_fee": None, "convert_by_date": None, "commitment_item_id": None}),
        (ItServiceIn, {"needed_from": None, "cde_container_id": None}),
        (ItemUpdate, {"purchase_order_id": None, "owner_user_id": None, "critical_override": None}),
    ],
)
def test_a_null_clears_a_field_that_can_be_cleared(model, body) -> None:
    assert model.model_validate(body).model_dump(exclude_unset=True) == body


def test_item_changes_keep_the_null_that_clears_a_link() -> None:
    assert ItemUpdate.model_validate({"purchase_order_id": None}).changes() == {"purchase_order_id": None}
    assert ItemCreate.model_validate({"code": "A", "title": "T", "component_class_code": "lift"}).changes() == {
        "code": "A",
        "title": "T",
        "component_class_code": "lift",
    }


def test_the_service_refuses_a_null_too() -> None:
    row = SimpleNamespace(description="x", supply_package_id=uuid.uuid4())
    with pytest.raises(PlantError) as exc:
        PlantService._apply(row, {"description": None}, ("description",), {"supply_package_id"})
    assert (exc.value.code, exc.value.detail, row.description) == ("null_not_allowed", "description", "x")
    PlantService._apply(row, {"supply_package_id": None}, ("supply_package_id",), {"supply_package_id"})
    assert row.supply_package_id is None


# ── numbers fit their columns ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("model", "body"),
    [
        (ItemUpdate, {"quantity": "1.2345"}),
        (ItemUpdate, {"quantity": "1" + "0" * 16}),
        (SpareIn, {"quantity": "0"}),
        (SpareIn, {"quantity": "-1"}),
        (SlotIn, {"reservation_fee": "-0.01"}),
        (SlotIn, {"reservation_fee": "1.001"}),
        (PaperOption, {"code": "a", "cost": "1.001"}),
        (PaperOption, {"code": "a", "cost": "-1"}),
        (PaperOption, {"code": "a", "cost": 1.5}),
    ],
)
def test_a_number_that_does_not_fit_its_column_is_refused(model, body) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(body)


def _slot(**kw):
    base = {"fee_refundable": "none", "reservation_fee": None, "currency": "", "slot_from": None, "slot_to": None}
    return SimpleNamespace(**{**base, **kw})


def test_a_fee_without_a_currency_is_refused_in_every_slot_state() -> None:
    with pytest.raises(PlantError) as exc:
        PlantService._check_slot(_slot(reservation_fee=Decimal("0.00")))
    assert exc.value.code == "fee_needs_currency"
    PlantService._check_slot(_slot(reservation_fee=Decimal("10.00"), currency="USD"))
    PlantService._check_slot(_slot())


def test_an_option_cost_without_a_currency_is_refused() -> None:
    paper = SimpleNamespace(
        options=[{"code": "a", "cost": "10.00"}, {"code": "b"}], criteria=[], recommendation="", rationale=""
    )
    with pytest.raises(PlantError) as exc:
        PlantService._check_paper_body(paper)
    assert exc.value.code == "cost_needs_currency"
    paper.options[0]["currency"] = "USD"
    PlantService._check_paper_body(paper)


# ── rule 13: money binds only through a released commitment ───────────────

_ITEM = uuid.uuid4()


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (None, ["commitment_not_found"]),
        (CommitmentRef(uuid.uuid4(), released=False), ["commitment_not_released"]),
        (CommitmentRef(uuid.uuid4(), released=True, plant_item_id=uuid.uuid4()), ["commitment_for_other_item"]),
        (CommitmentRef(uuid.uuid4(), released=True, currency="USD"), ["commitment_currency_mismatch"]),
        (
            CommitmentRef(uuid.uuid4(), released=True, released_amount=Decimal("24999.99"), currency="EUR"),
            ["commitment_release_below_fee"],
        ),
        (CommitmentRef(uuid.uuid4(), released=True, released_amount=Decimal("25000.00"), currency="EUR"), []),
        (CommitmentRef(uuid.uuid4(), released=True, plant_item_id=_ITEM), []),
    ],
)
def test_commitment_errors(ref, expected) -> None:
    assert calc.commitment_errors(ref, _ITEM, Decimal("25000.00"), "EUR") == expected


# ── readiness (SPEC 7) ────────────────────────────────────────────────────


def _row(code: str, **kw) -> dict:
    base = {
        "code": code,
        "status": "enquired",
        "critical": False,
        "long_lead": True,
        "basis_count": 1,
        "quote_stale": False,
        "order_status": "ok",
        "latest_order_date": "2027-01-01",
        "paper_status": None,
    }
    return {**base, **kw}


def test_a_long_lead_item_with_no_order_date_is_not_secured() -> None:
    rows = [
        _row("NO-DATE", latest_order_date=None),
        _row("NO-DATE-ORDERED", latest_order_date=None, status="ordered"),
        _row("OVERDUE", order_status="overdue"),
        _row("OVERDUE-ORDERED", order_status="ok", status="delivered"),
        _row("STALE", quote_stale=True),
        _row("TWO-BASIS", basis_count=2),
        _row("FINE"),
        _row("SHORT", long_lead=False, latest_order_date=None),
    ]
    assert calc.long_lead_open(rows) == ["NO-DATE", "OVERDUE", "STALE", "TWO-BASIS"]


def test_critical_items_need_a_route_and_an_approved_paper() -> None:
    rows = [
        _row("NO-ROUTE", critical=True, paper_status="approved"),
        _row("NO-PAPER", critical=True, status="route_set", paper_status="submitted"),
        _row("OK", critical=True, status="ordered", paper_status="approved"),
        _row("PLAIN", critical=False),
    ]
    assert calc.critical_open(rows) == ["NO-ROUTE", "NO-PAPER"]


# ── the periodic job is a declared process ────────────────────────────────


def test_the_sweeper_is_registered_as_a_process() -> None:
    from app.core.processes import process_registry
    from app.modules.plant_register.sweeper import PROCESS_ID, register_plant_sweeper

    register_plant_sweeper()
    register_plant_sweeper()
    assert process_registry.ids().count(PROCESS_ID) == 1
