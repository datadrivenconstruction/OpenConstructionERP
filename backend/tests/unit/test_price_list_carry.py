"""What a bill line takes from the price-list item it is made from, and what a copy keeps.

The routes themselves run on PG in
``tests/modules/test_price_list_lines_keep_their_source.py``; this file pins
the shape of what they carry.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.boq.price_list_carry import (
    CARRIED_KEYS,
    carry_block,
    linked_cost_item_id,
    price_list_block,
    provenance_of,
)

ITEM_BLOCK = {
    "region": "Toscana",
    "region_code": "TOS",
    "edition": "2025",
    "licence": "CC BY 3.0",
    "attribution": "Regione Toscana, Prezzario dei Lavori Pubblici della Toscana",
    "labour_share_pct": "40.36",
    "chapters": [{"code": "01", "title": "NUOVE COSTRUZIONI EDILI"}] * 3,
    "analysis": [{"name": "Operaio comune", "cost": 4.8}] * 20,
    "flags": ["analysis_exceeds_price"],
    "short_description": "Scavo",
}


def _item(block: dict | None) -> SimpleNamespace:
    return SimpleNamespace(metadata_={"prezzario": block} if block is not None else {"variant_stats": {}})


def test_a_line_takes_the_list_licence_and_shares_and_leaves_the_bulk_on_the_item() -> None:
    block = price_list_block(_item(ITEM_BLOCK))
    assert block == {
        "region": "Toscana",
        "region_code": "TOS",
        "edition": "2025",
        "licence": "CC BY 3.0",
        "attribution": "Regione Toscana, Prezzario dei Lavori Pubblici della Toscana",
        "labour_share_pct": "40.36",
    }
    assert set(block) <= set(CARRIED_KEYS)


def test_an_item_from_no_price_list_carries_nothing() -> None:
    assert price_list_block(_item(None)) is None
    assert price_list_block(SimpleNamespace(metadata_=None)) is None


def test_re_linking_to_an_item_without_a_list_drops_the_old_block() -> None:
    meta = {"prezzario": {"region": "Veneto"}, "resources": []}
    carry_block(meta, _item(None))
    assert meta["prezzario"] == {"region": "Veneto"}, "adding keeps what the caller sent"
    carry_block(meta, _item(None), replace=True)
    assert "prezzario" not in meta
    carry_block(meta, _item(ITEM_BLOCK), replace=True)
    assert meta["prezzario"]["region"] == "Toscana"


def test_the_link_is_read_from_the_metadata_as_the_editor_writes_it() -> None:
    item_id = uuid.uuid4()
    assert linked_cost_item_id({"cost_item_id": str(item_id)}) == item_id
    assert linked_cost_item_id({"cost_item_id": item_id}) == item_id
    for meta in ({"cost_item_id": "not-a-uuid"}, {"cost_item_id": ""}, {}, None):
        assert linked_cost_item_id(meta) is None


def test_a_copied_line_keeps_where_its_rate_came_from_and_nothing_else() -> None:
    meta = {
        "prezzario": {"region": "Lazio"},
        "cost_shares": {"labour": "0.4"},
        "xpwe_ep_id": "12",
        "safety_item": True,
        "cost_item_id": "abc",
        "resources": [{"name": "Operaio"}],
        "bim_qty_source": {"model": "x"},
    }
    copied = provenance_of(meta)
    assert copied == {
        "prezzario": {"region": "Lazio"},
        "cost_shares": {"labour": "0.4"},
        "xpwe_ep_id": "12",
        "safety_item": True,
        "cost_item_id": "abc",
    }
    copied["prezzario"]["region"] = "Umbria"
    assert meta["prezzario"]["region"] == "Lazio", "the copy is its own"
    assert provenance_of(None) == {}
