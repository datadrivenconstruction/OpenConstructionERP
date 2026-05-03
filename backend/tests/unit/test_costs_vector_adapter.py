"""Unit tests for :class:`CostItemVectorAdapter` and helpers.

Covers:
    * to_text format (description | classifier_codes | unit) per the design brief
    * to_payload column mapping (id, description, unit, unit_cost, currency,
      region_code, source, language, classification_din276/_nrm/_masterformat)
    * Language derivation from region prefix
    * Lazy-load behaviour: importing the module does NOT touch lancedb
    * upsert applies the E5 ``passage:`` prefix at encode time
    * search applies the E5 ``query:`` prefix at encode time
    * upsert idempotency — two upserts for the same id end with one row
    * delete removes by id
    * Search results sorted by score (highest first)
    * Graceful degradation when lancedb is missing — returns 0/empty, no raise
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from app.core.vector_index import COLLECTION_COSTS
from app.modules.costs.vector_adapter import (
    _PASSAGE_PREFIX,
    _QUERY_PREFIX,
    CostItemVectorAdapter,
    _language_for,
    cost_item_vector_adapter,
)

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_row(**overrides: Any) -> SimpleNamespace:
    """Build a duck-typed CostItem row with the fields the adapter touches."""
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "code": "CWICR-DE-330-100",
        "description": "Stahlbetonwand C30/37, 240mm, mit Schalung und Bewehrung",
        "unit": "m2",
        "rate": "182.50",
        "currency": "EUR",
        "source": "cwicr",
        "region": "DE_BERLIN",
        "classification": {
            "din276": "330",
            "masterformat": "03 30 00",
            "nrm": "2.6.1",
        },
        "metadata_": {},
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── Module-level / singleton ─────────────────────────────────────────────


def test_singleton_collection_name() -> None:
    assert cost_item_vector_adapter.collection_name == COLLECTION_COSTS
    assert cost_item_vector_adapter.module_name == "costs"


def test_collection_constant_value() -> None:
    """Spec mandates the collection name ``oe_cost_items`` exactly."""
    assert COLLECTION_COSTS == "oe_cost_items"


def test_e5_prefixes_are_canonical() -> None:
    """Both prefixes include the trailing space the E5 model expects."""
    assert _PASSAGE_PREFIX == "passage: "
    assert _QUERY_PREFIX == "query: "


# ── to_text ──────────────────────────────────────────────────────────────


def test_to_text_full_row_format() -> None:
    """Format mandated by the design brief:
    ``{description} | {classifier_codes} | {unit}``.
    """
    adapter = CostItemVectorAdapter()
    text = adapter.to_text(_make_row())
    parts = [p.strip() for p in text.split("|")]
    assert parts[0].startswith("Stahlbetonwand C30/37")
    # Classifier-codes segment carries every classification key
    classifier = parts[1]
    assert "din276:330" in classifier
    assert "masterformat:03 30 00" in classifier
    assert "nrm:2.6.1" in classifier
    # Unit segment is last
    assert parts[-1] == "m2"


def test_to_text_does_not_apply_passage_prefix() -> None:
    """``to_text`` must NOT prepend ``passage:``.

    The prefix is owned by ``upsert`` (E5 boundary). Adding it inside
    ``to_text`` would leak it into the stored payload's ``text`` column
    where it pollutes snippet rendering.
    """
    adapter = CostItemVectorAdapter()
    text = adapter.to_text(_make_row())
    assert not text.startswith("passage:")
    assert not text.startswith("query:")


def test_to_text_drops_empty_fields() -> None:
    adapter = CostItemVectorAdapter()
    text = adapter.to_text(_make_row(unit="", classification={}))
    assert "Stahlbetonwand" in text
    # No dangling pipes for empty segments
    assert " |  | " not in text


def test_to_text_classifier_keys_sorted_for_stable_output() -> None:
    """Same row → same vector regardless of dict insertion order.

    ``to_text`` must sort the classification dict before joining, so two
    rows with the same content but different key ordering hash to the
    same embedding.
    """
    adapter = CostItemVectorAdapter()
    row_a = _make_row(
        classification={"din276": "330", "masterformat": "03 30 00", "nrm": "2.6.1"}
    )
    row_b = _make_row(
        classification={"nrm": "2.6.1", "din276": "330", "masterformat": "03 30 00"}
    )
    assert adapter.to_text(row_a) == adapter.to_text(row_b)


def test_to_text_skips_empty_classification_values() -> None:
    adapter = CostItemVectorAdapter()
    text = adapter.to_text(
        _make_row(classification={"din276": "330", "nrm": "", "mf": None})
    )
    assert "din276:330" in text
    assert "nrm:" not in text
    assert "mf:" not in text


def test_to_text_handles_non_dict_classification() -> None:
    adapter = CostItemVectorAdapter()
    text = adapter.to_text(_make_row(classification="not-a-dict"))
    # No crash; classifier segment is silently empty.
    assert "Stahlbetonwand" in text


def test_to_text_empty_row_returns_empty_string() -> None:
    adapter = CostItemVectorAdapter()
    text = adapter.to_text(
        _make_row(description="", unit="", classification={})
    )
    assert text == ""


# ── to_payload ───────────────────────────────────────────────────────────


def test_to_payload_carries_every_brief_column() -> None:
    """Brief mandates: id, description, unit, unit_cost, currency,
    region_code, source, language, classification_din276/_nrm/_masterformat."""
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(_make_row())
    for key in (
        "id",
        "description",
        "unit",
        "unit_cost",
        "currency",
        "region_code",
        "source",
        "language",
        "classification_din276",
        "classification_nrm",
        "classification_masterformat",
    ):
        assert key in payload, f"missing payload key: {key}"


def test_to_payload_unit_cost_is_float() -> None:
    """The DB stores rate as a string; the payload exposes a float."""
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(_make_row(rate="182.50"))
    assert payload["unit_cost"] == pytest.approx(182.50)


def test_to_payload_unit_cost_handles_unparseable_rate() -> None:
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(_make_row(rate="N/A"))
    assert payload["unit_cost"] == 0.0


def test_to_payload_classification_columns_split_correctly() -> None:
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(
        _make_row(
            classification={
                "din276": "330",
                "nrm": "2.6.1",
                "masterformat": "03 30 00",
            }
        )
    )
    assert payload["classification_din276"] == "330"
    assert payload["classification_nrm"] == "2.6.1"
    assert payload["classification_masterformat"] == "03 30 00"


def test_to_payload_missing_classification_keys_become_empty_strings() -> None:
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(_make_row(classification={"din276": "330"}))
    assert payload["classification_din276"] == "330"
    assert payload["classification_nrm"] == ""
    assert payload["classification_masterformat"] == ""


def test_to_payload_language_from_region() -> None:
    adapter = CostItemVectorAdapter()
    assert adapter.to_payload(_make_row(region="DE_BERLIN"))["language"] == "de"
    assert adapter.to_payload(_make_row(region="USA_NEWYORK"))["language"] == "en"
    assert adapter.to_payload(_make_row(region="RU_MOSCOW"))["language"] == "ru"


def test_to_payload_language_falls_back_to_english() -> None:
    adapter = CostItemVectorAdapter()
    assert adapter.to_payload(_make_row(region=None))["language"] == "en"
    assert adapter.to_payload(_make_row(region="UNKNOWN_REGION"))["language"] == "en"


def test_to_payload_explicit_language_metadata_wins() -> None:
    """An explicit ``metadata.language`` overrides region-derived inference."""
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(
        _make_row(region="DE_BERLIN", metadata_={"language": "es"})
    )
    assert payload["language"] == "es"


def test_to_payload_title_clipped_to_160() -> None:
    adapter = CostItemVectorAdapter()
    payload = adapter.to_payload(_make_row(description="x" * 500))
    assert len(payload["title"]) == 160


def test_to_payload_id_stringified() -> None:
    adapter = CostItemVectorAdapter()
    item_id = uuid.uuid4()
    payload = adapter.to_payload(_make_row(id=item_id))
    assert payload["id"] == str(item_id)


# ── language helper ──────────────────────────────────────────────────────


def test_language_for_handles_explicit_metadata() -> None:
    row = _make_row(region="DE_BERLIN", metadata_={"language": "fr"})
    assert _language_for(row) == "fr"


def test_language_for_normalises_case() -> None:
    row = _make_row(region="DE_BERLIN", metadata_={"language": "  ZH  "})
    assert _language_for(row) == "zh"


def test_language_for_ignores_empty_explicit() -> None:
    row = _make_row(region="DE_BERLIN", metadata_={"language": ""})
    assert _language_for(row) == "de"


def test_language_for_ignores_non_string_explicit() -> None:
    row = _make_row(region="DE_BERLIN", metadata_={"language": 42})
    assert _language_for(row) == "de"


# ── project_id_of ────────────────────────────────────────────────────────


def test_project_id_of_always_none() -> None:
    """Cost items are tenant-global, never per-project."""
    adapter = CostItemVectorAdapter()
    assert adapter.project_id_of(_make_row()) is None


# ── Lazy-load behaviour ──────────────────────────────────────────────────


def test_module_imports_without_lancedb() -> None:
    """Importing the adapter module must not touch lancedb / fastembed.

    We assert this by checking that the adapter module does NOT import
    lancedb at module level — the only way it should appear in
    ``sys.modules`` after import is if a previous test imported it via
    the upsert / search path. Reload here to start clean.
    """
    # Snapshot existing lancedb state so we don't fight with other
    # tests that may have legitimately imported it.
    pre_lancedb = sys.modules.get("lancedb")
    pre_fastembed = sys.modules.get("fastembed")

    # Reload IN PLACE — preserves module object identity so that other
    # modules (e.g. app.core.match_service.ranker) which captured a
    # reference via ``from app.modules.costs import vector_adapter as cost_vector``
    # still see the same object. Replacing via ``del sys.modules[...]; import``
    # would orphan those references and break later monkeypatches.
    mod_name = "app.modules.costs.vector_adapter"
    if mod_name in sys.modules:
        importlib.reload(sys.modules[mod_name])
    else:
        importlib.import_module(mod_name)

    # If lancedb / fastembed were not in sys.modules before our reload,
    # they MUST still not be there after — the adapter must not have
    # imported them at module level.
    if pre_lancedb is None:
        assert "lancedb" not in sys.modules, (
            "vector_adapter must not import lancedb at module level"
        )
    if pre_fastembed is None:
        assert "fastembed" not in sys.modules, (
            "vector_adapter must not import fastembed at module level"
        )


# ── upsert ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_applies_passage_prefix() -> None:
    """E5 asymmetric encoding: indexed text MUST be prefixed ``passage:``."""
    from app.modules.costs import vector_adapter as cost_vec

    captured_texts: list[str] = []

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        captured_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    captured_items: list[list[dict[str, Any]]] = []

    def fake_index(collection: str, items: list[dict[str, Any]]) -> int:
        assert collection == COLLECTION_COSTS
        captured_items.append(items)
        return len(items)

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_index_collection", side_effect=fake_index),
    ):
        n = await cost_vec.upsert([_make_row()])

    assert n == 1
    assert len(captured_texts) == 1
    assert captured_texts[0].startswith("passage: ")
    # Stored ``text`` field has the prefix stripped — only the encode
    # step should see it.
    stored = captured_items[0][0]
    assert not stored["text"].startswith("passage:")
    assert "Stahlbetonwand" in stored["text"]


@pytest.mark.asyncio
async def test_upsert_payload_is_json_serialised() -> None:
    """The wire payload column is a JSON string with all brief fields."""
    from app.modules.costs import vector_adapter as cost_vec

    captured: list[dict[str, Any]] = []

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def fake_index(collection: str, items: list[dict[str, Any]]) -> int:
        captured.extend(items)
        return len(items)

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_index_collection", side_effect=fake_index),
    ):
        await cost_vec.upsert([_make_row(region="DE_BERLIN")])

    assert len(captured) == 1
    payload = json.loads(captured[0]["payload"])
    assert payload["language"] == "de"
    assert payload["region_code"] == "DE_BERLIN"
    assert payload["unit_cost"] == pytest.approx(182.50)


@pytest.mark.asyncio
async def test_upsert_idempotent_for_same_id() -> None:
    """Two upserts of the same row leave one record (per LanceDB upsert).

    We exercise the adapter's contract by asserting the same id is sent
    twice with the same payload — the underlying ``vector_index_collection``
    is responsible for the delete-then-insert dedup, which we mock here
    to count distinct ids rather than total calls.
    """
    from app.modules.costs import vector_adapter as cost_vec

    seen_ids: dict[str, int] = {}

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def fake_index(collection: str, items: list[dict[str, Any]]) -> int:
        for item in items:
            seen_ids[item["id"]] = seen_ids.get(item["id"], 0) + 1
        return len(items)

    row = _make_row()
    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_index_collection", side_effect=fake_index),
    ):
        await cost_vec.upsert([row])
        await cost_vec.upsert([row])

    # Same id sent twice — the upsert helper passes it through twice
    # and lets the storage layer dedup. No accidental id mutation.
    assert len(seen_ids) == 1
    assert seen_ids[str(row.id)] == 2


@pytest.mark.asyncio
async def test_upsert_skips_rows_without_id_or_text() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    captured_texts: list[str] = []

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        captured_texts.extend(texts)
        return [[0.0] * 3 for _ in texts]

    def fake_index(collection: str, items: list[dict[str, Any]]) -> int:
        return len(items)

    rows = [
        _make_row(id=None),
        _make_row(description="", unit="", classification={}),
        _make_row(),
    ]
    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_index_collection", side_effect=fake_index),
    ):
        n = await cost_vec.upsert(rows)

    assert n == 1
    assert len(captured_texts) == 1


@pytest.mark.asyncio
async def test_upsert_empty_list_is_noop() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    assert await cost_vec.upsert([]) == 0


# ── delete ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_routes_to_storage_layer() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    deleted: list[tuple[str, list[str]]] = []

    def fake_delete(collection: str, ids: list[str]) -> int:
        deleted.append((collection, ids))
        return len(ids)

    item_id = uuid.uuid4()
    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.vector_delete_collection", side_effect=fake_delete),
    ):
        n = await cost_vec.delete([item_id, str(uuid.uuid4()), None])

    # None entries are dropped; UUID and string forms both pass through.
    assert n == 2
    assert deleted[0][0] == COLLECTION_COSTS
    assert len(deleted[0][1]) == 2
    assert deleted[0][1][0] == str(item_id)


@pytest.mark.asyncio
async def test_delete_empty_list_is_noop() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    assert await cost_vec.delete([]) == 0


# ── search ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_applies_query_prefix() -> None:
    """E5 asymmetric encoding: query text MUST be prefixed ``query:``."""
    from app.modules.costs import vector_adapter as cost_vec

    captured_texts: list[str] = []

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        captured_texts.extend(texts)
        return [[0.1] * 3 for _ in texts]

    def fake_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_search_collection", side_effect=fake_search),
    ):
        await cost_vec.search("reinforced concrete wall 240mm")

    assert len(captured_texts) == 1
    assert captured_texts[0].startswith("query: ")
    assert "reinforced concrete wall 240mm" in captured_texts[0]


@pytest.mark.asyncio
async def test_search_returns_results_sorted_by_score() -> None:
    """The store returns hits sorted; the adapter preserves that order."""
    from app.modules.costs import vector_adapter as cost_vec

    fake_hits = [
        {
            "id": "a",
            "score": 0.95,
            "text": "wall A",
            "payload": json.dumps({"region_code": "DE_BERLIN", "language": "de"}),
        },
        {
            "id": "b",
            "score": 0.80,
            "text": "wall B",
            "payload": json.dumps({"region_code": "DE_BERLIN", "language": "de"}),
        },
        {
            "id": "c",
            "score": 0.55,
            "text": "wall C",
            "payload": json.dumps({"region_code": "DE_BERLIN", "language": "de"}),
        },
    ]

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def fake_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return fake_hits

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_search_collection", side_effect=fake_search),
    ):
        results = await cost_vec.search("wall")

    assert [r["id"] for r in results] == ["a", "b", "c"]
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_search_decodes_string_payload_into_dict() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    fake_hits = [
        {
            "id": "x",
            "score": 0.9,
            "text": "x",
            "payload": json.dumps({"region_code": "DE_BERLIN", "unit": "m2"}),
        }
    ]

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def fake_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return fake_hits

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_search_collection", side_effect=fake_search),
    ):
        results = await cost_vec.search("anything")

    assert results[0]["payload"]["region_code"] == "DE_BERLIN"
    assert results[0]["payload"]["unit"] == "m2"


@pytest.mark.asyncio
async def test_search_filters_by_region() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    fake_hits = [
        {
            "id": "a",
            "score": 0.95,
            "text": "a",
            "payload": json.dumps({"region_code": "DE_BERLIN"}),
        },
        {
            "id": "b",
            "score": 0.90,
            "text": "b",
            "payload": json.dumps({"region_code": "GB_LONDON"}),
        },
    ]

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def fake_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return fake_hits

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_search_collection", side_effect=fake_search),
    ):
        results = await cost_vec.search("wall", region="DE_BERLIN")

    assert [r["id"] for r in results] == ["a"]


@pytest.mark.asyncio
async def test_search_filters_by_language() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    fake_hits = [
        {
            "id": "a",
            "score": 0.95,
            "text": "a",
            "payload": json.dumps({"language": "de"}),
        },
        {
            "id": "b",
            "score": 0.90,
            "text": "b",
            "payload": json.dumps({"language": "en"}),
        },
    ]

    async def fake_encode(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 3 for _ in texts]

    def fake_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return fake_hits

    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch("app.core.vector.encode_texts_async", new=fake_encode),
        patch("app.core.vector.vector_search_collection", side_effect=fake_search),
    ):
        results = await cost_vec.search("wall", language="en")

    assert [r["id"] for r in results] == ["b"]


@pytest.mark.asyncio
async def test_search_empty_query_is_noop() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    assert await cost_vec.search("") == []
    assert await cost_vec.search("   ") == []


# ── Graceful degradation when lancedb is missing ─────────────────────────


@pytest.mark.asyncio
async def test_upsert_degrades_gracefully_without_lancedb() -> None:
    """Brief: 'must still start. degrade gracefully with a clear log message'."""
    from app.modules.costs import vector_adapter as cost_vec

    with patch.object(cost_vec, "_vector_available", return_value=False):
        # Must not raise; must return 0.
        n = await cost_vec.upsert([_make_row()])
    assert n == 0


@pytest.mark.asyncio
async def test_search_degrades_gracefully_without_lancedb() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    with patch.object(cost_vec, "_vector_available", return_value=False):
        results = await cost_vec.search("anything")
    assert results == []


@pytest.mark.asyncio
async def test_delete_degrades_gracefully_without_lancedb() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    with patch.object(cost_vec, "_vector_available", return_value=False):
        n = await cost_vec.delete([uuid.uuid4()])
    assert n == 0


@pytest.mark.asyncio
async def test_reindex_all_degrades_gracefully_without_lancedb() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    with patch.object(cost_vec, "_vector_available", return_value=False):
        result = await cost_vec.reindex_all([_make_row(), _make_row()])
    assert result["indexed"] == 0
    assert result["collection"] == COLLECTION_COSTS
    # Should still produce a took_ms timing, even if zero.
    assert "took_ms" in result


def test_collection_count_degrades_gracefully_without_lancedb() -> None:
    from app.modules.costs import vector_adapter as cost_vec

    with patch.object(cost_vec, "_vector_available", return_value=False):
        # collection_count is async but cheap to await synchronously here
        import asyncio as _asyncio

        n = _asyncio.get_event_loop().run_until_complete(cost_vec.collection_count())
    assert n == 0


def test_vector_available_caches_lancedb_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a missing lancedb by zeroing find_spec for 'lancedb'."""
    from app.modules.costs import vector_adapter as cost_vec

    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "lancedb":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    assert cost_vec._vector_available() is False


# ── Reindex_all batching ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reindex_all_batches_correctly() -> None:
    """``reindex_all`` issues one upsert per ``batch_size`` chunk."""
    from app.modules.costs import vector_adapter as cost_vec

    upsert_calls: list[int] = []

    async def fake_upsert(rows: list[Any]) -> int:
        upsert_calls.append(len(rows))
        return len(rows)

    rows = [_make_row() for _ in range(7)]
    with (
        patch.object(cost_vec, "_vector_available", return_value=True),
        patch.object(cost_vec, "upsert", side_effect=fake_upsert),
    ):
        result = await cost_vec.reindex_all(rows, batch_size=3)

    # 7 rows / batch_size=3 → batches of 3, 3, 1
    assert upsert_calls == [3, 3, 1]
    assert result["indexed"] == 7
    assert result["collection"] == COLLECTION_COSTS
