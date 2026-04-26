# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run-orchestration service for EAC v2 (RFC 35 §1.6 / §1.7).

The :func:`run_ruleset` coroutine is the top-level entry that the
``/rulesets/{id}:run`` endpoint and the Celery worker share. It:

1. Loads the ruleset and its active rules.
2. Loads the canonical element rows for ``model_id``.
3. Runs each rule via the pure :func:`execute_rule` engine.
4. Persists an :class:`EacRun` row with summary metrics + per-element
   :class:`EacRunResultItem` rows for inspection.

The runner intentionally lives next to the executor — the executor is
pure, the runner is the I/O envelope around it. Tests for the runner
exercise the persistence path with an in-memory SQLite session.

The dry-run helper (:func:`dry_run_rule`) is used by the rule editor's
"Test" panel: it accepts ad-hoc element dicts (no DB lookups, no
persistence) and returns the executor's :class:`ExecutionResult`
verbatim.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eac.engine.executor import (
    ExecutionError,
    ExecutionResult,
    UnsupportedOutputModeError,
    execute_rule,
)
from app.modules.eac.models import (
    EacRule,
    EacRuleset,
    EacRun,
    EacRunResultItem,
)
from app.modules.eac.schemas import EacRuleDefinition

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────


# Per-run cap on EacRunResultItem rows persisted into PostgreSQL.
# Beyond this we set EacRun.summary_json["spilled_to_parquet"]=True and
# stop inserting hot rows — Parquet spill is wired up in a separate
# follow-up (RFC 35 §1.6 "cold rows"). The cap protects the OLTP table
# from a runaway 500k-element model.
HOT_RESULT_ITEM_CAP = 100_000


# ── Public dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class RuleOutcome:
    """Per-rule slice of a run summary, surfaced in EacRun.summary_json."""

    rule_id: str
    rule_name: str
    output_mode: str
    elements_evaluated: int
    elements_matched: int
    elements_passed: int
    error: str | None = None


# ── Public entry points ─────────────────────────────────────────────────


async def dry_run_rule(
    rule_definition: dict[str, Any],
    elements: list[dict[str, Any]],
    *,
    session: AsyncSession | None = None,
    tenant_id: uuid.UUID | None = None,
) -> ExecutionResult:
    """Validate + execute ``rule_definition`` against ad-hoc ``elements``.

    No persistence — used by the rule editor's "Test" panel and by
    ``POST /rules:dry-run``. Returns the executor's
    :class:`ExecutionResult` so callers can render per-element verdicts.

    Two validation passes run before execution:

    1. **Pydantic shape check** — catches malformed payloads.
    2. **Semantic validator** (``engine.validator.validate_rule``) —
       formula safe-eval AST, ``between`` ordering, ReDoS reject,
       local-var cycle detection, alias-existence (when a session is
       supplied). Skipped if no session is given so unit-test callers
       can still dry-run rules without standing up a DB.

    Raises :class:`ExecutionError` on any failure so the caller can
    surface a 422 cleanly.
    """
    try:
        parsed = EacRuleDefinition.model_validate(rule_definition)
    except ValidationError as exc:
        raise ExecutionError(f"invalid rule definition: {exc}") from exc

    # Semantic validation (alias / formula / ReDoS / between-ordering).
    # We only run it when a session is provided — pure unit tests pass
    # ``session=None`` and rely on the executor's own per-step errors.
    if session is not None:
        from app.modules.eac.engine.validator import validate_rule as _validate

        result = await _validate(parsed, session=session, tenant_id=tenant_id)
        if not result.valid:
            messages = "; ".join(
                f"{i.path}: {i.message_i18n_key}" for i in result.issues
            )
            raise ExecutionError(f"rule failed semantic validation: {messages}")

    return execute_rule(parsed, elements)


async def run_ruleset(
    *,
    session: AsyncSession,
    ruleset_id: uuid.UUID,
    tenant_id: uuid.UUID,
    elements: list[dict[str, Any]],
    model_version_id: uuid.UUID | None = None,
    triggered_by: str = "manual",
) -> EacRun:
    """Execute every active rule in ``ruleset_id`` against ``elements``.

    Persists an :class:`EacRun` plus per-element
    :class:`EacRunResultItem` rows and returns the run record.

    The caller is responsible for resolving ``elements`` from whichever
    source is appropriate — the canonical Parquet table, a BIMElement
    query, or a unit-test fixture. Decoupling that lookup from the
    runner keeps the persistence path testable without standing up a
    real model loader.
    """
    ruleset = await session.get(EacRuleset, ruleset_id)
    if ruleset is None:
        raise ExecutionError(f"ruleset {ruleset_id} not found")
    if ruleset.tenant_id != tenant_id:
        # Defence-in-depth — the router must already have authorised the
        # caller, but we re-check so worker-side runs can't be tricked
        # into touching another tenant's data.
        raise ExecutionError("ruleset/tenant mismatch")

    rules = await _load_active_rules(session, ruleset_id)

    run = EacRun(
        ruleset_id=ruleset_id,
        model_version_id=model_version_id,
        status="running",
        triggered_by=triggered_by,
        tenant_id=tenant_id,
        started_at=datetime.now(UTC),
        elements_evaluated=len(elements),
        elements_matched=0,
        error_count=0,
    )
    session.add(run)
    await session.flush()  # populate run.id

    rule_outcomes: list[RuleOutcome] = []
    total_matched = 0
    total_errors = 0
    persisted_rows = 0
    spilled = False
    cancelled = False

    # Cooperative cancellation: imported lazily to avoid a hard import
    # cycle between runner -> api -> runner. The runner only needs the
    # ``is_cancelled`` query — the registry write happens in service.cancel.
    from app.modules.eac.engine.api import is_cancelled as _is_cancelled

    for rule in rules:
        if _is_cancelled(run.id):
            cancelled = True
            break
        try:
            parsed = EacRuleDefinition.model_validate(rule.definition_json or {})
        except ValidationError as exc:
            rule_outcomes.append(
                RuleOutcome(
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    output_mode=rule.output_mode,
                    elements_evaluated=len(elements),
                    elements_matched=0,
                    elements_passed=0,
                    error=f"definition_json invalid: {exc.errors()[:1]}",
                )
            )
            total_errors += 1
            continue

        try:
            result = execute_rule(parsed, elements)
        except UnsupportedOutputModeError as exc:
            rule_outcomes.append(
                RuleOutcome(
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    output_mode=rule.output_mode,
                    elements_evaluated=len(elements),
                    elements_matched=0,
                    elements_passed=0,
                    error=str(exc),
                )
            )
            total_errors += 1
            continue
        except ExecutionError as exc:
            logger.warning(
                "EAC rule %s execution error: %s", rule.id, exc, exc_info=True
            )
            rule_outcomes.append(
                RuleOutcome(
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    output_mode=rule.output_mode,
                    elements_evaluated=len(elements),
                    elements_matched=0,
                    elements_passed=0,
                    error=str(exc),
                )
            )
            total_errors += 1
            continue

        rule_outcomes.append(
            RuleOutcome(
                rule_id=str(rule.id),
                rule_name=rule.name,
                output_mode=result.output_mode,
                elements_evaluated=result.elements_evaluated,
                elements_matched=result.elements_matched,
                elements_passed=result.elements_passed,
            )
        )
        total_matched += result.elements_matched
        total_errors += len(result.errors)

        for item in _materialise_result_items(rule, run.id, tenant_id, result):
            if persisted_rows >= HOT_RESULT_ITEM_CAP:
                spilled = True
                break
            session.add(item)
            persisted_rows += 1

        if spilled:
            # Stop iterating the rest of the rules for this run — once
            # the hot table is full there is nothing useful we can store
            # without the Parquet spool path. The summary records the
            # spill so the UI can warn the user.
            break

    run.finished_at = datetime.now(UTC)
    run.elements_matched = total_matched
    run.error_count = total_errors
    run.status = _derive_status(rule_outcomes, spilled=spilled, cancelled=cancelled)
    run.summary_json = {
        "rules": [_outcome_dict(o) for o in rule_outcomes],
        "rule_count": len(rule_outcomes),
        "persisted_result_items": persisted_rows,
        "spilled_to_parquet": spilled,
        "cancelled": cancelled,
    }
    await session.flush()

    # Clear the in-process cancel token now that the run has terminated.
    # Best-effort: a failure here must not break the persisted run row.
    try:
        from app.modules.eac.engine.api import _clear_cancel  # noqa: PLC0415

        _clear_cancel(run.id)
    except Exception:  # noqa: BLE001
        pass

    return run


# ── Internal helpers ────────────────────────────────────────────────────


async def _load_active_rules(
    session: AsyncSession, ruleset_id: uuid.UUID
) -> list[EacRule]:
    """Return the active rules in stable order for deterministic runs."""
    stmt = (
        select(EacRule)
        .where(EacRule.ruleset_id == ruleset_id)
        .where(EacRule.is_active.is_(True))
        .order_by(EacRule.created_at.asc(), EacRule.id.asc())
    )
    return list((await session.scalars(stmt)).all())


def _materialise_result_items(
    rule: EacRule,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    result: ExecutionResult,
) -> Iterable[EacRunResultItem]:
    """Project an :class:`ExecutionResult` into ORM rows.

    Boolean mode → one row per element with ``pass_`` filled.
    Issue mode  → one row per failed element with the issue payload in
                  ``result_value``.
    Aggregate   → exactly one synthetic row carrying the scalar.
    """
    if result.output_mode == "boolean":
        for entry in result.boolean_results:
            yield EacRunResultItem(
                run_id=run_id,
                rule_id=rule.id,
                element_id=entry.element_id or "",
                pass_=entry.passed,
                attribute_snapshot=dict(entry.attribute_snapshot),
                result_value=None,
                error=entry.error,
                tenant_id=tenant_id,
            )
        return

    if result.output_mode == "issue":
        for issue in result.issue_results:
            yield EacRunResultItem(
                run_id=run_id,
                rule_id=rule.id,
                element_id=issue.element_id or "",
                pass_=False,
                attribute_snapshot=dict(issue.attribute_snapshot),
                result_value={
                    "title": issue.title,
                    "description": issue.description,
                    "topic_type": issue.topic_type,
                    "priority": issue.priority,
                    "stage": issue.stage,
                    "labels": list(issue.labels),
                },
                tenant_id=tenant_id,
            )
        return

    if result.output_mode == "aggregate" and result.aggregate_result is not None:
        yield EacRunResultItem(
            run_id=run_id,
            rule_id=rule.id,
            element_id="__aggregate__",
            pass_=None,
            attribute_snapshot=None,
            result_value={
                "value": result.aggregate_result.value,
                "result_unit": result.aggregate_result.result_unit,
                "elements_evaluated": result.aggregate_result.elements_evaluated,
            },
            tenant_id=tenant_id,
        )
        return


def _derive_status(
    outcomes: list[RuleOutcome],
    *,
    spilled: bool,
    cancelled: bool = False,
) -> str:
    """Map per-rule outcomes to the run's terminal status."""
    if cancelled:
        return "cancelled"
    if not outcomes:
        return "success"
    has_errors = any(o.error is not None for o in outcomes)
    has_passes = any(o.error is None for o in outcomes)
    if spilled:
        return "partial"
    if has_errors and has_passes:
        return "partial"
    if has_errors:
        return "failed"
    return "success"


def _outcome_dict(o: RuleOutcome) -> dict[str, Any]:
    return {
        "rule_id": o.rule_id,
        "rule_name": o.rule_name,
        "output_mode": o.output_mode,
        "elements_evaluated": o.elements_evaluated,
        "elements_matched": o.elements_matched,
        "elements_passed": o.elements_passed,
        "error": o.error,
    }


# ── BIM → canonical adapter ────────────────────────────────────────────


def bim_element_to_canonical(row: Any) -> dict[str, Any]:
    """Project a :class:`BIMElement` ORM row into the executor's canonical shape.

    Kept here (rather than on the BIMElement model) because the canonical
    contract is owned by EAC — every other consumer should go through
    this function so the field-name mapping has exactly one source of
    truth.
    """
    properties = dict(getattr(row, "properties", None) or {})
    quantities = dict(getattr(row, "quantities", None) or {})

    # Surface Pset_*.field flat keys alongside top-level keys so the
    # Pset-qualified attribute resolver finds both shapes.
    out_props: dict[str, Any] = dict(properties)
    for key, value in properties.items():
        if isinstance(value, dict):
            for sub_k, sub_v in value.items():
                out_props.setdefault(f"{key}.{sub_k}", sub_v)

    return {
        "stable_id": getattr(row, "stable_id", None),
        "element_type": getattr(row, "element_type", None),
        "ifc_class": properties.get("ifc_class") or getattr(row, "element_type", None),
        "name": getattr(row, "name", None),
        "level": getattr(row, "storey", None),
        "discipline": getattr(row, "discipline", None),
        "properties": out_props,
        "quantities": quantities,
        "classification": properties.get("classification") or {},
        "groups": properties.get("groups") or [],
    }


__all__ = [
    "HOT_RESULT_ITEM_CAP",
    "RuleOutcome",
    "bim_element_to_canonical",
    "dry_run_rule",
    "run_ruleset",
]
