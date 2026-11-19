# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keep the file a bill was imported from and tell whether the bill still matches it.

Format neutral: every native import records its file here (GAEB, BC3, Excel,
any reader of the registry). What the issuer of the file relies on when the
bill comes back is the line identity: item number, unit, quantity and text. A
snapshot of exactly those four per priceable line is stored with the import,
and :func:`compare_lines` reads the current bill against it. Prices are not
part of the snapshot: pricing the bill is what the receiver is asked to do.

The file is filed as a project document (tag ``exchange_source``) so it is
found where every other project file is, and its bytes stay on disk under the
module's uploads directory even when Documents is not installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.exchange_source_models import BOQExchangeSource

logger = logging.getLogger(__name__)

__all__ = [
    "BILL_CHANGED",
    "bill_fingerprint",
    "bill_state",
    "compare_lines",
    "latest_source",
    "record_source",
    "snapshot_lines",
]

#: Error code of an export refused because the bill moved away from its source file.
BILL_CHANGED = "bill_changed_since_import"

_THOUSANDTH = Decimal("0.001")
_ORDINAL_SPLIT = re.compile(r"[.\s/]+")
_MAX_DIFFERENCES = 200


def _ordinal_key(value: object) -> str:
    # "01.0010" and "1.10" are the same item number.
    parts = [p.lstrip("0") or "0" for p in _ORDINAL_SPLIT.split(str(value or "").strip()) if p]
    return ".".join(parts).upper()


def _unit_key(value: object) -> str:
    from app.modules.boq.units import to_gaeb_unit_code

    text = re.sub(r"[\s.]", "", str(value or ""))
    return to_gaeb_unit_code(text).lower() if text else ""


def _quantity_key(value: object) -> str:
    try:
        number = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return str(value or "")
    if not number.is_finite():
        return "0"
    return format(number.quantize(_THOUSANDTH).normalize(), "f")


def _text_key(value: object) -> str:
    return " ".join(str(value or "").split())


def _is_line(position: Any) -> bool:
    from app.modules.boq.service import _is_section, is_empty_position

    return not _is_section(position) and not is_empty_position(position)


def snapshot_lines(positions: Iterable[Any]) -> list[dict[str, str]]:
    """The identity of every priceable line: id, ordinal, unit, quantity, text."""
    out: list[dict[str, str]] = []
    for position in positions:
        if not _is_line(position):
            continue
        out.append(
            {
                "id": str(position.id),
                "ordinal": str(getattr(position, "ordinal", "") or ""),
                "unit": str(getattr(position, "unit", "") or ""),
                "quantity": _quantity_key(getattr(position, "quantity", "0")),
                "text": _text_key(getattr(position, "description", "")),
            }
        )
    return out


def bill_fingerprint(lines: Iterable[dict[str, str]]) -> str:
    """SHA-256 over the normalised lines, independent of order and of position ids."""
    canonical = sorted(
        (_ordinal_key(line.get("ordinal")), _unit_key(line.get("unit")), line.get("quantity", ""), line.get("text", ""))
        for line in lines
    )
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False).encode("utf-8")).hexdigest()


def compare_lines(
    source_lines: Iterable[dict[str, str]],
    positions: Iterable[Any],
    scope_ids: set[str] | None = None,
) -> list[dict[str, str]]:
    """What differs between the imported lines and the bill now.

    Args:
        source_lines: The snapshot stored with the import.
        positions: The bill's positions now.
        scope_ids: Only these position ids are compared (a package over part of
            the bill); ``None`` compares the whole bill. A source line whose
            position is gone counts as removed when its id is in scope or no
            scope is given.

    Returns:
        One entry per difference: ``{"ordinal", "field", "was", "now"}`` where
        ``field`` is ``ordinal``, ``unit``, ``quantity``, ``text``, ``removed``
        or ``added``. Empty when the bill still matches the file.
    """
    current = {line["id"]: line for line in snapshot_lines(positions)}
    source = {str(line.get("id")): line for line in source_lines if isinstance(line, dict)}

    def in_scope(pid: str) -> bool:
        return scope_ids is None or pid in scope_ids

    diffs: list[dict[str, str]] = []
    for pid, was in source.items():
        if not in_scope(pid):
            continue
        now = current.get(pid)
        if now is None:
            diffs.append({"ordinal": was.get("ordinal", ""), "field": "removed", "was": was.get("text", ""), "now": ""})
            continue
        checks = (
            ("ordinal", _ordinal_key),
            ("unit", _unit_key),
            ("quantity", _quantity_key),
            ("text", _text_key),
        )
        for field, key in checks:
            if key(was.get(field, "")) != key(now.get(field, "")):
                diffs.append(
                    {"ordinal": was.get("ordinal", ""), "field": field, "was": was.get(field, ""), "now": now[field]}
                )
    for pid, now in current.items():
        if pid not in source and in_scope(pid):
            diffs.append({"ordinal": now["ordinal"], "field": "added", "was": "", "now": now["text"]})
    return diffs[:_MAX_DIFFERENCES]


async def latest_source(session: AsyncSession, boq_id: uuid.UUID) -> BOQExchangeSource | None:
    """The newest imported file of a bill, or ``None`` when it was never imported."""
    stmt = (
        select(BOQExchangeSource)
        .where(BOQExchangeSource.boq_id == boq_id)
        .order_by(BOQExchangeSource.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def source_summary(source: BOQExchangeSource | None) -> dict[str, Any] | None:
    """The public facts of a source row, for API answers."""
    if source is None:
        return None
    return {
        "id": str(source.id),
        "format_id": source.format_id,
        "variant": source.variant,
        "file_name": source.file_name,
        "file_sha256": source.file_sha256,
        "file_size": source.file_size,
        "bill_sha256": source.bill_sha256,
        "line_count": source.line_count,
        "document_id": str(source.document_id) if source.document_id else None,
        "imported_at": source.created_at.isoformat() if source.created_at else None,
    }


async def bill_state(
    session: AsyncSession,
    boq_id: uuid.UUID,
    positions: Iterable[Any],
    scope_ids: set[str] | None = None,
) -> dict[str, Any]:
    """``{"source", "changed", "differences"}`` of a bill against its imported file."""
    source = await latest_source(session, boq_id)
    if source is None:
        return {"source": None, "changed": False, "differences": []}
    diffs = compare_lines(source.lines or [], positions, scope_ids)
    return {"source": source_summary(source), "changed": bool(diffs), "differences": diffs}


def _variant_of(imported: Any) -> str:
    for row in getattr(imported, "positions", None) or []:
        kind = (getattr(row, "metadata", None) or {}).get("gaeb_da_kind")
        if kind:
            return str(kind)[:20]
    fmt = str(getattr(imported, "source_format", "") or "")
    return fmt.rsplit("_", 1)[-1][:20] if "_" in fmt else ""


async def _file_document(
    session: AsyncSession, project_id: uuid.UUID, name: str, path: str, size: int, user_id: str, format_id: str
) -> uuid.UUID | None:
    try:
        from app.modules.documents.models import Document
    except Exception:  # noqa: BLE001 - Documents is a plugin; the file stays on disk
        return None
    try:
        async with session.begin_nested():
            doc = Document(
                project_id=project_id,
                name=name[:255],
                description="Imported bill, original file",
                category="other",
                file_size=size,
                mime_type="application/xml" if format_id == "gaeb_xml" else "application/octet-stream",
                file_path=path,
                version=1,
                uploaded_by=user_id,
                tags=["exchange_source", format_id],
                metadata_={"source": "boq_import", "format_id": format_id},
            )
            session.add(doc)
            await session.flush()
        return doc.id
    except Exception:  # noqa: BLE001 - the source row still carries the hash and lines
        logger.warning("Filing the imported bill %s in Documents failed", name, exc_info=True)
        return None


async def record_source(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None,
    format_id: str,
    imported: Any,
    content: bytes,
    file_name: str,
    user_id: str | None,
) -> BOQExchangeSource | None:
    """Store the imported file, file it in Documents and snapshot the bill as imported.

    Called after the import's positions are written, so the snapshot is the
    bill as the import left it. Never raises: the positions are committed.
    """
    try:
        from app.core.storage import module_uploads_dir
        from app.modules.boq.repository import PositionRepository

        positions = await PositionRepository(session).list_all_for_boq(boq_id)
        lines = snapshot_lines(positions)
        digest = hashlib.sha256(content).hexdigest()
        safe = re.sub(r"[^\w.\-]+", "_", file_name or "import")[-120:] or "import"
        path = ""
        if project_id is not None:
            target = module_uploads_dir("boq", "exchange_sources", str(project_id))
            full = target / f"{digest[:12]}_{safe}"

            def _write() -> None:
                target.mkdir(parents=True, exist_ok=True)
                full.write_bytes(content)

            try:
                await asyncio.to_thread(_write)
                path = str(full)
            except OSError:
                logger.warning("Keeping the imported bill file %s on disk failed", file_name, exc_info=True)
        document_id = None
        if path and project_id is not None:
            document_id = await _file_document(
                session, project_id, file_name or safe, path, len(content), user_id or "", format_id
            )
        row = BOQExchangeSource(
            boq_id=boq_id,
            project_id=project_id,
            format_id=format_id[:30],
            variant=_variant_of(imported),
            file_name=(file_name or "")[:255],
            file_sha256=digest,
            file_size=len(content),
            file_path=path,
            document_id=document_id,
            bill_sha256=bill_fingerprint(lines),
            line_count=len(lines),
            lines=lines,
            created_by=user_id,
        )
        async with session.begin_nested():
            session.add(row)
            await session.flush()
        await session.commit()
        return row
    except Exception:  # noqa: BLE001 - provenance, never fail an import
        logger.warning("Recording the imported file of BOQ %s failed", boq_id, exc_info=True)
        return None
