"""Tests for the module marketplace plugin manager.

Covers the two formerly-stubbed paths:
    * ``_install_from_zipfile`` now parses the extracted manifest and returns a
      ``ModuleInfo`` populated from the manifest's real version / display_name /
      dependencies (instead of "unknown").
    * ``check_updates`` compares each installed module's manifest version against
      the registry's advertised version and flags only the out-of-date ones.

These tests are filesystem / zip only — no database, no network. ``list_available``
(the registry source) is monkeypatched so the comparison logic is exercised
deterministically and offline.
"""

from __future__ import annotations

import textwrap
import zipfile
from pathlib import Path

import pytest

from app.core.plugin_manager import ModuleInfo, ModulePluginManager, _version_key


def _write_module_zip(
    zip_path: Path,
    *,
    dir_name: str,
    manifest_name: str,
    version: str,
    display_name: str = "Test Module",
    depends: list[str] | None = None,
    manifest_body: str | None = None,
) -> Path:
    """Build a minimal module zip with a valid manifest.py at the top level."""
    depends = depends or []
    if manifest_body is None:
        manifest_body = textwrap.dedent(
            f"""
            from app.core.module_loader import ModuleManifest

            manifest = ModuleManifest(
                name={manifest_name!r},
                version={version!r},
                display_name={display_name!r},
                description="A test fixture module",
                author="Test Author",
                category="community",
                depends={depends!r},
            )
            """
        ).strip()

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{dir_name}/manifest.py", manifest_body)
        zf.writestr(f"{dir_name}/__init__.py", "")
    return zip_path


# ── _version_key / comparison ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.0", (1, 2, 0)),
        ("v2.0", (2, 0)),
        ("1.2.0-rc1", (1, 2, 0)),
        ("3", (3,)),
        ("not-a-version", ()),
        ("", ()),
    ],
)
def test_version_key_parsing(version: str, expected: tuple[int, ...]) -> None:
    assert _version_key(version) == expected


def test_is_newer_semver() -> None:
    assert ModulePluginManager._is_newer("1.2.0", "1.1.9") is True
    assert ModulePluginManager._is_newer("1.0.0", "1.0.0") is False
    assert ModulePluginManager._is_newer("1.0.0", "2.0.0") is False
    # Junk installed but clean available → upgradable.
    assert ModulePluginManager._is_newer("1.0.0", "garbage") is True
    # Both junk but differing → flag it.
    assert ModulePluginManager._is_newer("nightly-b", "nightly-a") is True
    assert ModulePluginManager._is_newer("nightly", "nightly") is False


# ── install_from_zip ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_from_zip_returns_manifest_metadata(tmp_path: Path) -> None:
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()
    zip_path = _write_module_zip(
        tmp_path / "mod.zip",
        dir_name="oe_test_mod",
        manifest_name="oe_test_mod",
        version="2.3.1",
        display_name="Fancy Test Module",
        depends=["oe_projects", "oe_costs"],
    )

    mgr = ModulePluginManager(modules_dir)
    try:
        info = await mgr.install_from_zip(zip_path)
    finally:
        await mgr.close()

    assert isinstance(info, ModuleInfo)
    assert info.name == "oe_test_mod"
    assert info.version == "2.3.1"  # real manifest version, not "unknown"
    assert info.display_name == "Fancy Test Module"
    assert info.depends == ["oe_projects", "oe_costs"]
    assert (modules_dir / "oe_test_mod" / "manifest.py").is_file()


@pytest.mark.asyncio
async def test_install_from_zip_missing_manifest_raises(tmp_path: Path) -> None:
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("oe_no_manifest/__init__.py", "")

    mgr = ModulePluginManager(modules_dir)
    try:
        with pytest.raises(ValueError, match="No manifest.py"):
            await mgr.install_from_zip(zip_path)
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_install_from_zip_invalid_manifest_rolls_back(tmp_path: Path) -> None:
    """A manifest with no ModuleManifest must error and leave no partial install."""
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()
    zip_path = _write_module_zip(
        tmp_path / "broken.zip",
        dir_name="oe_broken",
        manifest_name="oe_broken",
        version="1.0.0",
        manifest_body="manifest = 'i am not a ModuleManifest'",
    )

    mgr = ModulePluginManager(modules_dir)
    try:
        with pytest.raises(ValueError, match="Invalid module manifest"):
            await mgr.install_from_zip(zip_path)
    finally:
        await mgr.close()

    # Extraction rolled back — no orphaned module directory left behind.
    assert not (modules_dir / "oe_broken").exists()


@pytest.mark.asyncio
async def test_install_from_zip_invalid_manifest_restores_backup(tmp_path: Path) -> None:
    """A failed reinstall over an existing module restores the backup."""
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    # Existing good install.
    good_zip = _write_module_zip(
        tmp_path / "good.zip",
        dir_name="oe_keep",
        manifest_name="oe_keep",
        version="1.0.0",
    )
    mgr = ModulePluginManager(modules_dir)
    try:
        await mgr.install_from_zip(good_zip)
        assert (modules_dir / "oe_keep" / "manifest.py").is_file()

        # Now try to overwrite it with a broken zip.
        broken_zip = _write_module_zip(
            tmp_path / "broken2.zip",
            dir_name="oe_keep",
            manifest_name="oe_keep",
            version="2.0.0",
            manifest_body="x = 1  # no manifest defined",
        )
        with pytest.raises(ValueError, match="Invalid module manifest"):
            await mgr.install_from_zip(broken_zip)
    finally:
        await mgr.close()

    # The original install is restored from backup.
    restored = modules_dir / "oe_keep"
    assert restored.is_file() is False
    assert (restored / "manifest.py").is_file()
    assert not restored.with_suffix(".bak").exists()


# ── check_updates ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_updates_flags_outdated_only(tmp_path: Path, monkeypatch) -> None:
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    mgr = ModulePluginManager(modules_dir)
    try:
        await mgr.install_from_zip(
            _write_module_zip(
                tmp_path / "a.zip",
                dir_name="oe_alpha",
                manifest_name="oe_alpha",
                version="1.0.0",
            )
        )
        await mgr.install_from_zip(
            _write_module_zip(
                tmp_path / "b.zip",
                dir_name="oe_beta",
                manifest_name="oe_beta",
                version="2.5.0",
            )
        )

        async def fake_available(*_args, **_kwargs) -> list[ModuleInfo]:
            return [
                ModuleInfo(name="oe_alpha", display_name="Alpha", version="1.4.0"),
                ModuleInfo(name="oe_beta", display_name="Beta", version="2.5.0"),
            ]

        monkeypatch.setattr(mgr, "list_available", fake_available)

        updates = await mgr.check_updates()
    finally:
        await mgr.close()

    # Only oe_alpha (1.0.0 → 1.4.0) is out of date; oe_beta is current.
    assert updates == [
        {
            "name": "oe_alpha",
            "installed_version": "1.0.0",
            "available_version": "1.4.0",
        }
    ]


@pytest.mark.asyncio
async def test_check_updates_offline_returns_empty(tmp_path: Path, monkeypatch) -> None:
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    mgr = ModulePluginManager(modules_dir)
    try:
        await mgr.install_from_zip(
            _write_module_zip(
                tmp_path / "a.zip",
                dir_name="oe_alpha",
                manifest_name="oe_alpha",
                version="1.0.0",
            )
        )

        async def empty_available(*_args, **_kwargs) -> list[ModuleInfo]:
            return []  # offline / registry unreachable

        monkeypatch.setattr(mgr, "list_available", empty_available)

        assert await mgr.check_updates() == []
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_check_updates_picks_highest_registry_version(tmp_path: Path, monkeypatch) -> None:
    """When the registry lists multiple versions, the newest one is compared."""
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    mgr = ModulePluginManager(modules_dir)
    try:
        await mgr.install_from_zip(
            _write_module_zip(
                tmp_path / "a.zip",
                dir_name="oe_alpha",
                manifest_name="oe_alpha",
                version="1.0.0",
            )
        )

        async def multi_available(*_args, **_kwargs) -> list[ModuleInfo]:
            return [
                ModuleInfo(name="oe_alpha", display_name="Alpha", version="1.1.0"),
                ModuleInfo(name="oe_alpha", display_name="Alpha", version="1.3.0"),
                ModuleInfo(name="oe_alpha", display_name="Alpha", version="1.2.0"),
            ]

        monkeypatch.setattr(mgr, "list_available", multi_available)

        updates = await mgr.check_updates()
    finally:
        await mgr.close()

    assert updates == [
        {
            "name": "oe_alpha",
            "installed_version": "1.0.0",
            "available_version": "1.3.0",
        }
    ]


# ── no registry configured (the default) ────────────────────────────────────


@pytest.mark.asyncio
async def test_list_available_without_registry_is_explicit_empty(tmp_path: Path, monkeypatch) -> None:
    """No public registry exists; the default must short-circuit, not hit the network."""
    mgr = ModulePluginManager(tmp_path / "modules")
    assert mgr.registry_url == ""

    async def boom(*_args, **_kwargs):
        raise AssertionError("HTTP must not be called when no registry is configured")

    monkeypatch.setattr(mgr._http, "get", boom)
    try:
        assert await mgr.list_available() == []
        # check_updates flows through list_available and stays an empty no-op.
        assert await mgr.check_updates() == []
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_install_without_registry_raises_clear_error(tmp_path: Path) -> None:
    mgr = ModulePluginManager(tmp_path / "modules")
    try:
        with pytest.raises(ValueError, match="No module registry is configured"):
            await mgr.install("oe_anything")
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_fetch_module_info_without_registry_returns_none(tmp_path: Path) -> None:
    mgr = ModulePluginManager(tmp_path / "modules")
    try:
        assert await mgr._fetch_module_info("oe_anything") is None
    finally:
        await mgr.close()


@pytest.mark.asyncio
async def test_list_installed_includes_version(tmp_path: Path) -> None:
    modules_dir = tmp_path / "modules"
    modules_dir.mkdir()

    mgr = ModulePluginManager(modules_dir)
    try:
        await mgr.install_from_zip(
            _write_module_zip(
                tmp_path / "a.zip",
                dir_name="oe_alpha",
                manifest_name="oe_alpha",
                version="9.9.9",
            )
        )
        installed = await mgr.list_installed()
    finally:
        await mgr.close()

    by_name = {m["name"]: m for m in installed}
    assert "oe_alpha" in by_name
    assert by_name["oe_alpha"]["version"] == "9.9.9"
    assert by_name["oe_alpha"]["has_manifest"] is True
