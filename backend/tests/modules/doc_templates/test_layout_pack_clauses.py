# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clauses a country pack ships: listed for its market only, printed, never edited by a firm."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.doc_templates import legal
from app.core.doc_templates.legal import PackClause
from app.modules.doc_templates import layout_service as ls

_DE_PACK = (
    Path(__file__).resolve().parents[4]
    / "packs/germany-de/src/openconstructionerp_germany_de/document_requirements.json"
)
_CLAUSE = PackClause(
    key="xx_warranty",
    country="XX",
    category="warranty",
    title={"en": "Warranty"},
    text={"en": "Defects are remedied under the XX Building Act."},
    source="XX Building Act § 7",
)


class _Repo:
    def __init__(self, _session: Any) -> None:
        pass

    async def clauses(self) -> list[Any]:
        from app.modules.doc_templates.models import DocClause

        return [
            DocClause(key="retention", category="payment", title={"en": "Retention"}, text={"en": "5 % retained."}),
            DocClause(key="xx_warranty", category="", title={}, text={"en": "A firm copy that the pack overrides."}),
        ]


@pytest.fixture
def pack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal, "_all_pack_clauses", lambda: (_CLAUSE,))
    monkeypatch.setattr(ls, "DocLayoutRepository", _Repo)


def test_the_german_pack_ships_its_clauses_with_a_source() -> None:
    raw = json.loads(_DE_PACK.read_text(encoding="utf-8"))
    entries = raw["clauses"]
    assert entries and all(e["source"] and e["text"].get("de") and e["text"].get("en") for e in entries)


def test_pack_clauses_are_listed_read_only_for_their_market(pack: None) -> None:
    items = asyncio.run(ls.list_clauses(None, ["XX"]))  # type: ignore[arg-type]
    by_key = {i["key"]: i for i in items}
    assert by_key["retention"]["locked"] is False
    assert by_key["xx_warranty"]["locked"] is True
    assert by_key["xx_warranty"]["source"] == "XX Building Act § 7"
    assert len([i for i in items if i["key"] == "xx_warranty"]) == 1


def test_another_market_sees_no_pack_clause(pack: None) -> None:
    items = asyncio.run(ls.list_clauses(None, ["YY"]))  # type: ignore[arg-type]
    assert [i["key"] for i in items] == ["retention", "xx_warranty"]
    assert all(i["locked"] is False for i in items)


def test_a_pack_clause_cannot_be_changed_or_deleted(pack: None) -> None:
    with pytest.raises(HTTPException) as saved:
        asyncio.run(ls.save_clause(None, "xx_warranty", "", {}, {"en": "Mine"}, "u1", ["XX"]))  # type: ignore[arg-type]
    assert saved.value.status_code == 409
    with pytest.raises(HTTPException) as deleted:
        asyncio.run(ls.delete_clause(None, "xx_warranty", ["XX"]))  # type: ignore[arg-type]
    assert deleted.value.status_code == 409


def test_a_clause_without_text_is_refused(pack: None) -> None:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(ls.save_clause(None, "empty", "", {"en": "Title"}, {"en": "  "}, "u1"))  # type: ignore[arg-type]
    assert caught.value.status_code == 422


def test_the_pack_text_prints_over_a_firm_clause_of_the_same_key(pack: None) -> None:
    clauses = asyncio.run(ls.clause_map(None, ["XX"]))  # type: ignore[arg-type]
    assert clauses["xx_warranty"]["text"] == {"en": "Defects are remedied under the XX Building Act."}
    assert clauses["retention"]["text"] == {"en": "5 % retained."}
