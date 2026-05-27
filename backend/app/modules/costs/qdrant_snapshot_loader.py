# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Load DDC-published CWICR snapshots into a server-mode Qdrant.

Companion to :mod:`app.modules.costs.qdrant_adapter`. The adapter handles
*search*; this module handles *populate-from-DDC* — i.e. taking the
``*_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot``
files DDC publishes and restoring them into the language-keyed Qdrant
collections (``cwicr_de_v3``, ``cwicr_ru_v3``, …) the search path
expects.

Why a dedicated module?
-----------------------

The adapter docstring documents the constraint we hit on 2026-05-09:
embedded ``QdrantClient(path=...)`` cannot ``recover_snapshot`` —
``NotImplementedError: Snapshots are not supported in the local
Qdrant``. So the snapshot ingest path is *server-mode only*. Splitting
it out keeps the runtime ``search()`` import graph from pulling httpx
on every cold start, and lets the CLI tool (``scripts/v3_snapshot_load.py``)
import this without dragging in the BGE-M3 encoder.

DDC snapshot filename convention
--------------------------------

::

    {REGION}_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot

* ``{REGION}`` — the canonical CWICR region id (``RU_STPETERSBURG``,
  ``USA_USD``, ``ENG_TORONTO``, …). Resolved to a language collection
  via :func:`region_language.language_for`.
* ``BGEM3_V3`` — encoder + schema marker. We deliberately filter on
  this so legacy ``*_EMBEDDINGS_3072_DDC_CWICR.snapshot`` files (the
  text-embedding-3-large run that predates the bge-m3 cutover) are
  skipped — restoring one would corrupt the v3 collection vector
  schema.

Multiple regions sharing a language (``USA_USD`` and ``GB_LONDON`` →
``cwicr_en_v3``) collide on restore. The current implementation logs a
WARNING and proceeds — last-write-wins. Operator workflow: restore the
canonical English variant (typically USA_USD) **last** so its rates
end up in the live collection. A per-region collection layout is
tracked as a v4 candidate; do not change it here without updating
:func:`country_to_collection` in lockstep.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.modules.costs.qdrant_adapter import country_to_collection

logger = logging.getLogger(__name__)


# ── Filename -> collection name ──────────────────────────────────────────


# Match ``REGION_workitems_…BGEM3_V3…`` where REGION is the leading
# uppercase token cluster. The ``_workitems_`` tail anchor is what every
# DDC v3 export name carries; the BGEM3_V3 token is checked separately
# (case-insensitively) to also accept ``bgem3_v3`` or future spelling
# tweaks DDC may publish.
_REGION_RE = re.compile(r"^(?P<region>[A-Z][A-Z0-9_]*?)_workitems_")
_V3_MARKER_RE = re.compile(r"BGEM3_V3", re.IGNORECASE)


def cwicr_snapshot_target_for(snapshot_filename: str | Path) -> str | None:
    """‌⁠‍Return the target collection name for a DDC v3 snapshot, or ``None``.

    ``None`` means "skip this file" — either it isn't a BGE-M3 v3
    snapshot, or its filename doesn't follow the DDC convention. The
    caller logs a structured skip reason and moves on.

    Examples (assuming the v3 default suffix ``_v3``)::

        >>> cwicr_snapshot_target_for(
        ...     "RU_STPETERSBURG_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot"
        ... )
        'cwicr_ru_v3'

        >>> cwicr_snapshot_target_for(
        ...     "USA_USD_workitems_costs_resources_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot"
        ... )
        'cwicr_en_v3'

        >>> cwicr_snapshot_target_for(
        ...     "DE_BERLIN_workitems_costs_resources_EMBEDDINGS_3072_DDC_CWICR.snapshot"
        ... ) is None
        True
    """

    name = Path(str(snapshot_filename)).name
    if not _V3_MARKER_RE.search(name):
        return None
    match = _REGION_RE.match(name)
    if not match:
        return None
    return country_to_collection(match.group("region"))


# ── REST snapshot upload ─────────────────────────────────────────────────


@dataclass
class SnapshotLoadSummary:
    """‌⁠‍Aggregate result of :func:`load_ddc_snapshot_dir`.

    Three buckets:

    * ``loaded`` — snapshots successfully restored (or, in dry-run mode,
      that would have been restored).
    * ``skipped`` — snapshots ignored because they aren't BGE-M3 v3 or
      their filename didn't parse. The string carries the reason for
      operator triage.
    * ``errors`` — snapshots that matched the v3 pattern but failed to
      upload. Includes the exception class + first 200 chars of message
      so a single corrupted file doesn't tank the whole run.

    Each entry is a flat ``str`` so the CLI can dump them line-by-line
    without further formatting; structured callers can reparse.
    """

    loaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True iff at least one snapshot loaded and no errors fired."""
        return bool(self.loaded) and not self.errors


class SnapshotRestoreError(RuntimeError):
    """Snapshot recover-from-URL failed. ``args[0]`` is the verbatim Qdrant message."""


def restore_snapshot_from_url(
    *,
    qdrant_url: str,
    collection_name: str,
    snapshot_url: str,
    api_key: str | None = None,
    timeout_s: int = 1800,
) -> bool:
    """Tell Qdrant to fetch a snapshot from ``snapshot_url`` directly.

    Uses ``PUT /collections/{name}/snapshots/recover`` which makes Qdrant
    issue its own HTTP GET for the URL — no multipart upload, no
    ``max_request_size_mb`` ceiling. This is the only working path for
    snapshots over Qdrant's default 32 MB upload limit (BGE-M3 v3 CWICR
    snapshots are 400–800 MB).

    The caller is responsible for ensuring ``snapshot_url`` is reachable
    *from inside the Qdrant process* — for dockerised Qdrant on Windows
    the host's localhost is exposed as ``host.docker.internal``. For
    cloud-hosted snapshots (HuggingFace, GitHub raw) the URL is reached
    over the public internet.

    Returns ``True`` on ``{"result": true, "status": "ok"}``. Raises
    :class:`SnapshotRestoreError` with Qdrant's verbatim error message on
    any non-success — callers convert that to a 502 with a human-readable
    hint (Windows AV / disk space / 404 / etc.).
    """

    if not qdrant_url:
        raise RuntimeError("restore_snapshot_from_url requires a server-mode Qdrant URL")

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("httpx is required for snapshot recover") from exc

    recover_url = qdrant_url.rstrip("/") + f"/collections/{collection_name}/snapshots/recover"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["api-key"] = api_key

    payload = {"location": snapshot_url, "priority": "snapshot"}
    # The Qdrant download + restore can take 5–15 min for 400 MB on a
    # slow link. httpx.Timeout splits connect/read/write/pool so the
    # read budget is what gets exhausted while we wait for the recover
    # response — bump it to the full timeout, leave connect/pool short
    # so a dead Qdrant URL fails fast.
    timeout = httpx.Timeout(connect=10.0, read=timeout_s, write=timeout_s, pool=10.0)

    logger.info(
        "Recovering snapshot for %s from %s via Qdrant recover-from-URL",
        collection_name,
        snapshot_url,
    )

    try:
        resp = httpx.put(recover_url, json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.error(
            "Snapshot recover-from-URL network error for %s -> %s: %s",
            snapshot_url,
            collection_name,
            exc,
        )
        raise SnapshotRestoreError(f"network error contacting Qdrant: {exc}") from exc

    try:
        body = resp.json()
    except ValueError:
        body = None

    if resp.is_success and isinstance(body, dict) and body.get("result") is True:
        logger.info(
            "Snapshot recovered into %s from %s (took %.1fs)",
            collection_name,
            snapshot_url,
            (body.get("time") or 0.0),
        )
        return True

    # Surface Qdrant's own error message verbatim — it's the most useful
    # diagnostic ("Failed to download snapshot from <url>: status - 404
    # Not Found", "Wrong input: <…>", "failed to sync file … Access is
    # denied. (os error 5)" on Windows Defender, etc).
    err = ""
    if isinstance(body, dict):
        status_obj = body.get("status")
        if isinstance(status_obj, dict):
            err = str(status_obj.get("error") or "")
    err = err or resp.text[:400] or f"HTTP {resp.status_code} from Qdrant"
    logger.error(
        "Snapshot recover-from-URL failed for %s -> %s: HTTP %s -- %s",
        snapshot_url,
        collection_name,
        resp.status_code,
        err,
    )
    raise SnapshotRestoreError(err)


def restore_snapshot_file(
    *,
    qdrant_url: str,
    collection_name: str,
    snapshot_path: Path,
    api_key: str | None = None,
    timeout_s: int = 1800,
) -> bool:
    """Upload a local ``.snapshot`` file via Qdrant's REST upload endpoint.

    qdrant-client's ``recover_snapshot(collection, location=...)`` only
    accepts URIs the *server* can fetch (``http://``, ``s3://``,
    ``file:///`` on the server's own disk). For a snapshot sitting on
    the operator's laptop or in CI workspace, we instead POST to
    ``/collections/{name}/snapshots/upload`` which streams the bytes
    multipart and creates the collection inline.

    Note: Qdrant's default ``service.max_request_size_mb`` is **32 MB**.
    Snapshots over that size (i.e. every BGE-M3 v3 CWICR snapshot,
    typically 400–800 MB) will be rejected with ``HTTP 500 — An error
    occurred processing field: snapshot``. Use
    :func:`restore_snapshot_from_url` for those instead, which sidesteps
    the multipart endpoint entirely.

    Returns ``True`` on a 2xx response, ``False`` (with an ERROR log) on
    any failure. Does not raise — the caller wants to continue with the
    next snapshot, not bail out.

    Embedded mode is rejected explicitly: passing a ``qdrant_url`` of
    ``None``/empty raises ``RuntimeError`` so the operator gets a clear
    "you need server mode" message instead of a confusing httpx error.
    """

    if not qdrant_url:
        raise RuntimeError(
            "restore_snapshot_file requires a server-mode Qdrant URL "
            "(set CWICR_QDRANT_URL or pass qdrant_url=...). Embedded "
            "mode does not support snapshot recovery — see "
            "qdrant_adapter module docstring."
        )

    snapshot_path = Path(snapshot_path)
    if not snapshot_path.is_file():
        raise FileNotFoundError(snapshot_path)

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover — httpx is in pyproject base deps
        raise RuntimeError(
            "httpx is required for snapshot upload; install via the project's base requirements"
        ) from exc

    upload_url = qdrant_url.rstrip("/") + f"/collections/{collection_name}/snapshots/upload?priority=snapshot"
    size_mb = snapshot_path.stat().st_size / 1e6
    logger.info(
        "Restoring snapshot %s -> %s (%.1f MB)",
        snapshot_path.name,
        collection_name,
        size_mb,
    )

    headers: dict[str, str] = {}
    if api_key:
        headers["api-key"] = api_key

    # httpx.Timeout(...) splits connect/read/write/pool — without this a
    # single int applies the same value to read, which quietly clamps the
    # whole upload to 5s on httpx>=0.25 if `timeout_s` is treated as a
    # connect-only hint. For a 400 MB+ snapshot Qdrant needs minutes to
    # ingest after the bytes land, and the previous 600 s read budget
    # turned out too tight on a slow Windows host (Issue: install timed
    # out at 603 s for USA_USD on localhost Qdrant). 30 min upper bound
    # is generous enough to cover the 800 MB GAEB-flavoured snapshots
    # that DDC plans to ship in v4 without surprise truncation.
    timeout = httpx.Timeout(connect=30.0, read=timeout_s, write=timeout_s, pool=30.0)
    try:
        with snapshot_path.open("rb") as fh:
            files = {
                "snapshot": (
                    snapshot_path.name,
                    fh,
                    "application/octet-stream",
                ),
            }
            resp = httpx.post(
                upload_url,
                files=files,
                headers=headers,
                timeout=timeout,
            )
    except httpx.HTTPError as exc:
        logger.error(
            "Snapshot upload network error for %s: %s",
            snapshot_path.name,
            exc,
        )
        return False

    if resp.is_success:
        # Qdrant returns 2xx the moment it accepts the upload, but the
        # body carries the actual restore outcome as ``{"result": true,
        # "status": "ok", "time": ...}``. A 200 with ``result: false``
        # (or a malformed body) means the bytes landed but the recover
        # step rejected them — historically this looked like a successful
        # install in the UI while the collection never appeared. Treat
        # it as a hard failure and let the caller raise.
        try:
            body = resp.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("result") is False:
            logger.error(
                "Qdrant accepted the upload but recover_snapshot returned result=false for %s -> %s: %s",
                snapshot_path.name,
                collection_name,
                resp.text[:200],
            )
            return False
        logger.info(
            "Snapshot %s restored into %s (status=%s)",
            snapshot_path.name,
            collection_name,
            resp.status_code,
        )
        return True

    logger.error(
        "Snapshot upload failed for %s -> %s: HTTP %s -- %s",
        snapshot_path.name,
        collection_name,
        resp.status_code,
        resp.text[:200],
    )
    return False


def load_ddc_snapshot_dir(
    snapshots_dir: Path | str,
    *,
    qdrant_url: str | None = None,
    api_key: str | None = None,
    dry_run: bool = False,
) -> SnapshotLoadSummary:
    """Walk a DDC repo clone and restore every BGE-M3 v3 snapshot found.

    ``snapshots_dir`` can point at any of:

    * The repo root (``OpenConstructionEstimate-DDC-CWICR/``) — recursively
      finds every ``RU___DDC_CWICR/RU_STPETERSBURG_*.snapshot`` etc.
    * A single language directory (``RU___DDC_CWICR/``).
    * A directory of mixed snapshots (e.g. a download bucket).

    Snapshots whose filenames don't match the BGE-M3 v3 pattern are
    pushed to ``summary.skipped`` and ignored. This includes the legacy
    ``*_EMBEDDINGS_3072_*`` files that ship in the same DDC repo —
    restoring those would clobber the v3 collection schema.

    Multiple snapshots resolving to the same language collection
    (``USA_USD`` + ``GB_LONDON`` -> ``cwicr_en_v3``) are processed in
    sorted order; each subsequent restore *replaces* the prior one
    (Qdrant's snapshot recovery semantics). A WARNING is logged so the
    operator can re-order if needed.

    ``dry_run=True`` walks the directory and resolves targets without
    issuing any HTTP requests — useful for previewing what a real run
    would do, especially against a large repo where the bandwidth cost
    is non-trivial.
    """

    snapshots_dir = Path(snapshots_dir)
    if not snapshots_dir.is_dir():
        raise FileNotFoundError(snapshots_dir)

    if qdrant_url is None:
        qdrant_url = getattr(get_settings(), "cwicr_qdrant_url", None)

    if not qdrant_url and not dry_run:
        raise RuntimeError(
            "load_ddc_snapshot_dir needs a server-mode Qdrant URL "
            "(CWICR_QDRANT_URL setting, or qdrant_url=). Pass "
            "dry_run=True to preview targets without contacting a server."
        )

    summary = SnapshotLoadSummary()
    seen_collections: dict[str, str] = {}

    for snap in sorted(snapshots_dir.rglob("*.snapshot")):
        target = cwicr_snapshot_target_for(snap.name)
        if target is None:
            summary.skipped.append(f"{snap.name}: not a BGE-M3 v3 DDC snapshot")
            continue

        prior = seen_collections.get(target)
        if prior is not None:
            logger.warning(
                "Two snapshots map to %s — %s will overwrite %s "
                "(last-write-wins). Operator: re-order or use a "
                "per-region collection layout if this is unwanted.",
                target,
                snap.name,
                prior,
            )
        seen_collections[target] = snap.name

        size_mb = snap.stat().st_size / 1e6
        if dry_run:
            summary.loaded.append(f"{snap.name} -> {target} (DRY RUN, {size_mb:.1f} MB)")
            continue

        try:
            ok = restore_snapshot_file(
                qdrant_url=qdrant_url,
                collection_name=target,
                snapshot_path=snap,
                api_key=api_key,
            )
        except (FileNotFoundError, RuntimeError) as exc:
            summary.errors.append(f"{snap.name} -> {target}: {type(exc).__name__}: {str(exc)[:200]}")
            continue

        if ok:
            summary.loaded.append(f"{snap.name} -> {target}")
        else:
            summary.errors.append(f"{snap.name} -> {target}: upload returned non-2xx (see ERROR log)")

    return summary


# ── Health probe ─────────────────────────────────────────────────────────


def server_collections(
    *,
    qdrant_url: str,
    api_key: str | None = None,
    timeout_s: int = 30,
) -> list[str]:
    """List the collections currently visible on a server-mode Qdrant.

    Used by the CLI's pre/post snapshot restore probe so the operator
    sees which ``cwicr_*_v3`` collections appeared after the run.
    Tolerates a missing /collections endpoint (returns empty list with
    a WARN log) so the CLI doesn't crash on an unexpected response —
    surfacing the snapshot summary is more useful than a stack trace.
    """

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("httpx required for server probe") from exc

    headers: dict[str, str] = {}
    if api_key:
        headers["api-key"] = api_key

    try:
        resp = httpx.get(
            qdrant_url.rstrip("/") + "/collections",
            headers=headers,
            timeout=timeout_s,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("server_collections probe failed: %s", exc)
        return []

    collections = (data.get("result") or {}).get("collections") or []
    return [str(c.get("name")) for c in collections if c.get("name")]


def enumerate_qdrant_v3_collections(
    *,
    qdrant_url: str | None = None,
    api_key: str | None = None,
    timeout_s: int = 30,
) -> list[str]:
    """Return the names of v3 collections currently on the configured Qdrant.

    Wraps :func:`server_collections` and filters to names matching the
    ``cwicr_*_v3`` convention so callers can answer "what BGE-M3 v3
    catalogues are actually installed on this server, including the ones
    not listed in :data:`CWICR_V3_CATALOGUES`?" — e.g. tenant-installed
    custom rate books that landed in Qdrant via the operator CLI.

    Resolves ``qdrant_url`` from ``cwicr_qdrant_url`` then ``qdrant_url``
    on :func:`get_settings` when not passed, mirroring the router's
    ``_v3_qdrant_url`` resolver. Returns an empty list (with a DEBUG log)
    when no server is configured or the probe fails — callers treat the
    result as authoritative only when non-empty, and the static
    registry remains the source of truth for installable cards.
    """
    if qdrant_url is None:
        try:
            settings = get_settings()
            qdrant_url = getattr(settings, "cwicr_qdrant_url", None) or getattr(settings, "qdrant_url", None)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("enumerate_qdrant_v3_collections: settings read failed: %s", exc)
            qdrant_url = None

    if not qdrant_url:
        logger.debug("enumerate_qdrant_v3_collections: no Qdrant URL configured — returning []")
        return []

    all_collections = server_collections(
        qdrant_url=qdrant_url,
        api_key=api_key,
        timeout_s=timeout_s,
    )
    return sorted(c for c in all_collections if c.startswith("cwicr_") and c.endswith("_v3"))


__all__ = [
    "SnapshotLoadSummary",
    "SnapshotRestoreError",
    "cwicr_snapshot_target_for",
    "enumerate_qdrant_v3_collections",
    "load_ddc_snapshot_dir",
    "restore_snapshot_file",
    "restore_snapshot_from_url",
    "server_collections",
]
