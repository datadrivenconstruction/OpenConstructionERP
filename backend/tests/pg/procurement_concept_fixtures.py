# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared builders for the procurement concept PostgreSQL tests.

A world is a throwaway database with real users (a manager, an editor who owns
the procurement area once a test names them, an editor who does not, an
outsider), an EUR project with team membership, module 3's package plan (built
from its table contract when module 3 itself is not installed in this tree),
and a concept for a public sub-central client under the shipped EU catalogue.

Governance is real: the project pins a shipped phase model, so its areas, gates
and frame documents are the rows governance itself builds, and the module finds
its area, its frame document and its release gate through the model's tags.
The constants below are read off that model the same way, so no test names a
code of it. ``tagged=False`` pins a company copy of the model with the
procurement tags removed and every code kept; ``from_start=True`` pins a
company copy whose first phase enables procurement, so no gate leads into the
phase that opens it; ``model=False`` pins no phase model at all, so governance
has no row for the project.
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model.models import DeliveryModel
from app.modules.procurement_concept import plan_source as plan
from app.modules.procurement_concept.events import handle_frame_document
from app.modules.procurement_concept.hosting import CAPABILITY, SUBJECT, hosting_of
from app.modules.procurement_concept.service import ProcurementConceptService
from app.modules.project_governance.catalogue import list_catalogues
from tests.pg.governance_fixtures import add_project, add_user

MODEL_ID = "neutral"
MODEL = next(c for c in list_catalogues() if c.id == MODEL_ID)
HOSTING = hosting_of(MODEL)
AREA = HOSTING.area_code
DOC_TYPE = HOSTING.document_types[0]
RELEASE_GATE = HOSTING.release_gate_codes[0]
GATE_CODES = tuple(g.code for g in MODEL.gates)
OTHER_GATE = next(code for code in GATE_CODES if code not in HOSTING.release_gate_codes)
#: A gate the model asks for the host document at, and that is not the release gate.
HOST_GATE = next(
    code
    for code in next(d for d in MODEL.document_types if d.code == DOC_TYPE).required_at_gates
    if code not in HOSTING.release_gate_codes
)
OTHER_AREA = next(a.code for a in MODEL.areas if a.code != AREA)
OTHER_DOC = next(d.code for d in MODEL.document_types if d.code != DOC_TYPE)
#: A document type that hosts no subject, so a company model may require it at no gate.
UNGATED_DOC = next(d.code for d in MODEL.document_types if not d.hosts)


@dataclass
class World:
    factory: async_sessionmaker[AsyncSession]
    project_id: uuid.UUID
    manager: uuid.UUID
    area_owner: uuid.UUID
    editor: uuid.UUID
    outsider: uuid.UUID
    packages: dict[str, uuid.UUID] = field(default_factory=dict)
    gates: dict[str, uuid.UUID] = field(default_factory=dict)
    area_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


async def ensure_plan_tables(factory: async_sessionmaker[AsyncSession]) -> None:
    """Module 3's two tables, created from the table contract only where module 3 did not create them."""
    async with factory() as s:
        conn = await s.connection()
        await conn.run_sync(lambda c: plan.stand_in_metadata().create_all(c, checkfirst=True))
        await s.commit()


async def add_contract_package(
    w: World, code: str, kind: str, *, parent: str | None = None, need_date: str | None = None
) -> uuid.UUID:
    pid = uuid.uuid4()
    async with w.factory() as s:
        await s.execute(
            sa.insert(plan.PACKAGE_TABLE).values(
                id=pid,
                project_id=w.project_id,
                code=code,
                title=f"{code} package",
                kind=kind,
                parent_id=w.packages.get(parent) if parent else None,
                scope=f"Scope of {code}",
                wbs_ref="",
                boq_ref="",
                need_date=need_date,
                status="planned",
                sort_order=len(w.packages),
            )
        )
        await s.commit()
    w.packages[code] = pid
    return pid


async def set_delivery_form(w: World, form: str, *, public_client: bool = True) -> None:
    async with w.factory() as s:
        await s.execute(
            sa.insert(DeliveryModel.__table__).values(
                id=uuid.uuid4(),
                project_id=w.project_id,
                catalogue_id="neutral",
                catalogue_version=1,
                selected_form_code=form,
                status="approved",
                owner_capability={"public_client": public_client},
            )
        )
        await s.commit()


async def add_procurement_area(w: World, owner: uuid.UUID | None, code: str = AREA) -> uuid.UUID:
    """Name the owner of one of the project's areas (the one that hosts procurement unless told otherwise)."""
    from app.modules.project_governance.models import GovernanceArea

    async with w.factory() as s:
        area = (
            await s.execute(
                sa.select(GovernanceArea).where(GovernanceArea.project_id == w.project_id, GovernanceArea.code == code)
            )
        ).scalar_one()
        area.owner_user_id = owner
        await s.commit()
        return area.id


async def add_frame_document(w: World, *, status: str = "draft", doc_type: str = DOC_TYPE) -> uuid.UUID:
    """Put one of the project's frame documents (the one that hosts procurement by default) into a status."""
    from app.modules.project_governance.models import GovernanceDocument

    async with w.factory() as s:
        doc = (
            await s.execute(
                sa.select(GovernanceDocument).where(
                    GovernanceDocument.project_id == w.project_id, GovernanceDocument.doc_type == doc_type
                )
            )
        ).scalar_one()
        doc.status = status
        await s.commit()
        return doc.id


async def drop_frame_document(w: World) -> None:
    """A project pinned before its model hosted procurement: the host document has no row."""
    from app.modules.project_governance.models import GovernanceDocument

    async with w.factory() as s:
        await s.execute(sa.delete(GovernanceDocument).where(GovernanceDocument.id == w.document_id))
        await s.commit()
    w.document_id = None


async def add_decision(w: World, gate_code: str, *, outcome: str = "go", by: uuid.UUID | None = None) -> uuid.UUID:
    from app.modules.project_governance.models import GovernanceDecision

    async with w.factory() as s:
        earlier = await s.execute(
            sa.select(sa.func.count())
            .select_from(GovernanceDecision)
            .where(GovernanceDecision.gate_id == w.gates[gate_code])
        )
        d = GovernanceDecision(
            project_id=w.project_id,
            gate_id=w.gates[gate_code],
            gate_code=gate_code,
            # One decision per attempt of a gate (governance's own unique rule).
            attempt_no=earlier.scalar_one() + 1,
            outcome=outcome,
            decided_by=by or w.manager,
            decided_at=datetime.now(UTC),
        )
        s.add(d)
        await s.commit()
        return d.id


async def add_condition(w: World, gate_code: str, *, status: str = "open") -> uuid.UUID:
    from app.modules.project_governance.models import GovernanceCondition

    decision_id = await add_decision(w, gate_code, outcome="go_with_conditions")
    async with w.factory() as s:
        c = GovernanceCondition(
            project_id=w.project_id,
            decision_id=decision_id,
            gate_id=w.gates[gate_code],
            gate_code=gate_code,
            text="Fabrication slot reserved in writing",
            status=status,
        )
        s.add(c)
        await s.commit()
        return c.id


async def set_condition(w: World, condition_id: uuid.UUID, status: str) -> None:
    from app.modules.project_governance.models import GovernanceCondition

    async with w.factory() as s:
        (await s.get(GovernanceCondition, condition_id)).status = status
        await s.commit()


async def bind_frame_document(w: World, *, by: uuid.UUID | None = None, notify: bool = True) -> bool:
    """What a go at the gate does in governance: the frame document becomes binding.

    Returns what the module's subscriber answered for the resulting event.
    """
    from app.modules.project_governance.models import GovernanceDocument

    await add_decision(w, RELEASE_GATE, by=by or w.manager)
    async with w.factory() as s:
        doc = await s.get(GovernanceDocument, w.document_id)
        doc.status = "binding"
        doc.approved_gate_id = w.gates[RELEASE_GATE]
        await s.commit()
    if not notify:
        return False
    return await handle_frame_document(
        {"project_id": str(w.project_id), "document_id": str(w.document_id), "status": "binding"},
        session_factory=w.factory,
    )


async def approve(w: World, *, submitter: uuid.UUID | None = None, by: uuid.UUID | None = None) -> None:
    """Submit the concept and let governance approve it (there is no other way to an approved concept)."""
    await svc_call(w, "transition", w.project_id, "in_review", actor_id=submitter or w.manager, can_manage=True)
    assert await bind_frame_document(w, by=by) is True


async def _company_model(
    session: AsyncSession, manager: uuid.UUID, *, from_start: bool, ungated_doc: bool = False
) -> str:
    """A published company copy of the shipped model with its procurement tags changed, every code kept.

    ``from_start=False``: it says nothing about procurement. ``from_start=True``:
    the host document stays and the first phase, which no gate leads into, is
    the only one that enables procurement. ``ungated_doc=True`` also has
    the model require :data:`UNGATED_DOC`, which hosts nothing, at no gate.
    The host document itself cannot be left without a gate: governance
    refuses such a model from every source.
    """
    from app.modules.project_governance.catalogue_store import CatalogueStore

    store = CatalogueStore(session)
    tenant = str(manager)
    row = await store.create(
        tenant,
        code="from_start" if from_start else "untagged",
        name="Model that opens procurement at once" if from_start else "Model without procurement tags",
        based_on_source="shipped",
        based_on_id=MODEL_ID,
        based_on_version=None,
        actor_id=manager,
    )
    body = copy.deepcopy(dict(row.draft_body))
    if not from_start:
        for doc in body["document_types"]:
            doc["hosts"] = [h for h in doc.get("hosts") or [] if h != SUBJECT]
    for phase in body["phases"]:
        phase["enables"] = [c for c in phase.get("enables") or [] if c != CAPABILITY]
    if from_start:
        first = min(body["phases"], key=lambda p: p["order"])
        first["enables"] = [*first["enables"], CAPABILITY]
    if ungated_doc:
        for doc in body["document_types"]:
            if doc["code"] == UNGATED_DOC:
                doc["required_at_gates"] = []
    await store.update_draft(tenant, row.id, body=body, name=None)
    await store.publish(tenant, row.id, actor_id=manager)
    return str(row.id)


async def _read_governance_rows(w: World) -> None:
    from app.modules.project_governance.models import GovernanceArea, GovernanceDocument, GovernanceGate

    async with w.factory() as s:
        gates = await s.execute(
            sa.select(GovernanceGate.code, GovernanceGate.id).where(GovernanceGate.project_id == w.project_id)
        )
        w.gates = dict(gates.all())
        w.area_id = (
            await s.execute(
                sa.select(GovernanceArea.id).where(
                    GovernanceArea.project_id == w.project_id, GovernanceArea.code == AREA
                )
            )
        ).scalar_one()
        w.document_id = (
            await s.execute(
                sa.select(GovernanceDocument.id).where(
                    GovernanceDocument.project_id == w.project_id, GovernanceDocument.doc_type == DOC_TYPE
                )
            )
        ).scalar_one()


async def build_world(
    factory: async_sessionmaker[AsyncSession],
    *,
    concept: bool = True,
    tagged: bool = True,
    model: bool = True,
    from_start: bool = False,
    ungated_doc: bool = False,
) -> World:
    from app.modules.procurement_concept.catalogue import register_kind
    from app.modules.project_governance.service import GovernanceService

    register_kind()
    await ensure_plan_tables(factory)
    async with factory() as s:
        manager = await add_user(s, "manager")
        area_owner = await add_user(s, "editor")
        editor = await add_user(s, "editor")
        outsider = await add_user(s, "manager")
        pid = await add_project(s, manager, [area_owner, editor])
        source, model_id = "shipped", MODEL_ID
        if from_start or not tagged:
            source, model_id = (
                "tenant",
                await _company_model(s, manager, from_start=from_start, ungated_doc=ungated_doc),
            )
        if model:
            await GovernanceService(s).set_model(
                pid,
                source=source,
                catalogue_id=model_id,
                version=None,
                four_eyes=True,
                actor_id=manager,
                tenant_id=str(manager),
            )
        await s.commit()
    w = World(factory, pid, manager, area_owner, editor, outsider)
    if model:
        await _read_governance_rows(w)
    if concept:
        async with factory() as s:
            await ProcurementConceptService(s).set_concept(
                pid,
                {
                    "catalogue_source": "shipped",
                    "catalogue_id": "eu",
                    "jurisdiction": "eu",
                    "client_type": "sub_central",
                    "public_client": True,
                },
                actor_id=manager,
                can_manage=True,
                tenant_id=str(manager),
            )
            await s.commit()
    return w


async def put(
    w: World, code: str, data: dict[str, Any], *, actor: uuid.UUID | None = None, can_manage: bool = True
) -> Any:
    async with w.factory() as s:
        row = await ProcurementConceptService(s).put_package(
            w.project_id,
            w.packages[code],
            data,
            actor_id=actor or w.manager,
            can_manage=can_manage,
            tenant_id=str(w.manager),
        )
        await s.commit()
        return row


async def svc_call(w: World, fn: str, *args: Any, **kw: Any) -> Any:
    async with w.factory() as s:
        out = await getattr(ProcurementConceptService(s), fn)(*args, **kw)
        await s.commit()
        return out


async def execute(w: World, code: str, **kw: Any) -> dict[str, Any]:
    return await svc_call(
        w,
        "create_execution",
        w.project_id,
        w.packages[code],
        vehicle=kw.pop("vehicle", None),
        submission_deadline=None,
        actor_id=kw.pop("actor", w.manager),
        can_manage=kw.pop("can_manage", True),
    )
