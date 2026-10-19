# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A country pack install says what it did, what it did not, and what was there already.

The product promise is "pick your country, press Install, everything is set
up". Each test here pins one place where the install or its preview said
something that was not true:

* a cost base that could not be downloaded (no internet) left the workspace
  with no prices, and the batch install still answered ``ok``;
* the Canadian cost base was offered with no size, because the loader and the
  base registry know it by two different names;
* the preview listed the pack's tax template as if applying the pack installed
  tax, while VAT, holidays, e-invoicing and payment terms come from the core
  by project country;
* our own country packs printed "In partnership with Germany Construction
  Pack", a partnership that does not exist;
* the California pack installed an office building in Denver, and the Texas
  pack padded its install with the same Denver office.

No database is needed: the loaders are stubbed and the session factory is a
stand-in that only has to open, commit and close.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from app.core.partner_pack import full_install as fi
from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKS_DIR = REPO_ROOT / "packs"
PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"


class _Session:
    async def commit(self) -> None:
        return None


class _SessionCtx:
    async def __aenter__(self) -> _Session:
        return _Session()

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _manifest(regions: list[str]) -> PartnerPackManifest:
    return PartnerPackManifest(
        slug="offline-test-pack",
        partner_name="Offline Test Pack",
        default_locale="de",
        default_currency="EUR",
        cwicr_regions=regions,
        metadata={"country": "DE"},
    )


def _offline(monkeypatch: pytest.MonkeyPatch, manifest: PartnerPackManifest) -> None:
    """No network: every cost base answers the loader's 'not found and download failed' 404."""
    monkeypatch.setattr(
        "app.core.partner_pack.discovery.get_pack_by_slug",
        lambda slug: manifest if slug == manifest.slug else None,
    )
    monkeypatch.setattr("app.database.async_session_factory", lambda: _SessionCtx())

    async def _no_network(db_id: str, _session: Any, **_kwargs: Any) -> dict[str, Any]:
        raise HTTPException(status_code=404, detail=f"GitHub download failed for {db_id}")

    monkeypatch.setattr("app.modules.costs.router.load_cwicr_region", _no_network)


# ── Gap: a cost base that did not download ──────────────────────────────────


async def test_an_offline_cost_step_says_the_workspace_has_no_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest(["cwicr-de-berlin"])
    _offline(monkeypatch, manifest)

    result, loaded, _resources = await fi._step_cost_db_detailed(manifest.slug)

    assert loaded == []
    assert result.status == "error"
    assert result.detail["prices_loaded"] is False
    assert result.detail["reason_code"] == "cost_base_not_loaded"
    (base,) = result.detail["bases"]
    assert base["status"] == "error"
    assert base["reason_code"] == "download_failed", "an offline install must read as a failed download"


async def test_a_cost_base_that_breaks_on_import_is_not_called_a_download(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest(["cwicr-de-berlin"])
    _offline(monkeypatch, manifest)

    async def _broken(db_id: str, _session: Any, **_kwargs: Any) -> dict[str, Any]:
        raise HTTPException(status_code=500, detail="import failed")

    monkeypatch.setattr("app.modules.costs.router.load_cwicr_region", _broken)
    result, _loaded, _resources = await fi._step_cost_db_detailed(manifest.slug)
    assert result.detail["bases"][0]["reason_code"] == "load_failed"


async def test_the_batch_install_is_not_ok_when_the_cost_base_did_not_load(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest(["cwicr-de-berlin"])
    _offline(monkeypatch, manifest)

    async def _apply(*_a: Any, **_k: Any) -> fi.StepResult:
        return fi.StepResult(step="apply_pack", status="ok")

    async def _demos(*_a: Any, **_k: Any) -> fi.StepResult:
        return fi.StepResult(step="demos", status="ok", detail={"installed": ["residential-berlin"]})

    monkeypatch.setattr(fi, "_step_apply_pack", _apply)
    monkeypatch.setattr(fi, "_step_demos", _demos)

    response = await fi.full_install(fi.FullInstallRequest(slug=manifest.slug, vectorize=False))

    cost = next(s for s in response.steps if s.step == "cost_db")
    assert cost.status == "error"
    assert cost.detail["prices_loaded"] is False
    assert response.ok is False, "a workspace with no prices was reported as a successful install"


async def test_the_stream_install_is_not_ok_when_the_cost_base_did_not_load(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    manifest = _manifest(["cwicr-de-berlin"])
    _offline(monkeypatch, manifest)

    async def _apply(*_a: Any, **_k: Any) -> fi.StepResult:
        return fi.StepResult(step="apply_pack", status="ok")

    monkeypatch.setattr(fi, "_step_apply_pack", _apply)
    monkeypatch.setattr(fi, "_demo_install_list", lambda _slug, _count: [])

    frames = [
        f
        async for f in fi.full_install_stream(fi.FullInstallRequest(slug=manifest.slug, vectorize=False, demo_count=0))
    ]
    done = next(json.loads(f.split("data: ", 1)[1]) for f in frames if f.startswith("event: done"))
    assert done["ok"] is False
    cost = next(s for s in done["steps"] if s["step"] == "cost_db")
    assert cost["detail"]["reason_code"] == "cost_base_not_loaded"


# ── Gap: the Canadian base had no size ──────────────────────────────────────


def test_the_canadian_cost_base_is_offered_with_its_size_and_currency() -> None:
    (entry,) = fi.describe_cost_bases(["cwicr-eng-toronto"])
    assert entry["loadable"] is True
    assert entry["db_id"] == "CA_TORONTO"
    # Measured by the cost-bases lane: CA_TORONTO imports 55,719 items.
    assert entry["positions"] == 55719
    assert entry["currency"] == "CAD"
    assert entry["market"]


def test_every_loadable_base_a_shipped_pack_names_has_a_size() -> None:
    from app.core.partner_pack.discovery import discover_packs

    unsized = {}
    for pack in discover_packs():
        for entry in fi.describe_cost_bases(list(pack.cwicr_regions or [])):
            if entry["loadable"] and not entry["positions"]:
                unsized.setdefault(pack.slug, []).append(entry["db_id"])
    assert not unsized, f"cost bases offered with no size: {unsized}"


# ── Gap: tax, holidays, e-invoicing and payment terms are built in ──────────


def test_the_built_in_country_facts_come_from_the_core_registries() -> None:
    from app.core.partner_pack.country_builtins import country_builtins

    facts = country_builtins("DE", today=date(2026, 10, 19))
    assert facts is not None
    assert facts["country"] == "DE"
    assert facts["vat"] == {"standard": "19", "reduced": "7", "zero": "0"}
    assert facts["holidays"] == {"year": 2026, "count": 9}
    assert facts["einvoice"]["platform"]
    codes = {row["code"] for row in facts["payment_terms"]}
    assert "de_vob_b_abschlag" in codes


def test_a_pack_with_no_single_market_has_no_built_in_country_facts() -> None:
    from app.core.partner_pack.country_builtins import country_builtins

    assert country_builtins(None) is None
    assert country_builtins("XX") is not None  # a well-formed code still answers row by row
    assert country_builtins("not-a-code") is None


def test_the_preview_says_tax_is_built_in_rather_than_installed() -> None:
    from app.core.partner_pack.apply import build_preview
    from app.core.validation.rules import register_builtin_rules

    register_builtin_rules()
    plan = build_preview("germany-de")["plan"]
    built_in = plan["built_in_for_country"]
    assert built_in["country"] == "DE"
    assert built_in["vat"]["standard"] == "19"
    joined = " ".join(plan["warnings"])
    assert "recorded for reference" not in joined
    assert "built into the platform for DE" in joined


# ── Gap: partner credit on our own packs ────────────────────────────────────


def _license_section(readme: Path) -> str:
    text = readme.read_text(encoding="utf-8")
    m = re.search(r"^## License\s*$(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def _force_included_slugs() -> set[str]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    slugs = set()
    for source in force_include:
        parts = Path(source).as_posix().split("/")
        if len(parts) >= 3 and parts[0] == ".." and parts[1] == "packs":
            slugs.add(parts[2])
    return slugs


def test_a_country_pack_without_its_own_line_claims_no_partnership() -> None:
    m = PartnerPackManifest(slug="some-country", partner_name="Somewhere Construction Pack", metadata={"country": "DE"})
    assert m.type == "country"
    assert m.effective_powered_by == "Powered by OpenConstructionERP"


def test_a_partner_pack_still_gets_its_partnership_line() -> None:
    m = PartnerPackManifest(slug="some-partner", partner_name="Acme Builders", pack_type="partner")
    assert m.effective_powered_by == "Powered by OpenConstructionERP · In partnership with Acme Builders"
    explicit = PartnerPackManifest(
        slug="explicit",
        partner_name="Xyz Partner",
        metadata={"country": "CA"},
        branding=PartnerBranding(powered_by_text="Powered by OpenConstructionERP, in partnership with Xyz Partner"),
    )
    assert explicit.effective_powered_by.endswith("in partnership with Xyz Partner")


def test_only_packs_under_a_partnership_agreement_show_a_partner_credit() -> None:
    """The README License section decides partner-ness, not the manifest's own claim."""
    from app.core.partner_pack.discovery import discover_packs

    shipped = _force_included_slugs()
    by_slug = {p.slug: p for p in discover_packs()}
    checked = 0
    wrong = []
    for slug in sorted(shipped):
        readme = PACKS_DIR / slug / "README.md"
        pack = by_slug.get(slug)
        if pack is None or not readme.is_file():
            continue
        checked += 1
        under_agreement = "partnership agreement" in _license_section(readme).lower()
        claims = "partnership" in pack.effective_powered_by.lower()
        if claims and not under_agreement:
            wrong.append(f"{slug}: {pack.effective_powered_by!r}")
    print(f"\nPOPULATION: {checked} shipped packs with a README checked")
    assert checked >= 30, f"only {checked} shipped packs were checked, the reader is looking at the wrong tree"
    assert not wrong, f"our own packs claim a partnership: {wrong}"


# ── Gap: wrong data in the state packs ──────────────────────────────────────────


@pytest.mark.parametrize(("slug", "state"), [("us-california", "US-CA"), ("us-texas", "US-TX")])
def test_a_state_pack_installs_only_projects_located_in_its_state(slug: str, state: str) -> None:
    from app.core.demo_projects import DEMO_TEMPLATES

    install = fi._demo_install_list(slug, 2)
    assert install, f"{slug} installs no demo"
    assert "commercial-denver" not in install, f"{slug} still installs the Denver office"
    flagship = DEMO_TEMPLATES[install[0]]
    if slug == "us-california":
        assert flagship.subdivision_code == state
        assert (flagship.address or {}).get("postcode", "").startswith("CA ")


def test_the_california_demo_is_in_california_and_validates_as_masterformat() -> None:
    from app.core.demo_projects import DEMO_TEMPLATES, PACK_DEMO_PROJECT

    demo_id = PACK_DEMO_PROJECT["us-california"]
    template = DEMO_TEMPLATES[demo_id]
    assert template.address["city"] == "Sacramento"
    assert template.subdivision_code == "US-CA"
    assert template.currency == "USD"
    assert template.classification_standard == "masterformat"
    text = " ".join([template.project_name, template.project_description, str(template.project_metadata)])
    assert "Denver" not in text and "Colorado" not in text


# ── A rule set that arrives with a module the pack switches on ─────────────────
#
# The eleven-areas pack names fifteen rule sets, and each one is registered by
# the on_startup of a module the same pack switches on. On a fresh install every
# module loads, so the preview resolves them all (the "Pack installs" CI lane
# installs the pack on a fresh database). But an admin who had switched one of
# those modules off got a 409 from the preview and from the apply, which is the
# very action that would switch the module back on. A name nothing registers is
# still refused while every module the pack needs is loaded.


def _governance_pack() -> PartnerPackManifest:
    return PartnerPackManifest(
        slug="pending-module-pack",
        partner_name="Pending Module Pack",
        default_locale="de",
        default_currency="EUR",
        validation_rule_sets=["boq_quality", "project_governance"],
        default_modules=["oe_project_governance"],
    )


def _registry(monkeypatch: pytest.MonkeyPatch, known: set[str], unloaded: list[str]) -> None:
    import app.core.partner_pack.apply as apply_module

    monkeypatch.setattr(apply_module, "_known_rule_sets", lambda: set(known))
    monkeypatch.setattr(apply_module, "_module_exists", lambda _name: True)
    monkeypatch.setattr(apply_module, "_unloaded_modules", lambda names: [n for n in names if n in unloaded])


def test_a_rule_set_whose_module_the_pack_switches_on_is_pending_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.partner_pack.apply as apply_module

    _registry(monkeypatch, {"boq_quality"}, ["oe_project_governance"])
    plan = apply_module._plan(_governance_pack())

    assert plan["rule_sets_enabled"] == ["boq_quality"]
    assert plan["rule_sets_pending_modules"] == ["project_governance"]
    assert any("oe_project_governance" in w and "project_governance" in w for w in plan["warnings"])


def test_a_rule_set_nothing_registers_is_still_refused_when_every_module_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.core.partner_pack.apply as apply_module

    _registry(monkeypatch, {"boq_quality"}, [])
    with pytest.raises(apply_module.UnknownRuleSetError):
        apply_module._plan(_governance_pack())


async def test_the_apply_switches_the_module_on_and_then_runs_its_rule_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.partner_pack.apply as apply_module

    known = {"boq_quality"}
    unloaded = ["oe_project_governance"]
    monkeypatch.setattr(apply_module, "_known_rule_sets", lambda: set(known))
    monkeypatch.setattr(apply_module, "_module_exists", lambda _name: True)
    monkeypatch.setattr(apply_module, "_unloaded_modules", lambda names: [n for n in names if n in unloaded])
    monkeypatch.setattr(apply_module, "get_pack_by_slug", lambda _slug: _governance_pack())
    saved: list[Any] = []
    monkeypatch.setattr(apply_module, "save_applied_state", saved.append)
    monkeypatch.setattr(apply_module, "reset_cache", lambda: None)

    async def enable(name: str, _app: object) -> dict[str, str]:
        # What the real loader does: on_startup registers the module's rule set.
        unloaded.remove(name)
        known.add("project_governance")
        return {"name": name, "status": "enabled"}

    monkeypatch.setattr(apply_module.module_loader, "enable_module", enable)
    result = await apply_module.apply_pack("pending-module-pack", install_demo=False, app=object())  # type: ignore[arg-type]

    assert result["applied"] is True
    assert result["plan"]["rule_sets_enabled"] == ["boq_quality", "project_governance"]
    assert result["plan"]["rule_sets_pending_modules"] == []
    assert len(saved) == 1


async def test_the_apply_refuses_when_the_module_came_up_without_the_rule_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.partner_pack.apply as apply_module

    unloaded = ["oe_project_governance"]
    monkeypatch.setattr(apply_module, "_known_rule_sets", lambda: {"boq_quality"})
    monkeypatch.setattr(apply_module, "_module_exists", lambda _name: True)
    monkeypatch.setattr(apply_module, "_unloaded_modules", lambda names: [n for n in names if n in unloaded])
    monkeypatch.setattr(apply_module, "get_pack_by_slug", lambda _slug: _governance_pack())
    saved: list[Any] = []
    monkeypatch.setattr(apply_module, "save_applied_state", saved.append)

    async def enable(name: str, _app: object) -> dict[str, str]:
        unloaded.remove(name)
        return {"name": name, "status": "enabled"}

    monkeypatch.setattr(apply_module.module_loader, "enable_module", enable)
    with pytest.raises(apply_module.UnknownRuleSetError):
        await apply_module.apply_pack("pending-module-pack", install_demo=False, app=object())  # type: ignore[arg-type]
    assert saved == [], "a pack whose rule set never arrived must not be recorded as applied"


def test_the_preview_of_a_pack_with_no_vat_row_does_not_claim_tax_is_built_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The core tax table has no row for some pack countries yet (France, for one)."""
    import app.core.partner_pack.apply as apply_module
    import app.core.partner_pack.country_builtins as cb

    monkeypatch.setattr(cb, "_vat", lambda _country: None)
    m = PartnerPackManifest(
        slug="no-vat-row-pack",
        partner_name="No VAT Row Pack",
        default_locale="fr",
        default_currency="EUR",
        metadata={"country": "FR"},
    )
    plan = apply_module._plan(m)
    assert plan["built_in_for_country"]["vat"] is None
    text = " ".join(plan["warnings"])
    assert "Tax, public holidays" not in text
    assert "no VAT rates for FR" in text
