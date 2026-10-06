# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Can /match-elements match for this project, and if not, why not.

The page used to find out at the end of a run: the user picked a project,
uploaded a model, grouped it, ran the match, and only then learned that the
instance had no search service, no catalogue, or a catalogue in another
language. This module answers the same questions up front, from the same
sources the run reads, so the page can say what is missing and what to do
before anyone uploads anything.

Every probe here degrades instead of raising: a readiness answer that
throws would put the page back where it started.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service.region_language import (
    is_multi_language_group,
    project_countries,
    project_country,
    project_language,
    resolve_language,
)
from app.modules.match_elements import schemas
from app.modules.match_elements.qdrant_supervisor import serves_url

logger = logging.getLogger(__name__)

#: Seconds the whole store check (local server start + probe) may take. The
#: card sits above the wizard; a slow answer is worse than "not answering",
#: which the card can act on and the poll re-checks.
PROBE_BUDGET_S = 3.0
#: Per-request timeout of the client the probe opens against a server.
CLIENT_TIMEOUT_S = 2


@dataclass(frozen=True)
class StoreProbe:
    """What the ranker's catalogue store looks like right now.

    ``mode`` is ``"server"`` or ``"embedded"``; ``status`` is ``"ok"``,
    ``"client_missing"`` or ``"unreachable"``; ``collections`` holds the
    ``cwicr_*`` collection names present; ``location`` is the server URL or
    the embedded store's path.
    """

    mode: str
    status: str
    collections: frozenset[str]
    location: str = ""


def _probe_client(*, timeout: int) -> object:
    """A client for the store the ranker reads, with a short timeout on a server.

    The ranker's own client (``qdrant_adapter._get_client``) has the
    library's default timeout, so a server that accepts the connection and
    then stalls would hold the probe for that long. Against a server this
    opens a separate client at the SAME resolved address with ``timeout``.
    The embedded store is a local file that only one client may hold open,
    so there the ranker's client is reused.
    """
    from app.modules.costs.qdrant_adapter import _get_client, resolve_cwicr_target  # noqa: PLC0415

    target = resolve_cwicr_target()
    if not target.is_server:
        return _get_client()
    from qdrant_client import QdrantClient  # noqa: PLC0415

    return QdrantClient(url=target.location, timeout=timeout)


def probe_store() -> StoreProbe:
    """Open the CWICR store the ranker opens and list its collections.

    Resolves the store through ``qdrant_adapter.resolve_cwicr_target``, the
    resolution the search path uses, so the answer is about that store and
    not about some other Qdrant the instance can also reach. Synchronous,
    so callers run it in a thread under :data:`PROBE_BUDGET_S`.
    """
    from app.modules.costs.qdrant_adapter import resolve_cwicr_target  # noqa: PLC0415

    target = resolve_cwicr_target()
    mode = "server" if target.is_server else "embedded"
    if not _client_available():
        return StoreProbe(mode, "client_missing", frozenset(), target.location)
    try:
        client = _probe_client(timeout=CLIENT_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - degrade, never fail
        logger.info("match readiness: catalogue store did not open: %s", exc)
        return StoreProbe(mode, "unreachable", frozenset(), target.location)
    try:
        listed = client.get_collections()
    except Exception as exc:  # noqa: BLE001 - degrade, never fail
        logger.info("match readiness: catalogue store did not answer: %s", exc)
        return StoreProbe(mode, "unreachable", frozenset(), target.location)
    names = {
        str(getattr(c, "name", "") or "")
        for c in (getattr(listed, "collections", None) or [])
        if str(getattr(c, "name", "") or "").startswith("cwicr_")
    }
    return StoreProbe(mode, "ok", frozenset(names), target.location)


def _client_available() -> bool:
    """The supervisor's answer, so this card and the install route agree.

    It imports the package rather than locating it: a partial install can be
    found on disk and still fail to import.
    """
    from app.modules.match_elements.qdrant_supervisor import qdrant_client_available  # noqa: PLC0415

    return qdrant_client_available()


def ensure_local_server() -> bool:
    """Start the native search server if it is installed and stopped.

    The Qdrant card this page used to carry did this on every load through
    ``GET /qdrant/health``; readiness replaced that card, so it keeps the
    behaviour. The probe goes to the URL the binary serves, not to
    ``qdrant_url``, because the question is "is OUR server up". Returns
    whether the binary is installed.
    """
    from app.modules.match_elements.qdrant_supervisor import (  # noqa: PLC0415
        LOCAL_URL,
        ensure_qdrant_running,
        find_qdrant_binary,
    )

    if find_qdrant_binary() is None:
        return False
    try:
        health = ensure_qdrant_running(LOCAL_URL, spawn_if_installed=True)
    except Exception as exc:  # noqa: BLE001 - degrade, never fail
        logger.info("match readiness: local search server did not start: %s", exc)
        return True
    if getattr(health, "reachable", False) and getattr(health, "spawn_attempted", False):
        # Same as the health route: a fresh spawn clears the general vector
        # client's cached "not reachable".
        from app.core.vector import reset_qdrant_client  # noqa: PLC0415

        reset_qdrant_client()
    return True


def _module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def embedder_installed() -> bool:
    """True when the free BGE-M3 language model's library is importable.

    ``find_spec`` instead of an import: importing FlagEmbedding pulls in
    torch, which is too heavy for a status probe.
    """
    return _module_present("FlagEmbedding")


def demo_mode() -> bool:
    """The public hosted demo flag, read where the catalogue installer reads it."""
    from app.modules.costs.router import _demo_mode_enabled  # noqa: PLC0415

    return _demo_mode_enabled()


def collection_language(name: str) -> str | None:
    """``"cwicr_it_v3"`` -> ``"it"``; ``None`` for a name of another shape."""
    parts = name.split("_")
    if len(parts) < 2 or parts[0] != "cwicr" or not parts[1]:
        return None
    return parts[1].lower()


def recommend_catalogue(
    language: str | None,
    countries: tuple[str, ...] | list[str],
    installed_languages: set[str],
) -> schemas.RecommendedCatalogue | None:
    """The published catalogue that fits the project best.

    ``countries`` is the project's country, or a group's countries most
    likely first (:func:`region_language.project_countries`). A catalogue in
    the project's language is required when the project has one; among
    those, the earliest country in ``countries`` wins, so an East African
    project is offered Nairobi rather than the first English catalogue in
    the registry. A project with countries but no single language is
    offered the earliest of them that has a catalogue. Ties keep the
    registry's order.
    """
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES  # noqa: PLC0415

    order = [c.upper() for c in countries if c]
    if not language and not order:
        return None
    best = None
    best_key: tuple[int, int] | None = None
    for idx, cat in enumerate(CWICR_V3_CATALOGUES):
        if not cat.available:
            continue
        iso = cat.country_iso.upper()
        rank = order.index(iso) if iso in order else len(order)
        if language and cat.language != language:
            continue
        if not language and rank == len(order):
            continue
        key = (rank, idx)
        if best_key is None or key < best_key:
            best, best_key = cat, key
    if best is None:
        return None
    return schemas.RecommendedCatalogue(
        region=best.region,
        language=best.language,
        country_iso=best.country_iso,
        installed=best.language in installed_languages,
    )


async def _bound_catalogue(db: AsyncSession, project_id: uuid.UUID) -> str | None:
    """The project's current catalogue binding, read without creating a row."""
    from app.modules.projects.models import MatchProjectSettings  # noqa: PLC0415

    row = (
        await db.execute(
            select(MatchProjectSettings.cost_database_id).where(MatchProjectSettings.project_id == project_id)
        )
    ).first()
    return (row[0] or None) if row is not None else None


async def can_change_catalogue(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None,
) -> bool:
    """Whether this user may change the project's match settings.

    Asks the check the match-settings PATCH route itself runs
    (``projects.router._verify_project_owner``) instead of restating it, so
    the card never offers a switch the server would refuse.
    """
    from fastapi import HTTPException  # noqa: PLC0415

    from app.config import get_settings  # noqa: PLC0415
    from app.modules.projects.router import _verify_project_owner  # noqa: PLC0415
    from app.modules.projects.service import ProjectService  # noqa: PLC0415

    try:
        await _verify_project_owner(ProjectService(db, get_settings()), project_id, str(user_id), payload)
    except HTTPException:
        return False
    return True


def _check_store() -> tuple[bool, StoreProbe]:
    return ensure_local_server(), probe_store()


async def _bounded_store_check() -> tuple[bool, StoreProbe]:
    """``(binary_installed, store)`` within :data:`PROBE_BUDGET_S`.

    Past the budget the store counts as not answering. The thread keeps
    running (a thread cannot be cancelled) and finishes on its own; the
    card's poll asks again.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_check_store), timeout=PROBE_BUDGET_S)
    except TimeoutError:
        from app.modules.costs.qdrant_adapter import resolve_cwicr_target  # noqa: PLC0415

        target = resolve_cwicr_target()
        logger.info("match readiness: catalogue store check exceeded %.1fs", PROBE_BUDGET_S)
        # ``True`` for the binary: we do not know, and offering an install
        # that may already be running would be the wrong button.
        mode = "server" if target.is_server else "embedded"
        return True, StoreProbe(mode, "unreachable", frozenset(), target.location)


async def compute_readiness(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    may_change_catalogue: bool = False,
) -> schemas.MatchReadiness:
    """Answer :class:`schemas.MatchReadiness` for one project."""
    from app.modules.projects.models import Project  # noqa: PLC0415
    from app.modules.projects.service import project_has_settled_matches  # noqa: PLC0415

    project = await db.get(Project, project_id)
    region = ((project.region if project is not None else "") or "").strip()
    country_code = ((getattr(project, "country_code", None) if project is not None else None) or "").strip()
    language = project_language(region, country_code)
    country = project_country(region, country_code)

    binary_installed, store = await _bounded_store_check()
    installed_languages = {lang for lang in (collection_language(n) for n in store.collections) if lang}
    recommended = recommend_catalogue(language, project_countries(region, country_code), installed_languages)
    bound = await _bound_catalogue(db, project_id)

    blockers: list[schemas.ReadinessItem] = []
    warnings: list[schemas.ReadinessItem] = []
    rec_params = {"catalogue": recommended.region} if recommended is not None else {}

    if demo_mode() and not store.collections:
        blockers.append(schemas.ReadinessItem(code="demo_mode"))
    elif store.status == "client_missing":
        blockers.append(schemas.ReadinessItem(code="search_client_missing"))
    elif store.status == "unreachable":
        params: dict[str, str] = {}
        if store.mode == "server" and not binary_installed and serves_url(store.location):
            # Installing the native binary brings up exactly the server the
            # ranker is configured to read. Anywhere else it changes nothing,
            # so the page offers no button there.
            params["local_install"] = "available"
        blockers.append(schemas.ReadinessItem(code="search_unreachable", params=params))
    elif not store.collections:
        # The catalogue installer restores snapshots, which only a Qdrant
        # server can do; the embedded store can never be filled from here.
        code = "search_not_configured" if store.mode == "embedded" else "no_catalogue_installed"
        blockers.append(schemas.ReadinessItem(code=code, params=rec_params))
    else:
        if language and language not in installed_languages:
            warnings.append(
                schemas.ReadinessItem(
                    code="no_catalogue_for_language",
                    params={"language": language, **rec_params},
                )
            )
        if not language:
            # A group of countries with different languages is a choice the
            # user makes; anything else we could not read ("INTL", free
            # text, nothing at all) is said as exactly that, not guessed.
            code = "region_language_unknown" if is_multi_language_group(region) else "region_unknown"
            warnings.append(schemas.ReadinessItem(code=code, params={"region": region}))
        bound_language = resolve_language(bound) if bound else None
        if (
            bound
            and language
            and bound_language
            and bound_language != language
            and language in installed_languages
            and recommended is not None
            and await project_has_settled_matches(db, project_id)
        ):
            # Auto-bind keeps this binding because people already confirmed
            # matches against it (see ``auto_bind_dominant_catalogue``);
            # offer the switch instead of making it behind their back.
            warnings.append(
                schemas.ReadinessItem(
                    code="binding_language_differs",
                    params={
                        "bound": bound,
                        "bound_language": bound_language or "",
                        "language": language,
                        "catalogue": recommended.region,
                    },
                )
            )

    if not blockers and not embedder_installed():
        warnings.append(schemas.ReadinessItem(code="embedder_missing"))

    return schemas.MatchReadiness(
        can_match=not blockers,
        blockers=blockers,
        warnings=warnings,
        project_region=region,
        project_language=language,
        project_country=country,
        installed_languages=sorted(installed_languages),
        recommended_catalogue=recommended,
        bound_catalogue=bound,
        can_change_catalogue=may_change_catalogue,
    )


__all__ = [
    "CLIENT_TIMEOUT_S",
    "PROBE_BUDGET_S",
    "StoreProbe",
    "can_change_catalogue",
    "collection_language",
    "compute_readiness",
    "demo_mode",
    "embedder_installed",
    "ensure_local_server",
    "probe_store",
    "recommend_catalogue",
]
