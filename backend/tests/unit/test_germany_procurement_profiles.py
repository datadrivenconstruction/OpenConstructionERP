"""The Germany pack's procurement profiles: one per federal state plus the federal baseline.

None may claim legal authority before a reviewer has filled and signed it off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROFILES = (
    Path(__file__).resolve().parents[3]
    / "packs"
    / "germany-de"
    / "src"
    / "openconstructionerp_germany_de"
    / "procurement_profiles"
)
STATES = {"BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH"}
REQUIRED = set(json.loads((PROFILES / "_schema.json").read_text(encoding="utf-8"))["required"])


def _profiles() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in PROFILES.glob("de_*.json")}


def test_federal_baseline_and_all_sixteen_states_are_present() -> None:
    profiles = _profiles()
    assert "de_federal" in profiles
    states = {p["jurisdiction"].removeprefix("DE-") for p in profiles.values() if p["level"] == "state"}
    assert states == STATES
    assert len(profiles) == 17


@pytest.mark.parametrize("name", sorted(_profiles()))
def test_profile_matches_the_schema_keys(name: str) -> None:
    profile = _profiles()[name]
    assert set(profile) == REQUIRED
    assert profile["profile_id"] == name
    if profile["level"] == "state":
        assert profile["extends"] == "de_federal"


@pytest.mark.parametrize("name", sorted(_profiles()))
def test_an_active_profile_is_reviewed_and_every_rule_cites_a_source(name: str) -> None:
    profile = _profiles()[name]
    if not profile["active"]:
        return
    assert profile["review_status"] == "reviewed"
    assert profile["reviewed_by"]
    assert profile["reviewed_on"]
    assert profile["versions"]
    for version in profile["versions"]:
        assert version["source_url"].startswith("https://")
        assert version["effective_from"]
        for rule in version["rules"]:
            assert rule["source_url"].startswith("https://")


def test_unreviewed_profiles_carry_no_values() -> None:
    for profile in _profiles().values():
        if profile["review_status"] != "reviewed":
            assert profile["active"] is False
            assert profile["versions"] == []


def test_hessen_is_the_only_pilot() -> None:
    assert [p["jurisdiction"] for p in _profiles().values() if p["pilot"]] == ["DE-HE"]
