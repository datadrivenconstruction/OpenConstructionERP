"""One-click full-workspace installer for a partner pack.

Implements the orchestration endpoint described in
``docs/country-pack-oneclick/DESIGN.md`` §5. A single admin call installs an
entire localized workspace for a pack:

    1. apply_pack   - enable the pack's modules, co-brand, persist defaults.
    2. locale       - surface the pack's default locale (front-end activates it).
    3. cost_db      - load the relational CWICR cost DB for the pack's regions.
    4. vector_db    - build the semantic vector DB for those regions.
    5. demos        - install up to N fully-worked country demo projects.

Every step is **fail-soft**: a step that errors is reported with
``status="error"`` (or ``"skipped"`` for graceful degradation such as a missing
embedding model) and the orchestrator carries on. The call never returns 500
because one step failed - it always returns the §5 response object so the
front-end checklist can render exactly what happened.

The slug → ``load-cwicr`` db_id resolution follows §5.1 (city-suffix index built
from ``_REGION_CURRENCY``); see :func:`resolve_cwicr_db_id`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Request / response models ────────────────────────────────────────────────


class FullInstallRequest(BaseModel):
    """Body for ``POST /api/v1/partner-pack/full-install``."""

    slug: str = Field(..., description="Partner-pack slug to install (required).")
    set_locale: bool = Field(
        default=True,
        description="Surface the pack's default locale as the workspace locale.",
    )
    install_cost_db: bool = Field(
        default=True,
        description="Load the relational CWICR cost DB for the pack's region(s).",
    )
    vectorize: bool = Field(
        default=True,
        description="Build the semantic vector DB for the loaded region(s).",
    )
    confirm_disables: bool = Field(
        default=False,
        description="Allow the apply step to DISABLE modules the pack wants hidden.",
    )
    demo_count: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Install up to N country demo projects (flagship first).",
    )


class StepResult(BaseModel):
    """One entry in the §5 response ``steps`` list."""

    step: str
    status: str  # "ok" | "error" | "skipped"
    detail: dict[str, Any] = Field(default_factory=dict)


class FullInstallResponse(BaseModel):
    """§5 response object."""

    slug: str
    ok: bool
    steps: list[StepResult]


# ── §5.1 CWICR slug → db_id resolver ─────────────────────────────────────────

# Aliases for city tokens that don't match the ``_REGION_CURRENCY`` suffix
# exactly. Keys are the slug's last segment (lowercased); values are the
# canonical ``load-cwicr`` db_id. Kept tiny and explicit so a reader can see
# every fudge:
#   * muenchen / munchen - German transliterations of the ``DE_MUNICH`` token.
#   * gbp - the UK-wide ``cwicr-uk-gbp`` slug has no city; the live UK
#     catalogue loads under ``GB_LONDON`` (DESIGN §5.1 "known live ids").
_CITY_TOKEN_ALIASES: dict[str, str] = {
    "muenchen": "DE_MUNICH",
    "munchen": "DE_MUNICH",
    "gbp": "GB_LONDON",
}


def _build_city_index() -> dict[str, str]:
    """Build the ``{city_token: db_id}`` index from ``_REGION_CURRENCY`` (§5.1).

    Each ``_REGION_CURRENCY`` key is ``<COUNTRY>_<CITY>``; we split on ``_`` and
    take the segment *after* the country prefix as the city token (lowercased),
    mapping it back to the full db_id. ``USA_USD`` → ``{"usd": "USA_USD"}``,
    ``DE_BERLIN`` → ``{"berlin": "DE_BERLIN"}``, etc. On a (currently
    non-existent) token collision the first key wins, which is deterministic
    because the source map is a literal dict.
    """
    from app.modules.costs.router import _REGION_CURRENCY

    index: dict[str, str] = {}
    for db_id in _REGION_CURRENCY:
        parts = db_id.split("_")
        if len(parts) < 2:
            continue
        token = parts[-1].lower()
        index.setdefault(token, db_id)
    return index


def resolve_cwicr_db_id(slug: str) -> str | None:
    """Resolve a CWICR marketplace slug to a ``load-cwicr`` db_id (§5.1).

    Pack slugs are ``cwicr-<lang>-<city>`` (the lang token is unreliable -
    ``eng``/``fra`` both mean Canada), so we match on the slug's **last**
    segment against the city-suffix index, falling back to the explicit alias
    map. Returns ``None`` when the slug resolves to no known live region (e.g.
    ``cwicr-fra-montreal``, ``cwicr-eng-wellington`` - no CWICR data yet); the
    caller reports those in ``detail.skipped``.
    """
    token = (slug or "").strip().lower().rsplit("-", 1)[-1]
    if not token:
        return None
    index = _build_city_index()
    if token in index:
        return index[token]
    return _CITY_TOKEN_ALIASES.get(token)


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def _step_apply_pack(
    slug: str,
    app: FastAPI | None,
    actor: str | None,
    *,
    confirm_disables: bool = False,
) -> StepResult:
    """Step 1 - apply the pack (modules + branding + defaults), no demo."""
    from app.core.partner_pack.apply import apply_pack

    res = await apply_pack(
        slug,
        confirm_disables=confirm_disables,
        install_demo=False,  # we install demos ourselves in step 5
        actor=actor,
        app=app,
    )
    effects = res.get("effects", {})
    enabled = effects.get("modules_enabled", []) or []
    disabled = effects.get("modules_disabled", []) or []
    return StepResult(
        step="apply_pack",
        status="ok",
        detail={"modules_enabled": len(enabled), "modules_disabled": len(disabled)},
    )


def _step_locale(slug: str) -> StepResult:
    """Step 2 - record the pack's default locale (front-end activates it)."""
    from app.core.partner_pack.discovery import get_pack_by_slug

    m = get_pack_by_slug(slug)
    locale = m.default_locale if m else None
    if not locale:
        return StepResult(step="locale", status="skipped", detail={"reason": "no default locale"})
    return StepResult(step="locale", status="ok", detail={"locale": locale})


async def _step_cost_db(slug: str) -> tuple[StepResult, list[str]]:
    """Step 3 - load the CWICR cost DB for each resolvable region.

    Returns the step result and the list of db_ids that were actually loaded
    (so step 4 can vectorize exactly those regions). Fail-soft: a per-region
    error is recorded in ``detail.errors`` and never aborts the rest.
    """
    from app.core.partner_pack.discovery import get_pack_by_slug
    from app.database import async_session_factory
    from app.modules.costs.router import load_cwicr_region

    m = get_pack_by_slug(slug)
    regions = list(m.cwicr_regions or []) if m else []

    loaded: list[str] = []
    items = 0
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    for region_slug in regions:
        db_id = resolve_cwicr_db_id(region_slug)
        if not db_id:
            skipped.append(region_slug)
            continue
        if db_id in loaded:
            # Two slugs resolving to the same live id (e.g. both UK slugs) -
            # load once.
            continue
        try:
            async with async_session_factory() as session:
                res = await load_cwicr_region(db_id, session)
                await session.commit()
            # The loader returns either freshly imported or already-loaded
            # counts; surface whichever is meaningful as the per-region total.
            count = int(res.get("total_items") or res.get("imported") or 0)
            items += count
            loaded.append(db_id)
        except Exception as exc:  # noqa: BLE001 - fail-soft per region
            logger.warning("full-install cost_db: region %s (%s) failed: %s", region_slug, db_id, exc)
            errors.append({"region": region_slug, "db_id": db_id, "error": str(exc)})

    detail: dict[str, Any] = {"regions": loaded, "items": items}
    if skipped:
        detail["skipped"] = skipped
    if errors:
        detail["errors"] = errors

    if loaded:
        status = "ok"
    elif skipped or errors:
        status = "skipped"
    else:
        # The pack declared no cwicr_regions at all.
        status = "skipped"
        detail.setdefault("reason", "no cwicr_regions declared")
    return StepResult(step="cost_db", status=status, detail=detail), loaded


async def _step_vector_db(loaded_regions: list[str]) -> StepResult:
    """Step 4 - vectorize each region loaded in step 3 (graceful degradation)."""
    from fastapi.responses import JSONResponse

    from app.database import async_session_factory
    from app.modules.costs.router import vectorize_region

    if not loaded_regions:
        return StepResult(
            step="vector_db",
            status="skipped",
            detail={"reason": "no regions loaded"},
        )

    vectors = 0
    done: list[str] = []
    degraded: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for db_id in loaded_regions:
        try:
            async with async_session_factory() as session:
                res = await vectorize_region(session, region=db_id)
                await session.commit()
            # ``vectorize_region`` returns a JSONResponse (503) when the vector
            # backend / embedding model is unavailable - that's acceptable
            # degradation, not a hard error.
            if isinstance(res, JSONResponse):
                reason = "vector backend unavailable"
                body = getattr(res, "body", None)
                if body:
                    try:
                        import json as _json

                        reason = _json.loads(body).get("message", reason)
                    except Exception:  # noqa: BLE001 - best-effort message
                        pass
                degraded.append({"region": db_id, "reason": reason})
                continue
            vectors += int(res.get("indexed") or 0)
            done.append(db_id)
        except Exception as exc:  # noqa: BLE001 - fail-soft per region
            logger.warning("full-install vector_db: region %s failed: %s", db_id, exc)
            errors.append({"region": db_id, "error": str(exc)})

    detail: dict[str, Any] = {"regions": done, "vectors": vectors}
    if degraded:
        detail["degraded"] = degraded
    if errors:
        detail["errors"] = errors

    if done:
        status = "ok"
    else:
        # Nothing indexed: either the model was unavailable (degraded) or every
        # region errored. Both surface as "skipped" so the call stays soft.
        status = "skipped"
    return StepResult(step="vector_db", status=status, detail=detail)


def _pack_country(slug: str) -> str | None:
    """Derive the pack's ISO-3166 country from its flagship demo's catalog row.

    ``PACK_DEMO_PROJECT[slug]`` → flagship demo_id → its ``DEMO_CATALOG`` row →
    ``country``. Returns ``None`` if the pack has no mapped demo or the row
    carries no country.
    """
    from app.core.demo_projects import DEMO_CATALOG, PACK_DEMO_PROJECT

    flagship = PACK_DEMO_PROJECT.get(slug)
    if not flagship:
        return None
    row = next((c for c in DEMO_CATALOG if c.get("demo_id") == flagship), None)
    if not row:
        return None
    return (row.get("country") or "").strip() or None


def _demo_install_list(slug: str, demo_count: int, country_fill: bool = True) -> list[str]:
    """Build the ordered, de-duplicated demo install list for the pack.

    A pack's manifest may declare an explicit ``demo_template_ids`` list. When
    present, those ids (in order, de-duplicated, filtered to ids that resolve to
    a loaded ``DemoTemplate``) are used verbatim - this guarantees every pack can
    pin exactly the market-appropriate demos it ships, even when no second demo
    shares the flagship's country (e.g. the cross-region modular / renewables
    packs). When the manifest declares none, fall back to the historical
    behaviour: flagship (``PACK_DEMO_PROJECT[slug]``) first, then every other
    ``DEMO_CATALOG`` demo sharing the flagship's ``country``. The result is
    truncated to ``demo_count``.

    Args:
        slug: The pack slug to build the install list for.
        demo_count: Maximum number of demos to return.
        country_fill: When True (default) and the manifest declares no explicit
            ``demo_template_ids``, the flagship is padded with other demos
            sharing its country. When False, the list is restricted to exactly
            what the pack pins - the manifest's ``demo_template_ids`` or, if it
            declares none, only the single ``PACK_DEMO_PROJECT[slug]`` flagship.
            Use False to seed a pack's own project(s) and nothing else.
    """
    from app.core.demo_projects import DEMO_CATALOG, DEMO_TEMPLATES, PACK_DEMO_PROJECT
    from app.core.partner_pack.discovery import get_pack_by_slug

    if demo_count <= 0:
        return []

    # Prefer the manifest's explicit demo_template_ids when declared. Only keep
    # ids that resolve to a real template so a typo never seeds a phantom demo.
    m = get_pack_by_slug(slug)
    explicit = list(getattr(m, "demo_template_ids", []) or []) if m else []
    if explicit:
        ordered: list[str] = []
        for demo_id in explicit:
            if demo_id in DEMO_TEMPLATES and demo_id not in ordered:
                ordered.append(demo_id)
        if ordered:
            return ordered[:demo_count]

    flagship = PACK_DEMO_PROJECT.get(slug)

    # Pack-only mode: return just the flagship, never the country fill.
    if not country_fill:
        return [flagship][:demo_count] if flagship else []

    country = _pack_country(slug)

    ordered = []
    if flagship:
        ordered.append(flagship)
    if country:
        for row in DEMO_CATALOG:
            demo_id = row.get("demo_id")
            if demo_id and demo_id not in ordered and (row.get("country") or "").strip() == country:
                ordered.append(demo_id)
    return ordered[:demo_count]


async def _step_demos(slug: str, demo_count: int) -> StepResult:
    """Step 5 - install the pack's country demos (idempotent, fail-soft)."""
    from app.core.demo_projects import install_demo_project
    from app.database import async_session_factory

    install_ids = _demo_install_list(slug, demo_count)
    if not install_ids:
        return StepResult(
            step="demos",
            status="skipped",
            detail={"reason": "no demos mapped for pack", "installed": []},
        )

    installed: list[str] = []
    errors: list[dict[str, str]] = []

    for demo_id in install_ids:
        try:
            async with async_session_factory() as session:
                await install_demo_project(session, demo_id, partner_pack=slug)
                await session.commit()
            installed.append(demo_id)
        except Exception as exc:  # noqa: BLE001 - one bad demo never aborts the rest
            logger.warning("full-install demos: demo %s failed: %s", demo_id, exc)
            errors.append({"demo_id": demo_id, "error": str(exc)})

    detail: dict[str, Any] = {"installed": installed}
    if errors:
        detail["errors"] = errors
    status = "ok" if installed else "error"
    return StepResult(step="demos", status=status, detail=detail)


def _soft(step_name: str, exc: Exception) -> StepResult:
    """Build a fail-soft ``status="error"`` result for an unexpected raise.

    The individual ``_step_*`` helpers already fail-soft internally; this is the
    outer guard so an unexpected error (e.g. an import blowing up) still yields a
    ``status="error"`` step instead of 500-ing the whole call (DESIGN §5).
    """
    logger.warning("full-install step %s raised: %s", step_name, exc)
    return StepResult(step=step_name, status="error", detail={"error": str(exc)})


# ── Streaming progress orchestrator (Modules-page pack activation) ───────────
#
# The batch ``full_install`` above runs every step server-side and returns one
# response object; the onboarding picker renders that as a checklist after the
# fact. The Modules page wants a *live* progress bar, so we expose the very same
# orchestration as an async generator that yields one event per step boundary.
# Each step reuses the identical ``_step_*`` helpers and per-region loaders, so
# behaviour (idempotency + fail-soft degradation) is byte-for-byte the same as
# the batch path; only the reporting changes.
#
# The ordered step ids the stream emits. ``resources`` is a reporting-only step:
# CWICR work items carry their labour/material/equipment breakdown in the same
# parquet (``..._workitems_costs_resources_...``), so loading the work catalog
# already loads the resource database in one pass. We surface the embedded
# resource count as its own progress row (the founder asked for a "Load
# resources (N)" step) without re-reading the file.
STREAM_STEPS: list[str] = [
    "apply_pack",
    "locale",
    "cost_db",
    "resources",
    "vector_db",
    "demos",
]


async def _step_cost_db_detailed(slug: str) -> tuple[StepResult, list[str], int]:
    """Load the CWICR cost DB and also return the embedded resource count.

    Same load path as :func:`_step_cost_db` (one parquet read per resolvable
    region, idempotent skip when already loaded) but additionally sums the
    ``resource_components`` each region reports so the streaming installer can
    render a distinct "Load resources" progress row. Returns
    ``(step_result, loaded_db_ids, resource_count)``.
    """
    from app.core.partner_pack.discovery import get_pack_by_slug
    from app.database import async_session_factory
    from app.modules.costs.router import load_cwicr_region

    m = get_pack_by_slug(slug)
    regions = list(m.cwicr_regions or []) if m else []

    loaded: list[str] = []
    items = 0
    resources = 0
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    for region_slug in regions:
        db_id = resolve_cwicr_db_id(region_slug)
        if not db_id:
            skipped.append(region_slug)
            continue
        if db_id in loaded:
            # Two slugs resolving to the same live id (e.g. both UK slugs) - load once.
            continue
        try:
            async with async_session_factory() as session:
                res = await load_cwicr_region(db_id, session)
                await session.commit()
            count = int(res.get("total_items") or res.get("imported") or 0)
            items += count
            resources += int(res.get("resource_components") or 0)
            loaded.append(db_id)
        except Exception as exc:  # noqa: BLE001 - fail-soft per region
            logger.warning("full-install cost_db: region %s (%s) failed: %s", region_slug, db_id, exc)
            errors.append({"region": region_slug, "db_id": db_id, "error": str(exc)})

    detail: dict[str, Any] = {"regions": loaded, "items": items, "resources": resources}
    if skipped:
        detail["skipped"] = skipped
    if errors:
        detail["errors"] = errors

    if loaded:
        status = "ok"
    elif skipped or errors:
        status = "skipped"
    else:
        status = "skipped"
        detail.setdefault("reason", "no cwicr_regions declared")
    return StepResult(step="cost_db", status=status, detail=detail), loaded, resources


def _sse(event: str, data: dict[str, Any]) -> str:
    """Format one Server-Sent-Events frame (mirrors erp_chat._sse)."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def full_install_stream(
    req: FullInstallRequest,
    *,
    app: FastAPI | None = None,
    actor: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE frames driving a live progress bar for a pack activation.

    Emits, in order:
        * ``start``         - ``{slug, steps: [{step, label_key, label}], total}``
        * ``step_start``    - ``{step, index, total}`` before each step runs
        * ``step_done``     - ``{step, index, total, status, detail}`` after it
        * ``done``          - ``{slug, ok, steps: [...full StepResult...]}``

    Every step is fail-soft exactly like :func:`full_install`; a step that errors
    is reported with ``status="error"``/``"skipped"`` and the stream continues,
    so the bar always reaches ``done``. Steps the pack does not include (no
    locale, no cwicr_regions, demos disabled) are emitted as ``skipped`` so the
    frontend can grey them out rather than spin forever.
    """
    slug = req.slug

    # Resolve the active step list up front. ``resources`` rides along with
    # ``cost_db`` (same load); we still announce it so the bar shows both rows.
    active_steps: list[str] = ["apply_pack"]
    if req.set_locale:
        active_steps.append("locale")
    if req.install_cost_db:
        active_steps.extend(["cost_db", "resources"])
    if req.vectorize:
        active_steps.append("vector_db")
    active_steps.append("demos")
    total = len(active_steps)

    # Stable label keys so the frontend can localize; English fallbacks travel
    # in ``label`` for clients that don't have the key yet.
    labels: dict[str, tuple[str, str]] = {
        "apply_pack": ("modules.pp_step_apply", "Apply preset"),
        "locale": ("modules.pp_step_locale", "Install language"),
        "cost_db": ("modules.pp_step_cost_db", "Load work catalog"),
        "resources": ("modules.pp_step_resources", "Load resources"),
        "vector_db": ("modules.pp_step_vector_db", "Build vector index"),
        "demos": ("modules.pp_step_demos", "Create demo project"),
    }

    yield _sse(
        "start",
        {
            "slug": slug,
            "total": total,
            "steps": [{"step": s, "label_key": labels[s][0], "label": labels[s][1]} for s in active_steps],
        },
    )

    results: list[StepResult] = []
    loaded_regions: list[str] = []
    apply_ok = False
    cost_resources = 0

    for index, step in enumerate(active_steps):
        yield _sse("step_start", {"step": step, "index": index, "total": total})
        try:
            if step == "apply_pack":
                result = await _step_apply_pack(slug, app, actor, confirm_disables=req.confirm_disables)
                apply_ok = result.status == "ok"
            elif step == "locale":
                result = _step_locale(slug)
            elif step == "cost_db":
                result, loaded_regions, cost_resources = await _step_cost_db_detailed(slug)
            elif step == "resources":
                # Reporting-only: resources were imported with the work catalog.
                if loaded_regions:
                    result = StepResult(
                        step="resources",
                        status="ok",
                        detail={"resources": cost_resources, "regions": loaded_regions},
                    )
                else:
                    result = StepResult(
                        step="resources",
                        status="skipped",
                        detail={"reason": "no cost database loaded", "resources": 0},
                    )
            elif step == "vector_db":
                result = await _step_vector_db(loaded_regions)
            elif step == "demos":
                result = await _step_demos(slug, req.demo_count)
            else:  # pragma: no cover - defensive; active_steps is closed-set
                result = StepResult(step=step, status="skipped", detail={})
        except Exception as exc:  # noqa: BLE001 - per-step fail-soft, never abort the stream
            result = _soft(step, exc)

        results.append(result)
        yield _sse(
            "step_done",
            {
                "step": step,
                "index": index,
                "total": total,
                "status": result.status,
                "detail": result.detail,
            },
        )

    # ``ok`` means "everything we attempted succeeded". Unlike the batch
    # ``full_install`` (which hard-requires a demo), the in-app activate dialog
    # lets the admin opt out of demos and load packs that ship no cost data, so
    # a step that was intentionally skipped must not flip the whole run to
    # "partial". ``ok`` is therefore: apply succeeded AND no step ERRORED. A
    # gracefully skipped step (no regions, demos disabled, vector backend down)
    # is fine; only a real ``error`` (or a failed apply) makes it partial.
    any_error = any(r.status == "error" for r in results)
    ok = apply_ok and not any_error

    logger.info(
        "Partner-pack stream-install '%s': ok=%s steps=%s",
        slug,
        ok,
        {r.step: r.status for r in results},
    )
    yield _sse(
        "done",
        {
            "slug": slug,
            "ok": ok,
            "steps": [{"step": r.step, "status": r.status, "detail": r.detail} for r in results],
        },
    )


async def full_install(
    req: FullInstallRequest,
    *,
    app: FastAPI | None = None,
    actor: str | None = None,
) -> FullInstallResponse:
    """Run the five-step one-click install for ``req.slug`` (DESIGN §5).

    Each step is fully fail-soft; the call always returns the §5 response.
    ``ok`` is true iff apply_pack succeeded **and** at least one demo installed.
    """
    slug = req.slug
    steps: list[StepResult] = []

    # 1. apply_pack
    try:
        apply_result = await _step_apply_pack(slug, app, actor)
    except Exception as exc:  # noqa: BLE001 - top-level fail-soft per DESIGN §5
        apply_result = _soft("apply_pack", exc)
    steps.append(apply_result)

    # 2. locale
    if req.set_locale:
        try:
            steps.append(_step_locale(slug))
        except Exception as exc:  # noqa: BLE001
            steps.append(_soft("locale", exc))

    # 3. cost_db
    loaded_regions: list[str] = []
    if req.install_cost_db:
        try:
            cost_step, loaded_regions = await _step_cost_db(slug)
        except Exception as exc:  # noqa: BLE001
            cost_step = _soft("cost_db", exc)
        steps.append(cost_step)

    # 4. vector_db
    if req.vectorize:
        try:
            steps.append(await _step_vector_db(loaded_regions))
        except Exception as exc:  # noqa: BLE001
            steps.append(_soft("vector_db", exc))

    # 5. demos
    try:
        demos_step = await _step_demos(slug, req.demo_count)
    except Exception as exc:  # noqa: BLE001
        demos_step = _soft("demos", exc)
    steps.append(demos_step)

    apply_ok = apply_result.status == "ok"
    demos_ok = demos_step.status == "ok" and bool(demos_step.detail.get("installed"))
    ok = apply_ok and demos_ok

    logger.info(
        "Partner-pack full-install '%s': ok=%s steps=%s",
        slug,
        ok,
        {s.step: s.status for s in steps},
    )
    return FullInstallResponse(slug=slug, ok=ok, steps=steps)
