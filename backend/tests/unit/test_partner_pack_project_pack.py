# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project resolves the country pack of its own market, not only the applied one."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.partner_pack.project_pack import pick_project_pack, project_preferred_slugs


@dataclass
class _Pack:
    slug: str
    country: str | None
    type: str = "country"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.country:
            self.metadata = {"country": self.country, **self.metadata}

    @property
    def market_country_code(self) -> str | None:
        code = str(self.metadata.get("country") or "").upper()
        return code if len(code) == 2 and code != "XX" else None


PACKS = [
    _Pack("hungary-hu", "HU"),
    _Pack("saudi-vision2030", "SA"),
    _Pack("bimhessen-de", "DE", metadata={"region_focus": "Hessen (DE-HE)"}),
    _Pack("germany-de", "DE", metadata={"classification_standard": "din276"}),
    _Pack("batimatech-ca", "CA"),
    _Pack("canada-ca", "CA", metadata={"classification_standard": "masterformat"}),
    _Pack("us-costdata", "US"),
    _Pack("us-texas", "US", metadata={"subdivision": "US-TX", "parent_pack": "us-costdata"}),
    _Pack("modular-prefab", "XX", type="industry"),
]
HU = PACKS[0]


def _slug(country: str | None, **kw: Any) -> tuple[str | None, str]:
    pack, source = pick_project_pack(PACKS, country=country, **kw)
    return (pack.slug if pack else None), source


def test_riyadh_project_under_another_applied_pack_gets_the_saudi_pack() -> None:
    assert _slug("SA", active=HU) == ("saudi-vision2030", "project")


def test_project_with_no_applied_pack_still_gets_its_country_pack() -> None:
    assert _slug("sa") == ("saudi-vision2030", "project")


def test_applied_pack_of_the_same_country_wins() -> None:
    assert _slug("HU", active=HU) == ("hungary-hu", "install")
    texas = PACKS[7]
    assert _slug("US", active=texas) == ("us-texas", "install")


@pytest.mark.parametrize("country", [None, "", "ZZ", "XX"])
def test_no_country_or_unserved_country_falls_back_to_the_applied_pack(country: str | None) -> None:
    assert _slug(country, active=HU) == ("hungary-hu", "install")
    assert _slug(country) == (None, "install")


def test_national_pack_beats_regional_and_classification_breaks_ties() -> None:
    assert _slug("DE")[0] == "germany-de"
    assert _slug("CA")[0] == "canada-ca"
    assert _slug("US")[0] == "us-costdata"


def test_subdivision_and_the_project_own_preference_pick_the_regional_pack() -> None:
    assert _slug("US", subdivision="US-TX")[0] == "us-texas"
    assert _slug("DE", preferred_slugs=[["bimhessen-de"]])[0] == "bimhessen-de"
    # A preferred pack for another country is ignored.
    assert _slug("CA", preferred_slugs=[["us-texas"]])[0] == "canada-ca"


def test_preferred_slugs_read_the_tag_then_the_demo_flagships() -> None:
    flagship = {"medical-us": ["us-texas"], "residential-berlin": ["bimhessen-de", "germany-de"]}
    assert project_preferred_slugs({"demo_id": "medical-us"}, flagship) == [["us-texas"]]
    assert project_preferred_slugs({"partner_pack": "x", "demo_id": "medical-us"}, flagship) == [["x"], ["us-texas"]]
    assert project_preferred_slugs(None, flagship) == []


def test_a_demo_flagged_by_two_packs_still_prefers_the_national_one() -> None:
    tiers = project_preferred_slugs(
        {"demo_id": "residential-berlin"}, {"residential-berlin": ["bimhessen-de", "germany-de"]}
    )
    assert _slug("DE", preferred_slugs=tiers)[0] == "germany-de"


# The demo bar's markets (frontend ``demoProfiles.ts``): demo -> (country, pack).
DEMO_BAR = {
    "full-showcase-riyadh": ("SA", "saudi-vision2030"),
    "residential-berlin": ("DE", "germany-de"),
    "office-london": ("GB", "uk-jct"),
    "medical-us": ("US", "us-texas"),
    "condo-toronto": ("CA", "canada-ca"),
    "school-paris": ("FR", "france-fr"),
    "office-shanghai": ("CN", "china-gbt50500"),
}


@pytest.mark.parametrize(("demo_id", "expected"), sorted(DEMO_BAR.items()))
def test_every_demo_bar_project_resolves_its_own_market_pack(demo_id: str, expected: tuple[str, str]) -> None:
    from app.core.demo_projects import DEMO_TEMPLATES, PACK_DEMO_PROJECT, _country_code_for
    from app.core.partner_pack.discovery import discover_packs

    country, slug = expected
    template = DEMO_TEMPLATES[demo_id]
    assert _country_code_for(template) == country
    packs = discover_packs()
    if slug not in {p.slug for p in packs}:
        pytest.skip(f"{slug} is not installed here")
    flagship: dict[str, list[str]] = {}
    for pack_slug, flagship_demo in PACK_DEMO_PROJECT.items():
        flagship.setdefault(flagship_demo, []).append(pack_slug)
    pack, source = pick_project_pack(
        packs,
        country=country,
        active=HU,
        subdivision=template.subdivision_code,
        preferred_slugs=project_preferred_slugs({"demo_id": demo_id}, flagship),
    )
    assert (pack.slug, source) == (slug, "project")


class _Session:
    def __init__(self, project: Any) -> None:
        self.project = project

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self.project


@pytest.mark.asyncio
async def test_current_endpoint_answers_with_the_project_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    import uuid
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.core.partner_pack import router as pack_router

    sa = PACKS[1]
    sa.to_public_dict = lambda: {"slug": sa.slug}  # type: ignore[attr-defined]
    HU.to_public_dict = lambda: {"slug": HU.slug}  # type: ignore[attr-defined]
    seen: list[str] = []

    async def _access(project_id: Any, user_id: str, _session: Any) -> None:
        seen.append(user_id)

    monkeypatch.setattr(pack_router, "verify_project_access", _access)
    monkeypatch.setattr(pack_router, "discover_packs", lambda: PACKS)
    monkeypatch.setattr(pack_router, "get_active_pack", lambda: HU)
    riyadh = SimpleNamespace(country_code="SA", subdivision_code=None, metadata_={"demo_id": "full-showcase-riyadh"})
    pid = uuid.uuid4()

    out = await pack_router.current_pack(_Session(riyadh), "u1", pid)
    assert out == {"active": True, "source": "project", "manifest": {"slug": "saudi-vision2030"}}
    assert seen == ["u1"]
    install = await pack_router.current_pack(_Session(riyadh), "u1", None)
    assert install["source"] == "install"
    assert install["manifest"] == {"slug": "hungary-hu"}
    with pytest.raises(HTTPException):
        await pack_router.current_pack(_Session(None), "u1", pid)
