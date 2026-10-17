"""Semantic search says it is unavailable instead of answering an empty list.

The endpoint used to catch the missing optional stack and return ``200 []``. The cost
grid draws that exactly as it draws a query that matched nothing, so a reader on a
deployment without the ``[semantic]`` extra was told their search had no results when
the search had never run. Every neighbouring endpoint in the same router already
answers 503 for the same condition, and the orchestrator above them documents 503 as
the graceful-degradation signal, so the odd one out was this one.

The client is still expected to fall back to lexical search. The point is that it can
now tell the reader it did.
"""

import pytest
from fastapi import HTTPException

from app.core import vector
from app.modules.costs.router import semantic_search

# Called directly, outside a request: no reader is bound, so the hits are not
# looked up against the database and the session is never used.


@pytest.mark.asyncio
async def test_missing_embedding_model_is_a_503_not_an_empty_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_model(_texts: list[str]) -> list[list[float]]:
        raise RuntimeError("No embedding model available. Install fastembed or sentence-transformers.")

    monkeypatch.setattr(vector, "encode_texts", no_model)

    with pytest.raises(HTTPException) as raised:
        await semantic_search(session=None, _user_id="reader", q="reinforced concrete", region=None, limit=25)

    assert raised.value.status_code == 503
    assert "not available" in str(raised.value.detail)
    # The remedy belongs in the message, not only in the server log.
    assert "semantic" in str(raised.value.detail)
    # The raw import text is never echoed back to the caller.
    assert "sentence-transformers" not in str(raised.value.detail)


@pytest.mark.asyncio
async def test_missing_optional_package_is_a_503_too(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_package(_texts: list[str]) -> list[list[float]]:
        raise ModuleNotFoundError("No module named 'qdrant_client'")

    monkeypatch.setattr(vector, "encode_texts", no_package)

    with pytest.raises(HTTPException) as raised:
        await semantic_search(session=None, _user_id="reader", q="foundation slab", region="de", limit=10)

    assert raised.value.status_code == 503
    assert "qdrant_client" not in str(raised.value.detail)


@pytest.mark.asyncio
async def test_a_working_stack_still_answers_with_its_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vector, "encode_texts", lambda texts: [[0.1, 0.2, 0.3] for _ in texts])
    monkeypatch.setattr(
        vector,
        "vector_search",
        lambda _vector, region=None, limit=25: [{"id": "1", "description": "Stahlbetonwand"}],
    )

    hits = await semantic_search(session=None, _user_id="reader", q="concrete wall", region=None, limit=25)

    assert hits == [{"id": "1", "description": "Stahlbetonwand"}]


def test_the_status_probe_names_the_state_without_loading_a_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three states, because the three remedies differ."""
    monkeypatch.setattr(vector, "_embedder_instance", None)
    monkeypatch.setattr(vector, "_embedder_tried", False)
    monkeypatch.setattr(vector, "_has_module", lambda name: False)
    absent = vector.embedder_status()
    assert absent["available"] is False
    assert absent["state"] == "library_missing"
    assert absent["model"]

    monkeypatch.setattr(vector, "_has_module", lambda name: True)
    assert vector.embedder_status()["state"] == "not_loaded"

    monkeypatch.setattr(vector, "_embedder_tried", True)
    assert vector.embedder_status()["state"] == "load_failed"

    monkeypatch.setattr(vector, "_embedder_instance", object())
    ready = vector.embedder_status()
    assert ready["available"] is True
    assert ready["state"] == "ready"
    assert ready["dimension"] > 0
