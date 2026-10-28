# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shipped catalogue labels resolve to text, governance gate names are authored, and a locale a module bundle
does not ship falls back to English without a warning."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.modules.commitment_release.messages import label_texts as commitment_label_texts
from app.modules.delivery_model.messages import label_texts, with_label_texts
from app.modules.project_governance.messages import translate as governance_text

_MODULES = Path(__file__).resolve().parents[2] / "app" / "modules"


def test_shipped_key_resolves_for_request_locale() -> None:
    key = "delivery_model.catalogue.neutral.contract_kind.land_tenure.leasehold"
    assert label_texts(key, None, "en")["en"] != key
    assert label_texts(key, None, "de")["de"] != key


def test_tenant_labels_win_and_unknown_key_stays_unresolved() -> None:
    assert label_texts("delivery_model.catalogue.neutral.nope", {"en": "Mine"}, "de") == {"en": "Mine"}
    assert label_texts("delivery_model.catalogue.neutral.nope", None, "de") is None
    assert label_texts(None, None, "de") is None


def test_catalogue_body_gets_texts_for_every_shipped_key() -> None:
    body = json.loads((_MODULES / "delivery_model" / "catalogues" / "neutral.json").read_text(encoding="utf-8"))
    resolved = with_label_texts({"contract_kinds": body.get("contract_kinds", [])}, "de")
    kinds = resolved["contract_kinds"]
    assert kinds
    for kind in kinds:
        assert kind.get("labels") or not kind.get("name_key"), kind["code"]


def test_commitment_catalogue_names_resolve() -> None:
    schedule = json.loads(
        (_MODULES / "commitment_release" / "catalogues" / "authority_schedule" / "neutral.json").read_text(
            encoding="utf-8"
        )
    )
    keys = [t["name_key"] for t in schedule.get("tiers", []) if t.get("name_key")]
    assert keys
    for key in keys:
        assert commitment_label_texts(key, None, "en")["en"] != key


def test_governance_gate_keys_exist_in_en_and_de() -> None:
    catalogue = json.loads((_MODULES / "project_governance" / "catalogues" / "neutral.json").read_text("utf-8"))
    gate_keys = [g["name_key"] for g in catalogue["gates"]]
    assert len(gate_keys) == 10
    for locale in ("en", "de"):
        for key in gate_keys:
            assert governance_text(key, locale=locale) != key
            assert not governance_text(key, locale=locale).islower() or " " in governance_text(key, locale=locale)


def test_unshipped_locale_falls_back_without_warning(caplog) -> None:
    from app.modules.delivery_model.messages import translate

    key = "delivery_model.catalogue.neutral.contract_kind.land_tenure.leasehold"
    with caplog.at_level(logging.INFO):
        for locale in ("sw", "sw-KE", "ha"):
            assert translate(key, locale=locale) == translate(key, locale="en")
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
