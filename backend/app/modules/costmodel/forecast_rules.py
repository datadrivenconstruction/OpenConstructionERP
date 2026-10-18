# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forecast documentation rules V19, V20 and V22, rule set ``cost_forecast``.

A forecast is a statement a controller signs. These rules point at the three
places where it stops being backed by the data or by a reason:

* V19 ``below_commitment``: a line's forecast is below what the project is
  already bound to pay plus the change orders waiting for a decision, and
  nothing explains it: no document behind a manual amount, no comment on a
  method chosen for the line. A forecast below the commitment says money will
  come back, which needs a credit note, a claim or a minute to stand on.
* V20 ``move_without_evidence``: on the open (draft) snapshot, a line moved by
  more than the project's threshold since the last frozen snapshot and has no
  comment and evidence yet. Freezing is refused while this rule fires.
* V22 ``method_override_without_comment``: a line is forecast by another
  method than the project's, and nobody said why.

V21 (the three checksums at completion) belongs to the completion wave.
Cost control runs this set on every read of its forecast panel, and on
freezing a snapshot. Each rule reads ``context.data["cost_forecast"]`` and is
silent on any other payload. Messages come from the validation message bundle
in the caller's locale.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate
from app.modules.costmodel.forecast_docs import EvidenceThreshold, money, needs_evidence, note_complete

logger = logging.getLogger(__name__)

RULE_SET = "cost_forecast"
PAYLOAD_KEY = "cost_forecast"

#: Money the comparisons let pass as rounding.
TOLERANCE = Decimal("0.01")
#: Shortest comment that counts as an explanation.
MIN_COMMENT = 3


def _payload(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get(PAYLOAD_KEY), dict):
        return data[PAYLOAD_KEY]
    return None


def _locale(context: ValidationContext) -> str:
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in payload.get(key) or [] if isinstance(r, dict)]


def _explained(text: object) -> bool:
    return len(str(text or "").strip()) >= MIN_COMMENT


class _ForecastRule(ValidationRule):
    """Shared plumbing: payload lookup and translated results."""

    standard = "universal"
    category = RuleCategory.COMPLETENESS

    def _method_name(self, method: str, locale: str) -> str:
        return translate(f"cost_forecast.method.{method}", locale)

    def _result(
        self,
        context: ValidationContext,
        message_key: str,
        *,
        element_ref: str | None,
        money_params: tuple[str, ...] = (),
        **params: Any,
    ) -> RuleResult:
        """A failed result. Params named in ``money_params`` are spelled as amounts for the sentence.

        ``details`` keeps every param as a plain string (a raw decimal for money).
        """
        locale = _locale(context)
        currency = str((_payload(context) or {}).get("currency") or "")
        shown = {k: (sentence_amount(money(v), currency) if k in money_params else v) for k, v in params.items()}
        for name in ("method", "project_method"):
            if name in shown:
                shown[name] = self._method_name(str(shown[name]), locale)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"cost_forecast.{message_key}.fail", locale, **shown),
            element_ref=element_ref,
            details={"problem": message_key, **{k: str(v) for k, v in params.items()}},
            suggestion=translate(f"cost_forecast.{message_key}.suggestion", locale, **shown),
        )

    def _passed(self) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="",
        )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if payload is None:
            return []
        return self.check(context, payload) or [self._passed()]


class BelowCommitmentRule(_ForecastRule):
    """V19: a forecast below the commitment plus pending changes is justified."""

    rule_id = "cost_forecast.below_commitment"
    name = "Forecast below what is already owed"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "A line's forecast is below its commitment plus the change orders waiting for a decision, "
        "with no document behind a manual amount and no comment on the line's method."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for line in _rows(payload, "lines"):
            forecast = money(line.get("forecast"))
            owed = money(line.get("committed")) + money(line.get("pending"))
            if owed - forecast <= TOLERANCE:
                continue
            if line.get("manual"):
                if line.get("manual_document"):
                    continue
            elif line.get("method_origin") == "line" and _explained(line.get("method_comment")):
                continue
            out.append(
                self._result(
                    context,
                    "below_commitment",
                    element_ref=str(line.get("key") or "") or None,
                    money_params=("forecast", "owed", "difference"),
                    code=str(line.get("code") or ""),
                    forecast=forecast,
                    owed=owed,
                    difference=owed - forecast,
                )
            )
        return out


class MoveWithoutEvidenceRule(_ForecastRule):
    """V20: a move above the threshold on the open snapshot has a comment and evidence."""

    rule_id = "cost_forecast.move_without_evidence"
    name = "Forecast move without evidence"
    severity = Severity.WARNING
    description = (
        "On the open snapshot, a line moved by more than the project's threshold since the last frozen "
        "snapshot and has no comment and evidence."
    )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("status") != "draft" or snapshot.get("baseline"):
            return []
        raw_pct = snapshot.get("threshold_pct")
        threshold = EvidenceThreshold(
            amount=money(snapshot.get("threshold_amount")),
            pct=None if raw_pct in (None, "") else money(raw_pct),
        )
        out: list[RuleResult] = []
        for line in _rows(snapshot, "lines"):
            raw_previous = line.get("previous")
            previous = None if raw_previous in (None, "") else money(raw_previous)
            current = money(line.get("current"))
            if not needs_evidence(previous, current, threshold):
                continue
            if note_complete(str(line.get("comment") or ""), line.get("evidence") or []):
                continue
            out.append(
                self._result(
                    context,
                    "move_without_evidence",
                    element_ref=str(line.get("key") or "") or None,
                    money_params=("previous", "current", "delta"),
                    code=str(line.get("code") or ""),
                    previous=previous if previous is not None else Decimal("0"),
                    current=current,
                    delta=current - (previous or Decimal("0")),
                )
            )
        return out


class MethodOverrideWithoutCommentRule(_ForecastRule):
    """V22: a line forecast by another method than the project's says why."""

    rule_id = "cost_forecast.method_override_without_comment"
    name = "Line method chosen without a comment"
    severity = Severity.WARNING
    description = "A line is forecast by a different method than the project's, and no comment says why."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        project_method = str(payload.get("project_method") or "")
        out: list[RuleResult] = []
        for line in _rows(payload, "lines"):
            if line.get("method_origin") != "line":
                continue
            method = str(line.get("method") or "")
            if method == project_method or _explained(line.get("method_comment")):
                continue
            out.append(
                self._result(
                    context,
                    "method_override_without_comment",
                    element_ref=str(line.get("key") or "") or None,
                    code=str(line.get("code") or ""),
                    method=method,
                    project_method=project_method,
                )
            )
        return out


FORECAST_RULES: tuple[type[_ForecastRule], ...] = (
    BelowCommitmentRule,
    MoveWithoutEvidenceRule,
    MethodOverrideWithoutCommentRule,
)

#: The spec's numbering of each rule (V21 belongs to the completion checksums).
RULE_NUMBERS: dict[str, str] = {
    BelowCommitmentRule.rule_id: "V19",
    MoveWithoutEvidenceRule.rule_id: "V20",
    MethodOverrideWithoutCommentRule.rule_id: "V22",
}


def register_cost_forecast_rules() -> None:
    """Register V19, V20 and V22 into the ``cost_forecast`` rule set."""
    for rule_cls in FORECAST_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered cost forecast validation rules")
