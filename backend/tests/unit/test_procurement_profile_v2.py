# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement profile schema v2: the CI gate on shipped data, chain merge, effective dates, the advisory gate, the v1 migrator."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.modules.procurement_concept import evaluator as ev
from app.modules.procurement_concept import profile as pr
from app.modules.procurement_concept.catalogue import CATALOGUE_DIR, ProcurementCatalogue
from app.modules.procurement_concept.profile_codes import country_of, is_known_jurisdiction

SRC = "https://example.org/law"


def _pv(value, start="2024-01-01", end=None, **kw) -> dict:
    return {"value": value, "source_url": SRC, "effective_from": start, "effective_to": end, **kw}


def _prof(code: str, parent: str | None = None, *, thresholds=(), standstill=(), authority=("central",)):
    return pr.ProcurementProfile.model_validate(
        {
            "header": {"jurisdiction": code, "parent": parent, "authority_types": list(authority)},
            "thresholds": [
                {
                    "contract_type": "works",
                    "authority_type": "central",
                    "effect": "above_requires_publication",
                    "amount": a,
                }
                for a in thresholds
            ],
            "notification": {"standstill": [{"channel": ch, "days": d} for ch, d in standstill]},
        }
    )


WORKS = "thresholds/works/central/above_requires_publication"


# ── CI gate over the shipped data ───────────────────────────────────────


def test_shipped_profiles_pass_the_gate_and_stay_unconfirmed() -> None:
    profiles = pr.load_shipped()
    assert {"EU", "DE", "GB", "US"} <= set(profiles)
    assert pr.validate_profiles(profiles) == []
    for prof in profiles.values():
        for e in pr.entries(prof):
            assert e.value.source_url, e.path
            assert e.value.effective_from is not None, e.path
            assert e.value.review_status.value == "unconfirmed", e.path
            assert e.value.confirmed_by is None


def test_shipped_profiles_carry_every_sourced_v1_value() -> None:
    shipped = pr.load_shipped()
    parents: dict[str, pr.ProcurementProfile] = {}
    for name in ("eu", "de_national", "uk", "us_federal"):
        cat = ProcurementCatalogue.model_validate(json.loads((CATALOGUE_DIR / f"{name}.json").read_text("utf-8")))
        made = pr.migrate_v1(cat, parents=parents).profiles
        parents.update(made)
        for code, prof in made.items():
            have = {(e.path, e.value.value_hash()) for e in pr.entries(shipped[code])}
            for e in pr.entries(prof):
                assert (e.path, e.value.value_hash()) in have, (code, e.path)


def test_gate_fails_on_missing_source_or_effective_from() -> None:
    p = _prof("FR", thresholds=[{"value": "100", "effective_from": "2024-01-01"}, _pv("200", start=None)])
    errors = pr.validate_profiles({"FR": p})
    assert f"value_without_source: FR/{WORKS}" in errors
    assert f"value_without_effective_from: FR/{WORKS}" in errors


def test_gate_fails_on_unknown_jurisdiction_and_parent_cycle() -> None:
    assert "unknown_jurisdiction: XX" in pr.validate_profiles({"XX": _prof("XX")})
    cyc = {"DE": _prof("DE", "AT"), "AT": _prof("AT", "DE")}
    assert any(e.startswith("parent_cycle") for e in pr.validate_profiles(cyc))
    with pytest.raises(pr.ProfileChainError, match="parent_cycle"):
        pr.chain_of("DE", cyc)
    assert "unknown_parent: DE/EU" in pr.validate_profiles({"DE": _prof("DE", "EU")})


def test_gate_fails_on_overlapping_windows() -> None:
    p = _prof("FR", thresholds=[_pv("100", "2024-01-01", "2025-12-31"), _pv("120", "2025-06-01")])
    assert f"value_window_overlap: FR/{WORKS}" in pr.validate_profiles({"FR": p})


def test_jurisdiction_codes() -> None:
    assert all(is_known_jurisdiction(c) for c in ("EU", "DE", "DE-BY", "US-CA", "GB"))
    assert not any(is_known_jurisdiction(c) for c in ("XX", "de", "DE-", "QQ-AB", "EUR"))
    assert country_of("DE-BY") == "DE"


# ── chain merge and effective dates ─────────────────────────────────────


def test_child_overrides_parent_and_inherits_the_rest() -> None:
    profiles = {
        "EU": _prof("EU", thresholds=[_pv("5000000")], standstill=[("electronic", _pv(10))]),
        "DE": _prof("DE", "EU", standstill=[("electronic", _pv(14))]),
        "DE-BY": _prof("DE-BY", "DE", thresholds=[_pv("1000000")]),
    }
    assert pr.validate_profiles(profiles) == []
    r = pr.resolve("DE-BY", profiles, date(2026, 1, 1))
    assert r.chain == ("EU", "DE", "DE-BY")
    assert (r.values[WORKS].value.value, r.values[WORKS].origin) == ("1000000", "DE-BY")
    standstill = r.values["notification/standstill/electronic"]
    assert (standstill.value.value, standstill.origin) == (14, "DE")
    assert pr.resolve("DE", profiles, date(2026, 1, 1)).values[WORKS].value.value == "5000000"


def test_effective_date_selects_the_slice_and_expired_is_stale() -> None:
    p = {"FR": _prof("FR", thresholds=[_pv("100", "2024-01-01", "2025-12-31"), _pv("120", "2026-01-01", "2027-12-31")])}
    assert pr.resolve("FR", p, date(2025, 6, 1)).values[WORKS].value.value == "100"
    now = pr.resolve("FR", p, date(2026, 6, 1)).values[WORKS]
    assert (now.value.value, now.status) == ("120", pr.STATUS_UNCONFIRMED)
    old = pr.resolve("FR", p, date(2028, 6, 1)).values[WORKS]
    assert (old.value.value, old.status) == ("120", pr.STATUS_STALE)
    # A value not yet in force does not count.
    assert WORKS not in pr.resolve("FR", p, date(2023, 6, 1)).values


def test_confirmation_is_bound_to_the_exact_value() -> None:
    p = {"FR": _prof("FR", thresholds=[_pv("100")])}
    h = pr.resolve("FR", p, date(2026, 1, 1)).values[WORKS].value_hash
    assert pr.resolve("FR", p, date(2026, 1, 1), [(WORKS, h)]).values[WORKS].status == pr.STATUS_CONFIRMED
    changed = {"FR": _prof("FR", thresholds=[_pv("101")])}
    assert pr.resolve("FR", changed, date(2026, 1, 1), [(WORKS, h)]).values[WORKS].status == pr.STATUS_UNCONFIRMED


# ── the advisory gate ───────────────────────────────────────────────────


def test_unconfirmed_and_stale_values_only_warn_with_their_source() -> None:
    p = {"FR": _prof("FR", thresholds=[_pv("100", "2024-01-01", "2025-12-31")])}
    prefixes = ev.profile_paths(ev.ConceptFacts(jurisdiction="fr", client_type="central"), "works", None)
    assert prefixes == ("thresholds/works/central/",)
    stale = ev.profile_findings(pr.resolve("FR", p, date(2026, 6, 1)), prefixes, "W1")
    assert [(f["code"], f["severity"], f["blocks_approval"]) for f in stale] == [
        ("profile_value_stale", ev.WARNING, False)
    ]
    assert stale[0]["source_url"] == SRC
    unconf = ev.profile_findings(pr.resolve("FR", p, date(2025, 6, 1)), prefixes, "W1")
    assert [f["code"] for f in unconf] == ["profile_value_unconfirmed"]
    r = pr.resolve("FR", p, date(2025, 6, 1))
    ok = pr.resolve("FR", p, date(2025, 6, 1), [(WORKS, r.values[WORKS].value_hash)])
    assert ev.profile_findings(ok, prefixes, "W1") == []
    assert ev.profile_findings(None, prefixes, "W1") == []


# ── v1 migrator ─────────────────────────────────────────────────────────


def test_migrator_keeps_only_overrides_and_reports_gaps_instead_of_inventing() -> None:
    eu = ProcurementCatalogue.model_validate(json.loads((CATALOGUE_DIR / "eu.json").read_text("utf-8")))
    de = ProcurementCatalogue.model_validate(json.loads((CATALOGUE_DIR / "de_national.json").read_text("utf-8")))
    m_eu = pr.migrate_v1(eu)
    m_de = pr.migrate_v1(de, parents=m_eu.profiles)
    eu_hashes = {(e.path, e.value.value_hash()) for e in pr.entries(m_eu.profiles["EU"])}
    de_prof = m_de.profiles["DE"]
    assert de_prof.header.parent == "EU" and de_prof.header.legacy_codes == ("de_national",)
    assert pr.entries(de_prof), "DE has its own national values"
    assert not any((e.path, e.value.value_hash()) in eu_hashes for e in pr.entries(de_prof))
    assert all(g.split(":")[0] in {"value_without_source_or_date", "lot_rule_stays_in_v1"} for g in m_de.gaps)
    for prof in m_de.profiles.values():
        for e in pr.entries(prof):
            assert e.value.source_url and e.value.effective_from
    assert pr.profile_for_legacy("de_national", pr.load_shipped()) == "DE"
    assert pr.profile_for_legacy("neutral", pr.load_shipped()) is None
