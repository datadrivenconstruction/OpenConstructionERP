# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate-basis demo seed - a versioned basis of estimate per demo project.

Drafts the qualification document that goes out with a price: what is included,
what is excluded, and what was assumed. Nothing here is written by hand. Every
line is produced by the module's own :mod:`.derivation` engine reading the
project's real BOQ, its real allowances register and its real preliminaries, so
the trades listed as included are the trades the estimate actually prices and
the allowance lines quote the amounts the allowances screen shows.

Documents are versioned rather than overwritten, which is how the module works,
so a project carries a short history: the concept-design basis signed off
earlier in the job, the tender issue behind it, and the current draft on top.
The older ones are ``final``; the newest is a ``draft`` carrying two edits an
estimator would really make - a standard exclusion switched off because the
scope does include it, and a project-specific assumption typed in by hand. That
is what turns the screen from a generated list into a document somebody owns.

Every version also carries the three judgements the platform will not make on
anybody's behalf: the AACE estimate class, what the market was doing when the
estimate was priced, and why the contingency is the size it is. They are seeded
rather than left blank because a demo whose class reads "not stated" shows the
reader the empty state instead of the feature, and because the class is what a
version history is really a history of - the concept issue is a class 4 and the
tender issue is a class 2, and the accuracy band on screen moves with it.

Every write goes through :class:`EstimateBasisService`, the same layer the API
uses, so a document this seeder cannot produce is a document the application
would have rejected too.

Generation dates are anchored to the run date, never hardcoded, so the history
still reads as recent a year from now.

Acts on the demo estate only, and on all of it. Every project handed in is
considered - there is no "flagship plus a few" cap, which is how a screen ends
up permanently empty on the projects that fell outside it. A project outside the
estate is declined outright rather than merely skipped as already-seeded: see
:func:`_is_demo_project`. On top of that, a project that already carries a basis
document is left untouched, so a re-run never doubles the history.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.estimate_basis.models import EstimateBasis
from app.modules.estimate_basis.schemas import QualificationItem, UpdateRequest
from app.modules.estimate_basis.service import EstimateBasisService

logger = logging.getLogger(__name__)

# Lifecycle statuses (mirrors the schema's own ``Literal["draft", "final"]``).
_DRAFT = "draft"
_FINAL = "final"

# Fewest priced line items a project needs before a basis of estimate says
# anything. Below this the derivation finds no trades and the document would be
# the standard exclusions alone, which reads as a template rather than a basis.
_MIN_PRICED_POSITIONS = 6


@dataclass(frozen=True)
class _Version:
    """One document in a project's basis history.

    ``age_days`` is how far back the generation is stamped, ``status`` is where
    the document ended up, and ``notes`` is the estimator's own commentary on
    the version.

    ``estimate_class`` is the AACE class the estimator STATED on that version -
    the judgement the platform suggests but never makes. It is seeded because a
    demo document with the class left unanswered would show the reader the
    empty state rather than the feature, and because the class is what the
    version history is really a history of. ``market_conditions`` and
    ``contingency_rationale`` are the two paragraphs no derivation can write.
    """

    title: str
    age_days: int
    status: str
    notes: str
    estimate_class: int
    market_conditions: str
    contingency_rationale: str


# The history a project carries, newest last. Every project gets the concept and
# current versions; longer registers also carry the tender issue between them,
# so two demo projects opened side by side do not show the same number of
# versions.
_CONCEPT = _Version(
    title="Basis of estimate - concept design",
    age_days=132,
    status=_FINAL,
    notes=(
        "Issued with the concept cost plan. Superseded by the tender issue; retained "
        "because the client's approval was given against these qualifications."
    ),
    estimate_class=4,
    market_conditions=(
        "Priced against the published regional rate base with no market test. Tender "
        "competition at concept stage was assumed to be three to four bidders on an "
        "open list, with no allowance for a constrained supply chain."
    ),
    contingency_rationale=(
        "Contingency set at the upper end of the concept range because the structural "
        "grid and the services strategy were both still open at this stage. It covers "
        "design development within the agreed area schedule, not scope growth beyond it."
    ),
)
_TENDER = _Version(
    title="Basis of estimate - tender issue",
    age_days=47,
    status=_FINAL,
    notes=(
        "Issued with the tender return. Exclusions unchanged from concept; the "
        "allowances were re-sized against the co-ordinated design."
    ),
    estimate_class=2,
    market_conditions=(
        "Rates are the returned tender prices, not a rate base. Four returns were "
        "received against the full bill and the analysis sits within a normal spread. "
        "No allowance is made for a bidder withdrawing before award."
    ),
    contingency_rationale=(
        "Contingency reduced against the concept figure: the design is co-ordinated "
        "and the quantities are measured from it. What remains covers the "
        "provisional sums still open and the ground risk carried below."
    ),
)
_CURRENT = _Version(
    title="Basis of estimate - current estimate",
    age_days=3,
    status=_DRAFT,
    notes=(
        "Working draft against the current estimate. Not yet issued - the ground "
        "conditions line is still with the geotechnical engineer."
    ),
    estimate_class=2,
    market_conditions=(
        "Held at the tender basis. Material prices have moved since the returns were "
        "opened and the movement is inside the band below; if it continues past the "
        "stated pricing date the estimate is to be re-based rather than stretched."
    ),
    contingency_rationale=(
        "Unchanged from the tender issue pending the geotechnical report. If the "
        "report confirms the assumed bearing stratum the contingency can come down; "
        "if it does not, the ground exclusion below becomes a priced item."
    ),
)

# Projects at an even position in the seeding call carry the full three-version
# history; the rest carry two. Indexed by position rather than drawn from the
# project id so the split is even rather than lucky.
_HISTORIES: tuple[tuple[_Version, ...], ...] = (
    (_CONCEPT, _TENDER, _CURRENT),
    (_CONCEPT, _CURRENT),
)

# The standard exclusion the current draft switches off, because on a live job
# somebody always finds one that does not apply. ``exc-prof-fees`` is drafted on
# every document by ``_STANDARD_EXCLUSIONS``, so the toggle always has a target.
_DISABLED_EXCLUSION_ID = "exc-prof-fees"

# The hand-typed assumption on the current draft. Deliberately the kind of line
# no deriver could produce - a site-specific access constraint - so the screen
# shows an auto line and a manual line side by side.
_MANUAL_ASSUMPTION_ID = "asm-manual-access"
_MANUAL_ASSUMPTION_TEXT = (
    "Deliveries are assumed to be restricted to a single booked slot per day through the "
    "shared site access, with no out-of-hours craneage."
)


def _is_demo_project(metadata: dict | None) -> bool:
    """Whether a project row belongs to the demo estate.

    The gate this seeder is allowed to act behind, and the reason it is not
    "does the project have a basis yet": the boot backfill runs over every
    project in the database and re-runs on every version upgrade, so on a
    customer installation a real project with no basis of estimate is handed
    here and looks exactly like an unseeded demo one. Publishing an invented
    qualification document inside it is a data incident, not a cosmetic one.

    ``demo_id`` is the key that covers the whole estate. The ten templates stamp
    it alongside ``is_demo``; the flagship reference project is built from its
    own baked fixture and stamps ``demo_id`` without ``is_demo``, so a gate on
    ``is_demo`` would skip the project users actually land on.

    Read from the fetched value rather than matched in SQL: ``metadata_`` is a
    JSON column, and a containment test against it compiles to a string LIKE on
    PostgreSQL rather than to JSONB containment.
    """
    if not isinstance(metadata, dict):
        return False
    return bool(str(metadata.get("demo_id") or "").strip())


async def _priced_position_count(session: AsyncSession, project_id: uuid.UUID) -> int:
    """Count the project's priced line items the derivation would actually read.

    Section headers carry no unit and are dropped by the service, so the gate
    counts the same rows the engine sees rather than every row in the BOQ.
    """
    try:
        from app.modules.boq.models import BOQ, Position

        stmt = (
            select(func.count())
            .select_from(Position)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id, Position.unit.notin_(("", "section")))
        )
        return int((await session.execute(stmt)).scalar_one())
    except Exception:
        logger.debug("BOQ lookup unavailable for project=%s", project_id)
        return 0


async def _base_date(session: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The estimate's stated base date, taken from the project's own BOQ.

    Ranked by :func:`app.modules.boq.base_date.latest_base_date` rather than by
    ``max()`` in SQL: ``base_date`` is free text holding a day, a month, a
    quarter or a year, and those strings do not sort in the order their dates
    run - ``"2026-Q1"`` sorts above ``"2026-12-01"``.
    """
    try:
        from app.modules.boq.base_date import latest_base_date
        from app.modules.boq.models import BOQ

        stmt = select(BOQ.base_date).where(BOQ.project_id == project_id, BOQ.base_date.is_not(None))
        return latest_base_date((await session.execute(stmt)).scalars().all())
    except Exception:
        return None


def _items(raw: list | None, category: str) -> list[QualificationItem]:
    """Read a stored qualification list back as validated schema items.

    A line the engine wrote that the schema will not accept is a line the API
    would refuse to serve, so validating here rather than editing the raw dicts
    keeps the seeded document inside the same contract as an edited one.
    """
    out: list[QualificationItem] = []
    for entry in raw or []:
        data = dict(entry)
        data["category"] = category
        out.append(QualificationItem.model_validate(data))
    return out


def _estimator_edit(doc: EstimateBasis, version: _Version) -> UpdateRequest:
    """Build the edit an estimator would make to the current draft.

    Switches off one standard exclusion that does not apply to this job (the
    line stays in the document, disabled, which is how the module records a
    deliberate removal) and adds one hand-typed assumption. The exported
    Markdown writes only enabled lines, so the toggle is visible in the export
    as well as on the screen.
    """
    exclusions = _items(doc.exclusions, "exclusion")
    for item in exclusions:
        if item.id == _DISABLED_EXCLUSION_ID:
            item.enabled = False

    assumptions = _items(doc.assumptions, "assumption")
    assumptions.append(
        QualificationItem(
            id=_MANUAL_ASSUMPTION_ID,
            category="assumption",
            text=_MANUAL_ASSUMPTION_TEXT,
            basis="manual",
            source="manual",
            enabled=True,
        )
    )
    return UpdateRequest(
        status=version.status,
        notes=version.notes,
        exclusions=exclusions,
        assumptions=assumptions,
        estimate_class=version.estimate_class,
        market_conditions=version.market_conditions,
        contingency_rationale=version.contingency_rationale,
    )


async def _seed_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    currency: str,
    owner_id: uuid.UUID,
    ordinal: int,
) -> dict[str, int]:
    """Seed one project's basis history. Returns per-entity counts (zeros when skipped)."""
    empty = {"projects": 0, "documents": 0, "qualifications": 0, "edits": 0}

    already = (
        (await session.execute(select(EstimateBasis.id).where(EstimateBasis.project_id == project_id).limit(1)))
        .scalars()
        .first()
    )
    if already is not None:
        return empty

    priced = await _priced_position_count(session, project_id)
    if priced < _MIN_PRICED_POSITIONS:
        # Without a priced estimate there is no basis to state: the derivation
        # would find no trades and draft the standard boilerplate alone.
        logger.debug(
            "Estimate basis demo skipped for project=%s (%d priced position(s))",
            project_id,
            priced,
        )
        return empty

    base_date = await _base_date(session, project_id)
    history = _HISTORIES[ordinal % len(_HISTORIES)]
    service = EstimateBasisService(session)
    counts = {"projects": 1, "documents": 0, "qualifications": 0, "edits": 0}
    now = datetime.now(UTC)

    for version in history:
        doc = await service.generate(
            project_id=project_id,
            boq_id=None,
            title=version.title,
            currency=currency,
            base_date=base_date,
            created_by=owner_id,
        )
        # ``generate`` stamps the derivation at "now", which is right for the
        # working draft and wrong for a version issued four months ago. Move the
        # stamp onto the day the version was actually issued; ``generated_at`` is
        # the document's own column, not a row timestamp.
        doc.generated_at = (now - timedelta(days=version.age_days)).isoformat()

        if version.status == _DRAFT:
            payload = _estimator_edit(doc, version)
            counts["edits"] += 1
        else:
            payload = UpdateRequest(
                status=version.status,
                notes=version.notes,
                estimate_class=version.estimate_class,
                market_conditions=version.market_conditions,
                contingency_rationale=version.contingency_rationale,
            )
        await service.update_document(doc, payload)

        counts["documents"] += 1
        counts["qualifications"] += len(doc.inclusions or []) + len(doc.exclusions or []) + len(doc.assumptions or [])

    return counts


async def seed_estimate_basis_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Draft the basis-of-estimate history for the demo projects.

    A reader who opens the Basis of estimate screen afterwards lands on a working
    draft carrying thirty or more qualification lines - one inclusion per trade
    the estimate actually prices, an exclusion per expected trade that is missing
    plus the eight standard exclusions, and assumptions naming the project's own
    allowances and preliminaries by amount. (Without an allowances register
    beside it the same document still carries around twenty lines; the register
    is what takes it past thirty.) Behind it sits the issued history
    (concept design, and on longer registers the tender issue) marked ``final``,
    so the version list is a list rather than a single row. One standard
    exclusion on the draft is switched off and one assumption is hand-typed, so
    the auto / manual distinction the editor draws is visible on screen.

    Args:
        session: Async DB session. The caller commits.
        project_ids: Projects to consider - every one of them, never a first few.
            A project is skipped when it is not part of the demo estate, when it
            already carries a basis document, or when it has too few priced line
            items for the derivation to say anything.

    Returns:
        Dict with per-entity insert counts across every project seeded.
    """
    totals = {"projects": 0, "documents": 0, "qualifications": 0, "edits": 0}
    ids = list(project_ids)
    if not ids:
        return totals

    from app.modules.projects.models import Project

    rows = (
        await session.execute(
            select(Project.id, Project.currency, Project.owner_id, Project.metadata_).where(Project.id.in_(ids)),
        )
    ).all()
    # Currency is sliced to the length the generate request accepts, so a
    # project carrying a longer code cannot produce a document the API would
    # refuse to draft.
    known = {pid: (str(ccy or "").strip().upper()[:8], owner, meta) for pid, ccy, owner, meta in rows}

    # Demo projects only. The position that picks a version history counts only
    # those, so the two histories stay evenly split on an installation that also
    # holds projects of its own.
    targets: list[tuple[uuid.UUID, str, uuid.UUID]] = []
    for project_id in ids:
        found = known.get(project_id)
        if found is None:
            continue
        currency, owner_id, metadata = found
        if owner_id is None or not _is_demo_project(metadata):
            continue
        targets.append((project_id, currency, owner_id))

    for ordinal, (project_id, currency, owner_id) in enumerate(targets):
        try:
            # A SAVEPOINT per project, so one project that cannot be seeded costs
            # only its own rows. Catching the exception is not enough on
            # PostgreSQL: a failed statement aborts the whole transaction, and
            # every later project would then fail on a poisoned session rather
            # than on anything wrong with itself.
            async with session.begin_nested():
                counts = await _seed_project(session, project_id, currency, owner_id, ordinal)
        except Exception:
            logger.warning("Estimate basis demo seed skipped for project=%s (non-fatal)", project_id, exc_info=True)
            continue
        for key, value in counts.items():
            totals[key] += value
    return totals


__all__ = ["seed_estimate_basis_demo"]
