"""The Italy pack offers the Toscana base, credits its publisher, and runs the italy rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

PACKAGE_DIR = Path(__file__).resolve().parents[3] / "packs" / "italy-it" / "src" / "openconstructionerp_italy_it"


@pytest.fixture(scope="module")
def manifest():
    spec = importlib.util.spec_from_file_location("_italy_manifest_under_test", PACKAGE_DIR / "manifest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


def test_the_pack_declares_rome_and_toscana(manifest) -> None:
    assert manifest.cwicr_regions == ["cwicr-it-rome", "cwicr-it-toscana"]


def test_onboarding_preloads_both_bases(manifest) -> None:
    script = yaml.safe_load((PACKAGE_DIR / manifest.onboarding_script_path).read_text(encoding="utf-8"))
    review = next(step for step in script["steps"] if step["id"] == "review")
    preload = next(a["preload_cwicr_regions"] for a in review["action"]["apply"] if "preload_cwicr_regions" in a)
    assert preload == ["cwicr-it-rome", "cwicr-it-toscana"]


def test_toscana_slug_resolves_to_the_bundled_base() -> None:
    from app.core.partner_pack.full_install import resolve_cwicr_db_id
    from app.modules.catalog.router import REGION_MAP

    assert resolve_cwicr_db_id("cwicr-it-toscana") == "IT_TOSCANA"
    assert resolve_cwicr_db_id("cwicr-it-rome") == "IT_ROME"
    assert "IT_TOSCANA" in REGION_MAP


def test_activation_dialog_credits_regione_toscana(manifest) -> None:
    from app.core.partner_pack.full_install import describe_cost_bases

    bases = {b["db_id"]: b for b in describe_cost_bases(manifest.cwicr_regions)}
    toscana = bases["IT_TOSCANA"]
    assert toscana["loadable"] is True
    assert toscana["licence"] == "CC BY 4.0"
    assert toscana["attribution"].startswith("Regione Toscana, Prezzario dei Lavori Pubblici della Toscana")
    # Rome carries no third-party licence, so nothing is credited there.
    assert bases["IT_ROME"]["attribution"] is None


def test_base_browser_payload_carries_the_attribution() -> None:
    from app.modules.costs.base_registry import public_catalog

    families = {f["key"]: f for f in public_catalog()["families"]}
    assert families["italy"]["licence"] == "CC BY 4.0"
    assert "Regione Toscana" in families["italy"]["attribution"]
    assert families["china"]["attribution"] is None


def test_the_pack_runs_the_italy_rule_set(manifest) -> None:
    from app.core.validation.engine import rule_registry
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    assert manifest.validation_rule_sets == ["italy"]
    assert {entry["rule_id"] for entry in rule_registry.list_rules(rule_set="italy")} >= {
        "prezzario.voce_code_format_valid",
        "prezzario.costi_sicurezza_separated",
    }


def test_readme_no_longer_says_rates_are_not_redistributed() -> None:
    text = (PACKAGE_DIR.parents[1] / "README.md").read_text(encoding="utf-8")
    assert "without redistributing the rates" not in text
    assert "CC BY 4.0" in text and "Regione Toscana" in text
    assert "No engine rule set is active yet" not in text
