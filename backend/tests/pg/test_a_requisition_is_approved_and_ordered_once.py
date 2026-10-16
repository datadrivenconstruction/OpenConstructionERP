# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A material requisition is approved by someone else and ordered exactly once (issue #516).

Drives ``/api/v1/procurement/requisitions`` over HTTP against PostgreSQL, one
session per request with commit on success and rollback on error, as the
application does. The world: a manager who approves, two editors who raise
requisitions, an outsider, a project with a bill whose position sits on the
cost spine, and three suppliers in the Vendor directory (active, blacklisted,
active).

What is pinned here:

* the supplier comes from the Vendor directory, and an unknown id is refused;
* only a holder of ``procurement.approve_requisition`` decides, never the person
  who submitted, a rejection needs its reason, and every decision is published;
* conversion writes one draft order line per requisition line with quantity,
  unit and cost line unchanged and the requisition line it came from, moves
  the requisitions to ``ordered``, and refuses a second conversion;
* the trace runs both ways: BOQ position -> requisition line -> order line, and
  order -> requisition -> BOQ sources; a line replace keeps the link;
* cancelling the order hands the requisitions back to ``approved``.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests._pg import isolated_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/procurement"
REQ = f"{BASE}/requisitions"


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    editor: uuid.UUID
    second_editor: uuid.UUID
    outsider: uuid.UUID
    positions: list[uuid.UUID]
    cost_line_id: uuid.UUID
    vendor_active: uuid.UUID
    vendor_blacklisted: uuid.UUID
    vendor_other: uuid.UUID
    events: list[tuple[str, dict]] = field(default_factory=list)


async def _user(s: AsyncSession, role: str) -> uuid.UUID:
    from app.modules.users.models import User

    uid = uuid.uuid4()
    s.add(
        User(
            id=uid,
            email=f"req-{role}-{uid.hex[:8]}@example.test",
            hashed_password="x",
            full_name=f"Req {role}",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await s.flush()
    return uid


async def _vendor(s: AsyncSession, name: str, status: str) -> uuid.UUID:
    from app.modules.supplier_catalogs.models import Vendor

    vendor = Vendor(code=f"V-{uuid.uuid4().hex[:8]}", name=name, status=status, currency="EUR")
    s.add(vendor)
    await s.flush()
    return vendor.id


@pytest_asyncio.fixture
async def world(monkeypatch):
    from app.core.events import event_bus
    from app.modules.boq.models import BOQ, Position
    from app.modules.costmodel.models import CostLine
    from app.modules.procurement.permissions import register_procurement_permissions
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership

    register_procurement_permissions()
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        event_bus,
        "publish_detached",
        lambda name, data=None, source_module=None: events.append((name, dict(data or {}))),
    )
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            manager = await _user(s, "manager")
            editor = await _user(s, "editor")
            second_editor = await _user(s, "editor")
            outsider = await _user(s, "manager")
            pid = uuid.uuid4()
            s.add(Project(id=pid, name="Requisitions", currency="EUR", status="active", owner_id=manager, metadata_={}))
            await s.flush()
            team = Team(project_id=pid, name="Site")
            s.add(team)
            await s.flush()
            for member in (editor, second_editor):
                s.add(TeamMembership(team_id=team.id, user_id=member))
            boq = BOQ(project_id=pid, name="Bill", description="")
            s.add(boq)
            await s.flush()
            positions = []
            for ordinal, qty in (("1.1", "50"), ("1.2", "20")):
                pos = Position(
                    boq_id=boq.id,
                    ordinal=ordinal,
                    description=f"Wall {ordinal}",
                    unit="m3",
                    quantity=qty,
                    unit_rate="100",
                    total="0",
                    metadata_={},
                )
                s.add(pos)
                positions.append(pos)
            await s.flush()
            cost_line = CostLine(
                project_id=pid,
                code="CL-1.1",
                description="Wall 1.1",
                unit="m3",
                source="boq",
                boq_position_id=positions[0].id,
                boq_id=boq.id,
                estimate_quantity="50",
                estimate_unit_rate="100",
                estimate_amount="5000",
                currency="",
                status="active",
            )
            s.add(cost_line)
            await s.flush()
            positions[0].cost_line_id = cost_line.id
            w = World(
                factory=factory,
                project_id=pid,
                manager=manager,
                editor=editor,
                second_editor=second_editor,
                outsider=outsider,
                positions=[p.id for p in positions],
                cost_line_id=cost_line.id,
                vendor_active=await _vendor(s, "Beton Nord", "active"),
                vendor_blacklisted=await _vendor(s, "Struck Off Ltd", "blacklisted"),
                vendor_other=await _vendor(s, "Kies Sued", "active"),
                events=events,
            )
            await s.commit()
        yield w


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.procurement.router import router

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://req-test") as c:
        yield c


def _body(w: World, *, vendor: uuid.UUID | None = None, title: str = "Concrete for walls") -> dict:
    return {
        "project_id": str(w.project_id),
        "title": title,
        "required_date": (date.today() + timedelta(days=30)).isoformat(),
        "vendor_id": str(vendor) if vendor else None,
        "items": [
            {
                "description": "Concrete C30/37",
                "unit": "m3",
                "quantity_requested": "71.4",
                "unit_cost": "95.50",
                "currency_code": "EUR",
                "sources": [
                    {"boq_position_id": str(w.positions[0]), "resource_key": "0:C30", "quantity": "51", "unit": "m3"},
                    {"boq_position_id": str(w.positions[1]), "resource_key": "0:C30", "quantity": "20.4", "unit": "m3"},
                ],
            },
            {
                "description": "Rebar B500",
                "unit": "t",
                "quantity_requested": "3.25",
                "boq_position_id": str(w.positions[0]),
                "sources": [
                    {"boq_position_id": str(w.positions[0]), "resource_key": "1:B500", "quantity": "3.25", "unit": "t"}
                ],
            },
        ],
    }


async def _submitted(w: World, *, by: uuid.UUID, vendor: uuid.UUID | None = None, title: str = "Concrete") -> dict:
    async with client_as(w, by, "editor") as c:
        created = await c.post(f"{REQ}/", json=_body(w, vendor=vendor, title=title))
        assert created.status_code == 201, created.text
        submitted = await c.post(f"{REQ}/{created.json()['id']}/submit")
        assert submitted.status_code == 200, submitted.text
        return submitted.json()


async def _approved(w: World, *, vendor: uuid.UUID | None = None, title: str = "Concrete") -> dict:
    req = await _submitted(w, by=w.editor, vendor=vendor, title=title)
    async with client_as(w, w.manager, "manager") as c:
        approved = await c.post(f"{REQ}/{req['id']}/approve", json={"comment": "Go ahead"})
    assert approved.status_code == 200, approved.text
    return approved.json()


# ── Vendor ──────────────────────────────────────────────────────────────────


async def test_the_supplier_comes_from_the_vendor_directory(world: World) -> None:
    async with client_as(world, world.editor, "editor") as c:
        unknown = await c.post(f"{REQ}/", json=_body(world, vendor=uuid.uuid4()))
        created = await c.post(f"{REQ}/", json=_body(world, vendor=world.vendor_active))
        cleared = await c.patch(f"{REQ}/{created.json()['id']}", json={"vendor_id": None})
        kept = await c.patch(f"{REQ}/{created.json()['id']}", json={"title": "Renamed"})

    assert unknown.status_code == 422
    assert created.status_code == 201, created.text
    assert created.json()["vendor_id"] == str(world.vendor_active)
    assert created.json()["vendor_name"] == "Beton Nord"
    assert created.json()["vendor_status"] == "active"
    assert cleared.json()["vendor_id"] is None
    assert kept.json()["vendor_id"] is None


# ── Approval ────────────────────────────────────────────────────────────────


async def test_only_an_approver_who_did_not_submit_decides(world: World) -> None:
    req = await _submitted(world, by=world.editor)
    async with client_as(world, world.second_editor, "editor") as c:
        by_editor = await c.post(f"{REQ}/{req['id']}/approve", json={})
    assert by_editor.status_code == 403, "an editor holds no procurement.approve_requisition"

    own = await _submitted(world, by=world.manager)
    async with client_as(world, world.manager, "manager") as c:
        self_approve = await c.post(f"{REQ}/{own['id']}/approve", json={})
        self_reject = await c.post(f"{REQ}/{own['id']}/reject", json={"comment": "No"})
    assert self_approve.status_code == 403
    assert "four-eyes" in self_approve.json()["detail"]
    assert self_reject.status_code == 403

    async with client_as(world, world.manager, "manager") as c:
        approved = await c.post(f"{REQ}/{req['id']}/approve", json={"comment": "Within budget"})
        again = await c.post(f"{REQ}/{req['id']}/approve", json={})
    body = approved.json()
    assert approved.status_code == 200, approved.text
    assert body["status"] == "approved"
    assert body["approver_id"] == str(world.manager)
    assert body["approver_name"] == "Req manager", "the UI shows who decided, not a bare id"
    assert body["decision_comment"] == "Within budget"
    assert body["decided_at"]
    assert body["submitted_by"] == str(world.editor)
    assert again.status_code == 200 and again.json()["status"] == "approved"
    assert [h["action"] for h in body["history"]] == ["created", "submitted", "approved"]
    approvals = [d for name, d in world.events if name == "procurement.requisition.approved"]
    assert len(approvals) == 1, "a repeated approval publishes nothing"
    assert approvals[0]["actor_id"] == str(world.manager)


async def test_a_rejection_needs_its_reason_and_goes_back_to_draft(world: World) -> None:
    req = await _submitted(world, by=world.editor)
    async with client_as(world, world.manager, "manager") as c:
        empty = await c.post(f"{REQ}/{req['id']}/reject", json={"comment": "   "})
        missing = await c.post(f"{REQ}/{req['id']}/reject", json={})
        rejected = await c.post(f"{REQ}/{req['id']}/reject", json={"comment": "Split the rebar into its own request"})
    assert empty.status_code == 422
    assert missing.status_code == 422
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["decision_comment"] == "Split the rebar into its own request"
    assert any(name == "procurement.requisition.rejected" for name, _ in world.events)

    async with client_as(world, world.editor, "editor") as c:
        withdrawn = await c.post(f"{REQ}/{req['id']}/withdraw")
        resubmitted = await c.post(f"{REQ}/{req['id']}/submit")
    assert withdrawn.json()["status"] == "draft"
    assert withdrawn.json()["decision_comment"] == "Split the rebar into its own request", "kept while revising"
    assert resubmitted.json()["status"] == "submitted"
    assert resubmitted.json()["decision_comment"] is None
    assert resubmitted.json()["approver_id"] is None
    assert resubmitted.json()["approver_name"] is None


async def test_a_supplier_blacklisted_after_submission_blocks_the_approval(world: World) -> None:
    from app.modules.supplier_catalogs.models import Vendor

    req = await _submitted(world, by=world.editor, vendor=world.vendor_active)
    async with world.factory() as s:
        (await s.get(Vendor, world.vendor_active)).status = "blacklisted"
        await s.commit()
    async with client_as(world, world.manager, "manager") as c:
        refused = await c.post(f"{REQ}/{req['id']}/approve", json={})
        state = await c.get(f"{REQ}/{req['id']}")
    assert refused.status_code == 422
    assert {e["rule_id"] for e in refused.json()["detail"]["errors"]} == {"procurement.requisition_vendor_active"}
    assert state.json()["status"] == "submitted"


async def test_submitting_a_requisition_with_a_blacklisted_supplier_is_refused(world: World) -> None:
    async with client_as(world, world.editor, "editor") as c:
        created = await c.post(f"{REQ}/", json=_body(world, vendor=world.vendor_blacklisted))
        refused = await c.post(f"{REQ}/{created.json()['id']}/submit")
    assert refused.status_code == 422
    assert "procurement.requisition_vendor_active" in {e["rule_id"] for e in refused.json()["detail"]["errors"]}


# ── Conversion ──────────────────────────────────────────────────────────────


async def test_approved_requisitions_become_one_draft_order_line_for_line(world: World) -> None:
    first = await _approved(world, vendor=world.vendor_active, title="Walls")
    second = await _approved(world, title="Slab")
    async with client_as(world, world.editor, "editor") as c:
        converted = await c.post(
            f"{REQ}/convert-to-po",
            json={
                "project_id": str(world.project_id),
                "requisition_ids": [first["id"], second["id"]],
                "delivery_date": (date.today() + timedelta(days=20)).isoformat(),
            },
        )
        assert converted.status_code == 201, converted.text
        result = converted.json()
        po = (await c.get(f"{BASE}/{result['po_id']}")).json()
        after = [(await c.get(f"{REQ}/{rid}")).json() for rid in (first["id"], second["id"])]

    assert result["line_count"] == 4
    assert po["status"] == "draft", "the order still goes through its own approval"
    assert po["metadata"]["vendor_id"] == str(world.vendor_active)
    assert po["vendor_name"] == "Beton Nord"
    req_lines = {line["id"]: line for req in after for line in req["items"]}
    assert {item["requisition_item_id"] for item in po["items"]} == set(req_lines)
    for item in po["items"]:
        source = req_lines[item["requisition_item_id"]]
        assert Decimal(item["quantity"]) == Decimal(source["quantity_requested"])
        assert item["unit"] == source["unit"]
        assert item["cost_line_id"] == source["cost_line_id"]
    concrete = next(i for i in po["items"] if i["description"] == "Concrete C30/37")
    assert Decimal(concrete["unit_rate"]) == Decimal("95.50")
    rebar = next(i for i in po["items"] if i["description"] == "Rebar B500")
    assert rebar["cost_line_id"] == str(world.cost_line_id)
    for req in after:
        assert req["status"] == "ordered"
        assert req["po_id"] == result["po_id"]
        assert req["po_number"] == result["po_number"]
        for line in req["items"]:
            assert Decimal(line["quantity_ordered"]) == Decimal(line["quantity_requested"])
            assert [p["po_id"] for p in line["po_items"]] == [result["po_id"]]
    ordered_events = [d for name, d in world.events if name == "procurement.requisition.ordered"]
    assert {d["requisition_id"] for d in ordered_events} == {first["id"], second["id"]}


async def test_a_requisition_is_never_ordered_twice(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    body = {"project_id": str(world.project_id), "requisition_ids": [req["id"]]}
    async with client_as(world, world.editor, "editor") as c:
        first = await c.post(f"{REQ}/convert-to-po", json=body)
        second = await c.post(f"{REQ}/convert-to-po", json=body)
        listed = await c.get(f"{BASE}/", params={"project_id": str(world.project_id)})
    assert first.status_code == 201, first.text
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "requisition_already_ordered"
    assert listed.json()["total"] == 1, "the refused conversion left no order behind"


async def test_a_plain_order_cannot_claim_a_requisition_line(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.editor, "editor") as c:
        refused = await c.post(
            f"{BASE}/",
            json={
                "project_id": str(world.project_id),
                "items": [
                    {"description": "Concrete", "quantity": "1", "requisition_item_id": req["items"][0]["id"]},
                ],
            },
        )
        state = await c.get(f"{REQ}/{req['id']}")
    assert refused.status_code == 422
    assert state.json()["status"] == "approved"


async def test_conversion_refusals_name_their_reason(world: World) -> None:
    submitted = await _submitted(world, by=world.editor, vendor=world.vendor_active)
    no_vendor = await _approved(world)
    walls = await _approved(world, vendor=world.vendor_active, title="Walls")
    slab = await _approved(world, vendor=world.vendor_other, title="Slab")
    async with client_as(world, world.editor, "editor") as c:

        async def convert(ids: list[str], **extra) -> dict:
            r = await c.post(
                f"{REQ}/convert-to-po",
                json={"project_id": str(world.project_id), "requisition_ids": ids, **extra},
            )
            return {"status": r.status_code, "detail": r.json()["detail"]}

        not_approved = await convert([submitted["id"]])
        vendorless = await convert([no_vendor["id"]])
        conflict = await convert([walls["id"], slab["id"]])
        contradicted = await convert([walls["id"]], vendor_id=str(world.vendor_other))
        blacklisted = await convert([no_vendor["id"]], vendor_id=str(world.vendor_blacklisted))
    assert not_approved["status"] == 409 and not_approved["detail"]["code"] == "requisition_not_approved"
    assert vendorless["status"] == 422
    assert {e["rule_id"] for e in vendorless["detail"]["errors"]} == {"procurement.requisition_vendor_chosen"}
    assert conflict["status"] == 409 and conflict["detail"]["code"] == "vendor_conflict"
    assert contradicted["status"] == 409 and contradicted["detail"]["code"] == "vendor_conflict"
    assert blacklisted["status"] == 422
    assert "procurement.requisition_vendor_active" in {e["rule_id"] for e in blacklisted["detail"]["errors"]}


async def test_an_outsider_reaches_nothing(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.outsider, "manager") as c:
        answers = [
            await c.post(f"{REQ}/{req['id']}/approve", json={}),
            await c.post(f"{REQ}/{req['id']}/reject", json={"comment": "x"}),
            await c.post(
                f"{REQ}/convert-to-po",
                json={"project_id": str(world.project_id), "requisition_ids": [req["id"]]},
            ),
            await c.get(f"{REQ}/trace/position/{world.positions[0]}", params={"project_id": str(world.project_id)}),
        ]
    assert [r.status_code for r in answers] == [404, 404, 404, 404]


# ── Traceability ────────────────────────────────────────────────────────────


async def test_the_trace_runs_from_position_to_order_and_back(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.editor, "editor") as c:
        converted = (
            await c.post(
                f"{REQ}/convert-to-po",
                json={"project_id": str(world.project_id), "requisition_ids": [req["id"]]},
            )
        ).json()
        by_position = (
            await c.get(f"{REQ}/trace/position/{world.positions[1]}", params={"project_id": str(world.project_id)})
        ).json()
        by_first = (
            await c.get(f"{REQ}/trace/position/{world.positions[0]}", params={"project_id": str(world.project_id)})
        ).json()
        by_order = (await c.get(f"{REQ}/trace/purchase-order/{converted['po_id']}")).json()

    [row] = by_position["items"]
    assert row["requisition_id"] == req["id"]
    assert row["description"] == "Concrete C30/37"
    assert Decimal(row["source_quantity"]) == Decimal("20.4")
    assert [p["po_number"] for p in row["purchase_orders"]] == [converted["po_number"]]
    assert sorted(r["resource_key"] for r in by_first["items"]) == ["0:C30", "1:B500"]

    assert [r["id"] for r in by_order["requisitions"]] == [req["id"]]
    concrete = next(line for line in by_order["lines"] if line["description"] == "Concrete C30/37")
    assert concrete["req_number"] == req["req_number"]
    assert sorted(s["boq_position_id"] for s in concrete["sources"]) == sorted(str(p) for p in world.positions)
    assert sorted((s["position_ordinal"], s["position_description"]) for s in concrete["sources"]) == [
        ("1.1", "Wall 1.1"),
        ("1.2", "Wall 1.2"),
    ]


async def test_a_line_replace_keeps_the_link_and_refuses_a_foreign_one(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    other = await _approved(world, vendor=world.vendor_active, title="Other")
    async with client_as(world, world.editor, "editor") as c:
        converted = (
            await c.post(
                f"{REQ}/convert-to-po",
                json={"project_id": str(world.project_id), "requisition_ids": [req["id"]]},
            )
        ).json()
        po = (await c.get(f"{BASE}/{converted['po_id']}")).json()
        lines = [
            {
                "description": i["description"],
                "quantity": i["quantity"],
                "unit": i["unit"],
                "unit_rate": "100",
                "requisition_item_id": i["requisition_item_id"],
            }
            for i in po["items"]
        ]
        kept = await c.patch(f"{BASE}/{po['id']}", json={"items": lines})
        foreign = await c.patch(
            f"{BASE}/{po['id']}",
            json={"items": [dict(lines[0], requisition_item_id=other["items"][0]["id"])]},
        )
    assert kept.status_code == 200, kept.text
    assert {i["requisition_item_id"] for i in kept.json()["items"]} == {i["id"] for i in req["items"]}
    assert foreign.status_code == 422


async def test_cancelling_the_order_hands_the_requisitions_back(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.editor, "editor") as c:
        first = (
            await c.post(
                f"{REQ}/convert-to-po",
                json={"project_id": str(world.project_id), "requisition_ids": [req["id"]]},
            )
        ).json()
    async with client_as(world, world.manager, "manager") as c:
        cancelled = await c.post(f"{BASE}/{first['po_id']}/cancel/", json={"reason": "Wrong supplier"})
        released = (await c.get(f"{REQ}/{req['id']}")).json()
        again = await c.post(
            f"{REQ}/convert-to-po",
            json={"project_id": str(world.project_id), "requisition_ids": [req["id"]]},
        )
    assert cancelled.status_code == 200, cancelled.text
    assert released["status"] == "approved"
    assert released["po_id"] is None
    assert all(Decimal(line["quantity_ordered"]) == 0 for line in released["items"])
    assert released["history"][-1]["action"] == "released"
    assert again.status_code == 201, again.text

    from app.modules.procurement.models import PurchaseOrderItem

    async with world.factory() as s:
        linked = (
            await s.execute(
                select(PurchaseOrderItem.po_id).where(
                    PurchaseOrderItem.requisition_item_id == uuid.UUID(req["items"][0]["id"])
                )
            )
        ).scalars()
        assert set(linked) == {uuid.UUID(first["po_id"]), uuid.UUID(again.json()["po_id"])}, (
            "the cancelled order keeps its link, so the first attempt stays traceable"
        )
