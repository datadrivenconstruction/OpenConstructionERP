# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The delivery model service on PostgreSQL, through the real governance gate.

Approval is the governance gate decision on the contracts area (lead decision
2): these tests drive the gate with the evidence provider registered and show
that it blocks until the decision is proposed, every risk allocated and the
package plan fits, that a proposed (not approved) decision is enough to pass,
and that the binding frame document approves the decision exactly once.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model.errors import DeliveryModelError
from app.modules.delivery_model.events import handle_frame_document, handle_risk_deleted
from app.modules.delivery_model.evidence import register_gate_evidence
from app.modules.delivery_model.service import DeliveryModelService
from app.modules.project_governance.errors import GovernanceError
from tests._pg import isolated_engine
from tests.pg.delivery_fixtures import (
    CONTRACT_DOC,
    GATE,
    align_allocations,
    build_world,
    call,
    change_request,
    compare,
    decisions,
    propose,
    settle_change_request,
    state,
)
from tests.pg.governance_fixtures import decide, documents, only_evidence, prepare_gate

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    with only_evidence(register=register_gate_evidence):
        async with isolated_engine() as engine:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            yield await build_world(factory)


async def _ready(w) -> dict[str, uuid.UUID]:
    """Compare, propose design and build, confirm the matrix and derive packages."""
    ids = await compare(w)
    await propose(w, ids["design_build"])
    await call(w, "confirm_allocations", None, w.manager)
    await call(w, "derive_packages", w.manager)
    return ids


async def _pass_gate(w) -> None:
    g = await prepare_gate(w, GATE)
    await decide(w, g.id, "go")
    doc = (await documents(w))[CONTRACT_DOC]
    await handle_frame_document(
        {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"}, session_factory=w.factory
    )


async def test_rule1_proposal_needs_two_scored_options_and_rationale(world) -> None:
    w = world
    ids = await compare(w, ("design_build",))
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_build"])
    assert exc.value.code == "single_option_decision"
    more = await call(w, "add_option", "cm_at_risk", overrides={}, notes="", actor_id=w.manager)
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_build"])
    assert exc.value.code == "scores_incomplete"
    await call(w, "prefill_scores", w.manager)
    await call(w, "patch_weights", {"innovation": "17"}, w.manager)
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_build"])
    assert exc.value.code == "weights_not_100"
    await call(w, "patch_weights", {"innovation": "7"}, w.manager)
    decision = await propose(w, more.id)
    assert decision.form_code == "cm_at_risk"
    assert (await state(w)).status == "proposed"


async def test_gate_blocks_until_ready_then_binding_approves_once(world) -> None:
    w = world
    ids = await compare(w)
    await propose(w, ids["design_build"])
    g = await prepare_gate(w, GATE)
    # Proposed but risks unallocated and no packages: the provider blocks the gate.
    with pytest.raises(GovernanceError) as exc:
        await decide(w, g.id, "go")
    refs = {v.get("ref") for v in exc.value.violations if v.get("code") == "evidence_not_met"}
    assert {"delivery_risks_allocated", "delivery_no_errors"} <= refs
    assert "delivery_decision_proposed" not in refs
    await call(w, "confirm_allocations", None, w.manager)
    await call(w, "derive_packages", w.manager)
    # A PROPOSED decision is enough: the gate decision is the approval.
    await decide(w, g.id, "go")
    doc = (await documents(w))[CONTRACT_DOC]
    assert doc.status == "binding"
    event = {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"}
    assert await handle_frame_document(event, session_factory=w.factory) is True
    assert await handle_frame_document(event, session_factory=w.factory) is False
    model = await state(w)
    assert model.status == "binding"
    async with w.factory() as s:
        [d] = await DeliveryModelService(s).decision_views(w.project_id)
    assert d["status"] == "approved"
    assert d["approved_by"] == str(w.decider) and d["approval_source"] == "gate"
    assert d["bound_revision_id"] == str(doc.bound_revision_id)
    assert d["four_eyes_violated"] is False
    # Rule 14: the snapshot is frozen; the model can no longer be edited here.
    frozen = d["snapshot"]
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "patch_weights", {"innovation": "8"}, w.manager)
    assert exc.value.code == "model_not_editable"
    async with w.factory() as s:
        [again] = await DeliveryModelService(s).decision_views(w.project_id)
    assert again["snapshot"] == frozen


async def test_rule9_form_change_after_binding(world) -> None:
    from app.modules.contracts.models import Contract

    w = world
    ids = await _ready(w)
    await _pass_gate(w)
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "reopen", w.manager)
    assert exc.value.code == "change_request_required"
    cr = await change_request(w)
    async with w.factory() as s:
        contract = Contract(
            project_id=w.project_id,
            code="C-1",
            title="Design and build works",
            contract_type="design_build",
            counterparty_type="subcontractor",
            total_value=Decimal("1000000"),
            currency="EUR",
            status="active",
            metadata_={},
        )
        s.add(contract)
        await s.commit()
    pkgs = {p["code"]: p for p in await call(w, "package_views")}
    db = uuid.UUID(pkgs["design_and_build"]["id"])
    await call(w, "link_package", db, "contract", contract.id, w.manager)
    await call(w, "reopen", w.manager)
    assert (await state(w)).change_request_id == cr
    with pytest.raises(DeliveryModelError) as exc:
        await propose(w, ids["design_bid_build_single"])
    assert exc.value.code == "form_change_impacts_packages"
    assert [v["ref"] for v in exc.value.violations] == ["design_and_build"]
    new = await propose(w, ids["design_bid_build_single"], dispositions={pkgs["design_and_build"]["id"]: "re_scope"})
    assert new.supersedes_id is not None
    # Governance approves the change request for real. The plan and the matrix still describe design and
    # build, so the decision is NOT approved yet: readiness is checked again at approval (review finding 4d).
    await settle_change_request(w, cr, "approved")
    assert (await state(w)).status == "proposed"
    assert (await decisions(w))["design_bid_build_single"]["approval_blocked_reason"] == "approval_not_ready"
    # Re-scope: the design and build package is taken out of the plan, the matrix follows the new form.
    await call(w, "unlink_package", db, w.manager)
    await call(w, "set_package_status", db, "cancelled", w.manager)
    await align_allocations(w)
    by_form = await decisions(w)  # a read catches up: no second event comes
    assert (await state(w)).status == "binding"
    assert by_form["design_bid_build_single"]["status"] == "approved"
    assert by_form["design_bid_build_single"]["approval_source"] == "change_request"
    assert by_form["design_bid_build_single"]["approved_by"] == str(w.decider)
    assert by_form["design_bid_build_single"]["approval_blocked_reason"] is None
    assert by_form["design_build"]["status"] == "superseded"
    assert (await state(w)).change_request_id is None


async def test_rules12_13_seeding_is_idempotent_and_deleted_link_is_flagged(world) -> None:
    from app.modules.risk.models import RiskItem
    from app.modules.risk.service import RiskService

    w = world
    await _ready(w)
    cats = ["design_errors", "ground_conditions", "price_escalation"]
    preview = await call(w, "seed_risks", cats, preview=True, actor_id=w.manager, locale="en")
    assert [p["risk_id"] for p in preview] == [None, None, None]
    first = await call(w, "seed_risks", cats, preview=False, actor_id=w.manager, locale="en")
    second = await call(w, "seed_risks", cats, preview=False, actor_id=w.manager, locale="en")
    assert len(first) == 3 and second == []
    async with w.factory() as s:
        risks = (await s.execute(select(RiskItem).where(RiskItem.project_id == w.project_id))).scalars().all()
        assert sorted(r.category for r in risks) == ["financial", "technical", "technical"]
        victim = next(r for r in risks if r.metadata_["delivery_model_category"] == "ground_conditions")
        await RiskService(s).delete_risk(victim.id)
        await s.commit()
    n = await handle_risk_deleted(
        {"project_id": str(w.project_id), "risk_id": str(victim.id)}, session_factory=w.factory
    )
    assert n == 1
    matrix = await call(w, "allocation_matrix")
    a = next(i["allocation"] for i in matrix["items"] if i["category_code"] == "ground_conditions")
    assert a["status"] == "link_missing" and a["risk_item_ids"] == []
    # Not recreated silently: only confirmed allocations without a link are seeded.
    assert await call(w, "seed_risks", ["ground_conditions"], preview=False, actor_id=w.manager, locale="en") == []
    # An edit alone does not clear the flag; the explicit confirm does, and then the row can be seeded again.
    await call(
        w,
        "put_allocation",
        "ground_conditions",
        {"party": a["party"], "basis": a["basis"], "shares": a["shares"], "rationale": a["rationale"]},
        w.manager,
    )
    matrix = await call(w, "allocation_matrix")
    edited = next(i["allocation"] for i in matrix["items"] if i["category_code"] == "ground_conditions")
    assert edited["status"] == "link_missing"
    await call(w, "confirm_allocations", ["ground_conditions"], w.manager)
    again = await call(w, "seed_risks", ["ground_conditions"], preview=False, actor_id=w.manager, locale="en")
    assert len(again) == 1 and again[0]["risk_id"] not in (None, str(victim.id))


async def test_rules10_11_owner_furnished_items(world) -> None:

    w = world
    await _ready(w)
    pkgs = {p["code"]: p for p in await call(w, "package_views")}
    db = uuid.UUID(pkgs["design_and_build"]["id"])
    await call(w, "update_package", db, {"need_date": "2027-03-01"}, w.manager)
    ofi = await call(
        w,
        "create_ofi",
        {"code": "OFI-1", "description": "Transformer", "package_id": db, "expected_delivery_date": "2027-03-15"},
        w.manager,
    )
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "set_ofi_status", ofi.id, "ordered", w.manager)
    assert exc.value.code == "ofi_without_route"
    report = await call(w, "consistency")
    sev = {(i["code"], i["severity"]) for i in report["items"] if i["ref"] == "OFI-1"}
    # The eleven-area model enables procurement in its second phase: before the gate into it a missing
    # route is a warning. (That it is an error once procurement is released is in the unit rules test.)
    assert sev == {("ofi_without_route", "warning"), ("ofi_late_for_installer", "warning")}
    await call(w, "set_ofi_route", ofi.id, route="framework", link_kind=None, link_id=None, actor_id=w.manager)
    report = await call(w, "consistency")
    assert "ofi_without_route" not in {i["code"] for i in report["items"]}


async def test_concurrent_proposals_one_wins(world) -> None:
    w = world
    ids = await compare(w)

    async def attempt(option_id):
        try:
            await propose(w, option_id)
            return "ok"
        except DeliveryModelError as exc:
            return exc.code

    results = await asyncio.gather(attempt(ids["design_build"]), attempt(ids["design_bid_build_single"]))
    assert sorted(results) == ["decision_pending", "ok"]
    async with w.factory() as s:
        assert len(await DeliveryModelService(s).decision_views(w.project_id)) == 1


async def test_rule15_catalogue_change_needs_mapping(world) -> None:
    import json

    from app.modules.delivery_model.catalogue import CATALOGUE_DIR, DELIVERY_FORMS_KIND
    from app.modules.project_governance.catalogue_store import CatalogueStore

    w = world
    await compare(w)
    await call(w, "confirm_allocations", ["archaeology_uxo"], w.manager)
    body = json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))
    for f in body["forms"]:
        if f["code"] == "design_build":
            f["code"] = "design_and_build"
    for a in body["default_allocations"]:
        a["forms"] = ["design_and_build" if x == "design_build" else x for x in a["forms"]]
    for c in body["criteria"]:
        c["scores"] = {("design_and_build" if k == "design_build" else k): v for k, v in c["scores"].items()}
    for t in body["package_templates"]:
        t["form"] = "design_and_build" if t["form"] == "design_build" else t["form"]
    body["risk_categories"] = [r for r in body["risk_categories"] if r["code"] != "archaeology_uxo"]
    body["default_allocations"] = [a for a in body["default_allocations"] if a["risk_category"] != "archaeology_uxo"]
    tenant = str(w.manager)
    async with w.factory() as s:
        store = CatalogueStore(s)
        DeliveryModelService(s)
        row = await store.create(
            tenant,
            code="owner_forms",
            name="Owner forms",
            based_on_source=None,
            based_on_id=None,
            based_on_version=None,
            actor_id=w.manager,
            kind=DELIVERY_FORMS_KIND,
        )
        await store.update_draft(tenant, row.id, body=body, name=None)
        await store.publish(tenant, row.id, actor_id=w.manager)
        await s.commit()
    kw = {
        "actor_id": w.manager,
        "tenant_id": tenant,
        "catalogue_source": "tenant",
        "catalogue_id": str(row.id),
        "catalogue_version": None,
        "category_mapping": {},
    }
    with pytest.raises(DeliveryModelError) as exc:
        await call(w, "change_catalogue", form_mapping={}, **kw)
    assert exc.value.code == "form_mapping_missing"
    await call(w, "change_catalogue", form_mapping={"design_build": "design_and_build"}, **kw)
    cmp = await call(w, "comparison")
    assert sorted(o["form_code"] for o in cmp["options"]) == ["design_and_build", "design_bid_build_single"]
    matrix = await call(w, "allocation_matrix")
    assert [o["status"] for o in matrix["orphans"]] == ["unconfirmed"]
