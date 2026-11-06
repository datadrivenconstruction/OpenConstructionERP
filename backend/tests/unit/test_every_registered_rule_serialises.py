"""Every registered rule must serialise the way GET /api/system/validation-rules does.

A rule class that forgets a required attribute (``standard``, ``severity``...)
registers fine and then crashes the listing endpoint for every caller.
"""

from __future__ import annotations

import importlib
import json
import pathlib

from app.core.validation.engine import RuleCategory, Severity, ValidationRule, rule_registry
from app.core.validation.rules import register_builtin_rules

_REQUIRED = ("rule_id", "name", "standard", "severity", "category")


def _load_all_rules() -> None:
    register_builtin_rules()
    modules = pathlib.Path(__file__).resolve().parents[2] / "app" / "modules"
    for p in sorted(modules.glob("*/validators.py")):
        try:
            importlib.import_module(f"app.modules.{p.parent.name}.validators")
        except Exception:  # noqa: BLE001 - modules needing a database are checked where they load
            continue


def test_every_registered_rule_has_the_attributes_the_listing_reads() -> None:
    _load_all_rules()
    rules = list(rule_registry._rules.values())
    assert len(rules) > 100
    broken = {}
    for rule in rules:
        assert isinstance(rule, ValidationRule)
        missing = [a for a in _REQUIRED if not hasattr(rule, a)]
        if not missing:
            if not isinstance(rule.severity, Severity):
                missing.append("severity (not a Severity)")
            if not isinstance(rule.category, RuleCategory):
                missing.append("category (not a RuleCategory)")
            if not isinstance(rule.standard, str) or not rule.standard:
                missing.append("standard (empty)")
        if missing:
            broken[type(rule).__name__] = missing
    assert not broken, f"rules the listing endpoint would crash on: {broken}"


def test_the_listing_payload_serialises_for_every_rule() -> None:
    _load_all_rules()
    payload = {"rule_sets": rule_registry.list_rule_sets(), "rules": rule_registry.list_rules()}
    assert len(json.dumps(payload)) > 0
    assert len(payload["rules"]) == len(rule_registry._rules)
