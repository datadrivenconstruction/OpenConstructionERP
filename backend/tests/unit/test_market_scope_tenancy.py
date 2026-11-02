"""Market scope: upgrade path, multi-market tenants, permissions, preview purity, inputs."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import market_scope as ms
from app.core.module_loader import ModuleManifest

_REGISTERED = {"boq_quality", "din276", "gaeb", "nrm", "masterformat", "uk_statutory"}
_BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tagged() -> dict[str, tuple[str, ...]]:
    return ms._scanned_module_markets()


@pytest.fixture(scope="module")
def packs() -> list:
    from app.core.partner_pack.discovery import discover_packs

    return list(discover_packs())


def _scope(profile: dict, tagged, packs, **kw) -> dict:
    return ms.resolve(
        ms.sanitise_profile(profile), markets_by_module=tagged, packs=packs, registered_rule_sets=_REGISTERED, **kw
    )


# Shape of a tenant that last saved settings on 19.0.0: no market_profile key at all.
LEGACY_METADATA = {
    "onboarding": {"company_type": "general_contractor", "completed": True, "country": "DE"},
    "module_preferences": {"takeoff": True, "boq": True, "uk_pack": True, "us_pack": False, "sa_pack": True},
    "solution_packages": {"installed": ["site_field"], "optional": [], "modules": {"takeoff": True}},
    "language": "de",
}


# ── Upgrade from a release without market profiles ──────────────────────────


def test_legacy_tenant_with_no_data_sees_everything(tagged) -> None:
    profile = ms.derive_profile(copy.deepcopy(LEGACY_METADATA), markets_by_module=tagged)
    assert profile["primary"] is None
    scope = ms.resolve(profile, markets_by_module=tagged, packs=[], registered_rule_sets=_REGISTERED)
    assert scope["hidden_modules"] == [] and scope["all_markets"] is True


def test_legacy_tenant_keeps_every_enabled_foreign_module(tagged) -> None:
    profile = ms.derive_profile(
        copy.deepcopy(LEGACY_METADATA), project_countries=["DE", "DE", "DE"], markets_by_module=tagged
    )
    scope = ms.resolve(profile, markets_by_module=tagged, packs=[], registered_rule_sets=_REGISTERED)
    hidden = set(scope["hidden_modules"])
    assert not {"uk_pack", "sa_pack"} & hidden
    assert {"us_pack", "china_pack"} <= hidden
    assert not {"boq", "takeoff"} & hidden


def test_derive_does_not_mutate_metadata_and_is_deterministic(tagged) -> None:
    meta = copy.deepcopy(LEGACY_METADATA)
    a = ms.derive_profile(meta, project_countries=["US", "DE"], markets_by_module=tagged)
    b = ms.derive_profile(meta, project_countries=["DE", "US"], markets_by_module=tagged)
    assert meta == LEGACY_METADATA
    assert a["keep_modules"] == b["keep_modules"]


@pytest.mark.parametrize(
    "meta",
    [None, {}, {"module_preferences": None, "onboarding": "x"}, {"solution_packages": []}, {"solution_packages": None}],
)
def test_derive_with_garbage_metadata_does_not_raise(tagged, meta) -> None:
    ms.derive_profile(meta, project_countries=["", "xx1", "DE"], markets_by_module=tagged)


def test_derived_primary_prefers_applied_pack_country(tagged) -> None:
    profile = ms.derive_profile({}, project_countries=["US"], active_pack_country="DE", markets_by_module=tagged)
    assert profile["primary"]["country"] == "DE"
    assert [m["country"] for m in profile["extra_markets"]] == ["US"]
    cross = ms.derive_profile({}, project_countries=["US"], active_pack_country="XX", markets_by_module=tagged)
    assert cross["primary"]["country"] == "US"


def test_stored_profile_rules() -> None:
    assert ms.stored_profile({ms.PROFILE_KEY: {"primary": {"country": "SA"}}})["primary"]["country"] == "SA"
    assert ms.stored_profile({ms.PROFILE_KEY: {"primary": None}}) is None
    assert ms.stored_profile({ms.PROFILE_KEY: "oops"}) is None
    assert ms.stored_profile(None) is None


def test_profile_without_primary_shows_everything(tagged) -> None:
    scope = _scope({"primary": None}, tagged, [])
    assert scope["all_markets"] is True and scope["hidden_modules"] == []


# ── Multi-market tenants ────────────────────────────────────────────────────


def test_de_plus_sa_union_of_modules(tagged, packs) -> None:
    scope = _scope({"primary": "DE", "extra_markets": ["SA"]}, tagged, packs)
    hidden = set(scope["hidden_modules"])
    assert not {"dach_pack", "middle_east_pack", "einvoice_clearance"} & hidden
    assert {"uk_pack", "us_pack", "china_pack"} <= hidden
    assert scope["units_system"] == "metric"
    assert {"germany-de", "saudi-vision2030"} <= set(scope["packs"])


def test_de_plus_us_is_both_units_and_both_rule_sets(tagged, packs) -> None:
    scope = _scope({"primary": "DE", "extra_markets": ["US"]}, tagged, packs)
    assert scope["units_system"] == "both"
    assert {"din276", "masterformat"} <= set(scope["rule_sets"])
    assert any(c.startswith("AIA") for c in scope["options"]["contract_forms"])


def test_explicit_units_override_market_default(tagged, packs) -> None:
    assert _scope({"primary": "US", "standards": {"units": "metric"}}, tagged, packs)["units_system"] == "metric"


def test_keep_modules_survives_in_scope(tagged, packs) -> None:
    scope = _scope({"primary": "DE", "keep_modules": ["oe_uk_pack"]}, tagged, packs)
    assert "uk_pack" not in scope["hidden_modules"]


def test_project_classification_picks_rule_set(tagged, packs) -> None:
    scope = _scope({"primary": "DE"}, tagged, packs, project_classification=" NRM ")
    assert "nrm" in scope["rule_sets"]
    unknown = _scope({"primary": "DE"}, tagged, packs, project_classification="nope")
    assert "nope" not in unknown["rule_sets"]
    assert unknown["rule_sets"][0] == "boq_quality"


def test_rule_sets_have_no_duplicates(tagged, packs) -> None:
    scope = _scope({"primary": "DE", "extra_markets": ["AT", "CH"]}, tagged, packs, project_classification="din276")
    assert len(scope["rule_sets"]) == len(set(scope["rule_sets"]))


def test_eu_tag_follows_membership(tagged, packs) -> None:
    eu_only = {n.removeprefix("oe_") for n, t in tagged.items() if "EU" in t and "*" not in t}
    if not eu_only:
        pytest.skip("no EU-tagged module")
    assert not eu_only & set(_scope({"primary": "FR"}, tagged, packs)["hidden_modules"])
    outside = {n for n in eu_only if not {"GB", "JP"} & set(tagged["oe_" + n])}
    assert outside <= set(_scope({"primary": "JP"}, tagged, packs)["hidden_modules"])


def test_neutral_modules_are_never_hidden(tagged, packs) -> None:
    for country in ("DE", "SA", "US", "CN", "GB", "JP", "BR"):
        scope = _scope({"primary": country}, tagged, packs)
        for name in scope["hidden_modules"]:
            assert "*" not in tagged["oe_" + name]


# ── Sanitising and large inputs ─────────────────────────────────────────────


def test_sanitise_dedupes_and_caps_field_lengths() -> None:
    profile = ms.sanitise_profile(
        {
            "primary": {"country": "de", "subdivision": "by"},
            "extra_markets": ["DE", "sa", "SA", {"country": "sa", "subdivision": "01"}],
            "company_type": "x" * 500,
            "standards": {"classification": "y" * 500, "units": " IMPERIAL "},
            "keep_modules": ["b", "a", "a", 3, None],
        }
    )
    assert profile["primary"] == {"country": "DE", "subdivision": "BY"}
    assert [m["country"] for m in profile["extra_markets"]] == ["SA", "SA"]
    assert len(profile["company_type"]) == 64
    assert len(profile["standards"]["classification"]) == 64
    assert profile["standards"]["units"] == "imperial"
    assert profile["keep_modules"] == ["a", "b"]


@pytest.mark.parametrize("raw", [None, [], "x", 5])
def test_sanitise_non_dict_inputs(raw) -> None:
    p = ms.sanitise_profile(raw)
    assert p["primary"] is None and p["extra_markets"] == []


def test_non_latin_country_text_is_dropped() -> None:
    arabic = "السعودية"
    p = ms.sanitise_profile({"primary": arabic, "extra_markets": ["РФ", "RU"]})
    assert p["primary"] is None
    assert [m["country"] for m in p["extra_markets"]] == ["RU"]


def test_large_market_list_resolves(tagged, packs) -> None:
    codes = sorted({c for tags in tagged.values() for c in tags if len(c) == 2})
    scope = _scope({"primary": codes[0], "extra_markets": codes[1:]}, tagged, packs)
    assert scope["hidden_modules"] == []


def test_normalise_tags_edge_cases() -> None:
    assert ms.normalise_tags(None) == ("*",)
    assert ms.normalise_tags([]) == ("*",)
    assert ms.normalise_tags(["", "  "]) == ("*",)
    assert ms.normalise_tags(["de", "DE", " at "]) == ("DE", "AT")
    assert ms.is_visible(["DE"], []) is False


def test_manifest_default_markets_is_every_market_and_not_shared() -> None:
    a = ModuleManifest(name="oe_fresh", version="1.0.0", display_name="Fresh")
    b = ModuleManifest(name="oe_fresh2", version="1.0.0", display_name="Fresh")
    assert a.markets == ["*"] and a.markets is not b.markets


# ── HTTP: permissions, tenancy, purity ──────────────────────────────────────


class _Session:
    def __init__(self, project=None, countries=()):
        self.project = project
        self.countries = countries

    async def execute(self, _stmt):
        return iter([(c,) for c in self.countries])

    async def get(self, _model, _pk):
        return self.project


def _http(service, payload=None, session=None):
    import httpx
    from fastapi import FastAPI

    from app.core.market_router import router
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.users.router import _get_service
    from tests.unit.test_solution_packages import USER_ID

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_current_user_payload] = lambda: payload or {"sub": USER_ID, "role": "admin"}
    app.dependency_overrides[_get_service] = lambda: service
    app.dependency_overrides[get_session] = lambda: session or _Session()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _service():
    from tests.unit.test_solution_packages import _Service

    return _Service()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["viewer", "editor", "manager", ""])
async def test_put_forbidden_below_admin(role: str) -> None:
    service = _service()
    async with _http(service, {"sub": "u1", "role": role}) as client:
        res = await client.put("/api/v1/market/", json={"primary": {"country": "DE"}})
        assert res.status_code == 403
        assert res.json()["detail"] == "package_admin_required"
    assert ms.PROFILE_KEY not in service.metadata


@pytest.mark.asyncio
async def test_put_owner_claim_allowed_foreign_tenant_claim_denied() -> None:
    async with _http(_service(), {"sub": "u1", "role": "editor", "tenant_id": "u1"}) as client:
        assert (await client.put("/api/v1/market/", json={"primary": {"country": "DE"}})).status_code == 200
    async with _http(_service(), {"sub": "u2", "role": "editor", "tenant_id": "u1"}) as client:
        assert (await client.put("/api/v1/market/", json={"primary": {"country": "DE"}})).status_code == 403


@pytest.mark.asyncio
async def test_get_open_to_viewer_reports_cannot_edit() -> None:
    async with _http(_service(), {"sub": "u1", "role": "viewer"}) as client:
        res = await client.get("/api/v1/market/")
        assert res.status_code == 200 and res.json()["can_edit"] is False


@pytest.mark.asyncio
async def test_put_validation_errors_save_nothing() -> None:
    service = _service()
    async with _http(service) as client:
        for body in (
            {},
            {"primary": {"country": "DEU"}},
            {"primary": {"country": "D"}},
            {"primary": {"country": "DE"}, "extra_markets": [{"country": "SA"}] * 51},
            {"primary": {"country": "DE"}, "keep_modules": ["m"] * 201},
        ):
            assert (await client.put("/api/v1/market/", json=body)).status_code == 422, body
    assert service.metadata == {}


@pytest.mark.asyncio
async def test_put_keeps_other_metadata_untouched() -> None:
    service = _service()
    service.metadata = copy.deepcopy(LEGACY_METADATA)
    async with _http(service) as client:
        assert (await client.put("/api/v1/market/", json={"primary": {"country": "DE"}})).status_code == 200
    for key, value in LEGACY_METADATA.items():
        assert service.metadata[key] == value
    assert service.metadata[ms.PROFILE_KEY]["primary"]["country"] == "DE"


@pytest.mark.asyncio
async def test_two_tenants_do_not_see_each_others_profile() -> None:
    a, b = _service(), _service()
    async with _http(a) as client_a, _http(b) as client_b:
        await client_a.put("/api/v1/market/", json={"primary": {"country": "SA"}})
        body = (await client_b.get("/api/v1/market/")).json()
        assert body["derived"] is True and body["markets"] != ["SA"]
        assert (await client_a.get("/api/v1/market/")).json()["markets"] == ["SA"]


@pytest.mark.asyncio
async def test_project_scope_follows_platform_access_check(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.core import market_router

    allowed: set[str] = set()

    async def _access(project_id, _user_id, _session):
        if str(project_id) not in allowed:
            raise HTTPException(status_code=404, detail="Project not found")

    monkeypatch.setattr(market_router, "verify_project_access", _access)
    # Owned by someone else: a team member or admin the access check lets through still gets the scope.
    project = SimpleNamespace(owner_id=uuid.uuid4(), country_code="US", classification_standard=None)
    pid = str(uuid.uuid4())
    async with _http(_service(), session=_Session(project=project)) as client:
        assert (await client.get("/api/v1/market/", params={"project_id": pid})).status_code == 404
        allowed.add(pid)
        body = (await client.get("/api/v1/market/", params={"project_id": pid})).json()
        assert body["markets"] == ["US"]


@pytest.mark.asyncio
async def test_get_rejects_malformed_project_id() -> None:
    async with _http(_service()) as client:
        assert (await client.get("/api/v1/market/", params={"project_id": "not-a-uuid"})).status_code == 422


@pytest.mark.asyncio
async def test_preview_saves_nothing_and_needs_no_admin() -> None:
    service = _service()
    service.metadata = copy.deepcopy(LEGACY_METADATA)
    async with _http(service, {"sub": "u1", "role": "viewer"}) as client:
        res = await client.post(
            "/api/v1/market/preview/", json={"primary": {"country": "DE"}, "extra_markets": [{"country": "US"}]}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["markets"] == ["DE", "US"] and "suggested_packages" in body
        assert "can_edit" not in body and "derived" not in body
        assert (await client.post("/api/v1/market/preview/", json={"primary": {"country": "ZZZ"}})).status_code == 422
    assert service.metadata == LEGACY_METADATA


@pytest.mark.asyncio
async def test_preview_unknown_country_suggests_nothing() -> None:
    async with _http(_service()) as client:
        body = (await client.post("/api/v1/market/preview/", json={"primary": {"country": "ZZ"}})).json()
        assert body["suggested_packages"] == []


@pytest.mark.asyncio
async def test_preview_removal_lists_what_disappears() -> None:
    async with _http(_service()) as client:
        both = (
            await client.post(
                "/api/v1/market/preview/", json={"primary": {"country": "DE"}, "extra_markets": [{"country": "SA"}]}
            )
        ).json()
        only = (await client.post("/api/v1/market/preview/", json={"primary": {"country": "DE"}})).json()
    assert set(only["hidden_modules"]) - set(both["hidden_modules"]) >= {"middle_east_pack"}


@pytest.mark.asyncio
async def test_derived_get_uses_project_countries_from_session() -> None:
    async with _http(_service(), session=_Session(countries=("SA", "SA", "DE"))) as client:
        body = (await client.get("/api/v1/market/")).json()
    assert body["markets"] == ["SA", "DE"] and body["derived"] is True


# ── Install ─────────────────────────────────────────────────────────────────


def test_market_profile_needs_no_migration() -> None:
    for path in (_BACKEND / "alembic" / "versions").glob("*.py"):
        assert "market_profile" not in path.read_text(encoding="utf-8"), path.name


def test_single_alembic_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND / "alembic"))
    assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1


# ── Company-wide profile and country data ────────────────────────────────────


class _Users:
    """Per-user metadata store standing in for UserService."""

    def __init__(self) -> None:
        self.by_id: dict[uuid.UUID, dict] = {}

    async def get_user(self, user_id: uuid.UUID) -> SimpleNamespace:
        return SimpleNamespace(metadata_=dict(self.by_id.get(user_id, {})))

    async def update_profile(self, user_id: uuid.UUID, **fields) -> None:
        self.by_id[user_id] = dict(fields["metadata_"])


@pytest.mark.asyncio
async def test_profile_is_company_wide_viewer_reads_admin_profile(monkeypatch) -> None:
    from app.core import market_router
    from tests.unit.test_solution_packages import USER_ID

    holder = uuid.uuid4()

    async def _holder(_session, _payload, _caller):
        return holder

    monkeypatch.setattr(market_router, "company_holder_id", _holder)
    users = _Users()
    async with _http(users) as admin:
        assert (await admin.put("/api/v1/market/", json={"primary": {"country": "SA"}})).status_code == 200
    assert ms.PROFILE_KEY in users.by_id[holder] and uuid.UUID(USER_ID) not in users.by_id
    async with _http(users, {"sub": USER_ID, "role": "viewer"}) as viewer:
        body = (await viewer.get("/api/v1/market/")).json()
    assert body["markets"] == ["SA"] and body["derived"] is False


@pytest.mark.asyncio
async def test_legacy_per_user_profile_moves_to_holder_on_admin_read(monkeypatch) -> None:
    from app.core import market_router
    from tests.unit.test_solution_packages import USER_ID

    holder = uuid.uuid4()

    async def _holder(_session, _payload, _caller):
        return holder

    monkeypatch.setattr(market_router, "company_holder_id", _holder)
    users = _Users()
    users.by_id[uuid.UUID(USER_ID)] = ms.save_profile({}, {"primary": {"country": "DE"}})
    async with _http(users) as client:
        assert (await client.get("/api/v1/market/")).json()["markets"] == ["DE"]
    assert ms.stored_profile(users.by_id[holder])["primary"]["country"] == "DE"


@pytest.mark.asyncio
async def test_holder_prefers_foreign_tenant_claim() -> None:
    from app.core.market_router import company_holder_id

    tenant, caller = uuid.uuid4(), uuid.uuid4()
    got = await company_holder_id(_Session(), {"sub": str(caller), "tenant_id": str(tenant)}, caller)
    assert got == tenant
    assert await company_holder_id(_Session(), {"sub": str(caller)}, caller) == caller


def test_supranational_members_come_from_country_data() -> None:
    import json

    data = json.loads((_BACKEND / "app" / "core" / "country_data" / "supranational_markets.json").read_text("utf-8"))
    assert set(data["markets"]["EU"]) == ms.supranational_markets()["EU"]
    assert "EU" in ms.expand_markets(["AT"]) and "EU" not in ms.expand_markets(["GB"])
    assert not hasattr(ms, "EU_MEMBERS")


def _admin(email, *, active=True, metadata=None, uid=None):
    return (uid or uuid.uuid4(), email, active, metadata or {}, None)


def test_holder_is_newest_saved_profile_even_on_inactive_admin() -> None:
    from app.core.market_router import SAVED_AT_KEY, pick_holder

    old = ms.save_profile({SAVED_AT_KEY: "2026-01-01T00:00:00+00:00"}, {"primary": {"country": "DE"}})
    new = ms.save_profile({SAVED_AT_KEY: "2026-06-01T00:00:00+00:00"}, {"primary": {"country": "SA"}})
    rows = [_admin("a@x.io", metadata=old), _admin("demo@openconstructionerp.com", active=False, metadata=new)]
    assert pick_holder(rows) == rows[1][0]


def test_new_holder_skips_demo_admin() -> None:
    from app.core.market_router import pick_holder

    rows = [_admin("demo@openconstructionerp.com"), _admin("boss@acme.io"), _admin("x@acme.io", active=False)]
    assert pick_holder(rows) == rows[1][0]
    assert pick_holder(rows[:1]) == rows[0][0]
    assert pick_holder([]) is None


@pytest.mark.asyncio
async def test_two_users_of_one_company_get_same_menu(monkeypatch) -> None:
    from app.core import market_router

    holder = uuid.uuid4()

    async def _holder(_session, _payload, _caller):
        return holder

    monkeypatch.setattr(market_router, "company_holder_id", _holder)
    users = _Users()
    session = _Session(countries=("SA", "DE"))
    bodies = []
    for sub in (str(uuid.uuid4()), str(uuid.uuid4())):
        async with _http(users, {"sub": sub, "role": "viewer"}, session) as client:
            bodies.append((await client.get("/api/v1/market/")).json())
    assert bodies[0]["markets"] == bodies[1]["markets"] == ["SA", "DE"]
    assert bodies[0]["hidden_modules"] == bodies[1]["hidden_modules"]


@pytest.mark.asyncio
async def test_put_records_holder_and_clears_every_guard_cache(monkeypatch) -> None:
    from app.core import market_router, module_guard
    from tests.unit.test_solution_packages import USER_ID

    holder = uuid.uuid4()

    async def _holder(_session, _payload, _caller):
        return holder

    monkeypatch.setattr(market_router, "company_holder_id", _holder)
    module_guard._cache["someone-else"] = (0.0, None)
    users = _Users()
    async with _http(users) as client:
        assert (await client.put("/api/v1/market/", json={"primary": {"country": "DE"}})).status_code == 200
    assert "someone-else" not in module_guard._cache
    saved = users.by_id[holder]
    assert saved[market_router.SAVED_BY_KEY] == USER_ID and saved[market_router.SAVED_AT_KEY]
