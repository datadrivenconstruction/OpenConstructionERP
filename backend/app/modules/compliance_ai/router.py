# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Compliance-AI router - health + NL → DSL verify endpoint.

The actual NL-to-DSL conversion lives in :mod:`app.core.validation.dsl.
nl_builder` so the router stays a thin envelope. Hardening shipped here
(vs the sibling :mod:`app.modules.compliance` route):

* ``check_ai_rate_limit`` is wired *unconditionally* (the sibling route
  did not enforce it) - closes the LLM cost-runaway path a scripted
  client could exploit by toggling ``use_ai=true`` in a tight loop.
* Auth is required (returns 401 without a JWT) so the cost bucket is
  always attributable to a real user.
* Service emits a structured verdict log + ``compliance.nl_rule.
  generated`` event via ``_log_failures`` (no silent task drops).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.dependencies import (
    CurrentUserPayload,
    SessionDep,
    check_ai_rate_limit,
)
from app.modules.compliance_ai.manifest import manifest
from app.modules.compliance_ai.schemas import (
    NlVerifyRequest,
    NlVerifyResponse,
)
from app.modules.compliance_ai.service import verify_nl_rule

# NOTE: no ``prefix=`` here - the module loader mounts this router at
# ``/api/v1/compliance-ai`` automatically (see
# :func:`app.core.module_loader.ModuleLoader._load_module`). Setting a
# prefix locally would double-mount as
# ``/api/v1/compliance-ai/compliance-ai`` and is a latent bug from the
# original skeleton.
router = APIRouter(tags=["Compliance AI"])


@router.get("/_health", include_in_schema=False)
async def module_health() -> dict[str, str]:
    return {
        "module": manifest.name,
        "version": manifest.version,
        "status": "healthy",
    }


@router.post(
    "/from-nl",
    response_model=NlVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Convert plain-language text into a Compliance DSL verdict",
)
async def from_nl(
    body: NlVerifyRequest,
    payload: CurrentUserPayload,
    session: SessionDep,
    _ai_remaining: int = Depends(check_ai_rate_limit),
) -> NlVerifyResponse:
    """Verify an NL rule and return the resulting DSL + verdict envelope.

    Rate-limited via :func:`check_ai_rate_limit` (default 10/min/user,
    overridable via ``AI_RATE_LIMIT``) so a runaway client cannot drive
    unbounded LLM cost when ``use_ai=true``.
    """
    user_id = payload.get("sub") or payload.get("user_id")
    return await verify_nl_rule(
        body,
        user_id=str(user_id) if user_id else None,
        session=session,
    )


__all__ = ["manifest", "router"]
