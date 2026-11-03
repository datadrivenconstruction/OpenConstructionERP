"""Spec book to proposed submittal register: import job, review, idempotent confirm.

Nothing here writes to the live register until :meth:`SpecImportService.confirm`, and
that only for the proposals a person ticked.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.modules.submittals import spec_parser
from app.modules.submittals.models import SpecImport, SpecProposal, Submittal
from app.modules.submittals.schemas import SUBMITTAL_TYPES, SubmittalCreate
from app.modules.submittals.service import SubmittalService

logger = logging.getLogger(__name__)

#: Proposals below this are hidden by default.
HIDE_BELOW = 0.5
#: A book bigger than this is not read whole into memory for OCR.
MAX_OCR_BYTES = 150 * 1024 * 1024

_NORM = re.compile(r"[^0-9a-zÀ-￿]+")


def norm_title(title: str) -> str:
    return _NORM.sub(" ", (title or "").lower()).strip()


def _key(section: str | None, kind: str, title: str) -> tuple[str, str, str]:
    return ((section or "").strip(), kind, norm_title(title))


def parse_file(path: Path, use_ocr: bool, progress: dict[str, int]) -> tuple[spec_parser.SpecParser, bool]:
    """Parse a spec PDF page by page (blocking; run in a thread). Returns (parser, ocr_used)."""
    import pdfplumber  # noqa: PLC0415

    with pdfplumber.open(str(path)) as pdf:
        progress["total"] = len(pdf.pages)

    def pages() -> Any:
        for number, text in spec_parser.iter_pdf_pages(path):
            progress["done"] = number
            yield number, text

    parser = spec_parser.parse_pages(pages())
    if parser.sections or not use_ocr:
        return parser, False
    if path.stat().st_size > MAX_OCR_BYTES:
        return parser, False
    from app.modules.file_search.extractors import extract_text  # noqa: PLC0415

    result = extract_text(path.read_bytes(), "application/pdf")
    text_pages = ((i + 1, t) for i, t in enumerate(result.text.split("\f")))
    return spec_parser.parse_pages(text_pages), True


class SpecImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, import_id: uuid.UUID) -> SpecImport:
        row = await self.session.get(SpecImport, import_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spec import not found")
        return row

    async def create(self, project_id: uuid.UUID, document_id: uuid.UUID, user_id: str | None) -> SpecImport:
        from app.modules.documents.models import Document  # noqa: PLC0415

        doc = await self.session.get(Document, document_id)
        if doc is None or doc.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found in this project")
        row = SpecImport(
            project_id=project_id,
            document_id=document_id,
            status="uploaded",
            parser_version=spec_parser.PARSER_VERSION,
            created_by=user_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def document_path(self, row: SpecImport) -> Path | None:
        from app.core.storage import is_within_safe_root  # noqa: PLC0415
        from app.modules.documents.models import Document  # noqa: PLC0415
        from app.modules.documents.service import UPLOAD_BASE  # noqa: PLC0415

        doc = await self.session.get(Document, row.document_id)
        if doc is None or not doc.file_path:
            return None
        base = Path(UPLOAD_BASE).resolve()
        raw = Path(doc.file_path)
        path = (raw if raw.is_absolute() else base / raw).resolve()
        if not path.is_file() or path.is_symlink() or not is_within_safe_root(path, extra_roots=[base]):
            return None
        return path

    async def run(self, import_id: uuid.UUID, use_ocr: bool = False) -> None:
        """Parse the book and store proposals. Runs in the background with a session of its own."""
        from app.database import async_session_factory  # noqa: PLC0415

        async with async_session_factory() as session:
            svc = SpecImportService(session)
            row = await svc.get(import_id)
            try:
                path = await svc.document_path(row)
                if path is None:
                    row.status, row.error_code = "failed", "file_missing"
                    await session.commit()
                    return
                progress = {"total": 0, "done": 0}
                task = asyncio.create_task(asyncio.to_thread(parse_file, path, use_ocr, progress))
                while not task.done():
                    await asyncio.wait({task}, timeout=1.0)
                    row.pages_total, row.pages_done = progress["total"], progress["done"]
                    await session.commit()
                parser, ocr_used = task.result()
                row.pages_total, row.pages_done = progress["total"], max(progress["done"], progress["total"])
                await svc.store(row, parser, ocr_used)
                await session.commit()
            except Exception:
                logger.exception("Spec import %s failed", import_id)
                await session.rollback()
                row = await svc.get(import_id)
                row.status, row.error_code = "failed", "parse_failed"
                await session.commit()

    async def store(self, row: SpecImport, parser: spec_parser.SpecParser, ocr_used: bool) -> None:
        row.section_count = len(parser.sections)
        row.status = "parsed"
        row.metadata_ = {**(row.metadata_ or {}), "ocr_used": ocr_used}
        report = await validation_engine.validate(
            data={"section_count": row.section_count, "pages_done": row.pages_done},
            rule_sets=["spec_import"],
            target_type="spec_import",
            target_id=str(row.id),
            project_id=str(row.project_id),
            metadata={"locale": get_locale(), "operation": "read"},
        )
        row.error_code = "no_sections_found" if any(not r.passed for r in report.results) else None
        for p in parser.proposals:
            self.session.add(
                SpecProposal(
                    import_id=row.id,
                    project_id=row.project_id,
                    spec_section=p.spec_section,
                    section_title=p.section_title,
                    kind=p.kind,
                    submittal_type=p.submittal_type,
                    title=p.title,
                    source_page=p.source_page,
                    source_excerpt=p.source_excerpt,
                    confidence=p.confidence,
                )
            )
        await self.session.flush()

    async def _existing_keys(self, project_id: uuid.UUID) -> set[tuple[str, str, str]]:
        rows = (
            await self.session.execute(
                select(Submittal.spec_section, Submittal.submittal_type, Submittal.title).where(
                    Submittal.project_id == project_id
                )
            )
        ).all()
        return {_key(s, t, title) for s, t, title in rows}

    async def proposals(self, import_id: uuid.UUID, *, include_hidden: bool = False) -> dict[str, Any]:
        imp = await self.get(import_id)
        stmt = select(SpecProposal).where(SpecProposal.import_id == import_id)
        if not include_hidden:
            stmt = stmt.where(SpecProposal.confidence >= HIDE_BELOW)
        rows = list(
            (await self.session.execute(stmt.order_by(SpecProposal.spec_section, SpecProposal.source_page))).scalars()
        )
        existing = await self._existing_keys(imp.project_id)
        items = [
            {
                "id": str(r.id),
                "spec_section": r.spec_section,
                "section_title": r.section_title,
                "kind": r.kind,
                "submittal_type": r.submittal_type,
                "title": r.title,
                "source_page": r.source_page,
                "source_excerpt": r.source_excerpt,
                "confidence": r.confidence,
                "decision": r.decision,
                "submittal_id": str(r.submittal_id) if r.submittal_id else None,
                "duplicate": r.submittal_id is None and _key(r.spec_section, r.submittal_type, r.title) in existing,
            }
            for r in rows
        ]
        return {
            "import": {
                "id": str(imp.id),
                "document_id": str(imp.document_id),
                "status": imp.status,
                "section_count": imp.section_count,
                "pages_total": imp.pages_total,
                "pages_done": imp.pages_done,
                "error_code": imp.error_code,
            },
            "items": items,
            "warnings": await self._section_warnings(items, imp),
        }

    async def _section_warnings(self, items: list[dict[str, Any]], imp: SpecImport) -> list[dict[str, Any]]:
        kinds: dict[str, set[str]] = {}
        for it in items:
            kinds.setdefault(it["spec_section"], set()).add(it["kind"])
        out: list[dict[str, Any]] = []
        for section, have in kinds.items():
            report = await validation_engine.validate(
                data={"spec_section": section, "kinds": sorted(have)},
                rule_sets=["spec_section"],
                target_type="spec_section",
                target_id=section,
                project_id=str(imp.project_id),
                metadata={"locale": get_locale(), "operation": "read"},
            )
            out.extend(
                {"rule_id": r.rule_id, "spec_section": section, "message": r.message, "suggestion": r.suggestion}
                for r in report.results
                if not r.passed
            )
        return out

    async def confirm(
        self,
        import_id: uuid.UUID,
        accept_ids: list[uuid.UUID],
        edits: dict[str, dict[str, Any]],
        reject_ids: list[uuid.UUID],
        user_id: str | None,
    ) -> dict[str, Any]:
        """Create draft submittals for the ticked proposals. Safe to repeat: a created proposal is skipped."""
        imp = await self.get(import_id)
        rows = {
            r.id: r
            for r in (
                await self.session.execute(select(SpecProposal).where(SpecProposal.import_id == import_id))
            ).scalars()
        }
        for rid in reject_ids:
            rej = rows.get(rid)
            if rej is not None and rej.submittal_id is None:
                rej.decision = "rejected"
        existing = await self._existing_keys(imp.project_id)
        created: list[dict[str, str]] = []
        skipped_existing: list[str] = []
        skipped_duplicates: list[str] = []
        warnings: list[dict[str, str]] = []
        svc = SubmittalService(self.session)
        for rid in accept_ids:
            prop = rows.get(rid)
            if prop is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=f"Proposal {rid} is not in this import"
                )
            if prop.submittal_id is not None:
                skipped_existing.append(str(rid))
                continue
            edit = edits.get(str(rid)) or {}
            title = str(edit.get("title") or prop.title).strip()[:500]
            section = str(edit.get("spec_section") or prop.spec_section).strip()[:100]
            stype = str(edit.get("submittal_type") or prop.submittal_type)
            if stype not in SUBMITTAL_TYPES:
                raise HTTPException(status_code=422, detail=f"Unknown submittal type '{stype}'")
            key = _key(section, stype, title)
            fmt = await validation_engine.validate(
                data={"spec_section": section, "title": title, "duplicate": key in existing},
                rule_sets=["spec_submittal_item"],
                target_type="spec_proposal",
                target_id=str(rid),
                project_id=str(imp.project_id),
                metadata={"locale": get_locale(), "operation": "read"},
            )
            warnings.extend(
                {"proposal_id": str(rid), "rule_id": r.rule_id, "message": r.message}
                for r in fmt.results
                if not r.passed
            )
            if key in existing:
                skipped_duplicates.append(str(rid))
                continue
            sub = await svc.create_submittal(
                SubmittalCreate(
                    project_id=imp.project_id,
                    title=title,
                    spec_section=section,
                    submittal_type=stype,
                    status="draft",
                    metadata={"spec_import_id": str(imp.id), "source_page": prop.source_page},
                ),
                user_id=user_id,
            )
            existing.add(key)
            prop.submittal_id = sub.id
            prop.decision = "edited" if edit else "accepted"
            if edit:
                prop.title, prop.spec_section, prop.submittal_type = title, section, stype
            created.append({"proposal_id": str(rid), "submittal_id": str(sub.id), "number": sub.submittal_number})
        pending = [r for r in rows.values() if r.decision == "pending" and r.confidence >= HIDE_BELOW]
        if not pending:
            imp.status = "confirmed"
        await self.session.flush()
        return {
            "created": created,
            "already_created": skipped_existing,
            "skipped_duplicates": skipped_duplicates,
            "warnings": warnings,
            "status": imp.status,
        }
