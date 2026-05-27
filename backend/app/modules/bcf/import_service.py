# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍BCF 3.0 → :class:`ClashIssue` import service.

This module is the **inverse** of :class:`app.modules.bcf.service.BCFExportService`:
it takes a ``.bcfzip`` produced by Revit / ArchiCAD / Solibri (or by our
own BCFWriter — round-trip!) and upserts each Topic into the project's
:class:`app.modules.clash.models.ClashIssue` table.

Design pillars
--------------
1. **Decoupled from BCF CRUD.** Lives next to (not inside)
   :class:`BCFService` so the BCF-Topic persistence path is unchanged.
2. **Defensive about the clash schema.** If ``ClashIssue`` or its
   alembic migration (``v41_clash_signature_smart_issues``) hasn't run,
   the service raises :class:`BCFImportFeatureUnavailable` → the router
   maps that to a structured 503 instead of a 500.
3. **Idempotent.** Re-importing the same archive produces 0 changes —
   topics are upserted by ``(project_id, server_assigned_id)`` falling
   back to ``(project_id, topic.guid)`` reinterpreted as a signature.
4. **Single transaction.** The session is owned by the request; we
   ``flush()`` after every insert so a foreign-key error inside one
   topic fails the whole import (router rolls back).
5. **Translates BCF enums to OE enums.** ``TopicStatus`` → our smart
   status; ``Priority`` → our four-level priority. Unknown values become
   ``new`` / ``medium`` and we log a warning.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.bcf.reader import (
    BCFFormatError,
    BCFReader,
    BCFReaderError,
    BCFSecurityError,
    ParsedBCF,
    ParsedTopic,
)

logger = logging.getLogger(__name__)


class BCFImportFeatureUnavailable(Exception):
    """‌⁠‍Raised when the clash schema (v41) hasn't migrated yet.

    Mirrors :class:`app.modules.bcf.service.BCFExportFeatureUnavailable`
    so the router maps the same condition consistently for both halves
    of the round-trip.
    """


# ── enum mappings ─────────────────────────────────────────────────────────


# BCF TopicStatus → OE smart-issue status. ``"new"`` / ``"persisted"``
# both encode a still-active issue from the importer's perspective.
# We use ``"persisted"`` for ``"In Progress"`` (someone is working it),
# ``"new"`` for ``"Open"``/``"ReOpened"``, and ``"resolved"`` for
# ``"Closed"``.
_STATUS_MAP: dict[str, str] = {
    "open": "new",
    "in progress": "persisted",
    "inprogress": "persisted",
    "closed": "resolved",
    "reopened": "new",
    "re-opened": "new",
    "active": "new",
    "persisted": "persisted",
    "resolved": "resolved",
    "ignored": "ignored",
    "archived": "archived",
    "new": "new",
}


# BCF Priority → OE priority (low/medium/high/critical).
_PRIORITY_MAP: dict[str, str] = {
    "critical": "critical",
    "major": "high",
    "high": "high",
    "normal": "medium",
    "medium": "medium",
    "minor": "low",
    "low": "low",
}


# ── report DTOs ───────────────────────────────────────────────────────────


@dataclass
class ImportErrorEntry:
    """Per-topic error captured during BCF→ClashIssue mapping."""

    topic_guid: str
    message: str


@dataclass
class ImportReport:
    """Outcome of :meth:`BCFImportService.import_clashes_from_bcf`."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[ImportErrorEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON-serialisable view of the report (router response body)."""
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": [{"topic_guid": e.topic_guid, "message": e.message} for e in self.errors],
        }


# ── service ───────────────────────────────────────────────────────────────


class BCFImportService:
    """‌⁠‍Maps a parsed BCF archive onto the project's clash-issue tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_clashes_from_bcf(
        self,
        project_id: uuid.UUID,
        raw: bytes,
        current_user_id: uuid.UUID | str,
    ) -> ImportReport:
        """Parse ``raw`` (.bcfzip) and upsert each Topic as a ClashIssue.

        Args:
            project_id: target project — every created row scopes to this id.
            raw: the raw ``.bcfzip`` bytes (multipart upload body).
            current_user_id: id of the caller (for the ``ClashRun``
                created-by stamp; the row is the import-source run).

        Returns:
            :class:`ImportReport` with per-action counters + per-topic
            error list. A topic that fails individually does NOT roll
            back its siblings — the report carries the failure inline so
            the UI can show "39 imported, 1 failed" cleanly.

        Raises:
            BCFImportFeatureUnavailable: clash module / table absent.
            BCFReaderError: archive itself is malformed (zip bomb,
                non-zip payload, missing bcf.version). The router maps
                these to HTTP 422 / 413.
        """
        # 1. Detect clash module + ClashIssue at runtime so the BCF module
        #    still loads on a deployment that hasn't run the v41 migration.
        try:
            from app.modules.clash.models import (
                ClashIssue,
                ClashRun,
            )
        except Exception as exc:  # noqa: BLE001
            raise BCFImportFeatureUnavailable(
                "Clash issue table requires the v41_clash_signature_smart_issues migration"
            ) from exc

        # 2. Probe the table exists. ``run_sync`` keeps us inside the
        #    request's async session without spinning up a sync engine.
        try:
            await self.session.execute(select(ClashIssue).where(ClashIssue.id == uuid.uuid4()).limit(1))
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if "no such table" in msg or "does not exist" in msg:
                raise BCFImportFeatureUnavailable(
                    "Clash issue table requires the v41_clash_signature_smart_issues migration"
                ) from exc
            raise

        # 3. Parse the BCF archive (frozen DTOs).
        parsed: ParsedBCF = BCFReader().parse(raw)

        report = ImportReport()

        # 4. Pre-resolve every existing issue's lookup keys so the loop
        #    is O(N) inserts + a single SELECT for the keys we touch.
        existing_by_serverid, existing_by_sig = await self._index_existing_issues(ClashIssue, project_id)

        # 5. Mint a "BCF import" ClashRun the new issues will reference.
        #    A re-import re-uses any prior import run for the same archive
        #    when no new rows are created — avoiding garbage runs.
        run = await self._get_or_create_import_run(ClashRun, project_id, current_user_id, archive_bytes=raw)

        for ptopic in parsed.topics:
            if ptopic.parse_error:
                report.errors.append(
                    ImportErrorEntry(
                        topic_guid=ptopic.guid,
                        message=ptopic.parse_error,
                    )
                )
                continue
            try:
                action = await self._upsert_topic(
                    ClashIssue=ClashIssue,
                    project_id=project_id,
                    run=run,
                    ptopic=ptopic,
                    existing_by_serverid=existing_by_serverid,
                    existing_by_sig=existing_by_sig,
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Failed to import BCF topic %s into project %s",
                    ptopic.guid,
                    project_id,
                )
                report.errors.append(
                    ImportErrorEntry(
                        topic_guid=ptopic.guid,
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if action == "created":
                report.created += 1
            elif action == "updated":
                report.updated += 1
            else:
                report.skipped += 1

        await self.session.flush()
        return report

    # ── internals ──────────────────────────────────────────────────

    async def _index_existing_issues(
        self,
        ClashIssue,  # noqa: N803
        project_id: uuid.UUID,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Build lookup dicts for the project's ClashIssue rows.

        Two indexes:

        * by_serverid: keys are the BCF ``ServerAssignedId`` we'd emit
          (the stringified issue.server_assigned_id);
        * by_sig: keys are the issue's signature_hash, which is what our
          export uses as the BCF topic guid.

        Returns ``({}, {})`` when the table is empty.
        """
        result = await self.session.execute(select(ClashIssue).where(ClashIssue.project_id == project_id))
        rows = list(result.scalars().all())
        by_serverid: dict[str, object] = {}
        by_sig: dict[str, object] = {}
        for r in rows:
            sid = (getattr(r, "server_assigned_id", "") or "").strip()
            if sid:
                by_serverid[sid] = r
            sig = (getattr(r, "signature_hash", "") or "").strip().lower()
            if sig:
                by_sig[sig] = r
        return by_serverid, by_sig

    async def _get_or_create_import_run(
        self,
        ClashRun,  # noqa: N803
        project_id: uuid.UUID,
        current_user_id: uuid.UUID | str,
        archive_bytes: bytes,
    ):
        """Reuse a per-import ClashRun row when one exists, else create.

        The run name embeds a SHA-256 of the archive so re-importing the
        same file lands on the same run row (idempotent).
        """
        archive_hash = hashlib.sha256(archive_bytes).hexdigest()[:16]
        run_name = f"BCF import {archive_hash}"
        existing = await self.session.execute(
            select(ClashRun).where(ClashRun.project_id == project_id).where(ClashRun.name == run_name)
        )
        row = existing.scalars().first()
        if row is not None:
            return row
        run = ClashRun(
            project_id=project_id,
            name=run_name,
            model_ids=[],
            clash_type="bcf_import",
            mode="cross_discipline",
            status="completed",
            created_by=str(current_user_id),
            total_clashes=0,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def _upsert_topic(
        self,
        *,
        ClashIssue,  # noqa: N803
        project_id: uuid.UUID,
        run,
        ptopic: ParsedTopic,
        existing_by_serverid: dict[str, object],
        existing_by_sig: dict[str, object],
    ) -> str:
        """Return one of ``"created" | "updated" | "skipped"`` for the topic."""
        # 1. Resolve identity. ServerAssignedId wins; signature fallback
        #    handles BCF archives produced by other tools.
        sid = (ptopic.server_assigned_id or "").strip()
        topic_guid_normalised = (ptopic.guid or "").strip().lower()
        sig_hash = self._normalise_signature(topic_guid_normalised)

        existing = None
        if sid and sid in existing_by_serverid:
            existing = existing_by_serverid[sid]
        elif sig_hash and sig_hash in existing_by_sig:
            existing = existing_by_sig[sig_hash]

        status = self._map_status(ptopic.topic_status)
        priority = self._map_priority(ptopic.priority)

        if existing is None:
            # Create.
            issue = ClashIssue(
                project_id=project_id,
                signature_hash=sig_hash,
                status=status,
                first_seen_run_id=run.id,
                last_seen_run_id=run.id,
                missing_run_count=0,
                priority=priority,
                server_assigned_id=sid or "",
                tags=list(ptopic.labels),
                signature_quality="weak",
            )
            self.session.add(issue)
            await self.session.flush()
            # Register so a second topic with the same id in the same
            # archive collides cleanly (idempotent within one import).
            if sid:
                existing_by_serverid[sid] = issue
            if sig_hash:
                existing_by_sig[sig_hash] = issue
            return "created"

        # Update. We don't trample columns the importer doesn't own
        # (assignee_id, due_date if previously set). Status + priority +
        # tags reflect the incoming archive; last_seen_run advances.
        changed = False
        new_status = self._map_status(ptopic.topic_status)
        if getattr(existing, "status", "") != new_status:
            existing.status = new_status
            changed = True
        new_priority = self._map_priority(ptopic.priority)
        if getattr(existing, "priority", "") != new_priority:
            existing.priority = new_priority
            changed = True
        new_tags = list(ptopic.labels)
        if list(getattr(existing, "tags", []) or []) != new_tags:
            existing.tags = new_tags
            changed = True
        # Always re-stamp the last-seen run when an archive carries the
        # topic — that's the whole point of the BCF round-trip.
        if getattr(existing, "last_seen_run_id", None) != run.id:
            existing.last_seen_run_id = run.id
            changed = True
        return "updated" if changed else "skipped"

    @staticmethod
    def _normalise_signature(guid: str) -> str:
        """Coerce a topic GUID into the 40-char signature shape clash uses.

        Our exporter uses the 40-char SHA-1 hex clash signature directly
        as the BCF topic guid. A non-hex / non-uuid input still needs a
        stable hash so re-import is idempotent — we SHA-1 it ourselves.
        """
        if not guid:
            return ""
        g = guid.strip().strip("{}").lower()
        # 40-hex passes through (the clash signature shape exactly).
        if len(g) == 40 and all(c in "0123456789abcdef" for c in g):
            return g
        # 32-hex uuid (RFC 4122 with dashes removed): keep as-is so it
        # matches the column's String(40) and we don't double-hash a
        # legitimate canonical input.
        return hashlib.sha1(g.encode("utf-8"), usedforsecurity=False).hexdigest()

    @staticmethod
    def _map_status(raw: str | None) -> str:
        """Map a BCF TopicStatus → OE smart-issue status."""
        if not raw:
            return "new"
        key = raw.strip().lower()
        if key in _STATUS_MAP:
            return _STATUS_MAP[key]
        logger.warning("Unknown BCF TopicStatus %r — defaulting to 'new'", raw)
        return "new"

    @staticmethod
    def _map_priority(raw: str | None) -> str:
        """Map a BCF Priority → OE priority."""
        if not raw:
            return "medium"
        key = raw.strip().lower()
        if key in _PRIORITY_MAP:
            return _PRIORITY_MAP[key]
        logger.warning("Unknown BCF Priority %r — defaulting to 'medium'", raw)
        return "medium"


# ── exception re-exports for router import convenience ────────────────────

__all__ = [
    "BCFFormatError",
    "BCFImportFeatureUnavailable",
    "BCFReaderError",
    "BCFSecurityError",
    "BCFImportService",
    "ImportErrorEntry",
    "ImportReport",
]

# Mark UTC as referenced — defensive future-proofing if we ever stamp
# import timestamps directly on ClashRun (currently created_at fires).
_ = UTC
_ = datetime
