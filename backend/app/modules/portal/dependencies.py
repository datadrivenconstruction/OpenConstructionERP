# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Module-local FastAPI dependencies for the Customer & Partner Portal.

We deliberately do NOT touch the global :mod:`app.dependencies` — portal
authentication is a parallel surface to the internal JWT auth used by
``RequirePermission``. Internal admins use the internal auth; portal users
use the magic-link + session-token flow defined here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.dependencies import SessionDep
from app.modules.portal.models import PortalUser
from app.modules.portal.service import PortalService

_portal_bearer = HTTPBearer(auto_error=False, scheme_name="PortalSession")


async def get_current_portal_user(
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_portal_bearer),
    ] = None,
) -> PortalUser:
    """‌⁠‍Validate the ``Authorization: Bearer <token>`` header against
    :meth:`PortalService.verify_session`. Raises 401 on any failure.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal session required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    svc = PortalService(session)
    user = await svc.verify_session(credentials.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired portal session",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_portal_session_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_portal_bearer),
    ] = None,
) -> str:
    """‌⁠‍Return the raw bearer token for revocation endpoints. Raises 401 if absent."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Portal session required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# ── Type aliases ──────────────────────────────────────────────────────────

RequirePortalSession = Annotated[PortalUser, Depends(get_current_portal_user)]
PortalSessionToken = Annotated[str, Depends(get_current_portal_session_token)]


__all__ = [
    "PortalSessionToken",
    "RequirePortalSession",
    "get_current_portal_session_token",
    "get_current_portal_user",
]
