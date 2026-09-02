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

Four gates, because each one alone has a blind spot the others cover.

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

``test_every_country_is_measured_against_its_own_national_rule_set`` asks the
question neither of the other two can. Both of them are satisfied by a country
reaching *a* jurisdiction pack; neither asks whether the pack it reached is
*its own*. Austria is the shape they miss. "AT" resolved to the DACH pack,
which runs DIN 276 and GAEB, so Austria reached a jurisdiction pack, cleared
both gates, and was measured against German standards while the registered
"onorm" set never ran for it. A country getting the neighbours' answer looks
exactly like a country getting its own, and this gate is the only place that
tells them apart.

The fourth gate is about a different word. The three above all measure
*reachability*, and reaching a rule set is not the same as being checked by it:
several rules skip a position whose field is empty, so a set can be reached,
run, and emit nothing. ``test_no_national_rule_set_is_inert_...`` and
``test_a_national_pack_answers_differently_...`` run the engine on the payload
``run_compliance_gate`` really builds and ask for findings, not for pack ids.

All four print their population next to the verdict. A gate whose population has
quietly shrunk is green for the wrong reason, so both registry-backed ones also
assert a floor: the demo registry and the pack registry each load behind a
``try/except`` that degrades to a smaller population rather than raising.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.core.validation.engine import rule_registry, validation_engine
from app.core.validation.project_context import with_project_context
from app.core.validation.rules import register_builtin_rules
from app.modules.contracts.compliance_packs import (
    DEFAULT_PACK_ID,
    RULE_PACKS,
    WORKFLOW_CONTRACT_SIGNATURE,
    resolve_pack,
    resolve_rule_sets,
)
from app.modules.contracts.models import ContractLine
from app.modules.contracts.service import ContractsService

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
    named = set(NO_NATIONAL_RULES_REGISTERED)

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
        "tag in NO_NATIONAL_RULES_REGISTERED with the reason no rule set in "
        "the engine is about it."
    )

    stale = sorted(named - on_baseline)
    assert not stale, (
        f"these tags are named as falling back to '{DEFAULT_PACK_ID}' but no longer do; "
        f"delete them from the exception tables: {stale}"
    )


# ── Gate 3: no country is measured against somebody else's standards ───────

#: The rule set a country's own projects have to be measured against.
#:
#: This is the table neither gate above can be written from, because both of
#: them are satisfied the moment a country reaches a pack that is not the
#: baseline, and neither asks whose pack it is. Austria reached one for months:
#: "AT" resolved to the DACH pack, which runs DIN 276 and GAEB, both of which
#: really are used in Austria, so nothing looked wrong. What never ran was
#: "onorm", the set the engine registers for the Austrian standard, and the
#: settings page cannot show the difference between a country's own pack and a
#: neighbour's.
#:
#: The table is written by hand, so what keeps it honest is the three
#: assertions below rather than its shape. Every set named here must be
#: registered in the engine, must be more than what the universal baseline
#: already runs, and must be reached by the pack the country really resolves
#: to. A row cannot be parked here to make a gate green without failing one of
#: them, and a new national pack cannot skip the table, because every pack that
#: claims a jurisdiction has to name its country here.
#:
#: Switzerland is deliberately absent, and the absence is the point of the
#: asymmetry with Austria: no Swiss rule set is registered at all, so the DACH
#: pack is the honest answer for a Swiss project rather than a substituted one.
#: Austria differs only in that "onorm" exists.
NATIONAL_RULE_SET_BY_COUNTRY: dict[str, str] = {
    "AT": "onorm",
    "BR": "sinapi",
    "CA": "masterformat",
    "CN": "gbt50500",
    "DE": "din276",
    "ES": "bc3",
    "FR": "dpgf",
    "GB": "nrm",
    "HU": "hungary",
    "IN": "cpwd",
    "JP": "sekisan",
    "MX": "mexico",
    "RU": "gesn",
    "TR": "birimfiyat",
    "US": "masterformat",
}


@pytest.mark.parametrize(
    ("code", "rule_set"),
    sorted(NATIONAL_RULE_SET_BY_COUNTRY.items()),
)
def test_the_national_rule_set_table_names_sets_that_really_exist(code: str, rule_set: str) -> None:
    """A row has to be checkable, or it is just a comment.

    Two ways a row could be fiction, and both are closed here. The engine may
    register nothing under the name, which is what happens when a rule set is
    deleted or renamed and the table is not followed. Or the name may be one
    the universal pack already runs, which would let a country be declared
    nationally covered by the cross-market baseline it was already getting.
    """
    register_builtin_rules()
    assert rule_registry.has_rules(rule_set), (
        f"{code} names rule set {rule_set!r} as its own, but the engine registers no rules under that name"
    )
    assert rule_set not in RULE_PACKS[DEFAULT_PACK_ID]["rule_sets"], (
        f"{code} names {rule_set!r} as its national rule set, but the "
        f"'{DEFAULT_PACK_ID}' pack already runs it for every country"
    )


def test_every_pack_that_claims_a_jurisdiction_is_named_in_the_table() -> None:
    """A national pack cannot ship without the table saying what it must run.

    One-directional on purpose. A country belongs in the table as soon as its
    rules are registered, whether or not a pack reaches them yet - that is how
    the gate below stays red until the pack ships. What must not happen is the
    reverse: a pack claiming a jurisdiction the table has never heard of, which
    would let it carry any rule sets at all without being checked.
    """
    claimed = {str(pack["jurisdiction"]) for pack in RULE_PACKS.values() if pack.get("jurisdiction")}
    print(
        f"\nPOPULATION: {len(claimed)} packs claim a jurisdiction, "
        f"{len(NATIONAL_RULE_SET_BY_COUNTRY)} countries name a national rule set"
    )
    unnamed = sorted(claimed - set(NATIONAL_RULE_SET_BY_COUNTRY))
    assert not unnamed, (
        "These packs claim a jurisdiction that NATIONAL_RULE_SET_BY_COUNTRY "
        f"does not name, so nothing checks what they run: {unnamed}"
    )


def test_every_country_is_measured_against_its_own_national_rule_set() -> None:
    """The gate the Austria case defeats when it is written on packs alone."""
    register_builtin_rules()
    rows = [
        (code, rule_set, resolve_pack(code, None)) for code, rule_set in sorted(NATIONAL_RULE_SET_BY_COUNTRY.items())
    ]
    reached = [(c, rs, p) for c, rs, p in rows if rs in resolve_rule_sets([p])]
    missing = [(c, rs, p) for c, rs, p in rows if rs not in resolve_rule_sets([p])]

    print(
        f"\nPOPULATION: {len(rows)} countries whose own rule set is registered; "
        f"{len(reached)} are measured against it by the pack they resolve to; "
        f"{len(missing)} are not"
    )

    assert not missing, (
        "These countries resolve to a pack that never runs their own rule "
        "set, so their contracts are signed against somebody else's "
        "standards or against the cross-market baseline alone:\n"
        + "\n".join(
            f"  {code}: needs {rule_set!r}, resolves to {pack!r} which runs {resolve_rule_sets([pack])}"
            for code, rule_set, pack in missing
        )
        + "\nAdd a pack whose rule_sets include that country's set, or extend "
        "the pack it already resolves to. Do not delete the row: a country "
        "whose rules are registered and unreachable is exactly what this gate "
        "is for."
    )


# ── Gate 4: reaching a rule set is not the same as being checked by it ──────
#
# Every gate above is satisfied by a pack id. None of them runs a rule. That
# gap is wide enough to walk a defect through, because a rule here reads its
# own keys off the position dict and several of them skip a position whose key
# is empty: ONORMPositionFormat, BirimFiyatValidPoz and SekisanMetricUnits all
# pass over a line with no ordinal, no classification code or no unit. A pack
# built only out of rules of that kind would name a jurisdiction, run, find
# nothing and report success, which is the shape this whole file exists to
# refuse.
#
# The payload matters as much as the rules. ``with_project_context`` adds
# exactly one key, ``project_unit_system``, so no region and no classification
# standard ever reaches a rule through the contract gate. A region-gated rule
# would therefore be silently inert here while looking perfectly covered, and
# the only way to tell is to run the engine and count findings. Positions come
# from the contract module's own mapper rather than from a dict written here,
# because a fixture that drifts from the mapper tests the fixture.
#
# These two run a rule set on its own rather than through a pack, and that is
# deliberate: a pack also carries the universal baseline, whose cost-
# concentration rule fires on any single-line bill, so no line could ever come
# back clean and "the pack accepts a compliant line" would be unassertable.
# The composition is with gate 3, not inside these: gate 3 says the country's
# pack reaches the set, and these say the set tells a compliant line from a
# non-compliant one. Neither half means anything without the other.


def _sov_line(
    code: str,
    description: str,
    unit: str,
    classification: dict[str, str] | None = None,
) -> ContractLine:
    """One schedule-of-values line, in the shape the contract module stores."""
    return ContractLine(
        id=uuid.uuid4(),
        code=code,
        description=description,
        unit=unit,
        quantity=Decimal("10"),
        unit_rate=Decimal("100"),
        total_value=Decimal("1000"),
        parent_line_id=None,
        metadata_={"classification": classification} if classification else {},
    )


def _findings(rule_sets: list[str], lines: list[ContractLine]) -> list[str]:
    """Rule ids that did not pass, measured through the gate's own two calls.

    ``_contract_lines_as_positions`` is invoked unbound because it reads
    nothing off ``self``, and ``with_project_context`` is invoked with no
    session because that is a supported call which yields the null key rather
    than omitting it. Both are the product's, not this test's.
    """
    positions = ContractsService._contract_lines_as_positions(None, lines)  # noqa: SLF001

    async def _run() -> Any:
        data = await with_project_context(None, uuid.uuid4(), {"positions": positions})
        return await validation_engine.validate(
            data=data,
            rule_sets=rule_sets,
            target_type="contract",
            target_id=str(uuid.uuid4()),
            project_id=str(uuid.uuid4()),
            metadata={"locale": "en", "workflow": WORKFLOW_CONTRACT_SIGNATURE},
        )

    report = asyncio.run(_run())
    assert not report.unsupported_rule_sets, (
        f"the engine does not know {report.unsupported_rule_sets}, so it ran nothing for them"
    )
    return sorted(r.rule_id for r in report.results if not r.passed)


def test_no_national_rule_set_is_inert_on_the_payload_the_gate_builds() -> None:
    """A set that finds nothing on a bare line checks nothing at signature.

    The bare line is a schedule-of-values row with an ordinal, a description, a
    unit and money, and no national code of any kind - which is exactly what a
    contract drafted without the local standard looks like. Every national set
    is expected to have something to say about it. A set that says nothing is
    either gated on a key the contract payload never carries or is checking
    something a schedule of values cannot express, and either way naming it in
    a pack tells a signer their jurisdiction was checked when it was not.
    """
    register_builtin_rules()
    bare = [_sov_line("1", "Excavation", "m3")]
    findings = {
        rule_set: _findings([rule_set], bare) for rule_set in sorted(set(NATIONAL_RULE_SET_BY_COUNTRY.values()))
    }
    silent = sorted(rs for rs, found in findings.items() if not found)

    print(
        f"\nPOPULATION: {len(findings)} distinct national rule sets run against a bare "
        f"schedule-of-values line; {len(findings) - len(silent)} produce findings, {len(silent)} are silent"
    )

    assert not silent, (
        "These rule sets are reachable from a pack and find nothing on a line "
        f"carrying no national code at all: {silent}. Either the rules are "
        "gated on a key the contract payload never carries (it carries "
        "positions plus project_unit_system and nothing else), or the pack "
        "naming them claims a check it does not perform."
    )


#: The three packs whose lines this file writes out in full, with a compliant
#: and a malformed code apiece. Three and not fifteen on purpose: a compliant
#: line has to be written against the standard itself, and inventing eleven
#: more from the rule sources would be asserting what the regex says rather
#: than what the standard says. The test above covers all fifteen for the
#: weaker property, that none of them is inert.
_DISCRIMINATION_CASES: dict[str, dict[str, list[ContractLine]]] = {
    "AT": {
        "bare": [_sov_line("1", "Excavation", "m3")],
        "compliant": [_sov_line("01.02.0030", "Bored pile shoring wall, 800 mm diameter, C30/37", "m")],
        "malformed": [_sov_line("1-2-3", "Bored pile shoring wall, 800 mm diameter, C30/37", "m")],
    },
    "JP": {
        "bare": [_sov_line("1", "Excavation", "m3")],
        "compliant": [_sov_line("1.1", "Excavation", "m3", {"sekisan": "1-2-3"})],
        "malformed": [_sov_line("1.1", "Excavation", "fathom", {"sekisan": "1-2-3"})],
    },
    "TR": {
        "bare": [_sov_line("1", "Excavation", "m3")],
        "compliant": [_sov_line("1.1", "Excavation", "m3", {"birimfiyat": "15.140"})],
        "malformed": [_sov_line("1.1", "Excavation", "m3", {"birimfiyat": "NOT-A-POZ"})],
    },
}


@pytest.mark.parametrize("code", sorted(_DISCRIMINATION_CASES))
def test_a_national_pack_answers_differently_to_a_compliant_line(code: str) -> None:
    """The pack has to tell a compliant line from a non-compliant one.

    Three lines rather than two, because a rule that skips an empty field
    proves nothing on a bare line. The malformed line carries a national code
    that is present but wrong, which is the only input the format rules ever
    look at.
    """
    register_builtin_rules()
    rule_set = NATIONAL_RULE_SET_BY_COUNTRY[code]
    cases = _DISCRIMINATION_CASES[code]
    found = {label: _findings([rule_set], lines) for label, lines in cases.items()}

    print(f"\nPOPULATION: {code} / {rule_set!r} over {len(cases)} lines: {found}")

    assert found["bare"], f"{rule_set} finds nothing on a line with no national code"
    assert not found["compliant"], f"{rule_set} rejects a line written to its own standard: {found['compliant']}"
    assert found["malformed"], f"{rule_set} accepts a malformed national code, so its format rules never run"
