# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The progress billing figures in the national packs say where they came from.

``us_pack`` and ``dach_pack`` carry a ``progress_billing`` block: retention
tiers and caps, the events that release retention and the documents each one
needs, the evidence stored materials need before they are billable, the
certificates a subcontractor must hold before it is paid, the billing cycle,
and the code a change-order line gets. A contract is seeded from these, so a
wrong figure is billed.

The rule held here is the one ``test_us_state_packs`` holds for the state
packs, applied to this block: the dict holding a number carries a non-empty
``statute_reference`` or ``source`` plus an ``effective_date`` key (``None``
is an answer, a missing key is not); only a list element such as a retention
tier may lean on the dict that lists it. No test can know the number is
right; these make sure it says who said so.

The second half is the joins. The block names payment clock regimes, a tax
withholding scheme, a contract security type, subcontractor certificate and
waiver types, and document roles. Each name is checked against the vocabulary
that will read it, because a name nothing recognises is inert data that no
page would show as broken.

Pure dict work plus schema imports; nothing here queries a database.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.regional_packs import PROGRESS_BILLING_KEYS
from app.modules.contracts.schemas import SECURITY_TYPES
from app.modules.dach_pack.config import PACK_CONFIG as DACH_CFG
from app.modules.payment_clock.data import REGIME_CODES
from app.modules.subcontractors.schemas import _VALID_WAIVER_TYPES, CertificateCreate
from app.modules.tax_withholding.data import WITHHOLDING_REGIMES
from app.modules.us_pack.config import PACK_CONFIG as US_CFG

_PACKS: list[tuple[str, dict[str, Any]]] = [("us_pack", US_CFG), ("dach_pack", DACH_CFG)]

# Every (pack, country, block) the sweep covers, so a failure names the block.
_BLOCKS: list[tuple[str, str, dict[str, Any]]] = [
    (pack, country, block) for pack, cfg in _PACKS for country, block in cfg["progress_billing"].items()
]

# An ISO date, an ISO year-month, or a bare year, as in the state packs.
_EFFECTIVE_DATE_RX = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_NUMBER_RX = re.compile(r"^-?\d+(\.\d+)?$")

# ``source`` says what kind of authority a figure rests on when no clause
# states it. A closed list, so a typo or a vague word cannot pass as a source.
_KNOWN_SOURCES = frozenset({"industry_practice", "state_law", "contractual", "platform_convention"})

# The release events the retention engine understands (plan part 5), plus the
# two a pack adds: a US step-down in recompute mode and the German exchange of
# the retention for a bond.
_KNOWN_EVENTS = frozenset(
    {"substantial_completion", "final_completion", "defects_period_end", "rate_step_down", "security_substituted"}
)

# The neutral document roles the contracts module adds for retention releases
# (plan part 5). Form numbers never become role names.
_RELEASE_DOC_ROLES = frozenset(
    {
        "certificate_substantial_completion",
        "affidavit_payment_of_debts",
        "affidavit_release_of_liens",
        "consent_of_surety",
        "acceptance_protocol",
        "final_invoice",
        "final_lien_waiver",
    }
)

# Evidence a stored material can carry (plan part 6 model fields).
_STORED_MATERIAL_EVIDENCE = frozenset(
    {
        "delivery_ticket",
        "invoice",
        "bill_of_sale",
        "insurance",
        "photo",
        "title_transferred",
        "security",
        "owner_approved_offsite",
    }
)
_LOCATION_KINDS = frozenset({"on_site", "off_site", "bonded_warehouse", "supplier_premises"})

# Certificate types the subcontractors lane adds to the cert_type vocabulary
# for Germany. Until that lands they are accepted from this list; every other
# cert_type must pass the live schema.
_CERT_TYPES_PENDING_IN_SUBCONTRACTORS = frozenset(
    {"construction_tax_exemption", "social_security_clearance", "employers_liability_clearance"}
)


def _block_id(item: tuple[str, str, dict[str, Any]]) -> str:
    return f"{item[0]}.{item[1]}"


def _is_sourced(node: Any) -> bool:
    if not isinstance(node, dict) or "effective_date" not in node:
        return False
    return any(isinstance(node.get(key), str) and node[key].strip() for key in ("statute_reference", "source"))


def _walk(node: Any, path: str, list_owner_sourced: bool) -> list[tuple[str, str, Any, bool]]:
    """Return (path, key, leaf, covered) for every leaf.

    A leaf is covered when the dict holding it cites a source. A dict that is
    an element of a list (a retention tier) may lean on the dict that owns the
    list; a nested dict may not lean on its parent, because a figure with a
    citation of its own (the escrow deadline, the open-items multiplier) must
    not hide under a clause that never stated it.
    """
    leaves: list[tuple[str, str, Any, bool]] = []
    if isinstance(node, dict):
        covered = _is_sourced(node) or list_owner_sourced
        for key, value in node.items():
            if isinstance(value, dict):
                leaves.extend(_walk(value, f"{path}.{key}", False))
            elif isinstance(value, list):
                leaves.extend(_walk(value, f"{path}.{key}", covered))
            else:
                leaves.append((path, str(key), value, covered))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, dict | list):
                leaves.extend(_walk(value, f"{path}[{index}]", list_owner_sourced))
            else:
                leaves.append((path, str(index), value, list_owner_sourced))
    return leaves


def _dicts_with_paths(node: Any, path: str) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        found.append((path, node))
        for key, value in node.items():
            found.extend(_dicts_with_paths(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_dicts_with_paths(value, f"{path}[{index}]"))
    return found


# ── The sweep has to reach something ───────────────────────────────────────────


def test_both_national_packs_carry_a_block() -> None:
    """A sweep that reached no block is not a clean sweep."""
    assert {(pack, country) for pack, country, _ in _BLOCKS} == {("us_pack", "US"), ("dach_pack", "DE")}


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_block_carries_every_sub_key(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    missing = [key for key in PROGRESS_BILLING_KEYS if not isinstance(block.get(key), dict)]
    assert not missing, f"{pack} {country} progress_billing lacks {missing}"


@pytest.mark.parametrize(("pack", "cfg"), _PACKS, ids=[name for name, _ in _PACKS])
def test_blocks_are_keyed_by_a_country_the_pack_claims(pack: str, cfg: dict[str, Any]) -> None:
    """A per-country key is what stops one country's figures answering for another."""
    claimed = set(cfg["countries"])
    for key in cfg["progress_billing"]:
        assert re.fullmatch(r"[A-Z]{2}", key), f"{pack} progress_billing key {key!r} is not an ISO-2 code"
        assert key in claimed, f"{pack} writes progress_billing for {key}, which it does not claim"


def test_dach_writes_germany_only() -> None:
    """Austria and Switzerland stay unanswered until someone sources them."""
    assert {"AT", "CH"} <= set(DACH_CFG["countries"]), "precondition: the pack still claims AT and CH"
    assert set(DACH_CFG["progress_billing"]) == {"DE"}


# ── Sourcing ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_every_number_says_where_it_came_from(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    numbers = [
        (path, key, leaf)
        for path, key, leaf, _covered in _walk(block, country, False)
        if isinstance(leaf, str) and _NUMBER_RX.match(leaf) and not key.endswith("effective_date")
    ]
    assert numbers, f"{pack} {country}: the sweep found no figure at all"
    unsourced = [
        f"{path}.{key}={leaf!r}"
        for path, key, leaf, covered in _walk(block, country, False)
        if not covered and isinstance(leaf, str) and _NUMBER_RX.match(leaf) and not key.endswith("effective_date")
    ]
    assert not unsourced, (
        f"{pack} {country}: figures without statute_reference/source and effective_date above them: {unsourced}"
    )


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_every_rule_entry_cites_even_without_a_number(item: tuple[str, str, dict[str, Any]]) -> None:
    """Events, requirements and location rules state law or practice even when they carry no figure."""
    pack, country, block = item
    entries = [
        *block["release_events"]["events"],
        *block["sub_payment_requirements"]["requirements"],
        *block["stored_materials"]["requirements_by_location_kind"].values(),
    ]
    for name in PROGRESS_BILLING_KEYS:
        if name != "release_events":
            entries.append(block[name])
    uncited = [entry.get("event") or entry.get("code") or sorted(entry) for entry in entries if not _is_sourced(entry)]
    assert not uncited, f"{pack} {country}: entries without a citation and effective_date: {uncited}"


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_effective_dates_and_sources_are_well_formed(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    for _path, node in _dicts_with_paths(block, country):
        if "effective_date" in node:
            value = node["effective_date"]
            assert value is None or (isinstance(value, str) and _EFFECTIVE_DATE_RX.match(value)), (
                f"{pack} {country}: effective_date {value!r} is not an ISO date, year-month or year"
            )
        if "source" in node:
            assert node["source"] in _KNOWN_SOURCES, f"{pack} {country}: unknown source {node['source']!r}"


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_figures_are_strings_never_floats(item: tuple[str, str, dict[str, Any]]) -> None:
    """Rates and money are Decimal-as-string in this tree; a bool is a flag, not a figure."""
    pack, country, block = item
    bad = [
        f"{path}.{key}={leaf!r}"
        for path, key, leaf, _covered in _walk(block, country, False)
        if isinstance(leaf, int | float) and not isinstance(leaf, bool)
    ]
    assert not bad, f"{pack} {country}: numeric literals must be strings: {bad}"


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_no_form_numbers_in_the_data(item: tuple[str, str, dict[str, Any]]) -> None:
    """Payment and close-out form numbers are trademarks and stay out of the API."""
    pack, country, block = item
    hits = [
        f"{path}.{key}"
        for path, key, leaf, _covered in _walk(block, country, False)
        if isinstance(leaf, str) and re.search(r"\bG\s?70\d", leaf)
    ]
    assert not hits, f"{pack} {country}: form number in {hits}"


# ── Shape the consumers read ───────────────────────────────────────────────────


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_retention_tiers_are_ordered_percentages(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    policy = block["retention_policy"]
    assert policy["tier_mode"] in {"prospective", "recompute"}
    thresholds = [float(tier["from_percent_complete"]) for tier in policy["tiers"]]
    assert thresholds and thresholds[0] == 0, f"{pack} {country}: the first tier must start at 0 percent complete"
    assert thresholds == sorted(set(thresholds)), f"{pack} {country}: tier thresholds must strictly increase"
    for tier in policy["tiers"]:
        assert 0 < float(tier["rate"]) <= 100
    for event in block["release_events"]["events"]:
        released = event["release_percent_of_held"]
        assert released is None or 0 <= float(released) <= 100


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_optional_policy_figures_are_spelled_one_way(item: tuple[str, str, dict[str, Any]]) -> None:
    """``None`` means "tier rate" / "no cap suggested" in every pack, so a rate is a rate or absent."""
    pack, country, block = item
    policy = block["retention_policy"]
    rate = policy["stored_materials_rate"]
    assert rate is None or (isinstance(rate, str) and _NUMBER_RX.match(rate)), f"{pack} {country}: {rate!r}"
    cap = policy["cap"]
    assert cap is None or (_is_sourced(cap) and _NUMBER_RX.match(cap["percent_of_contract_sum"])), (
        f"{pack} {country}: a cap must be a sourced percentage of the contract sum or None"
    )


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_procurement_rule_figures_are_scoped_to_public_clients(item: tuple[str, str, dict[str, Any]]) -> None:
    """VOB/A binds public awarding authorities; its ceilings must not sit where every contract reads them."""
    pack, country, block = item
    unscoped = [
        path
        for path, node in _dicts_with_paths(block, country)
        if "VOB/A" in str(node.get("statute_reference") or "")
        and not path.rsplit(".", 1)[-1].startswith("public_client")
    ]
    assert not unscoped, f"{pack} {country}: public-procurement figures outside a public_client_ key: {unscoped}"


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_billing_cycle_is_what_the_period_resolver_reads(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    cycle = block["billing_cycle"]
    assert cycle["frequency"] == "monthly"
    assert re.fullmatch(r"month_end|day:([1-9]|[12]\d|3[01])", cycle["period_end"]), cycle["period_end"]


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_change_line_format_uses_only_its_placeholders(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    fmt = block["change_line_code_format"]
    used = set(re.findall(r"\{(\w+)\}", fmt["format"]))
    assert used and used <= set(fmt["placeholders"]), f"{pack} {country}: {fmt['format']!r} vs {fmt['placeholders']}"
    assert fmt["format"].format(source_code="CO-005")


# ── Joins to the vocabularies that read the names ──────────────────────────────


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_release_events_and_documents_are_known(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    for event in block["release_events"]["events"]:
        assert event["event"] in _KNOWN_EVENTS, f"{pack} {country}: unknown release event {event['event']!r}"
        for key in ("required_documents", "required_documents_when_bonded", "documents_owner_may_require"):
            unknown = set(event.get(key) or ()) - _RELEASE_DOC_ROLES
            assert not unknown, f"{pack} {country} {event['event']}.{key}: unknown document roles {unknown}"
        security = event.get("requires_security_type")
        if security is not None:
            assert security in SECURITY_TYPES.split("|"), f"{security!r} is not a contract security type"


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_stored_material_evidence_names_match_the_model(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    by_kind = block["stored_materials"]["requirements_by_location_kind"]
    assert set(by_kind) == _LOCATION_KINDS, f"{pack} {country}: location kinds {sorted(by_kind)}"
    for kind, rule in by_kind.items():
        assert rule["any_of"], f"{pack} {country} {kind}: an empty any_of would make everything billable"
        for alternative in rule["any_of"]:
            assert alternative, f"{pack} {country} {kind}: an empty alternative passes every material"
            unknown = set(alternative) - _STORED_MATERIAL_EVIDENCE
            assert not unknown, f"{pack} {country} {kind}: unknown evidence {unknown}"


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_subcontractor_evidence_names_are_accepted(item: tuple[str, str, dict[str, Any]]) -> None:
    pack, country, block = item
    for requirement in block["sub_payment_requirements"]["requirements"]:
        if requirement["evidence"] == "certificate":
            # A tax exemption must hold on the day of payment, a clearance through the period.
            assert requirement["valid_at"] in {"period_end", "payment_date"}, requirement["code"]
            cert_type = requirement["cert_type"]
            if cert_type in _CERT_TYPES_PENDING_IN_SUBCONTRACTORS:
                continue
            try:
                CertificateCreate(subcontractor_id=uuid.uuid4(), cert_type=cert_type)
            except ValidationError as exc:
                pytest.fail(f"{pack} {country}: cert_type {cert_type!r} is rejected by the schema: {exc}")
        elif requirement["evidence"] == "lien_waiver":
            named = set()
            for value in requirement["waiver_types"].values():
                named.update(value if isinstance(value, list) else [value])
            assert named <= _VALID_WAIVER_TYPES, f"{pack} {country}: unknown waiver types {named - _VALID_WAIVER_TYPES}"
        else:
            pytest.fail(f"{pack} {country}: unknown evidence kind {requirement['evidence']!r}")


@pytest.mark.parametrize("item", _BLOCKS, ids=_block_id)
def test_the_summary_the_rollup_reads_matches_the_detail(item: tuple[str, str, dict[str, Any]]) -> None:
    """``subcontractors.rollup.requirements_from_pack`` reads the summary; the detail must say the same."""
    pack, country, block = item
    subs = block["sub_payment_requirements"]
    detailed = [r["cert_type"] for r in subs["requirements"] if r["evidence"] == "certificate"]
    assert subs["certificate_types"] == detailed, f"{pack} {country}: summary {subs['certificate_types']} vs {detailed}"
    waivers = any(r["evidence"] == "lien_waiver" for r in subs["requirements"])
    assert subs["lien_waiver_required"] is waivers, f"{pack} {country}: lien_waiver_required disagrees with the detail"


def test_named_payment_clock_regimes_exist() -> None:
    named = [
        (pack, country, code)
        for pack, country, block in _BLOCKS
        for code in block["billing_cycle"]["payment_clock_regimes"].values()
    ]
    assert named, "no regime named at all; the join would be vacuous"
    missing = [item for item in named if item[2] not in REGIME_CODES]
    assert not missing, f"payment clock regimes named but not shipped: {missing}"


def test_named_withholding_scheme_exists() -> None:
    schemes = {regime["scheme_code"] for regime in WITHHOLDING_REGIMES}
    named = [
        requirement["withholding_scheme"]
        for _pack, _country, block in _BLOCKS
        for requirement in block["sub_payment_requirements"]["requirements"]
        if "withholding_scheme" in requirement
    ]
    assert named == ["DE_BAUABZUGSTEUER"]
    assert set(named) <= schemes
