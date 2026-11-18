# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out validation rules (rule set ``setting_out``).

Rules run over a plain dict context built by the service from each stake's
newest record::

    {"stakes": [{"request", "point_id", "verdict", "d_mm", "tol_h_mm",
                 "dz_mm", "tol_v_mm", "instrument", "control_ref", "measured"}]}

SET-001 error: a stake outside its tolerance (opens an NCR draft on request).
SET-002 warning: a stakeout record with no instrument or no control reference.
"""

from __future__ import annotations

from app.core.validation.engine import RuleCategory, RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, rows

SETTING_OUT_RULE_SET = "setting_out"


class _SettingOutRule(MoneyRule):
    standard = SETTING_OUT_RULE_SET
    message_section = "setting_out"
    category = RuleCategory.CONSISTENCY


def _fmt(value: object) -> str:
    try:
        return f"{float(value):.0f}" if float(value) == round(float(value)) else f"{float(value):.1f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "?"


class StakeWithinToleranceRule(_SettingOutRule):
    """SET-001: every measured stake is within its tolerance."""

    rule_id = "SET-001"
    name = "Stakes within tolerance"
    severity = Severity.ERROR
    description = "Radial deviation d = sqrt(dE^2 + dN^2) and dZ against the request's tolerance"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for s in rows(context, "stakes"):
            if not s.get("measured") or s.get("verdict") != "fail":
                continue
            pid = str(s.get("point_id") or "")
            tol_h = s.get("tol_h_mm")
            d = s.get("d_mm")
            # A height failure with the plan position inside tolerance reports dZ instead.
            if tol_h is not None and d is not None and float(d) <= float(tol_h) and s.get("dz_mm") is not None:
                d, tol_h = abs(float(s["dz_mm"])), s.get("tol_v_mm")
            out.append(
                self.fail(
                    context,
                    "stake_off",
                    ref=f"{s.get('request') or ''}/{pid}",
                    id=pid,
                    d=_fmt(d),
                    t=_fmt(tol_h),
                )
            )
        return out or [self.ok()]


class RecordTraceableRule(_SettingOutRule):
    """SET-002: a record names the instrument and the control it was set up on."""

    rule_id = "SET-002"
    name = "Stakeout records are traceable"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Instrument and control reference on every stakeout record"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self.fail(
                context,
                "record_untraceable",
                ref=f"{s.get('request') or ''}/{s.get('point_id') or ''}",
                id=str(s.get("point_id") or ""),
            )
            for s in rows(context, "stakes")
            if s.get("measured")
            and (not str(s.get("instrument") or "").strip() or not str(s.get("control_ref") or "").strip())
        ]
        return out or [self.ok()]


SETTING_OUT_RULES = (StakeWithinToleranceRule, RecordTraceableRule)


def register_setting_out_validation_rules() -> None:
    """Register the setting-out rules with the platform rule registry."""
    for rule_class in SETTING_OUT_RULES:
        rule_registry.register(rule_class(), [SETTING_OUT_RULE_SET])


__all__ = ["SETTING_OUT_RULES", "SETTING_OUT_RULE_SET", "register_setting_out_validation_rules"]


# Registered at import so a process that only loads this module still knows the rule set.
register_setting_out_validation_rules()
