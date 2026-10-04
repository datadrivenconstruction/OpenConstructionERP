# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cross-project validation status: the latest report of every estimate.

A head of estimating wants one answer per project: which estimates failed
validation, which only warn, and which nobody has validated yet. The reports
already exist (``oe_validation_report``), so this module only reads them. It
never re-runs validation.

The read is a fixed set of statements whatever the size of the estate:

1. the projects the caller may access (the same rule every project read
   uses, archived projects left out, partner-pack scope applied),
2. the estimates of those projects (the project bill register, so the list
   matches what the BOQ page shows),
3. the newest report of each estimate, picked in SQL with a window function.

Ranking, worst first: ``errors`` > ``warnings`` > ``not_validated`` > ``info``
> ``passed``. An estimate without a report, or whose latest report did not
actually check anything, is ``not_validated`` and sits above everything that
did pass, so silence can never read as a clean bill of health.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.validation.schemas import (
    PortfolioEstimateStatus,
    PortfolioProjectStatus,
    PortfolioStateSummary,
    ValidationPortfolioResponse,
)

STATE_ERRORS = "errors"
STATE_WARNINGS = "warnings"
STATE_NOT_VALIDATED = "not_validated"
STATE_INFO = "info"
STATE_PASSED = "passed"

#: Lower is worse. The order a reader should look at things in.
STATE_RANK: dict[str, int] = {
    STATE_ERRORS: 0,
    STATE_WARNINGS: 1,
    STATE_NOT_VALIDATED: 2,
    STATE_INFO: 3,
    STATE_PASSED: 4,
}


def report_state(status: str | None, total_rules: int | None) -> str:
    """Map a stored report status to the state a reader sees.

    Only an outcome that says something about the estimate keeps its own
    state. ``pending``, ``skipped``, ``unsupported``, an unknown value and a
    missing report all become ``not_validated``. A ``passed`` report that ran
    no rules at all is also ``not_validated``: zero checks passed is not a
    pass. ``failed`` is a legacy spelling of ``errors``.
    """
    if status in (STATE_ERRORS, "failed"):
        return STATE_ERRORS
    if status in (STATE_WARNINGS, STATE_INFO):
        return status
    if status == STATE_PASSED and (total_rules or 0) > 0:
        return STATE_PASSED
    return STATE_NOT_VALIDATED


def worst_state(states: Iterable[str]) -> str:
    """The worst of ``states``, or ``not_validated`` when there are none."""
    worst = None
    for state in states:
        if worst is None or STATE_RANK.get(state, 0) < STATE_RANK.get(worst, 0):
            worst = state
    return worst if worst is not None else STATE_NOT_VALIDATED


def _rule_sets(meta_rule_sets: Any, rule_set: str | None) -> list[str]:
    """The rule sets a report ran, from its metadata or its ``a+b`` label."""
    if isinstance(meta_rule_sets, list) and meta_rule_sets and all(isinstance(x, str) for x in meta_rule_sets):
        names = meta_rule_sets
    else:
        names = (rule_set or "").split("+")
    return list(dict.fromkeys(n.strip() for n in names if n and n.strip()))


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, str) and x]


def _score(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _estimate_sort_key(e: PortfolioEstimateStatus) -> tuple[Any, ...]:
    return (STATE_RANK[e.state], -e.error_count, -e.warning_count, e.boq_name.lower(), str(e.boq_id))


def _project_sort_key(p: PortfolioProjectStatus) -> tuple[Any, ...]:
    return (
        STATE_RANK[p.state],
        -p.error_count,
        -p.warning_count,
        -p.not_validated_count,
        p.project_name.lower(),
        str(p.project_id),
    )


async def _visible_projects(session: AsyncSession, user_id: str) -> list[tuple[uuid.UUID, str]]:
    """``(id, name)`` of every live project the caller may open."""
    from app.core.partner_pack.scope import scope_project_query
    from app.dependencies import accessible_project_ids
    from app.modules.projects.models import Project

    ids = await accessible_project_ids(session, user_id, live_only=True)
    if not ids:
        return []
    stmt = select(Project.id, Project.name).where(Project.id.in_(list(ids)), Project.status != "archived")
    stmt = scope_project_query(stmt, Project)
    rows = (await session.execute(stmt)).all()
    return [(pid, name or "") for pid, name in rows]


async def build_portfolio_status(session: AsyncSession, user_id: str) -> ValidationPortfolioResponse:
    """Latest validation status of every estimate in every project the caller can see."""
    from app.modules.boq.models import BOQ
    from app.modules.validation.models import ValidationReport as VR

    projects = await _visible_projects(session, user_id)
    if not projects:
        return ValidationPortfolioResponse()
    project_ids = [pid for pid, _ in projects]

    # Column select only: the BOQ entity loads every position and markup
    # through its ``selectin`` relationships. ``variation_request_id IS NULL``
    # is the project bill register, the same filter the BOQ list applies.
    boq_rows = (
        await session.execute(
            select(BOQ.id, BOQ.project_id, BOQ.name).where(
                BOQ.project_id.in_(project_ids),
                BOQ.variation_request_id.is_(None),
            )
        )
    ).all()

    latest: dict[tuple[uuid.UUID, str], Any] = {}
    if boq_rows:
        register_ids = select(BOQ.id).where(
            BOQ.project_id.in_(project_ids),
            BOQ.variation_request_id.is_(None),
        )
        # Never the ``results`` column, and never the whole metadata blob: an
        # estimate audit keeps its findings there and they can be large.
        ranked = (
            select(
                VR.id,
                VR.project_id,
                VR.target_id,
                VR.rule_set,
                VR.status,
                VR.score,
                VR.total_rules,
                VR.passed_count,
                VR.warning_count,
                VR.error_count,
                VR.created_at,
                VR.metadata_["rule_sets"].label("meta_rule_sets"),
                VR.metadata_["unsupported_rule_sets"].label("meta_unsupported"),
                func.row_number()
                .over(
                    partition_by=(VR.project_id, VR.target_id),
                    order_by=(VR.created_at.desc(), VR.id.desc()),
                )
                .label("rn"),
            )
            .where(
                VR.target_type == "boq",
                VR.project_id.in_(project_ids),
                VR.target_id.in_(register_ids),
            )
            .subquery()
        )
        for row in (await session.execute(select(ranked).where(ranked.c.rn == 1))).all():
            latest[(row.project_id, str(row.target_id).lower())] = row

    estimates_by_project: dict[uuid.UUID, list[PortfolioEstimateStatus]] = {pid: [] for pid in project_ids}
    for boq_id, boq_project_id, boq_name in boq_rows:
        row = latest.get((boq_project_id, str(boq_id).lower()))
        estimates_by_project.setdefault(boq_project_id, []).append(_estimate(boq_id, boq_name, row))

    out: list[PortfolioProjectStatus] = []
    summary = PortfolioStateSummary()
    for pid, name in projects:
        estimates = sorted(estimates_by_project.get(pid, []), key=_estimate_sort_key)
        project = _project(pid, name, estimates)
        setattr(summary, project.state, getattr(summary, project.state) + 1)
        out.append(project)
    out.sort(key=_project_sort_key)
    return ValidationPortfolioResponse(project_count=len(out), summary=summary, projects=out)


def _estimate(boq_id: uuid.UUID, boq_name: str | None, row: Any) -> PortfolioEstimateStatus:
    if row is None:
        return PortfolioEstimateStatus(boq_id=boq_id, boq_name=boq_name or "", state=STATE_NOT_VALIDATED)
    return PortfolioEstimateStatus(
        boq_id=boq_id,
        boq_name=boq_name or "",
        state=report_state(row.status, row.total_rules),
        report_id=row.id,
        report_status=row.status,
        rule_sets=_rule_sets(row.meta_rule_sets, row.rule_set),
        unsupported_rule_sets=_str_list(row.meta_unsupported),
        error_count=row.error_count or 0,
        warning_count=row.warning_count or 0,
        passed_count=row.passed_count or 0,
        total_rules=row.total_rules or 0,
        score=_score(row.score),
        validated_at=row.created_at,
    )


def _project(pid: uuid.UUID, name: str, estimates: Sequence[PortfolioEstimateStatus]) -> PortfolioProjectStatus:
    validated = [e for e in estimates if e.state != STATE_NOT_VALIDATED]
    stamps: list[datetime] = [e.validated_at for e in estimates if e.validated_at is not None]
    rule_sets: dict[str, None] = {}
    for e in estimates:
        for rs in e.rule_sets:
            rule_sets.setdefault(rs, None)
    return PortfolioProjectStatus(
        project_id=pid,
        project_name=name,
        state=worst_state(e.state for e in estimates),
        estimate_count=len(estimates),
        validated_count=len(validated),
        not_validated_count=len(estimates) - len(validated),
        error_count=sum(e.error_count for e in estimates),
        warning_count=sum(e.warning_count for e in estimates),
        passed_count=sum(e.passed_count for e in estimates),
        rule_sets=list(rule_sets),
        last_validated_at=max(stamps) if stamps else None,
        estimates=list(estimates),
    )
