"""Element-table upload refusals carry a code the UI translates."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from tests.unit.test_bim_hub_upload_guard import _call, _make_service, _upload


async def _refusal(data: bytes, filename: str) -> dict:
    with pytest.raises(HTTPException) as exc:
        await _call(_make_service(), _upload(data, filename))
    assert exc.value.status_code == 400
    assert isinstance(exc.value.detail, dict)
    return exc.value.detail


@pytest.mark.asyncio
async def test_wrong_table_type_is_coded() -> None:
    d = await _refusal(b"x", "model.txt")
    assert d["code"] == "unsupported_data_file_type"
    assert d["message"]


@pytest.mark.asyncio
async def test_empty_table_is_coded() -> None:
    d = await _refusal(b"element_id,element_type\n", "elements.csv")
    assert d["code"] == "no_data_rows"


@pytest.mark.asyncio
async def test_table_without_ids_is_coded() -> None:
    d = await _refusal(b"foo,bar\n1,2\n", "elements.csv")
    assert d["code"] in {"no_valid_elements", "data_file_unreadable"}
