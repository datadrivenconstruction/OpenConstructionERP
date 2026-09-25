# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hazardous-material markers read from data, in every cost database language."""

from __future__ import annotations

import pytest

from app.modules.costs.hazards import hazard_terms, hazards_in, query_names_a_hazard


@pytest.mark.parametrize(
    "text",
    [
        "Wall cladding with chrysotile cement sheets on a ready-made wooden frame",
        "Asbestzement-Wellplatten verlegen",
        "Plaques en amiante-ciment",
        "Placas de fibrocemento con amianto",
        "Chapas de fibrocimento com amianto",
        "АСБЕСТОЦЕМЕНТНЫЕ листы",
        "Азбестоциментови плочи",
        "Płyty azbestowo-cementowe",
        "石棉瓦屋面",
        "石綿スレート",
        "석면 슬레이트",
        "Tấm lợp amiăng",
    ],
)
def test_asbestos_is_recognised_in_each_language(text: str) -> None:
    assert hazards_in([text]) == ["asbestos"]


def test_an_ordinary_item_carries_no_marker() -> None:
    assert hazards_in(["Timber frame walls, studs 50x100", None, ""]) == []


def test_the_terms_come_from_the_data_file() -> None:
    terms = hazard_terms()
    assert "asbestos" in terms
    assert all(t == t.casefold() for t in terms["asbestos"])


def test_a_search_that_names_the_hazard_is_not_demoted() -> None:
    assert query_names_a_hazard("chrysotile sheets")
    assert not query_names_a_hazard("frame walls")
    assert not query_names_a_hazard(None)
