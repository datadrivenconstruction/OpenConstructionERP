"""Wave 23 — worldwide currency parameterisation helper.

Provides :func:`resolve_template_currency` — the authoritative
resolution chain for any document / report render that needs to know
which ISO 4217 currency to use.

Resolution order
----------------
1. ``override_currency`` — caller / template-level override.
2. ``project_id`` → ``Project.currency`` — per-project default.
3. ``tenant_currency`` — reserved for future per-tenant setting; always
   ``None`` today (the tenant model has no ``default_currency`` yet).
4. Hard fallback: ``"EUR"``.

Blocking 422
------------
When ``require_resolved=True`` the function raises
:class:`fastapi.HTTPException` 422 if *no* currency could be resolved
(i.e. the project row is missing *and* no override was supplied). This
is the 422 path described in the task spec for document template renders
that must never emit a currency-less PDF.

Usage
-----
::

    from app.modules.reporting.currency_resolver import resolve_template_currency

    # In an async endpoint or service method:
    currency = await resolve_template_currency(
        session=db,
        project_id=project_id,
        override_currency=template.override_currency,
        require_resolved=True,   # 422 if nothing resolves
    )
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    import uuid as _uuid_mod

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: ISO 4217 fallback currency — used when neither override nor project
#: currency is available and ``require_resolved`` is ``False``.
CURRENCY_FALLBACK = "EUR"


async def resolve_template_currency(
    *,
    session: AsyncSession,
    project_id: _uuid_mod.UUID | None = None,
    override_currency: str | None = None,
    tenant_currency: str | None = None,
    require_resolved: bool = False,
) -> str:
    """Resolve the effective ISO 4217 currency for a document / report render.

    Resolution order:
        1. ``override_currency`` — e.g. from ``PropertyDevCustomTemplate.override_currency``
           or ``GenerateReportRequest.override_currency``.
        2. Project's ``currency`` field (looked up via ``project_id``).
        3. ``tenant_currency`` — reserved placeholder; always ``None`` today.
        4. Hard fallback ``"EUR"`` (unless ``require_resolved=True``).

    Args:
        session: Active async SQLAlchemy session.
        project_id: UUID of the owning project.  May be ``None`` for
            portfolio-wide reports.
        override_currency: Caller-supplied ISO 4217 code (3 chars).
        tenant_currency: Reserved for future per-tenant default; pass
            ``None`` for now.
        require_resolved: When ``True`` and no currency can be resolved
            (project missing, no override), raise ``HTTP 422`` rather
            than returning the hard fallback.

    Returns:
        Resolved ISO 4217 currency code (upper-cased, 3 chars).

    Raises:
        HTTPException: 422 when ``require_resolved=True`` and no currency
            is resolvable.
    """
    # 1. Caller override.
    if override_currency:
        code = override_currency.strip().upper()
        if code:
            return code

    # 2. Project currency.
    if project_id is not None:
        try:
            from sqlalchemy import select

            from app.modules.projects.models import Project

            row = (await session.execute(select(Project.currency).where(Project.id == project_id))).scalar_one_or_none()
            if row and isinstance(row, str) and row.strip():
                return row.strip().upper()
        except Exception:
            logger.debug(
                "resolve_template_currency: project lookup failed for %s",
                project_id,
            )

    # 3. Tenant currency (reserved — always None today).
    if tenant_currency:
        code = tenant_currency.strip().upper()
        if code:
            return code

    # 4. Fallback.
    if require_resolved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Cannot resolve currency for this document: the project has no "
                "default_currency configured and no override_currency was supplied. "
                "Please set the project currency or provide an override_currency."
            ),
        )

    return CURRENCY_FALLBACK
