# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared building blocks for the quality-module rule sets (NCR, inspections).

Both ask the same kinds of question of a record: is a field present that its
status demands, is a due or scheduled date already behind us, does a recorded
result agree with the evidence under it. Messages live in the shared bundle
under the ``quality`` section.
"""

from __future__ import annotations

import contextlib
import functools
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.i18n import get_locale
from app.core.validation.engine import RuleResult, Severity, ValidationContext, ValidationReport, validation_engine
from app.core.validation.failure import finding, introduced_errors, raise_rule_failure, rule_failure_detail
from app.core.validation.messages import translate
from app.core.validation.money_rules import MoneyRule, locale_of


def parse_day(value: Any) -> date | None:
    """Parse an ISO date or datetime (``Z`` allowed) to a calendar day; ``None`` when absent or malformed."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def today_of(context: ValidationContext) -> date:
    """The reference day: ``metadata['today']`` when given (tests, back-dated runs), else the UTC day."""
    given = parse_day((context.metadata or {}).get("today"))
    return given or datetime.now(UTC).date()


def latest_local_day(context: ValidationContext) -> date:
    """The latest calendar day that can be "today" anywhere on earth (UTC+14), for not-in-the-future checks.

    A site east of UTC dates its records with a local day that is already tomorrow in UTC; judging
    against the UTC day alone would refuse that site's same-day record.
    """
    return today_of(context) + timedelta(days=1)


class QualityRule(MoneyRule):
    """Base for the quality-module rules: result building from the ``quality`` message section.

    Modules with their own wording set ``message_section`` to their section in the bundle.
    """

    message_section = "quality"

    def fail(
        self,
        context: ValidationContext,
        key: str,
        *,
        ref: str = "",
        severity: Severity | None = None,
        **params: Any,
    ) -> RuleResult:
        """A failing result whose text is ``<message_section>.<key>`` in the caller's locale."""
        locale = locale_of(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"{self.message_section}.{key}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=translate(f"{self.message_section}.{key}.suggestion", locale=locale),
            details={k: str(v) for k, v in params.items()},
        )


def rule_errors_detail(report: Any, message: str, errors: Any = None) -> dict[str, Any]:
    """The 422 body a gated quality write answers with."""
    return rule_failure_detail(report, error="quality_rules_failed", errors=errors, message=message)


def warning_findings(report: Any) -> list[dict[str, Any]]:
    """Non-blocking findings, in the shape a response carries them."""
    return [finding(r) for r in report.warnings]


async def gate_rule_set(
    *,
    rule_set: str,
    data: dict[str, Any],
    target_type: str,
    target_id: str,
    project_id: Any,
    operation: str,
    subject: str,
    before: dict[str, Any] | None = None,
    warnings_only: bool = False,
    error: str = "quality_rules_failed",
) -> ValidationReport:
    """Run ``rule_set`` over ``data`` at a write point; ERROR findings answer the shared coded 422.

    ``before`` is the stored state of a record being edited: errors it already had are not
    charged to the edit, so a record saved before the rules existed stays editable.
    ``warnings_only`` is for system-created records, which are reported and never refused.
    WARNING findings never block; the caller attaches them to its response.
    """

    async def _run(payload: dict[str, Any]) -> ValidationReport:
        return await validation_engine.validate(
            data=payload,
            rule_sets=[rule_set],
            target_type=target_type,
            target_id=target_id,
            project_id=str(project_id) if project_id else None,
            metadata={"locale": get_locale(), "operation": operation},
        )

    report = await _run(data)
    if not warnings_only:
        blocking = await introduced_errors(report, (lambda: _run(before)) if before is not None else None)
        raise_rule_failure(
            report,
            blocking,
            error=error,
            message=f"This {subject} cannot be saved ({operation}) until the errors listed below are corrected.",
        )
    return report


async def gate_keyed_rule_set(
    state: dict[str, Any],
    *,
    rule_set: str,
    key: str,
    target_type: str,
    target_id: str,
    operation: str,
    subject: str,
    error_code: str,
    before: dict[str, Any] | None = None,
    project_id: str | None = None,
    warnings_only: bool = False,
) -> ValidationReport:
    """``gate_rule_set`` for a record the rules read under ``data[key]`` (with its ``id`` set)."""

    def wrap(record: dict[str, Any]) -> dict[str, Any]:
        return {key: {**record, "id": target_id}}

    return await gate_rule_set(
        rule_set=rule_set,
        data=wrap(state),
        before=wrap(before) if before is not None else None,
        warnings_only=warnings_only,
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        operation=operation,
        subject=subject,
        error=error_code,
    )


def record_snapshot(source: Any, names: Any, changes: dict[str, Any] | None = None) -> dict[str, Any]:
    """The fields ``names`` of a stored record (object or dict) with ``changes`` applied on top.

    This is the record as it will be after the write, which is what the rules judge; with no
    ``changes`` it is the stored record, the ``before`` side of the "only what the edit introduces" filter.
    """
    changes = changes or {}
    out: dict[str, Any] = {}
    for name in names:
        if name in changes:
            out[name] = changes[name]
        elif isinstance(source, dict):
            out[name] = source.get(name)
        else:
            out[name] = getattr(source, name, None)
    return out


async def gate_record(
    rule_set: str,
    key: str,
    record: Any,
    names: Any,
    changes: dict[str, Any] | None = None,
    *,
    operation: str,
    project_id: Any,
    error_code: str,
    target_id: str = "",
    warnings_only: bool = False,
    whole: bool = False,
) -> list[dict[str, Any]]:
    """Gate one record write: the rules judge ``record`` with ``changes`` applied; returns the warnings.

    A write that edits a stored record passes its ``target_id``; the stored fields are then the
    ``before`` state, so only the errors this edit introduces block it. ``whole`` judges the record in
    full instead, for a final step (closing) that must not carry an error forward from a legacy state.
    """
    report = await gate_keyed_rule_set(
        record_snapshot(record, names, changes),
        rule_set=rule_set,
        key=key,
        target_type=f"{rule_set}_{key}",
        target_id=target_id,
        operation=operation,
        subject=key.replace("_", " "),
        error_code=error_code,
        before=record_snapshot(record, names) if target_id and not whole else None,
        project_id=str(project_id) if project_id else None,
        warnings_only=warnings_only,
    )
    if warnings_only:
        return [finding(r) for r in (*report.errors, *report.warnings)]
    return warning_findings(report)


def carries_warnings(method: Any) -> Any:
    """Decorate an async service write: the non-blocking findings of its gate ride on the returned record.

    The service keeps them in ``self.findings`` (reset per call); the response schema reads
    ``validation_warnings`` off the record.
    """

    @functools.wraps(method)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        self.findings = []
        out = await method(self, *args, **kwargs)
        if out is not None and not isinstance(out, (list, tuple, dict, set)):
            with contextlib.suppress(AttributeError):
                out.validation_warnings = list(self.findings)
        return out

    return wrapper
