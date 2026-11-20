"""R12: the catalog card of the design editor link (needs the ERP core patch 0002 applied; skips without it)."""

from __future__ import annotations

import pytest

marketplace = pytest.importorskip("app.core.marketplace")
if not hasattr(marketplace, "DESIGN_LINK_ID"):
    pytest.skip("core patch 0002 (marketplace card) is not applied", allow_module_level=True)


class _Loader:
    def __init__(self, names: set[str]):
        self.loaded_modules = {name: object() for name in names}


def _card(loaded: set[str]) -> dict:
    original = marketplace.module_loader
    marketplace.module_loader = _Loader(loaded)
    try:
        cards = marketplace.get_marketplace_catalog()
    finally:
        marketplace.module_loader = original
    found = [c for c in cards if c["id"] == marketplace.DESIGN_LINK_ID]
    assert len(found) == 1, "exactly one design card"
    return found[0]


def test_card_is_an_integration_with_a_description():
    card = _card(set())
    assert card["category"] == "integration"
    assert card["name"] and len(card["description"]) > 40
    assert card["price"] == "Free"


def test_card_is_not_marked_coming_soon_and_follows_the_module():
    assert _card(set())["installed"] is False
    assert _card(set())["coming_soon"] is False
    assert _card({"oe_design"})["installed"] is True


def test_other_integrations_keep_their_behaviour():
    cards = marketplace.get_marketplace_catalog()
    others = [c for c in cards if c["category"] == "integration" and c["id"] != marketplace.DESIGN_LINK_ID]
    assert all(c["coming_soon"] is True and c["installed"] is False for c in others)


def test_ids_stay_unique():
    ids = [m.id for m in marketplace.MARKETPLACE_MODULES]
    assert len(ids) == len(set(ids))
