"""Packs-umbrella rename: pack type inference + backward-compat aliases.

Covers the contract that external packs and existing installs depend on:
  * old manifests with no ``pack_type`` still load and infer a sensible type;
  * ``OE_PARTNER_PACK`` still selects a pack (env alias path), and ``OE_PACK``
    wins when both are set;
  * an existing ``partner_pack_state.json`` still resolves the active pack
    (state-file dual read);
  * the old ``/api/v1/partner-pack/*`` route and the new ``/api/v1/packs/*``
    alias return the same data.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.partner_pack import state as pack_state
from app.core.partner_pack.discovery import get_active_pack, reset_cache
from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest
from app.core.partner_pack.router import alias_router, router


class FakeEP:
    """Minimal entry-point stub the discovery loader accepts."""

    def __init__(self, name: str, manifest: PartnerPackManifest) -> None:
        self.name = name
        self.value = f"openconstructionerp_{name.replace('-', '_')}:MANIFEST"
        self._manifest = manifest

    def load(self) -> PartnerPackManifest:
        return self._manifest


@pytest.fixture(autouse=True)
def _isolate_pack_discovery_cache() -> Iterator[None]:
    """Reset the memoized pack discovery around every test in this module.

    Several tests patch ``discovery.entry_points`` to inject a fake pack and then
    hit routes that call the lru_cached ``discover_packs``. Without a teardown
    reset the fake pack stays cached after the patch is removed and leaks into
    unrelated tests (e.g. the demo-project mapping checks), so reset on both ends.
    """
    reset_cache()
    yield
    reset_cache()


class TestPackTypeInference:
    def test_old_country_manifest_infers_country(self) -> None:
        """A pre-umbrella manifest with country metadata loads as 'country'."""
        m = PartnerPackManifest(
            slug="batimatech-ca",
            partner_name="Batimatech",
            branding=PartnerBranding(powered_by_text="Powered by ... Batimatech"),
            metadata={"country": "CA", "country_name_en": "Canada"},
        )
        # No pack_type authored -> still valid, and resolves to country
        # (country metadata beats the partner co-branding signal).
        assert m.type == "country"
        assert m.to_public_dict()["type"] == "country"

    def test_cross_region_xx_infers_industry(self) -> None:
        m = PartnerPackManifest(
            slug="renewables-epc",
            partner_name="Renewables EPC",
            metadata={"country": "XX", "country_name_en": "Cross-region (Renewables EPC)"},
        )
        assert m.type == "industry"

    def test_industry_metadata_infers_industry(self) -> None:
        m = PartnerPackManifest(
            slug="doker-formwork",
            partner_name="Doka Formwork",
            metadata={"industry": "formwork"},
        )
        assert m.type == "industry"

    def test_partner_branding_only_infers_partner(self) -> None:
        m = PartnerPackManifest(
            slug="acme-partner",
            partner_name="Acme",
            branding=PartnerBranding(powered_by_text="In partnership with Acme"),
        )
        assert m.type == "partner"

    def test_bare_manifest_defaults_to_partner(self) -> None:
        m = PartnerPackManifest(slug="bare-pack", partner_name="Bare")
        assert m.type == "partner"

    def test_explicit_type_is_respected(self) -> None:
        m = PartnerPackManifest(
            slug="show-case",
            partner_name="Demo",
            pack_type="showcase",
            metadata={"country": "DE"},  # would infer 'country' if left blank
        )
        assert m.type == "showcase"


class TestEnvAlias:
    def test_old_env_var_still_selects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_cache()
        m = PartnerPackManifest(slug="legacy-pack", partner_name="Legacy")
        monkeypatch.delenv("OE_PACK", raising=False)
        monkeypatch.setenv("OE_PARTNER_PACK", "legacy-pack")
        with (
            patch("app.core.partner_pack.discovery.entry_points", return_value=[FakeEP("legacy-pack", m)]),
            patch("app.core.partner_pack.discovery._discover_filesystem_packs", return_value=[]),
        ):
            active = get_active_pack()
            assert active is not None
            assert active.slug == "legacy-pack"

    def test_new_env_var_wins_over_old(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_cache()
        a = PartnerPackManifest(slug="pack-a", partner_name="Pack A")
        b = PartnerPackManifest(slug="pack-b", partner_name="Pack B")
        monkeypatch.setenv("OE_PARTNER_PACK", "pack-a")
        monkeypatch.setenv("OE_PACK", "pack-b")
        with (
            patch(
                "app.core.partner_pack.discovery.entry_points",
                return_value=[FakeEP("pack-a", a), FakeEP("pack-b", b)],
            ),
            patch("app.core.partner_pack.discovery._discover_filesystem_packs", return_value=[]),
        ):
            active = get_active_pack()
            assert active is not None
            assert active.slug == "pack-b"


class TestStateFileDualRead:
    def test_legacy_state_file_resolves(self, tmp_path: Path) -> None:
        """An existing partner_pack_state.json (legacy name) still loads."""
        legacy = tmp_path / pack_state.STATE_FILENAME_LEGACY
        legacy.write_text(
            json.dumps({"slug": "kept-pack", "pack_version": "1.0.0"}),
            encoding="utf-8",
        )
        loaded = pack_state.load_applied_state(data_dir=tmp_path)
        assert loaded is not None
        assert loaded.slug == "kept-pack"
        assert pack_state.get_applied_slug(tmp_path) == "kept-pack"

    def test_new_state_file_wins_over_legacy(self, tmp_path: Path) -> None:
        (tmp_path / pack_state.STATE_FILENAME_LEGACY).write_text(json.dumps({"slug": "old-slug"}), encoding="utf-8")
        (tmp_path / pack_state.STATE_FILENAME).write_text(json.dumps({"slug": "new-slug"}), encoding="utf-8")
        loaded = pack_state.load_applied_state(data_dir=tmp_path)
        assert loaded is not None
        assert loaded.slug == "new-slug"

    def test_save_writes_new_name_then_clear_removes_both(self, tmp_path: Path) -> None:
        # Pre-existing legacy file plus a fresh save under the new name.
        (tmp_path / pack_state.STATE_FILENAME_LEGACY).write_text(json.dumps({"slug": "legacy"}), encoding="utf-8")
        pack_state.save_applied_state(
            pack_state.AppliedPackState(slug="written", pack_version="2.0.0"),
            data_dir=tmp_path,
        )
        assert (tmp_path / pack_state.STATE_FILENAME).exists()
        # Clear must wipe BOTH so the legacy record cannot resurrect the pack.
        pack_state.clear_applied_state(data_dir=tmp_path)
        assert not (tmp_path / pack_state.STATE_FILENAME).exists()
        assert not (tmp_path / pack_state.STATE_FILENAME_LEGACY).exists()
        assert pack_state.load_applied_state(data_dir=tmp_path) is None


class TestRouteAlias:
    @pytest.fixture
    def client(self) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.include_router(alias_router)
        return TestClient(app)

    def test_old_and_new_routes_return_same_data(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_cache()
        m = PartnerPackManifest(
            slug="alias-pack",
            partner_name="Alias Co",
            metadata={"country": "DE", "country_name_en": "Germany"},
        )
        monkeypatch.delenv("OE_PACK", raising=False)
        monkeypatch.setenv("OE_PARTNER_PACK", "alias-pack")
        with (
            patch("app.core.partner_pack.discovery.entry_points", return_value=[FakeEP("alias-pack", m)]),
            patch("app.core.partner_pack.discovery._discover_filesystem_packs", return_value=[]),
        ):
            old = client.get("/api/v1/partner-pack/current")
            new = client.get("/api/v1/packs/current")
            assert old.status_code == 200
            assert new.status_code == 200
            assert old.json() == new.json()
            assert new.json()["manifest"]["type"] == "country"

            old_installed = client.get("/api/v1/partner-pack/installed")
            new_installed = client.get("/api/v1/packs/installed")
            assert old_installed.json() == new_installed.json()
