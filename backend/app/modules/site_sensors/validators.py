# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ ``site_sensors``.

Payload built by ``SiteSensorsService.validation_payload``::

    {"devices": [{"id", "code", "active", "offline"}],
     "exceedances": [{"id", "device", "status", "value", "limit"}],
     "strips": [{"id", "element", "struck", "target_mpa", "strength_at_strike_mpa"}],
     "evidence": [{"id", "device", "sha256", "readings", "filed"}],
     "bim_links": [{"id", "label", "model_id", "element_id"}]}

Each result carries ``details.message_key`` and its parameters for the client.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

SENSOR_RULE_SET = "site_sensors"


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    raw = data.get(key) or []
    return [r for r in raw if isinstance(r, dict)]


class _SensorRule(ValidationRule):
    standard = "site_sensors"
    category = RuleCategory.COMPLIANCE
    severity = Severity.WARNING
    key = ""
    text = ""
    rows_key = ""

    def _result(self, ref: str, passed: bool, **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else self.text.format(**params),
            element_ref=ref,
            details={"message_key": f"siteSensors.rules.{self.key}", **{k: str(v) for k, v in params.items()}},
        )

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [r for row in _rows(context, self.rows_key) if (r := self.check(row)) is not None]


class SensorOnline(_SensorRule):
    """An active sensor has reported within its offline window."""

    key = "sensor_online"
    rule_id = "site_sensors.sensor_online"
    name = "Sensor Online"
    description = "Every active sensor reported within its offline window."
    rows_key = "devices"
    text = "Sensor {device} has stopped reporting"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if not row.get("active"):
            return None
        return self._result(str(row.get("id")), not row.get("offline"), device=row.get("code", ""))


class ExceedanceAcknowledged(_SensorRule):
    """A reading above its limit has been seen and acknowledged by a person."""

    key = "exceedance_acknowledged"
    rule_id = "site_sensors.exceedance_acknowledged"
    name = "Exceedance Acknowledged"
    description = "Every limit exceedance is acknowledged."
    severity = Severity.ERROR
    rows_key = "exceedances"
    text = "Sensor {device} read {value} above its limit of {limit} and nobody has acknowledged it"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        return self._result(
            str(row.get("id")),
            row.get("status") != "open",
            device=row.get("device", ""),
            value=row.get("value"),
            limit=row.get("limit"),
        )


class StrikeAfterTargetStrength(_SensorRule):
    """Formwork was struck only once the estimated strength reached the target."""

    key = "strike_after_target_strength"
    rule_id = "site_sensors.strike_after_target_strength"
    name = "Strike After Target Strength"
    description = "No formwork is struck before the pour reaches its target strength."
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    rows_key = "strips"
    text = "Formwork on {element} was struck at {strength} MPa, below the target of {target} MPa"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        if not row.get("struck"):
            return None
        raw = row.get("strength_at_strike_mpa")
        strength = Decimal(str(raw)) if raw is not None else Decimal("0")
        target = Decimal(str(row.get("target_mpa") or 0))
        return self._result(
            str(row.get("id")), strength >= target, element=row.get("element", ""), strength=strength, target=target
        )


class EvidenceHashed(_SensorRule):
    """A filed sensor export carries a SHA-256 of its CSV, holds readings and has both documents."""

    key = "evidence_hashed"
    rule_id = "site_sensors.evidence_hashed"
    name = "Evidence Hashed"
    description = "Every sensor evidence export has an integrity code, readings and both documents filed."
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    rows_key = "evidence"
    text = "Evidence from {device} has no valid integrity code, no readings or a missing document"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        digest = str(row.get("sha256") or "")
        valid = len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
        ok = valid and int(row.get("readings") or 0) > 0 and bool(row.get("filed"))
        return self._result(str(row.get("id")), ok, device=row.get("device", ""))


class BimLinkComplete(_SensorRule):
    """A device or strike that names a BIM element also names the model the element is in."""

    key = "bim_link_complete"
    rule_id = "site_sensors.bim_link_complete"
    name = "BIM Link Complete"
    description = "A BIM element link always carries its model."
    category = RuleCategory.CONSISTENCY
    rows_key = "bim_links"
    text = "{label} links a BIM element without a model"

    def check(self, row: dict[str, Any]) -> RuleResult | None:
        return self._result(str(row.get("id")), bool(row.get("model_id")), label=row.get("label", ""))


SENSOR_RULES: tuple[type[_SensorRule], ...] = (
    SensorOnline,
    ExceedanceAcknowledged,
    StrikeAfterTargetStrength,
    EvidenceHashed,
    BimLinkComplete,
)


def register_sensor_rules() -> None:
    """Idempotently register the site sensor rules."""
    for rule in SENSOR_RULES:
        rule_registry.register(rule(), rule_sets=[SENSOR_RULE_SET])


async def run_rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every rule against one payload, as plain dicts."""
    context = ValidationContext(data=payload, metadata={})
    out: list[dict[str, Any]] = []
    for rule_cls in SENSOR_RULES:
        for r in await rule_cls().validate(context):
            out.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
            )
    return out


register_sensor_rules()
