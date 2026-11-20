"""Project start: templates come from the generator's own typologies and only propose values."""

from __future__ import annotations

import pytest

from .conftest import LINK, make_user

BASE = "/api/v1/design"


def test_templates_are_generator_typologies_with_their_defaults():
    from app.modules.design import model_params as mp
    from app.modules.design.start_api import templates

    ts = {t["id"]: t for t in templates()}
    assert set(ts) == {"residential_block", "house", "school", "kindergarten", "office"}
    for t in ts.values():
        vals = {v["pointer"]: v for v in t["values"]}
        assert vals["/generator/template"]["value"] == t["typology"] in mp.TYPOLOGY
        assert mp.CATEGORY[vals["/use/category"]["value"]] == t["typology"]
        # a generator default is typical, not known for this project: shown as doubtful
        assert vals["/massing/floor_height_m"] == {
            "pointer": "/massing/floor_height_m",
            "value": mp.TYPOLOGY[t["typology"]][1],
            "doubtful": True,
        }
        assert not vals["/use/category"]["doubtful"]
        assert t["max_floors"] == mp.TYPOLOGY[t["typology"]][0]
        assert t["source"] == mp.GENERATOR_REF
    assert ts["kindergarten"]["typology"] == "school" and ts["residential_block"]["typology"] == "apartment_section"


@pytest.mark.asyncio
async def test_templates_endpoint_needs_a_login_and_writes_nothing(client):
    assert (await client.get(f"{BASE}/templates", headers=LINK)).status_code == 401
    _, h = await make_user(client)
    r = await client.get(f"{BASE}/templates", headers={**h, **LINK})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["id"] for t in body["templates"]][:2] == ["residential_block", "house"]
