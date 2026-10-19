# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""VAT regimes per contract, and Egypt's three construction regimes.

The distinguishing dates: 2025-07-17 and 2025-07-18 for the document, a
contract signed on either side of 2025-07-18, and evidence issued on either
side of it. Each eligibility case changes one fact of a contract that
otherwise qualifies, so a check that ignores that fact fails here.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.vat_regimes import (
    FINDING_KEYS,
    ContractFacts,
    Evidence,
    countries_with_regimes,
    data_eg,
    effective_rate_pct,
    eligibility_findings,
    in_force,
    lookup,
    regimes_for,
    validate_regimes,
    window_findings,
)
from app.modules.i18n_foundation.seed import load_tax_seed_rows

D = Decimal
REGIMES = data_eg.REGIMES
TRANSITIONAL = lookup(REGIMES, country="EG", code="EG_CONSTR_TRANSITIONAL_36")
STANDARD = lookup(REGIMES, country="EG", code="EG_CONSTR_STANDARD")
SCHEDULE = lookup(REGIMES, country="EG", code="EG_CONSTR_SCHEDULE_5")


def _qualifying(**changes: object) -> ContractFacts:
    """A contract signed before the cutoff, billed before it, holding both pieces of evidence."""
    base = ContractFacts(
        signed_on=date(2024, 11, 1),
        started_on=date(2024, 12, 1),
        is_subcontract=False,
        evidence={
            "approved_certificate": Evidence("IPC-07", date(2025, 6, 30)),
            "einvoice": Evidence("ETA-UUID-123", date(2025, 7, 2)),
        },
        original_value=D("10000000"),
        current_value=D("10000000"),
        allowed_increase_pct=D("25"),
    )
    return replace(base, **changes)


def _keys(facts: ContractFacts) -> list[str]:
    assert TRANSITIONAL is not None
    return [finding.key for finding in eligibility_findings(TRANSITIONAL, facts)]


# ── The table ────────────────────────────────────────────────────────────────


def test_the_egyptian_table_is_sound() -> None:
    assert validate_regimes(REGIMES) == []
    assert regimes_for("EG") is REGIMES
    assert "EG" in countries_with_regimes()
    assert regimes_for("TR") == ()


def test_every_regime_names_a_seed_line_that_ships() -> None:
    shipped = {(row["country_code"], row["tax_code"]) for row in load_tax_seed_rows()}
    for regime in REGIMES:
        assert (regime.country_code, regime.tax_code) in shipped, regime.code


@pytest.mark.parametrize(
    ("on", "offered"),
    [
        (date(2025, 7, 17), ["EG_CONSTR_SCHEDULE_5"]),
        (date(2025, 7, 18), ["EG_CONSTR_STANDARD", "EG_CONSTR_TRANSITIONAL_36"]),
        (date(2026, 10, 19), ["EG_CONSTR_STANDARD", "EG_CONSTR_TRANSITIONAL_36"]),
    ],
)
def test_the_regimes_offered_on_each_side_of_the_cutoff(on: date, offered: list[str]) -> None:
    found = in_force(REGIMES, country="EG", activity=data_eg.CONSTRUCTION, on=on)
    assert [regime.code for regime in found] == offered
    # The default comes first, so a contract that chooses nothing gets it.
    assert found[0].is_default


def test_the_transitional_regime_is_five_point_zero_four_percent_without_input_credit() -> None:
    assert TRANSITIONAL is not None and STANDARD is not None and SCHEDULE is not None
    assert effective_rate_pct(TRANSITIONAL, D("14")) == D("5.04")
    assert TRANSITIONAL.input_credit is False
    assert effective_rate_pct(STANDARD, D("14")) == D("14")
    assert STANDARD.input_credit is True
    assert SCHEDULE.input_credit is False


def test_the_schedule_tax_is_marked_for_expert_review() -> None:
    assert SCHEDULE is not None
    assert SCHEDULE.review_status == "needs_expert_review"


def test_the_scope_of_construction_services_ships_as_data_in_both_languages() -> None:
    items = data_eg.CONSTRUCTION_SERVICES_SCOPE["items"]
    assert isinstance(items, dict)
    assert len(items["en"]) == len(items["ar"]) == 17
    assert "Decree No. 417 of 2025" in str(data_eg.CONSTRUCTION_SERVICES_SCOPE["legal_reference"])


# ── Who may choose the transitional regime ───────────────────────────────────


def test_a_qualifying_contract_has_no_findings() -> None:
    assert _keys(_qualifying()) == []


def test_a_contract_signed_on_the_cutoff_does_not_qualify() -> None:
    assert _keys(_qualifying(signed_on=date(2025, 7, 18))) == ["contract_too_late"]


def test_a_contract_signed_the_day_before_qualifies() -> None:
    assert _keys(_qualifying(signed_on=date(2025, 7, 17))) == []


def test_the_start_date_stands_in_for_a_missing_signature_date() -> None:
    assert _keys(_qualifying(signed_on=None, started_on=date(2025, 1, 1))) == []
    assert _keys(_qualifying(signed_on=None, started_on=date(2025, 8, 1))) == ["contract_too_late"]


def test_a_contract_with_no_date_at_all_is_a_finding_not_a_pass() -> None:
    assert _keys(_qualifying(signed_on=None, started_on=None)) == ["contract_date_missing"]


def test_missing_evidence_is_named_by_kind() -> None:
    facts = _qualifying(evidence={"approved_certificate": Evidence("IPC-07", date(2025, 6, 30))})
    findings = eligibility_findings(TRANSITIONAL, facts)  # type: ignore[arg-type]
    assert [(f.key, f.params["evidence"]) for f in findings] == [("evidence_missing", "einvoice")]


def test_a_blank_reference_is_missing_evidence() -> None:
    facts = _qualifying(
        evidence={
            "approved_certificate": Evidence("  ", date(2025, 6, 30)),
            "einvoice": Evidence("ETA-UUID-123", date(2025, 7, 2)),
        }
    )
    assert _keys(facts) == ["evidence_missing"]


def test_evidence_issued_on_the_cutoff_does_not_qualify() -> None:
    facts = _qualifying(
        evidence={
            "approved_certificate": Evidence("IPC-07", date(2025, 6, 30)),
            "einvoice": Evidence("ETA-UUID-123", date(2025, 7, 18)),
        }
    )
    assert _keys(facts) == ["evidence_too_late"]


def test_undated_evidence_is_a_finding() -> None:
    facts = _qualifying(
        evidence={
            "approved_certificate": Evidence("IPC-07", None),
            "einvoice": Evidence("ETA-UUID-123", date(2025, 7, 2)),
        }
    )
    assert _keys(facts) == ["evidence_date_missing"]


def test_a_subcontract_also_needs_the_main_contractor_certificate() -> None:
    assert _keys(_qualifying(is_subcontract=True)) == ["evidence_missing"]
    with_certificate = dict(_qualifying().evidence)
    with_certificate["main_contractor_certificate"] = Evidence("MC-2025-14", date(2025, 7, 10))
    assert _keys(_qualifying(is_subcontract=True, evidence=with_certificate)) == []


def test_a_scope_increase_within_the_contracts_own_limit_keeps_the_regime() -> None:
    assert _keys(_qualifying(current_value=D("12500000"))) == []


def test_a_scope_increase_beyond_it_is_a_new_contract() -> None:
    assert _keys(_qualifying(current_value=D("12500001"))) == ["scope_increase_new_contract"]


def test_an_increase_the_contract_sets_no_limit_for_cannot_be_judged() -> None:
    assert _keys(_qualifying(current_value=D("10000001"), allowed_increase_pct=None)) == ["scope_increase_unjudged"]


def test_the_standard_regime_has_no_conditions() -> None:
    assert STANDARD is not None
    assert eligibility_findings(STANDARD, _qualifying(signed_on=date(2026, 1, 1), evidence={})) == []


# ── A document dated outside its regime ──────────────────────────────────────


def test_the_schedule_tax_cannot_tax_a_certificate_dated_on_the_cutoff() -> None:
    assert SCHEDULE is not None
    findings = window_findings(SCHEDULE, REGIMES, date(2025, 7, 18))
    assert [f.key for f in findings] == ["not_in_force"]
    assert findings[0].params["instead"] == "EG_CONSTR_STANDARD, EG_CONSTR_TRANSITIONAL_36"
    assert window_findings(SCHEDULE, REGIMES, date(2025, 7, 17)) == []


def test_the_transitional_regime_cannot_tax_a_certificate_before_it_existed() -> None:
    assert TRANSITIONAL is not None
    assert [f.key for f in window_findings(TRANSITIONAL, REGIMES, date(2025, 7, 17))] == ["not_in_force"]


def test_every_emitted_key_is_in_the_vocabulary() -> None:
    assert TRANSITIONAL is not None and SCHEDULE is not None
    seen = {f.key for f in eligibility_findings(TRANSITIONAL, _qualifying(signed_on=None, started_on=None))}
    seen |= {f.key for f in window_findings(SCHEDULE, REGIMES, date(2026, 1, 1))}
    assert seen <= set(FINDING_KEYS)


# ── The table is checked like the payment tax rows ───────────────────────────


def test_a_base_fraction_above_one_is_refused() -> None:
    assert TRANSITIONAL is not None
    assert any("base_fraction" in p for p in validate_regimes((replace(TRANSITIONAL, base_fraction=D("1.2")),)))


def test_two_overlapping_defaults_are_refused() -> None:
    assert TRANSITIONAL is not None
    problems = validate_regimes((*REGIMES, replace(TRANSITIONAL, code="X", is_default=True)))
    assert any("two default regimes overlap" in p for p in problems)


def test_an_unknown_evidence_kind_is_refused() -> None:
    assert TRANSITIONAL is not None and TRANSITIONAL.eligibility is not None
    bad = replace(TRANSITIONAL, eligibility=replace(TRANSITIONAL.eligibility, required_evidence=("selfie",)))
    assert any("unknown evidence kinds" in p for p in validate_regimes((bad,)))


def test_importing_the_package_pulls_in_no_module_layer_and_no_database() -> None:
    backend = Path(__file__).resolve().parents[2]
    probe = (
        "import sys\n"
        "import app.core.vat_regimes.data_eg\n"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('sqlalchemy', 'pydantic', 'fastapi')"
        " or m.startswith('app.modules'))\n"
        "print(','.join(bad))\n"
    )
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], cwd=backend, capture_output=True, text=True, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == ""
