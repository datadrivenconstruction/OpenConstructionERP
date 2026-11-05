# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared building blocks for the quality-module rule sets (NCR, inspections).

Both ask the same kinds of question of a record: is a field present that its
status demands, is a due or scheduled date already behind us, does a recorded
result agree with the evidence under it. Messages live in the shared bundle
under the ``quality`` section.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext
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
    """The 422 body a gated quality write answers with (same shape as procurement)."""
    errors = report.errors if errors is None else errors
    return {
        "message": message,
        "report": report.summary(),
        "errors": [
            {"rule_id": r.rule_id, "message": r.message, "element_ref": r.element_ref, "suggestion": r.suggestion}
            for r in errors
        ],
    }


def warning_findings(report: Any) -> list[dict[str, Any]]:
    """Non-blocking findings, in the shape a response carries them."""
    return [
        {"rule_id": r.rule_id, "message": r.message, "element_ref": r.element_ref, "suggestion": r.suggestion}
        for r in report.warnings
    ]


async def gate_rule_set(
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
) -> Any:
    """Run ``rule_set`` over a record as it will be stored; ERROR findings answer a coded 422.

    WARNING findings do not block: the returned report carries them for the caller to attach.
    With ``before`` (the stored record on update) only errors the edit introduces block, so a
    record saved before the rules existed stays editable.
    """
    from fastapi import HTTPException, status  # noqa: PLC0415

    from app.core.i18n import get_locale  # noqa: PLC0415
    from app.core.validation.engine import validation_engine  # noqa: PLC0415

    async def run(record: dict[str, Any]) -> Any:
        return await validation_engine.validate(
            data={key: {**record, "id": target_id}},
            rule_sets=[rule_set],
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            metadata={"locale": get_locale(), "operation": operation},
        )

    report = await run(state)
    blocking = list(report.errors)
    if blocking and before is not None:
        legacy = {(r.rule_id, r.element_ref, r.message) for r in (await run(before)).errors}
        blocking = [r for r in blocking if (r.rule_id, r.element_ref, r.message) not in legacy]
    if blocking:
        detail = rule_errors_detail(
            report,
            f"This {subject} cannot be saved ({operation}) until the errors listed below are corrected.",
            blocking,
        )
        detail["error"] = error_code
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)
    return report
