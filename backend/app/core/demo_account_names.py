# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The display names of the three demo logins, in the language of the demo they appear in.

The demo logins carried placeholder names ("Elena Marchetti", "Anna Musterfrau", "Michael Carter")
that showed up in approval lines, handbook signatures and gate decisions of filmed German projects.
They are now invented names with the part each login plays, one set per demo language. The emails
never change, so every existing install keeps signing in as before.

Two moments set the name, and neither ever overwrites a name somebody chose:

* the boot seeder creates the logins with the English set, and renames a login that still carries
  one of the retired placeholders to that set (:func:`retire_placeholder_names`);
* installing a demo told in another language (a pack project whose ``locale`` has a set here)
  renames a login that still carries a default name of any language to that language's set
  (:func:`name_demo_accounts_for`). The boot never renames back, so a German pack demo keeps its
  German names across restarts.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEMO_EMAIL = "demo@openconstructionerp.com"
ESTIMATOR_EMAIL = "estimator@openconstructionerp.com"
MANAGER_EMAIL = "manager@openconstructionerp.com"

#: Language -> login email -> display name. The admin owns and steers the demo projects, the estimator
#: is the cost role of every four-eyes step, the manager is the client's decider at the gates.
DEMO_ACCOUNT_NAMES: dict[str, dict[str, str]] = {
    "en": {
        DEMO_EMAIL: "Claire Donovan, Project Controls",
        ESTIMATOR_EMAIL: "Owen Hartley, Cost Management",
        MANAGER_EMAIL: "Rachel Ainsworth, Client Representative",
    },
    "de": {
        DEMO_EMAIL: "Julia Hofmann, Projektsteuerung",
        ESTIMATOR_EMAIL: "Tobias Kessler, Kostenplanung",
        MANAGER_EMAIL: "Katrin Seidl, Bauherrenvertretung",
    },
}

DEFAULT_LANGUAGE = "en"

#: The placeholder names the logins carried before, per email.
RETIRED_PLACEHOLDERS: dict[str, str] = {
    DEMO_EMAIL: "Elena Marchetti",
    ESTIMATOR_EMAIL: "Anna Musterfrau",
    MANAGER_EMAIL: "Michael Carter",
}


def demo_account_name(email: str, language: str = DEFAULT_LANGUAGE) -> str:
    """The display name of a demo login in ``language``, the English one for a language without a set."""
    names = DEMO_ACCOUNT_NAMES.get(_language(language), DEMO_ACCOUNT_NAMES[DEFAULT_LANGUAGE])
    return names[email]


def _language(locale: str | None) -> str:
    return (locale or "").split("-")[0].split("_")[0].lower()


def _default_names(email: str) -> set[str]:
    return {names[email] for names in DEMO_ACCOUNT_NAMES.values()} | {RETIRED_PLACEHOLDERS[email]}


async def _rename(session: AsyncSession, language: str, *, only_retired: bool) -> int:
    from app.modules.users.models import User

    renamed = 0
    for email in RETIRED_PLACEHOLDERS:
        user = (await session.execute(select(User).where(func.lower(User.email) == email))).scalar_one_or_none()
        if user is None:
            continue
        current = (user.full_name or "").strip()
        replaceable = {RETIRED_PLACEHOLDERS[email]} if only_retired else _default_names(email)
        target = demo_account_name(email, language)
        if current in replaceable and current != target:
            user.full_name = target
            renamed += 1
    if renamed:
        await session.flush()
        logger.info("demo accounts renamed to the %s set: %s", language, renamed)
    return renamed


async def retire_placeholder_names(session: AsyncSession) -> int:
    """Rename a demo login still carrying a retired placeholder to the English set. The caller commits."""
    return await _rename(session, DEFAULT_LANGUAGE, only_retired=True)


async def name_demo_accounts_for(session: AsyncSession, project_ids: list[uuid.UUID] | None) -> dict[str, Any]:
    """Give the demo logins the names of the language the given pack demo projects are told in.

    Only a project installed by a pack (``metadata_["partner_pack"]``) with a locale that has a set
    here decides; generic demos keep whatever the logins are called. A login whose name somebody
    changed is never touched. The caller commits.
    """
    from app.modules.projects.models import Project

    if not project_ids:
        return {"language": None, "renamed": 0}
    rows = (await session.execute(select(Project.locale, Project.metadata_).where(Project.id.in_(project_ids)))).all()
    languages = {
        _language(locale)
        for locale, meta in rows
        if isinstance(meta, dict) and meta.get("partner_pack") and _language(locale) in DEMO_ACCOUNT_NAMES
    }
    if len(languages) != 1:
        return {"language": None, "renamed": 0}
    (language,) = languages
    return {"language": language, "renamed": await _rename(session, language, only_retired=False)}


__all__ = [
    "DEMO_ACCOUNT_NAMES",
    "RETIRED_PLACEHOLDERS",
    "demo_account_name",
    "name_demo_accounts_for",
    "retire_placeholder_names",
]
