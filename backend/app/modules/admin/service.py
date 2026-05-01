"""Admin service — qa-reset implementation.

Resets the demo dataset to a known baseline so the QA crawler can run
idempotently. Three independent gates protect the destructive path:

* ``QA_RESET_ALLOWED=1`` env var (off by default)
* ``confirm_token`` body field == ``QA_RESET_TOKEN`` env var (constant-time)
* ``request.url.hostname`` matches a dev/staging pattern, never production

Only data owned by the demo accounts is touched; the user rows themselves
are preserved so subsequent logins keep working without re-seeding users.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)


DEMO_EMAILS: tuple[str, ...] = (
    "demo@openestimator.io",
    "estimator@openestimator.io",
    "manager@openestimator.io",
)

# Hostnames that look like dev/staging/qa. A hostname not in this list is
# treated as production — the gate refuses to run.
SAFE_HOSTNAME_SUBSTRINGS: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "staging",
    "test",
    "qa",
    "dev",
)

# Sanity ceiling: if the user count exceeds this, abort even if every other
# gate passed. Real production tenants will trip this trivially; the local
# demo install never gets near it.
MAX_USERS_FOR_RESET: int = 100


@dataclass
class GateError(Exception):
    """Raised when one of the three gates rejects the request.

    ``code`` is the machine-readable gate ID; ``message`` is shown to the
    operator. The HTTP layer maps this to a 403/503 response without
    leaking internals.
    """

    code: str
    message: str

    def __str__(self) -> str:  # noqa: D401
        return f"{self.code}: {self.message}"


def is_production_hostname(hostname: str | None) -> bool:
    """Return ``True`` when the hostname does NOT look like dev/staging.

    Conservative: missing hostname → production (refuse). Any safe substring
    match → not production.
    """
    if not hostname:
        return True
    lowered = hostname.lower()
    return not any(s in lowered for s in SAFE_HOSTNAME_SUBSTRINGS)


def check_gates(*, hostname: str | None, confirm_token: str | None, tenant: str) -> None:
    """Run all three safety gates. Raises :class:`GateError` on failure."""
    if os.environ.get("QA_RESET_ALLOWED", "").strip() != "1":
        raise GateError(
            code="qa_reset_disabled",
            message="QA reset is disabled (set QA_RESET_ALLOWED=1 on the backend process).",
        )

    expected = os.environ.get("QA_RESET_TOKEN", "")
    if not expected:
        raise GateError(
            code="qa_reset_token_unset",
            message="Server has no QA_RESET_TOKEN configured; refusing.",
        )
    if confirm_token is None or not hmac.compare_digest(expected, confirm_token):
        raise GateError(
            code="qa_reset_token_mismatch",
            message="Invalid confirm_token.",
        )

    if tenant != "demo":
        raise GateError(
            code="qa_reset_bad_tenant",
            message="Only the 'demo' tenant can be reset.",
        )

    if is_production_hostname(hostname):
        raise GateError(
            code="qa_reset_production_hostname",
            message="Refusing to run against a production-looking hostname.",
        )


async def _resolve_demo_user_ids(session: AsyncSession) -> list:
    rows = (
        await session.execute(select(User).where(User.email.in_(DEMO_EMAILS)))
    ).scalars().all()
    return [u.id for u in rows]


async def _sanity_user_count(session: AsyncSession) -> None:
    """Abort if total users > ceiling — production safeguard."""
    from sqlalchemy import func

    total = (
        await session.execute(select(func.count()).select_from(User))
    ).scalar() or 0
    if total > MAX_USERS_FOR_RESET:
        raise GateError(
            code="qa_reset_user_count_exceeded",
            message=(
                f"User table has {total} rows (> {MAX_USERS_FOR_RESET}); "
                "looks like production. Refusing."
            ),
        )


async def reset_demo_data(session: AsyncSession) -> dict:
    """Delete all demo-owned projects (cascades to BOQ/positions/etc.) and reseed.

    Returns a summary dict suitable for the API response.
    """
    started = time.monotonic()

    await _sanity_user_count(session)

    demo_user_ids = await _resolve_demo_user_ids(session)
    if not demo_user_ids:
        # Nothing to wipe; still attempt re-seed below so a fresh DB ends
        # up populated.
        logger.info("qa-reset: no demo users present, skipping wipe")

    # Delete all projects owned by demo users. CASCADE on FK takes care of
    # BOQ rows, positions, schedules, finance, etc. — we don't enumerate
    # every per-module table because the cascades are already set up.
    deleted_projects = 0
    if demo_user_ids:
        result = await session.execute(
            delete(Project).where(Project.owner_id.in_(demo_user_ids))
        )
        deleted_projects = result.rowcount or 0
        await session.flush()

    # Re-seed the canonical 5 demo projects under demo@openestimator.io.
    seeded = 0
    seeded_demo_ids: list[str] = []
    try:
        from app.core.demo_projects import install_demo_project

        for demo_id in (
            "residential-berlin",
            "office-london",
            "medical-us",
            "school-paris",
            "warehouse-dubai",
        ):
            try:
                result = await install_demo_project(
                    session, demo_id, force_reinstall=True
                )
                seeded += 1
                seeded_demo_ids.append(demo_id)
                logger.info(
                    "qa-reset: seeded demo %s (%s positions)",
                    demo_id,
                    result.get("positions"),
                )
            except Exception:
                logger.exception("qa-reset: failed to seed %s (continuing)", demo_id)
    except ImportError:
        logger.warning("qa-reset: demo_projects module not available; skipping reseed")

    # Audit log entry — best-effort, never blocks.
    try:
        from app.core.audit import audit_log

        await audit_log(
            session,
            action="qa_reset",
            entity_type="tenant",
            entity_id="demo",
            user_id=None,
            details={
                "demo_users": list(DEMO_EMAILS),
                "deleted_projects": deleted_projects,
                "seeded_projects": seeded,
                "seeded_demo_ids": seeded_demo_ids,
            },
        )
    except Exception:
        logger.exception("qa-reset: audit_log write failed (non-fatal)")

    took_ms = int((time.monotonic() - started) * 1000)
    return {
        "reset": True,
        "demo_users": list(DEMO_EMAILS),
        "deleted_projects": deleted_projects,
        "seeded_projects": seeded,
        "seeded_demo_ids": seeded_demo_ids,
        "took_ms": took_ms,
    }
