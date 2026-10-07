"""France classifies to DPGF, and UNTEC stays readable for the rows that carry it.

Until 2026-10 the registry mapped FR to ``untec``, a standard with no rules in
the engine, while every French line the product ships is keyed
``classification["dpgf"]`` and the only French rule, ``dpgf.lot_required``,
reads that key. A French project created from the region picker was therefore
stored under a standard nothing checked. The decision was to register DPGF as
a classification standard and make it the French default.

Existing projects are not rewritten. A row whose ``classification_standard``
says ``untec`` keeps resolving to ``untec`` because an explicit standard wins
over the region, and the French country row in ``boq.router`` still adds the
``dpgf`` rule set to it, so it is validated against the French rules either way.
"""

from __future__ import annotations

from app.core.classification_registry import (
    CLASSIFICATION_STANDARD_LABELS,
    KNOWN_CLASSIFICATION_STANDARDS,
    resolve_standard,
)
from app.core.validation.engine import rule_registry
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.router import _STANDARD_RULE_SETS, _build_rule_sets


def test_a_french_region_resolves_to_dpgf() -> None:
    for region in ("FR", "France", "FR_PARIS"):
        resolved = resolve_standard(None, region)
        assert resolved.standard == "dpgf", region
        assert resolved.source == "region"


def test_dpgf_is_storable_and_named() -> None:
    assert "dpgf" in KNOWN_CLASSIFICATION_STANDARDS
    assert CLASSIFICATION_STANDARD_LABELS["dpgf"] == "DPGF"
    assert resolve_standard("dpgf", "FR").source == "explicit"


def test_a_project_already_stored_under_untec_keeps_it() -> None:
    """No stored row changes its standard because the default moved."""
    assert "untec" in KNOWN_CLASSIFICATION_STANDARDS
    resolved = resolve_standard("untec", "FR")
    assert resolved.standard == "untec"
    assert resolved.source == "explicit"


def test_francophone_africa_still_reads_untec() -> None:
    for region in ("SN", "CI", "CM"):
        assert resolve_standard(None, region).standard == "untec", region


def test_a_french_project_runs_the_dpgf_rules_the_engine_registers() -> None:
    """The rule-set name the router asks for must be one the engine has.

    The check is against the engine's own registry, not a list written here,
    because a standard whose rule-set name differs from its own name (tetelrend
    against hungary) logs an unknown set and validates nothing.
    """
    register_builtin_rules()
    registered = set(rule_registry.list_rule_sets())
    assert _STANDARD_RULE_SETS["dpgf"] == "dpgf"
    assert "dpgf" in registered

    for standard in ("dpgf", "untec", ""):
        rule_sets = _build_rule_sets(["boq_quality"], standard, "FR")
        assert "dpgf" in rule_sets, standard
        assert set(rule_sets) <= registered, (standard, sorted(set(rule_sets) - registered))
