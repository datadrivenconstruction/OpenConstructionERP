"""/api/v1/design estimate endpoints (R6). Registered on the module router by ``register``."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import SessionDep

from . import cost_suggest, links, rules
from . import estimate as est
from .auth import PrincipalDep, require_project
from .models import DesignRevision


class RuleListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    offset: int = 0
    limit: int = 50


class StarterRequest(BaseModel):
    country: str = Field(min_length=2, max_length=2)


class ReasonRequest(BaseModel):
    reason: str = Field(max_length=2000)


class PriceRequest(BaseModel):
    cost_item_id: uuid.UUID | None = None
    unit_rate: Decimal | None = Field(default=None, ge=0)
    source_url: str | None = Field(default=None, max_length=1000)
    price_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class ConfirmRequest(BaseModel):
    """A person's pick among the ERP's suggestions: a Cost Match result + item, or an assembly."""

    result_id: uuid.UUID | None = None
    cost_item_id: uuid.UUID | None = None
    assembly_id: uuid.UUID | None = None


class RunRequest(BaseModel):
    revision_id: uuid.UUID | None = None


def register(router, can_accept) -> None:
    """``can_accept(session, user_id, project)`` is the module's project-manager check."""

    async def manager(principal, project_id: uuid.UUID, session) -> None:
        from app.modules.projects.models import Project

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "The estimate is managed in the ERP")
        project = await session.get(Project, project_id)
        if not await can_accept(session, principal.user_id, project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a project manager may change the estimate")

    @router.get("/projects/{project_id}/estimate/rules", response_model=RuleListResponse)
    async def list_rules(
        project_id: uuid.UUID,
        principal: PrincipalDep,
        session: SessionDep,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> RuleListResponse:
        await require_project(principal, project_id, session)
        rows = await est._rule_rows(session, project_id)
        return RuleListResponse(
            items=[
                {"id": r.code, "kind": r.kind, "enabled": r.enabled, **r.body} for r in rows[offset : offset + limit]
            ],
            total=len(rows),
            offset=offset,
            limit=limit,
        )

    @router.post("/projects/{project_id}/estimate/rules/starter", status_code=status.HTTP_201_CREATED)
    async def install_starter(
        project_id: uuid.UUID, body: StarterRequest, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        doc = rules.starter_set(body.country.upper())
        if doc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"No starter rule set for country {body.country.upper()}")
        e = await est.install_rules(session, project_id, doc, principal.user_id)
        await session.commit()
        return {"boq_id": str(e.boq_id), "rules": len(doc["rules"]), "country": e.country, "use": e.use}

    @router.post("/projects/{project_id}/estimate/rules", status_code=status.HTTP_201_CREATED)
    async def install_custom(
        project_id: uuid.UUID, body: dict[str, Any], principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        await manager(principal, project_id, session)
        try:
            e = await est.install_rules(session, project_id, body, principal.user_id)
        except rules.RulesError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        await session.commit()
        return {"boq_id": str(e.boq_id), "rules": len(body["rules"])}

    @router.post("/projects/{project_id}/estimate/run")
    async def run_rules(
        project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep, body: RunRequest | None = None
    ) -> dict[str, Any]:
        """Apply the rules to a revision: the given one, else the latest published, else the latest shared."""
        await manager(principal, project_id, session)
        q = select(DesignRevision).where(DesignRevision.project_id == project_id)
        if body and body.revision_id:
            q = q.where(DesignRevision.id == body.revision_id)
        else:
            q = q.where(DesignRevision.status.in_(("published", "shared"))).order_by(
                (DesignRevision.status == "published").desc(), DesignRevision.number.desc()
            )
        rev = (await session.execute(q.limit(1))).scalar_one_or_none()
        if rev is None or rev.bim_model_id is None or rev.status not in ("published", "shared"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No revision to run the rules on")
        rows = await est.recompute(session, project_id, rev.id, rev.bim_model_id, principal.user_id)
        await links.sync(session, project_id)  # BOQ, viewer and 4D see the elements
        await session.commit()
        return {"revision_id": str(rev.id), "positions": len(rows)}

    @router.get("/projects/{project_id}/estimate")
    async def get_estimate(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        return await est.summary(session, project_id)

    @router.get("/revisions/{revision_id}/impact")
    async def revision_impact(revision_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> dict[str, Any]:
        rev = await session.get(DesignRevision, revision_id)
        if rev is None or rev.status == "uploading":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found")
        await require_project(principal, rev.project_id, session)
        return await est.impact(session, rev)

    @router.put("/projects/{project_id}/estimate/positions/{position_id}/override-reason", status_code=204)
    async def override_reason(
        project_id: uuid.UUID, position_id: uuid.UUID, body: ReasonRequest, principal: PrincipalDep, session: SessionDep
    ) -> None:
        await manager(principal, project_id, session)
        await est.set_override_reason(session, project_id, position_id, body.reason)
        await session.commit()

    @router.post("/projects/{project_id}/estimate/positions/{position_id}/suggestions")
    async def suggestions(
        project_id: uuid.UUID, position_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
    ) -> dict[str, Any]:
        """Assemblies and a Cost Match run for a position without a direct cost item. Applies nothing."""
        await manager(principal, project_id, session)
        out = await cost_suggest.suggest(session, project_id, position_id, principal.user_id)
        await session.commit()  # the Cost Match run is kept as the evidence behind a later confirmation
        return out

    @router.post("/projects/{project_id}/estimate/positions/{position_id}/confirm-suggestion", status_code=204)
    async def confirm_suggestion(
        project_id: uuid.UUID,
        position_id: uuid.UUID,
        body: ConfirmRequest,
        principal: PrincipalDep,
        session: SessionDep,
    ) -> None:
        await manager(principal, project_id, session)
        if body.assembly_id is not None and body.result_id is None:
            await cost_suggest.confirm_assembly(session, project_id, position_id, body.assembly_id)
        elif body.result_id is not None and body.cost_item_id is not None and body.assembly_id is None:
            await cost_suggest.confirm_cost_match(
                session, project_id, position_id, body.result_id, body.cost_item_id, principal.user_id
            )
        else:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Give an assembly_id, or result_id with cost_item_id"
            )
        await session.commit()

    @router.post("/projects/{project_id}/estimate/positions/{position_id}/price", status_code=204)
    async def price(
        project_id: uuid.UUID, position_id: uuid.UUID, body: PriceRequest, principal: PrincipalDep, session: SessionDep
    ) -> None:
        await manager(principal, project_id, session)
        await est.price_position(
            session,
            project_id,
            position_id,
            cost_item_id=body.cost_item_id,
            unit_rate=body.unit_rate,
            source_url=body.source_url,
            price_date=body.price_date,
            currency=body.currency,
        )
        await session.commit()
