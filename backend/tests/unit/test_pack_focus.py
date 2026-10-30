# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pack focus: every shipped pack resolves to modules, focus hides the rest, show-all reverses it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import pack_focus
from app.core import solution_packages as sp
from app.core.partner_pack.discovery import discover_packs
from tests.unit.test_solution_packages import _client, _Service


def test_every_shipped_pack_resolves_to_existing_modules() -> None:
    packs = discover_packs()
    assert len(packs) >= 30
    assert pack_focus.validate_packs(packs) == []
    known = sp.known_modules()
    for manifest in packs:
        mods, _ = pack_focus.pack_modules(manifest)
        assert mods and set(mods) <= known, manifest.slug


def test_declared_modules_win_over_the_fallback() -> None:
    manifest = SimpleNamespace(slug="x", type="partner", default_modules=["oe_daily_diary"])
    mods, source = pack_focus.pack_modules(manifest)
    assert source == "manifest" and "daily_diary" in mods and "tendering" not in mods


def test_empty_declaration_falls_back_by_type() -> None:
    manifest = SimpleNamespace(slug="x", type="country", default_modules=[])
    mods, source = pack_focus.pack_modules(manifest)
    assert source == "fallback" and {"boq", "validation", "tendering"} <= set(mods)


def test_validate_flags_a_pack_without_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(pack_focus.FALLBACK_BY_TYPE, "partner", ("no_such_module",))
    manifest = SimpleNamespace(slug="empty", type="partner", default_modules=[])
    issues = pack_focus.validate_packs([manifest])
    assert any("empty: resolves to no modules" in i for i in issues)


def test_focus_hides_others_and_show_all_restores() -> None:
    meta = pack_focus.focus({}, "germany-de", ["boq", "tendering"])
    state = sp.read_state(meta)
    assert state["focus_pack"] == "germany-de"
    assert state["modules"]["boq"] is True and state["modules"]["takeoff"] is False
    assert sp.is_blocked(meta, "takeoff") and not sp.is_blocked(meta, "boq")
    # One click brings one module back without dropping the focus.
    meta, _ = sp.set_module(meta, "takeoff", True)
    assert not sp.is_blocked(meta, "takeoff") and sp.read_state(meta)["focus_pack"] == "germany-de"
    meta = pack_focus.show_all(meta)
    state = sp.read_state(meta)
    assert state["focus_pack"] is None and all(state["modules"].values())


@pytest.mark.asyncio
async def test_http_preview_focus_show_all() -> None:
    service = _Service()
    async with _client(service) as client:
        res = await client.get("/api/v1/solution-packages/focus/germany-de/preview/")
        assert res.status_code == 200
        body = res.json()
        assert "boq" in body["modules"] and body["hidden"] and body["demo_template_ids"]

        pkg = await client.get("/api/v1/solution-packages/focus/package:site_field/preview/")
        assert pkg.status_code == 200 and "daily_diary" in pkg.json()["modules"]

        assert (await client.get("/api/v1/solution-packages/focus/nope/preview/")).status_code == 404

        res = await client.post("/api/v1/solution-packages/focus/germany-de/")
        assert res.status_code == 200
        state = res.json()
        assert state["focus_pack"] == "germany-de" and state["modules"]["takeoff"] is False

        res = await client.post("/api/v1/solution-packages/show-all/")
        assert res.json()["focus_pack"] is None and res.json()["modules"]["takeoff"] is True


@pytest.mark.asyncio
async def test_focus_needs_package_admin() -> None:
    async with _client(_Service(), {"sub": "u", "role": "viewer"}) as client:
        assert (await client.post("/api/v1/solution-packages/focus/germany-de/")).status_code == 403
        assert (await client.post("/api/v1/solution-packages/show-all/")).status_code == 403


def test_first_package_install_records_the_focus() -> None:
    meta, _ = sp.install({}, ["site_field"])
    assert sp.read_state(meta)["focus_pack"] == "package:site_field"
    meta, _ = sp.install(meta, ["trades"])
    assert sp.read_state(meta)["focus_pack"] == "package:site_field"
