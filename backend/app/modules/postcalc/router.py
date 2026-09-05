# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Post-calculation API routes.

Mounted at ``/api/v1/postcalc``. Two read-only endpoints that reconcile a
project's estimate against its site actuals, at the two grains the question is
asked at:

    GET /projects/{project_id}/productivity?format=json|markdown
    GET /projects/{project_id}/norm-outturn

The first is per bill line. ``format=json`` (default) returns the full structured
report; ``format=markdown`` returns the same numbers as an auditable Markdown
document. Optional ``tolerance`` (the on-plan band, default 0.05) and
``min_confidence`` (the installed-coverage floor for a feedback factor, default
0.10) tune the analysis.

The second is per production norm (issue #457), rolling up every position priced
from one, which is the grain a norm library is corrected at.

Reads need viewer access to the project, and access is verified first so a caller
can never read the productivity of a project they cannot see.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.postcalc.service import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_TOLERANCE,
    PostCalcService,
)

router = APIRouter()

_READ = Depends(RequirePermission("postcalc.read"))

_MARKDOWN_FORMATS = frozenset({"markdown", "md"})


@router.get(
    "/projects/{project_id}/productivity",
    response_model=None,
    dependencies=[_READ],
)
async def get_productivity(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    fmt: str = Query(default="json", alias="format", description="json (default) or markdown"),
    tolerance: float | None = Query(default=None, ge=0, le=1, description="On-plan band, e.g. 0.05 for 5%"),
    min_confidence: float | None = Query(
        default=None,
        ge=0,
        le=1,
        description="Installed-coverage floor for a feedback factor, e.g. 0.10",
    ),
) -> Response | dict:
    """Planned-vs-actual labour productivity for a project, as JSON or Markdown."""
    await verify_project_access(project_id, user_id, session)

    tol = Decimal(str(tolerance)) if tolerance is not None else DEFAULT_TOLERANCE
    conf = Decimal(str(min_confidence)) if min_confidence is not None else DEFAULT_MIN_CONFIDENCE
    service = PostCalcService(session)

    if fmt.strip().lower() in _MARKDOWN_FORMATS:
        body = await service.render_markdown(project_id, tolerance=tol, min_confidence=conf)
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="postcalc-{project_id}.md"'},
        )

    report = await service.generate(project_id, tolerance=tol, min_confidence=conf)
    return report.to_dict()


@router.get(
    "/projects/{project_id}/norm-outturn",
    response_model=None,
    dependencies=[_READ],
)
async def get_norm_outturn(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    tolerance: float | None = Query(default=None, ge=0, le=1, description="On-plan band, e.g. 0.05 for 5%"),
) -> dict:
    """Per production norm: what the estimate allowed against what it cost.

    The endpoint above answers this per bill line. This answers it per norm, by
    rolling up every position of the project that was priced from one. That is
    the grain an estimator corrects a norm library at: a norm is reused across a
    bill, so whether it held is a fact about all of its positions together and
    no single line answers it.

    Two baselines come back for each norm and neither is called simply the
    estimate. ``bill_*`` is what the priced line says, fixed when the bill was
    priced and already carrying the bid and regional factors. ``norm_*`` is what
    the library says today, read live and absent when the norm has since been
    deleted. They agree on the day a bill is priced and drift afterwards, and
    the drift is the interesting part.

    Scoped to one project, because money is per project and is reported in that
    project's base currency.
    """
    await verify_project_access(project_id, user_id, session)

    tol = Decimal(str(tolerance)) if tolerance is not None else DEFAULT_TOLERANCE
    report = await PostCalcService(session).norm_outturn(project_id, tolerance=tol)
    return report.to_dict()
