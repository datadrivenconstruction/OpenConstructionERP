"""Budget ledger: the three rules, the draft -> approved path, and who may do what.

The service runs against a fake session and stubbed figures, so no database is needed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.validation.engine import ValidationContext, rule_registry
from app.dependencies import RequirePermission
from app.modules.costmodel import budget_ledger_service as svc_mod
from app.modules.costmodel.budget_ledger_models import BudgetLedgerAudit, BudgetModification, BudgetTransfer
from app.modules.costmodel.budget_ledger_router import router
from app.modules.costmodel.budget_ledger_rules import PAYLOAD_KEY, RULE_SET
from app.modules.costmodel.budget_ledger_schemas import LegIn, ModificationIn, TransferIn
from app.modules.costmodel.budget_ledger_service import BudgetLedgerService
from app.modules.costmodel.validators import register_costmodel_validation_rules

D = Decimal
PROJECT = uuid.uuid4()
WALLS, ROOF, SLAB = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
CODES = {str(WALLS): "331", str(ROOF): "360", str(SLAB): "320"}
BUDGET = {str(WALLS): D("10000"), str(ROOF): D("5000"), str(SLAB): D("2000")}
COMMITTED = {str(WALLS): D("7000"), str(ROOF): D("0"), str(SLAB): D("0")}

register_costmodel_validation_rules()


async def _run(payload: dict) -> dict[str, list]:
    ctx = ValidationContext(data={PAYLOAD_KEY: payload}, project_id=str(PROJECT), metadata={"locale": "en"})
    out: dict[str, list] = {}
    for rule in rule_registry.get_rules_for_sets([RULE_SET]):
        out[rule.rule_id] = [r for r in await rule.validate(ctx) if not r.passed]
    return out


def _leg(line: uuid.UUID, amount: str, budget: str = "10000", committed: str = "0") -> dict:
    return {
        "cost_line_id": str(line),
        "code": CODES[str(line)],
        "amount": amount,
        "budget": budget,
        "committed": committed,
    }


# ── rules ─────────────────────────────────────────────────────────────────


async def test_balanced_transfer_passes_every_rule():
    found = await _run({"kind": "transfer", "action": "create", "legs": [_leg(WALLS, "-500"), _leg(ROOF, "500")]})
    assert not any(found.values())


@pytest.mark.parametrize(
    "legs",
    [
        [_leg(WALLS, "-500"), _leg(ROOF, "400")],
        [_leg(WALLS, "-500")],
        [_leg(WALLS, "-500"), _leg(WALLS, "500")],
        [_leg(WALLS, "0"), _leg(ROOF, "0")],
    ],
)
async def test_transfer_that_does_not_net_to_zero_is_refused(legs):
    found = await _run({"kind": "transfer", "action": "create", "legs": legs})
    assert found["budget_ledger.net_zero"]


async def test_taking_a_line_below_committed_is_refused():
    legs = [_leg(WALLS, "-4000", budget="10000", committed="7000"), _leg(ROOF, "4000")]
    found = await _run({"kind": "transfer", "action": "create", "legs": legs})
    assert [r.element_ref for r in found["budget_ledger.below_committed"]] == [str(WALLS)]
    assert "331" in found["budget_ledger.below_committed"][0].message


async def test_reduction_down_to_committed_is_allowed():
    legs = [_leg(WALLS, "-3000", budget="10000", committed="7000"), _leg(ROOF, "3000")]
    assert not (await _run({"kind": "transfer", "action": "create", "legs": legs}))["budget_ledger.below_committed"]


@pytest.mark.parametrize("state", ["approved", "rejected"])
@pytest.mark.parametrize("action", ["edit", "delete"])
async def test_decided_entry_is_immutable(state, action):
    found = await _run({"kind": "transfer", "action": action, "guard": True, "status": state, "code": "BT-001"})
    assert found["budget_ledger.approved_immutable"]
    assert not found["budget_ledger.net_zero"]


async def test_draft_can_be_edited():
    found = await _run({"kind": "transfer", "action": "edit", "guard": True, "status": "draft", "code": "BT-001"})
    assert not any(found.values())


async def test_rules_ignore_other_payloads():
    ctx = ValidationContext(data={"something_else": {}}, project_id=str(PROJECT))
    for rule in rule_registry.get_rules_for_sets([RULE_SET]):
        assert await rule.validate(ctx) == []


def test_rule_messages_exist_in_english():
    from app.core.validation.messages import is_key_present

    for key in ("net_zero", "below_committed", "approved_immutable"):
        assert is_key_present(f"budget_ledger.{key}.fail", "en")
        assert is_key_present(f"budget_ledger.{key}.suggestion", "en")


# ── service ───────────────────────────────────────────────────────────────


class _Rows:
    def all(self):
        return []

    def scalars(self):
        return iter(())


class _Nested:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc) -> bool:
        return False


class FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.deleted: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def begin_nested(self):
        return _Nested()

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def execute(self, *_a, **_k):
        return _Rows()

    async def get(self, _model, _id):
        return None


@pytest.fixture
def service(monkeypatch):
    s = BudgetLedgerService(FakeSession())  # type: ignore[arg-type]
    store: dict[uuid.UUID, object] = {}

    async def spine(_project):
        return None, "EUR", dict(BUDGET), dict(COMMITTED)

    async def codes(_project):
        return CODES

    async def delta(_session, _project):
        return {}

    async def legs(transfer_id):
        return [g for g in s.session.added if getattr(g, "transfer_id", None) == transfer_id]

    async def get(_model, _project, entry_id):
        return store[entry_id]

    monkeypatch.setattr(s, "_spine", spine)
    monkeypatch.setattr(s, "_codes", codes)
    monkeypatch.setattr(s, "_legs", legs)
    monkeypatch.setattr(s, "_get", get)
    monkeypatch.setattr(svc_mod, "approved_budget_delta", delta)
    s.store = store  # type: ignore[attr-defined]
    return s


def _audits(s) -> list[BudgetLedgerAudit]:
    return [o for o in s.session.added if isinstance(o, BudgetLedgerAudit)]


async def _draft(s, amount="500") -> BudgetTransfer:
    out = await s.create_transfer(
        PROJECT,
        TransferIn(
            reason="Walls over, roof under",
            legs=[LegIn(cost_line_id=WALLS, amount=D(f"-{amount}")), LegIn(cost_line_id=ROOF, amount=D(amount))],
        ),
        "u1",
        "en",
    )
    transfer = next(o for o in s.session.added if isinstance(o, BudgetTransfer))
    s.store[transfer.id] = transfer
    assert out.status == "draft" and out.code == "BT-001" and out.moved == D(amount)
    return transfer


async def test_transfer_goes_draft_submitted_approved_with_audit(service):
    t = await _draft(service)
    await service.transfer_step(PROJECT, t.id, "submit", "u1", "", "en")
    out = await service.transfer_step(PROJECT, t.id, "approve", "boss", "", "en")
    assert out.status == "approved" and t.decided_by == "boss"
    assert [a.action for a in _audits(service)] == ["create", "submit", "approve"]


async def test_unbalanced_transfer_is_refused_with_the_rule_message(service):
    body = TransferIn(
        reason="x", legs=[LegIn(cost_line_id=WALLS, amount=D("-500")), LegIn(cost_line_id=ROOF, amount=D("300"))]
    )
    with pytest.raises(HTTPException) as err:
        await service.create_transfer(PROJECT, body, "u1", "en")
    assert err.value.status_code == 422
    assert err.value.detail[0]["rule_id"] == "budget_ledger.net_zero"
    assert err.value.detail[0]["msg"]


async def test_transfer_below_committed_is_refused_when_created_and_when_approved(service):
    body = TransferIn(
        reason="x", legs=[LegIn(cost_line_id=WALLS, amount=D("-4000")), LegIn(cost_line_id=ROOF, amount=D("4000"))]
    )
    with pytest.raises(HTTPException) as err:
        await service.create_transfer(PROJECT, body, "u1", "en")
    assert err.value.detail[0]["rule_id"] == "budget_ledger.below_committed"

    t = await _draft(service, "2500")  # 10000 - 2500 = 7500, still above the 7000 committed
    await service.transfer_step(PROJECT, t.id, "submit", "u1", "", "en")
    COMMITTED_BEFORE = dict(COMMITTED)
    COMMITTED[str(WALLS)] = D("9000")  # an order arrived while it waited
    try:

        async def spine(_p):
            return None, "EUR", dict(BUDGET), dict(COMMITTED)

        service._spine = spine  # type: ignore[method-assign]
        with pytest.raises(HTTPException) as err2:
            await service.transfer_step(PROJECT, t.id, "approve", "boss", "", "en")
        assert err2.value.detail[0]["rule_id"] == "budget_ledger.below_committed"
        assert t.status == "submitted"
    finally:
        COMMITTED.update(COMMITTED_BEFORE)


async def test_approved_transfer_cannot_be_changed_or_deleted(service):
    t = await _draft(service)
    await service.transfer_step(PROJECT, t.id, "submit", "u1", "", "en")
    await service.transfer_step(PROJECT, t.id, "approve", "boss", "", "en")
    body = TransferIn(
        reason="again", legs=[LegIn(cost_line_id=WALLS, amount=D("-1")), LegIn(cost_line_id=ROOF, amount=D("1"))]
    )
    with pytest.raises(HTTPException) as e1:
        await service.update_transfer(PROJECT, t.id, body, "u1", "en")
    with pytest.raises(HTTPException) as e2:
        await service.delete_transfer(PROJECT, t.id, "u1", "en")
    with pytest.raises(HTTPException) as e3:
        await service.transfer_step(PROJECT, t.id, "reject", "boss", "late", "en")
    for err in (e1, e2, e3):
        assert err.value.status_code == 422
        assert err.value.detail[0]["rule_id"] == "budget_ledger.approved_immutable"
    assert t.status == "approved" and not service.session.deleted


async def test_reject_needs_a_reason_and_is_final(service):
    t = await _draft(service)
    await service.transfer_step(PROJECT, t.id, "submit", "u1", "", "en")
    with pytest.raises(HTTPException) as err:
        await service.transfer_step(PROJECT, t.id, "reject", "boss", "  ", "en")
    assert err.value.status_code == 422
    out = await service.transfer_step(PROJECT, t.id, "reject", "boss", "No funds", "en")
    assert out.status == "rejected" and out.decision_note == "No funds"


async def test_a_draft_cannot_be_approved_without_being_submitted(service):
    t = await _draft(service)
    with pytest.raises(HTTPException) as err:
        await service.transfer_step(PROJECT, t.id, "approve", "boss", "", "en")
    assert err.value.status_code == 409


async def test_draft_can_be_deleted(service):
    t = await _draft(service)
    await service.delete_transfer(PROJECT, t.id, "u1", "en")
    assert service.session.deleted == [t]


async def test_modification_flow_and_zero_amount(service):
    with pytest.raises(HTTPException):
        await service.create_modification(
            PROJECT, ModificationIn(cost_line_id=SLAB, amount=D("0"), reason="x"), "u1", "en"
        )
    out = await service.create_modification(
        PROJECT,
        ModificationIn(cost_line_id=SLAB, amount=D("1500"), reason="Owner added scope", approval_ref="Letter 12"),
        "u1",
        "en",
    )
    assert out.code == "BM-001" and out.line_code == "320" and out.status == "draft"
    mod = next(o for o in service.session.added if isinstance(o, BudgetModification))
    service.store[mod.id] = mod
    await service.modification_step(PROJECT, mod.id, "submit", "u1", "", "en")
    done = await service.modification_step(PROJECT, mod.id, "approve", "boss", "", "en")
    assert done.status == "approved"


async def test_modification_cutting_below_committed_is_refused(service):
    with pytest.raises(HTTPException) as err:
        await service.create_modification(
            PROJECT, ModificationIn(cost_line_id=WALLS, amount=D("-4000"), reason="Descope"), "u1", "en"
        )
    assert err.value.detail[0]["rule_id"] == "budget_ledger.below_committed"


async def test_unknown_cost_line_is_404(service):
    with pytest.raises(HTTPException) as err:
        await service.create_modification(
            PROJECT, ModificationIn(cost_line_id=uuid.uuid4(), amount=D("10"), reason="x"), "u1", "en"
        )
    assert err.value.status_code == 404


# ── router permissions ────────────────────────────────────────────────────


def _needed() -> dict[tuple[str, str], str]:
    out = {}
    for route in router.routes:
        perms = [d.call.permission for d in route.dependant.dependencies if isinstance(d.call, RequirePermission)]
        for method in route.methods:
            out[(method, route.path)] = perms[0] if perms else ""
    return out


def test_every_route_is_gated_and_decisions_need_manage():
    needed = _needed()
    assert needed and all(needed.values())
    base = "/projects/{project_id}/budget-ledger"
    assert needed[("GET", f"{base}/")] == "costmodel.read"
    for kind in ("transfers", "modifications"):
        assert needed[("POST", f"{base}/{kind}/")] == "costmodel.write"
        assert needed[("PUT", f"{base}/{kind}/{{entry_id}}/")] == "costmodel.write"
        assert needed[("DELETE", f"{base}/{kind}/{{entry_id}}/")] == "costmodel.write"
        assert needed[("POST", f"{base}/{kind}/{{entry_id}}/submit/")] == "costmodel.write"
        assert needed[("POST", f"{base}/{kind}/{{entry_id}}/{{decision}}/")] == "costmodel.manage"


def test_viewer_cannot_write_and_editor_cannot_decide():
    from app.core.permissions import Role, permission_registry
    from app.modules.costmodel.permissions import register_costmodel_permissions

    register_costmodel_permissions()
    assert not permission_registry.role_has_permission(Role.VIEWER, "costmodel.write")
    assert permission_registry.role_has_permission(Role.EDITOR, "costmodel.write")
    assert not permission_registry.role_has_permission(Role.EDITOR, "costmodel.manage")
    assert permission_registry.role_has_permission(Role.MANAGER, "costmodel.manage")


async def test_code_race_takes_the_next_number(service, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    session = service.session
    real_flush = session.flush
    state = {"clashed": False}

    async def flush():
        if not state["clashed"] and any(getattr(o, "code", "") == "BT-001" for o in session.added):
            state["clashed"] = True
            session.added[:] = [o for o in session.added if getattr(o, "code", "") != "BT-001"]
            raise IntegrityError("insert", {}, Exception("uq_costmodel_budget_transfer_code"))
        await real_flush()

    session.flush = flush
    out = await service.create_transfer(
        PROJECT,
        TransferIn(
            reason="Race",
            legs=[LegIn(cost_line_id=WALLS, amount=D("-100")), LegIn(cost_line_id=ROOF, amount=D("100"))],
        ),
        "u1",
        "en",
    )
    assert state["clashed"] and out.code == "BT-002"
