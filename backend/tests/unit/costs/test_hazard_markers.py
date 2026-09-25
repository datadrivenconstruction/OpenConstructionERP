# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hazardous-material markers read from data, in every cost database language."""

from __future__ import annotations

import pytest

from app.modules.costs.hazards import hazard_sql_flag, hazard_terms, hazards_in, query_names_a_hazard


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


@pytest.mark.parametrize(
    "text",
    [
        "Asbestos-free fibre cement sheets",
        "Non-asbestos brake lining",
        "Faserzementplatten, asbestfrei",
        "Plaques fibres-ciment sans amiante",
        "Placas de fibrocemento sin amianto",
        "Безасбестовые плиты",
        "Płyty bezazbestowe",
        "无石棉纤维水泥板",
    ],
)
def test_a_phrase_that_denies_the_hazard_carries_no_marker(text: str) -> None:
    assert hazards_in([text]) == []


def test_a_denial_does_not_hide_a_second_real_mention() -> None:
    assert hazards_in(["Remove asbestos cement roof, fit asbestos-free sheets"]) == ["asbestos"]


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("Asbestos cement sheets", 1),
        ("Asbestos-free fibre cement sheets", 0),
        ("Plaques fibres-ciment sans amiante", 0),
        ("Timber frame walls", 0),
    ],
)
def test_the_sql_flag_agrees_with_the_marker(text: str, flag: int) -> None:
    from sqlalchemy import bindparam, create_engine, select

    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        got = conn.execute(select(hazard_sql_flag(bindparam("d", text)))).scalar_one()
    assert got == flag
