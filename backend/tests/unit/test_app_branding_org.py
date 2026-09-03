# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The organisation profile in workspace branding.

The point of these fields is that the CODE carries nobody's company:
reference prefix, organisation name and own mail domains resolve
branding-first, environment second, neutral default last. Each rail is
tested with the failure it prevents:

* the prefix lands inside minted references and a regex - junk tightens
  to A-Z/0-9 or disappears;
* domains are matched against inbound senders - anything that is not a
  plausible domain is dropped rather than silently never-matching;
* a partial admin update (just the organisation fields) must not wipe
  the stored logo - the router merges before it sanitises.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.app_branding import (
    DEFAULT_BRANDING,
    merge_branding,
    org_display_name,
    org_mail_domains,
    org_reference_prefix,
    read_branding,
    sanitise,
    write_branding,
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OE_REGISTER_HOUSE", "OE_PM_ORG", "OE_OUTLOOK_OWN_DOMAINS"):
        monkeypatch.delenv(var, raising=False)


# ── sanitise tightens ────────────────────────────────────────────────────


def test_prefix_tightens_to_uppercase_alnum() -> None:
    assert sanitise({"reference_prefix": " ac-me!9x "})["reference_prefix"] == "ACME9X"
    assert sanitise({"reference_prefix": "!!!"})["reference_prefix"] == ""
    assert sanitise({"reference_prefix": "ABCDEFGHIJK"})["reference_prefix"] == "ABCDEFGH"
    assert sanitise({"reference_prefix": 42})["reference_prefix"] == ""


def test_domains_tighten_to_plausible_domains() -> None:
    got = sanitise({"own_mail_domains": " @Foo.COM , bad domain, x.example ,, javascript:x"})
    assert got["own_mail_domains"] == "foo.com,x.example"
    assert sanitise({"own_mail_domains": ["a.com"]})["own_mail_domains"] == ""


def test_org_name_trims_and_caps() -> None:
    assert sanitise({"org_name": "  Acme  "})["org_name"] == "Acme"
    assert len(sanitise({"org_name": "x" * 500})["org_name"]) == 80


def test_stored_files_without_org_fields_read_with_defaults(tmp_path: Path) -> None:
    """A pre-existing branding file (logo era) must keep working."""
    (tmp_path / "app_branding.json").write_text('{"mode": "text", "company_name": "Old Brand"}', encoding="utf-8")
    got = read_branding(tmp_path)
    assert got["company_name"] == "Old Brand"
    assert got["reference_prefix"] == ""
    assert got["own_mail_domains"] == ""


# ── resolution chain: branding > env > neutral ───────────────────────────


def test_accessors_fall_back_to_neutral_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    assert org_reference_prefix(tmp_path) == "REG"
    assert org_display_name(tmp_path) == "Projects Team"
    assert org_mail_domains(tmp_path) == []


def test_env_covers_headless_deployments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("OE_REGISTER_HOUSE", "acme")
    monkeypatch.setenv("OE_PM_ORG", "Acme Electrical")
    monkeypatch.setenv("OE_OUTLOOK_OWN_DOMAINS", "Acme.example, other.example")
    assert org_reference_prefix(tmp_path) == "ACME"
    assert org_display_name(tmp_path) == "Acme Electrical"
    assert org_mail_domains(tmp_path) == ["acme.example", "other.example"]


def test_branding_wins_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OE_REGISTER_HOUSE", "ENVCO")
    monkeypatch.setenv("OE_PM_ORG", "Env Co")
    monkeypatch.setenv("OE_OUTLOOK_OWN_DOMAINS", "env.example")
    write_branding(
        {
            "org_name": "Stored Org",
            "reference_prefix": "STOR",
            "own_mail_domains": "stored.example",
        },
        tmp_path,
    )
    assert org_reference_prefix(tmp_path) == "STOR"
    assert org_display_name(tmp_path) == "Stored Org"
    assert org_mail_domains(tmp_path) == ["stored.example"]


def test_company_name_backfills_org_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    write_branding({"mode": "text", "company_name": "Sidebar Brand"}, tmp_path)
    assert org_display_name(tmp_path) == "Sidebar Brand"


# ── the router merge: a partial update must not wipe the logo ────────────


def test_partial_org_update_keeps_the_logo(tmp_path: Path) -> None:
    logo = "data:image/png;base64,AAAA"
    write_branding({"mode": "logo", "logo_data_url": logo}, tmp_path)

    result = merge_branding({"org_name": "Acme", "reference_prefix": "AC"}, tmp_path)
    assert result["logo_data_url"] == logo, "the org save must merge, not replace"
    assert result["org_name"] == "Acme"
    stored = read_branding(tmp_path)
    assert stored["logo_data_url"] == logo
    assert stored["reference_prefix"] == "AC"


def test_default_shape_carries_the_org_fields() -> None:
    for key in ("org_name", "reference_prefix", "own_mail_domains"):
        assert key in DEFAULT_BRANDING
