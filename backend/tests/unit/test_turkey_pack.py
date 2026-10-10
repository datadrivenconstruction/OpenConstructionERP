# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Turkish pack switches on what the engine runs, and its demo clears it.

Two rule sets: ``birimfiyat`` reads the poz number every Turkish line is priced
from, and ``turkey`` is the country's statute, starting with the KDV rate.
The pack's four documents used to enable nothing at all although the engine
already had both poz checks, and the Istanbul demo asked for neither set, so a
Turkish user's first bill was never read by a single Turkish rule.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.core.demo_packs import PACK_TEMPLATES
from app.core.validation.engine import validation_engine
from app.core.validation.rules import register_builtin_rules
from app.modules.boq.router import _COUNTRY_RULE_SETS
from app.modules.contracts.compliance_packs import RULE_PACKS

REPO_ROOT = Path(__file__).resolve().parents[3]
PACK = REPO_ROOT / "packs" / "turkey-tr" / "src" / "openconstructionerp_turkey_tr"
DEMO_ID = "mixed-use-istanbul"


@pytest.fixture(scope="module")
def manifest() -> Any:
    spec = importlib.util.spec_from_file_location("_tr_manifest", PACK / "manifest.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


def _documents() -> dict[str, dict[str, Any]]:
    return {p.stem: json.loads(p.read_bytes().decode("utf-8")) for p in sorted(PACK.glob("rule_packs/*.json"))}


def _template() -> Any:
    return next(t for t in PACK_TEMPLATES if t.demo_id == DEMO_ID)


def _demo_payload() -> dict[str, Any]:
    """The shipped demo, in the shape the payload builder produces."""
    template = _template()
    positions: list[dict[str, Any]] = []
    for ordinal, title, classification, items in template.sections:
        positions.append(
            {"id": f"s-{ordinal}", "ordinal": ordinal, "description": title, "classification": classification}
        )
        for item_ordinal, description, unit, quantity, rate, item_classification in items:
            positions.append(
                {
                    "id": f"p-{item_ordinal}",
                    "ordinal": item_ordinal,
                    "description": description,
                    "unit": unit,
                    "quantity": quantity,
                    "unit_rate": str(rate),
                    "classification": item_classification,
                    "parent_id": f"s-{ordinal}",
                }
            )
    markups = [
        {"name": name, "category": category, "percentage": str(percentage), "apply_to": apply_to, "is_active": True}
        for name, percentage, category, apply_to in template.markups
    ]
    return {
        "positions": positions,
        "boq": {"name": template.boq_name, "metadata": template.boq_metadata, "currency": template.currency},
        "markups": markups,
    }


# ── One rule set list, everywhere it is written ─────────────────────────


def test_the_pack_switches_on_both_turkish_rule_sets(manifest: Any) -> None:
    assert set(manifest.validation_rule_sets) == {"birimfiyat", "turkey"}


def test_every_place_that_names_turkish_rule_sets_names_the_same_ones(manifest: Any) -> None:
    expected = set(manifest.validation_rule_sets)
    assert expected <= set(RULE_PACKS["tr_compliance"]["rule_sets"])
    assert expected <= set(_COUNTRY_RULE_SETS["TR"])


def test_both_sets_have_rules_behind_them(manifest: Any) -> None:
    register_builtin_rules()
    for rule_set in manifest.validation_rule_sets:
        assert validation_engine.registry.has_rules(rule_set), rule_set


# ── The documents promise what the engine has ───────────────────────────


def test_the_unit_price_document_enables_the_two_poz_checks() -> None:
    document = _documents()["bayindirlik_unit_prices"]
    assert set(document["enables_rule_ids"]) == {"birimfiyat.code_required", "birimfiyat.valid_poz"}
    # The planned synonyms of the two built checks are gone, not kept twice.
    planned = set(document["planned_not_built_rule_ids"])
    assert not planned & {"birimfiyat.poz_reference_present", "birimfiyat.poz_number_format_valid"}


def test_every_document_says_who_has_not_read_it() -> None:
    for stem, document in _documents().items():
        status = str(document.get("review_status") or "")
        assert "quantity surveyor" in status.lower(), stem


def test_the_pack_names_the_ministry_by_its_current_name(manifest: Any) -> None:
    """The ministry was renamed in 2011 and again in 2021; it is the Çevre,
    Şehircilik ve İklim Değişikliği Bakanlığı that publishes the unit prices."""
    assert "Bayindirlik Bakanligi Birim Fiyat" not in manifest.description
    text = (PACK.parent.parent / "pyproject.toml").read_bytes().decode("utf-8")
    assert "Bayindirlik Bakanligi Birim Fiyat" not in text


def test_the_wizard_does_not_ask_for_the_seismic_zones_tbdy_2018_abolished(manifest: Any) -> None:
    """TBDY 2018 replaced the four numbered seismic zones with site-specific
    hazard from the AFAD map and an earthquake design class. A wizard that
    offers "Zone 1" under a TBDY 2018 heading asks a question the code no
    longer has."""
    script = yaml.safe_load((PACK / manifest.onboarding_script_path).read_bytes().decode("utf-8"))
    options = [
        str(option)
        for step in script["steps"]
        for field in step.get("fields", [])
        for option in field.get("options", []) or []
    ]
    assert not [option for option in options if option.lower().startswith("zone ")]


# ── The demo clears the checks the pack switches on ──────────────────────


@pytest.mark.asyncio
async def test_the_istanbul_demo_passes_the_turkish_checks(manifest: Any) -> None:
    register_builtin_rules()
    report = await validation_engine.validate(
        data=_demo_payload(),
        rule_sets=list(manifest.validation_rule_sets),
        target_type="boq",
        target_id=DEMO_ID,
        metadata={"locale": "en"},
    )
    fired = {result.rule_id for result in report.results}
    assert {"birimfiyat.code_required", "birimfiyat.valid_poz", "turkey.kdv_rate_in_force"} <= fired
    failed = sorted({result.rule_id for result in report.results if not result.passed})
    assert not failed, f"the Istanbul demo cannot clear its own pack's checks: {failed}"
