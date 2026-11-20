"""Who is calling: an ERP session (JWT) or a linked editor (project-scoped ``ddcl_`` token).

Link tokens are stored as sha256 only, die with the user's password change (the token's
creation time is passed as ``iat`` to the ERP's own check), and work for one project only.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update

from app.dependencies import SessionDep, get_optional_user_payload, verify_user_exists_and_active

TOKEN_PREFIX = "ddcl_"
LINK_VERSIONS = (1,)
_MAJOR = re.compile(r"0|[1-9][0-9]{0,5}")


def new_secret(prefix: str = "") -> str:
    return prefix + secrets.token_urlsafe(32)


def digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def now_utc() -> datetime:
    return datetime.now(UTC)


def as_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    via_link: bool
    project_id: uuid.UUID | None  # set for link tokens: the only project they may touch


async def link_version(x_ddc_link: Annotated[str | None, Header()] = None) -> int | None:
    """The highest contract major both sides speak; 426 when there is none or the header is malformed.

    The header is one canonical decimal or a comma-separated list of them (``1`` or ``1,2``);
    int() alone would accept "+1", "01" and "1_0".
    """
    if x_ddc_link is None:
        return None
    parts = [p.strip() for p in x_ddc_link.split(",")]
    offered = [int(p) for p in parts if _MAJOR.fullmatch(p)]
    common = [m for m in offered if m in LINK_VERSIONS]
    major = max(common) if common and len(offered) == len(parts) else -1
    if major not in LINK_VERSIONS:
        raise HTTPException(
            status_code=status.HTTP_426_UPGRADE_REQUIRED,
            detail={"message": "Unsupported X-DDC-Link version", "supported": list(LINK_VERSIONS)},
        )
    return major


def _bearer(request: Request) -> str | None:
    scheme, _, param = (request.headers.get("Authorization") or "").partition(" ")
    return param if scheme.lower() == "bearer" and param else None


async def get_principal(
    request: Request,
    session: SessionDep,
    payload: Annotated[dict[str, Any] | None, Depends(get_optional_user_payload)],
    _version: Annotated[int | None, Depends(link_version)],
) -> Principal:
    token = _bearer(request)
    if token and token.startswith(TOKEN_PREFIX):
        from .models import DesignLinkToken

        row = (
            await session.execute(select(DesignLinkToken).where(DesignLinkToken.token_hash == digest(token)))
        ).scalar_one_or_none()
        now = now_utc()
        if row is None or row.revoked_at is not None or as_aware(row.expires_at) <= now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Link token invalid or expired")
        await verify_user_exists_and_active(
            str(row.user_id), issued_at=int(as_aware(row.created_at).timestamp()), session_id=None
        )
        await session.execute(update(DesignLinkToken).where(DesignLinkToken.id == row.id).values(last_used_at=now))
        return Principal(user_id=row.user_id, via_link=True, project_id=row.project_id)
    if payload is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return Principal(user_id=uuid.UUID(str(payload["sub"])), via_link=False, project_id=None)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def require_project(principal: Principal, project_id: uuid.UUID, session) -> None:
    """Link tokens are bound to one project; every caller must still have ERP access to it."""
    from app.dependencies import verify_project_access

    if principal.project_id is not None and principal.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    await verify_project_access(project_id, str(principal.user_id), session)
