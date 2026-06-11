"""Partner-pack state must live in the ACTIVE data dir (FA-0003).

Before the fix, ``partner_pack_state.json`` was always resolved to the
DEFAULT ``~/.openestimate`` regardless of ``serve --data-dir``, so a stale
pack applied on the default install silently hijacked seeding, branding and
locale of ANY custom ``--data-dir`` instance. These tests pin the contract:

* default-install behavior (no ``OE_CLI_DATA_DIR``) is unchanged,
* a custom data dir is fully isolated (never inherits the default's pack),
* the active-pack cache is keyed per resolved state dir.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.partner_pack import discovery
from app.core.partner_pack.discovery import get_active_pack, reset_cache
from app.core.partner_pack.manifest import PartnerPackManifest
from app.core.partner_pack.state import (
    STATE_FILENAME,
    AppliedPackState,
    _resolve_state_dir,
    get_applied_slug,
    load_applied_state,
    save_applied_state,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Isolate every test: fake home, no CLI data dir, no env pack, fresh caches."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.delenv("OE_CLI_DATA_DIR", raising=False)
    monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_cache()
    yield
    reset_cache()


def _write_state(slug: str, data_dir: Path) -> None:
    save_applied_state(AppliedPackState(slug=slug, pack_version="1.0.0"), data_dir)


class TestDefaultDirUnchanged:
    """Without OE_CLI_DATA_DIR the legacy default resolution still applies."""

    def test_resolves_to_legacy_default(self) -> None:
        assert _resolve_state_dir() == Path.home() / ".openestimate"

    def test_explicit_data_dir_argument_wins(self, tmp_path: Path) -> None:
        explicit = tmp_path / "explicit"
        assert _resolve_state_dir(explicit) == explicit

    def test_default_install_roundtrip(self) -> None:
        _write_state("legacy-pack", Path.home() / ".openestimate")
        assert (Path.home() / ".openestimate" / STATE_FILENAME).is_file()
        # No env, no argument: reads from the default dir, as before.
        assert get_applied_slug() == "legacy-pack"

    def test_cli_data_dir_pointing_at_default_keeps_working(self, monkeypatch: pytest.MonkeyPatch) -> None:
        default_dir = Path.home() / ".openestimate"
        _write_state("legacy-pack", default_dir)
        monkeypatch.setenv("OE_CLI_DATA_DIR", str(default_dir))
        assert get_applied_slug() == "legacy-pack"


class TestCustomDataDirIsolated:
    """A custom --data-dir instance never sees the default install's pack."""

    def test_state_written_and_read_in_active_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        custom = tmp_path / "custom-data"
        monkeypatch.setenv("OE_CLI_DATA_DIR", str(custom))
        _write_state("custom-pack", custom)
        assert (custom / STATE_FILENAME).is_file()
        assert not (Path.home() / ".openestimate" / STATE_FILENAME).exists()
        assert get_applied_slug() == "custom-pack"

    def test_save_with_no_argument_targets_active_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        custom = tmp_path / "custom-data"
        monkeypatch.setenv("OE_CLI_DATA_DIR", str(custom))
        save_applied_state(AppliedPackState(slug="custom-pack"))
        assert (custom / STATE_FILENAME).is_file()
        assert not (Path.home() / ".openestimate" / STATE_FILENAME).exists()

    def test_custom_dir_does_not_inherit_default_pack(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """FA-0003 regression: stale default-install pack must not leak in."""
        _write_state("stale-pack", Path.home() / ".openestimate")
        custom = tmp_path / "fresh-data"
        custom.mkdir()
        monkeypatch.setenv("OE_CLI_DATA_DIR", str(custom))

        assert get_applied_slug() is None
        assert load_applied_state() is None

        # Even if the stale pack is installed and resolvable by slug, the
        # custom-dir instance must stay vanilla.
        stale_manifest = PartnerPackManifest(slug="stale-pack", partner_name="Stale")
        with patch.object(discovery, "get_pack_by_slug", return_value=stale_manifest):
            assert get_active_pack() is None


class TestActivePackCacheKeyedPerPath:
    """get_active_pack memoizes per resolved state dir, not one global slot."""

    def test_two_data_dirs_get_independent_answers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        dir_a = tmp_path / "data-a"
        dir_b = tmp_path / "data-b"
        _write_state("pack-aaa", dir_a)
        _write_state("pack-bbb", dir_b)
        manifests = {
            "pack-aaa": PartnerPackManifest(slug="pack-aaa", partner_name="Pack A"),
            "pack-bbb": PartnerPackManifest(slug="pack-bbb", partner_name="Pack B"),
        }
        with patch.object(discovery, "get_pack_by_slug", side_effect=manifests.get):
            monkeypatch.setenv("OE_CLI_DATA_DIR", str(dir_a))
            active_a = get_active_pack()
            assert active_a is not None
            assert active_a.slug == "pack-aaa"

            # Switch the active dir WITHOUT clearing caches: a single global
            # memo would keep returning pack-aaa here.
            monkeypatch.setenv("OE_CLI_DATA_DIR", str(dir_b))
            active_b = get_active_pack()
            assert active_b is not None
            assert active_b.slug == "pack-bbb"

            # Both entries coexist in the cache - flipping back is consistent.
            monkeypatch.setenv("OE_CLI_DATA_DIR", str(dir_a))
            again = get_active_pack()
            assert again is not None
            assert again.slug == "pack-aaa"

    def test_reset_cache_clears_per_path_entries(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        dir_a = tmp_path / "data-a"
        _write_state("pack-aaa", dir_a)
        manifest = PartnerPackManifest(slug="pack-aaa", partner_name="Pack A")
        monkeypatch.setenv("OE_CLI_DATA_DIR", str(dir_a))
        with patch.object(discovery, "get_pack_by_slug", return_value=manifest):
            active = get_active_pack()
            assert active is not None
            assert active.slug == "pack-aaa"

        # Un-apply: file removed + reset_cache -> the cached entry must not survive.
        (dir_a / STATE_FILENAME).unlink()
        reset_cache()
        assert get_active_pack() is None
