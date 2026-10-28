"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The offline fallback of the vector loader has to survive its own first line.

When the pre-built embeddings cannot be fetched, this endpoint falls back to
generating them locally from the cost items already in the database. That branch
unpacked ``CostItemRepository.search`` into two names while the method returns
three, so it raised ``ValueError`` before doing anything. The surrounding
``except`` turned that into "vector generation failed", which named the
embedding model - so the message pointed at everything except the line above it.

Only an installation that cannot reach the download takes this branch, which is
why it could stay broken: the machines that never see it are the ones that would
have reported it.

The second test is the control. The first one runs against a stand-in
repository, and a stand-in is only evidence while it still matches the real
signature, so this pins the arity the stand-in was built from. If the repository
ever returns a different number of values, this fails and says so instead of
letting the first test keep passing against a contract that moved.
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

import pytest

from app.modules.costs import router
from app.modules.costs.repository import CostItemRepository

DB_ID = "XX_OFFLINE"
ITEMS = 4
DIM = 8


class _Item:
    """The attributes the fallback reads off a cost item."""

    def __init__(self, index: int) -> None:
        self.id = f"00000000-0000-0000-0000-{index:012d}"
        self.code = f"R{index:04d}"
        self.description = f"Work item {index}"
        self.unit = "m3"
        self.rate = 10.0 + index
        self.region = DB_ID


class _Repo:
    """Returns what ``CostItemRepository.search`` returns: rows, total, has_more."""

    def __init__(self, _session: Any) -> None:
        self.calls = 0

    async def search(self, **_kwargs: Any) -> tuple[list[_Item], int, bool]:
        self.calls += 1
        items = [_Item(index) for index in range(ITEMS)]
        return items, len(items), False


async def test_the_offline_fallback_reaches_the_embedding_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.vector as vector_module
    import app.modules.costs.repository as repository_module

    encoded: list[list[str]] = []
    indexed_records: list[dict[str, Any]] = []

    def _encode(texts: list[str]) -> list[list[float]]:
        encoded.append(list(texts))
        return [[float(position)] * DIM for position in range(len(texts))]

    def _index(records: list[dict[str, Any]]) -> int:
        indexed_records.extend(records)
        return len(records)

    def _no_download(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("no route to host")

    monkeypatch.setitem(router._GITHUB_CWICR_FILES, DB_ID, f"{DB_ID}/{DB_ID}.parquet")
    monkeypatch.setattr(router, "_CWICR_CACHE_DIR", tmp_path)
    monkeypatch.setattr(router, "_download_to_file", _no_download)
    monkeypatch.setattr(repository_module, "CostItemRepository", _Repo)
    monkeypatch.setattr(vector_module, "encode_texts", _encode)
    monkeypatch.setattr(vector_module, "vector_index", _index)

    response = await router.load_vector_from_github(db_id=DB_ID, session=None, _user_id=None)  # type: ignore[arg-type]

    assert response["source"] == "local", "the download was reachable, so the offline branch never ran"
    assert response["indexed"] == ITEMS
    assert len(indexed_records) == ITEMS
    assert encoded, "nothing was ever handed to the embedding model"


def test_the_stand_in_matches_the_real_search_signature() -> None:
    hints = typing.get_type_hints(CostItemRepository.search)
    returned = typing.get_args(hints["return"])

    assert len(returned) == 3, (
        f"CostItemRepository.search now returns {len(returned)} values; the stand-in above returns 3, "
        "so the fallback test is no longer evidence about the real call"
    )
