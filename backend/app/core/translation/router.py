"""Translation API — test harness + dictionary download/status.

Mounted at ``/api/v1/translation``. Three endpoints:

* ``POST /translate``                        — translate one term (test harness)
* ``POST /lookup-tables/download``           — kick off a MUSE / IATE download
                                               in the background, return a task id
* ``GET  /lookup-tables/status``             — what's downloaded, sizes, age,
                                               in-flight download tasks

Auth: requires a logged-in user (the LLM tier needs the user's AISettings;
the download endpoints touch the user's ``~/.openestimate`` directory).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field

from app.core.translation import TierUsed, TranslationResult, translate
from app.core.translation.cache import TranslationCache
from app.core.translation.downloader import (
    download_iate_dump,
    download_muse_pair,
    list_downloaded,
    process_iate_tbx,
)
from app.dependencies import CurrentUserId, SessionDep
from app.modules.ai.repository import AISettingsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/translation", tags=["Translation"])


# ── Schemas ─────────────────────────────────────────────────────────────


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    # ISO-639-1 (2-letter) preferred; ISO-639-3 (3-letter) and BCP-47 short
    # subtags (e.g. ``zh-cn``) accepted. Restricted to alphabetic + a single
    # optional hyphen so callers can't smuggle paths or URL fragments.
    source_lang: str = Field(
        ..., min_length=2, max_length=8, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z]{2,4})?$",
    )
    target_lang: str = Field(
        ..., min_length=2, max_length=8, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z]{2,4})?$",
    )
    domain: str = Field(default="construction", max_length=64)


class TranslateResponse(BaseModel):
    translated: str
    source_lang: str
    target_lang: str
    tier_used: TierUsed
    confidence: float
    cost_usd: float | None = None


class DownloadRequest(BaseModel):
    """Body for ``POST /lookup-tables/download``.

    * ``kind="muse"`` requires ``source_lang`` and ``target_lang``.
    * ``kind="iate"`` requires either ``url`` (mirror download) or
      ``local_tbx_path`` (already downloaded by the user).
    """

    kind: str = Field(..., pattern="^(muse|iate)$")
    source_lang: str | None = None
    target_lang: str | None = None
    url: str | None = None
    local_tbx_path: str | None = None


class DownloadResponse(BaseModel):
    task_id: str
    kind: str
    status: str  # "queued"


class StatusResponse(BaseModel):
    dictionaries: dict[str, list[dict[str, Any]]]
    cache: dict[str, Any]
    in_flight: list[dict[str, Any]]


# ── In-process task tracker ─────────────────────────────────────────────
# A real deployment will route long downloads through Celery, but for the
# initial MVP we track tasks in a process-local dict so the status endpoint
# can show progress without bringing in a broker dependency.

_TASKS: dict[str, dict[str, Any]] = {}


def _record_task(task_id: str, **fields: Any) -> None:
    entry = _TASKS.setdefault(task_id, {})
    entry.update(fields)


async def _run_muse(task_id: str, src: str, tgt: str) -> None:
    _record_task(task_id, status="running", progress=0.0)
    try:
        path = await download_muse_pair(
            src,
            tgt,
            on_progress=lambda v: _record_task(task_id, progress=float(v)),
        )
        _record_task(task_id, status="done", progress=1.0, path=str(path))
    except Exception as exc:  # noqa: BLE001 — surface message to status
        logger.warning("MUSE download %s-%s failed: %s", src, tgt, exc)
        _record_task(task_id, status="failed", error=str(exc))


async def _run_iate(
    task_id: str, url: str | None, local_path: str | None
) -> None:
    _record_task(task_id, status="running", progress=0.0)
    try:
        if local_path:
            paths = await process_iate_tbx(
                local_path,
                on_progress=lambda v: _record_task(task_id, progress=float(v)),
            )
        elif url:
            tbx_path = await download_iate_dump(
                url=url,
                on_progress=lambda v: _record_task(task_id, progress=float(v) * 0.7),
            )
            paths = await process_iate_tbx(
                tbx_path,
                on_progress=lambda v: _record_task(
                    task_id, progress=0.7 + 0.3 * float(v)
                ),
            )
        else:
            raise ValueError("either url or local_tbx_path is required for IATE")
        _record_task(
            task_id,
            status="done",
            progress=1.0,
            pairs={k: str(v) for k, v in paths.items()},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("IATE processing failed: %s", exc)
        _record_task(task_id, status="failed", error=str(exc))


# ── Endpoints ───────────────────────────────────────────────────────────


@router.post("/translate", response_model=TranslateResponse)
async def translate_one(
    body: TranslateRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> TranslateResponse:
    """Translate a single term — test harness for the cascade.

    Looks up the caller's AISettings so the LLM tier has a key to use;
    if no settings row exists the LLM tier just degrades to a miss.
    """
    repo = AISettingsRepository(session)
    user_settings = None
    try:
        user_uuid = uuid.UUID(user_id)
        user_settings = await repo.get_by_user_id(user_uuid)
    except (ValueError, TypeError):
        # Malformed user id — translate without LLM tier.
        user_settings = None

    result: TranslationResult = await translate(
        body.text,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        domain=body.domain,
        user_settings=user_settings,
    )
    return TranslateResponse(
        translated=result.translated,
        source_lang=result.source_lang,
        target_lang=result.target_lang,
        tier_used=result.tier_used,
        confidence=result.confidence,
        cost_usd=result.cost_usd,
    )


@router.post(
    "/lookup-tables/download",
    response_model=DownloadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_download(
    body: DownloadRequest,
    background: BackgroundTasks,
    user_id: CurrentUserId,
) -> DownloadResponse:
    """Kick off a MUSE / IATE download in the background."""
    task_id = uuid.uuid4().hex
    _record_task(
        task_id,
        kind=body.kind,
        status="queued",
        progress=0.0,
        owner=user_id,
    )

    if body.kind == "muse":
        if not body.source_lang or not body.target_lang:
            raise HTTPException(
                status_code=400,
                detail="source_lang and target_lang are required for MUSE",
            )
        background.add_task(
            _run_muse,
            task_id,
            body.source_lang.lower(),
            body.target_lang.lower(),
        )
    else:  # iate
        if not body.url and not body.local_tbx_path:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Either url or local_tbx_path is required for IATE. "
                    "Download the dump from https://iate.europa.eu/download-iate "
                    "and pass the local path."
                ),
            )
        background.add_task(
            _run_iate, task_id, body.url, body.local_tbx_path
        )

    return DownloadResponse(task_id=task_id, kind=body.kind, status="queued")


@router.get("/lookup-tables/status", response_model=StatusResponse)
async def lookup_status(
    user_id: CurrentUserId,
) -> StatusResponse:
    """Report which dictionaries are present, cache stats, and in-flight tasks."""
    cache = TranslationCache()
    try:
        cache_stats = await cache.stats()
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("cache stats failed: %s", exc)
        cache_stats = {"rows": 0, "hits": 0}

    # Filter in-flight tasks by owner so user A can't see user B's
    # task IDs, error strings (which can leak filesystem paths from
    # ``process_iate_tbx``), or download progress.  Admins still see
    # only their own tasks here — there's a separate audit view for
    # cross-tenant inspection if needed.
    return StatusResponse(
        dictionaries=list_downloaded(),
        cache=cache_stats,
        in_flight=[
            {"task_id": tid, **{k: v for k, v in t.items() if k != "owner"}}
            for tid, t in _TASKS.items()
            if t.get("status") in ("queued", "running")
            and t.get("owner") == user_id
        ],
    )
