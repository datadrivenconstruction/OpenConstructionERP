# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""When the seeded demo administrator is an administrator, and when not.

A person who installs the platform for themselves with the demo seed on signs
in through the "Admin" tile on the login page, which is the password-free demo
login for ``demo@openconstructionerp.com``. Everything a new install is for
(installing a country pack, a cost base, switching modules) is admin only, so
that account has to be an administrator there, including on an install created
by an older release or by a seeder script that wrote the row as a viewer.

Two things limit that, and both live here so the seeder and the login ask the
same questions:

* The public hosted demo keeps its demo rows as they are. It runs with
  ``OE_DEMO_MODE`` (and may add ``OE_DEMO_READ_ONLY``), and on it the demo
  accounts are viewers on purpose. With either flag set nothing is promoted.
* A password-free admin session is only acceptable while nobody has taken the
  install over. Once a real administrator exists, the promotion stops and the
  demo login refuses an account that would sign in as admin, because anyone
  who can reach the port could otherwise take that session. The row itself is
  left alone: the operator may still sign in to it with its password.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.demo_accounts import DEMO_ADMIN_EMAIL

logger = logging.getLogger(__name__)

#: Machine-readable key of the demo-login refusal, matched by the login page.
DEMO_ADMIN_SUPERSEDED = "demo_admin_superseded"

#: Fallback copy for clients that are not our login page.
DEMO_ADMIN_SUPERSEDED_MESSAGE = (
    "This installation has an administrator, so the demo administrator account "
    "can no longer be opened without a password. Please sign in with your own account."
)


def demo_admin_promotion_allowed() -> bool:
    """False on the public hosted demo, True on an installation someone runs for themselves."""
    from app.core.demo_privacy import demo_mode_enabled
    from app.core.demo_read_only import demo_read_only_enabled

    return not demo_mode_enabled() and not demo_read_only_enabled()


async def reconcile_demo_admin_role(session: AsyncSession) -> bool:
    """Make the seeded demo administrator an admin where that is still safe.

    Runs on every boot from the demo seeder, so an install created by an older
    release or by a script that wrote the row as a viewer is repaired on its
    next start. Changes nothing on the public demo, nothing once a real admin
    exists, and nothing for a deactivated row. Returns True when it promoted.
    """
    from app.modules.users.models import User
    from app.modules.users.repository import UserRepository

    if not demo_admin_promotion_allowed():
        return False
    if await UserRepository(session).has_admin():
        return False
    user = (await session.execute(select(User).where(func.lower(User.email) == DEMO_ADMIN_EMAIL))).scalar_one_or_none()
    if user is None or not user.is_active or user.role == "admin":
        return False
    logger.info(
        "Demo administrator %s promoted from %s to admin (no real admin on this install)", user.email, user.role
    )
    user.role = "admin"
    await session.flush()
    return True
