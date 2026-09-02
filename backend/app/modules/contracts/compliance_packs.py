# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance rule packs for contract gates.

A *rule pack* is a jurisdiction-scoped bundle of validation rule-SET ids
(the same set names the core :class:`ValidationEngine` already knows -
``boq_quality``, ``din276``, ``gaeb``, ``nrm``, ``masterformat`` …). Each
pack also declares which workflow gates enforce it (currently only
``contract_signature``).

These packs are deterministic seed data, not user-authored DSL - they map a
project's region to a concrete, runnable set of validation rules so the
compliance gate that runs on a contract ``draft → active`` transition has
something real to execute. A project picks which packs it enforces via the
``Project.compliance_rule_packs`` JSON column; the gate resolves the union
of every pack's ``rule_sets`` and feeds them to the validation engine.

Design choices:
    * ``rule_sets`` reference rule sets that genuinely exist in the engine's
      registry. Unknown set names are simply skipped by the engine
      (``get_rules_for_sets`` ignores them), so a pack can declare an
      aspirational set without crashing - but the shipped packs only list
      sets we actually register, so the gate always evaluates real rules.
    * The ``universal`` pack is the safe default for any project with no
      region match - it enforces the cross-market ``boq_quality`` rule set.
    * Region → pack auto-mapping is a *suggestion*; projects can override.
"""

from __future__ import annotations

from typing import Any

# ── Workflow gate identifiers ──────────────────────────────────────────────

WORKFLOW_CONTRACT_SIGNATURE = "contract_signature"


# ── Pack registry ──────────────────────────────────────────────────────────
#
# ``rule_sets`` are the names the ValidationEngine resolves via
# ``rule_registry.get_rules_for_sets``. Keep every entry pointing at a set
# that is registered in app.core.validation.rules so the gate always runs
# real checks.

RULE_PACKS: dict[str, dict[str, Any]] = {
    "universal": {
        "id": "universal",
        "name": "Universal Compliance",
        "description": "Cross-market quality and completeness checks applied "
        "to the contract's schedule of values before signature.",
        "jurisdiction": None,
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality"],
    },
    "de_compliance": {
        "id": "de_compliance",
        "name": "Germany / DACH Compliance",
        "description": "DIN 276 cost-group structure and GAEB tender-format "
        "checks plus the universal quality baseline. Covers Germany and "
        "Switzerland, and a project tagged with the DACH region as a whole; "
        "Austria adds ÖNORM on top of these through its own pack.",
        "jurisdiction": "DE",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "din276", "gaeb"],
    },
    "uk_compliance": {
        "id": "uk_compliance",
        "name": "United Kingdom Compliance",
        "description": "NRM measurement-rule compliance plus the statutory declarations a UK "
        "contract turns on - contract form, payment regime, retention, CDM 2015 duty holders, "
        "the Building Safety Act higher-risk regime and VAT treatment - and the universal "
        "quality baseline.",
        "jurisdiction": "GB",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        # ``uk_statutory`` was registered and shipped, and two surfaces already
        # declared it (the London demo and the uk-jct pack), but no pack reached
        # it, so the one gate whose whole subject is the contract - signature -
        # ran the measurement rules and none of the statutory ones. All six are
        # warnings, so adding them tells a signer what is undeclared without
        # blocking on it.
        "rule_sets": ["boq_quality", "nrm", "uk_statutory"],
    },
    "us_compliance": {
        "id": "us_compliance",
        "name": "United States Compliance",
        "description": "MasterFormat classification checks plus the universal quality baseline.",
        "jurisdiction": "US",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "masterformat"],
    },
    "mx_compliance": {
        "id": "mx_compliance",
        "name": "Mexico Compliance",
        "description": "APU unit-price completeness, IVA and CFDI invoicing, and "
        "subcontract retencion checks for LOPSRM public works plus the "
        "universal quality baseline.",
        "jurisdiction": "MX",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "mexico"],
    },
    # ── Packs added because the rules were already there ───────────────────
    #
    # Each pack below points at a rule set the engine already registered and
    # that nothing could reach. The rules were written, registered, declared by
    # a demo or a country pack, and then never run by the contract gate,
    # because the gate is fed by packs alone and no pack named the country. The
    # user saw a pack id on the settings page either way, so the fallback was
    # invisible: "no jurisdiction claimed this project" rendered exactly like
    # "this project's jurisdiction is enforced".
    #
    # Nothing here is a new rule. A pack whose rule_sets were only the
    # universal baseline under a national name is deliberately NOT written,
    # because it would claim national checks the product does not have, which
    # is worse than the honest fallback. Italy is the country that wanted one
    # and did not get one; see the note under PACK_BY_COUNTRY.
    "hu_compliance": {
        "id": "hu_compliance",
        "name": "Hungary Compliance",
        "description": "Item codes from the Hungarian sectoral item orders, chapter "
        "recognition, the material and fee (anyag / dij) split reconciling to the line "
        "rate, and per-project item-number uniqueness, plus the universal quality baseline.",
        "jurisdiction": "HU",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        # "hungary" is the ENGINE rule-set name. The Hungarian classification
        # standard is spelled "tetelrend" and is a different namespace: it is
        # the key an item code sits under inside a position's classification
        # dict. Writing the classification name here would resolve to nothing,
        # and the engine skips an unknown set without complaining.
        "rule_sets": ["boq_quality", "hungary"],
    },
    "cn_compliance": {
        "id": "cn_compliance",
        "name": "China Compliance",
        "description": "GB/T 50500 bill-of-quantities item codes, present and in the "
        "9- or 12-digit national format, plus the universal quality baseline.",
        "jurisdiction": "CN",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "gbt50500"],
    },
    "es_compliance": {
        "id": "es_compliance",
        "name": "Spain Compliance",
        "description": "FIEBDC-3 (BC3) concept codes on every priced line, in the "
        "hierarchical format the exchange format requires, plus the universal quality "
        "baseline.",
        "jurisdiction": "ES",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "bc3"],
    },
    "ru_compliance": {
        "id": "ru_compliance",
        "name": "Russia Compliance",
        "description": "GESN/FER norm codes, the labour, plant and material breakdown a "
        "cited norm consumes, labour hours, and the price level the estimate is stated "
        "in, plus the universal quality baseline.",
        "jurisdiction": "RU",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "gesn"],
    },
    "br_compliance": {
        "id": "br_compliance",
        "name": "Brazil Compliance",
        "description": "SINAPI composition codes and ABNT NBR 12721 cost-group sections "
        "(S1-S11), plus the universal quality baseline.",
        "jurisdiction": "BR",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        # Two sets, because Brazil measures against two independent references:
        # SINAPI is the price and composition base, NBR 12721 is the ABNT cost
        # -group hierarchy. A bill can satisfy either without the other.
        "rule_sets": ["boq_quality", "sinapi", "nbr"],
    },
    "in_compliance": {
        "id": "in_compliance",
        "name": "India Compliance",
        "description": "CPWD/DSR item references and IS 1200 metric measurement units, "
        "plus the universal quality baseline.",
        "jurisdiction": "IN",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "cpwd"],
    },
    "fr_compliance": {
        "id": "fr_compliance",
        "name": "France Compliance",
        "description": "DPGF lot allocation and pricing completeness across the decomposed "
        "price schedule, plus the universal quality baseline.",
        "jurisdiction": "FR",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "dpgf"],
    },
    "ca_compliance": {
        "id": "ca_compliance",
        "name": "Canada Compliance",
        "description": "MasterFormat classification checks, the standard CSC co-publishes "
        "for Canadian projects, plus the universal quality baseline.",
        "jurisdiction": "CA",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        # Canada shares the American classification set rather than having one
        # of its own, and that is a real answer rather than a stand-in:
        # MasterFormat is co-published by CSI and CSC, both Canadian demos
        # measure to it, and the Canadian country pack ships against it. What
        # this pack does NOT carry is any Canada-specific statutory rule -
        # nothing in the engine reads provincial holdback periods, lien
        # deadlines or a CCDC contract form - so it enforces classification,
        # not Canadian contract law. When those rules are written they belong
        # in a "canada" set added here, not folded into masterformat.
        "rule_sets": ["boq_quality", "masterformat"],
    },
    # ── One country was not missing a pack, it was given a neighbour's ─────
    #
    # Austria is a different defect from the eight above and needs saying
    # plainly, because the fix revises a decision rather than filling a hole.
    # "AT" used to resolve to the DACH pack. That pack is not wrong about
    # Austria: DIN 276 cost groups and the GAEB tender format really are used
    # there, which is why the mapping was written and why nothing looked
    # broken. What it left out was "onorm", the set the engine registers for
    # the Austrian standard, so an Austrian contract was measured entirely
    # against German references and the settings page showed a national pack
    # either way.
    #
    # This is the same shape as the bill that charged Austria Germany's 19
    # percent VAT because the two share the DACH region, and it gets the same
    # answer: a country is entitled to its own. The parallel extends to what
    # is deliberately NOT done. That fix did not split the DACH region, since
    # overheads and profit really are shared; this one does not drop the
    # shared sets, since DIN 276 and GAEB really are read in Vienna. ÖNORM is
    # added alongside them, not in place of them.
    #
    # Both ÖNORM rules are warnings, so this pack tells an Austrian signer
    # what is undeclared without blocking on it, and no contract that could be
    # signed before this pack existed becomes unsignable because of it.
    "at_compliance": {
        "id": "at_compliance",
        "name": "Austria Compliance",
        "description": "ÖNORM B 2063 position structure and description detail, alongside the "
        "DIN 276 cost groups and the GAEB tender format an Austrian bill is also written "
        "against, plus the universal quality baseline.",
        "jurisdiction": "AT",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "din276", "gaeb", "onorm"],
    },
    "jp_compliance": {
        "id": "jp_compliance",
        "name": "Japan Compliance",
        "description": "Sekisan item codes on every priced line and the metric units "
        "Japanese measurement practice is stated in, plus the universal quality baseline.",
        "jurisdiction": "JP",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "sekisan"],
    },
    "tr_compliance": {
        "id": "tr_compliance",
        "name": "Turkey Compliance",
        "description": "Birim fiyat poz numbers on every priced line, in the published "
        "unit-price format, plus the universal quality baseline.",
        "jurisdiction": "TR",
        "enforced_workflows": [WORKFLOW_CONTRACT_SIGNATURE],
        "rule_sets": ["boq_quality", "birimfiyat"],
    },
}

#: Default pack every project falls back to when nothing else matches.
DEFAULT_PACK_ID = "universal"

# --------------------------------------------------------------------------- #
# Pack resolution: three keyspaces that cannot overlap.
#
# A project carries an ISO 3166-1 alpha-2 ``country_code`` (a controlled value)
# and a free-text ``region`` (whatever somebody typed). Resolution reads the
# ISO column first and treats the region label as a fallback only.
#
# This used to be one table of substrings matched against the region alone, and
# two of its entries were two letters long. ``de`` matched the Spanish and
# French preposition, so "Ciudad de Mexico" and "Ile-de-France" both enforced
# the German pack, and ``us`` matched inside "Russia", "Australia", "Belarus"
# and "Cyprus", all of which enforced the American one. The tables below cannot
# repeat that: nothing here is ever matched as a bare substring. ISO codes and
# legacy codes match a whole string, labels match a whole word or phrase, and
# no two-letter token appears in the label table at all - so the order the
# tables are consulted in does not decide any answer.
# --------------------------------------------------------------------------- #

#: ISO 3166-1 alpha-2 country code → pack id. Matched exactly, never as a
#: substring. Seeded from each pack's own ``jurisdiction`` so there is one
#: source of truth for which pack covers which country, then extended with the
#: countries a pack covers beyond the one it is named for.
#:
#: On the ambiguity of ``DE``, which is now halved rather than gone.
#: ``Project.country_code`` was NOT NULL with ``server_default='DE'`` until
#: revision ``v3319``, so it had three states that looked like two: a project
#: created through the API with no country chosen held 'DE' from the default,
#: a project created through the demo path held '' because an empty string
#: does not trigger a server default, and a project whose owner really did
#: choose Germany held 'DE' as well. Explicit Germany was indistinguishable
#: from never-chosen in the row. The note here used to end by saying that
#: fixing it needed a nullable column and was a migration rather than a
#: resolver change; that migration has since been written.
#:
#: What changed is only the future. A project created from ``v3319`` onwards
#: with no country holds NULL, which every reader in this file already treats
#: as unknown, so never-chosen and Germany are finally distinct. What did not
#: change is the past: rows written before that revision still hold 'DE', and
#: no signal in the data separates the deliberate ones from the defaulted
#: ones, so the migration deliberately rewrites nothing. We therefore still
#: resolve 'DE' at face value - demoting it would break every real German
#: project to protect the ones that never chose - and still treat '' as
#: unknown. Note that ``currency`` in the same model deliberately defaults to
#: '' with the comment "No EUR bias"; ``country_code`` got the same treatment
#: only for rows written from here on.
#:
#: What is still NOT here, and why, so the next reader does not have to
#: re-derive it. One situation, where there used to be two, and it is the one
#: the settings page cannot show: the universal pack renders exactly like a
#: national one.
#:
#: * No rule set in the engine is about the country at all, so the universal
#:   pack is the honest answer. Italy is the notable one - it ships a demo and
#:   a case page, and nothing in the engine reads a DEI or computo metrico
#:   code. Also NL, PL, KR, AE, ZA, SA, AU and NZ.
#:
#: The other used to read "a national rule set IS registered and no pack
#: reaches it", and is now empty. Japan ("sekisan"), Turkey ("birimfiyat") and
#: Austria ("onorm") were the three. Austria was the one worth spelling out,
#: because it was not a country falling through to the baseline but a country
#: resolving to the neighbours' pack, which no gate written on "did it reach a
#: pack" can see, and which the settings page renders as national coverage.
#:
#: ``tests/unit/test_every_shipped_country_reaches_a_compliance_pack.py``
#: holds all of this as assertions rather than prose. Its
#: ``NO_NATIONAL_RULES_REGISTERED`` table is the list above and goes red when
#: a country joins it without being named;
#: ``NATIONAL_RULE_SET_BY_COUNTRY`` is the other and goes red when a country
#: whose own rule set is registered resolves to a pack that does not run it.
PACK_BY_COUNTRY: dict[str, str] = {
    **{str(pack["jurisdiction"]): pack_id for pack_id, pack in RULE_PACKS.items() if pack.get("jurisdiction")},
    # Switzerland runs the DACH pack; it is not a German-only pack. Austria
    # used to sit on this line beside it and no longer does: it has "onorm" of
    # its own, so it gets "at_compliance" from the comprehension above, which
    # carries the DACH sets plus the Austrian one. Switzerland stays because
    # no Swiss rule set is registered anywhere, which makes the DACH pack the
    # honest answer for a Swiss project rather than a substituted one. The day
    # a Swiss set is written, this line is the thing to revisit.
    "CH": "de_compliance",
}

#: Short codes that are *not* ISO alpha-2, matched against a whole region
#: string only. "UK" is the everyday abbreviation for a country whose ISO code
#: is "GB", and this product's own region tags have always used it.
PACK_BY_LEGACY_CODE: dict[str, str] = {
    "uk": "uk_compliance",
}

#: Human region labels → pack id, matched as a whole word or a whole phrase
#: against the region text. Every key here is longer than two characters; the
#: test suite gates that, because a two-letter key is what caused the defect
#: this table replaced.
PACK_BY_LABEL: dict[str, str] = {
    # "dach" stays on the German pack. It is the one label here that is not a
    # country, and a project that tags itself with the region as a whole has
    # not said it is Austrian, so it gets the sets the three markets share.
    "dach": "de_compliance",
    "germany": "de_compliance",
    "deutschland": "de_compliance",
    # "austria" moved off the German pack with the ISO code. A project that
    # only ever typed its region was the one most exposed to the substitution,
    # because it never had a country column to be read first.
    "austria": "at_compliance",
    "österreich": "at_compliance",
    "switzerland": "de_compliance",
    "united kingdom": "uk_compliance",
    "great britain": "uk_compliance",
    "britain": "uk_compliance",
    "england": "uk_compliance",
    "scotland": "uk_compliance",
    "wales": "uk_compliance",
    "united states": "us_compliance",
    "united states of america": "us_compliance",
    "america": "us_compliance",
    "usa": "us_compliance",
    "mexico": "mx_compliance",
    "méxico": "mx_compliance",
    "hungary": "hu_compliance",
    "magyarország": "hu_compliance",
    "china": "cn_compliance",
    "spain": "es_compliance",
    "españa": "es_compliance",
    "russia": "ru_compliance",
    "russian federation": "ru_compliance",
    "brazil": "br_compliance",
    "brasil": "br_compliance",
    "india": "in_compliance",
    # "france" matches on token boundaries, so it also claims "Ile-de-France",
    # which is correct and is the same string the old substring table got
    # wrong in the other direction: "de" matched inside it and enforced the
    # German pack. A whole-word "france" reaching the French pack is the right
    # answer arriving by the right mechanism. "Indiana" cannot be claimed by
    # "india" for the same reason - " india " is not inside " indiana ".
    "france": "fr_compliance",
    "canada": "ca_compliance",
    "japan": "jp_compliance",
    "turkey": "tr_compliance",
    "türkiye": "tr_compliance",
}


def _normalise_country_code(country_code: str | None) -> str | None:
    """Normalise an ISO country code, or ``None`` when none was given.

    The empty string is *not* a country: it is how the demo path spells "no
    country was chosen", because an empty string does not trigger the column's
    server default. Anything that is not two letters is rejected rather than
    guessed at.
    """
    if not country_code:
        return None
    code = country_code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        return None
    return code


def _normalise_region(region: str) -> str:
    """Lower-case ``region`` and reduce it to space-separated word tokens.

    Punctuation becomes a separator, so "Ile-de-France" and "Ciudad de Mexico"
    both split into words and neither can be matched by a fragment of one.
    """
    lowered = region.strip().lower()
    return " ".join("".join(c if c.isalnum() else " " for c in lowered).split())


def get_rule_pack(pack_id: str) -> dict[str, Any] | None:
    """Return the rule-pack definition for ``pack_id`` (or ``None``)."""
    return RULE_PACKS.get(pack_id)


def list_rule_packs() -> list[dict[str, Any]]:
    """Return every known rule pack as a list (stable order)."""
    return list(RULE_PACKS.values())


def valid_pack_ids(pack_ids: list[str]) -> list[str]:
    """Filter ``pack_ids`` down to the ones that actually exist.

    Order-preserving and de-duplicating. Used to validate a project's
    requested pack selection before persisting it so a typo never silently
    disables the gate.
    """
    seen: set[str] = set()
    out: list[str] = []
    for pid in pack_ids:
        if pid in RULE_PACKS and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def suggest_pack_for_country(country_code: str | None) -> str | None:
    """Pack for an ISO 3166-1 alpha-2 ``country_code``, or ``None``.

    ``None`` means "this column gave no answer" and covers both a country with
    no pack registered (Italy, the Netherlands, Poland) and no usable country
    at all (the empty string the demo path writes). Callers that need to tell
    those apart should use :func:`resolve_pack`, which does.
    """
    code = _normalise_country_code(country_code)
    if code is None:
        return None
    return PACK_BY_COUNTRY.get(code)


def suggest_pack_for_region(region: str | None) -> str:
    """Suggest a single default pack id for a coarse ``region`` tag.

    A fallback for when no ISO country is on the record - prefer
    :func:`resolve_pack`, which consults the country column first.

    Matched in three passes, none of which is a bare substring test: the whole
    string against the ISO codes, then the whole string against the non-ISO
    legacy codes, then whole words and phrases against the labels. Falls back
    to :data:`DEFAULT_PACK_ID`. Pure and deterministic.
    """
    if not region:
        return DEFAULT_PACK_ID
    normalised = _normalise_region(region)
    if not normalised:
        return DEFAULT_PACK_ID

    # A region tag that is exactly a country code means that country. This is
    # an equality test on the whole string, so it carries none of the substring
    # risk that made "de" match "Ciudad de Mexico".
    exact = suggest_pack_for_country(normalised)
    if exact is not None:
        return exact
    legacy = PACK_BY_LEGACY_CODE.get(normalised)
    if legacy is not None:
        return legacy

    # Whole word or whole phrase. Padding both sides means a label can only
    # match on token boundaries, so "mexico" matches "Ciudad de Mexico" while
    # "usa" cannot match inside "Russia".
    padded = f" {normalised} "
    for label, pack_id in PACK_BY_LABEL.items():
        if f" {_normalise_region(label)} " in padded:
            return pack_id
    return DEFAULT_PACK_ID


def resolve_pack(country_code: str | None, region: str | None) -> str:
    """Resolve one default pack from the ISO country, then the region label.

    The ISO column decides whenever it holds a usable code, including when that
    country has no pack registered: a project that declares itself Italian gets
    the universal pack, not whatever its free-text region happens to spell. The
    region label is consulted only when no country is known at all.

    Used to seed a new project's default selection - never to override an
    explicit choice the caller made.
    """
    code = _normalise_country_code(country_code)
    if code is not None:
        return PACK_BY_COUNTRY.get(code, DEFAULT_PACK_ID)
    return suggest_pack_for_region(region)


def resolve_rule_sets(
    pack_ids: list[str],
    *,
    workflow: str = WORKFLOW_CONTRACT_SIGNATURE,
) -> list[str]:
    """Resolve the union of validation rule-set names for ``pack_ids``.

    Only packs that enforce ``workflow`` contribute their rule sets. Unknown
    pack ids are skipped. The result is order-preserving and de-duplicated so
    the validation engine receives a clean, stable list.
    """
    seen: set[str] = set()
    out: list[str] = []
    for pid in pack_ids:
        pack = RULE_PACKS.get(pid)
        if pack is None:
            continue
        if workflow not in pack.get("enforced_workflows", []):
            continue
        for rs in pack.get("rule_sets", []):
            if rs not in seen:
                seen.add(rs)
                out.append(rs)
    return out
