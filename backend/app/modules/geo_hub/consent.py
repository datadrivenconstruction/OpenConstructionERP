# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Whether, and where, a project address may leave the server for geocoding.

A site address is often a private person's home. Saving one used to send it
to the public OpenStreetMap services at once, without anyone being asked.
Now the installation is asked once: a manager answers allow (public
services), deny, or mirror (the deployer's own Nominatim). Until then
nothing is sent, neither for the automatic map pin nor for suggestions.

Environment switches set by the deployer take precedence over the answer:

* ``OE_GEOCODER_DISABLED=true`` sends nothing, whatever was answered.
* ``OE_GEOCODER_BASE_URL`` is the deployer's own Nominatim. Addresses go
  there without asking, because the deployer already chose where they go.
  Suggestions then use Photon only when ``OE_GEOCODER_PHOTON_URL`` names a
  Photon of their own too, so a private Nominatim never falls back to the
  public Photon.
* ``OE_GEOCODER_PHOTON_DISABLED=true`` keeps suggestions off Photon.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.modules.geo_hub.models import GeocodingConsent

State = Literal["unanswered", "allow", "deny", "mirror", "env_disabled", "env_mirror"]
Choice = Literal["allow", "deny", "mirror"]

PUBLIC_NOMINATIM_URL = "https://nominatim.openstreetmap.org"
PUBLIC_PHOTON_URL = "https://photon.komoot.io"
SCOPE = "installation"

# Several workers each hold a copy; a short lifetime bounds how long a
# changed answer takes to reach them. The worker that saves the answer
# drops its copy at once.
_CACHE_SECONDS = 30.0
_cache: tuple[float, tuple[str, str | None] | None] | None = None


@dataclass(frozen=True)
class Outbound:
    """Where geocoding traffic may go right now."""

    state: State
    nominatim_url: str | None
    photon_url: str | None

    @property
    def allowed(self) -> bool:
        return self.nominatim_url is not None


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _env_url(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip().rstrip("/")
    return value or None


def invalidate_cache() -> None:
    global _cache
    _cache = None


async def _read_choice(session: AsyncSession | None) -> tuple[str, str | None] | None:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    stmt = select(GeocodingConsent.choice, GeocodingConsent.mirror_url).where(GeocodingConsent.scope == SCOPE)
    if session is not None:
        row = (await session.execute(stmt)).first()
    else:
        async with async_session_factory() as own:
            row = (await own.execute(stmt)).first()
    value = (row[0], row[1]) if row is not None else None
    _cache = (now, value)
    return value


def decide(answer: tuple[str, str | None] | None) -> Outbound:
    """Combine the environment and the stored answer into a destination."""
    if _flag("OE_GEOCODER_DISABLED"):
        return Outbound("env_disabled", None, None)
    photon_off = _flag("OE_GEOCODER_PHOTON_DISABLED")
    env_photon = None if photon_off else _env_url("OE_GEOCODER_PHOTON_URL")
    env_base = _env_url("OE_GEOCODER_BASE_URL")
    if env_base is not None:
        return Outbound("env_mirror", env_base, env_photon)
    if answer is None:
        return Outbound("unanswered", None, None)
    choice, mirror_url = answer
    if choice == "allow":
        return Outbound("allow", PUBLIC_NOMINATIM_URL, None if photon_off else env_photon or PUBLIC_PHOTON_URL)
    if choice == "mirror" and mirror_url:
        return Outbound("mirror", mirror_url.rstrip("/"), env_photon)
    return Outbound("deny", None, None)


async def resolve_outbound(session: AsyncSession | None = None) -> Outbound:
    """Return where geocoding may go; fails closed when the answer is unreadable."""
    if _flag("OE_GEOCODER_DISABLED") or _env_url("OE_GEOCODER_BASE_URL") is not None:
        return decide(None)
    try:
        answer = await _read_choice(session)
    except Exception:  # noqa: BLE001 - a missing table or a dead session means "not asked"
        return Outbound("unanswered", None, None)
    return decide(answer)


async def save_choice(session: AsyncSession, choice: Choice, mirror_url: str | None, user_id: str | None) -> None:
    """Store the installation's answer; the caller commits."""
    row = (await session.execute(select(GeocodingConsent).where(GeocodingConsent.scope == SCOPE))).scalar_one_or_none()
    if row is None:
        row = GeocodingConsent(scope=SCOPE)
        session.add(row)
    row.choice = choice
    row.mirror_url = mirror_url if choice == "mirror" else None
    row.decided_by = user_id
    await session.flush()
    invalidate_cache()
