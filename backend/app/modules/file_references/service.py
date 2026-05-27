# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File References business logic.

Three responsibilities:

* :func:`validate_iso19650_name` — stateless validator that returns a
  list of failure codes for a single filename.
* :func:`scan_project` — iterate every file in a project across the 8
  kinds, run the validator, and upsert :class:`FileNamingViolation`
  rows.
* CRUD over :class:`FileReference` — the cross-entity link table.

The ISO 19650 parser splits the *base* of the filename (sans
extension) on ``-``. The format is:

    Project-Originator-Volume-Level-Type-Role-Number[-Status][-Revision]

Field constraints (per docstring at top of the original brief):

    Project     2-6 alnum
    Originator  2-6 alnum
    Volume      1-2 alnum   or literal "XX"
    Level       2 alnum     (e.g. 00, 01, XX)
    Type        2-4 alnum
    Role        2-4 alnum
    Number      4 digits
    Status      2 alnum     (S0..S6 in practice — accepted as ``^S[0-6]$``
                            but more permissive in the parser to leave
                            room for project-specific status codes)
    Revision    2-3 alnum   (``P01``, ``P01.01`` collapsed without the
                            dot, ``C01`` etc.)

Violation codes returned (multiple may apply):

    not-iso19650     The filename has no hyphens at all OR fails every
                     structural check below.
    missing-volume   The volume field is absent or empty.
    bad-level        Level isn't a 2-character token or "XX".
    bad-role-code    Role isn't 2-4 alnum chars.
    bad-number       Number isn't exactly 4 digits.
    too-many-parts   Hyphen-split yields more than 9 parts.
    too-few-parts    Hyphen-split yields fewer than 7 parts.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_references.models import (
    FileNamingViolation,
    FileReference,
)
from app.modules.file_references.schemas import (
    ALLOWED_FILE_KINDS,
    FileReferenceCreate,
    FileReferenceResponse,
    Iso19650Parts,
    Iso19650Result,
    NamingViolationResponse,
    ProjectScanResponse,
)

logger = logging.getLogger(__name__)


# ── ISO 19650 validator ───────────────────────────────────────────────


_PROJECT_RE = re.compile(r"^[A-Za-z0-9]{2,6}$")
_ORIGINATOR_RE = re.compile(r"^[A-Za-z0-9]{2,6}$")
_VOLUME_RE = re.compile(r"^([A-Za-z0-9]{1,2}|XX)$")
_LEVEL_RE = re.compile(r"^[A-Za-z0-9]{2}$")
_TYPE_RE = re.compile(r"^[A-Za-z0-9]{2,4}$")
_ROLE_RE = re.compile(r"^[A-Za-z0-9]{2,4}$")
_NUMBER_RE = re.compile(r"^\d{4}$")
_STATUS_RE = re.compile(r"^[A-Za-z0-9]{2,3}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9]{2,8}$")


def _strip_ext(filename: str) -> str:
    """Return the filename without its extension.

    Multi-dot filenames keep everything before the final dot — a single
    extension only. ``A-B-C-D-0001.tar.gz`` → ``A-B-C-D-0001.tar``.
    """
    return Path(filename).stem


def validate_iso19650_name(filename: str) -> Iso19650Result:
    """Validate a filename against the ISO 19650 format.

    Returns every failure that applies — callers can render a single
    banner listing the codes. ``parts`` is best-effort: even when the
    overall name is invalid, individual fields are surfaced so the
    IsoNameBuilder wizard can pre-fill.
    """
    base = _strip_ext(filename).strip()
    parts_split = base.split("-") if base else []
    parts = Iso19650Parts()
    codes: list[str] = []

    if "-" not in base:
        codes.append("not-iso19650")
        return Iso19650Result(
            filename=filename,
            rule_set="iso19650",
            is_valid=False,
            violation_codes=codes,
            parts=parts,
        )

    if len(parts_split) > 9:
        codes.append("too-many-parts")
    if len(parts_split) < 7:
        codes.append("too-few-parts")

    # Best-effort field mapping — index by position; missing fields stay None.
    pad = parts_split + [""] * (9 - len(parts_split)) if len(parts_split) < 9 else parts_split
    project = pad[0] if len(pad) > 0 else ""
    originator = pad[1] if len(pad) > 1 else ""
    volume = pad[2] if len(pad) > 2 else ""
    level = pad[3] if len(pad) > 3 else ""
    typ = pad[4] if len(pad) > 4 else ""
    role = pad[5] if len(pad) > 5 else ""
    number = pad[6] if len(pad) > 6 else ""
    status = pad[7] if len(pad) > 7 else ""
    revision = pad[8] if len(pad) > 8 else ""

    parts = Iso19650Parts(
        project=project or None,
        originator=originator or None,
        volume=volume or None,
        level=level or None,
        type=typ or None,
        role=role or None,
        number=number or None,
        status=status or None,
        revision=revision or None,
    )

    # Field-level checks. The structural codes are intentionally narrow
    # so the banner shows the user the exact thing to fix.
    if not volume:
        codes.append("missing-volume")
    elif not _VOLUME_RE.match(volume):
        # Treated as a structural breakage of the volume field —
        # represented under the same code so a one-bad-volume file
        # doesn't escalate to the catch-all "not-iso19650".
        codes.append("missing-volume")

    if level and not _LEVEL_RE.match(level) or not level:
        codes.append("bad-level")

    if role and not _ROLE_RE.match(role) or not role:
        codes.append("bad-role-code")

    if number and not _NUMBER_RE.match(number) or not number:
        codes.append("bad-number")

    # Structural fields outside the seven we already gate — when both
    # project and originator are also broken we surface the catch-all.
    proj_ok = bool(project and _PROJECT_RE.match(project))
    orig_ok = bool(originator and _ORIGINATOR_RE.match(originator))
    type_ok = bool(typ and _TYPE_RE.match(typ))
    if not proj_ok or not orig_ok or not type_ok:
        # Don't double-up "not-iso19650" if a more specific code already
        # explains the failure. Add it only when no specific code has
        # been raised yet.
        if not codes or (
            "missing-volume" not in codes
            and "bad-level" not in codes
            and "bad-role-code" not in codes
            and "bad-number" not in codes
        ):
            codes.append("not-iso19650")

    # Optional fields: only emit a code if the user *supplied* a status
    # / revision and it fails the regex. Empty optional fields are fine.
    if status and not _STATUS_RE.match(status):
        # Reuse "not-iso19650" — there's no dedicated optional-field
        # code by design, and these usually co-occur with another flag.
        if "not-iso19650" not in codes:
            codes.append("not-iso19650")
    if revision and not _REVISION_RE.match(revision):
        if "not-iso19650" not in codes:
            codes.append("not-iso19650")

    # De-dupe while preserving order — the banner UI uses the first
    # entry as the "headline" code.
    seen: set[str] = set()
    ordered: list[str] = []
    for c in codes:
        if c in seen:
            continue
        seen.add(c)
        ordered.append(c)

    return Iso19650Result(
        filename=filename,
        rule_set="iso19650",
        is_valid=len(ordered) == 0,
        violation_codes=ordered,
        parts=parts,
    )


# ── Project scan ──────────────────────────────────────────────────────


# Per-kind importer for filename extraction. The scan is best-effort:
# any kind whose table or filename column is missing is skipped with a
# warning so the sweep keeps running for the rest.
async def _iter_project_files(session: AsyncSession, project_id: uuid.UUID) -> list[tuple[str, str, str]]:
    """Return ``[(file_kind, file_id, filename), ...]`` for a project.

    The list is deliberately materialised in-memory: a single project
    typically has hundreds of files (rarely thousands). For the
    enterprise tier this can be streamed later.
    """
    out: list[tuple[str, str, str]] = []

    # ── documents ────────────────────────────────────────────────
    try:
        from app.modules.documents.models import Document

        rows = (
            await session.execute(select(Document.id, Document.name).where(Document.project_id == project_id))
        ).all()
        for did, name in rows:
            out.append(("document", str(did), name or ""))
    except Exception:  # pragma: no cover — defensive across module pruning
        logger.exception("Naming scan: documents kind skipped")

    # ── photos ───────────────────────────────────────────────────
    try:
        from app.modules.daily_diary.models import DiaryPhoto  # type: ignore

        if hasattr(DiaryPhoto, "project_id") and hasattr(DiaryPhoto, "filename"):
            rows = (
                await session.execute(
                    select(DiaryPhoto.id, DiaryPhoto.filename).where(DiaryPhoto.project_id == project_id)
                )
            ).all()
            for pid, name in rows:
                out.append(("photo", str(pid), name or ""))
    except Exception:
        logger.debug("Naming scan: photo kind unavailable")

    # ── sheets ───────────────────────────────────────────────────
    try:
        from app.modules.dwg_takeoff.models import DwgSheet  # type: ignore

        if hasattr(DwgSheet, "project_id"):
            name_attr = "filename" if hasattr(DwgSheet, "filename") else ("name" if hasattr(DwgSheet, "name") else None)
            if name_attr is not None:
                rows = (
                    await session.execute(
                        select(
                            DwgSheet.id,
                            getattr(DwgSheet, name_attr),
                        ).where(DwgSheet.project_id == project_id)
                    )
                ).all()
                for sid, name in rows:
                    out.append(("sheet", str(sid), name or ""))
    except Exception:
        logger.debug("Naming scan: sheet kind unavailable")

    # ── bim_models ───────────────────────────────────────────────
    try:
        from app.modules.bim_hub.models import BimModel  # type: ignore

        if hasattr(BimModel, "project_id"):
            name_attr = "filename" if hasattr(BimModel, "filename") else ("name" if hasattr(BimModel, "name") else None)
            if name_attr is not None:
                rows = (
                    await session.execute(
                        select(
                            BimModel.id,
                            getattr(BimModel, name_attr),
                        ).where(BimModel.project_id == project_id)
                    )
                ).all()
                for mid, name in rows:
                    out.append(("bim_model", str(mid), name or ""))
    except Exception:
        logger.debug("Naming scan: bim_model kind unavailable")

    return out


async def scan_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    rule_set: str = "iso19650",
) -> ProjectScanResponse:
    """Run the naming validator across every file in a project.

    Idempotent: rows are upserted in place, and any pre-existing row
    whose file is now compliant is cleared (removed). The response
    counts (added / updated / cleared) make the sweep auditable.
    """
    if rule_set != "iso19650":
        # The "none" rule_set explicitly skips validation but still
        # clears stale rows so the banner disappears project-wide.
        cleared = (
            await session.execute(delete(FileNamingViolation).where(FileNamingViolation.project_id == project_id))
        ).rowcount or 0
        await session.flush()
        return ProjectScanResponse(
            project_id=project_id,
            rule_set=rule_set,
            scanned=0,
            violations_added=0,
            violations_updated=0,
            violations_cleared=int(cleared),
        )

    files = await _iter_project_files(session, project_id)

    # Load existing rows once so we can upsert by (kind, file_id).
    existing_stmt = select(FileNamingViolation).where(
        FileNamingViolation.project_id == project_id,
        FileNamingViolation.rule_set == rule_set,
    )
    existing = list((await session.execute(existing_stmt)).scalars().all())
    existing_by_key: dict[tuple[str, str], FileNamingViolation] = {(r.file_kind, r.file_id): r for r in existing}

    added = 0
    updated = 0
    keep_keys: set[tuple[str, str]] = set()

    for file_kind, file_id, filename in files:
        if not filename:
            continue
        result = validate_iso19650_name(filename)
        key = (file_kind, file_id)
        if result.is_valid:
            # No row needed — if one existed it'll be cleared below.
            continue
        keep_keys.add(key)
        summary = result.violation_codes[0]
        row = existing_by_key.get(key)
        if row is None:
            row = FileNamingViolation(
                project_id=project_id,
                rule_set=rule_set,
                file_kind=file_kind,
                file_id=file_id,
                filename=filename,
                violation_codes=list(result.violation_codes),
                summary=summary,
            )
            session.add(row)
            added += 1
        else:
            row.filename = filename
            row.violation_codes = list(result.violation_codes)
            row.summary = summary
            # Re-scan resets the acknowledged flag iff the violation
            # codes changed (we have new findings the user hasn't seen).
            if sorted(row.violation_codes) != sorted(result.violation_codes):
                row.acknowledged_at = None
                row.acknowledged_by_id = None
            updated += 1

    # Clear rows for files that became valid since the last scan.
    cleared = 0
    for key, row in existing_by_key.items():
        if key not in keep_keys:
            await session.delete(row)
            cleared += 1

    await session.flush()
    return ProjectScanResponse(
        project_id=project_id,
        rule_set=rule_set,
        scanned=len(files),
        violations_added=added,
        violations_updated=updated,
        violations_cleared=cleared,
    )


# ── Naming violation listing / ack ────────────────────────────────────


async def list_violations(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    include_acknowledged: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[NamingViolationResponse], int]:
    """Paginated list of naming violations for a project."""
    base = select(FileNamingViolation).where(FileNamingViolation.project_id == project_id)
    if not include_acknowledged:
        base = base.where(FileNamingViolation.acknowledged_at.is_(None))
    base = base.order_by(FileNamingViolation.created_at.desc())

    total = int((await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one())
    rows = list((await session.execute(base.limit(limit).offset(offset))).scalars().all())
    items = [NamingViolationResponse.model_validate(r) for r in rows]
    return items, total


async def acknowledge_violation(
    session: AsyncSession,
    violation_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> NamingViolationResponse | None:
    """Mark a single violation as acknowledged.

    Returns ``None`` when the row is missing — the router emits 404.
    """
    stmt = select(FileNamingViolation).where(FileNamingViolation.id == violation_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    if row.acknowledged_at is None:
        row.acknowledged_at = datetime.now(UTC)
        row.acknowledged_by_id = actor_id
        await session.flush()
        # After a flush that touched the row, server-side defaults
        # (``updated_at`` onupdate trigger) may be unloaded — refresh
        # so ``model_validate`` doesn't trip greenlet lazy-load.
        await session.refresh(row)
    return NamingViolationResponse.model_validate(row)


# ── References CRUD ──────────────────────────────────────────────────


async def create_reference(
    session: AsyncSession,
    payload: FileReferenceCreate,
    actor_id: uuid.UUID | None,
) -> FileReferenceResponse:
    """Insert a new file → entity link.

    Idempotent w.r.t. the unique key ``(file_kind, file_id, target_type,
    target_id, relation)`` — re-creating the same link returns the
    existing row instead of raising.
    """
    if payload.file_kind not in ALLOWED_FILE_KINDS:
        raise ValueError(f"Unknown file_kind: {payload.file_kind!r}")

    # Idempotent insert: look up first, then create on miss.
    find_stmt = select(FileReference).where(
        FileReference.file_kind == payload.file_kind,
        FileReference.file_id == payload.file_id,
        FileReference.target_type == payload.target_type,
        FileReference.target_id == payload.target_id,
        FileReference.relation == payload.relation,
    )
    existing = (await session.execute(find_stmt)).scalar_one_or_none()
    if existing is not None:
        # Keep the project_id in sync on idempotent re-create (so a
        # re-tag after a project move heals the link).
        if existing.project_id != payload.project_id:
            existing.project_id = payload.project_id
            await session.flush()
        return FileReferenceResponse.model_validate(existing)

    row = FileReference(
        project_id=payload.project_id,
        file_kind=payload.file_kind,
        file_id=payload.file_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        relation=payload.relation,
        target_label=payload.target_label,
        created_by_id=actor_id,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        # Race window with a parallel writer — recover by re-fetching.
        await session.rollback()
        existing = (await session.execute(find_stmt)).scalar_one_or_none()
        if existing is None:
            raise
        return FileReferenceResponse.model_validate(existing)
    return FileReferenceResponse.model_validate(row)


async def delete_reference(
    session: AsyncSession,
    reference_id: uuid.UUID,
) -> bool:
    """Delete a single reference by id. ``False`` when missing."""
    stmt = select(FileReference).where(FileReference.id == reference_id)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def list_references_for_file(
    session: AsyncSession,
    *,
    file_kind: str,
    file_id: str,
) -> tuple[list[FileReferenceResponse], int]:
    """All entities that reference a given file."""
    stmt = (
        select(FileReference)
        .where(
            FileReference.file_kind == file_kind,
            FileReference.file_id == file_id,
        )
        .order_by(FileReference.created_at.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    items = [FileReferenceResponse.model_validate(r) for r in rows]
    return items, len(items)


async def list_files_for_target(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: str,
) -> tuple[list[FileReferenceResponse], int]:
    """All files that reference a given entity."""
    stmt = (
        select(FileReference)
        .where(
            FileReference.target_type == target_type,
            FileReference.target_id == target_id,
        )
        .order_by(FileReference.created_at.desc())
    )
    rows = list((await session.execute(stmt)).scalars().all())
    items = [FileReferenceResponse.model_validate(r) for r in rows]
    return items, len(items)


async def purge_references_for_file(
    session: AsyncSession,
    *,
    file_kind: str,
    file_id: str,
) -> int:
    """Cleanup hook called by the file-manager dispatcher on delete."""
    result = await session.execute(
        delete(FileReference).where(
            FileReference.file_kind == file_kind,
            FileReference.file_id == file_id,
        )
    )
    await session.flush()
    return int(result.rowcount or 0)


# Re-exports
__all__ = [
    "acknowledge_violation",
    "create_reference",
    "delete_reference",
    "list_files_for_target",
    "list_references_for_file",
    "list_violations",
    "purge_references_for_file",
    "scan_project",
    "validate_iso19650_name",
]
