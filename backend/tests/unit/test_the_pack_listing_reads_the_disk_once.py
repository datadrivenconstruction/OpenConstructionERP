"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``GET /api/v1/partner-pack/installed`` must not rescan the machine per request.

The header asks for this listing on every page. Each ``has_logo`` /
``has_favicon`` / ``has_onboarding_script`` flag in it used to call
``read_pack_file``, and every one of those calls re-ran
``importlib.metadata.entry_points`` for both pack groups. Over the 43 packs of
a source checkout that was 102 scans and about five seconds of CPU per request,
measured, and three concurrent requests took 146 to 252 seconds on the machine
where a price edit in the BOQ looked like a frozen app.

The listing now scans the entry-points once and answers each flag once per
process, and ``reset_cache()`` (called by install, rescan, apply and un-apply)
drops both. These tests count the scans and the reads through monkeypatch, so
they fail if either cache is removed and also if the invalidation stops working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.partner_pack import discovery as discovery_mod
from app.core.partner_pack import state as state_mod
from app.core.partner_pack.discovery import _iter_entry_points, reset_cache
from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest
from app.core.partner_pack.router import list_installed, rescan


def _write_pack(packs_dir: Path, slug: str) -> Path:
    """Drop a declarative pack that names three files and ships only the logo."""
    root = packs_dir / slug
    root.mkdir(parents=True)
    manifest = PartnerPackManifest(
        slug=slug,
        partner_name="Acme Partner",
        branding=PartnerBranding(logo_path="logo.svg", favicon_path="favicon.ico"),
        onboarding_script_path="onboarding.yaml",
    )
    (root / "manifest.json").write_text(json.dumps(manifest.model_dump(mode="json")), encoding="utf-8")
    (root / "logo.svg").write_text("<svg/>", encoding="utf-8")
    return root


def _flags(listing: dict) -> dict[str, bool]:
    """The three carried-file flags of the only pack in ``listing``."""
    (pack,) = listing["installed"]
    return {
        "has_logo": pack["branding"]["has_logo"],
        "has_favicon": pack["branding"]["has_favicon"],
        "has_onboarding_script": pack["has_onboarding_script"],
    }


@pytest.fixture
def counted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate discovery in ``tmp_path`` and count entry-point scans and file reads.

    The repo ``packs/`` tree is switched off so the only pack is the dropped one,
    and ``entry_points`` answers with no pip packs while counting its calls.
    """
    calls = {"entry_points": 0, "read_pack_file": 0}
    real_read = discovery_mod.read_pack_file

    def fake_entry_points(*args: object, **kwargs: object) -> list:
        calls["entry_points"] += 1
        return []

    def counting_read(slug: str, relpath: str) -> bytes | None:
        calls["read_pack_file"] += 1
        return real_read(slug, relpath)

    monkeypatch.delenv("OE_PACK", raising=False)
    monkeypatch.delenv("OE_PARTNER_PACK", raising=False)
    monkeypatch.setattr(discovery_mod, "_resolve_data_dir", lambda d=None: tmp_path if d is None else d)
    monkeypatch.setattr(state_mod, "_resolve_state_dir", lambda data_dir=None: tmp_path)
    monkeypatch.setattr(discovery_mod, "_packs_dir", lambda: None)
    monkeypatch.setattr(discovery_mod, "entry_points", fake_entry_points)
    monkeypatch.setattr(discovery_mod, "read_pack_file", counting_read)
    reset_cache()
    yield tmp_path, calls
    reset_cache()


def test_the_second_listing_neither_scans_nor_reads(counted: tuple[Path, dict[str, int]]) -> None:
    data_dir, calls = counted
    _write_pack(data_dir / "packs", "acme")

    first = list_installed()
    # One scan per pack group, and one read per declared file.
    assert calls == {"entry_points": 2, "read_pack_file": 3}
    assert _flags(first) == {"has_logo": True, "has_favicon": False, "has_onboarding_script": False}

    calls.update(entry_points=0, read_pack_file=0)
    second = list_installed()
    assert calls == {"entry_points": 0, "read_pack_file": 0}, (
        "a repeat listing rescanned the installed distributions or re-read the pack files; "
        "the header calls this on every page"
    )
    assert second == first


def test_reset_cache_lets_the_listing_see_a_file_added_since(counted: tuple[Path, dict[str, int]]) -> None:
    data_dir, calls = counted
    root = _write_pack(data_dir / "packs", "acme")
    assert _flags(list_installed())["has_favicon"] is False

    (root / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    # Same lifetime as the manifest cache: a file added by hand is seen after a reset.
    assert _flags(list_installed())["has_favicon"] is False

    reset_cache()
    calls.update(entry_points=0, read_pack_file=0)
    assert _flags(list_installed()) == {"has_logo": True, "has_favicon": True, "has_onboarding_script": False}
    assert calls == {"entry_points": 2, "read_pack_file": 3}


def test_the_rescan_route_drops_both_caches(counted: tuple[Path, dict[str, int]]) -> None:
    data_dir, calls = counted
    root = _write_pack(data_dir / "packs", "acme")
    assert _flags(list_installed())["has_onboarding_script"] is False

    (root / "onboarding.yaml").write_text("steps: []\n", encoding="utf-8")
    assert rescan() == {"count": 1, "slugs": ["acme"]}
    assert _flags(list_installed())["has_onboarding_script"] is True


def test_a_caller_cannot_poison_the_cached_entry_points(counted: tuple[Path, dict[str, int]]) -> None:
    _, calls = counted
    handed_out = _iter_entry_points()
    handed_out.append(object())  # type: ignore[arg-type]
    assert _iter_entry_points() == []
    assert calls["entry_points"] == 2
