# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which country pack speaks for one project.

The applied pack is install-wide: it co-brands the app, scopes listings and
seeds new projects. A project in another country still belongs to its own
market, so the screens that describe "the regional pack" for that project
resolve it here: the installed country pack whose market is the project's
country. The applied pack wins whenever it is for that same country, and a
project with no country, or a country no installed pack serves, falls back to
the applied pack. Nothing is applied or written; this is a read.

Ties between several packs for one country are broken by what the project
says about itself (its pack tag, its demo's flagship pack, its subdivision),
then national packs before regional ones, then a pack that names the market's
classification standard, then the slug. Country values stay in the manifests.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any


def _meta(pack: Any) -> dict[str, Any]:
    return getattr(pack, "metadata", None) or {}


def _country(pack: Any) -> str | None:
    code = getattr(pack, "market_country_code", None)
    return code.upper() if isinstance(code, str) and code else None


def _is_regional(pack: Any) -> bool:
    meta = _meta(pack)
    return bool(meta.get("subdivision") or meta.get("parent_pack") or meta.get("region_focus"))


def pick_project_pack(
    packs: Iterable[Any],
    *,
    country: str | None,
    active: Any | None = None,
    subdivision: str | None = None,
    preferred_slugs: Sequence[Collection[str]] = (),
) -> tuple[Any | None, str]:
    """Pick the pack for a project.

    Args:
        packs: Every discovered pack manifest.
        country: The project's ISO 3166-1 alpha-2 country, or ``None``.
        active: The install-wide applied pack, or ``None``.
        subdivision: The project's ISO 3166-2 subdivision, if known.
        preferred_slugs: Tiers of packs the project names itself, strongest
            tier first; packs within one tier rank by the rules below.

    Returns:
        ``(pack, source)`` where ``source`` is ``"project"`` when the pack was
        resolved from the project's country and ``"install"`` when it is the
        applied pack (or none at all).
    """
    code = (country or "").strip().upper()
    if len(code) != 2 or (active is not None and _country(active) == code):
        return active, "install"
    candidates = [p for p in packs if getattr(p, "type", None) == "country" and _country(p) == code]
    if not candidates:
        return active, "install"
    sub = (subdivision or "").strip().upper()

    def key(pack: Any) -> tuple[int, int, int, int, str]:
        meta = _meta(pack)
        pack_sub = str(meta.get("subdivision") or "").upper()
        return (
            next((i for i, tier in enumerate(preferred_slugs) if pack.slug in tier), len(preferred_slugs)),
            0 if sub and pack_sub == sub else 1,
            1 if _is_regional(pack) else 0,
            0 if meta.get("classification_standard") else 1,
            pack.slug,
        )

    return min(candidates, key=key), "project"


def project_country(country_code: Any, region: Any = None) -> str | None:
    """The project's market: ``country_code``, else a ``region`` that is itself an alpha-2 code.

    ``region`` is free text in older rows ("Middle East", "DACH", "UK"), so it
    only counts when it is a clean two-letter code; anything else names no market.
    """
    for value in (country_code, region):
        code = str(value or "").strip().upper()
        if len(code) == 2 and code.isascii() and code.isalpha():
            return code
    return None


def project_preferred_slugs(metadata: Any, flagship_by_demo: dict[str, list[str]]) -> list[list[str]]:
    """Tiers of packs a project names itself: its pack tag, then its demo's flagship packs."""
    md = metadata if isinstance(metadata, dict) else {}
    tiers: list[list[str]] = []
    tag = md.get("partner_pack")
    if isinstance(tag, str) and tag:
        tiers.append([tag])
    demo_id = md.get("demo_id")
    if isinstance(demo_id, str) and flagship_by_demo.get(demo_id):
        tiers.append(list(flagship_by_demo[demo_id]))
    return tiers
