# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Italian prezzario rules run, are reachable from an Italian project, and say so.

Five of the twelve ``prezzario.*`` ids the Italy pack declares have a body:
the voce code format, the voce presence, the separated safety costs, the
stated labour share and the general expenses and profit not added twice. Before this the whole document was declared-only, so an
Italian bill was validated without a single Italian rule and the coverage
report said 0 of 11.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from string import Formatter
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext, rule_registry
from app.core.validation.messages import is_key_present
from app.core.validation.rules.italy_prezzario import (
    ITALY_PREZZARIO_RULES,
    PrezzarioCostiSicurezzaSeparated,
    PrezzarioIncidenzaManodoperaDocumented,
    PrezzarioOverheadsNotAppliedTwice,
    PrezzarioVoceCodeFormatValid,
    PrezzarioVoceReferencePresent,
    voce_code_is_well_formed,
)
from app.modules.boq.router import _build_rule_sets

REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_PACK = (
    REPO_ROOT
    / "packs"
    / "italy-it"
    / "src"
    / "openconstructionerp_italy_it"
    / "rule_packs"
    / "prezzario_regionale.json"
)
IMPLEMENTED = {
    "prezzario.voce_code_format_valid",
    "prezzario.voce_reference_present",
    "prezzario.costi_sicurezza_separated",
    "prezzario.incidenza_manodopera_documented",
    "prezzario.overheads_not_applied_twice",
}


def _run(
    rule: Any,
    positions: list[dict[str, Any]],
    markups: list[dict[str, Any]] | None = None,
    workflow: str | None = None,
) -> list[Any]:
    data: dict[str, Any] = {"positions": positions}
    if markups is not None:
        data["markups"] = markups
    metadata: dict[str, Any] = {"locale": "en"}
    if workflow:
        metadata["workflow"] = workflow
    return asyncio.run(rule.validate(ValidationContext(data=data, metadata=metadata)))


def _line(pid: str, code: str | None = None, **meta: Any) -> dict[str, Any]:
    pos: dict[str, Any] = {
        "id": pid,
        "ordinal": pid,
        "description": "Scavo a sezione obbligata",
        "unit": "m3",
        "quantity": 10,
        "unit_rate": 12.5,
        "classification": {"voci": code} if code is not None else {},
    }
    if meta:
        pos["metadata"] = meta
    return pos


# ── The code format ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "code",
    [
        "TOS25_01.A03.001.001",
        "VEN26-01.02.04.a",
        "LOM261.1C.00.010.0010",
        "LOM261.RM.87.10.15.D0017.0000.-",
        "BOL24_A.1.2",
        "CAM24_A00.010.100.A",
        "PUG2026/01.E01.001.001",
        "NP.01",
        "NP 12",
        "N.P.3",
    ],
)
def test_a_ministry_coded_voce_or_a_nuovo_prezzo_is_well_formed(code: str) -> None:
    assert voce_code_is_well_formed(code)


@pytest.mark.parametrize(
    "code", ["XYZ25_01.A03", "TOS_01.A03", "TOS2_01", "TOS19999_01", "01.A03.001", "scavo", "TOS25"]
)
def test_a_code_without_region_and_year_is_not(code: str) -> None:
    assert not voce_code_is_well_formed(code)


def test_a_list_numbered_without_a_prefix_passes_when_the_line_says_which_list() -> None:
    assert not voce_code_is_well_formed("A1.01.3.a.1")
    assert voce_code_is_well_formed("A1.01.3.a.1", {"region": "Lazio", "edition": "2023"})
    assert voce_code_is_well_formed("2.1.11.CAM", {"region": "Umbria"})


@pytest.mark.parametrize("code", ["A.01.010.a", "A1.01.3.a.1", "1C.02.050.0020", "A", "voce 12/b"])
def test_a_line_that_names_its_list_is_never_warned_about_its_code(code: str) -> None:
    # Official data must not raise the warning by itself: whatever the list
    # prints is its code once the line says which list it is from.
    line = _line("1", code, prezzario={"region": "Lazio", "edition": "2023"})
    assert _run(PrezzarioVoceCodeFormatValid(), [line])[0].passed


@pytest.mark.parametrize("code", ["A.01.010.a", "1C.02.050.0020", "TOS25", "see specification", "XYZ25_01.A03"])
def test_a_hand_typed_code_naming_no_list_is_warned_about(code: str) -> None:
    results = _run(PrezzarioVoceCodeFormatValid(), [_line("1", code)])
    assert not results[0].passed
    assert code in results[0].message


def test_a_line_imported_from_an_xpwe_file_cites_the_files_own_list() -> None:
    # The file carries its elenco prezzi and the line points at one of its
    # items, so an unprefixed code there was copied, not typed.
    by_item = _line("1", "A.01.010.a", xpwe_ep_id="17")
    by_source = {**_line("2", "A.01.010.a"), "source": "xpwe_import"}
    typed = _line("3", "A.01.010.a")
    results = _run(PrezzarioVoceCodeFormatValid(), [by_item, by_source, typed])
    assert [r.passed for r in results] == [True, True, False]


def test_the_format_rule_fails_a_hand_typed_code_and_names_it() -> None:
    results = _run(
        PrezzarioVoceCodeFormatValid(),
        [_line("1", "TOS25_01.A03.001.001"), _line("2", "scavo generico"), _line("3")],
    )
    assert [r.passed for r in results] == [True, False]  # line 3 has no code: not this rule's finding
    assert "scavo generico" in results[1].message


# ── Presence ────────────────────────────────────────────────────────────────


def test_every_leaf_must_cite_a_voce() -> None:
    results = _run(PrezzarioVoceReferencePresent(), [_line("1", "VEN26-01.02.01.00"), _line("2")])
    assert [r.passed for r in results] == [True, False]
    assert "2" in results[1].message


def test_sections_are_not_asked_for_a_voce() -> None:
    section = {"id": "s", "ordinal": "01", "type": "section", "description": "SCAVI", "classification": {}}
    child = {**_line("1", "VEN26-01.02.01.00"), "parent_id": "s"}
    results = _run(PrezzarioVoceReferencePresent(), [section, child])
    assert len(results) == 1 and results[0].passed


# ── Safety costs ────────────────────────────────────────────────────────────


def test_an_italian_bill_without_a_safety_line_fails_once() -> None:
    results = _run(PrezzarioCostiSicurezzaSeparated(), [_line("1", "TOS25_01.A03.001.001")])
    assert len(results) == 1 and not results[0].passed


def test_the_platform_italian_markup_line_counts_as_the_safety_line() -> None:
    markups = [{"name": "Oneri della sicurezza non soggetti a ribasso", "category": "other", "is_active": True}]
    results = _run(PrezzarioCostiSicurezzaSeparated(), [_line("1", "TOS25_01.A03.001.001")], markups)
    assert results[0].passed


def test_an_inactive_safety_markup_does_not_count() -> None:
    markups = [{"name": "Oneri della sicurezza", "category": "other", "is_active": False}]
    results = _run(PrezzarioCostiSicurezzaSeparated(), [_line("1", "TOS25_01.A03.001.001")], markups)
    assert not results[0].passed


def test_a_line_from_a_safety_chapter_counts_as_the_safety_line() -> None:
    lines = [
        _line("1", "TOS25_01.A03.001.001"),
        _line("2", "TOS25_17.N05.002.018", prezzario={"region": "Toscana", "safety": True}),
    ]
    assert _run(PrezzarioCostiSicurezzaSeparated(), lines)[0].passed


def test_a_bill_with_no_italian_line_is_left_alone() -> None:
    assert _run(PrezzarioCostiSicurezzaSeparated(), [_line("1")]) == []


# ── Labour share ────────────────────────────────────────────────────────────


def test_a_line_from_the_import_states_its_labour_share() -> None:
    lines = [
        _line("1", "TOS25_01.A03.001.001", prezzario={"region": "Toscana", "labour_share_pct": "40.36"}),
        _line("2", "TOS25_01.A03.001.002", prezzario={"region": "Toscana", "labour_share_pct": "0"}),
        _line("3", "TOS25_01.A03.001.003", resources=[{"type": "labor", "total": 3}]),
        _line("4", "TOS25_01.A03.001.004"),
        _line("5"),
    ]
    results = _run(PrezzarioIncidenzaManodoperaDocumented(), lines)
    # A stated zero is a statement; line 5 cites nothing and is not an Italian line.
    assert [r.passed for r in results] == [True, True, True, False]


def test_a_contract_workflow_is_not_asked_for_a_labour_share() -> None:
    # The schedule of values a contract validates carries no cost breakdown,
    # so the same unstated line that fails on the bill is not asked there.
    lines = [_line("1", "TOS25_01.A03.001.004")]
    assert _run(PrezzarioIncidenzaManodoperaDocumented(), lines)[0].passed is False
    assert _run(PrezzarioIncidenzaManodoperaDocumented(), lines, workflow="contract_signature") == []


# ── General expenses and profit ─────────────────────────────────────────


def _priced(pid: str, total: float, from_list: bool) -> dict[str, Any]:
    line = _line(pid, "TOS25_01.A03.001.001", prezzario={"region": "Toscana"}) if from_list else _line(pid, "NP.01")
    return {**line, "total": total}


SG = {
    "name": "Spese generali",
    "category": "overhead",
    "markup_type": "percentage",
    "percentage": 15,
    "apply_to": "direct_cost",
    "sort_order": 1,
    "is_active": True,
}
UTILE = {
    "name": "Utile d'impresa",
    "category": "profit",
    "markup_type": "percentage",
    "percentage": 10,
    "apply_to": "cumulative",
    "sort_order": 2,
    "is_active": True,
}
SAFETY = {
    "name": "Oneri della sicurezza non soggetti a ribasso",
    "category": "overhead",
    "markup_type": "percentage",
    "percentage": 3,
    "apply_to": "direct_cost",
    "sort_order": 3,
    "is_active": True,
}


def test_a_list_priced_bill_with_general_expenses_and_profit_is_warned_with_its_own_figure() -> None:
    lines = [_priced("1", 600, True), _priced("2", 400, True)]
    results = _run(PrezzarioOverheadsNotAppliedTwice(), lines, [SG, UTILE, SAFETY])
    assert len(results) == 1 and not results[0].passed
    # 15 % on the direct cost, then 10 % on cost plus 15 %: 1.15 x 1.10 = 1.265.
    assert results[0].details["added_percent"] == 27
    assert "27%" in results[0].message
    # The safety line is not general expenses, whatever its category says.
    assert results[0].details["markups"] == ["Spese generali", "Utile d'impresa"]


def test_the_figure_follows_the_bills_own_markups() -> None:
    lines = [_priced("1", 1000, True)]
    sg_only = {**SG, "percentage": 13}
    results = _run(PrezzarioOverheadsNotAppliedTwice(), lines, [sg_only])
    assert results[0].details["added_percent"] == 13


def test_an_analysis_priced_bill_keeps_its_general_expenses_and_profit() -> None:
    lines = [_priced("1", 600, False), _priced("2", 400, False), _priced("3", 100, True)]
    assert _run(PrezzarioOverheadsNotAppliedTwice(), lines, [SG, UTILE]) == []


def test_a_bill_citing_its_list_at_direct_cost_keeps_its_markups() -> None:
    # The Italian demo bills cite the list but state their rates net of spese
    # generali and utile, which they carry as markups: nothing is counted twice.
    lines = [_line(pid, "A.01.010.a", prezzario={"region": "Lazio", "rate_includes_overheads": False}) for pid in "12"]
    assert _run(PrezzarioOverheadsNotAppliedTwice(), lines, [SG, UTILE]) == []


def test_a_list_priced_bill_without_those_markups_passes() -> None:
    lines = [_priced("1", 600, True), _priced("2", 400, True)]
    results = _run(PrezzarioOverheadsNotAppliedTwice(), lines, [SAFETY, {**UTILE, "is_active": False}])
    assert results[0].passed


def test_utili_d_impresa_is_profit_by_its_name() -> None:
    # The plural is as common on an Italian bill as the singular.
    utili = {**UTILE, "name": "Utili d'impresa", "category": "overhead"}
    results = _run(PrezzarioOverheadsNotAppliedTwice(), [_priced("1", 1000, True)], [SG, utili])
    assert results[0].details["markups"] == ["Spese generali", "Utili d'impresa"]
    assert results[0].details["added_percent"] == 27


IMPREVISTI = {
    "name": "Imprevisti",
    "category": "contingency",
    "markup_type": "percentage",
    "percentage": 10,
    "apply_to": "direct_cost",
    "sort_order": 0,
    "is_active": True,
}


def test_an_earlier_markup_raises_the_base_the_way_the_bill_computes_it() -> None:
    # 10 % contingency first, then 15 % general expenses on cost plus
    # contingency: the bill adds 16.5 % of the direct cost as general expenses.
    sg_cumulative = {**SG, "apply_to": "cumulative", "sort_order": 1}
    results = _run(PrezzarioOverheadsNotAppliedTwice(), [_priced("1", 1000, True)], [IMPREVISTI, sg_cumulative])
    assert results[0].details["added_percent_exact"] == "16.5"
    assert results[0].details["added_percent"] == 17
    assert results[0].details["markups"] == ["Spese generali"]


def test_the_amounts_the_bill_computed_are_the_ones_reported() -> None:
    # The validate endpoint hands over each line's amount from the BOQ markup
    # engine (escalation, scoping and currency included); the rule reports
    # that figure rather than working one out again.
    computed = {**SG, "markup_type": "escalation", "percentage": None, "amount": "200"}
    results = _run(PrezzarioOverheadsNotAppliedTwice(), [_priced("1", 1000, True)], [computed])
    assert results[0].details["added_percent"] == 20


# ── Lines an XPWE bill brings in ────────────────────────────────────────────


def test_an_xpwe_line_states_its_labour_share_in_its_cost_shares() -> None:
    lines = [
        _line("1", "EX26_01.A03.001.001", xpwe_ep_id="1", cost_shares={"labour": "0.3544"}),
        _line("2", "EX26_01.B02.004.002", xpwe_ep_id="2", cost_shares={"material": "0.52"}),
    ]
    results = _run(PrezzarioIncidenzaManodoperaDocumented(), lines)
    assert [r.passed for r in results] == [True, False]


def test_an_xpwe_safety_item_is_the_safety_line() -> None:
    lines = [
        _line("1", "EX26_01.A03.001.001", xpwe_ep_id="1"),
        _line("2", "EX26_17.S01.001.001", xpwe_ep_id="3", safety_item=True),
    ]
    assert _run(PrezzarioCostiSicurezzaSeparated(), lines)[0].passed


def test_a_line_classified_as_safety_cost_is_the_safety_line() -> None:
    line = _line("1", "TOS25_17.P03.001.001")
    line["classification"]["cost_type"] = "sicurezza"
    line["description"] = "Recinzione di cantiere"
    assert _run(PrezzarioCostiSicurezzaSeparated(), [line])[0].passed


def test_the_xpwe_bill_import_raises_no_finding_its_file_does_not_deserve() -> None:
    from app.modules.boq.importers.xpwe import _parse_sync

    computo = Path(__file__).resolve().parents[1] / "fixtures" / "xpwe" / "computo_small.xpwe"
    imported = _parse_sync(computo.read_bytes())
    positions = [
        {
            "id": str(index),
            "ordinal": pos.ordinal or str(index),
            "description": pos.description,
            "unit": pos.unit,
            "quantity": pos.quantity,
            "unit_rate": pos.unit_rate,
            "total": pos.quantity * pos.unit_rate,
            "classification": pos.classification,
            "source": "xpwe_import",
            "metadata": pos.metadata,
        }
        for index, pos in enumerate(imported.positions, start=1)
    ]
    assert positions
    for rule in (
        PrezzarioVoceCodeFormatValid(),
        PrezzarioIncidenzaManodoperaDocumented(),
        PrezzarioCostiSicurezzaSeparated(),
    ):
        failed = [r.element_ref for r in _run(rule, positions) if not r.passed]
        assert failed == [], f"{rule.rule_id} on {failed}"


# ── Wiring ──────────────────────────────────────────────────────────────────


def test_the_rule_ids_are_the_ones_the_pack_declares() -> None:
    declared = set(json.loads(RULE_PACK.read_text(encoding="utf-8"))["enables_rule_ids"])
    ids = {rule.rule_id for rule in ITALY_PREZZARIO_RULES}
    assert ids == IMPLEMENTED
    assert ids <= declared


def test_the_rules_are_registered_into_the_italy_set() -> None:
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    members = {entry["rule_id"] for entry in rule_registry.list_rules(rule_set="italy")}
    assert members == IMPLEMENTED


def test_the_pack_coverage_reports_five_implemented_and_seven_declared_only() -> None:
    from app.core.validation import pack_coverage
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    pack_coverage.reset_cache()
    coverage = next(p for p in pack_coverage.get_pack_coverage().packs if p.pack_id == "prezzario_regionale")
    assert set(coverage.implemented) == IMPLEMENTED
    assert coverage.declared_only_count == 7


@pytest.mark.parametrize(
    ("standard", "region", "country"),
    [("", "IT", None), ("", "IT_ROME", None), ("", "", "IT"), ("voci", "", None)],
)
def test_an_italian_project_gets_the_italian_rule_set(standard: str, region: str, country: str | None) -> None:
    assert "italy" in _build_rule_sets(["boq_quality"], standard, region, country_code=country)


def test_an_italian_project_naming_another_standard_drops_the_voce_rules() -> None:
    assert "italy" not in _build_rule_sets(["boq_quality"], "din276", "IT")


@pytest.mark.parametrize("locale", ["en", "de", "es", "ru", "it"])
@pytest.mark.parametrize(
    "key",
    [
        "prezzario.voce_code_format_valid.fail",
        "prezzario.voce_code_format_valid.suggestion",
        "prezzario.voce_reference_present.fail",
        "prezzario.voce_reference_present.suggestion",
        "prezzario.costi_sicurezza_separated.fail",
        "prezzario.costi_sicurezza_separated.suggestion",
        "prezzario.incidenza_manodopera_documented.fail",
        "prezzario.incidenza_manodopera_documented.suggestion",
        "prezzario.overheads_not_applied_twice.fail",
        "prezzario.overheads_not_applied_twice.suggestion",
    ],
)
def test_every_message_is_localised(key: str, locale: str) -> None:
    assert is_key_present(key, locale=locale)


def test_italian_prezzario_messages_preserve_every_interpolation_field() -> None:
    messages = Path(__file__).resolve().parents[2] / "app/core/validation/messages"
    english = json.loads((messages / "en.json").read_text(encoding="utf-8"))["prezzario"]
    italian = json.loads((messages / "it.json").read_text(encoding="utf-8"))["prezzario"]
    formatter = Formatter()
    for rule, variants in english.items():
        for variant, template in variants.items():
            expected = {field for _, field, _, _ in formatter.parse(template) if field is not None}
            actual = {field for _, field, _, _ in formatter.parse(italian[rule][variant]) if field is not None}
            assert actual == expected, f"prezzario.{rule}.{variant}"
