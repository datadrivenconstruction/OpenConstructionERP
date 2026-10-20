"""The workspace UI appearance default rides on the branding payload.

An admin pins accent, font, density and radius once; users without a personal
choice follow it. These tests hold the contract: only allowed values survive,
a field left out of a PUT keeps its stored value (saving the appearance cannot
drop the logo, saving the logo cannot drop the appearance), ``null`` clears it,
and old payloads without the key still work.
No database: the data dir is a tmp path via ``OE_DATA_DIR``.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.core.app_branding import (
    APPEARANCE_OPTIONS,
    DEFAULT_BRANDING,
    read_branding,
    sanitise,
    sanitise_appearance,
    write_branding,
)
from app.core.branding_router import BrandingUpdate, WorkspaceAppearance, put_branding


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "OE_CLI_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))


def test_sanitise_keeps_only_allowed_values() -> None:
    raw = {"accent": "teal", "font": "comic-sans", "density": "compact", "radius": 7, "extra": "x"}
    assert sanitise_appearance(raw) == {"accent": "teal", "density": "compact"}
    assert sanitise_appearance({"accent": "pink"}) is None
    assert sanitise_appearance("teal") is None


def test_old_payload_without_appearance_reads_as_none() -> None:
    clean = sanitise({"mode": "text", "company_name": "Acme"})
    assert clean["appearance"] is None
    assert sanitise(None) == DEFAULT_BRANDING


def test_pydantic_schema_mirrors_the_allowed_values() -> None:
    for axis, allowed in APPEARANCE_OPTIONS.items():
        for value in allowed:
            WorkspaceAppearance(**{axis: value})
        with pytest.raises(ValidationError):
            WorkspaceAppearance(**{axis: "nope"})
    with pytest.raises(ValidationError):
        WorkspaceAppearance(colour="blue")


def test_appearance_alone_is_persisted_and_default_brand_kept() -> None:
    out = asyncio.run(put_branding(BrandingUpdate(appearance=WorkspaceAppearance(accent="violet", radius="round"))))
    assert out.mode == "default"
    assert out.appearance is not None
    assert out.appearance.accent == "violet"
    assert read_branding()["appearance"] == {"accent": "violet", "radius": "round"}


def test_appearance_alone_keeps_the_logo() -> None:
    write_branding({"mode": "text", "company_name": "Acme"})
    asyncio.run(put_branding(BrandingUpdate(appearance=WorkspaceAppearance(density="compact"))))
    stored = read_branding()
    assert stored["mode"] == "text"
    assert stored["company_name"] == "Acme"
    assert stored["appearance"] == {"density": "compact"}


def test_omitted_appearance_is_kept_and_null_clears_it() -> None:
    write_branding({"mode": "default", "appearance": {"accent": "amber"}})
    asyncio.run(put_branding(BrandingUpdate(mode="text", company_name="Acme")))
    stored = read_branding()
    assert stored["company_name"] == "Acme"
    assert stored["appearance"] == {"accent": "amber"}

    asyncio.run(put_branding(BrandingUpdate(mode="default", company_name="", appearance=None)))
    assert read_branding() == DEFAULT_BRANDING
