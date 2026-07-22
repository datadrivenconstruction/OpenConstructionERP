# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Catalog API routes.

The catalog stores **resources** - single-input items (one material, one
labour rate, one machine, etc.) with one price per region. Resources do
not have a material/labour/equipment breakdown because each resource
*already is* one of those - the kind is in ``resource_type``.

Resources are referenced by **cost positions** (work compositions) in
``oe_costs_item``, exposed at ``/api/v1/costs/``. A position's
``components[]`` array names the resources it consumes by ``code`` and
adds quantity / unit-rate / cost. So:

    /api/v1/costs/         - work positions (≈55k canonical, more with
                             regional price variants). The "work items"
                             you see referenced in legacy CSV columns
                             *are* these.
    /api/v1/catalog/       - leaf resources with prices. Each maps to
                             zero or more cost positions via the
                             ``components[].code`` field.

Use ``/api/v1/catalog/{resource_id}/used-by/`` to walk the relation in
the resource→positions direction (the inverse of ``components[]``).

Endpoints:
    GET  /           -- Search/list catalog resources (public, query params)
    GET  /stats      -- Counts by type and category
    GET  /regions    -- List loaded catalog regions with counts
    POST /import/{region} -- Download catalog from GitHub and import
    DELETE /region/{region} -- Remove all resources for a region
    PATCH /adjust-prices -- Bulk price adjustment by factor
    GET  /{resource_id}            -- Get single resource by ID
    GET  /{resource_id}/used-by/   -- Cost positions that reference this resource
    POST /           -- Create a custom resource (auth required)
    POST /extract    -- Extract resources from cost items (admin)
"""

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    OptionalUserPayload,
    RequirePermission,
    SessionDep,
)
from app.modules.catalog.schemas import (
    CatalogResourceCreate,
    CatalogResourceResponse,
    CatalogSearchResponse,
    CatalogStatsResponse,
)
from app.modules.catalog.service import CatalogResourceService
from app.modules.costs import base_registry

router = APIRouter(tags=["catalog"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CatalogResourceService:
    return CatalogResourceService(session)


def _fmt_price(value: float) -> str:
    """Serialise a price without lossy fixed-2dp truncation (CAT-003).

    Prices are stored as ``String(50)``. The previous code wrote
    ``round(x, 2)`` on every adjustment, so applying a factor N times
    compounded a sub-cent error per step and ``factor`` then ``1/factor``
    never restored the original. We keep full IEEE-754 precision and use
    ``repr``-grade formatting (``%.12g``) so round-trips stay stable while
    trailing-zero noise is still trimmed for display.
    """
    # %.12g keeps enough significant digits to survive repeated
    # multiply/divide cycles, then normalise -0.0 → 0.
    out = f"{value:.12g}"
    return "0" if out in ("-0", "-0.0") else out


def _normalise_band(base: float, lo: float, hi: float) -> tuple[float, float, float]:
    """Enforce the price-band invariant ``min <= base <= max`` (CAT-001).

    ``CatalogResourceCreate._check_price_band`` rejects an inverted /
    out-of-band resource at create time, but the bulk ``adjust-prices``
    and GitHub-import write paths bypassed that model validator, so an
    inverted band could still be *persisted* (a pre-existing inversion
    survives a uniform multiply; a CSV row may already be inverted).
    Every downstream "is the rate within band?" check then becomes
    meaningless.

    A band is only meaningful when both ``lo`` and ``hi`` are > 0 (0 is
    the documented "no band" sentinel, mirroring the create validator);
    single-price resources are left untouched. We *normalise* rather
    than reject so a bulk run / large import is not aborted by a few
    dirty rows: swap an inverted ``lo``/``hi``, then clamp ``base`` into
    ``[lo, hi]``. Returns the corrected ``(base, lo, hi)`` triple.
    """
    if lo > 0 and hi > 0:
        if lo > hi:
            lo, hi = hi, lo
        if base < lo:
            base = lo
        elif base > hi:
            base = hi
    return base, lo, hi


# ── Region-to-GitHub mapping ─────────────────────────────────────────────

# The 30 metro-coded regional catalogs DDC publishes, plus the authentic
# national / regional bases we generate locally from official government
# sources. Each key is the region id that names the catalog CSV
# (DDC_CWICR_<region>_Catalog.csv); the value is the repo folder used only as
# the GitHub fallback path (locally generated catalogs resolve from the source
# checkout in ``data/catalog/regions`` first), and follows the same
# uppercased-language-code convention as the published metros.
# Region id to the repo folder holding its resource-catalog CSV. Derived from
# the single-source base registry (app.modules.costs.base_registry) so the
# catalog download path, the cost-item parquet path and the /base-catalog API
# stay in lockstep. The 30 global-CWICR markets resolve to a nested
# ``CIS-Russia-GESN-FER-TER/<XX>___DDC_CWICR`` folder; each national base to its
# own folder root. National catalog CSVs still ship in ``data/catalog/regions``
# and resolve from the local checkout first, so the folder is a GitHub fallback.
REGION_MAP: dict[str, str] = {v.region: v.catalog_folder for v in base_registry.iter_variants()}

_GITHUB_BASE = "https://raw.githubusercontent.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR/main"

# Local cache for downloaded catalog CSVs. Shares the parent directory with the
# CWICR parquet cache in app.modules.costs.router so one folder holds all
# downloaded reference data, and a region imported once stays available offline.
_CATALOG_CACHE_DIR = Path.home() / ".openestimator" / "cache" / "catalog"
_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOCAL_CATALOG_DIRS = (
    _REPO_ROOT / "data" / "catalog" / "regions",
    Path.cwd() / "data" / "catalog" / "regions",
)
_LOCAL_CATALOG_FILE_ALIASES: dict[str, tuple[str, ...]] = {
    # The authentic China resource CSV was regenerated under the legacy
    # language-prefixed catalogue filename. Resolve the product id without
    # duplicating the generated CSV/XLSX artifacts.
    "ZH_CHINA": ("ZH_SHANGHAI",),
}

# Downloaded market-catalog CSVs (one national base repriced into a market).
# Cached per base under ``markets/<base_region>/`` because the SAME market token
# holds different prices for each base (China's London file is Chinese resources
# at London prices; Greece's London file is Greek resources at London prices).
_MARKET_CATALOG_CACHE_DIR = _CATALOG_CACHE_DIR / "markets"


def _read_region_catalog_csv(region: str, folder: str) -> tuple[bytes, str]:
    """Resolve the catalog CSV bytes for one region.

    The regional CWICR catalogs are not shipped inside the package; they are
    downloaded on demand from the public CWICR data repository and cached
    locally, so a region imported once stays available without network.

    Lookup order:
      1. Local cache dir (a previous successful download).
      2. Repository checkout (`data/catalog/regions`) for locally generated
         catalogues that have not been published upstream yet.
      3. GitHub download (cached on success for the next offline run).

    Runs in a worker thread (blocking I/O). Returns ``(raw_bytes, source)``
    where ``source`` is ``cache`` / ``github``. Raises ``RuntimeError`` with
    an actionable message when both fail.
    """
    # The national bases export their catalog CSV under a short country token
    # (e.g. TR_NATIONAL -> DDC_CWICR_TR_Catalog.csv) that differs from the
    # platform region id; the registry knows that token, so try it as a
    # fallback name after the region-id name and any explicit local alias.
    registry_token = base_registry.catalog_token(region)
    candidate_csv_names = (
        f"DDC_CWICR_{region}_Catalog.csv",
        *((f"DDC_CWICR_{registry_token}_Catalog.csv",) if registry_token and registry_token != region else ()),
        *(f"DDC_CWICR_{alias}_Catalog.csv" for alias in _LOCAL_CATALOG_FILE_ALIASES.get(region, ())),
    )
    csv_name = candidate_csv_names[0]

    # 1. Local cache from a previous download. The 1 KB floor skips a stuck
    #    0-byte file left by an interrupted write.
    for candidate_csv_name in candidate_csv_names:
        cached = _CATALOG_CACHE_DIR / candidate_csv_name
        try:
            if cached.is_file() and cached.stat().st_size > 1000:
                return cached.read_bytes(), "cache"
        except OSError:
            logger.warning("Unreadable cached catalog CSV at %s, ignoring", cached)

    # 2. Local generated catalogues in a source checkout. This keeps new
    # authentic bases usable before they are mirrored to the public DDC repo.
    for local_dir in _LOCAL_CATALOG_DIRS:
        for candidate_csv_name in candidate_csv_names:
            local_csv = local_dir / candidate_csv_name
            try:
                if local_csv.is_file() and local_csv.stat().st_size > 1000:
                    return local_csv.read_bytes(), "local"
            except OSError:
                logger.warning("Unreadable local catalog CSV at %s, ignoring", local_csv)

    # 3. GitHub download (cached on success for the next offline run).
    # Belt-and-braces: `folder` and `region` come from the static REGION_MAP
    # only (already validated by the caller), but URL-quote them anyway and
    # verify the final URL still has the trusted host. This makes the trust
    # boundary explicit and silences CodeQL's `py/partial-ssrf` finding.
    import urllib.request
    from urllib.parse import quote, urlparse

    last_error: Exception | None = None
    last_url = ""
    for candidate_csv_name in candidate_csv_names:
        # ``safe='/'`` keeps the path separators in a nested base folder
        # (CIS-Russia-GESN-FER-TER/XX___DDC_CWICR) intact; the host is still
        # pinned below, so the SSRF trust boundary is unchanged.
        url = f"{_GITHUB_BASE}/{quote(folder, safe='/')}/{quote(candidate_csv_name, safe='')}"
        last_url = url
        if urlparse(url).netloc != "raw.githubusercontent.com":
            raise RuntimeError("Catalog source host is not allowed.")
        logger.info("Downloading catalog CSV: %s", url)

        req = urllib.request.Request(
            url,
            headers={"User-Agent": ("OpenConstructionERP (+https://datadrivenconstruction.io; DDC-CWICR-OE-2026)")},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - host pinned above
                raw_bytes = resp.read()
        except Exception as exc:
            logger.error("Failed to download catalog CSV from %s: %s", url, exc)
            last_error = exc
            continue

        # Cache under the canonical name for the next (possibly offline) run.
        try:
            _CATALOG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            (_CATALOG_CACHE_DIR / csv_name).write_bytes(raw_bytes)
        except OSError:
            logger.warning("Could not cache catalog CSV at %s", _CATALOG_CACHE_DIR / csv_name)
        return raw_bytes, "github"

    raise RuntimeError(
        f"Could not load the '{region}' resource catalog: it is not in the local "
        f"cache and the GitHub download failed "
        f"({last_error.__class__.__name__}: {last_error}). URL: {last_url}. Check that this server "
        f"can reach raw.githubusercontent.com, or place the CSV at {_CATALOG_CACHE_DIR / csv_name} "
        f"and retry."
    ) from last_error


# ── Market catalog reader (base repriced into a market) ──────────────────


def _read_market_catalog_csv(base_region: str, market_token: str) -> tuple[bytes, str]:
    """Resolve the bytes of one market catalog CSV for a national base.

    A market catalog lives under the base's own folder,
    ``<base_folder>/markets/DDC_CWICR_<market_token>_Catalog.csv``, where
    ``base_folder`` is resolved from the single-source base registry. Reuses the
    same cache-then-GitHub mechanism as :func:`_read_region_catalog_csv`, but the
    cache is scoped per base (the same market token carries different prices for
    each base). Runs in a worker thread (blocking I/O). Returns
    ``(raw_bytes, source)`` with ``source`` in ``cache`` / ``github``. Raises
    ``RuntimeError`` on an unknown base or a failed download.
    """
    base_folder = base_registry.github_catalog_folder(base_region)
    if not base_folder:
        raise RuntimeError(f"Unknown base region '{base_region}'; no catalog folder is registered for it.")

    csv_name = f"DDC_CWICR_{market_token}_Catalog.csv"
    cached = _MARKET_CATALOG_CACHE_DIR / base_region / csv_name

    # 1. Per-base local cache from a previous download (1 KB floor skips a stuck
    #    0-byte file left by an interrupted write).
    try:
        if cached.is_file() and cached.stat().st_size > 1000:
            return cached.read_bytes(), "cache"
    except OSError:
        logger.warning("Unreadable cached market CSV at %s, ignoring", cached)

    # 2. GitHub download (cached on success for the next offline run). ``folder``
    #    and ``market_token`` are validated by the caller, but URL-quote them and
    #    re-pin the host anyway so the SSRF trust boundary stays explicit.
    import urllib.request
    from urllib.parse import quote, urlparse

    url = f"{_GITHUB_BASE}/{quote(base_folder, safe='/')}/markets/{quote(csv_name, safe='')}"
    if urlparse(url).netloc != "raw.githubusercontent.com":
        raise RuntimeError("Catalog source host is not allowed.")
    logger.info("Downloading market catalog CSV: %s", url)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": ("OpenConstructionERP (+https://datadrivenconstruction.io; DDC-CWICR-OE-2026)")},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - host pinned above
            raw_bytes = resp.read()
    except Exception as exc:
        logger.error("Failed to download market catalog CSV from %s: %s", url, exc)
        raise RuntimeError(
            f"Could not download the '{market_token}' market catalog for base '{base_region}' "
            f"({exc.__class__.__name__}: {exc}). URL: {url}. Check that this server can reach "
            f"raw.githubusercontent.com and retry."
        ) from exc

    try:
        (_MARKET_CATALOG_CACHE_DIR / base_region).mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw_bytes)
    except OSError:
        logger.warning("Could not cache market CSV at %s", cached)
    return raw_bytes, "github"


async def fetch_market_catalog_rows(base_region: str, market_token: str) -> list[dict[str, Any]]:
    """Download + parse one market catalog CSV into a list of row dicts.

    Reuses the region-catalog CSV parse (``csv.DictReader``) but reads from the
    base's ``markets/`` subfolder and returns the parsed rows WITHOUT inserting
    any ``CatalogResource`` - the caller (the base-market reprice endpoint) folds
    the rows straight into the resource price sheet. Each market CSV downloads
    once and is cached per base. Raises ``RuntimeError`` on download failure.
    """
    import csv
    import io

    raw_bytes, source = await asyncio.to_thread(_read_market_catalog_csv, base_region, market_token)
    logger.info(
        "Market catalog for %s/%s resolved from %s (%d bytes)",
        base_region,
        market_token,
        source,
        len(raw_bytes),
    )
    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


# ── Import from bundled data / cache / GitHub ────────────────────────────


@router.post("/import/{region}")
async def import_catalog_from_github(
    region: str,
    session: SessionDep,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("catalog.create")),
) -> dict[str, Any]:
    """Import the resource catalog CSV for a region into the DB.

    Resolves the CSV from the local cache first, then downloads it from the
    public CWICR data repository and caches it, so a region imported once
    stays available without network access.

    Accepts any of the region ids in ``REGION_MAP``: the 30 metro locales
    (AR_DUBAI, AU_SYDNEY, BG_SOFIA, CS_PRAGUE, DE_BERLIN, ENG_TORONTO,
    SP_BARCELONA, FR_PARIS, HI_MUMBAI, HR_ZAGREB, ID_JAKARTA, IT_ROME,
    JA_TOKYO, KO_SEOUL, MX_MEXICOCITY, NG_LAGOS, NL_AMSTERDAM, NZ_AUCKLAND,
    PL_WARSAW, PT_SAOPAULO, RO_BUCHAREST, RU_STPETERSBURG, SV_STOCKHOLM,
    TH_BANGKOK, TR_ISTANBUL, TR_NATIONAL, UK_GBP, USA_USD, VI_HANOI,
    ZA_JOHANNESBURG, ZH_SHANGHAI, ZH_CHINA) plus the authentic national /
    regional bases (BR_NATIONAL, ES_ANDALUCIA, IT_TOSCANA, GR_NATIONAL). The
    codeless coefficient bases VN_NATIONAL and ID_NATIONAL are recognised keys
    but have no resource catalog to import.
    """
    import csv
    import io

    folder = REGION_MAP.get(region)
    if folder is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown region '{region}'. Valid regions: {', '.join(sorted(REGION_MAP))}",
        )

    # Offload blocking file/network I/O to a worker thread so the event loop
    # stays responsive during the 60-second download window.
    try:
        raw_bytes, csv_source = await asyncio.to_thread(_read_region_catalog_csv, region, folder)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    logger.info("Catalog CSV for %s resolved from %s (%d bytes)", region, csv_source, len(raw_bytes))

    text = raw_bytes.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    from sqlalchemy import delete as sql_delete

    from app.modules.catalog.models import CatalogResource

    # Delete existing resources for this region (clean reimport)
    await session.execute(sql_delete(CatalogResource).where(CatalogResource.region == region))
    await session.flush()

    imported = 0
    skipped = 0

    _MAPPED_FIELDS = {
        "resource_code",
        "name",
        "type",
        "category",
        "unit",
        "price_avg",
        "price_min",
        "price_max",
        "currency",
        "usage_count",
    }

    batch: list[CatalogResource] = []
    BATCH_SIZE = 500

    for row in reader:
        resource_code = (row.get("resource_code") or "").strip()
        if not resource_code:
            skipped += 1
            continue

        # Build specifications from unmapped fields
        specifications: dict[str, Any] = {}
        for key, val in row.items():
            if key and key not in _MAPPED_FIELDS and val:
                specifications[key] = val

        try:
            # CAT-001: normalise the price band on import - a CSV row may
            # ship price_min > price_max (or an avg outside the band),
            # and this write path bypasses the create-time validator.
            _b, _lo, _hi = _normalise_band(
                float(row.get("price_avg") or 0),
                float(row.get("price_min") or 0),
                float(row.get("price_max") or 0),
            )
            resource = CatalogResource(
                resource_code=resource_code,
                name=(row.get("name") or resource_code).strip()[:500],
                resource_type=(row.get("type") or "material").strip().lower(),
                category=(row.get("category") or "General").strip(),
                unit=(row.get("unit") or "unit").strip()[:20],
                # CAT-003: preserve source precision; do not truncate to
                # 2dp on import (compounds with later adjust-prices passes).
                base_price=_fmt_price(_b),
                min_price=_fmt_price(_lo),
                max_price=_fmt_price(_hi),
                currency=(row.get("currency") or "").strip(),
                usage_count=int(float(row.get("usage_count") or 0)),
                source="github_import",
                region=region,
                specifications=specifications,
                metadata_={},
            )
            batch.append(resource)
            imported += 1
        except (ValueError, TypeError):
            skipped += 1
            continue

        if len(batch) >= BATCH_SIZE:
            session.add_all(batch)
            await session.flush()
            batch.clear()

    if batch:
        session.add_all(batch)
        await session.flush()

    logger.info(
        "Catalog import complete for %s: %d imported, %d skipped",
        region,
        imported,
        skipped,
    )

    return {"imported": imported, "skipped": skipped, "region": region, "source": csv_source}


# ── List loaded regions ──────────────────────────────────────────────────


@router.get("/regions/")
async def list_catalog_regions(
    session: SessionDep,
) -> list[dict[str, Any]]:
    """List loaded catalog regions with resource counts."""
    from app.modules.catalog.repository import CatalogResourceRepository

    repo = CatalogResourceRepository(session)
    return await repo.stats_by_region()


# ── Delete region ────────────────────────────────────────────────────────


@router.delete("/region/{region}")
async def delete_catalog_region(
    region: str,
    session: SessionDep,
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("catalog.delete")),
) -> dict[str, Any]:
    """Remove all resources for a specific region."""
    from app.modules.catalog.repository import CatalogResourceRepository

    repo = CatalogResourceRepository(session)
    deleted = await repo.delete_by_region(region)
    logger.info("Deleted %d catalog resources for region %s", deleted, region)
    return {"deleted": deleted, "region": region}


# ── Bulk Price Adjustment ─────────────────────────────────────────────────


@router.patch(
    "/adjust-prices/",
    dependencies=[Depends(RequirePermission("catalog.create"))],
)
async def adjust_prices(
    session: SessionDep,
    _user_id: CurrentUserId,
    factor: float = Query(
        ..., gt=0, le=10, description="Multiplication factor (e.g. 1.05 for +5%), must be 0 < f ≤ 10"
    ),
    resource_type: str | None = Query(default=None, description="Filter by type: material, labor, equipment"),
    category: str | None = Query(default=None, description="Filter by category"),
    region: str | None = Query(default=None, description="Filter by region"),
) -> dict:
    """Adjust prices by a factor for filtered resources.

    Use cases:
    - Inflation adjustment: factor=1.05 (+5%)
    - Regional coefficient: factor=1.12 (Munich vs Berlin)
    - Discount: factor=0.95 (-5%)
    """
    # Explicit validation - Query(gt=, le=) may not be enforced in all FastAPI versions
    if factor <= 0 or factor > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Factor must be between 0 (exclusive) and 10 (inclusive), got {factor}",
        )

    from sqlalchemy import func, select

    from app.modules.catalog.models import CatalogResource

    # Build filter conditions using SQLAlchemy (DB-agnostic)
    conditions = [CatalogResource.is_active.is_(True)]
    if resource_type:
        conditions.append(CatalogResource.resource_type == resource_type)
    if category:
        conditions.append(CatalogResource.category == category)
    if region:
        conditions.append(CatalogResource.region == region)

    # Count matching rows first
    count_stmt = select(func.count()).select_from(CatalogResource).where(*conditions)
    count = (await session.execute(count_stmt)).scalar_one()

    if count > 0:
        # Fetch and update in batches via ORM to stay DB-agnostic
        stmt = select(CatalogResource).where(*conditions)
        result = await session.execute(stmt)
        resources = list(result.scalars().all())

        adjusted_ids: list[str] = []
        for res in resources:
            try:
                # CAT-003: keep full precision internally. Stored as
                # String(50); previously each write was truncated to 2dp
                # so repeated factor passes drifted (and factor→1/factor
                # never restored the original). ``_fmt_price`` trims only
                # trailing-zero noise, not significant digits.
                new_base = float(res.base_price) * factor
                new_lo = float(res.min_price) * factor
                new_hi = float(res.max_price) * factor
                # CAT-001: a uniform positive multiply preserves order,
                # so it cannot *create* an inversion - but a row that
                # was ALREADY inverted (e.g. from an old import that
                # predated the band validator) would survive every bulk
                # run untouched. Normalise here so the invariant is
                # restored on the next adjust-prices pass.
                new_base, new_lo, new_hi = _normalise_band(new_base, new_lo, new_hi)
                res.base_price = _fmt_price(new_base)
                res.min_price = _fmt_price(new_lo)
                res.max_price = _fmt_price(new_hi)
                adjusted_ids.append(str(res.id))
            except (ValueError, TypeError):
                pass

        await session.flush()

        # CAT-002: a bulk price change must notify subscribers so
        # assemblies / BOQ snapshots derived from these resources can
        # refresh - consistent with the costs.item.updated → assemblies
        # flow. Best-effort: never fail the request on a publish error.
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "catalog.resources.updated",
                {
                    "count": len(adjusted_ids),
                    "resource_ids": adjusted_ids,
                    "factor": factor,
                    "filters": {
                        "resource_type": resource_type,
                        "category": category,
                        "region": region,
                    },
                },
                source_module="oe_catalog",
            )
        except Exception:
            logger.debug("catalog.resources.updated publish skipped", exc_info=True)

    logger.info(
        "Adjusted %d resource prices by factor %.4f (type=%s, category=%s, region=%s)",
        count,
        factor,
        resource_type,
        category,
        region,
    )

    return {
        "adjusted": count,
        "factor": factor,
        "filters": {
            "resource_type": resource_type,
            "category": category,
            "region": region,
        },
    }


# ── Search / List ─────────────────────────────────────────────────────────


@router.get("/", response_model=CatalogSearchResponse)
async def search_catalog(
    # Public endpoint (mirrors the unauthenticated ``/regions/`` route and
    # the "(public, query params)" contract in this module's docstring).
    # Use OPTIONAL auth: ``CurrentUserId = None`` looks optional but is an
    # ``Annotated[..., Depends()]`` param - FastAPI ignores the ``= None``
    # default and ALWAYS resolves the dependency, so an anonymous /
    # expired-token request got a 401 here while ``/regions/`` returned
    # 200. The catalog page then rendered region tabs (with counts) but an
    # empty resource list. ``OptionalUserPayload`` returns ``None`` for an
    # anonymous request instead of raising, restoring the intended public
    # behaviour. ``_user`` is unused - kept only as a presence marker.
    _user: OptionalUserPayload = None,
    service: CatalogResourceService = Depends(_get_service),
    q: str | None = Query(default=None, description="Text search on code and name"),
    resource_type: str | None = Query(default=None, description="Filter: material, equipment, labor, operator"),
    category: str | None = Query(default=None, description="Filter by category"),
    region: str | None = Query(default=None, description="Filter by region"),
    unit: str | None = Query(default=None, description="Filter by unit"),
    min_price: float | None = Query(default=None, ge=0, description="Min base price"),
    max_price: float | None = Query(default=None, ge=0, description="Max base price"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> CatalogSearchResponse:
    """Search and list catalog resources with optional filters."""
    from app.modules.catalog.schemas import CatalogSearchQuery

    query = CatalogSearchQuery(
        q=q,
        resource_type=resource_type,
        category=category,
        region=region,
        unit=unit,
        min_price=min_price,
        max_price=max_price,
        limit=limit,
        offset=offset,
    )
    items, total = await service.search_resources(query)
    return CatalogSearchResponse(
        items=[CatalogResourceResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Stats ─────────────────────────────────────────────────────────────────


@router.get("/stats/", response_model=CatalogStatsResponse)
async def catalog_stats(
    region: str | None = Query(
        default=None,
        description="Scope counts to a single region so they match the region-filtered resource list",
    ),
    # Public endpoint - same optional-auth fix as ``search_catalog`` above
    # (a forced 401 here left the page's type/category badges empty).
    _user: OptionalUserPayload = None,
    service: CatalogResourceService = Depends(_get_service),
) -> CatalogStatsResponse:
    """Get aggregated counts by type and category (optionally per region)."""
    return await service.get_stats(region=region)


# ── Inverse lookup: positions that use a resource ─────────────────────────
# Declared BEFORE ``/{resource_id}`` so FastAPI's ordered path-matcher
# considers the longer pattern first - otherwise the bare resource-id
# route can shadow this one.


@router.get("/{resource_id}/used-by/")
async def list_cost_positions_using_resource(
    resource_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """List the cost positions that reference this resource.

    The catalog resource is the *leaf* (one material / labour rate /
    equipment item). Cost positions are the *compositions* - each one
    carries a ``components[]`` array naming the resources it consumes.
    This endpoint walks that link in the resource→positions direction:
    given a resource id, return every cost position whose
    ``components[].code`` matches the resource's ``resource_code``.

    Result shape:

    ::

        {
          "resource_code": "...",
          "items": [
            {"id": "...", "code": "...", "description": "...",
             "unit": "...", "rate": "...", "currency": "...",
             "region": "...",
             "component": {"quantity": 1.0, "unit_rate": ..., "cost": ..., "type": "material"}}
          ],
          "total": 106,
          "limit": 50,
          "offset": 0,
        }

    Implementation: SQLAlchemy + DB-side JSON ``LIKE`` filter on the
    serialised ``components`` column. We post-filter in Python to extract
    the matched ``component`` dict (the row may carry many components).
    For SQLite/Postgres parity we don't use JSON-path operators here -
    the LIKE on a small per-row payload is fast enough for catalog UI.
    """
    from sqlalchemy import func, or_, select

    from app.modules.catalog.models import CatalogResource
    from app.modules.costs.models import CostItem

    resource = (
        await session.execute(select(CatalogResource).where(CatalogResource.id == resource_id))
    ).scalar_one_or_none()
    if resource is None:
        raise HTTPException(
            status_code=404,
            detail=translate("errors.resource_not_found", locale=get_locale()),
        )

    code = resource.resource_code
    # JSON column stored as text - match the code as a quoted substring so
    # we don't false-positive on prefix collisions ("ME_X" matching "ME_XYZ").
    needle = f'"code": "{code}"'
    needle_alt = f'"code":"{code}"'  # compact JSON variant

    base_filter = or_(
        func.cast(CostItem.components, String).ilike(f"%{needle}%"),
        func.cast(CostItem.components, String).ilike(f"%{needle_alt}%"),
    )

    total = (await session.execute(select(func.count()).select_from(CostItem).where(base_filter))).scalar_one()

    rows = (
        (
            await session.execute(
                select(CostItem).where(base_filter).order_by(CostItem.code, CostItem.id).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )

    items: list[dict[str, Any]] = []
    for row in rows:
        matched_component: dict[str, Any] | None = None
        for c in row.components or []:
            if isinstance(c, dict) and c.get("code") == code:
                matched_component = c
                break
        items.append(
            {
                "id": str(row.id),
                "code": row.code,
                "description": row.description,
                "unit": row.unit,
                "rate": row.rate,
                "currency": row.currency,
                "region": row.region,
                "component": matched_component,
            }
        )

    return {
        "resource_code": code,
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ── Single resource ───────────────────────────────────────────────────────


@router.get("/{resource_id}", response_model=CatalogResourceResponse)
async def get_catalog_resource(
    resource_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: CatalogResourceService = Depends(_get_service),
) -> CatalogResourceResponse:
    """Get a single catalog resource by ID."""
    resource = await service.get_resource(resource_id)
    return CatalogResourceResponse.model_validate(resource)


# ── Create ────────────────────────────────────────────────────────────────


@router.post("/", response_model=CatalogResourceResponse, status_code=201)
async def create_catalog_resource(
    data: CatalogResourceCreate,
    service: CatalogResourceService = Depends(_get_service),
    _user: str = Depends(RequirePermission("catalog.create")),
) -> CatalogResourceResponse:
    """Create a new custom catalog resource."""
    resource = await service.create_resource(data)
    return CatalogResourceResponse.model_validate(resource)


# ── Extract from cost items ──────────────────────────────────────────────


@router.post("/extract/")
async def extract_resources(
    service: CatalogResourceService = Depends(_get_service),
    _user: str = Depends(RequirePermission("catalog.extract")),
) -> dict[str, Any]:
    """Extract top 100 resources from existing cost item components.

    This is an admin-level operation that:
    1. Scans all cost items for components
    2. Aggregates by component code and type
    3. Computes avg/min/max rates
    4. Categorizes resources
    5. Inserts top 100 (50 materials, 30 equipment, 10 labor, 10 operators)
    """
    counts = await service.extract_from_cost_items()
    total = sum(counts.values())
    return {
        "status": "success",
        "total_extracted": total,
        "by_type": counts,
    }
