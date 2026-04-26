# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Public engine API for EAC v2 (RFC 35 §1.7 / RFC 36 W1.1, task #221).

A thin facade over the engine internals (planner, validator, executor,
runner) that gives any caller — router, scripts, Celery worker, tests,
UI — a single, stable surface to drive a full EAC run end-to-end.

Capabilities (one function per row):

* :func:`compile_plan`   — validate + plan a rule definition.
* :func:`describe_plan`  — render an :class:`ExecutionPlan` as a human
  readable dict (alias resolutions, formula, post-step, projection).
* :func:`run`            — execute a ruleset (delegates to
  :func:`runner.run_ruleset`); supports ``dry_run`` to skip persistence.
* :func:`status`         — current run state with derived progress %.
* :func:`list_runs`      — paginated tenant-scoped listing.
* :func:`cancel`         — gracefully stop a running execution.
* :func:`rerun`          — replay a finished run on the same inputs.
* :func:`diff`           — compare two runs of the same ruleset.

Cancellation is cooperative: :func:`cancel` flips a flag in the in-process
``_CANCEL_TOKENS`` registry which the runner checks between rules. For
out-of-process execution (Celery / multi-worker) the token is also
persisted via ``EacRun.status='cancelled'`` so a worker reading the row
sees the request even if it lives in a different process.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eac.engine.executor import (
    ExecutionError,
    UnsupportedOutputModeError,
)
from app.modules.eac.engine.planner import ExecutionPlan, plan_rule
from app.modules.eac.engine.runner import dry_run_rule, run_ruleset
from app.modules.eac.engine.validator import validate_rule
from app.modules.eac.models import (
    EacRule,
    EacRuleset,
    EacRun,
    EacRunResultItem,
)
from app.modules.eac.schemas import EacRuleDefinition

logger = logging.getLogger(__name__)


# ── Public dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class CompiledPlan:
    """Output of :func:`compile_plan`.

    Carries the plan plus the validator's verdict so the caller can
    surface schema / semantic issues before scheduling the run.
    """

    plan: ExecutionPlan
    valid: bool
    issues: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RunStatus:
    """Snapshot of a run's state for :func:`status`.

    ``progress`` is a float in ``[0.0, 1.0]`` derived from
    ``elements_evaluated / max(1, elements_evaluated)`` for finished runs
    and from ``persisted_result_items / elements_evaluated`` for in-flight
    ones. It is intentionally derived rather than persisted so the same
    column doesn't have to be updated on every row insert.
    """

    run_id: uuid.UUID
    status: str
    progress: float
    elements_evaluated: int
    elements_matched: int
    error_count: int
    started_at: datetime | None
    finished_at: datetime | None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunDiff:
    """Output of :func:`diff` — what changed between two runs.

    Comparisons are made on ``(rule_id, element_id)`` pairs so the same
    element inspected by the same rule is the unit of change.
    """

    run_id_a: uuid.UUID
    run_id_b: uuid.UUID
    elements_only_in_a: list[str]
    elements_only_in_b: list[str]
    flipped_pass_to_fail: list[str]
    flipped_fail_to_pass: list[str]
    unchanged_count: int


# ── In-process cancellation registry ────────────────────────────────────


# Maps run_id -> True when a cancellation has been requested. The runner
# checks this between rules. For out-of-process workers, the
# EacRun.status='cancelled' write below acts as the canonical signal.
_CANCEL_TOKENS: dict[uuid.UUID, bool] = {}


def _request_cancel(run_id: uuid.UUID) -> None:
    """Mark ``run_id`` as cancelled in the in-process registry."""
    _CANCEL_TOKENS[run_id] = True


def is_cancelled(run_id: uuid.UUID) -> bool:
    """Return True if a cancellation has been requested for ``run_id``.

    Public so the runner can poll between rules without reaching into
    private state.
    """
    return _CANCEL_TOKENS.get(run_id, False)


def _clear_cancel(run_id: uuid.UUID) -> None:
    """Drop ``run_id`` from the registry once it has terminated."""
    _CANCEL_TOKENS.pop(run_id, None)


# ── Compile + describe ─────────────────────────────────────────────────


async def compile_plan(
    rule_definition: dict[str, Any],
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
) -> CompiledPlan:
    """Validate and compile a rule into an :class:`ExecutionPlan`.

    Two passes:

    1. **Pydantic shape check** — ``EacRuleDefinition.model_validate``
       (already raises a typed ``ValidationError``).
    2. **Semantic validator** — alias / formula / regex / between
       ordering. Skipped when ``session`` is ``None`` (pure unit-test
       callers) so the planner can still be exercised offline.

    The plan is always produced when (1) succeeds, even if (2) returns
    issues — callers may want to inspect the SQL even with semantic
    warnings outstanding. The verdict lives on :attr:`CompiledPlan.valid`.
    """
    parsed = EacRuleDefinition.model_validate(rule_definition)
    plan = plan_rule(parsed)

    if session is None:
        return CompiledPlan(plan=plan, valid=True, issues=[])

    result = await validate_rule(parsed, session=session, tenant_id=tenant_id)
    issues = [
        {
            "code": issue.code,
            "severity": issue.severity,
            "path": issue.path,
            "message_i18n_key": issue.message_i18n_key,
        }
        for issue in result.issues
    ]
    return CompiledPlan(plan=plan, valid=result.valid, issues=issues)


def describe_plan(plan: ExecutionPlan) -> dict[str, Any]:
    """Return a human-readable explanation of ``plan``.

    Used by the rule-editor "explain" panel and by ``GET
    /api/v1/eac/plans/{rule_id}/describe`` (when the front-end wants to
    show why a rule does what it does).

    The output is intentionally JSON-serialisable: SQL, projection
    columns, sorted parameters, the post-Python step, plus the cost
    estimate. ``parameters`` is sorted by key for deterministic output
    so two equivalent rules produce identical descriptions.
    """
    return {
        "duckdb_sql": plan.duckdb_sql,
        "projection_columns": list(plan.projection_columns),
        "parameters": dict(sorted(plan.parameters.items())),
        "post_python_step": plan.post_python_step,
        "estimated_cost": plan.estimated_cost,
    }


# ── Run + status + cancel + listing ────────────────────────────────────


async def run(
    *,
    session: AsyncSession,
    ruleset_id: uuid.UUID,
    tenant_id: uuid.UUID,
    elements: list[dict[str, Any]],
    model_version_id: uuid.UUID | None = None,
    triggered_by: str = "manual",
    dry_run: bool = False,
) -> EacRun | dict[str, Any]:
    """Execute ``ruleset_id`` against ``elements``.

    ``dry_run=True`` skips persistence and returns a dict that mirrors
    the executor's :class:`ExecutionResult` for each rule — handy for
    test scripts and the rule-editor preview. ``dry_run=False`` returns
    the persisted :class:`EacRun` row.
    """
    if dry_run:
        # Loop through every active rule and call the pure dry-run path.
        rules = await _load_active_rules(session, ruleset_id, tenant_id)
        outcomes: list[dict[str, Any]] = []
        for rule in rules:
            try:
                result = await dry_run_rule(
                    rule.definition_json or {},
                    elements,
                    session=session,
                    tenant_id=tenant_id,
                )
                outcomes.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "output_mode": result.output_mode,
                        "elements_evaluated": result.elements_evaluated,
                        "elements_matched": result.elements_matched,
                        "elements_passed": result.elements_passed,
                        "errors": list(result.errors),
                    }
                )
            except (ExecutionError, UnsupportedOutputModeError) as exc:
                outcomes.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "output_mode": rule.output_mode,
                        "elements_evaluated": len(elements),
                        "elements_matched": 0,
                        "elements_passed": 0,
                        "error": str(exc),
                    }
                )
        return {
            "dry_run": True,
            "ruleset_id": str(ruleset_id),
            "rules": outcomes,
        }

    return await run_ruleset(
        session=session,
        ruleset_id=ruleset_id,
        tenant_id=tenant_id,
        elements=elements,
        model_version_id=model_version_id,
        triggered_by=triggered_by,
    )


async def status(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None = None,
) -> RunStatus | None:
    """Return a :class:`RunStatus` snapshot for ``run_id``.

    ``None`` is returned when the run does not exist (or belongs to a
    different tenant). Callers map that to a 404.
    """
    run_row = await session.get(EacRun, run_id)
    if run_row is None:
        return None
    if tenant_id is not None and run_row.tenant_id != tenant_id:
        return None

    progress = _derive_progress(run_row)
    errors: list[str] = []
    if run_row.summary_json:
        for rule_outcome in run_row.summary_json.get("rules", []) or []:
            err = rule_outcome.get("error")
            if err:
                errors.append(f"{rule_outcome.get('rule_name', '?')}: {err}")

    return RunStatus(
        run_id=run_row.id,
        status=run_row.status,
        progress=progress,
        elements_evaluated=run_row.elements_evaluated,
        elements_matched=run_row.elements_matched,
        error_count=run_row.error_count,
        started_at=run_row.started_at,
        finished_at=run_row.finished_at,
        errors=errors,
    )


async def cancel(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None = None,
) -> bool:
    """Request graceful cancellation of ``run_id``.

    Returns ``True`` when the cancellation was accepted (run exists and
    is in a cancellable state), ``False`` otherwise. Idempotent: cancelling
    an already-cancelled run is a no-op that returns ``True``.

    The runner observes the cancel signal between rules; in-flight rule
    execution finishes its current rule before honouring the request.
    For multi-worker setups the persisted ``status='cancelled'`` write
    is the canonical cross-process signal.
    """
    run_row = await session.get(EacRun, run_id)
    if run_row is None:
        return False
    if tenant_id is not None and run_row.tenant_id != tenant_id:
        return False
    if run_row.status in {"success", "failed", "cancelled"}:
        # Terminal states — accept the request idempotently when the run
        # is already cancelled, refuse otherwise.
        return run_row.status == "cancelled"

    _request_cancel(run_id)
    run_row.status = "cancelled"
    run_row.finished_at = datetime.now(UTC)
    await session.flush()
    return True


async def list_runs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ruleset_id: uuid.UUID | None = None,
    run_status: str | None = None,
    triggered_by: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[EacRun]:
    """Paginated listing of runs visible to ``tenant_id``.

    Filters compose with AND semantics; ``ruleset_id`` is the most
    common path (run-history view of a single ruleset).
    """
    stmt = (
        select(EacRun)
        .where(EacRun.tenant_id == tenant_id)
        .order_by(EacRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if ruleset_id is not None:
        stmt = stmt.where(EacRun.ruleset_id == ruleset_id)
    if run_status is not None:
        stmt = stmt.where(EacRun.status == run_status)
    if triggered_by is not None:
        stmt = stmt.where(EacRun.triggered_by == triggered_by)
    return list((await session.scalars(stmt)).all())


# ── Rerun ───────────────────────────────────────────────────────────────


async def rerun(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
    elements: list[dict[str, Any]],
    triggered_by: str = "manual",
) -> EacRun:
    """Replay a prior run against ``elements``.

    Convenience wrapper: looks up the original run's ``ruleset_id`` and
    ``model_version_id`` and dispatches a fresh :func:`run`. The caller
    supplies ``elements`` because the originals may not be cheap to
    rebuild — the persistence layer doesn't keep them.

    Raises :class:`ExecutionError` when the source run is missing or
    belongs to another tenant.
    """
    src = await session.get(EacRun, run_id)
    if src is None or src.tenant_id != tenant_id:
        raise ExecutionError(f"run {run_id} not found")
    return await run_ruleset(
        session=session,
        ruleset_id=src.ruleset_id,
        tenant_id=tenant_id,
        elements=elements,
        model_version_id=src.model_version_id,
        triggered_by=triggered_by,
    )


# ── Diff ────────────────────────────────────────────────────────────────


async def diff(
    session: AsyncSession,
    run_id_a: uuid.UUID,
    run_id_b: uuid.UUID,
    *,
    tenant_id: uuid.UUID,
) -> RunDiff:
    """Compare two runs of the same ruleset.

    The diff is computed by joining ``EacRunResultItem`` rows on
    ``(rule_id, element_id)``. Only rows from runs of the **same**
    ruleset are eligible — comparing across rulesets is not meaningful.

    Raises :class:`ExecutionError` on tenant mismatch or unrelated
    rulesets so the caller can surface a 422 cleanly.
    """
    run_a = await session.get(EacRun, run_id_a)
    run_b = await session.get(EacRun, run_id_b)
    if run_a is None or run_b is None:
        raise ExecutionError("one or both runs not found")
    if run_a.tenant_id != tenant_id or run_b.tenant_id != tenant_id:
        raise ExecutionError("run/tenant mismatch")
    if run_a.ruleset_id != run_b.ruleset_id:
        raise ExecutionError(
            "runs belong to different rulesets — diff is not meaningful"
        )

    rows_a = list(
        (
            await session.scalars(
                select(EacRunResultItem).where(
                    EacRunResultItem.run_id == run_id_a
                )
            )
        ).all()
    )
    rows_b = list(
        (
            await session.scalars(
                select(EacRunResultItem).where(
                    EacRunResultItem.run_id == run_id_b
                )
            )
        ).all()
    )

    map_a = {(r.rule_id, r.element_id): r for r in rows_a}
    map_b = {(r.rule_id, r.element_id): r for r in rows_b}

    only_a: list[str] = []
    only_b: list[str] = []
    f2p: list[str] = []
    p2f: list[str] = []
    unchanged = 0

    for key, row in map_a.items():
        if key not in map_b:
            only_a.append(row.element_id)
            continue
        other = map_b[key]
        if row.pass_ == other.pass_:
            unchanged += 1
        elif row.pass_ is False and other.pass_ is True:
            f2p.append(row.element_id)
        elif row.pass_ is True and other.pass_ is False:
            p2f.append(row.element_id)

    for key, row in map_b.items():
        if key not in map_a:
            only_b.append(row.element_id)

    return RunDiff(
        run_id_a=run_id_a,
        run_id_b=run_id_b,
        elements_only_in_a=sorted(only_a),
        elements_only_in_b=sorted(only_b),
        flipped_pass_to_fail=sorted(p2f),
        flipped_fail_to_pass=sorted(f2p),
        unchanged_count=unchanged,
    )


# ── Internal helpers ────────────────────────────────────────────────────


async def _load_active_rules(
    session: AsyncSession,
    ruleset_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[EacRule]:
    """Return the active rules for a ruleset (tenant-scoped)."""
    ruleset = await session.get(EacRuleset, ruleset_id)
    if ruleset is None or ruleset.tenant_id != tenant_id:
        return []
    stmt = (
        select(EacRule)
        .where(EacRule.ruleset_id == ruleset_id)
        .where(EacRule.is_active.is_(True))
        .order_by(EacRule.created_at.asc(), EacRule.id.asc())
    )
    return list((await session.scalars(stmt)).all())


def _derive_progress(run_row: EacRun) -> float:
    """Compute ``[0.0, 1.0]`` progress from a run row.

    Finished runs (``success`` / ``failed`` / ``partial`` / ``cancelled``)
    are reported as 1.0 if they evaluated anything, 0.0 if they never
    started. Running rows estimate from
    ``persisted_result_items / max(1, elements_evaluated)`` — best-effort
    because the runner doesn't checkpoint a counter today.
    """
    if run_row.status in {"success", "failed", "partial", "cancelled"}:
        return 1.0 if run_row.elements_evaluated > 0 else 0.0
    if run_row.elements_evaluated <= 0:
        return 0.0
    persisted = 0
    if run_row.summary_json:
        persisted = int(run_row.summary_json.get("persisted_result_items", 0) or 0)
    if persisted <= 0:
        return 0.0
    ratio = persisted / max(1, run_row.elements_evaluated)
    if ratio < 0.0:
        return 0.0
    if ratio > 1.0:
        return 1.0
    return ratio


__all__ = [
    "CompiledPlan",
    "RunDiff",
    "RunStatus",
    "cancel",
    "compile_plan",
    "describe_plan",
    "diff",
    "is_cancelled",
    "list_runs",
    "rerun",
    "run",
    "status",
]
