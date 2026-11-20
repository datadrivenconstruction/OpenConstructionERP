"""Desktop writes elements.parquet with zstd, the browser build with snappy: intake must treat them alike."""

from __future__ import annotations

import pytest

from .ddcrev import example_rows, package, parquet
from .test_design_revisions import BIM, _linked_project, _upload

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("codec", ["zstd", "snappy", "none"])
async def test_intake_accepts_any_parquet_compression(client, codec):
    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    data, _ = package(pid, rows, files={"elements.parquet": parquet(rows, compression=codec)})
    r = await _upload(client, pid, tok, data)
    assert r.status_code == 201, r.text
    mid = r.json()["bim_model_id"]
    els = (await client.get(f"{BIM}/models/{mid}/elements/", headers=h)).json()["items"]
    got = sorted((e["stable_id"], repr(sorted(e["quantities"].items()))) for e in els)
    # Identical across codecs: compare with the zstd baseline built from the same rows.
    uid2, h2, pid2, tok2 = await _linked_project(client)
    base, _ = package(pid2, rows)
    r2 = await _upload(client, pid2, tok2, base)
    assert r2.status_code == 201, r2.text
    els2 = (await client.get(f"{BIM}/models/{r2.json()['bim_model_id']}/elements/", headers=h2)).json()["items"]
    want = sorted((e["stable_id"], repr(sorted(e["quantities"].items()))) for e in els2)
    assert len(got) == len(rows) and got == want
