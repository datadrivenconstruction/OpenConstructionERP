# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The project-derived half of a validation payload, built in one place.

A rule reads its inputs from the mapping the caller hands the engine, and a
rule whose input is missing returns nothing rather than failing. So a surface
that assembles that mapping by hand does not get a smaller report - it gets a
report silently missing whatever the absent key would have decided, and no exit
code says so. That is not hypothetical: ``BOQUnitSystemConsistencyRule`` shipped
registered and enabled while every caller omitted the one key it reads, and when
one caller finally wrote it the others carried on without it, so the same bill
answered differently depending on which button ran it.

The split this module draws is between the two halves of such a payload. The
rows are the caller's own: a bill, a contract's schedule of values and a
pipeline's upstream rows are projected differently on purpose, and forcing one
projection on all of them would change what every rule sees. Anything derived
from the *project* is not the caller's own, because it is the same fact whoever
asks. This module owns that half, and every surface that validates rows calls
it, so a new surface inherits a key it has never heard of.

The keys are always written, nulls included. An absent key and a null one used
to mean the same thing - "nothing to check" - which is exactly why a payload
nobody built properly was indistinguishable from a project no regional pack
claims. Now a null says the question was asked and nothing answered, and an
absent key says nobody asked at all.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.core.regional_packs import resolve_measurement_system

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: The key under which the project record itself travels. The
#: ``project_completeness`` rules read the project, not the bill, so the
#: facts they judge (country, currency, dates, client, which bills exist and
#: whether procurement has started) are carried here as one mapping rather
#: than as a dozen loose top-level keys.
PROJECT_RECORD_KEY = "project_record"

#: Every key this module contributes. Named so a test can assert the property
#: ("each surface reaches the engine with these") without repeating the list,
#: and so adding a key here reaches every surface at once.
PROJECT_CONTEXT_KEYS: tuple[str, ...] = ("project_unit_system", PROJECT_RECORD_KEY)

#: The contract party role that names the client. ``PARTY_ROLES`` in the
#: contracts schemas spells the client side of a construction contract
#: ``employer``, the term the standard forms use; a project with no
#: ``client_id`` still has a recorded client when a contract carries one.
CLIENT_PARTY_ROLE = "employer"


def _as_uuid(project_id: uuid.UUID | str | None) -> uuid.UUID | None:
    """Coerce a project id to :class:`uuid.UUID`, or ``None`` if it is not one."""
    if isinstance(project_id, uuid.UUID):
        return project_id
    if isinstance(project_id, str) and project_id.strip():
        try:
            return uuid.UUID(project_id.strip())
        except ValueError:
            return None
    return None


async def _measurement_system(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """Resolve the measurement system the project's regional pack declares.

    Args:
        session: Live session the caller owns.
        project_id: Project the validation run is scoped to.

    Returns:
        ``"metric"`` or ``"imperial"`` when the project's country (or, as a
        fallback, its region) resolves to a regional pack, otherwise ``None``.
    """
    from app.modules.projects.models import Project

    row = (await session.execute(select(Project.country_code, Project.region).where(Project.id == project_id))).first()
    if row is None:
        return None
    country_code, region = row
    return resolve_measurement_system(country_code=country_code, region=region)


async def _bills(session: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """The project's own bills of quantities, each with how many rows it holds.

    Variation bills are left out on purpose: a bill raised for one variation
    request prices that request's scope, not the project's estimate, and the
    project's bill register excludes them for the same reason. The position
    count comes from a grouped subquery rather than a join grouped on the bill,
    because the bill carries a JSON column and PostgreSQL has no equality for
    that type to group by.
    """
    from app.modules.boq.models import BOQ, Position

    counts = select(Position.boq_id, func.count().label("n")).group_by(Position.boq_id).subquery()
    stmt = (
        select(BOQ.id, BOQ.name, BOQ.status, BOQ.base_date, BOQ.metadata_, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.boq_id == BOQ.id)
        .where(BOQ.project_id == project_id, BOQ.variation_request_id.is_(None))
        .order_by(BOQ.name)
    )
    return [
        {
            "id": str(bill_id),
            "name": name,
            "status": status,
            "base_date": base_date,
            "metadata": metadata if isinstance(metadata, dict) else {},
            "position_count": int(position_count or 0),
        }
        for bill_id, name, status, base_date, metadata, position_count in (await session.execute(stmt)).all()
    ]


async def _contract_counts(session: AsyncSession, project_id: uuid.UUID) -> tuple[int | None, int | None]:
    """How many contracts the project has, and how many of their parties are the client.

    ``(None, None)`` when the contracts module is not installed: that is a
    question nobody can ask, and the rules that read these keep quiet on a
    null rather than reporting an absence the product has no register for.
    """
    try:
        from app.modules.contracts.models import Contract, ContractParty
    except ImportError:
        return None, None
    contracts = await session.scalar(
        select(func.count()).select_from(Contract).where(Contract.project_id == project_id)
    )
    client_parties = await session.scalar(
        select(func.count())
        .select_from(ContractParty)
        .join(Contract, Contract.id == ContractParty.contract_id)
        .where(Contract.project_id == project_id, ContractParty.party_role == CLIENT_PARTY_ROLE)
    )
    return int(contracts or 0), int(client_parties or 0)


async def _tender_count(session: AsyncSession, project_id: uuid.UUID) -> int | None:
    """How many tender packages the project has, or ``None`` without the tendering module."""
    try:
        from app.modules.tendering.models import TenderPackage
    except ImportError:
        return None
    count = await session.scalar(
        select(func.count()).select_from(TenderPackage).where(TenderPackage.project_id == project_id)
    )
    return int(count or 0)


async def _project_record(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any] | None:
    """The project as the completeness rules read it, or ``None`` for an unknown id.

    Only columns the project model actually has, and only children the tree
    actually records. A rule may then assert exactly what the data model can
    answer, and nothing here is a guess dressed as a fact: a null column is
    passed through as null, a module that is not installed yields a null count.
    """
    from app.modules.projects.models import Project

    row = (
        await session.execute(
            select(
                Project.id,
                Project.name,
                Project.country_code,
                Project.region,
                Project.currency,
                Project.classification_standard,
                Project.status,
                Project.phase,
                Project.planned_start_date,
                Project.planned_end_date,
                Project.client_id,
                Project.fx_rates,
            ).where(Project.id == project_id)
        )
    ).first()
    if row is None:
        return None
    contract_count, client_party_count = await _contract_counts(session, project_id)
    return {
        "id": str(row.id),
        "name": row.name,
        "country_code": row.country_code,
        "region": row.region,
        "currency": row.currency,
        "classification_standard": row.classification_standard,
        "status": row.status,
        "phase": row.phase,
        "planned_start_date": row.planned_start_date,
        "planned_end_date": row.planned_end_date,
        "client_id": row.client_id,
        # The project's hand-typed exchange rates, so a rule scaling a
        # threshold into the project currency converts by the same rates the
        # assembly prices do rather than by a table of its own.
        "fx_rates": list(row.fx_rates) if isinstance(row.fx_rates, list) else [],
        "bills": await _bills(session, project_id),
        "contract_count": contract_count,
        "client_party_count": client_party_count,
        "tender_count": await _tender_count(session, project_id),
    }


async def with_project_context(
    session: AsyncSession | None,
    project_id: uuid.UUID | str | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Return ``data`` plus the validation keys derived from its project.

    The session is the caller's own rather than one opened here. A validation
    run frequently happens inside a transaction that has not committed - the
    demo seeder validates projects it created moments earlier in the same unit
    of work - and a second session cannot see those rows, so it would resolve
    nothing and call the result "no pack answered".

    Args:
        session: The caller's live session. ``None`` is tolerated so a surface
            with no database in scope still produces a well-formed payload,
            and it is the one case where a null key means "could not ask"
            rather than "asked and nothing answered". The rule is silent
            either way, which is why the two are allowed to share a value;
            a caller that has a session should pass it rather than rely on it.
        project_id: Project the run is scoped to, as a UUID or its string form.
            ``None``, or an id no project matches, yields null keys.
        data: The caller's own payload - positions, markups, whatever its rules
            read. Left unmodified; a new mapping is returned.

    Returns:
        A new mapping carrying ``data`` plus every key in
        :data:`PROJECT_CONTEXT_KEYS`.
    """
    unit_system: str | None = None
    record: dict[str, Any] | None = None
    scoped = _as_uuid(project_id)
    if session is not None and scoped is not None:
        try:
            unit_system = await _measurement_system(session, scoped)
        except Exception:  # noqa: BLE001 - a payload is still owed to the caller
            # Degrading to a null key is safe in a way that omitting it is not:
            # null still says the question was asked, so the rule skips rather
            # than reporting that nobody built the payload.
            logger.warning("Could not resolve the measurement system for project=%s", scoped, exc_info=True)
        try:
            record = await _project_record(session, scoped)
        except Exception:  # noqa: BLE001 - same contract as the key above
            logger.warning("Could not load the project record for project=%s", scoped, exc_info=True)
    return {**data, "project_unit_system": unit_system, PROJECT_RECORD_KEY: record}
