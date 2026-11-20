"""/api/v1/design endpoints for converter-imported models (R16, contract §8/§9a). Registered by ``register``."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from app.dependencies import SessionDep

from . import imported
from .auth import PrincipalDep, require_project
from .schemas import RevisionView


class ImportRequest(BaseModel):
    bim_model_id: uuid.UUID
    depth_level: Literal["D1", "D2", "D3", "D4", "D5"] | None = None


async def held_lock(session, project_id: uuid.UUID):
    from app.modules.collaboration_locks.service import CollabLockService

    from .router import LOCK_ENTITY

    return await CollabLockService(session).get_for_entity(entity_type=LOCK_ENTITY, entity_id=project_id)


def register(router, require_publisher) -> None:
    """``require_publisher(session, user_id)`` is the module's publish check (403 for read-only roles)."""

    @router.get("/projects/{project_id}/imported-models")
    async def imported_models(project_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> list[dict]:
        await require_project(principal, project_id, session)
        return [
            {
                "bim_model_id": str(m.id),
                "name": m.name,
                "model_format": m.model_format or "",
                "element_count": m.element_count,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in await imported.candidates(session, project_id)
        ]

    @router.post(
        "/projects/{project_id}/revisions/import", response_model=RevisionView, status_code=status.HTTP_201_CREATED
    )
    async def import_revision(
        project_id: uuid.UUID, body: ImportRequest, principal: PrincipalDep, session: SessionDep
    ) -> RevisionView:
        from app.modules.bim_hub.models import BIMModel

        from .models import DesignRevision

        await require_project(principal, project_id, session)
        if principal.via_link:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Imported models are added in the ERP")
        await require_publisher(session, principal.user_id)
        model = await session.get(BIMModel, body.bim_model_id)
        if model is None or model.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found in this project")
        held = await held_lock(session, project_id)
        if held is not None:  # the editor bases its next upload on the chain tip; nothing joins the chain under it
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                {
                    "message": "Project is being edited",
                    "held_by": held.user_name,
                    "expires_at": held.expires_at.isoformat(),
                },
            )
        try:
            rev = await imported.wrap(session, model, user_id=principal.user_id, depth_level=body.depth_level)
            revision_id = rev.id
            await session.commit()
        except imported.NotWrappable as exc:
            await session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "Another revision was added at the same time") from exc
        return RevisionView.of(await session.get(DesignRevision, revision_id, populate_existing=True))
