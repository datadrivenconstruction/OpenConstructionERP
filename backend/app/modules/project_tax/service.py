# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project tax profile: derive, save, and refuse a change inside the lock.

Two rules shape this service.

**An edition is stored, never inferred from today.** A project that states no
edition gets a proposal from the day the project was created: the newest
edition of its standard already in force then. The proposal is returned with
``stored=False`` and is not written, so an old project keeps reading as old
until a person confirms otherwise, and a priced bill is never re-labelled.

**A tax method election is locked.** Where the election carries a lock period,
leaving the method before the lock ends is refused here, not only flagged,
because a return already filed on the elected method cannot be refiled by a
screen. The method left behind is kept in ``method_history``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.item_codes import editions as standard_editions
from app.core.item_codes import standard_entry, standard_for_country
from app.core.line_tax import default_edition, lock_ends_on, method_change_locked
from app.modules.project_tax import repository
from app.modules.project_tax.models import ProjectTaxProfile
from app.modules.project_tax.schemas import EditionOption, ProfileResponse, ProfileUpdate

_FIELDS = tuple(ProfileUpdate.model_fields)


class ProfileLockedError(Exception):
    """A change of tax method inside the election's lock period."""

    def __init__(self, ends_on: date, election: date | None) -> None:
        super().__init__(f"The tax method is locked until {ends_on.isoformat()}")
        self.ends_on = ends_on
        self.election = election


def _created_on(project: Any) -> date | None:
    value = getattr(project, "created_at", None)
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def standard_for_project(project: Any) -> str | None:
    """The classification standard whose editions apply to this project.

    The project's own standard when it has editions; otherwise the standard
    whose data names the project's country. ``None`` for a market with no
    edition data, which is most of them.
    """
    own = str(getattr(project, "classification_standard", "") or "").strip().lower()
    if own and standard_entry(own).get("editions"):
        return own
    return standard_for_country(str(getattr(project, "country_code", "") or ""))


def _cross_region(row: Any) -> bool | None:
    site = (getattr(row, "site_city", None) or "").strip().lower()
    home = (getattr(row, "home_city", None) or "").strip().lower()
    if site and home:
        return site != home
    site_sub = (getattr(row, "site_subdivision", None) or "").strip().upper()
    home_sub = (getattr(row, "home_subdivision", None) or "").strip().upper()
    if site_sub and home_sub and site_sub != home_sub:
        return True
    return None


def to_response(project: Any, row: ProjectTaxProfile | None) -> ProfileResponse:
    """The response for ``project``: the stored row, or a derived proposal."""
    standard = standard_for_project(project)
    options = [EditionOption(**e) for e in standard_editions(standard)] if standard else []
    if row is not None:
        data = {name: getattr(row, name) for name in _FIELDS}
        response = ProfileResponse(
            project_id=project.id,
            stored=True,
            edition_source="stored" if row.standard_edition else "none",
            method_history=list(row.method_history or []),
            **data,
        )
        response.cross_region = _cross_region(row)
        response.lock_ends_on = lock_ends_on(row.election_date, row.lock_months)
        response.editions = options
        return response
    proposed = default_edition([e.model_dump() for e in options], _created_on(project)) if options else None
    return ProfileResponse(
        project_id=project.id,
        stored=False,
        edition_source="derived" if proposed else "none",
        standard_edition=proposed,
        editions=options,
    )


def apply_update(
    row: ProjectTaxProfile,
    update: ProfileUpdate,
    *,
    today: date,
    is_new: bool,
) -> ProjectTaxProfile:
    """Write ``update`` onto ``row``, refusing a method change inside the lock.

    A method change on a stored row moves the old election into the history and
    starts a new election, dated as stated or today.

    Raises:
        ProfileLockedError: The method changes before the current lock ends.
    """
    changing = not is_new and row.tax_method != update.tax_method
    if changing:
        if method_change_locked(row.election_date, row.lock_months, today):
            ends = lock_ends_on(row.election_date, row.lock_months)
            assert ends is not None
            raise ProfileLockedError(ends, row.election_date)
        history = list(row.method_history or [])
        history.append(
            {
                "method": row.tax_method,
                "election_date": row.election_date.isoformat() if row.election_date else None,
                "changed_on": today.isoformat(),
            }
        )
        row.method_history = history
    for name in _FIELDS:
        setattr(row, name, getattr(update, name))
    if changing and update.election_date is None:
        row.election_date = today
    return row


async def save_profile(
    session: AsyncSession,
    project: Any,
    update: ProfileUpdate,
    *,
    user_id: str | None,
    today: date | None = None,
) -> ProjectTaxProfile:
    """Create or update the profile of ``project``."""
    row = await repository.get_for_project(session, project.id)
    is_new = row is None
    if row is None:
        row = ProjectTaxProfile(project_id=project.id, method_history=[])
    apply_update(row, update, today=today or date.today(), is_new=is_new)
    row.updated_by = user_id
    return await repository.save(session, row)


def record_for_rules(project: Any, profile: ProfileResponse) -> dict[str, Any]:
    """The plain dict the profile rules read."""
    return {
        "record_type": "project_tax_profile",
        "project_id": str(project.id),
        "country_code": getattr(project, "country_code", None),
        **profile.model_dump(mode="json"),
    }
