# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A broken XPWE price list is refused with the code the bill import names it by.

The XPWE reader raises coded parse errors (``xpwe_not_well_formed`` with the
line and column, ``xpwe_dtd_refused``, ...). The price-list preview used to
fold every one of them into ``pricelist_unreadable``, so the screen could not
say where the file breaks off. The code and its values now pass through.
"""

from __future__ import annotations

import io

import pytest

from app.modules.costs.pricelist_import import PriceListRefused, preview
from app.modules.costs.pricelists.service import plan_upload
from tests.fixtures import xpwe_builder as fx


def _refusal(content: bytes, name: str = "elenco.xpwe") -> PriceListRefused:
    with pytest.raises(PriceListRefused) as caught:
        preview(plan_upload(io.BytesIO(content), name), None, None)
    return caught.value


def test_a_list_cut_off_mid_file_names_where_it_breaks() -> None:
    whole = fx.small_computo()
    refused = _refusal(whole[: len(whole) // 2])
    assert refused.code == "xpwe_not_well_formed"
    assert set(refused.params) == {"line", "column"}
    assert refused.params["line"] >= 1
    # The English fallback is the parser's, not the bare code.
    assert str(refused) != refused.code


def test_a_list_declaring_entities_is_refused_by_code() -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aa">]><PweDocumento>&a;</PweDocumento>'
    assert _refusal(bomb).code == "xpwe_dtd_refused"


def test_the_refusal_reaches_the_screen_with_its_values() -> None:
    whole = fx.small_computo()
    detail = _refusal(whole[: len(whole) // 2]).as_http().detail
    assert detail["code"] == "xpwe_not_well_formed"
    assert {"line", "column"} <= set(detail)
