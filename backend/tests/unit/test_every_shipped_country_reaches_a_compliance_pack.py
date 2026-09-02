# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country the product ships for must reach a compliance pack, or be named here.

The failure this file exists to catch is silent. ``resolve_pack`` answers for
every country, because an unmatched one falls back to ``universal``, and the
settings page renders a pack id either way. So a country whose national rules
were written, registered and shipped can sit behind the cross-market baseline
for months with nothing red anywhere: the gate runs, it passes, and the user is
told a pack is enforced. Nothing in the product distinguishes "this country's
pack ran" from "no pack claimed this country".

Two gates, because either one alone has a blind spot the other covers.

``test_every_declared_rule_set_is_reachable_from_a_pack`` walks the rule sets
the shipped demo templates and country packs declare and asks whether any
compliance pack reaches them. It catches a *rule set* that exists but is dead
code from the gate's point of view. It is blind to a country whose demos
declare only sets that some other country's pack already reaches: both Canadian
demos declare ``masterformat``, which ``us_compliance`` reaches, so this gate
saw Canada as covered while ``resolve_pack("CA")`` returned ``universal``.

``test_every_shipped_country_resolves_to_more_than_the_baseline`` walks the
countries instead and asks what ``resolve_pack`` actually answers for each. It
catches the Canada case, and it is blind to a rule set nobody's demo declares.

Both print their population next to the verdict. A gate whose population has
quietly shrunk is green for the wrong reason, so both also assert a floor: the
demo registry and the pack registry each load behind a ``try/except`` that
degrades to a smaller population rather than raising.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import rule_registry
from app.core.validation.rules import register_builtin_rules
from app.modules.contracts.compliance_packs import (
    DEFAULT_PACK_ID,
    RULE_PACKS,
    resolve_pack,
)

# ── Populations, taken from the two paths that actually ship a country ──────
#
# Demo templates carry a free-text ``region`` ("CN", "UK", "DACH", "France"),
# which is the column ``resolve_pack`` consults when no ISO country is on the
# record. Country packs carry an ISO code in ``metadata["country"]``. Each is
# run through ``resolve_pack`` the way the product runs it, rather than through
# an assumed shape.


def _demo_templates() -> dict[str, object]:
    from app.core.demo_projects import DEMO_TEMPLATES

    return dict(DEMO_TEMPLATES)


def _shipped_packs() -> list[object]:
    from app.core.partner_pack import discovery

    return list(discovery.discover_packs())


#: Floors, not exact counts. The exact number moves whenever a demo or a pack
#: ships, and a test that pins it would be edited on every unrelated change
#: until somebody edited it downwards without noticing. What must never happen
#: is the population collapsing, because both registries swallow a load failure
#: and carry on with fewer entries.
MIN_DEMO_TEMPLATES = 40
MIN_SHIPPED_PACKS = 18


# ── Gate 1: no rule set is declared and then left unreachable ───────────────

#: Rule sets a shipped demo or pack declares that NO compliance pack reaches,
#: deliberately. Each one is here because it is not a jurisdiction rule set: it
#: belongs to a module that runs it through its own service call, so reaching it
#: from a country's contract-signature gate would enforce something that has
#: nothing to do with the country. The reason matters more than the entry - a
#: set parked here to make the gate green would defeat the gate.
NON_JURISDICTION_RULE_SETS: dict[str, str] = {
    "formwork": (
        "Registered by the formwork module's own validators and run by that "
        "module's service. Declared by the doker-formwork pack, which is a "
        "trade pack with no country, so no jurisdiction should reach it."
    ),
    "project_completeness": (
        "Registered by the carbon module's validators, not by "
        "register_builtin_rules. A cross-cutting completeness set the demo "
        "path runs directly; it names no jurisdiction and blocking a contract "
        "signature on it would be a different decision from this one."
    ),
}


def _declared_rule_sets() -> dict[str, set[str]]:
    """Every rule set a shipped demo template or country pack declares."""
    declared: dict[str, set[str]] = {}
    for demo_id, template in _demo_templates().items():
        for rs in getattr(template, "validation_rule_sets", None) or []:
            declared.setdefault(rs, set()).add(f"demo:{demo_id}")
    for manifest in _shipped_packs():
        slug = getattr(manifest, "slug", "?")
        for rs in getattr(manifest, "validation_rule_sets", None) or []:
            declared.setdefault(rs, set()).add(f"pack:{slug}")
    return declared


def _pack_reachable_rule_sets() -> set[str]:
    """Every rule set some compliance pack can put in front of the engine."""
    return {rs for pack in RULE_PACKS.values() for rs in pack.get("rule_sets", [])}


def test_the_populations_this_file_asserts_over_actually_loaded() -> None:
    """Print the population, and refuse to run the gates over a collapsed one."""
    demos = _demo_templates()
    packs = _shipped_packs()
    print(f"\nPOPULATION: {len(demos)} demo templates, {len(packs)} shipped packs")
    assert len(demos) >= MIN_DEMO_TEMPLATES, (
        f"only {len(demos)} demo templates loaded (expected at least {MIN_DEMO_TEMPLATES}). "
        "app.core.demo_projects swallows a pack-template load failure, so a short "
        "population here means the loader broke, not that demos were deleted."
    )
    assert len(packs) >= MIN_SHIPPED_PACKS, (
        f"only {len(packs)} packs discovered (expected at least {MIN_SHIPPED_PACKS})."
    )


def test_every_declared_rule_set_is_reachable_from_a_pack() -> None:
    """A rule set that ships and no pack reaches is dead code that reads as coverage."""
    declared = _declared_rule_sets()
    reachable = _pack_reachable_rule_sets()
    unreachable = {rs: sorted(who) for rs, who in declared.items() if rs not in reachable}

    print(
        f"\nPOPULATION: {len(declared)} distinct rule sets declared by shipped demos and packs, "
        f"of which {len(declared) - len(unreachable)} are reachable from a compliance pack and "
        f"{len(unreachable)} are not ({len(NON_JURISDICTION_RULE_SETS)} named as deliberate). "
        f"Packs reach {len(reachable)} sets in total."
    )

    unexpected = {rs: who for rs, who in unreachable.items() if rs not in NON_JURISDICTION_RULE_SETS}
    assert not unexpected, (
        "These rule sets ship, but no compliance pack reaches them, so the "
        "contract-signature gate never runs them:\n"
        + "\n".join(f"  {rs}: declared by {', '.join(who)}" for rs, who in sorted(unexpected.items()))
        + "\nAdd a pack whose rule_sets name the set, or name it in "
        "NON_JURISDICTION_RULE_SETS with the reason it must not be reachable."
    )

    stale = sorted(set(NON_JURISDICTION_RULE_SETS) - set(unreachable))
    assert not stale, f"NON_JURISDICTION_RULE_SETS names sets that are now reachable or gone: {stale}"


def test_every_rule_set_a_pack_names_is_registered_in_the_engine() -> None:
    """A pack pointing at a set the engine does not know runs nothing, silently.

    ``get_rules_for_sets`` skips an unknown set name, so a typo in a pack's
    ``rule_sets`` costs the whole jurisdiction its checks and reports success.
    Membership, never a count: the registry's contents depend on what a run has
    imported, so a count taken here disagrees with itself when the file runs
    alone versus inside the suite.
    """
    register_builtin_rules()
    known = set(rule_registry.list_rule_sets())
    print(f"\nPOPULATION: {len(RULE_PACKS)} packs naming {len(_pack_reachable_rule_sets())} distinct rule sets")
    missing = {
        pack_id: [rs for rs in pack.get("rule_sets", []) if rs not in known]
        for pack_id, pack in RULE_PACKS.items()
        if any(rs not in known for rs in pack.get("rule_sets", []))
    }
    assert not missing, f"packs name rule sets the engine does not register: {missing}"


def test_no_pack_claims_a_jurisdiction_while_carrying_only_the_baseline() -> None:
    """A national pack whose rule sets are just the universal baseline is a lie.

    It tells the user their jurisdiction is checked while running exactly the
    cross-market rules the default already ran. That is worse than the honest
    fallback, which at least reads as absent.
    """
    baseline = set(RULE_PACKS[DEFAULT_PACK_ID]["rule_sets"])
    hollow = [
        pack_id
        for pack_id, pack in RULE_PACKS.items()
        if pack.get("jurisdiction") and not (set(pack.get("rule_sets", [])) - baseline)
    ]
    print(f"\nPOPULATION: {sum(1 for p in RULE_PACKS.values() if p.get('jurisdiction'))} packs claiming a jurisdiction")
    assert not hollow, (
        f"these packs name a jurisdiction but add nothing to the universal baseline {sorted(baseline)}: {hollow}"
    )


# ── Gate 2: no shipped country falls through to the baseline unnoticed ──────

#: Country tags whose projects deliberately get the universal pack, because no
#: rule set in the engine is about that country. The universal pack is the
#: honest answer here: it says "cross-market checks only", which is the truth.
NO_NATIONAL_RULES_REGISTERED: dict[str, str] = {
    "AE": "No Emirati rule set is registered; the Abu Dhabi demo measures to MasterFormat.",
    "AU": "No Australian rule set is registered; the AS/NZS packs declare NRM.",
    "EU": "Not a country. Two cross-region demos carry it as their region tag.",
    "IT": "No Italian rule set is registered. Nothing in the engine reads a DEI or computo metrico code.",
    "KR": "No Korean rule set is registered.",
    "Middle East": "Not a country. The built-in Dubai demo carries it as free text.",
    "NL": "No Dutch rule set is registered; nothing reads an NL-SfB or STABU code.",
    "NZ": "No New Zealand rule set is registered; the NZS pack declares NRM.",
    "PL": "No Polish rule set is registered; nothing reads a KNR code.",
    "SA": "No Saudi rule set is registered; the Vision 2030 pack declares MasterFormat.",
    "XX": "Not a country. The cross-region trade packs use it to mean 'no country'.",
    "ZA": "No South African rule set is registered; the pack declares MasterFormat.",
}

#: Country tags whose national rule set IS written and registered, but which no
#: compliance pack reaches yet. This is a backlog, not a design decision, and
#: the assertion below keeps it honest: each entry must name a set the engine
#: really registers, so an entry cannot survive by being vague.
NATIONAL_RULES_REGISTERED_BUT_NO_PACK_YET: dict[str, str] = {
    "JP": "sekisan",
    "TR": "birimfiyat",
}


def _country_tags() -> dict[tuple[str, str], set[str]]:
    """Every country tag the product ships, keyed by ``(column, tag)``.

    The column matters and cannot be guessed from the tag's shape. A demo
    template's ``region`` is free text and reaches ``resolve_pack`` as the
    region argument; a pack's ``metadata["country"]`` is an ISO code and
    reaches it as the country argument. Two letters does not settle which:
    "UK" is exactly the everyday abbreviation that is NOT an ISO code, and
    routing it through the country column resolves it to the universal pack
    while the product, reading it as a region, resolves it to the UK pack.
    Guessing here would have invented a defect the product does not have.
    """
    tags: dict[tuple[str, str], set[str]] = {}
    for demo_id, template in _demo_templates().items():
        region = getattr(template, "region", None)
        if region:
            tags.setdefault(("region", str(region)), set()).add(f"demo:{demo_id}")
    for manifest in _shipped_packs():
        meta = getattr(manifest, "metadata", None) or {}
        country = meta.get("country") if isinstance(meta, dict) else None
        if country:
            tags.setdefault(("country", str(country)), set()).add(f"pack:{getattr(manifest, 'slug', '?')}")
    return tags


def _resolved_pack_for_tag(column: str, tag: str) -> str:
    """Resolve a tag through the same column the product reads it from."""
    return resolve_pack(tag, None) if column == "country" else resolve_pack(None, tag)


def test_every_shipped_country_resolves_to_more_than_the_baseline() -> None:
    """The gate the Canada case defeats when it is written on rule sets alone."""
    tags = _country_tags()
    on_baseline = {tag for (column, tag) in tags if _resolved_pack_for_tag(column, tag) == DEFAULT_PACK_ID}
    named = set(NO_NATIONAL_RULES_REGISTERED) | set(NATIONAL_RULES_REGISTERED_BUT_NO_PACK_YET)

    distinct = {tag for _column, tag in tags}
    print(
        f"\nPOPULATION: {len(tags)} (column, tag) pairs over {len(distinct)} distinct country tags "
        f"shipped by demos and packs; {len(distinct) - len(on_baseline)} reach a jurisdiction pack; "
        f"{len(on_baseline)} fall back to '{DEFAULT_PACK_ID}' ({len(named)} named as expected)"
    )

    shippers = {tag: sorted({w for (_c, t), who in tags.items() if t == tag for w in who}) for tag in distinct}
    fell_through = sorted(on_baseline - named)
    assert not fell_through, (
        "These country tags ship, and their projects silently get the "
        f"cross-market '{DEFAULT_PACK_ID}' pack at contract signature:\n"
        + "\n".join(f"  {tag}: shipped by {', '.join(shippers[tag])}" for tag in fell_through)
        + "\nEither add a pack whose jurisdiction is that country, or name the "
        "tag in NO_NATIONAL_RULES_REGISTERED / "
        "NATIONAL_RULES_REGISTERED_BUT_NO_PACK_YET with a reason."
    )

    stale = sorted(named - on_baseline)
    assert not stale, (
        f"these tags are named as falling back to '{DEFAULT_PACK_ID}' but no longer do; "
        f"delete them from the exception tables: {stale}"
    )


@pytest.mark.parametrize(
    ("code", "rule_set"),
    sorted(NATIONAL_RULES_REGISTERED_BUT_NO_PACK_YET.items()),
)
def test_the_backlog_names_rule_sets_that_really_exist(code: str, rule_set: str) -> None:
    """A backlog entry has to be checkable, or it is just a comment.

    Each country parked here claims its rules are already written. Assert the
    engine really registers the named set, so the entry cannot quietly become
    fiction, and so deleting the set without clearing the entry goes red.
    """
    register_builtin_rules()
    assert rule_registry.has_rules(rule_set), (
        f"{code} is parked in the backlog claiming rule set {rule_set!r} exists, "
        "but the engine registers no rules under that name"
    )
