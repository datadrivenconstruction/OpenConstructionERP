# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Index an imported cost catalogue for CAD-BIM Match.

Match ranks against vector collections embedded with BGE-M3, and until now
only the published ``cwicr_<lang>`` collections existed. An imported price
list (an Italian regional prezzario, say) lives in ``oe_costs_item`` under its
own ``region`` and was invisible to Match: the ``/vector/index/`` action writes
a different store with a different model that the ranker never reads.

This module embeds the active rows of one imported catalogue with the Match
encoder into a collection of its own, ``oecat_<hash>``. The name is derived
from the region string, so no table is needed to find it, and it deliberately
does not start with ``cwicr_``: the language-fallback logic in
:mod:`app.modules.costs.qdrant_adapter` picks from ``cwicr_*`` collections and
must never serve someone's price list to an unrelated project.

Each point's id is the ``CostItem.id`` and its payload carries
``cost_item_id``, so a confirmed candidate resolves to the real cost item and
its real rate. Re-running is idempotent: a row whose text is unchanged is not
embedded again, a row whose price changed only has its payload rewritten, and
points of rows that are gone are deleted. An interrupted run is resumed by
running it again.

The work runs inside the ``match_catalogue_indexer`` registry process (see
:mod:`app.core.processes.matching`), which is off by default like the matching
models it depends on. Job state is kept in memory: what is already indexed is
read back from the store, so a restart loses only the progress bar.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PROCESS_ID = "match_catalogue_indexer"
COLLECTION_PREFIX = "oecat_"

#: Rows read from the database per page.
PAGE_SIZE = 256
#: Texts per encoder forward pass. Small enough to keep the peak memory of
#: BGE-M3 modest on a 3 GB server.
ENCODE_BATCH = 32
#: ``cost_database_id`` on the project's match settings is String(32), so a
#: longer region can be picked for a run but not bound to a project.
MAX_BINDABLE_REGION = 32

_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

# Error codes the frontend translates (``costs.match_index.error_<code>``).
ERR_EMBEDDER = "embedder_unavailable"
ERR_DISABLED = "indexer_disabled"
ERR_NOT_FOUND = "catalogue_not_found"
ERR_PUBLISHED = "catalogue_is_published"
ERR_EMPTY = "catalogue_empty"
ERR_STORE = "store_unavailable"
ERR_FAILED = "index_failed"


class MatchIndexError(Exception):
    """A refusal the route turns into a translated error.

    Attributes:
        code: Stable error code, also the frontend's i18n key suffix.
        status_code: HTTP status for the route.
    """

    def __init__(self, code: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class IndexJob:
    """Progress of one catalogue's indexing run in this process."""

    region: str
    language: str
    country: str = ""
    status: str = "queued"  # queued | running | done | failed | interrupted
    total: int = 0
    processed: int = 0
    embedded: int = 0
    removed: int = 0
    error_code: str | None = None
    error: str | None = None
    queued_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialisable view for the status route."""
        return asdict(self)


_jobs: dict[str, IndexJob] = {}
_language_cache: dict[str, str] = {}
_queue: list[str] = []
_start_tasks: set[asyncio.Task[None]] = set()


def collection_for_region(region: str) -> str:
    """The collection an imported catalogue is indexed into.

    Hex only after the prefix, so the ``rsplit("_v", 1)`` retries the adapter
    uses for versioned CWICR names can never cut it.
    """
    digest = hashlib.sha1(region.strip().encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{COLLECTION_PREFIX}{digest[:20]}"


def is_published_region(region: str) -> bool:
    """True for a region id of a published CWICR catalogue."""
    from app.modules.costs.cwicr_v3_catalogue import CWICR_V3_CATALOGUES  # noqa: PLC0415

    wanted = region.strip().upper()
    return any(cat.region.upper() == wanted for cat in CWICR_V3_CATALOGUES)


def embedder_installed() -> bool:
    """Whether the Match encoder's library and the store client are installed.

    ``find_spec`` instead of an import: FlagEmbedding pulls in torch.
    """
    for name in ("FlagEmbedding", "qdrant_client"):
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def indexer_enabled() -> bool:
    """Whether the indexer process and the encoder it needs may run."""
    from app.core.processes.matching import matching_model_allowed  # noqa: PLC0415

    return matching_model_allowed(PROCESS_ID) and matching_model_allowed("cwicr_ranker")


def validate_request(language: str, country: str | None) -> tuple[str, str]:
    """Normalise the language and optional country of an index request.

    Raises:
        ValueError: The language or country is not a plain ISO code.
    """
    lang = (language or "").strip().lower().split("-")[0]
    if not _LANGUAGE_RE.match(lang):
        raise ValueError("language must be an ISO 639-1 code such as 'it'")
    ctry = (country or "").strip().upper()
    if ctry and not _COUNTRY_RE.match(ctry):
        raise ValueError("country must be an ISO 3166 alpha-2 code such as 'IT'")
    return lang, ctry


# ── Reading what is indexed ────────────────────────────────────────────────


def _collection_meta(client: Any, name: str) -> dict[str, Any] | None:
    """Point count plus language, country and region of one collection."""
    try:
        info = client.get_collection(name)
    except Exception:  # noqa: BLE001 - a missing collection is simply not indexed
        return None
    count = int(getattr(info, "points_count", None) or 0)
    meta: dict[str, Any] = {"collection": name, "points": count, "language": "", "country": "", "region": ""}
    if count:
        try:
            points, _ = client.scroll(collection_name=name, limit=1, with_payload=True, with_vectors=False)
            payload = (points[0].payload or {}) if points else {}
            meta["language"] = str(payload.get("language") or "")
            meta["country"] = str(payload.get("country") or "")
            meta["region"] = str(payload.get("catalogue_region") or "")
        except Exception:  # noqa: BLE001 - the count is still worth reporting
            logger.debug("match_index: payload probe of %s failed", name, exc_info=True)
    return meta


def describe_collections(names: list[str], client: Any = None) -> list[dict[str, Any]]:
    """Describe the given ``oecat_*`` collections. Synchronous, never raises.

    Args:
        names: Collection names.
        client: Store client to ask; the adapter's by default. The readiness
            probe passes its short-timeout client so a slow store cannot hold
            the card past its budget.
    """
    if client is None:
        try:
            from app.modules.costs.qdrant_adapter import _get_client  # noqa: PLC0415

            client = _get_client()
        except Exception:  # noqa: BLE001 - no store, nothing indexed
            return []
    out = []
    for name in names:
        meta = _collection_meta(client, name)
        if meta is not None and meta["points"] > 0 and meta["region"]:
            out.append(meta)
    return out


def list_custom_collections() -> list[str]:
    """Names of the ``oecat_*`` collections in the Match store. Never raises."""
    try:
        from app.modules.costs.qdrant_adapter import _get_client  # noqa: PLC0415

        listed = _get_client().get_collections()
    except Exception:  # noqa: BLE001 - no store, nothing indexed
        return []
    return sorted(
        str(getattr(c, "name", "") or "")
        for c in (getattr(listed, "collections", None) or [])
        if str(getattr(c, "name", "") or "").startswith(COLLECTION_PREFIX)
    )


def indexed_catalogues() -> list[dict[str, Any]]:
    """Every imported catalogue with points in the Match store."""
    return describe_collections(list_custom_collections())


async def visible_regions(
    db: Any,
    *,
    owner_id: uuid.UUID | None,
    is_admin: bool,
    region: str | None = None,
) -> dict[str, int]:
    """Imported catalogues the caller may see, with their active row counts.

    An imported price list is a user-owned :class:`CostCatalog`; its rows carry
    the catalogue id. The same ownership rule as ``/catalogs/`` applies: a
    region is visible when every active row in it is either shared
    (``catalog_id IS NULL``) or in a catalogue the caller created. One row the
    caller may not see hides the whole region, so neither its name nor its
    size leaks, and nobody can index rows they could not read. Admins see all.
    Published CWICR regions are left out.
    """
    from sqlalchemy import case, func, literal, or_, select  # noqa: PLC0415

    from app.modules.costs.models import CostCatalog, CostItem  # noqa: PLC0415

    hidden: Any
    if is_admin:
        hidden = literal(0)
    elif owner_id is None:
        hidden = case((CostItem.catalog_id.isnot(None), 1), else_=0)
    else:
        # A dangling catalogue id joins to NULL and counts as hidden.
        hidden = case(
            (
                CostItem.catalog_id.isnot(None)
                & or_(CostCatalog.created_by.is_(None), CostCatalog.created_by != owner_id),
                1,
            ),
            else_=0,
        )
    stmt = (
        select(CostItem.region, func.count(CostItem.id), func.sum(hidden))
        .outerjoin(CostCatalog, CostItem.catalog_id == CostCatalog.id)
        .where(CostItem.is_active.is_(True))
        .where(CostItem.region.isnot(None))
        .where(CostItem.region != "")
    )
    if region is not None:
        stmt = stmt.where(CostItem.region == region)
    from app.core import cost_scope  # noqa: PLC0415

    # This query does the ownership arithmetic itself and needs the rows the
    # caller may NOT read in order to hide the region they sit in.
    with cost_scope.system_scope():
        rows = (await db.execute(stmt.group_by(CostItem.region))).all()
    return {
        str(r): int(n)
        for r, n, h in rows
        if r and int(n or 0) > 0 and not int(h or 0) and not is_published_region(str(r))
    }


async def catalogue_overview(
    db: Any,
    *,
    owner_id: uuid.UUID | None = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    """One entry per imported catalogue the caller may see, for the costs page.

    Combines the SQL row count, the indexed point count and this process's job
    state, so the page can say "not indexed", "indexing 40 %", "indexed" or
    "failed" without a second request. Scoped by :func:`visible_regions`.
    """
    regions = await visible_regions(db, owner_id=owner_id, is_admin=is_admin)
    if not regions:
        return []
    names = {collection_for_region(r): r for r in regions}
    try:
        metas = await asyncio.wait_for(asyncio.to_thread(describe_collections, list(names)), timeout=10)
    except TimeoutError:
        metas = []
    by_region = {names[m["collection"]]: m for m in metas if m["collection"] in names}
    out: list[dict[str, Any]] = []
    for region, count in sorted(regions.items()):
        meta = by_region.get(region) or {}
        job = _jobs.get(region)
        out.append(
            {
                "region": region,
                "count": count,
                "indexed": int(meta.get("points") or 0),
                "language": str(meta.get("language") or (job.language if job else "")),
                "country": str(meta.get("country") or (job.country if job else "")),
                "bindable": len(region) <= MAX_BINDABLE_REGION,
                "job": job.as_dict() if job else None,
            }
        )
    return out


def catalogue_language(region: str | None) -> str:
    """The language an indexed catalogue was indexed with, ``""`` if unknown."""
    if not region:
        return ""
    cached = _language_cache.get(region)
    if cached is not None:
        return cached
    try:
        from app.modules.costs.qdrant_adapter import _get_client  # noqa: PLC0415

        meta = _collection_meta(_get_client(), collection_for_region(region))
    except Exception:  # noqa: BLE001 - unknown language, the caller falls back
        meta = None
    language = str((meta or {}).get("language") or "")
    _language_cache[region] = language
    return language


# ── Requesting a run ───────────────────────────────────────────────────────


async def request_index(
    db: Any,
    region: str,
    language: str,
    country: str | None,
    *,
    owner_id: uuid.UUID | None = None,
    is_admin: bool = False,
) -> IndexJob:
    """Queue ``region`` for indexing and make sure the indexer runs.

    Idempotent: a catalogue already queued or running keeps its job. A
    catalogue the caller may not see (:func:`visible_regions`) is refused
    exactly like one that does not exist.

    Raises:
        MatchIndexError: The catalogue cannot be indexed now; ``code`` says why.
        ValueError: The language or country is malformed.
    """
    region = (region or "").strip()
    lang, ctry = validate_request(language, country)
    if not region:
        raise MatchIndexError(ERR_NOT_FOUND, 404, "Catalogue not found")
    if is_published_region(region):
        raise MatchIndexError(
            ERR_PUBLISHED, 409, "Published catalogues are installed with their own vector index already"
        )
    count = (await visible_regions(db, owner_id=owner_id, is_admin=is_admin, region=region)).get(region, 0)
    if not count:
        raise MatchIndexError(ERR_NOT_FOUND, 404, "Catalogue not found or has no active items")
    if not embedder_installed():
        raise MatchIndexError(ERR_EMBEDDER, 503, "The matching model is not installed on this server")
    if not indexer_enabled():
        raise MatchIndexError(ERR_DISABLED, 409, "The matching model is switched off")

    job = _jobs.get(region)
    if job is not None and job.status in ("queued", "running"):
        # Asking again also re-kicks a queue whose start went wrong.
        _ensure_running()
        return job
    job = IndexJob(region=region, language=lang, country=ctry, total=int(count))
    _jobs[region] = job
    _queue.append(region)
    _ensure_running()
    return job


def _ensure_running() -> None:
    """Start the indexer process unless it is already draining the queue.

    No await between the queue append in :func:`request_index` and the status
    read here, and none between the drain loop's last empty check and its
    return, so a request can never fall between a finishing run and the next.
    """
    from app.core.processes import process_registry  # noqa: PLC0415
    from app.core.processes.registry import ProcessStatus  # noqa: PLC0415

    if PROCESS_ID not in process_registry.ids():
        # A bare app without the registry (some tests): run in place.
        task = asyncio.get_running_loop().create_task(run_queue(), name="match-index-inline")
    else:
        # A finished start task leaves the set only on its done callback, a
        # loop turn later; counting it would skip the start a retry needs.
        if any(not t.done() for t in _start_tasks) or process_registry.status(PROCESS_ID) in {
            ProcessStatus.STARTING,
            ProcessStatus.RUNNING,
            ProcessStatus.DEGRADED,
        }:
            return
        task = asyncio.get_running_loop().create_task(_start_process(), name="match-index-start")
    _start_tasks.add(task)
    task.add_done_callback(_start_tasks.discard)


async def _start_process() -> None:
    """Start the indexer; if it did not come up, fail what it would have run.

    The process depends on the ranker's encoder. When that cannot load (not
    downloaded yet, out of memory) or the process was switched off in the
    meantime, the registry records the failure and ``run_queue`` never runs,
    so without this the jobs would read "waiting to start" until a restart.
    """
    from app.core.processes import process_registry  # noqa: PLC0415
    from app.core.processes.registry import ProcessStatus  # noqa: PLC0415

    try:
        await process_registry.restart(PROCESS_ID)
    except Exception:  # noqa: BLE001 - reported on the jobs below
        logger.warning("match_index: the indexer did not start", exc_info=True)
    if not _queue or process_registry.status(PROCESS_ID) in {
        ProcessStatus.STARTING,
        ProcessStatus.RUNNING,
        ProcessStatus.DEGRADED,
    }:
        return
    if not indexer_enabled():
        code = ERR_DISABLED
    elif process_registry.status("cwicr_ranker") is ProcessStatus.ERROR:
        code = ERR_EMBEDDER
    else:
        code = ERR_FAILED
    logger.warning("match_index: %d queued catalogue(s) not indexed (%s)", len(_queue), code)
    for region in _queue:
        job = _jobs.get(region)
        if job is not None and job.status == "queued":
            job.status, job.error_code, job.finished_at = "failed", code, time.time()
    _queue.clear()


# ── The run ────────────────────────────────────────────────────────────────


async def run_queue() -> None:
    """Index every queued catalogue, one after another. The process body."""
    from app.core import cost_scope  # noqa: PLC0415

    while _queue:
        region = _queue.pop(0)
        job = _jobs.get(region)
        if job is None or job.status != "queued":
            continue
        job.status = "running"
        try:
            # The request was checked against the catalogue's owner before it
            # was queued. The indexer then reads the whole region: read as the
            # user whose request woke it, it would see a part of a catalogue
            # and drop the rest from the index as stale.
            with cost_scope.system_scope():
                await index_catalogue(job)
        except asyncio.CancelledError:
            job.status = "interrupted"
            job.finished_at = time.time()
            # Whatever was still waiting runs on the next request.
            for pending in _queue:
                if pending in _jobs and _jobs[pending].status == "queued":
                    _jobs[pending].status = "interrupted"
            _queue.clear()
            raise
        except MatchIndexError as exc:
            job.status, job.error_code, job.error = "failed", exc.code, str(exc)
        except Exception as exc:  # noqa: BLE001 - one bad catalogue must not stop the queue
            logger.exception("match_index: indexing %r failed", region)
            job.status, job.error_code, job.error = "failed", ERR_FAILED, str(exc)[:300]
        else:
            job.status = "done"
        job.finished_at = time.time()


def _embed_text(description: str, unit: str, classification: dict[str, Any] | None) -> str:
    """The text a row is embedded with: its description, unit and section."""
    parts = [description.strip()]
    for key in ("collection", "department", "section", "category"):
        value = (classification or {}).get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    if unit.strip():
        parts.append(unit.strip())
    return " | ".join(p for p in parts if p)[:2000]


def _float_rate(rate: Any) -> float:
    try:
        return float(str(rate).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _digest(*parts: Any) -> str:
    joined = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()


def _payload(row: Any, job: IndexJob, text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rate_code": str(row.code),
        "cost_item_id": str(row.id),
        "description": str(row.description or ""),
        "rate_unit": str(row.unit or ""),
        "unit_cost": _float_rate(row.rate),
        "currency": str(row.currency or ""),
        "country": job.country,
        "language": job.language,
        "source": "catalogue",
        "catalogue_region": job.region,
        "is_abstract": False,
        "text_hash": _digest(text),
    }
    payload["payload_hash"] = _digest(*(payload[k] for k in sorted(payload)))
    return payload


def _encode_or_raise(texts: list[str]) -> dict[str, Any]:
    from app.modules.costs.qdrant_adapter import _encode  # noqa: PLC0415

    try:
        return _encode(texts)
    except RuntimeError as exc:
        # The adapter raises English sentences for a missing or switched-off
        # encoder; the page shows a translated message by code instead.
        raise MatchIndexError(ERR_EMBEDDER, 503, str(exc)) from exc


def _models() -> Any:
    """``qdrant_client.http.models``, imported on use (an optional extra)."""
    from qdrant_client.http import models  # noqa: PLC0415

    return models


def _ensure_collection(client: Any, name: str, dim: int) -> None:
    m = _models()
    try:
        client.get_collection(name)
        return
    except Exception:  # noqa: BLE001 - absent, create it below
        pass
    client.create_collection(
        collection_name=name,
        vectors_config={"dense": m.VectorParams(size=dim, distance=m.Distance.COSINE)},
        sparse_vectors_config={"sparse": m.SparseVectorParams()},
    )


async def _fetch_page(session_factory: Any, region: str, last_id: Any) -> list[Any]:
    """One page of the catalogue's active rows after ``last_id``, by id.

    Keyset paging on the primary key, a fresh session per page: a long run
    holds no transaction open and sees rows added while it works.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.costs.models import CostItem  # noqa: PLC0415

    async with session_factory() as session:
        stmt = (
            select(
                CostItem.id,
                CostItem.code,
                CostItem.description,
                CostItem.unit,
                CostItem.rate,
                CostItem.currency,
                CostItem.classification,
            )
            .where(CostItem.is_active.is_(True))
            .where(CostItem.region == region)
            .order_by(CostItem.id)
            .limit(PAGE_SIZE)
        )
        if last_id is not None:
            stmt = stmt.where(CostItem.id > last_id)
        return list((await session.execute(stmt)).all())


async def index_catalogue(job: IndexJob, *, session_factory: Any = None) -> None:
    """Bring the collection of ``job.region`` in line with its active rows.

    Args:
        job: The catalogue and the language and country to stamp on it.
        session_factory: Opens a database session; the app's by default.
    """
    from app.modules.costs.qdrant_adapter import _get_client, forget_collection  # noqa: PLC0415

    if session_factory is None:
        from app.database import async_session_factory as session_factory  # noqa: PLC0415

    name = collection_for_region(job.region)
    try:
        client = await asyncio.to_thread(_get_client)
        m = _models()
    except Exception as exc:
        raise MatchIndexError(ERR_STORE, 503, str(exc)) from exc
    exists = await asyncio.to_thread(_collection_meta, client, name) is not None

    seen: set[str] = set()
    last_id: Any = None
    started = time.perf_counter()
    while True:
        rows = await _fetch_page(session_factory, job.region, last_id)
        if not rows:
            break
        last_id = rows[-1].id

        texts = {str(r.id): _embed_text(str(r.description or ""), str(r.unit or ""), r.classification) for r in rows}
        payloads = {str(r.id): _payload(r, job, texts[str(r.id)]) for r in rows}
        seen.update(payloads)

        existing: dict[str, dict[str, Any]] = {}
        if exists:
            found = await asyncio.to_thread(
                client.retrieve,
                collection_name=name,
                ids=list(payloads),
                with_payload=["text_hash", "payload_hash"],
                with_vectors=False,
            )
            existing = {str(p.id): (p.payload or {}) for p in found}

        to_embed: list[str] = []
        for pid, payload in payloads.items():
            old = existing.get(pid)
            if old is None or old.get("text_hash") != payload["text_hash"]:
                to_embed.append(pid)
            elif old.get("payload_hash") != payload["payload_hash"]:
                # Same text, new price or unit: no need to run the encoder.
                await asyncio.to_thread(client.overwrite_payload, collection_name=name, payload=payload, points=[pid])

        for i in range(0, len(to_embed), ENCODE_BATCH):
            batch = to_embed[i : i + ENCODE_BATCH]
            encoded = await asyncio.to_thread(_encode_or_raise, [texts[pid] for pid in batch])
            if not exists:
                await asyncio.to_thread(_ensure_collection, client, name, len(encoded["dense"][0]))
                exists = True
            points = [
                m.PointStruct(
                    id=pid,
                    vector={"dense": encoded["dense"][j], "sparse": encoded["sparse"][j]},
                    payload=payloads[pid],
                )
                for j, pid in enumerate(batch)
            ]
            await asyncio.to_thread(client.upsert, collection_name=name, points=points)
            job.embedded += len(batch)
        job.processed += len(rows)
        job.total = max(job.total, job.processed)

    if not seen:
        raise MatchIndexError(ERR_EMPTY, 409, "The catalogue has no active items")

    # Points of rows that were deleted or deactivated since the last run.
    if exists:
        stale: list[str] = []
        offset: Any = None
        while True:
            points, offset = await asyncio.to_thread(
                client.scroll,
                collection_name=name,
                limit=1024,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            stale.extend(str(p.id) for p in points if str(p.id) not in seen)
            if offset is None:
                break
        for i in range(0, len(stale), 1024):
            await asyncio.to_thread(
                client.delete, collection_name=name, points_selector=m.PointIdsList(points=stale[i : i + 1024])
            )
        job.removed = len(stale)

    forget_collection(name)
    _language_cache.pop(job.region, None)
    with contextlib.suppress(Exception):
        from app.core.match_service import ranker_qdrant  # noqa: PLC0415

        for custom in (False, True):
            ranker_qdrant._catalog_status_cache.pop(
                ranker_qdrant.catalog_status_cache_key(job.region, custom=custom), None
            )
    logger.info(
        "match_index: %r indexed into %s (%d rows, %d embedded, %d removed) in %.1fs",
        job.region,
        name,
        job.processed,
        job.embedded,
        job.removed,
        time.perf_counter() - started,
    )


def job_for(region: str) -> IndexJob | None:
    """This process's job for ``region``, if one ran or is waiting."""
    return _jobs.get(region)


def reset_state() -> None:
    """Forget every job (tests)."""
    _jobs.clear()
    _queue.clear()
    _language_cache.clear()


__all__ = [
    "visible_regions",
    "COLLECTION_PREFIX",
    "ERR_DISABLED",
    "ERR_EMBEDDER",
    "MAX_BINDABLE_REGION",
    "PROCESS_ID",
    "IndexJob",
    "MatchIndexError",
    "catalogue_language",
    "catalogue_overview",
    "collection_for_region",
    "describe_collections",
    "embedder_installed",
    "index_catalogue",
    "indexed_catalogues",
    "indexer_enabled",
    "is_published_region",
    "request_index",
    "run_queue",
]
