# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The comparison, the matrix and the package plan on PostgreSQL: the smaller review findings.

Each test pins one input the review showed going wrong: a catalogue mapping
that collides, an explicit null that was ignored, packages that parent each
other, a double submit, a weight the column would round, an option override
that changed nothing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.delivery_model.errors import DeliveryModelError
from app.modules.delivery_model.service import DeliveryModelService
from tests._pg import isolated_engine
from tests.pg.delivery_fixtures import build_world, call, compare, view
from tests.pg.governance_fixtures import add_project

pytestmark = pytest.mark.asyncio

PACKAGE = {"title": "Works", "kind": "construction", "builds": True, "party": "contractor"}


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


async def _package(w, code: str, **extra):
    return await call(w, "create_package", {"code": code, **PACKAGE, **extra}, w.manager)


async def _refused(awaitable) -> tuple[str, int]:
    with pytest.raises(DeliveryModelError) as exc:
        await awaitable
    return exc.value.code, exc.value.status_code


async def _tenant_catalogue(w, renames: dict[str, str]) -> str:
    """Publish a tenant copy of the shipped catalogue with some forms renamed; return its id."""
    from app.modules.delivery_model.catalogue import CATALOGUE_DIR, DELIVERY_FORMS_KIND
    from app.modules.project_governance.catalogue_store import CatalogueStore

    def new(code: str) -> str:
        return renames.get(code, code)

    body = json.loads((CATALOGUE_DIR / "neutral.json").read_text(encoding="utf-8"))
    for f in body["forms"]:
        f["code"] = new(f["code"])
    for a in body["default_allocations"]:
        a["forms"] = [new(x) for x in a["forms"]]
    for c in body["criteria"]:
        c["scores"] = {new(k): v for k, v in c["scores"].items()}
    for t in body["package_templates"]:
        t["form"] = new(t["form"])
    tenant = str(w.manager)
    async with w.factory() as s:
        store = CatalogueStore(s)
        row = await store.create(
            tenant,
            code=f"forms_{uuid.uuid4().hex[:6]}",
            name="Owner forms",
            based_on_source=None,
            based_on_id=None,
            based_on_version=None,
            actor_id=w.manager,
            kind=DELIVERY_FORMS_KIND,
        )
        await store.update_draft(tenant, row.id, body=body, name=None)
        await store.publish(tenant, row.id, actor_id=w.manager)
        await s.commit()
        return str(row.id)


# ── finding 9: a mapping that puts two options on one form ──────────────────


async def test_two_options_mapped_onto_one_form_are_refused_not_a_server_error(world) -> None:
    w = world
    await compare(w)
    cid = await _tenant_catalogue(w, {"design_build": "db_new", "design_bid_build_single": "dbb_new"})
    kw = {
        "actor_id": w.manager,
        "tenant_id": str(w.manager),
        "catalogue_source": "tenant",
        "catalogue_id": cid,
        "catalogue_version": None,
        "category_mapping": {},
    }
    with pytest.raises(DeliveryModelError) as exc:
        await call(
            w,
            "change_catalogue",
            form_mapping={"design_build": "db_new", "design_bid_build_single": "db_new"},
            **kw,
        )
    assert (exc.value.code, exc.value.status_code) == ("form_mapping_collision", 422)
    assert [v["code"] for v in exc.value.violations] == ["form_mapping_collision"]
    with pytest.raises(DeliveryModelError) as exc:
        await call(
            w,
            "change_catalogue",
            form_mapping={"design_build": "db_new", "design_bid_build_single": "no_such_form"},
            **kw,
        )
    assert (exc.value.code, exc.value.status_code) == ("form_mapping_unknown_target", 422)
    # Nothing moved: the options are where they were, on the catalogue they were on.
    assert sorted(o["form_code"] for o in (await call(w, "comparison"))["options"]) == [
        "design_bid_build_single",
        "design_build",
    ]
    assert (await view(w))["catalogue_id"] == "neutral"


async def test_another_tenants_catalogue_cannot_be_pinned_and_a_stored_pin_keeps_resolving(world) -> None:
    """Finding 20: the id comes from the request, so it is resolved for the caller's tenant only."""
    w = world
    await compare(w)
    cid = await _tenant_catalogue(w, {"design_build": "db_new"})
    kw = {
        "actor_id": w.manager,
        "catalogue_source": "tenant",
        "catalogue_id": cid,
        "catalogue_version": None,
        "form_mapping": {"design_build": "db_new"},
        "category_mapping": {},
    }
    assert await _refused(call(w, "change_catalogue", tenant_id=str(w.outsider), **kw)) == ("unknown_catalogue", 404)
    assert await _refused(call(w, "change_catalogue", tenant_id=None, **kw)) == ("unknown_catalogue", 404)
    assert (await view(w))["catalogue_id"] == "neutral"
    await call(w, "change_catalogue", tenant_id=str(w.manager), **kw)
    # Once pinned, every member of the project reads it, whatever their own tenant is.
    assert (await view(w))["catalogue_id"] == cid
    assert "db_new" in {o["form_code"] for o in (await call(w, "comparison"))["options"]}


# ── finding 10: overrides ───────────────────────────────────────────────────


async def test_an_override_is_validated_and_changes_what_the_rules_read(world) -> None:
    w = world
    assert await _refused(
        call(w, "add_option", "design_build", overrides={"no_such_attribute": True}, notes="", actor_id=w.manager)
    ) == ("override_invalid", 422)
    plain = await call(w, "add_option", "design_bid_build_single", overrides={}, notes="", actor_id=w.manager)
    option = await call(w, "add_option", "design_build", overrides={}, notes="", actor_id=w.manager)
    assert await _refused(
        call(w, "update_option", option.id, {"overrides": {"design_responsibility": "nobody"}}, w.manager)
    ) == ("override_invalid", 422)
    before = {o["form_code"]: o for o in (await call(w, "comparison"))["options"]}
    assert before["design_build"]["customised"] == []
    await call(w, "update_option", option.id, {"overrides": {"design_responsibility": "owner"}}, w.manager)
    after = {o["form_code"]: o for o in (await call(w, "comparison"))["options"]}
    assert after["design_build"]["customised"] == ["design_responsibility"]
    assert after["design_build"]["form"]["design_responsibility"] == "owner"
    assert after["design_bid_build_single"]["customised"] == [] and plain.id is not None


# ── findings 12 and 13: clearing a field, and parents ───────────────────────


async def test_an_explicit_null_clears_a_nullable_field_and_refuses_the_others(world) -> None:
    w = world
    parent = await _package(w, "P1")
    child = await _package(w, "P2", parent_id=parent.id, price_basis="lump_sum")
    assert child.parent_id == parent.id
    cleared = await call(w, "update_package", child.id, {"parent_id": None, "price_basis": None}, w.manager)
    assert (cleared.parent_id, cleared.price_basis) == (None, None)
    assert await _refused(call(w, "update_package", child.id, {"title": None}, w.manager)) == (
        "field_not_nullable",
        422,
    )
    ofi = await call(
        w,
        "create_ofi",
        {"code": "O1", "description": "Pump", "package_id": child.id, "install_by": "package"},
        w.manager,
    )
    assert ofi.package_id == child.id
    detached = await call(w, "update_ofi", ofi.id, {"package_id": None, "install_by": "owner"}, w.manager)
    assert detached.package_id is None
    assert await _refused(call(w, "update_ofi", ofi.id, {"description": None}, w.manager)) == (
        "field_not_nullable",
        422,
    )


async def test_packages_cannot_parent_each_other_at_any_distance(world) -> None:
    w = world
    a = await _package(w, "A")
    b = await _package(w, "B", parent_id=a.id)
    c = await _package(w, "C", parent_id=b.id)
    assert await _refused(call(w, "update_package", a.id, {"parent_id": a.id}, w.manager)) == ("parent_invalid", 422)
    assert await _refused(call(w, "update_package", a.id, {"parent_id": b.id}, w.manager)) == ("parent_invalid", 422)
    assert await _refused(call(w, "update_package", a.id, {"parent_id": c.id}, w.manager)) == ("parent_invalid", 422)
    rows = {p["code"]: p for p in await call(w, "package_views")}
    assert rows["A"]["parent_id"] is None
    # A legal move still works: C directly under A.
    moved = await call(w, "update_package", c.id, {"parent_id": a.id}, w.manager)
    assert moved.parent_id == a.id


# ── finding 14: a double submit ─────────────────────────────────────────────


async def test_a_double_submit_of_a_package_or_an_item_is_a_conflict(world) -> None:
    w = world

    async def attempt(fn, data):
        try:
            await call(w, fn, data, w.manager)
            return "ok"
        except DeliveryModelError as exc:
            return f"{exc.code}:{exc.status_code}"

    package = {"code": "P1", **PACKAGE}
    assert sorted(await asyncio.gather(*(attempt("create_package", package) for _ in range(3)))) == [
        "ok",
        "package_code_exists:409",
        "package_code_exists:409",
    ]
    item = {"code": "O1", "description": "Pump", "install_by": "owner"}
    assert sorted(await asyncio.gather(*(attempt("create_ofi", item) for _ in range(3)))) == [
        "ofi_code_exists:409",
        "ofi_code_exists:409",
        "ok",
    ]


async def test_a_double_submit_of_the_model_itself_is_a_conflict(world) -> None:
    w = world
    async with w.factory() as s:
        project_id = await add_project(s, w.manager, [])
        await s.commit()

    async def attempt():
        try:
            async with w.factory() as s:
                await DeliveryModelService(s).set_model(
                    project_id, actor_id=w.manager, tenant_id=str(w.manager), catalogue_id="neutral"
                )
                await s.commit()
            return "ok"
        except DeliveryModelError as exc:
            return f"{exc.code}:{exc.status_code}"

    assert sorted(await asyncio.gather(*(attempt() for _ in range(4)))) == ["model_exists:409"] * 3 + ["ok"]


# ── finding 15: weights ─────────────────────────────────────────────────────


async def test_a_weight_the_column_would_round_is_refused(world) -> None:
    w = world
    codes = [c["code"] for c in (await call(w, "comparison"))["criteria"]]
    thirds = {codes[0]: "33.33333", codes[1]: "33.33333", codes[2]: "33.33334"}
    assert await _refused(call(w, "patch_weights", thirds, w.manager)) == ("weight_invalid", 422)
    exact = dict.fromkeys(codes, "0") | {codes[0]: "33.3333", codes[1]: "33.3333", codes[2]: "33.3334"}
    await call(w, "patch_weights", exact, w.manager)
    stored = {c["code"]: Decimal(c["weight"]) for c in (await call(w, "comparison"))["criteria"]}
    assert sum(stored.values()) == Decimal("100")
    assert stored[codes[2]] == Decimal("33.3334")


# ── finding 18: the form in use before a proposal, and the caller's locale ──


async def test_before_a_proposal_the_matrix_and_the_plan_use_the_leading_form(world, monkeypatch) -> None:
    from app.modules.delivery_model import messages

    w = world
    await compare(w)
    matrix = await call(w, "allocation_matrix")
    item = next(i for i in matrix["items"] if i["default"] is not None and i["default"]["party"] != "shared")
    default = item["default"]
    row = await call(
        w,
        "put_allocation",
        item["category_code"],
        {"party": default["party"], "basis": default["basis"]},
        w.manager,
    )
    assert row.source == "catalogue_default"
    seen: list[str] = []
    real = messages.translate

    def spy(key: str, *, locale: str = "en", **kw):
        seen.append(locale)
        return real(key, locale=locale, **kw)

    monkeypatch.setattr(messages, "translate", spy)
    created = await call(w, "derive_packages", w.manager, locale="de")
    assert created and set(seen) == {"de"}
    assert (await view(w))["selected_form_code"] is None
