"""``GET /projects/{id}/validation``: the ``design`` rule set over one project (see validators)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query

from app.dependencies import SessionDep

from .auth import PrincipalDep, require_project
from .validators import run


def register(router: APIRouter) -> None:
    @router.get("/projects/{project_id}/validation")
    async def design_validation(
        project_id: uuid.UUID,
        principal: PrincipalDep,
        session: SessionDep,
        locale: str = Query(default="en", max_length=12),
    ) -> dict[str, Any]:
        await require_project(principal, project_id, session)
        data, report = await run(session, project_id, locale)
        return {
            "checked": {"positions": len(data["design_positions"]), "revisions": len(data["revisions"])},
            "findings": [
                {
                    "rule_id": r.rule_id,
                    "severity": str(r.severity),
                    "message": r.message,
                    "suggestion": r.suggestion,
                    "ref": r.element_ref,
                }
                for r in report.results
                if not r.passed and not r.is_engine_error
            ],
        }
