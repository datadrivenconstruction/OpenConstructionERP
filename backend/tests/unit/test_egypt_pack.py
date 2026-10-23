# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The Egypt pack composes data the platform already holds and invents none of it.

The pack sets no VAT, calendar or contract limit. Those live in core registries
keyed by the country, each with its own source. What the pack can get wrong is
the wiring (a methodology that does not exist, a demo that prices in another
currency or at another rate) and the copies of facts in its reference
documents, which are compared here with the code that enforces them.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.core.demo_projects import DEMO_TEMPLATES, PACK_DEMO_PROJECT
from app.modules.contracts.public_procurement import PUBLIC_WORKS_LIMITS
from app.modules.methodology.templates import TEMPLATES_BY_SLUG

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = REPO_ROOT / "packs" / "egypt-eg" / "src" / "openconstructionerp_egypt_eg"
RULE_PACKS = PACKAGE_DIR / "rule_packs"
ARABIC = re.compile(r"[؀-ۿ]")


def _manifest():  # noqa: ANN202
    import importlib.util

    spec = importlib.util.spec_from_file_location("egypt_eg_manifest", PACKAGE_DIR / "manifest.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MANIFEST


def test_the_manifest_names_the_egyptian_market() -> None:
    m = _manifest()
    assert m.slug == "egypt-eg"
    assert m.default_currency == "EGP"
    assert m.metadata["country"] == "EG"
    assert ARABIC.search(m.metadata["country_name_ar"])
    assert m.default_methodology in TEMPLATES_BY_SLUG
    assert TEMPLATES_BY_SLUG[m.default_methodology]["country_code"] == "EG"
    assert m.default_tax_template is None, "VAT comes from the country registry by document date"


def test_every_declared_document_is_shipped_and_names_itself() -> None:
    m = _manifest()
    on_disk = {p.stem for p in RULE_PACKS.glob("*.json")}
    assert set(m.validation_rule_packs) == on_disk
    for stem in on_disk:
        doc = json.loads((RULE_PACKS / f"{stem}.json").read_text(encoding="utf-8"))
        assert doc["rule_pack_id"] == stem
        assert doc["jurisdiction"] == "EG"
        assert doc["sources"], f"{stem} cites no source"
        assert doc["review_status"].startswith("Provisional")
        assert ARABIC.search(doc["name_ar"])
        assert len(doc["why_no_rules"]) > 80


def test_the_law_182_document_matches_the_limits_the_contracts_module_enforces() -> None:
    doc = json.loads((RULE_PACKS / "public_contracts_law_182.json").read_text(encoding="utf-8"))
    limits = PUBLIC_WORKS_LIMITS["EG"]
    assert doc["figures"], "the document records no figure"
    for field, figure in doc["figures"].items():
        assert str(limits[field]["value"]) == figure["value"], field


def test_the_vat_document_matches_the_regime_dates_in_core() -> None:
    from app.core.vat_regimes.data_eg import CUTOFF

    doc = json.loads((RULE_PACKS / "vat_construction_law_157.json").read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in doc["regimes"]}
    assert by_id["standard"]["from"] == CUTOFF.isoformat()
    assert by_id["schedule_tax"]["until"] == "2025-07-17"
    # 14 percent on 36 percent of the value.
    assert Decimal("14") * Decimal("0.36") == Decimal(by_id["transitional_decree_418"]["effective_rate_percent"])


def test_the_onboarding_script_sets_only_what_exists() -> None:
    script = yaml.safe_load((PACKAGE_DIR / "onboarding.yaml").read_text(encoding="utf-8"))
    text = (PACKAGE_DIR / "onboarding.yaml").read_text(encoding="utf-8")
    assert "set_tax_template" not in text
    assert ARABIC.search(script["title_ar"])
    apply = next(s["action"]["apply"] for s in script["steps"] if "action" in s)
    assert {"set_default_currency": "EGP"} in apply


def test_the_demo_is_wired_and_priced_as_an_egyptian_project() -> None:
    assert PACK_DEMO_PROJECT["egypt-eg"] == "residential-cairo"
    t = DEMO_TEMPLATES["residential-cairo"]
    assert t.currency == "EGP"
    assert t.region == "EG"
    assert t.address["country"] == "Egypt"
    assert t.classification_standard == "masterformat"
    assert _manifest().demo_template_ids == ["residential-cairo"]

    tax = [m for m in t.markups if m[2] == "tax"]
    assert [(m[0], m[1]) for m in tax] == [("VAT at 14%", 14.0)]

    # Overhead, profit and VAT follow the Egyptian estimating method.
    steps = {step["key"]: Decimal(step["rate"]) for step in TEMPLATES_BY_SLUG["egypt"]["cascade_steps"]}
    percents = {m[2]: Decimal(str(m[1])) for m in t.markups}
    assert percents["overhead"] == steps["overhead"]
    assert percents["profit"] == steps["profit"]
    assert percents["tax"] == steps["vat"]


@pytest.mark.parametrize("weekday", [6, 0, 1, 2, 3])
def test_the_work_week_the_pack_describes_is_the_one_core_holds(weekday: int) -> None:
    from app.core.calendar import _WORKING_WEEK

    assert weekday in _WORKING_WEEK["EG"]
