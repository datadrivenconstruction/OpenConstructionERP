"""Unit tests for the partner-pack core (manifest + discovery + router)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.partner_pack.discovery import (
    discover_packs,
    get_active_pack,
    get_pack_by_slug,
    reset_cache,
)
from app.core.partner_pack.manifest import (
    PartnerBranding,
    PartnerPackManifest,
)
from app.core.partner_pack.router import router as partner_pack_router
from app.dependencies import get_current_user_payload


@pytest.fixture
def sample_manifest() -> PartnerPackManifest:
    return PartnerPackManifest(
        slug="test-pack",
        partner_name="Test Partner",
        partner_url="https://example.test",
        pack_version="1.0.0",
        description="A test pack.",
        default_locale="fr-CA",
        additional_locales={"fr-CA": "locales/fr-CA.json"},
        cwicr_regions=["cwicr-eng-toronto"],
        default_currency="CAD",
        validation_rule_packs=["nbc_2020"],
        branding=PartnerBranding(
            primary_color="#BE1B2F",
            accent_color="#0F2C5F",
            logo_path="logo.svg",
        ),
        onboarding_script_path="onboarding.yaml",
    )


@pytest.fixture
def client(sample_manifest: PartnerPackManifest) -> TestClient:
    app = FastAPI()
    app.include_router(partner_pack_router)
    # ``/current`` and ``/installed`` answer signed-in callers only; these
    # tests are about what they say, so the caller is stood in for.
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": "pack-reader"}
    return TestClient(app)


class TestManifestSchema:
    def test_manifest_valid(self, sample_manifest: PartnerPackManifest) -> None:
        assert sample_manifest.slug == "test-pack"
        assert sample_manifest.effective_powered_by == (
            "Powered by OpenConstructionERP · In partnership with Test Partner"
        )

    def test_custom_powered_by_text_wins(self) -> None:
        m = PartnerPackManifest(
            slug="custom-text",
            partner_name="XX",
            branding=PartnerBranding(powered_by_text="Custom co-brand line"),
        )
        assert m.effective_powered_by == "Custom co-brand line"

    def test_slug_pattern_enforced(self) -> None:
        with pytest.raises(Exception):
            PartnerPackManifest(slug="Has_Capitals", partner_name="XX")
        with pytest.raises(Exception):
            PartnerPackManifest(slug="ab", partner_name="XX")  # too short

    def test_currency_iso_4217(self) -> None:
        with pytest.raises(Exception):
            PartnerPackManifest(slug="bad-curr", partner_name="XX", default_currency="cad")

    def test_to_public_dict_strips_internal_paths(self, sample_manifest: PartnerPackManifest) -> None:
        pub = sample_manifest.to_public_dict()
        assert "logo_path" not in pub["branding"]
        assert "favicon_path" not in pub["branding"]
        assert "onboarding_script_path" not in pub
        assert pub["additional_locales"] == ["fr-CA"]
        # has_logo, has_favicon and has_onboarding_script are deliberately not
        # asserted here any more. They used to read the manifest - has_logo was
        # hardcoded True - and now answer whether the pack CARRIES the file. So
        # they are False for this fixture, which is a bare manifest whose slug
        # resolves to no pack anywhere on disk, and that says nothing about the
        # serialiser this test is about. Their real behaviour needs a pack that
        # exists, and is covered in test_partner_pack_dropin.py.


class TestDiscovery:
    def test_no_packs_installed(self) -> None:
        reset_cache()
        with (
            patch("app.core.partner_pack.discovery.entry_points", return_value=[]),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[],
            ),
        ):
            assert discover_packs() == []
            assert get_active_pack() is None
            assert get_pack_by_slug("anything") is None

    def test_pack_discovered_and_loaded(self, sample_manifest: PartnerPackManifest) -> None:
        reset_cache()

        class FakeEP:
            name = "test-pack"
            value = "openconstructionerp_test:MANIFEST"

            @staticmethod
            def load() -> PartnerPackManifest:
                return sample_manifest

        with (
            patch(
                "app.core.partner_pack.discovery.entry_points",
                return_value=[FakeEP()],
            ),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[],
            ),
        ):
            packs = discover_packs()
            assert len(packs) == 1
            assert packs[0].slug == "test-pack"

    def test_env_var_selects_pack(self, sample_manifest: PartnerPackManifest, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_cache()
        other = PartnerPackManifest(slug="other-pack", partner_name="Other")

        class A:
            name = "test-pack"
            value = "x:M"

            @staticmethod
            def load() -> PartnerPackManifest:
                return sample_manifest

        class B:
            name = "other-pack"
            value = "y:M"

            @staticmethod
            def load() -> PartnerPackManifest:
                return other

        monkeypatch.setenv("OE_PARTNER_PACK", "other-pack")
        with (
            patch(
                "app.core.partner_pack.discovery.entry_points",
                return_value=[A(), B()],
            ),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[],
            ),
        ):
            active = get_active_pack()
            assert active is not None
            assert active.slug == "other-pack"

    def test_failed_pack_load_does_not_crash_discovery(self) -> None:
        reset_cache()

        class BrokenEP:
            name = "broken"
            value = "broken:M"

            @staticmethod
            def load() -> object:
                raise RuntimeError("boom")

        with (
            patch(
                "app.core.partner_pack.discovery.entry_points",
                return_value=[BrokenEP()],
            ),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[],
            ),
        ):
            assert discover_packs() == []
            assert get_active_pack() is None

    def test_filesystem_packs_discovered_but_never_auto_active(
        self, sample_manifest: PartnerPackManifest, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Filesystem packs are listable but must not co-brand the app.

        Discovering packs from the repo ``packs/`` dir must never make one
        active unless ``OE_PARTNER_PACK`` explicitly names it.
        """
        reset_cache()
        monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
        with (
            patch("app.core.partner_pack.discovery.entry_points", return_value=[]),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[sample_manifest],
            ),
        ):
            packs = discover_packs()
            assert [m.slug for m in packs] == ["test-pack"]
            # Discovered, but no env -> not active.
            assert get_active_pack() is None

    def test_entrypoint_pack_overrides_filesystem_on_slug_collision(self, sample_manifest: PartnerPackManifest) -> None:
        reset_cache()
        fs_version = PartnerPackManifest(
            slug="test-pack",
            partner_name="Filesystem Copy",
            pack_version="0.0.1",
        )

        class EP:
            name = "test-pack"
            value = "openconstructionerp_test:MANIFEST"

            @staticmethod
            def load() -> PartnerPackManifest:
                return sample_manifest

        with (
            patch(
                "app.core.partner_pack.discovery.entry_points",
                return_value=[EP()],
            ),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[fs_version],
            ),
        ):
            packs = discover_packs()
            assert len(packs) == 1
            # Entry-point version wins on collision.
            assert packs[0].partner_name == "Test Partner"
            assert packs[0].pack_version == "1.0.0"


class TestRouter:
    def test_current_when_no_pack(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        reset_cache()
        monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
        with (
            patch("app.core.partner_pack.discovery.entry_points", return_value=[]),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[],
            ),
        ):
            r = client.get("/api/v1/partner-pack/current")
            assert r.status_code == 200
            assert r.json() == {"active": False}

    def test_current_with_pack(
        self,
        client: TestClient,
        sample_manifest: PartnerPackManifest,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reset_cache()

        class EP:
            name = "test-pack"
            value = "openconstructionerp_test:MANIFEST"

            @staticmethod
            def load() -> PartnerPackManifest:
                return sample_manifest

        # Activation is explicit-only: a pack is only active when named by
        # OE_PARTNER_PACK. Discovering a pack must not auto-activate it.
        monkeypatch.setenv("OE_PARTNER_PACK", "test-pack")
        with (
            patch("app.core.partner_pack.discovery.entry_points", return_value=[EP()]),
            patch(
                "app.core.partner_pack.discovery._discover_filesystem_packs",
                return_value=[],
            ),
        ):
            r = client.get("/api/v1/partner-pack/current")
            assert r.status_code == 200
            data = r.json()
            assert data["active"] is True
            assert data["manifest"]["slug"] == "test-pack"
            assert data["manifest"]["branding"]["primary_color"] == "#BE1B2F"

    def test_logo_404_when_no_pack(self, client: TestClient) -> None:
        reset_cache()
        with patch("app.core.partner_pack.discovery.entry_points", return_value=[]):
            r = client.get("/api/v1/partner-pack/logo")
            assert r.status_code == 404

    def test_inspect_pack_by_slug_unknown(self, client: TestClient) -> None:
        reset_cache()
        with patch("app.core.partner_pack.discovery.entry_points", return_value=[]):
            r = client.get("/api/v1/partner-pack/by-slug/nope")
            assert r.status_code == 404
