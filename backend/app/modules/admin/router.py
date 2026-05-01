"""Admin API routes.

Endpoints:
    POST /qa-reset       — reset the demo dataset (triple-gated)
"""

import logging

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.dependencies import SessionDep
from app.modules.admin.service import GateError, check_gates, reset_demo_data

router = APIRouter()
logger = logging.getLogger(__name__)


class QAResetRequest(BaseModel):
    """Body for POST /qa-reset.

    ``confirm_token`` must equal ``os.environ['QA_RESET_TOKEN']`` server-side.
    ``tenant`` must equal ``"demo"`` — the only resettable tenant.
    """

    tenant: str = Field(default="demo", description="Tenant to reset; only 'demo' is allowed.")
    confirm_token: str = Field(min_length=1, description="Shared secret matching QA_RESET_TOKEN env.")


class QAResetResponse(BaseModel):
    reset: bool
    demo_users: list[str]
    deleted_projects: int
    seeded_projects: int
    seeded_demo_ids: list[str]
    took_ms: int


@router.post(
    "/qa-reset",
    response_model=QAResetResponse,
    summary="Reset demo dataset (QA crawler baseline)",
    description=(
        "Hard-deletes all projects owned by the demo accounts and re-seeds the "
        "canonical 5 demo projects. Idempotent — safe to call repeatedly. "
        "Triple-gated by env (QA_RESET_ALLOWED=1), shared-secret token, and "
        "hostname check (refuses production). Use only against dev/staging."
    ),
)
async def qa_reset(
    body: QAResetRequest,
    request: Request,
    session: SessionDep,
) -> QAResetResponse:
    hostname = request.url.hostname
    try:
        check_gates(
            hostname=hostname,
            confirm_token=body.confirm_token,
            tenant=body.tenant,
        )
    except GateError as exc:
        logger.warning(
            "qa-reset rejected: code=%s host=%s", exc.code, hostname,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    try:
        result = await reset_demo_data(session)
    except GateError as exc:
        # Sanity-cap gate fires inside the service after the cheaper checks
        # so the error path is the same shape.
        logger.warning(
            "qa-reset aborted by service gate: code=%s host=%s", exc.code, hostname,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception:
        logger.exception("qa-reset failed unexpectedly")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "qa_reset_internal_error", "message": "Unexpected failure during reset."},
        )

    return QAResetResponse(**result)
