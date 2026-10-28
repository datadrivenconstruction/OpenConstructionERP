"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the drop-in partner-pack feature.

Covers the three new capabilities:
  * data-dir folder discovery (a ``manifest.json`` pack dropped in a folder),
  * data-dir zip discovery (a ``.zip`` dropped in, safely extracted + loaded),
  * the ``POST /api/v1/partner-pack/install`` upload endpoint (good vs malicious),
  * the ``pack new`` scaffolder produces a folder ``discover_packs()`` then finds.

All filesystem state is confined to ``tmp_path``; the runtime data dir is
monkeypatched so no test ever touches the real ``~/.openestimate`` or the
session DB dir.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.partner_pack import discovery as discovery_mod
from app.core.partner_pack.discovery import (
    PackInstallError,
    discover_packs,
    get_active_pack,
    get_pack_by_slug,
    install_dropped_zip,
    read_pack_file,
    reset_cache,
)
from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest
from app.core.partner_pack.router import router as partner_pack_router
from app.dependencies import get_current_user_payload

# ── Helpers ──────────────────────────────────────────────────────────────────


def _manifest_dict(slug: str = "drop-pack", partner: str = "Drop Partner") -> dict:
    """A minimal valid serialized-manifest dict for ``slug``."""
    return PartnerPackManifest(
        slug=slug,
        partner_name=partner,
        pack_version="1.2.3",
        default_locale="de",
        default_currency="EUR",
        branding=PartnerBranding(primary_color="#123456", logo_path="logo.svg"),
        onboarding_script_path="onboarding.yaml",
    ).model_dump(mode="json")


def _write_folder_pack(packs_dir: Path, slug: str = "drop-pack", *, wrapped: bool = False) -> Path:
    """Create a dropped folder pack under ``packs_dir``. Returns its root dir."""
    root = packs_dir / slug
    body = root / "inner" if wrapped else root
    body.mkdir(parents=True)
    (body / "manifest.json").write_text(json.dumps(_manifest_dict(slug)), encoding="utf-8")
    (body / "logo.svg").write_text("<svg/>", encoding="utf-8")
    return root


def _make_pack_zip_bytes(slug: str = "zip-pack", *, wrapped: bool = True) -> bytes:
    """Build the bytes of a valid pack ``.zip`` (optionally wrapped in a folder)."""
    import io

    bio = io.BytesIO()
    prefix = f"{slug}/" if wrapped else ""
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr(f"{prefix}manifest.json", json.dumps(_manifest_dict(slug)))
        zf.writestr(f"{prefix}logo.svg", "<svg/>")
    return bio.getvalue()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the partner-pack data-dir resolver at an isolated tmp dir.

    Returns the data dir; its ``packs/`` sub-folder is the scanned drop folder.
    Also clears OE_PARTNER_PACK and busts the discovery cache around the test.
    """
    monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
    monkeypatch.setattr(discovery_mod, "_resolve_data_dir", lambda d=None: tmp_path if d is None else d)
    # Isolate from any repo packs/ and pip entry-point packs so assertions are
    # about the dropped packs only.
    monkeypatch.setattr(discovery_mod, "_discover_filesystem_packs", lambda: [])
    monkeypatch.setattr(discovery_mod, "_discover_entrypoint_packs", lambda: [])
    reset_cache()
    yield tmp_path
    reset_cache()


# ── 1. Data-dir folder discovery ──────────────────────────────────────────────


class TestFolderDiscovery:
    def test_folder_pack_discovered(self, data_dir: Path) -> None:
        _write_folder_pack(data_dir / "packs", "drop-pack")
        packs = discover_packs()
        assert [m.slug for m in packs] == ["drop-pack"]
        assert get_pack_by_slug("drop-pack").pack_version == "1.2.3"

    def test_wrapped_folder_pack_discovered(self, data_dir: Path) -> None:
        _write_folder_pack(data_dir / "packs", "wrapped-pack", wrapped=True)
        assert [m.slug for m in discover_packs()] == ["wrapped-pack"]

    def test_dropped_pack_never_auto_active(self, data_dir: Path) -> None:
        _write_folder_pack(data_dir / "packs", "drop-pack")
        # Discovered but, with no OE_PARTNER_PACK and nothing applied, not active.
        assert get_pack_by_slug("drop-pack") is not None
        assert get_active_pack() is None

    def test_invalid_manifest_skipped_not_crash(self, data_dir: Path) -> None:
        packs = data_dir / "packs"
        bad = packs / "bad-pack"
        bad.mkdir(parents=True)
        (bad / "manifest.json").write_text("{ not valid json", encoding="utf-8")
        # A good one alongside it.
        _write_folder_pack(packs, "good-pack")
        slugs = [m.slug for m in discover_packs()]
        assert slugs == ["good-pack"]

    def test_read_pack_file_resolves_dropped_asset(self, data_dir: Path) -> None:
        _write_folder_pack(data_dir / "packs", "drop-pack")
        reset_cache()
        assert read_pack_file("drop-pack", "logo.svg") == b"<svg/>"
        # Path traversal is blocked.
        assert read_pack_file("drop-pack", "../../../../etc/passwd") is None
        assert read_pack_file("drop-pack", "/etc/passwd") is None

    def test_public_dict_flags_answer_the_filesystem_not_the_manifest(self, data_dir: Path) -> None:
        """``has_logo`` and its siblings report what the pack carries, not what it says.

        This dropped pack declares a logo and an onboarding script and writes
        only the logo, so off one manifest one flag has to come back true and
        the other false. That is the pair the old code could not produce:
        ``has_logo`` was hardcoded True and the other two read a path field for
        non-None, so both were true here and one of them was a lie. The
        frontend then advertised an onboarding script that 404s.

        A dropped pack is also the population that makes the check worth having.
        backend/tests/unit/test_community_packs_ship.py keeps declared and
        carried identical for the fifteen packs this repository ships, so it
        can only ever answer true for those; it cannot see this pack at all.
        """
        _write_folder_pack(data_dir / "packs", "drop-pack")
        reset_cache()
        pub = get_pack_by_slug("drop-pack").to_public_dict()
        assert pub["branding"]["has_logo"] is True, "logo.svg was written, so the pack carries it"
        assert pub["has_onboarding_script"] is False, (
            "the manifest names onboarding.yaml and _write_folder_pack does not write it, so the "
            "pack does not carry it and must not be advertised as having it"
        )
        assert pub["branding"]["has_favicon"] is False, "no favicon declared and none on disk"

    def test_no_packs_dir_returns_empty(self, data_dir: Path) -> None:
        # data_dir exists but has no packs/ sub-folder yet.
        assert discover_packs() == []


# ── 2. Data-dir zip discovery (passive scan auto-extracts) ────────────────────


class TestZipDiscovery:
    def test_dropped_zip_extracted_and_loaded(self, data_dir: Path) -> None:
        packs = data_dir / "packs"
        packs.mkdir()
        (packs / "zip-pack.zip").write_bytes(_make_pack_zip_bytes("zip-pack"))
        slugs = [m.slug for m in discover_packs()]
        assert slugs == ["zip-pack"]
        # The zip was extracted into a real folder (idempotent on rescan).
        assert (packs / "zip-pack").is_dir()
        assert (packs / "zip-pack" / "manifest.json").is_file()

    def test_zip_slug_authoritative_over_filename(self, data_dir: Path) -> None:
        packs = data_dir / "packs"
        packs.mkdir()
        # File named differently from the manifest slug.
        (packs / "vendor-bundle.zip").write_bytes(_make_pack_zip_bytes("real-slug"))
        assert [m.slug for m in discover_packs()] == ["real-slug"]
        # Asset resolves by the manifest slug, reading from the extracted dir.
        reset_cache()
        assert read_pack_file("real-slug", "logo.svg") == b"<svg/>"

    def test_malformed_zip_ignored_not_crash(self, data_dir: Path) -> None:
        packs = data_dir / "packs"
        packs.mkdir()
        (packs / "broken.zip").write_bytes(b"PK\x03\x04 not really a zip")
        # Plus a valid folder pack to prove discovery still runs.
        _write_folder_pack(packs, "good-pack")
        assert [m.slug for m in discover_packs()] == ["good-pack"]

    def test_zip_without_manifest_ignored(self, data_dir: Path) -> None:
        import io

        packs = data_dir / "packs"
        packs.mkdir()
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("nope/readme.txt", "no manifest here")
        (packs / "nomanifest.zip").write_bytes(bio.getvalue())
        assert discover_packs() == []


# ── 3. install_dropped_zip (the endpoint's core) ──────────────────────────────


class TestInstallDroppedZip:
    def test_install_good_zip(self, data_dir: Path) -> None:
        manifest = install_dropped_zip(_make_pack_zip_bytes("uploaded"))
        assert manifest.slug == "uploaded"
        assert (data_dir / "packs" / "uploaded" / "manifest.json").is_file()

    def test_install_rejects_non_zip(self, data_dir: Path) -> None:
        with pytest.raises(PackInstallError, match="not a valid zip"):
            install_dropped_zip(b"%PDF-1.7 totally not a zip")

    def test_install_rejects_zip_without_manifest(self, data_dir: Path) -> None:
        import io

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("pkg/readme.txt", "x")
        with pytest.raises(PackInstallError, match="manifest.json"):
            install_dropped_zip(bio.getvalue())

    def test_install_rejects_unsafe_member(self, data_dir: Path) -> None:
        import io

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("manifest.json", json.dumps(_manifest_dict("evil")))
            # Absolute-path member -> Zip Slip attempt.
            info = zipfile.ZipInfo()
            info.filename = "/etc/cron.d/pwned"
            zf.writestr(info, "evil")
        with pytest.raises(PackInstallError, match="unsafe"):
            install_dropped_zip(bio.getvalue())

    def test_install_rejects_duplicate_slug(self, data_dir: Path) -> None:
        install_dropped_zip(_make_pack_zip_bytes("dup"))
        with pytest.raises(PackInstallError, match="already installed"):
            install_dropped_zip(_make_pack_zip_bytes("dup"))


# ── 4. POST /install endpoint (admin-gated upload) ────────────────────────────


@pytest.fixture
def admin_client(data_dir: Path) -> TestClient:
    """A TestClient whose requests authenticate as an admin user."""
    app = FastAPI()
    app.include_router(partner_pack_router)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": "test-admin",
        "role": "admin",
        "permissions": ["admin"],
    }
    return TestClient(app)


class TestInstallEndpoint:
    def test_accepts_good_pack_zip(self, admin_client: TestClient, data_dir: Path) -> None:
        zip_bytes = _make_pack_zip_bytes("api-pack")
        r = admin_client.post(
            "/api/v1/partner-pack/install",
            files={"file": ("api-pack.zip", zip_bytes, "application/zip")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {
            "installed": True,
            "slug": "api-pack",
            "partner_name": "Drop Partner",
            "pack_version": "1.2.3",
        }
        # Immediately discoverable (cache was busted).
        assert get_pack_by_slug("api-pack") is not None

    def test_rejects_non_zip_upload(self, admin_client: TestClient) -> None:
        r = admin_client.post(
            "/api/v1/partner-pack/install",
            files={"file": ("evil.zip", b"%PDF-1.7 nope", "application/zip")},
        )
        assert r.status_code == 400
        assert "not a .zip" in r.json()["detail"]

    def test_rejects_zip_without_manifest(self, admin_client: TestClient) -> None:
        import io

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("pkg/readme.txt", "no manifest")
        r = admin_client.post(
            "/api/v1/partner-pack/install",
            files={"file": ("x.zip", bio.getvalue(), "application/zip")},
        )
        assert r.status_code == 400
        assert "manifest.json" in r.json()["detail"]

    def test_rejects_malicious_traversal_zip(self, admin_client: TestClient, data_dir: Path) -> None:
        import io

        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("manifest.json", json.dumps(_manifest_dict("evil")))
            info = zipfile.ZipInfo()
            info.filename = "../../../../tmp/oe_pwned.txt"
            zf.writestr(info, "evil")
        r = admin_client.post(
            "/api/v1/partner-pack/install",
            files={"file": ("evil.zip", bio.getvalue(), "application/zip")},
        )
        assert r.status_code == 400
        assert "unsafe" in r.json()["detail"]
        # And nothing was written into the data dir.
        assert not (data_dir / "packs" / "evil").exists()

    def test_requires_admin(self, data_dir: Path) -> None:
        """Without the admin override the endpoint must not be open."""
        app = FastAPI()
        app.include_router(partner_pack_router)
        # Authenticated as a non-admin with no permissions.
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": "joe",
            "role": "viewer",
            "permissions": [],
        }
        client = TestClient(app)
        r = client.post(
            "/api/v1/partner-pack/install",
            files={"file": ("x.zip", _make_pack_zip_bytes("nope"), "application/zip")},
        )
        assert r.status_code == 403


# ── 5. pack new scaffolder produces a discoverable pack ───────────────────────


class TestPackNewScaffolder:
    def test_pack_new_is_discoverable(self, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.cli import cmd_pack_new

        # Scaffold straight into the scanned data-dir packs folder.
        out_dir = data_dir / "packs"
        out_dir.mkdir(parents=True, exist_ok=True)
        args = argparse.Namespace(slug="acme-co", out=str(out_dir), force=False)
        cmd_pack_new(args)

        pack_dir = out_dir / "acme-co"
        assert (pack_dir / "manifest.json").is_file()
        assert (pack_dir / "logo.svg").is_file()
        assert (pack_dir / "onboarding.yaml").is_file()
        assert (pack_dir / "README.md").is_file()

        # The scaffolded manifest validates and is discovered.
        reset_cache()
        slugs = [m.slug for m in discover_packs()]
        assert "acme-co" in slugs
        # And its logo asset reads back through the data-dir resolver.
        assert read_pack_file("acme-co", "logo.svg") is not None

    def test_pack_new_rejects_bad_slug(self, tmp_path: Path) -> None:
        from app.cli import cmd_pack_new

        args = argparse.Namespace(slug="Has_Capitals", out=str(tmp_path), force=False)
        with pytest.raises(SystemExit) as exc:
            cmd_pack_new(args)
        assert exc.value.code == 1
