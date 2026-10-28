# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the delivery model PostgreSQL tests.

A world is a throwaway database with real users and a project that runs
governance on the shipped ``elf_module_framework`` model (eleven areas, one
gate ``development_to_execution`` at which every area's frame document is
required, including the contracts area ``m02_contract_management``), approval
routes for ``phase_gate`` and ``frame_change``, a CDE container per frame
document, and the shipped ``neutral`` delivery forms catalogue pinned.
Everything commits for real, so row locks behave as in production.

Tags. The delivery model finds its carrier document and the procurement phase
through the governance read port (``hosts`` on a document type, ``enables`` on
a phase). Under the eleven-area model the carrier is the contract management
frame document, and procurement is enabled by the first phase, so no gate
guards it. :func:`build_world` can also pin a tenant copy of a shipped model
with the delivery tags taken out, which is the only way a project has no
carrier now that every shipped model names one.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model.service import DeliveryModelService
from app.modules.project_governance.service import GovernanceService
from tests.pg.governance_fixtures import World, add_container, add_project, add_route, add_user

GATE = "development_to_execution"
CONTRACT_DOC = "m02_contract_management_frame"


async def _untagged_copy(session: AsyncSession, tenant: str, actor: uuid.UUID, catalogue_id: str) -> str:
    """Publish a tenant copy of a shipped phase model that hosts the delivery model nowhere; return its id."""
    import json

    from app.modules.project_governance.catalogue import CATALOGUE_DIR
    from app.modules.project_governance.catalogue_store import CatalogueStore

    body = json.loads((CATALOGUE_DIR / f"{catalogue_id}.json").read_text(encoding="utf-8"))
    for doc in body["document_types"]:
        doc["hosts"] = [h for h in doc.get("hosts", []) if h != "delivery_model"]
    for phase in body["phases"]:
        phase["enables"] = [e for e in phase.get("enables", []) if e != "procurement"]
    store = CatalogueStore(session)
    row = await store.create(
        tenant,
        code=f"untagged_{uuid.uuid4().hex[:6]}",
        name="Model without a delivery frame document",
        based_on_source=None,
        based_on_id=None,
        based_on_version=None,
        actor_id=actor,
    )
    await store.update_draft(tenant, row.id, body=body, name=None)
    await store.publish(tenant, row.id, actor_id=actor)
    return str(row.id)


async def build_world(
    factory: async_sessionmaker[AsyncSession],
    *,
    governance: bool = True,
    catalogue_id: str = "elf_module_framework",
    carrier: bool = True,
) -> World:
    from app.modules.delivery_model.catalogue import register_kinds

    register_kinds()
    async with factory() as s:
        manager = await add_user(s, "manager")
        decider = await add_user(s, "manager")
        owner = await add_user(s, "editor")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [decider, owner, editor])
        w = World(factory, pid, manager, decider, owner, editor, outsider)
        if governance:
            w.gate_route_id = await add_route(s, pid, "phase_gate", decider)
            w.change_route_id = await add_route(s, pid, "frame_change", decider)
            source = "shipped"
            if not carrier:
                source, catalogue_id = "tenant", await _untagged_copy(s, str(manager), manager, catalogue_id)
            await GovernanceService(s).set_model(
                pid,
                source=source,
                catalogue_id=catalogue_id,
                version=None,
                four_eyes=True,
                actor_id=manager,
                tenant_id=str(manager),
            )
            # Governance reads only a pinned route; nothing is found by project or kind.
            await GovernanceService(s).update_settings(
                pid,
                four_eyes=None,
                decision_route_id=w.gate_route_id,
                change_route_id=w.change_route_id,
                fields_set={"decision_route_id", "change_route_id"},
                actor_id=manager,
            )
            for d in await GovernanceService(s).repo.list_documents(pid):
                w.containers[d.doc_type] = await add_container(s, pid, d.doc_type)
        await DeliveryModelService(s).set_model(pid, actor_id=manager, tenant_id=str(manager), catalogue_id="neutral")
        await s.commit()
    return w


async def call(w: World, fn: str, *args: Any, **kw: Any) -> Any:
    """Run one service method in its own committed session."""
    async with w.factory() as s:
        out = await getattr(DeliveryModelService(s), fn)(w.project_id, *args, **kw)
        await s.commit()
        return out


async def compare(
    w: World, forms: tuple[str, ...] = ("design_bid_build_single", "design_build")
) -> dict[str, uuid.UUID]:
    """Add the forms as options and score them with the catalogue defaults."""
    ids = {}
    for code in forms:
        row = await call(w, "add_option", code, overrides={}, notes="", actor_id=w.manager)
        ids[code] = row.id
    await call(w, "prefill_scores", w.manager)
    return ids


async def propose(w: World, option_id: uuid.UUID, **kw: Any) -> Any:
    return await call(
        w,
        "propose",
        option_id=option_id,
        rationale=kw.pop("rationale", "Single point of responsibility and a fixed price at award."),
        owner_capability=None,
        dispositions=kw.pop("dispositions", {}),
        actor_id=kw.pop("actor_id", w.manager),
    )


async def state(w: World) -> Any:
    from sqlalchemy import select

    from app.modules.delivery_model.models import DeliveryModel

    async with w.factory() as s:
        return (await s.execute(select(DeliveryModel).where(DeliveryModel.project_id == w.project_id))).scalar_one()


async def align_allocations(w: World) -> None:
    """Put every risk category on the default of the form in use and confirm the matrix."""
    matrix = await call(w, "allocation_matrix")
    for item in matrix["items"]:
        default = item["default"]
        if default is None:
            continue
        await call(
            w,
            "put_allocation",
            item["category_code"],
            {"party": default["party"], "basis": default["basis"], "shares": default["shares"] or {}, "rationale": ""},
            w.manager,
        )
    await call(w, "confirm_allocations", None, w.manager)


async def view(w: World, **kw: Any) -> dict[str, Any]:
    """The model as the API returns it, read in its own committed session (the catch-up may write)."""
    return await call(w, "model_view", **kw)


async def decisions(w: World) -> dict[str, dict[str, Any]]:
    """Decision views by form code."""
    return {d["form_code"]: d for d in await call(w, "decision_views")}


async def change_request(w: World, *, reason: str = "The owner cannot staff the design review") -> uuid.UUID:
    """A newer revision of the carrier document and a governance change request for it."""
    from sqlalchemy import func, select

    from app.modules.cde.models import DocumentRevision
    from tests.pg.governance_fixtures import add_revision, documents

    doc = (await documents(w))[CONTRACT_DOC]
    async with w.factory() as s:
        container = w.containers[CONTRACT_DOC]
        count = select(func.count()).select_from(DocumentRevision).where(DocumentRevision.container_id == container)
        n = (await s.execute(count)).scalar_one()
        await add_revision(s, container, n + 1, f"m02-hash-{n + 1}")
        cr = await GovernanceService(s).create_change_request(
            w.project_id,
            doc.id,
            reason=reason,
            impact="Delivery form",
            proposed_revision_id=None,
            actor_id=w.manager,
            is_manager=True,
        )
        await s.commit()
        return cr.id


async def settle_change_request(w: World, cr_id: uuid.UUID, verdict: str, *, by: uuid.UUID | None = None) -> None:
    """Governance's own verdict on the change request, then the event its subscriber would deliver."""
    from app.modules.delivery_model.events import handle_frame_document
    from tests.pg.governance_fixtures import documents

    async with w.factory() as s:
        await GovernanceService(s).apply_change_decision(cr_id, decision=verdict, decided_by=by or w.decider)
        await s.commit()
    if verdict == "approved":
        doc = (await documents(w))[CONTRACT_DOC]
        await handle_frame_document(
            {"project_id": str(w.project_id), "document_id": str(doc.id), "status": "binding"},
            session_factory=w.factory,
        )


def catalogue_body_with_forms(keep: tuple[str, ...]) -> dict[str, Any]:
    """The shipped delivery forms catalogue reduced to the forms in ``keep`` (every reference to another form removed)."""
    import json

    from app.modules.delivery_model.catalogue import CATALOGUE_DIR

    body = json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))
    body["forms"] = [f for f in body["forms"] if f["code"] in keep]
    for allocation in body["default_allocations"]:
        allocation["forms"] = [code for code in allocation["forms"] if code in keep]
    body["default_allocations"] = [a for a in body["default_allocations"] if a["forms"]]
    for criterion in body["criteria"]:
        criterion["scores"] = {code: v for code, v in criterion["scores"].items() if code in keep}
    body["package_templates"] = [t for t in body["package_templates"] if t["form"] in keep]
    return body
