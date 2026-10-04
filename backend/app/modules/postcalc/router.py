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

    GET /projects/{project_id}/quantity-check?boq_id=&snapshot_id=
    PUT /projects/{project_id}/quantity-check/baseline

The quantity check compares, per bill position, the contract quantity frozen in
the bill's quantity baseline with the quantity the site measured, and prices the
difference at the contract rate (see ``quantity_check``). The PUT names which
snapshot of the bill is the baseline, or freezes one; it needs ``boq.update``
and writes only that pointer, never a quantity or price.

Reads need viewer access to the project, and access is verified first so a caller
can never read the productivity of a project they cannot see.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.postcalc.quantity_check import QuantityCheckError, load_quantity_check
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


def _quantity_check_not_found() -> HTTPException:
    # One answer for a bill or snapshot that does not exist and one that
    # belongs to another project, so the reply says nothing about the latter.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bill or baseline not found in this project")


@router.get(
    "/projects/{project_id}/quantity-check",
    response_model=None,
    dependencies=[_READ],
)
async def get_quantity_check(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    boq_id: uuid.UUID | None = Query(
        default=None, description="The bill to check; the project's first bill if omitted"
    ),
    snapshot_id: uuid.UUID | None = Query(
        default=None,
        description="Read the contract quantities from this snapshot of the bill instead of its designated baseline",
    ),
) -> dict:
    """Contract quantity against measured quantity, per position of one bill.

    The contract side is the bill's quantity baseline (a snapshot, captured
    when the bill is first locked or chosen by a person), or the live bill
    with a ``no_baseline`` warning when there is none. The measured side is
    each position's measurement sheet, typed in or written by a GAEB X31
    apply, and the source is named per line. Money is the difference at the
    contract unit rate, net of bill markups, in the bill's currency.
    """
    await verify_project_access(project_id, user_id, session)
    try:
        return await load_quantity_check(session, project_id, boq_id=boq_id, snapshot_id=snapshot_id)
    except QuantityCheckError:
        raise _quantity_check_not_found() from None


class QuantityBaselineRequest(BaseModel):
    """Which snapshot a bill's quantity check compares against."""

    boq_id: uuid.UUID
    snapshot_id: uuid.UUID | None = Field(
        default=None,
        description="The snapshot to use as the baseline. Leave empty with freeze=false to clear the baseline.",
    )
    freeze: bool = Field(
        default=False,
        description="Snapshot the bill as it stands now and make that the baseline. Ignores snapshot_id.",
    )


@router.put(
    "/projects/{project_id}/quantity-check/baseline",
    response_model=None,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def set_quantity_baseline(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    body: QuantityBaselineRequest = Body(...),
) -> dict:
    """Name the snapshot a bill's contract quantities are read from, or freeze one now.

    Allowed on a locked bill: the pointer changes no price or quantity of the
    bill, only what the quantity check compares against.
    """
    from sqlalchemy import select

    from app.modules.boq.models import BOQ, BOQSnapshot
    from app.modules.boq.quantity_baseline import designate_baseline, freeze_baseline

    await verify_project_access(project_id, user_id, session)
    boq_project = (await session.execute(select(BOQ.project_id).where(BOQ.id == body.boq_id))).scalar_one_or_none()
    if boq_project != project_id:
        raise _quantity_check_not_found()
    if body.freeze:
        await freeze_baseline(session, body.boq_id, user_id=user_id)
    elif body.snapshot_id is not None:
        owner = (
            await session.execute(select(BOQSnapshot.boq_id).where(BOQSnapshot.id == body.snapshot_id))
        ).scalar_one_or_none()
        if owner != body.boq_id:
            raise _quantity_check_not_found()
        await designate_baseline(session, body.boq_id, body.snapshot_id, user_id=user_id)
    else:
        await designate_baseline(session, body.boq_id, None, user_id=user_id)
    try:
        return await load_quantity_check(session, project_id, boq_id=body.boq_id, snapshot_id=None)
    except QuantityCheckError:
        raise _quantity_check_not_found() from None
