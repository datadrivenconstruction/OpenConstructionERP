# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Delivery forms catalogue: every shipped file validates against the platform's own vocabularies.

Each check names the vocabulary it is held to (contract types, party roles,
risk register categories, the phase spine), and the negative cases show the
validator refusing a body that breaks exactly that one rule.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.modules.delivery_model.catalogue import (
    CATALOGUE_DIR,
    DELIVERY_FORMS_KIND,
    DeliveryFormsCatalogue,
    register_kinds,
    share_errors,
    validate_delivery_forms,
)
from app.modules.project_governance.catalogue import InvalidCatalogueError
from app.modules.project_governance.catalogue_kinds import get_catalogue_kind

MODULES = Path(__file__).resolve().parents[2] / "app" / "modules"


def _shipped() -> tuple[DeliveryFormsCatalogue, ...]:
    register_kinds()
    return get_catalogue_kind(DELIVERY_FORMS_KIND).shipped()


def _raw() -> dict:
    return json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))


def test_kind_is_registered_under_the_lead_decision_name() -> None:
    register_kinds()
    assert get_catalogue_kind("delivery_forms").kind == DELIVERY_FORMS_KIND == "delivery_forms"


def test_every_shipped_catalogue_validates() -> None:
    shipped = _shipped()
    assert [c.id for c in shipped] == ["neutral"]
    for c in shipped:
        assert validate_delivery_forms(c, "shipped") == []


def test_vocabularies_match_the_owning_modules() -> None:
    from app.modules.contracts.schemas import CONTRACT_TYPES, PARTY_ROLES
    from app.modules.risk.schemas import RiskCreate

    contract_types = set(CONTRACT_TYPES.split("|"))
    roles = set(PARTY_ROLES.split("|"))
    pattern = next(m.pattern for m in RiskCreate.model_fields["category"].metadata if getattr(m, "pattern", None))
    for c in _shipped():
        for f in c.forms:
            assert set(f.compatible_contract_types) <= contract_types, f.code
            for a in f.aliases:
                assert a.source_url.startswith("https://"), (f.code, a.term)
        for p in c.parties:
            assert p.contract_party_role in roles, p.code
        for cat in c.risk_categories:
            assert re.fullmatch(pattern, cat.register_category), cat.code
        for basis, types in c.price_basis_contract_types.items():
            assert set(types) <= contract_types, basis


def test_every_form_has_a_default_for_every_category_and_a_template() -> None:
    for c in _shipped():
        for f in c.forms:
            assert c.template_for(f.code) is not None, f.code
            for cat in c.risk_categories:
                assert c.default_for(f.code, cat.code) is not None, (f.code, cat.code)
            for crit in c.criteria:
                assert f.code in crit.scores, (crit.code, f.code)


def test_fidic_emerald_is_a_flag_and_an_alias_not_a_form() -> None:
    c = _shipped()[0]
    assert "underground_gbr" not in {f.code for f in c.forms}
    assert [fl.code for fl in c.flags] == ["underground_risk_sharing"]
    holders = {f.code for f in c.forms if any("Emerald" in a.term for a in f.aliases)}
    assert holders == {"design_build", "design_bid_build_single"}


def test_unverified_legal_rule_ships_unconfirmed() -> None:
    rules = {r.code: r for r in _shipped()[0].country_rules}
    assert str(rules["de_public_lot_splitting"].review_status) == "unconfirmed"


def test_every_shipped_label_key_has_english_text() -> None:
    from app.modules.delivery_model.messages import is_key_present

    raw = json.dumps(_raw())
    keys = set(re.findall(r'"(delivery_model\.catalogue\.[a-z0-9_.]+)"', raw))
    assert keys
    missing = sorted(k for k in keys if not is_key_present(k, "en"))
    assert missing == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda b: b["risk_categories"][0].update(register_category="commercial"), "register_category_unknown"),
        (lambda b: b["forms"][0].update(compatible_contract_types=["alliance"]), "form_contract_type_unknown"),
        (lambda b: b["parties"][0].update(contract_party_role="client"), "party_role_unknown"),
        (lambda b: b["forms"][0]["aliases"][0].update(source_url=""), "alias_without_source"),
        (lambda b: b["criteria"][0].update(default_weight="16"), "criteria_weights_not_100"),
        (lambda b: b["default_allocations"].append(dict(b["default_allocations"][0])), "allocation_duplicate"),
        (lambda b: b["price_basis_contract_types"].update(gmp=["guaranteed"]), "contract_type_unknown"),
        (lambda b: b["forms"][3].update(design_transfer_stage="lph4"), "form_transfer_stage_unknown"),
    ],
)
def test_validator_refuses_each_broken_rule(mutate, expected) -> None:
    body = _raw()
    mutate(body)
    with pytest.raises(InvalidCatalogueError) as exc:
        get_catalogue_kind(DELIVERY_FORMS_KIND).parse_body(body, source="shipped", origin="test")
    assert any(str(e).startswith(expected) for e in exc.value.errors), exc.value.errors


def test_share_rules() -> None:
    assert share_errors("shared", {"owner": "60", "contractor": "40"}) == []
    assert share_errors("shared", {"owner": "60", "contractor": "30"}) == ["shares_not_100"]
    assert share_errors("shared", {"owner": "100"}) == ["shared_needs_two_parties"]
    assert share_errors("owner", {"owner": "100", "x": "0"}) == ["shares_without_shared_party"]
    assert share_errors("shared", {"owner": "50", "nobody": "50"}, {"owner", "contractor"}) == ["share_party_unknown"]


def test_no_other_module_carries_the_delivery_form() -> None:
    """Rule 16: "who designs / builds / supplies" lives in the package plan only."""
    offenders = []
    pattern = re.compile(r"\b(delivery_form|delivery_model|selected_form_code|designs|builds)\b\s*:\s*Mapped")
    for models in MODULES.glob("*/models.py"):
        if models.parent.name == "delivery_model":
            continue
        if pattern.search(models.read_text(encoding="utf-8")):
            offenders.append(models.parent.name)
    assert offenders == []
