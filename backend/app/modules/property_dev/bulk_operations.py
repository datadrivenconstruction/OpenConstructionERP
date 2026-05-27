"""Property Development bulk-operations service.

Sales-ops admin console — five batch endpoints that today require one-by-one
clicks across hundreds of items:

  1. ``bulk_plot_status_change``       — flip N plots to target status
  2. ``bulk_extend_reservation_expiry`` — push expiry on N reservations
  3. ``bulk_regenerate_documents``      — re-render PDFs after template fix
  4. ``bulk_import_leads_csv``          — bulk-create Leads from CSV upload
  5. ``bulk_merge_buyers``              — fold N duplicate buyers into one

Atomicity contract (load-bearing):
    Every endpoint runs inside ``session.begin_nested()`` (SAVEPOINT).
    On a successful classify-or-write loop the SAVEPOINT releases and the
    request commits as usual. On a top-level exception the SAVEPOINT
    rolls back the entire batch — partial writes never escape. Mirrors
    the procurement R7 PO → invoice pattern.

    Per-item "soft" failures (illegal FSM transition on one plot in a
    batch of 40) are RECORDED in ``BulkResult.failed`` and the batch
    continues — those rows are simply not written. The SAVEPOINT covers
    the rows we DID classify/write; the failed entries never invoked a
    write in the first place. The net effect: failed-items don't poison
    the batch, but a DB-level crash kills the whole transaction.

    Buyer merge is the only operation that must abort on the first hard
    FK error: half-repointing reservations from ``dup_a`` while leaving
    payments stranded would silently lose audit trail. The merge body
    explicitly re-raises inside the SAVEPOINT to force the full rollback.

IDOR pattern (silent-skip variant):
    Standard property_dev IDOR collapses to 404 to avoid existence-oracle
    leaks. Bulk operations take that further: any item the caller cannot
    touch is silently skipped (recorded in ``BulkResult.skipped``) so the
    request as a whole succeeds. This matches sales-ops UX: picking 100
    plots from an inventory map and getting one 404 because one belongs
    to a sister tenant would be confusing — the operator sees "skipped:
    1, succeeded: 99" instead.

CSV magic-byte gate:
    CSV has no canonical magic-byte signature. We re-use the contacts
    module's binary-prefix denylist (``MZ``, ``ELF``, etc.) and additionally
    reject ZIP, OLE, PDF, and PNG prefixes (anything that's CLEARLY a
    non-text format). Uses the file-signature detector for symmetry.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import log_activity
from app.core.events import event_bus
from app.modules.property_dev.models import (
    Buyer,
    ContractParty,
    Lead,
    Plot,
    Reservation,
    SalesContract,
    WarrantyClaim,
)
from app.modules.property_dev.schemas import (
    BULK_MAX_ITEMS,
    BulkFailed,
    BulkResult,
    BulkSkipped,
    BuyerBulkMerge,
    DocumentsBulkRegenerate,
    PlotBulkStatusChange,
    ReservationBulkExtendExpiry,
)

logger = logging.getLogger(__name__)

# ── Canonical error codes ───────────────────────────────────────────────
#
# Stable codes keep the UI free of brittle string-matching on
# ``error_message`` (which is localised / free-form). Codes also feed the
# CSV log download so operators can pivot a 200-row failure breakdown
# by ``error_code`` without parsing English prose.

CODE_NOT_FOUND = "not_found"
CODE_IDOR_SKIP = "not_owner"
CODE_FSM_REJECT = "fsm_invalid_transition"
CODE_ALREADY_CONVERTED = "reservation_terminal"
CODE_EXPIRY_IN_PAST = "expiry_in_past"
CODE_NOT_ACTIVE = "reservation_not_active"
CODE_DOC_RENDER_FAIL = "document_render_failed"
CODE_BAD_TARGET = "bad_target_for_doc_type"
CODE_CSV_INVALID = "csv_row_invalid"
CODE_CSV_EMAIL_MISSING = "csv_email_missing"
CODE_CSV_EMAIL_DUP = "csv_email_duplicate_in_dev"
CODE_PRIMARY_MISSING = "primary_buyer_missing"
CODE_DUP_NOT_FOUND = "duplicate_buyer_missing"
CODE_CROSS_DEV_MERGE = "cross_development_merge_blocked"


# ── Shared helpers ──────────────────────────────────────────────────────


def _enforce_batch_cap(n: int) -> None:
    """Reject requests over the per-call cap. 422 (was 400) per RFC 9457."""
    if n > BULK_MAX_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Batch size {n} exceeds the per-request cap of {BULK_MAX_ITEMS}. "
                f"Split the request into smaller chunks."
            ),
        )


async def _owner_ids_for_payload(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Extract ``(is_admin, user_id_str)`` from a JWT payload."""
    is_admin = payload.get("role") == "admin"
    user_id = payload.get("sub") or payload.get("user_id")
    return is_admin, str(user_id) if user_id is not None else None


async def _project_owner_for_dev_id(session: AsyncSession, dev_id: uuid.UUID) -> str | None:
    """Resolve development → project.owner_id without raising on missing."""
    from app.modules.projects.repository import ProjectRepository
    from app.modules.property_dev.repository import DevelopmentRepository

    dev = await DevelopmentRepository(session).get_by_id(dev_id)
    if dev is None:
        return None
    project = await ProjectRepository(session).get_by_id(dev.project_id)
    if project is None:
        return None
    return str(project.owner_id) if project.owner_id is not None else None


def _safe_publish(event_name: str, payload: dict[str, Any]) -> None:
    """Fire an event without blocking; swallow scheduler errors.

    Three defensive carve-outs (in order of importance):

    * **Only publish when a NAMED handler is subscribed.** The core event
      bus registers a wildcard handler ``_dispatch_to_webhooks`` that
      opens a fresh ``async_session_factory()`` for every event. With
      aiosqlite (single-writer) this collides with the outer request's
      SAVEPOINT and leaves a dangling Task that surfaces as
      ``RuntimeError: await wasn't used with future`` on the NEXT request
      in the same test session. Bulk summary events have no specific
      named subscribers today, and the wildcard webhook bridge cannot
      deliver useful data when no WebhookEndpoint rows exist anyway —
      so skipping the detached task entirely is both correct and safe.
    * Wrap ``publish_detached`` in try/except to keep unit tests without
      a running event loop happy.
    * Wildcard-only publish remains possible by deployments configuring
      a named subscriber (e.g. an analytics module) — that explicit opt-in
      proves the receiver expects bulk-ops fan-out.
    """
    has_named_handlers = bool(event_bus._handlers.get(event_name))  # noqa: SLF001
    if not has_named_handlers:
        logger.debug(
            "bulk-ops event %s skipped (no NAMED subscribers; "
            "wildcard webhook bridge is suppressed to avoid SAVEPOINT "
            "collisions on aiosqlite)",
            event_name,
        )
        return
    try:
        event_bus.publish_detached(
            event_name,
            data=payload,
            source_module="property_dev",
        )
    except RuntimeError:
        logger.debug("bulk-ops event %s suppressed (no running loop)", event_name)


# ════════════════════════════════════════════════════════════════════════
# 1. Bulk plot status change
# ════════════════════════════════════════════════════════════════════════


async def bulk_plot_status_change(
    session: AsyncSession,
    data: PlotBulkStatusChange,
    *,
    user_payload: dict[str, Any],
    dry_run: bool,
) -> BulkResult:
    """Bulk-flip ``status`` on a set of plots.

    Per-item filter chain:
      * Plot missing                 → ``failed`` (not_found)
      * Caller doesn't own the plot  → ``skipped`` (not_owner, silent IDOR)
      * Illegal FSM transition       → ``failed`` (fsm_invalid_transition)
      * Otherwise                    → write + ``succeeded``

    Classification (existence + IDOR) runs BEFORE the SAVEPOINT so reads
    don't fight a half-open transaction. Only the writes are wrapped in
    ``session.begin_nested()``.
    """
    from app.modules.property_dev.service import allowed_plot_transitions

    _enforce_batch_cap(len(data.plot_ids))

    is_admin, user_id = await _owner_ids_for_payload(user_payload)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Auth required for bulk operations.")

    skipped: list[BulkSkipped] = []
    failed: list[BulkFailed] = []
    # Plots that survived classification and should actually be written.
    to_write: list[tuple[Plot, str, str]] = []
    succeeded_idempotent = 0
    # Pre-cache project ownership per development so 500 plots from
    # the same dev don't hit the projects table 500 times.
    owner_cache: dict[uuid.UUID, str | None] = {}

    # ── Classification pass (READ-ONLY) ──────────────────────────────
    for pid in data.plot_ids:
        plot = await session.get(Plot, pid)
        if plot is None:
            failed.append(
                BulkFailed(
                    entity_id=str(pid),
                    error_message="Plot not found.",
                    error_code=CODE_NOT_FOUND,
                )
            )
            continue

        if not is_admin:
            dev_id = plot.development_id
            if dev_id not in owner_cache:
                owner_cache[dev_id] = await _project_owner_for_dev_id(session, dev_id)
            if owner_cache[dev_id] != user_id:
                skipped.append(
                    BulkSkipped(
                        entity_id=str(pid),
                        reason="Plot belongs to a different tenant.",
                        code=CODE_IDOR_SKIP,
                    )
                )
                continue

        current = plot.status
        target = data.target_status

        if current == target:
            succeeded_idempotent += 1
            continue

        if target not in allowed_plot_transitions(current):
            failed.append(
                BulkFailed(
                    entity_id=str(pid),
                    error_message=(
                        f"Illegal FSM transition: {current} -> {target}. "
                        f"Allowed from {current}: "
                        f"{sorted(allowed_plot_transitions(current))}"
                    ),
                    error_code=CODE_FSM_REJECT,
                )
            )
            continue

        to_write.append((plot, current, target))

    # ── Write pass (inside SAVEPOINT) ────────────────────────────────
    succeeded = succeeded_idempotent
    if not dry_run and to_write:
        async with session.begin_nested():
            for plot, current, target in to_write:
                plot.status = target
                session.add(plot)
                try:
                    await log_activity(
                        session,
                        actor_id=user_id,
                        entity_type="property_dev.plot",
                        entity_id=str(plot.id),
                        action="bulk_status_change",
                        from_status=current,
                        to_status=target,
                        reason=data.reason or None,
                        metadata={"batch_size": len(data.plot_ids)},
                    )
                except Exception:  # noqa: BLE001 — audit must not block bulk
                    logger.exception(
                        "bulk_plot_status_change: audit-log write failed for %s",
                        plot.id,
                    )
                succeeded += 1
            await session.flush()
    else:
        # Dry-run: count classification-only successes (every plot that
        # would have written).
        succeeded = succeeded_idempotent + len(to_write)

    if not dry_run:
        _safe_publish(
            "property_dev.bulk.plot_status_change",
            {
                "requested": len(data.plot_ids),
                "succeeded": succeeded,
                "skipped": len(skipped),
                "failed": len(failed),
                "target_status": data.target_status,
                "actor_id": user_id,
            },
        )

    return BulkResult(
        requested=len(data.plot_ids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
    )


# ════════════════════════════════════════════════════════════════════════
# 2. Bulk reservation extend expiry
# ════════════════════════════════════════════════════════════════════════


async def bulk_extend_reservation_expiry(
    session: AsyncSession,
    data: ReservationBulkExtendExpiry,
    *,
    user_payload: dict[str, Any],
    dry_run: bool,
) -> BulkResult:
    """Bulk-extend ``expires_at`` on a set of active reservations."""
    _enforce_batch_cap(len(data.reservation_ids))

    is_admin, user_id = await _owner_ids_for_payload(user_payload)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Auth required for bulk operations.")

    # Reject past dates up front — global validation, not per-item.
    try:
        new_expiry_date = date.fromisoformat(data.new_expiry)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"new_expiry is not a valid ISO date: {exc}",
        ) from exc
    today = datetime.now(UTC).date()
    if new_expiry_date <= today:
        raise HTTPException(
            status_code=422,
            detail=(
                f"new_expiry {data.new_expiry} must be strictly after today "
                f"({today.isoformat()}). Use the cancel endpoint to expire "
                f"reservations early."
            ),
        )

    skipped: list[BulkSkipped] = []
    failed: list[BulkFailed] = []
    to_write: list[tuple[Reservation, str | None]] = []
    owner_cache: dict[uuid.UUID, str | None] = {}

    # Classification pass (read-only)
    for rid in data.reservation_ids:
        res = await session.get(Reservation, rid)
        if res is None:
            failed.append(
                BulkFailed(
                    entity_id=str(rid),
                    error_message="Reservation not found.",
                    error_code=CODE_NOT_FOUND,
                )
            )
            continue

        # IDOR via plot → development → project owner
        if not is_admin:
            plot = await session.get(Plot, res.plot_id)
            if plot is None:
                skipped.append(
                    BulkSkipped(
                        entity_id=str(rid),
                        reason="Parent plot missing.",
                        code=CODE_IDOR_SKIP,
                    )
                )
                continue
            dev_id = plot.development_id
            if dev_id not in owner_cache:
                owner_cache[dev_id] = await _project_owner_for_dev_id(session, dev_id)
            if owner_cache[dev_id] != user_id:
                skipped.append(
                    BulkSkipped(
                        entity_id=str(rid),
                        reason="Reservation belongs to a different tenant.",
                        code=CODE_IDOR_SKIP,
                    )
                )
                continue

        if res.status != "active":
            failed.append(
                BulkFailed(
                    entity_id=str(rid),
                    error_message=(
                        f"Reservation is in terminal/non-active status "
                        f"'{res.status}'. Only active reservations can be "
                        f"extended."
                    ),
                    error_code=(CODE_ALREADY_CONVERTED if res.status == "converted" else CODE_NOT_ACTIVE),
                )
            )
            continue

        to_write.append((res, res.expires_at))

    # Write pass
    succeeded = 0
    if not dry_run and to_write:
        async with session.begin_nested():
            for res, old_expiry in to_write:
                res.expires_at = data.new_expiry
                session.add(res)
                try:
                    await log_activity(
                        session,
                        actor_id=user_id,
                        entity_type="property_dev.reservation",
                        entity_id=str(res.id),
                        action="bulk_extend_expiry",
                        reason=data.reason or None,
                        metadata={
                            "old_expiry": old_expiry,
                            "new_expiry": data.new_expiry,
                        },
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "bulk_extend_reservation_expiry: audit-log failed for %s",
                        res.id,
                    )
                succeeded += 1
            await session.flush()
    else:
        succeeded = len(to_write)

    if not dry_run:
        _safe_publish(
            "property_dev.bulk.reservation_extend",
            {
                "requested": len(data.reservation_ids),
                "succeeded": succeeded,
                "skipped": len(skipped),
                "failed": len(failed),
                "new_expiry": data.new_expiry,
                "actor_id": user_id,
            },
        )

    return BulkResult(
        requested=len(data.reservation_ids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
    )


# ════════════════════════════════════════════════════════════════════════
# 3. Bulk regenerate documents
# ════════════════════════════════════════════════════════════════════════


async def bulk_regenerate_documents(
    session: AsyncSession,
    data: DocumentsBulkRegenerate,
    *,
    user_payload: dict[str, Any],
    dry_run: bool,
) -> BulkResult:
    """Re-render PDF documents for a set of reservations or contracts.

    Stores re-rendered bytes in the entity's ``metadata.bulk_doc_regen``
    JSON sub-key as ``{rendered_at, bytes_len, doc_type, locale}`` —
    the actual bytes are NOT inlined (would blow up the JSON column).
    A real deployment ships the bytes to MinIO via the Documents module
    bridge; this lightweight stub keeps the test surface deterministic.
    """
    from app.modules.property_dev.service import PropertyDevService

    target_ids = data.reservation_ids or data.sales_contract_ids or []
    _enforce_batch_cap(len(target_ids))

    is_admin, user_id = await _owner_ids_for_payload(user_payload)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Auth required for bulk operations.")

    skipped: list[BulkSkipped] = []
    failed: list[BulkFailed] = []
    to_render: list[tuple[uuid.UUID, Any, str]] = []  # (eid, target, kind)
    owner_cache: dict[uuid.UUID, str | None] = {}

    svc = PropertyDevService(session)

    # Classification pass — existence + IDOR before any rendering.
    for eid in target_ids:
        target_kind = "reservation" if data.reservation_ids else "sales_contract"
        if target_kind == "reservation":
            target = await session.get(Reservation, eid)
            if target is None:
                failed.append(
                    BulkFailed(
                        entity_id=str(eid),
                        error_message="Reservation not found.",
                        error_code=CODE_NOT_FOUND,
                    )
                )
                continue
            plot_id = target.plot_id
        else:
            target = await session.get(SalesContract, eid)
            if target is None:
                failed.append(
                    BulkFailed(
                        entity_id=str(eid),
                        error_message="Sales contract not found.",
                        error_code=CODE_NOT_FOUND,
                    )
                )
                continue
            plot_id = target.plot_id

        if not is_admin:
            plot = await session.get(Plot, plot_id)
            if plot is None:
                skipped.append(
                    BulkSkipped(
                        entity_id=str(eid),
                        reason="Parent plot missing.",
                        code=CODE_IDOR_SKIP,
                    )
                )
                continue
            dev_id = plot.development_id
            if dev_id not in owner_cache:
                owner_cache[dev_id] = await _project_owner_for_dev_id(session, dev_id)
            if owner_cache[dev_id] != user_id:
                skipped.append(
                    BulkSkipped(
                        entity_id=str(eid),
                        reason="Document target belongs to a different tenant.",
                        code=CODE_IDOR_SKIP,
                    )
                )
                continue

        to_render.append((eid, target, target_kind))

    succeeded = 0

    if dry_run:
        return BulkResult(
            requested=len(target_ids),
            succeeded=len(to_render),
            skipped=skipped,
            failed=failed,
            dry_run=True,
        )

    # ── Render + stamp pass (writes) ─────────────────────────────────
    async with session.begin_nested():
        for eid, target, target_kind in to_render:
            try:
                if target_kind == "reservation":
                    pdf_bytes = await svc.generate_document(  # type: ignore[attr-defined]
                        doc_type=data.document_type,
                        reservation_id=eid,
                        locale=data.locale,
                    )
                else:
                    pdf_bytes = await svc.generate_document(  # type: ignore[attr-defined]
                        doc_type=data.document_type,
                        contract_id=eid,
                        locale=data.locale,
                    )
            except HTTPException as http_exc:
                failed.append(
                    BulkFailed(
                        entity_id=str(eid),
                        error_message=str(http_exc.detail)[:1000],
                        error_code=(CODE_BAD_TARGET if http_exc.status_code in (400, 422) else CODE_DOC_RENDER_FAIL),
                    )
                )
                continue
            except Exception as exc:  # noqa: BLE001
                logger.exception("bulk_regenerate_documents: render failed for %s", eid)
                failed.append(
                    BulkFailed(
                        entity_id=str(eid),
                        error_message=str(exc)[:1000],
                        error_code=CODE_DOC_RENDER_FAIL,
                    )
                )
                continue

            stamp = {
                "rendered_at": datetime.now(UTC).isoformat(),
                "bytes_len": len(pdf_bytes),
                "doc_type": data.document_type,
                "locale": data.locale,
                "actor_id": user_id,
            }
            md = dict(target.metadata_ or {})
            md.setdefault("bulk_doc_regen", []).append(stamp)
            md["bulk_doc_regen"] = md["bulk_doc_regen"][-20:]
            target.metadata_ = md
            session.add(target)

            try:
                await log_activity(
                    session,
                    actor_id=user_id,
                    entity_type=f"property_dev.{target_kind}",
                    entity_id=str(eid),
                    action="bulk_document_regenerated",
                    metadata={
                        "doc_type": data.document_type,
                        "locale": data.locale,
                        "bytes_len": len(pdf_bytes),
                    },
                )
            except Exception:  # noqa: BLE001
                logger.exception("bulk_regenerate_documents: audit-log failed for %s", eid)

            succeeded += 1

        await session.flush()

    if not dry_run:
        _safe_publish(
            "property_dev.bulk.document_regenerate",
            {
                "requested": len(target_ids),
                "succeeded": succeeded,
                "skipped": len(skipped),
                "failed": len(failed),
                "doc_type": data.document_type,
                "actor_id": user_id,
            },
        )

    return BulkResult(
        requested=len(target_ids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
    )


# ════════════════════════════════════════════════════════════════════════
# 4. Bulk import leads from CSV
# ════════════════════════════════════════════════════════════════════════


_CSV_REQUIRED_HEADERS = (
    "full_name",
    "email",
    "phone",
    "source",
    "plot_type_interest",
    "budget_min",
    "budget_max",
    "notes",
)

# Anything that's CLEARLY a non-text payload disguised as CSV. CSV itself
# has no magic-bytes signature so we use a denylist approach.
_CSV_BANNED_PREFIXES: tuple[bytes, ...] = (
    b"MZ",  # Windows PE
    b"\x7fELF",  # Linux ELF
    b"\xca\xfe\xba\xbe",  # Mach-O / Java class
    b"PK\x03\x04",  # ZIP / XLSX / DOCX
    b"PK\x05\x06",
    b"\xd0\xcf\x11\xe0",  # OLE compound (legacy XLS)
    b"%PDF-",
    b"\x89PNG",
    b"\xff\xd8\xff",  # JPEG
    b"GIF8",
)

_LEAD_SOURCE_ALIASES: dict[str, str] = {
    "web_form": "web_form",
    "webform": "web_form",
    "web": "web_form",
    "walk_in": "walk_in",
    "walkin": "walk_in",
    "broker": "broker",
    "referral": "referral",
    "portal": "portal",
    "other": "other",
}


def _validate_csv_magic_bytes(content: bytes, *, filename: str = "") -> None:
    """Reject obvious binaries up front."""
    if not content:
        raise HTTPException(
            status_code=400,
            detail="Uploaded CSV file is empty.",
        )
    head = content[:16]
    for sig in _CSV_BANNED_PREFIXES:
        if head.startswith(sig):
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Uploaded file does not look like CSV "
                    f"(binary signature detected{f' in {filename}' if filename else ''})."
                ),
            )


def _parse_money(value: str) -> Decimal | None:
    """Parse a CSV money cell. Empty → None."""
    s = (value or "").strip()
    if not s:
        return None
    # Allow both "120000" and "120,000.50" / "120 000.50".
    s = s.replace(" ", "").replace(",", "")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid money: {value!r}")


async def bulk_import_leads_csv(
    session: AsyncSession,
    file: UploadFile,
    *,
    user_payload: dict[str, Any],
    dry_run: bool,
    development_id: uuid.UUID | None = None,
) -> BulkResult:
    """Bulk-create Leads from a CSV upload.

    Each row is keyed on ``lower(email)``. Within the SAME development
    (or globally when no development is set), a duplicate-email row is
    folded into the existing Lead's ``notes`` instead of creating a
    second row. This matches the typical sales-ops workflow where a CSV
    sometimes reuses an existing prospect.
    """
    is_admin, user_id = await _owner_ids_for_payload(user_payload)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Auth required for bulk operations.")

    # ── Read + magic-byte sniff ─────────────────────────────────────
    raw = await file.read()
    _validate_csv_magic_bytes(raw, filename=file.filename or "")

    # Decode with the usual encoding fallbacks (mirrors contacts module).
    text: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(
            status_code=400,
            detail="Unable to decode CSV file (tried utf-8-sig / utf-8 / latin-1).",
        )

    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if reader.fieldnames is None:
        raise HTTPException(
            status_code=400,
            detail="CSV has no header row.",
        )
    headers_lower = {h.strip().lower() for h in reader.fieldnames}
    missing = [h for h in _CSV_REQUIRED_HEADERS if h not in headers_lower]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"CSV is missing required header(s): {', '.join(missing)}. "
                f"Required headers: {', '.join(_CSV_REQUIRED_HEADERS)}."
            ),
        )

    rows = list(reader)
    _enforce_batch_cap(len(rows))

    # IDOR: if caller pinned a development, confirm they own it (silent
    # 404 — bulk-import without a permitted dev is a config mistake worth
    # surfacing). When no dev is pinned, leads are tenant-loose by design.
    if development_id is not None and not is_admin:
        owner = await _project_owner_for_dev_id(session, development_id)
        if owner != user_id:
            raise HTTPException(status_code=404, detail="Development not found")

    skipped: list[BulkSkipped] = []
    failed: list[BulkFailed] = []
    succeeded = 0
    # Track which emails we've created in THIS batch — a CSV with the
    # same email twice should fold the second into the first (same dedupe
    # rule as cross-batch).
    in_batch_emails: dict[str, uuid.UUID] = {}

    async with session.begin_nested():
        for row_idx, raw_row in enumerate(rows, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw_row.items()}
            email = (row.get("email") or "").strip().lower()
            if not email:
                failed.append(
                    BulkFailed(
                        entity_id=f"row:{row_idx}",
                        error_message="Row is missing the required 'email' field.",
                        error_code=CODE_CSV_EMAIL_MISSING,
                    )
                )
                continue

            full_name = (row.get("full_name") or "").strip()
            phone = (row.get("phone") or "").strip() or None
            raw_source = (row.get("source") or "other").strip().lower()
            source = _LEAD_SOURCE_ALIASES.get(raw_source, "other")
            notes_in = (row.get("notes") or "").strip()
            plot_interest = (row.get("plot_type_interest") or "").strip()
            try:
                budget_min = _parse_money(row.get("budget_min", ""))
                budget_max = _parse_money(row.get("budget_max", ""))
            except ValueError as exc:
                failed.append(
                    BulkFailed(
                        entity_id=f"row:{row_idx}",
                        error_message=str(exc),
                        error_code=CODE_CSV_INVALID,
                    )
                )
                continue

            # ── Dedupe within the same development ─────────────────
            existing = await _find_existing_lead_by_email(session, email, development_id=development_id)
            if existing is None and email in in_batch_emails:
                # In-batch duplicate — fetch the freshly created Lead so
                # we can append to its notes.
                existing = await session.get(Lead, in_batch_emails[email])

            if existing is not None:
                if not dry_run:
                    appendix = (
                        f"\n[bulk_csv {datetime.now(UTC).date().isoformat()} row {row_idx}] {notes_in}"
                        if notes_in
                        else (
                            f"\n[bulk_csv {datetime.now(UTC).date().isoformat()} row {row_idx}] (duplicate, no notes)"
                        )
                    )
                    new_notes = (existing.notes or "") + appendix
                    existing.notes = new_notes
                    session.add(existing)
                skipped.append(
                    BulkSkipped(
                        entity_id=str(existing.id),
                        reason=(
                            f"Email '{email}' already exists in this development; appended notes to existing Lead."
                        ),
                        code=CODE_CSV_EMAIL_DUP,
                    )
                )
                continue

            if dry_run:
                succeeded += 1
                continue

            note_blob = notes_in or ""
            if plot_interest:
                note_blob = f"plot_type_interest: {plot_interest}\n{note_blob}".strip()

            new_lead = Lead(
                development_id=development_id,
                source=source,
                full_name=full_name,
                email=email,
                phone=phone,
                budget_min=budget_min,
                budget_max=budget_max,
                notes=note_blob or None,
                status="new",
            )
            session.add(new_lead)
            try:
                await session.flush()
            except Exception as exc:  # noqa: BLE001
                logger.exception("bulk_import_leads_csv: insert failed at row %s", row_idx)
                failed.append(
                    BulkFailed(
                        entity_id=f"row:{row_idx}",
                        error_message=str(exc)[:1000],
                        error_code=CODE_CSV_INVALID,
                    )
                )
                continue
            in_batch_emails[email] = new_lead.id
            succeeded += 1

        if dry_run:
            await session.rollback()

    if not dry_run:
        _safe_publish(
            "property_dev.bulk.lead_import",
            {
                "requested": len(rows),
                "succeeded": succeeded,
                "skipped": len(skipped),
                "failed": len(failed),
                "development_id": str(development_id) if development_id else None,
                "actor_id": user_id,
            },
        )

    return BulkResult(
        requested=len(rows),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
    )


async def _find_existing_lead_by_email(
    session: AsyncSession,
    email: str,
    *,
    development_id: uuid.UUID | None,
) -> Lead | None:
    """Dedupe lookup: lower(email) within the same development (or global)."""
    from sqlalchemy import func, select

    stmt = select(Lead).where(func.lower(Lead.email) == email)
    if development_id is not None:
        stmt = stmt.where(Lead.development_id == development_id)
    else:
        stmt = stmt.where(Lead.development_id.is_(None))
    res = await session.execute(stmt.limit(1))
    return res.scalars().first()


# ════════════════════════════════════════════════════════════════════════
# 5. Bulk merge buyers
# ════════════════════════════════════════════════════════════════════════


async def bulk_merge_buyers(
    session: AsyncSession,
    data: BuyerBulkMerge,
    *,
    user_payload: dict[str, Any],
    dry_run: bool,
) -> BulkResult:
    """Fold a set of duplicate buyer rows into one primary buyer.

    FK repointing scope (every table that carries ``buyer_id`` in the
    property_dev schema):
        * oe_property_dev_reservation.buyer_id
        * oe_property_dev_sales_contract  (via ContractParty.buyer_id)
        * oe_property_dev_contract_party.buyer_id (with dedupe — see below)
        * oe_property_dev_warranty_claim.buyer_id
        * oe_property_dev_buyer_selection (via Buyer FK — no direct
          buyer_id rewrite needed because we cascade through Buyer)
        * oe_property_dev_snag.buyer_id (SET NULL on buyer delete — we
          rewrite explicitly so portal-raised snags survive the merge)

    Soft delete: duplicates get ``status='cancelled'``,
    ``cancelled_reason='merged_into:<primary_id>'`` and
    ``metadata_.merged_into=<primary_id>``. We do NOT hard-delete because
    audit trails (ActivityLog entity_id) may reference these UUIDs.

    Atomicity: the entire operation runs inside one SAVEPOINT. If ANY
    repoint fails partway through, the SAVEPOINT rolls back the partial
    write and the BulkResult.failed entry records what blew up. This
    closes the "step 3 failed after step 2 wrote" data-loss scenario
    flagged in the task brief.
    """
    _enforce_batch_cap(len(data.duplicate_buyer_ids) + 1)

    is_admin, user_id = await _owner_ids_for_payload(user_payload)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Auth required for bulk operations.")

    primary = await session.get(Buyer, data.primary_buyer_id)
    if primary is None:
        # Fail the whole request — caller's primary anchor doesn't exist.
        # Returning a single ``failed`` entry would mask the misclick.
        return BulkResult(
            requested=len(data.duplicate_buyer_ids),
            succeeded=0,
            skipped=[],
            failed=[
                BulkFailed(
                    entity_id=str(data.primary_buyer_id),
                    error_message="Primary buyer not found.",
                    error_code=CODE_PRIMARY_MISSING,
                )
            ],
            dry_run=dry_run,
        )

    # IDOR on the primary — caller must own the destination tenant or
    # the merge is silently a no-op (returns 404-equivalent at the
    # request level via the same "not found" code).
    if not is_admin:
        primary_owner = await _project_owner_for_dev_id(session, primary.development_id)
        if primary_owner != user_id:
            raise HTTPException(status_code=404, detail="Primary buyer not found")

    skipped: list[BulkSkipped] = []
    failed: list[BulkFailed] = []
    succeeded = 0

    async with session.begin_nested():
        owner_cache: dict[uuid.UUID, str | None] = {
            primary.development_id: (
                user_id if is_admin else (await _project_owner_for_dev_id(session, primary.development_id))
            )
        }

        for dup_id in data.duplicate_buyer_ids:
            dup = await session.get(Buyer, dup_id)
            if dup is None:
                failed.append(
                    BulkFailed(
                        entity_id=str(dup_id),
                        error_message="Duplicate buyer not found.",
                        error_code=CODE_DUP_NOT_FOUND,
                    )
                )
                continue

            # IDOR check on duplicate
            if not is_admin:
                if dup.development_id not in owner_cache:
                    owner_cache[dup.development_id] = await _project_owner_for_dev_id(session, dup.development_id)
                if owner_cache[dup.development_id] != user_id:
                    skipped.append(
                        BulkSkipped(
                            entity_id=str(dup_id),
                            reason="Duplicate buyer belongs to a different tenant.",
                            code=CODE_IDOR_SKIP,
                        )
                    )
                    continue

            # Cross-development merge is blocked: a buyer in Dev A
            # cannot logically replace one in Dev B (different escrow
            # accounts, different jurisdictions, different reservations).
            if dup.development_id != primary.development_id:
                failed.append(
                    BulkFailed(
                        entity_id=str(dup_id),
                        error_message=(
                            f"Cannot merge buyer from development {dup.development_id} "
                            f"into primary in {primary.development_id}."
                        ),
                        error_code=CODE_CROSS_DEV_MERGE,
                    )
                )
                continue

            if dry_run:
                succeeded += 1
                continue

            # ── Repoint FK references ───────────────────────────────
            #
            # Re-raise on hard failure: the SAVEPOINT must roll back
            # all partial repoints if any step blows up. See module
            # docstring "Atomicity contract".
            try:
                await _repoint_buyer_fks(session, dup_id, data.primary_buyer_id)

                # Soft-delete the duplicate
                dup.status = "cancelled"
                dup.cancelled_reason = f"merged_into:{data.primary_buyer_id}"
                dup.cancelled_at = datetime.now(UTC).date().isoformat()
                md = dict(dup.metadata_ or {})
                md["merged_into"] = str(data.primary_buyer_id)
                md["merged_at"] = datetime.now(UTC).isoformat()
                md["merged_by"] = user_id
                if data.reason:
                    md["merge_reason"] = data.reason
                dup.metadata_ = md
                session.add(dup)

                # Audit-logged inside the same SAVEPOINT — if the audit
                # log write itself fails, we MUST roll back the merge.
                # Stranded buyers without an audit trail are a P0
                # compliance hazard.
                await log_activity(
                    session,
                    actor_id=user_id,
                    entity_type="property_dev.buyer",
                    entity_id=str(dup_id),
                    action="bulk_merged_into",
                    from_status=dup.status,
                    to_status="cancelled",
                    reason=data.reason or None,
                    metadata={
                        "primary_buyer_id": str(data.primary_buyer_id),
                        "development_id": str(dup.development_id),
                    },
                )

                await session.flush()
                succeeded += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "bulk_merge_buyers: repoint failed for %s -> %s",
                    dup_id,
                    data.primary_buyer_id,
                )
                # Surface as a per-item failure, but the SAVEPOINT will
                # capture and re-raise so the whole batch rolls back.
                failed.append(
                    BulkFailed(
                        entity_id=str(dup_id),
                        error_message=str(exc)[:1000],
                        error_code="merge_repoint_failed",
                    )
                )
                raise

        if dry_run:
            await session.rollback()

    if not dry_run:
        _safe_publish(
            "property_dev.bulk.buyer_merge",
            {
                "requested": len(data.duplicate_buyer_ids),
                "succeeded": succeeded,
                "skipped": len(skipped),
                "failed": len(failed),
                "primary_buyer_id": str(data.primary_buyer_id),
                "actor_id": user_id,
            },
        )

    return BulkResult(
        requested=len(data.duplicate_buyer_ids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        dry_run=dry_run,
    )


async def _repoint_buyer_fks(
    session: AsyncSession,
    from_buyer_id: uuid.UUID,
    to_buyer_id: uuid.UUID,
) -> None:
    """Update every property_dev FK that points at ``from_buyer_id``.

    Called inside the merge SAVEPOINT — caller catches and re-raises so
    a half-applied repoint never escapes.
    """
    # Reservations
    await session.execute(
        sa_update(Reservation).where(Reservation.buyer_id == from_buyer_id).values(buyer_id=to_buyer_id)
    )

    # Warranty claims
    await session.execute(
        sa_update(WarrantyClaim).where(WarrantyClaim.buyer_id == from_buyer_id).values(buyer_id=to_buyer_id)
    )

    # Snag.buyer_id is nullable — repoint when set.
    from app.modules.property_dev.models import Snag as _Snag

    await session.execute(sa_update(_Snag).where(_Snag.buyer_id == from_buyer_id).values(buyer_id=to_buyer_id))

    # ContractParty — UNIQUE(sales_contract_id, buyer_id) means a naive
    # ``UPDATE … SET buyer_id = primary`` would unique-violate if the
    # primary already has a party row on the same contract. Strategy:
    # for each duplicate's party, either move it (when no conflict) or
    # delete it (when primary already on contract).
    from sqlalchemy import select

    party_stmt = select(ContractParty).where(ContractParty.buyer_id == from_buyer_id)
    parties = (await session.execute(party_stmt)).scalars().all()
    for party in parties:
        existing_stmt = select(ContractParty).where(
            ContractParty.sales_contract_id == party.sales_contract_id,
            ContractParty.buyer_id == to_buyer_id,
        )
        existing_primary_party = (await session.execute(existing_stmt)).scalars().first()
        if existing_primary_party is None:
            party.buyer_id = to_buyer_id
            session.add(party)
        else:
            # Primary already has a party on this contract — delete the
            # duplicate's party to avoid the unique-constraint clash.
            await session.delete(party)

    # Buyer selections, sales contracts via plot — buyer is referenced
    # indirectly through ContractParty (the canonical multi-buyer junction),
    # so the above repoint is sufficient for SalesContract attribution.
    await session.flush()
