"""Market scope: a German tenant sees no UK/US/SA rows, a Saudi one sees GCC, a US one sees AIA."""

from __future__ import annotations

import importlib
import uuid

import pytest

from app.core import market_scope as ms
from app.core.regional_packs import PACK_CONFIG_MODULES, pack_configs

_REGISTERED = {"boq_quality", "din276", "gaeb", "nrm", "masterformat", "uk_statutory"}


@pytest.fixture(scope="module")
def tagged() -> dict[str, tuple[str, ...]]:
    return ms._scanned_module_markets()


@pytest.fixture(scope="module")
def packs() -> list:
    from app.core.partner_pack.discovery import discover_packs

    return list(discover_packs())


def _tenant(country: str, tagged, packs) -> dict:
    profile = ms.sanitise_profile({"primary": {"country": country}})
    return ms.resolve(profile, markets_by_module=tagged, packs=packs, registered_rule_sets=_REGISTERED)


def test_german_tenant_sees_no_uk_us_or_saudi_rows(tagged, packs) -> None:
    scope = _tenant("DE", tagged, packs)
    hidden = set(scope["hidden_modules"])
    for foreign in ("uk_pack", "us_pack", "us_ca_pack", "us_tx_pack", "middle_east_pack", "sa_pack", "china_pack"):
        assert foreign in hidden
    assert "dach_pack" not in hidden
    # German regimes live in these, so they stay.
    for own in ("einvoice_clearance", "payment_clock", "tax_withholding"):
        assert own not in hidden
    assert "germany-de" in scope["packs"]
    assert not {"uk-jct", "us-texas", "us-california", "saudi-vision2030", "uae-ae"} & set(scope["packs"])
    assert scope["units_system"] == "metric"
    assert scope["rule_sets"][:3] == ["boq_quality", "din276", "gaeb"]
    assert "nrm" not in scope["rule_sets"] and "masterformat" not in scope["rule_sets"]
    assert not any(code.startswith("AIA") for code in scope["options"]["contract_forms"])


def test_saudi_tenant_sees_gcc(tagged, packs) -> None:
    scope = _tenant("SA", tagged, packs)
    hidden = set(scope["hidden_modules"])
    assert "middle_east_pack" not in hidden
    assert "einvoice_clearance" not in hidden  # ZATCA
    assert {"dach_pack", "uk_pack", "us_pack", "sa_pack", "tax_withholding"} <= hidden
    assert "saudi-vision2030" in scope["packs"]
    assert "germany-de" not in scope["packs"]
    assert any(code.startswith("FIDIC") for code in scope["options"]["contract_forms"])


def test_us_tenant_sees_aia_and_imperial(tagged, packs) -> None:
    scope = _tenant("US", tagged, packs)
    hidden = set(scope["hidden_modules"])
    assert {"us_pack", "us_ca_pack", "us_tx_pack", "tax_withholding"}.isdisjoint(hidden)
    assert {"dach_pack", "uk_pack", "middle_east_pack"} <= hidden
    assert any(code.startswith("AIA") for code in scope["options"]["contract_forms"])
    assert scope["units_system"] == "imperial"
    assert "masterformat" in scope["rule_sets"] and "din276" not in scope["rule_sets"]


def test_no_profile_and_no_data_shows_everything(tagged) -> None:
    profile = ms.derive_profile({}, markets_by_module=tagged)
    scope = ms.resolve(profile, markets_by_module=tagged, packs=[], registered_rule_sets=_REGISTERED)
    assert scope["all_markets"] is True
    assert scope["hidden_modules"] == []
    assert scope["units_system"] == "both"


def test_existing_tenant_keeps_what_it_uses(tagged) -> None:
    metadata = {"module_preferences": {"uk_pack": True}, "onboarding": {"company_type": "general_contractor"}}
    profile = ms.derive_profile(metadata, project_countries=["DE", "DE", "US"], markets_by_module=tagged)
    assert profile["primary"]["country"] == "DE"
    assert [m["country"] for m in profile["extra_markets"]] == ["US"]
    assert profile["company_type"] == "general_contractor"
    assert profile["keep_modules"] == ["oe_uk_pack"]
    scope = ms.resolve(profile, markets_by_module=tagged, packs=[], registered_rule_sets=_REGISTERED)
    assert "uk_pack" not in scope["hidden_modules"]
    assert "us_pack" not in scope["hidden_modules"]
    assert "middle_east_pack" in scope["hidden_modules"]


def test_project_country_narrows_scope(tagged) -> None:
    profile = ms.sanitise_profile({"primary": "DE", "extra_markets": ["US"]})
    scope = ms.resolve(
        profile, project_country="us", markets_by_module=tagged, packs=[], registered_rule_sets=_REGISTERED
    )
    assert scope["markets"] == ["US"]
    assert "dach_pack" in scope["hidden_modules"]


def test_eu_tag_covers_member_states() -> None:
    assert ms.is_visible(["EU"], ["AT"])
    assert not ms.is_visible(["EU"], ["GB"])
    assert ms.is_visible(["*"], ["GB"])
    assert ms.is_visible(["GB"], ["*"])


def test_sanitise_drops_garbage() -> None:
    profile = ms.sanitise_profile(
        {"primary": {"country": "Germany"}, "extra_markets": ["de", "zz9", 5], "standards": {"units": "cubits"}}
    )
    assert profile["primary"] is None
    assert profile["extra_markets"] == [{"country": "DE", "subdivision": ""}]
    assert profile["standards"]["units"] == ""


def test_every_regional_pack_module_is_tagged_with_its_countries(tagged) -> None:
    for module_path, config in zip(PACK_CONFIG_MODULES, pack_configs(), strict=True):
        name = "oe_" + module_path.split(".")[2]
        assert set(tagged[name]) == {c.upper() for c in config["countries"]}, name


@pytest.mark.parametrize(
    ("module", "countries"),
    [
        ("tax_withholding", "app.modules.tax_withholding.data"),
        ("einvoice_clearance", "app.modules.einvoice_clearance.regimes"),
        ("payment_clock", "app.modules.payment_clock.data"),
    ],
)
def test_country_modules_cover_their_own_data(tagged, module: str, countries: str) -> None:
    data = importlib.import_module(countries)
    if module == "tax_withholding":
        codes = {r["country_code"] for r in data.WITHHOLDING_REGIMES}
    elif module == "einvoice_clearance":
        codes = set(data.SUPPORTED_COUNTRIES)
    else:
        codes = {r["country_code"] for r in data.PAYMENT_REGIMES}
    assert codes <= set(tagged[f"oe_{module}"])


def test_manifest_markets_are_iso_codes(tagged) -> None:
    for name, tags in tagged.items():
        for tag in tags:
            assert tag == "*" or (len(tag) == 2 and tag.isalpha() and tag.isupper()), (name, tag)


class _Session:
    async def execute(self, _stmt):
        return iter([("DE",), (None,)])

    async def get(self, _model, _pk):
        return None


def _http(service, payload=None):
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
    app.dependency_overrides[get_session] = lambda: _Session()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_http_get_derives_then_put_saves() -> None:
    from tests.unit.test_solution_packages import _Service

    service = _Service()
    async with _http(service) as client:
        body = (await client.get("/api/v1/market/")).json()
        assert body["derived"] is True and body["markets"] == ["DE"] and body["can_edit"] is True
        assert "uk_pack" in body["hidden_modules"]

        res = await client.put("/api/v1/market/", json={"primary": {"country": "SA"}, "standards": {"units": "metric"}})
        assert res.status_code == 200
        body = res.json()
        assert body["derived"] is False and body["markets"] == ["SA"]
        assert "middle_east_pack" not in body["hidden_modules"]
        assert service.metadata[ms.PROFILE_KEY]["primary"]["country"] == "SA"

        assert (await client.get("/api/v1/market/", params={"project_id": str(uuid.uuid4())})).status_code == 404


@pytest.mark.asyncio
async def test_http_put_needs_admin() -> None:
    from tests.unit.test_solution_packages import _Service

    async with _http(_Service(), {"sub": "u", "role": "viewer"}) as client:
        assert (await client.put("/api/v1/market/", json={"primary": {"country": "DE"}})).status_code == 403
        assert (await client.get("/api/v1/market/")).json()["can_edit"] is False


@pytest.mark.asyncio
async def test_http_preview_does_not_save() -> None:
    from tests.unit.test_solution_packages import _Service

    service = _Service()
    async with _http(service) as client:
        body = (await client.post("/api/v1/market/preview/", json={"primary": {"country": "SA"}})).json()
        assert "middle_east_pack" not in body["hidden_modules"]
        assert "real_estate_gcc" in body["suggested_packages"]
        assert ms.PROFILE_KEY not in service.metadata


def test_einvoice_module_is_keyed_without_prefix_and_hidden_for_a_non_mandate_market(tagged, packs) -> None:
    # The frontend gate reads these exact unprefixed keys.
    de = _tenant("DE", tagged, packs)
    assert "DE" in de["module_markets"]["einvoice_clearance"]
    assert "oe_einvoice_clearance" not in de["module_markets"]
    us = _tenant("US", tagged, packs)
    assert "einvoice_clearance" in us["hidden_modules"]
    assert "oe_einvoice_clearance" not in us["hidden_modules"]
