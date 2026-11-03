# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontract change pass-through: markup, owner-approval gate, leakage, time rule, billing hand-off."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.subcontractors import change_chain
from app.modules.subcontractors import validators as checks
from app.modules.subcontractors.change_chain import (
    OWNER_NOT_APPROVED_CODE,
    SpawnFromOwnerChange,
    SpawnLine,
    SubcontractChangeCreate,
    SubcontractChangeService,
    SubcontractChangeUpdate,
    owner_change_is_approved,
    pass_through,
)
from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement, SubcontractChange

D = Decimal


@pytest.mark.parametrize(
    ("owner", "markup", "expected"),
    [
        ("1000.00", "0", "1000.00"),
        ("1000.00", "10", "900.00"),
        ("1000.00", "100", "0.00"),
        ("-1000.00", "10", "-900.00"),
        ("100.05", "10", "90.05"),  # 90.045 rounds half up
        ("0.05", "50", "0.03"),  # 0.025 rounds half up
        ("1000.00", "12.5", "875.00"),
    ],
)
def test_pass_through_keeps_the_gc_markup(owner: str, markup: str, expected: str) -> None:
    assert pass_through(D(owner), D(markup), True) == D(expected)


def test_a_free_price_is_not_marked_down() -> None:
    assert pass_through(D("1000"), D("10"), False) == D("1000.00")


def test_owner_status_mapping() -> None:
    assert owner_change_is_approved("change_order", "approved")
    assert owner_change_is_approved("change_order", "executed")
    assert not owner_change_is_approved("change_order", "submitted")
    assert owner_change_is_approved("variation_order", "issued")
    assert not owner_change_is_approved("variation_order", "draft")
    assert not owner_change_is_approved("variation_order", "voided")
    assert not owner_change_is_approved(None, "approved")


class _Session:
    def __init__(self, *rows: Any) -> None:
        self.rows = {row.id: row for row in rows}
        self.info: dict[str, Any] = {}

    async def get(self, _model: Any, key: uuid.UUID) -> Any:
        return self.rows.get(key)

    def add(self, row: Any) -> None:
        row.id = row.id or uuid.uuid4()
        if isinstance(row, SubcontractChange):
            now = datetime.now(UTC)
            row.decision_note, row.created_at, row.updated_at = "", now, now
        self.rows[row.id] = row

    async def flush(self) -> None:
        for row in self.rows.values():
            if isinstance(row, SubcontractChange):
                row.id = row.id or uuid.uuid4()


class _Svc(SubcontractChangeService):
    """Service over in-memory rows with a controllable owner change."""

    def __init__(self, session: _Session, owner: dict[str, Any] | None) -> None:
        super().__init__(session)  # type: ignore[arg-type]
        self.owner = owner

    async def owner_change(self, owner_type: str, owner_id: uuid.UUID) -> dict[str, Any] | None:
        return self.owner

    async def list_for_owner_change(self, owner_type: str, owner_id: uuid.UUID) -> list[SubcontractChange]:
        return [
            r for r in self.session.rows.values() if isinstance(r, SubcontractChange) and r.owner_change_id == owner_id
        ]  # type: ignore[attr-defined]

    async def list_for_agreement(self, agreement_id: uuid.UUID) -> list[SubcontractChange]:
        return [
            r for r in self.session.rows.values() if isinstance(r, SubcontractChange) and r.agreement_id == agreement_id
        ]  # type: ignore[attr-defined]

    async def _next_code(self, agreement_id: uuid.UUID) -> str:
        return f"SCO-{len(await self.list_for_agreement(agreement_id)) + 1:03d}"


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(change_chain, "publish_after_commit", lambda _s, name, data, **_kw: events.append((name, data)))

    class _Finance:
        def __init__(self, _session: Any) -> None:
            pass

        async def sync_project_budget(self, project_id: uuid.UUID) -> None:
            return None

    import app.modules.finance.service as finance_service

    monkeypatch.setattr(finance_service, "FinanceService", _Finance)
    return events


def _owner(status: str = "approved", value: str = "10000.00", days: int = 10, kind: str = "change_order") -> dict:
    return {
        "project_id": None,
        "value": D(value),
        "code": "CO-1",
        "title": "Extra slab",
        "status": status,
        "currency": "EUR",
        "days": days,
        "kind": kind,
    }


def _agreement(project_id: uuid.UUID | None = None, value: str = "100000.00") -> SubcontractAgreement:
    return SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=uuid.uuid4(),
        project_id=project_id or uuid.uuid4(),
        title="Concrete",
        total_value=D(value),
        currency="EUR",
        status="active",
    )


async def _spawn(svc: _Svc, agreement: SubcontractAgreement, **line: Any) -> SubcontractChange:
    owner_id = uuid.uuid4() if not getattr(svc, "owner_id", None) else svc.owner_id  # type: ignore[attr-defined]
    svc.owner_id = owner_id  # type: ignore[attr-defined]
    svc.owner["project_id"] = agreement.project_id  # type: ignore[index]
    rows = await svc.spawn_from_owner_change(
        SpawnFromOwnerChange(
            owner_change_type="change_order",
            owner_change_id=owner_id,
            lines=[SpawnLine(agreement_id=agreement.id, **line)],
        )
    )
    return rows[0]


@pytest.mark.asyncio
async def test_spawn_computes_the_amount_from_the_owner_share_and_markup() -> None:
    agreement = _agreement()
    svc = _Svc(_Session(agreement), _owner(value="10000.00"))
    row = await _spawn(svc, agreement, markup_pct=D("10"), time_impact_days=4)
    assert row.amount == D("9000.00")
    assert row.owner_amount == D("10000.00") and row.markup_pct == D("10")
    assert row.time_impact_days == 4 and row.owner_time_days == 10


@pytest.mark.asyncio
async def test_spawn_keeps_an_explicit_amount_and_defaults_markup_to_zero() -> None:
    agreement = _agreement()
    svc = _Svc(_Session(agreement), _owner())
    row = await _spawn(svc, agreement, amount=D("7777.00"))
    assert row.amount == D("7777.00") and row.markup_pct == D("0")


@pytest.mark.asyncio
async def test_spawn_without_amount_or_share_on_several_lines_is_refused() -> None:
    a, b = _agreement(), _agreement()
    owner = _owner()
    owner["project_id"] = a.project_id
    svc = _Svc(_Session(a, b), owner)
    with pytest.raises(HTTPException) as exc:
        await svc.spawn_from_owner_change(
            SpawnFromOwnerChange(
                owner_change_type="change_order",
                owner_change_id=uuid.uuid4(),
                lines=[SpawnLine(agreement_id=a.id), SpawnLine(agreement_id=a.id)],
            )
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_updating_markup_recomputes_a_back_to_back_amount() -> None:
    agreement = _agreement()
    svc = _Svc(_Session(agreement), _owner(value="2000.00"))
    row = await _spawn(svc, agreement)
    assert row.amount == D("2000.00")
    svc.session.rows[row.id] = row  # type: ignore[attr-defined]
    await svc.update(row.id, SubcontractChangeUpdate(markup_pct=D("25")))
    assert row.amount == D("1500.00")


@pytest.mark.asyncio
async def test_approval_is_blocked_until_the_owner_change_is_approved(published: list) -> None:
    agreement = _agreement()
    owner = _owner(status="submitted")
    svc = _Svc(_Session(agreement), owner)
    row = await _spawn(svc, agreement, markup_pct=D("10"))
    row.status = "submitted"
    svc.session.rows[row.id] = row  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc:
        await svc.transition(row.id, "approved", user_id="u1")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == OWNER_NOT_APPROVED_CODE and exc.value.detail["owner_status"] == "submitted"
    assert agreement.total_value == D("100000.00") and row.applied_amount is None and published == []

    owner["status"] = "approved"
    await svc.transition(row.id, "approved", user_id="u1")
    await svc.transition(row.id, "approved", user_id="u1")  # replay adds nothing
    assert agreement.total_value == D("109000.00")
    assert [name for name, _ in published] == ["subcontractors.change.approved"]
    assert published[0][1]["markup_pct"] == "10.000" or published[0][1]["markup_pct"] == "10"
    assert published[0][1]["time_impact_days"] == 0


@pytest.mark.asyncio
async def test_a_change_that_is_not_back_to_back_is_not_gated(published: list) -> None:
    agreement = _agreement()
    svc = _Svc(_Session(agreement), _owner(status="draft"))
    row = await _spawn(svc, agreement, amount=D("500.00"), back_to_back=False)
    row.status = "submitted"
    svc.session.rows[row.id] = row  # type: ignore[attr-defined]
    await svc.transition(row.id, "approved")
    assert agreement.total_value == D("100500.00")


@pytest.mark.asyncio
async def test_leakage_shows_what_the_gc_absorbs() -> None:
    a, b = _agreement(), _agreement(project_id=None)
    owner = _owner(value="10000.00", days=10)
    owner["project_id"] = a.project_id
    b.project_id = a.project_id
    svc = _Svc(_Session(a, b), owner)
    owner_id = uuid.uuid4()
    svc.owner_id = owner_id  # type: ignore[attr-defined]
    rows = await svc.spawn_from_owner_change(
        SpawnFromOwnerChange(
            owner_change_type="change_order",
            owner_change_id=owner_id,
            lines=[
                SpawnLine(agreement_id=a.id, owner_share=D("6000"), markup_pct=D("10"), time_impact_days=6),
                SpawnLine(
                    agreement_id=b.id,
                    owner_share=D("4000"),
                    amount=D("4500.00"),
                    markup_pct=D("10"),
                    time_impact_days=7,
                ),
            ],
        )
    )
    for r in rows:
        r.status = "approved"
    chain = await svc.chain("change_order", owner_id)
    # approved 5400 + 4500, markup kept 600 + 400: 10000 - 9900 - 1000 = -900
    assert chain.approved_sub_total == "9900.00" and chain.markup_retained == "1000.00"
    assert chain.leakage == "-900.00"
    assert chain.days_owner == 10 and chain.days_sub_total == 13
    assert [c.markup_pct for c in chain.changes] == ["10.000", "10.000"] or [c.markup_pct for c in chain.changes] == [
        "10",
        "10",
    ]


def test_rule_blocks_an_unapproved_owner_change_and_names_the_status() -> None:
    base = {"code": "SCO-1", "back_to_back": True, "owner_change_id": "x"}
    [finding] = checks.check_change_owner_approved(
        {**base, "owner_change_approved": False, "owner_change_status": "draft"}
    )
    assert finding.params["status"] == "draft"
    assert checks.check_change_owner_approved({**base, "owner_change_approved": True}) == []
    assert checks.check_change_owner_approved({**base, "back_to_back": False, "owner_change_approved": False}) == []
    assert checks.check_change_owner_approved({"code": "S", "back_to_back": True, "owner_change_approved": False}) == []


def test_rule_warns_when_sub_days_exceed_the_owner_days() -> None:
    base = {"code": "SCO-1", "owner_change_id": "x", "owner_time_days": 10}
    [finding] = checks.check_change_time_within_owner({**base, "linked_time_days": 13})
    assert finding.details == {"sub_days": 13, "owner_days": 10}
    assert checks.check_change_time_within_owner({**base, "linked_time_days": 10}) == []
    assert checks.check_change_time_within_owner({"code": "S", "owner_change_id": "x", "linked_time_days": 5}) == []


def test_both_rules_are_registered_with_messages() -> None:
    from app.core.validation.engine import rule_registry
    from app.core.validation.messages import translate
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    rules = {r.rule_id: r for r in rule_registry.get_rules_for_sets(["subcontract_change"])}
    assert rules["subcontract.change_owner_approved"].severity.value == "error"
    assert rules["subcontract.change_time_within_owner"].severity.value == "warning"
    for locale in ("en", "de", "ru"):
        for key in ("change_owner_approved", "change_time_within_owner"):
            text = translate(
                f"subcontract.{key}.fail", locale=locale, code="SCO-1", status="draft", sub_days="3", owner_days="2"
            )
            assert "SCO-1" in text


@pytest.mark.asyncio
async def test_sov_lines_list_approved_unbilled_and_mark_billed_once(published: list) -> None:
    agreement = _agreement()
    svc = _Svc(_Session(agreement), _owner())
    row = await _spawn(svc, agreement, amount=D("800.00"))
    other = await _spawn(svc, agreement, amount=D("100.00"))
    row.status = "submitted"
    svc.session.rows[row.id] = row  # type: ignore[attr-defined]
    await svc.transition(row.id, "approved")
    assert [r.id for r in await svc.sov_lines(agreement.id)] == [row.id]  # the draft one is not offered

    app_id = uuid.uuid4()
    svc.session.rows[app_id] = PaymentApplication(id=app_id, agreement_id=agreement.id)  # type: ignore[attr-defined]
    await svc.mark_billed(row.id, app_id)
    await svc.mark_billed(row.id, app_id)  # replay
    assert row.metadata_["billed_in"] == str(app_id)
    assert await svc.sov_lines(agreement.id) == []
    assert other.status == "draft"

    other_app = uuid.uuid4()
    svc.session.rows[other_app] = PaymentApplication(id=other_app, agreement_id=agreement.id)  # type: ignore[attr-defined]
    with pytest.raises(HTTPException) as exc:
        await svc.mark_billed(row.id, other_app)
    assert exc.value.status_code == 409
    # billing never moves the agreement value a second time
    assert agreement.total_value == D("100800.00")


@pytest.mark.asyncio
async def test_mark_billed_refuses_a_foreign_application_and_an_unapproved_change() -> None:
    agreement = _agreement()
    svc = _Svc(_Session(agreement), _owner())
    row = await _spawn(svc, agreement, amount=D("1.00"))
    svc.session.rows[row.id] = row  # type: ignore[attr-defined]
    with pytest.raises(HTTPException) as exc:
        await svc.mark_billed(row.id, uuid.uuid4())
    assert exc.value.status_code == 409
    row.status, row.applied_amount = "approved", D("1.00")
    with pytest.raises(HTTPException) as exc2:
        await svc.mark_billed(row.id, uuid.uuid4())
    assert exc2.value.status_code == 422


def test_create_schema_bounds_markup() -> None:
    with pytest.raises(ValueError):
        SubcontractChangeCreate(agreement_id=uuid.uuid4(), title="x", amount=D("1"), markup_pct=D("101"))
