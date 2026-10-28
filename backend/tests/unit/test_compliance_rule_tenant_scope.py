# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tenant-isolation tests for compliance DSL rule registration.

The validation ``rule_registry`` is a single process-global singleton with
no tenant dimension. Compliance DSL rules are authored per tenant, so the
service must namespace every rule by its tenant before it touches the
registry - otherwise (a) tenant B could run a rule set by name and execute
tenant A's rule against tenant B's data, and (b) a tenant could register a
``rule_id`` / ``standard`` matching a built-in and overwrite the built-in's
body, or inject into a built-in set, for everyone.

These tests exercise the namespacing helpers directly and via a real
``compile_rule`` + ``rule_registry.register`` round-trip, and assert that:

* built-ins (bare id, bare set) are never overwritten or polluted;
* a tenant's rule is reachable ONLY under its ``t:{tenant}:`` scoped id and
  scoped set;
* the bare/global set does not gain the tenant's scoped id;
* one tenant's delete cannot evict a built-in or another tenant's rule;
* a tenant cannot escape its namespace by stuffing colons into ``standard``
  or ``rule_sets`` (only ``rule_id`` is colon-restricted by the parser).

Every test cleans the registry entries it adds so global state never leaks
into other tests in the shard.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterator

import pytest

from app.core.validation.engine import rule_registry
from app.core.validation.rules import register_builtin_rules
from app.modules.compliance.service import (
    _deregister_compiled,
    _ns,
    _register_compiled,
    _scoped_rule_id,
    _scoped_sets,
)

# A built-in rule that exists in the hand-coded registry. A tenant that
# submits this exact id + standard is the worst case: without scoping it would
# overwrite the built-in body and join the global ``din276`` set.
BUILTIN_RULE_ID = "din276.cost_group_required"
BUILTIN_SET = "din276"


# ── Helpers / fixtures ──────────────────────────────────────────────────────


def _definition_yaml(rule_id: str, standard: str, *, rule_sets: list[str] | None = None) -> str:
    """Minimal valid DSL document with a controllable id / standard / sets."""
    lines = [
        f"rule_id: {rule_id}",
        "name: Tenant scope probe",
        "severity: error",
        f"standard: {standard}",
        "scope: positions",
        "expression:",
        "  forEach: position",
        "  assert: position.quantity > 0",
    ]
    if rule_sets is not None:
        # Inline-list form keeps YAML simple and unambiguous.
        joined = ", ".join(rule_sets)
        lines.insert(4, f"rule_sets: [{joined}]")
    return textwrap.dedent("\n".join(lines))


def _parse(yaml_text: str):
    # Imported lazily so a parser import error surfaces inside the test body
    # (clear traceback) rather than at module-collection time.
    from app.core.validation.dsl import parse_definition

    return parse_definition(yaml_text)


def _registry_snapshot() -> tuple[set[str], dict[str, list[str]]]:
    """Copy the registry's id set and per-set membership for diffing."""
    rules = dict(rule_registry._rules)  # noqa: SLF001 - test introspection
    sets = {name: list(ids) for name, ids in rule_registry._rule_sets.items()}  # noqa: SLF001
    return set(rules), sets


@pytest.fixture(autouse=True)
def _restore_registry() -> Iterator[None]:
    """Snapshot the registry before each test and restore it afterwards.

    Built-ins are (re-)registered first so the "built-in present" assertions
    are meaningful even when this is the first test to touch the registry.
    Restoring from the snapshot then removes anything a test added and re-adds
    anything it removed, so no test can leak scoped ids into another.
    """
    register_builtin_rules()
    saved_ids, saved_sets = _registry_snapshot()
    saved_rule_objs = dict(rule_registry._rules)  # noqa: SLF001
    try:
        yield
    finally:
        live_rules = rule_registry._rules  # noqa: SLF001
        live_sets = rule_registry._rule_sets  # noqa: SLF001
        # Drop ids the test added.
        for rid in list(live_rules):
            if rid not in saved_ids:
                live_rules.pop(rid, None)
        # Re-add ids the test removed (restore original object identity).
        for rid in saved_ids:
            if rid not in live_rules:
                live_rules[rid] = saved_rule_objs[rid]
        # Reset set membership wholesale to the snapshot.
        live_sets.clear()
        live_sets.update({name: list(ids) for name, ids in saved_sets.items()})


# ── Pure helper behaviour ───────────────────────────────────────────────────


def test_ns_distinguishes_tenants_and_system() -> None:
    assert _ns("A") == "t:A"
    assert _ns("B") == "t:B"
    assert _ns(None) == "t:__system__"
    assert _ns("A") != _ns("B")


def test_scoped_rule_id_is_prefixed() -> None:
    assert _scoped_rule_id("A", BUILTIN_RULE_ID) == f"t:A:{BUILTIN_RULE_ID}"
    # Distinct tenants never collide on the same bare id.
    assert _scoped_rule_id("A", BUILTIN_RULE_ID) != _scoped_rule_id("B", BUILTIN_RULE_ID)


def test_scoped_sets_defaults_to_standard_then_prefixes() -> None:
    # No explicit sets -> registry default is [standard]; we then prefix it.
    assert _scoped_sets("A", None, "din276") == ["t:A:din276"]
    # Explicit sets are each prefixed.
    assert _scoped_sets("A", ["custom", "acme"], "din276") == ["t:A:custom", "t:A:acme"]


def test_scoped_sets_neutralises_colon_spoofing() -> None:
    # standard / rule_sets are NOT colon-restricted by the parser, so a tenant
    # could try to name another tenant's namespace. The unconditional prefix
    # still confines them to their own bucket.
    spoof = _scoped_sets("attacker", ["t:victim:din276"], "t:victim:din276")
    assert spoof == ["t:attacker:t:victim:din276"]
    assert "t:victim:din276" not in spoof


def test_empty_rule_sets_tuple_yields_none_for_default() -> None:
    # The parser stores rule_sets as a tuple; an empty tuple must collapse to
    # None so _scoped_sets falls back to [standard] (mirrors the call site
    # ``list(definition.rule_sets) or None``).
    definition = _parse(_definition_yaml("custom.no_sets", "custom"))
    assert definition.rule_sets == ()
    assert (list(definition.rule_sets) or None) is None
    assert _scoped_sets("A", list(definition.rule_sets) or None, definition.standard) == ["t:A:custom"]


# ── Register round-trip: built-in is never overwritten ──────────────────────


def test_tenant_rule_does_not_overwrite_builtin() -> None:
    # Sanity: the built-in is present before we start.
    builtin_obj = rule_registry.get_rule(BUILTIN_RULE_ID)
    assert builtin_obj is not None, "built-in din276 rule must be registered"
    assert BUILTIN_RULE_ID in rule_registry._rule_sets.get(BUILTIN_SET, [])  # noqa: SLF001

    # Tenant A submits a rule with the SAME bare id and standard as the built-in.
    definition = _parse(_definition_yaml(BUILTIN_RULE_ID, BUILTIN_SET))
    registered = _register_compiled(definition, "A")

    # (a) The built-in object at the bare id is byte-for-byte the same object -
    #     not replaced by the tenant's compiled rule.
    assert rule_registry.get_rule(BUILTIN_RULE_ID) is builtin_obj
    assert rule_registry.get_rule(BUILTIN_RULE_ID) is not registered

    # (b) The tenant rule is reachable ONLY under its scoped id.
    scoped_id = f"t:A:{BUILTIN_RULE_ID}"
    assert registered.rule_id == scoped_id
    assert rule_registry.get_rule(scoped_id) is registered

    # (c) The scoped set exists and contains the scoped id; the bare/global
    #     ``din276`` set is untouched and never gains the scoped id.
    scoped_set = f"t:A:{BUILTIN_SET}"
    assert scoped_id in rule_registry._rule_sets.get(scoped_set, [])  # noqa: SLF001
    assert scoped_id not in rule_registry._rule_sets.get(BUILTIN_SET, [])  # noqa: SLF001
    assert BUILTIN_RULE_ID in rule_registry._rule_sets.get(BUILTIN_SET, [])  # noqa: SLF001


def test_two_tenants_same_id_are_isolated() -> None:
    definition_a = _parse(_definition_yaml(BUILTIN_RULE_ID, BUILTIN_SET))
    definition_b = _parse(_definition_yaml(BUILTIN_RULE_ID, BUILTIN_SET))
    rule_a = _register_compiled(definition_a, "A")
    rule_b = _register_compiled(definition_b, "B")

    assert rule_a.rule_id == f"t:A:{BUILTIN_RULE_ID}"
    assert rule_b.rule_id == f"t:B:{BUILTIN_RULE_ID}"
    # Distinct registry entries - B did not overwrite A.
    assert rule_registry.get_rule(rule_a.rule_id) is rule_a
    assert rule_registry.get_rule(rule_b.rule_id) is rule_b

    # B running A's scoped set name still only resolves A's rule, and vice
    # versa - the two scoped sets do not bleed into each other.
    a_rules = rule_registry.get_rules_for_sets([f"t:A:{BUILTIN_SET}"])
    b_rules = rule_registry.get_rules_for_sets([f"t:B:{BUILTIN_SET}"])
    assert rule_a in a_rules and rule_a not in b_rules
    assert rule_b in b_rules and rule_b not in a_rules


def test_tenant_cannot_inject_into_global_set_via_custom_rule_sets() -> None:
    # Tenant tries to land in the global "boq_quality" set by naming it.
    definition = _parse(_definition_yaml("acme.custom_check", "custom", rule_sets=["boq_quality", "din276"]))
    registered = _register_compiled(definition, "A")
    scoped_id = registered.rule_id
    assert scoped_id == "t:A:acme.custom_check"

    # The global sets did not gain the tenant's rule; only the scoped variants did.
    assert scoped_id not in rule_registry._rule_sets.get("boq_quality", [])  # noqa: SLF001
    assert scoped_id not in rule_registry._rule_sets.get("din276", [])  # noqa: SLF001
    assert scoped_id in rule_registry._rule_sets.get("t:A:boq_quality", [])  # noqa: SLF001
    assert scoped_id in rule_registry._rule_sets.get("t:A:din276", [])  # noqa: SLF001


# ── Deregister isolation ────────────────────────────────────────────────────


def test_deregister_removes_only_the_tenant_scoped_rule() -> None:
    builtin_obj = rule_registry.get_rule(BUILTIN_RULE_ID)
    assert builtin_obj is not None

    definition = _parse(_definition_yaml(BUILTIN_RULE_ID, BUILTIN_SET))
    _register_compiled(definition, "A")
    scoped_id = f"t:A:{BUILTIN_RULE_ID}"
    assert rule_registry.get_rule(scoped_id) is not None

    # Deleting tenant A's rule must remove ONLY the scoped entry.
    _deregister_compiled("A", BUILTIN_RULE_ID)

    assert rule_registry.get_rule(scoped_id) is None
    assert scoped_id not in rule_registry._rule_sets.get(f"t:A:{BUILTIN_SET}", [])  # noqa: SLF001
    # Built-in body and its bare-set membership survive untouched.
    assert rule_registry.get_rule(BUILTIN_RULE_ID) is builtin_obj
    assert BUILTIN_RULE_ID in rule_registry._rule_sets.get(BUILTIN_SET, [])  # noqa: SLF001


def test_deregister_with_wrong_tenant_is_a_noop() -> None:
    definition = _parse(_definition_yaml(BUILTIN_RULE_ID, BUILTIN_SET))
    _register_compiled(definition, "A")
    scoped_id = f"t:A:{BUILTIN_RULE_ID}"

    # Tenant B tries to deregister the same bare id - must not touch A's entry.
    _deregister_compiled("B", BUILTIN_RULE_ID)

    assert rule_registry.get_rule(scoped_id) is not None
    assert scoped_id in rule_registry._rule_sets.get(f"t:A:{BUILTIN_SET}", [])  # noqa: SLF001
