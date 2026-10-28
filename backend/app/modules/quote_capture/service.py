# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture service: ingest, match, review, level and confirm.

Flow: a quote arrives (PDF, scan, Excel, email or pasted text), the document is
stored unaltered, the extraction pipeline reads header, lines and conditions,
and the lines are matched to the scope of the tender package. A person reviews
and edits; the validation rules gate the confirm. Confirming writes the quote
into exactly one place (a bid in the tender comparison, a supplier price list,
or a draft purchase order) and keeps, on both sides, the trail of every value
where the confirmed figure differs from what the machine read.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quote_capture import logic
from app.modules.quote_capture.documents import QuoteDocument, read_document, read_text
from app.modules.quote_capture.extraction import LlmCall, extract
from app.modules.quote_capture.levelling import QuoteInput, RefRow, level
from app.modules.quote_capture.matching import Candidate, match_lines, semantic_scores
from app.modules.quote_capture.models import CapturedQuote
from app.modules.quote_capture.numbers import plain, to_decimal
from app.modules.quote_capture.repository import QuoteRepository
from app.modules.quote_capture.validators import evaluate

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
TEXT_CAP = 200_000
_ALLOWED_EXT = (".pdf", ".xlsx", ".xlsm", ".png", ".jpg", ".jpeg", ".txt", ".eml", ".csv")


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Quote not found")


class QuoteCaptureService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = QuoteRepository(session)

    # ── context ───────────────────────────────────────────────────────────
    async def _project(self, project_id: uuid.UUID) -> Any:
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        return project

    async def _package(self, package_id: uuid.UUID | None) -> Any:
        if package_id is None:
            return None
        from app.modules.tendering.models import TenderPackage

        return await self.session.get(TenderPackage, package_id)

    async def scope_positions(self, package: Any) -> list[Any]:
        """Priced positions of the package's scope (sections and empty rows dropped)."""
        if package is None or package.boq_id is None:
            return []
        from app.modules.boq.service import BOQService
        from app.modules.tendering.service import _positions_in_scope

        try:
            boq = await BOQService(self.session).get_boq_with_positions(package.boq_id)
        except HTTPException:
            return []
        rows = _positions_in_scope(boq.positions, package.metadata_)
        return [p for p in rows if (p.unit or "").strip() and (to_decimal(p.quantity) or 0) > 0]

    def _candidates(self, positions: list[Any]) -> list[Candidate]:
        return [
            Candidate(
                position_id=str(p.id),
                ordinal=p.ordinal or "",
                description=p.description or "",
                unit=p.unit or "",
                quantity=to_decimal(p.quantity) or Decimal("0"),
                unit_rate=to_decimal(p.unit_rate) or Decimal("0"),
            )
            for p in positions
        ]

    async def _llm_call(self, user_id: str | None) -> LlmCall | None:
        """A callable over the user's configured AI provider, or None (rules only)."""
        if not user_id:
            return None
        from app.modules.ai.ai_client import call_ai, resolve_provider_key_model
        from app.modules.ai.repository import AISettingsRepository

        try:
            settings = await AISettingsRepository(self.session).get_by_user_id(uuid.UUID(str(user_id)))
            provider, api_key, model = resolve_provider_key_model(settings)
        except (ValueError, TypeError):
            return None

        async def _call(system: str, prompt: str) -> str | None:
            raw, _tokens = await call_ai(
                provider=provider, api_key=api_key, system=system, prompt=prompt, model=model, max_tokens=8192
            )
            return raw

        return _call

    # ── ingest ────────────────────────────────────────────────────────────
    async def upload(
        self,
        *,
        project_id: uuid.UUID,
        package_id: uuid.UUID | None,
        file: UploadFile,
        user_id: str | None,
        locale: str | None = None,
    ) -> CapturedQuote:
        filename = (file.filename or "quote").strip()[:255]
        if not filename.lower().endswith(_ALLOWED_EXT):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported quote file type")
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if not payload:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The uploaded file is empty.")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The quote file is too large.")
        quote_id = uuid.uuid4()
        key = f"quote-capture/{project_id}/{quote_id}/{filename}"
        from app.core.storage import get_storage_backend

        await get_storage_backend().put(key, payload)
        document = read_document(payload, filename)
        return await self._ingest(
            quote_id=quote_id,
            project_id=project_id,
            package_id=package_id,
            document=document,
            filename=filename,
            storage_key=key,
            mime=file.content_type,
            user_id=user_id,
            locale=locale,
        )

    async def create_from_text(
        self,
        *,
        project_id: uuid.UUID,
        package_id: uuid.UUID | None,
        text: str,
        filename: str,
        user_id: str | None,
        locale: str | None = None,
        llm: bool = True,
        engine_label: str | None = None,
    ) -> CapturedQuote:
        document = read_text(text, kind="email")
        return await self._ingest(
            quote_id=uuid.uuid4(),
            project_id=project_id,
            package_id=package_id,
            document=document,
            filename=filename,
            storage_key=None,
            mime="text/plain",
            user_id=user_id,
            locale=locale,
            use_llm=llm,
            engine_label=engine_label,
        )

    async def _ingest(
        self,
        *,
        quote_id: uuid.UUID,
        project_id: uuid.UUID,
        package_id: uuid.UUID | None,
        document: QuoteDocument,
        filename: str,
        storage_key: str | None,
        mime: str | None,
        user_id: str | None,
        locale: str | None,
        use_llm: bool = True,
        engine_label: str | None = None,
    ) -> CapturedQuote:
        project = await self._project(project_id)
        package = await self._package(package_id)
        if package is not None and package.project_id != project_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Package belongs to another project")
        loc = locale or getattr(project, "locale", None)
        llm = await self._llm_call(user_id) if use_llm else None
        engine, result = await extract(document, locale=loc, llm_call=llm)
        header = result["header"]
        row = CapturedQuote(
            id=quote_id,
            project_id=project_id,
            package_id=package_id,
            boq_id=getattr(package, "boq_id", None),
            supplier_name=str(logic.header_value(header, "supplier") or "")[:255],
            status="draft",
            source_kind=document.kind,
            original_filename=filename,
            storage_key=storage_key,
            mime_type=mime,
            extraction_engine=engine_label or engine,
            locale=(loc or "")[:10],
            currency=str(logic.header_value(header, "currency") or getattr(project, "currency", "") or "")[:10],
            quote_total=str(logic.header_value(header, "quote_total") or "0"),
            page_count=len(document.pages),
            header=header,
            lines=result["lines"],
            notes=result["notes"],
            document={
                "engine": document.engine,
                "pages": document.pages,
                "lines": [{"text": ln.text, "anchor": ln.anchor} for ln in document.lines],
            },
            document_text=document.text[:TEXT_CAP] or None,
            created_by=str(user_id) if user_id else None,
        )
        await self._match(row, package)
        await self.repo.add(row)
        await self._log(row, user_id, "quote_capture.captured", engine=row.extraction_engine, lines=len(row.lines))
        return row

    async def _match(self, row: CapturedQuote, package: Any) -> None:
        positions = await self.scope_positions(package)
        if not positions:
            return
        cands = self._candidates(positions)
        semantic = await semantic_scores(row.lines, cands)
        suggestions = match_lines(row.lines, cands, locale=row.locale, semantic=semantic)
        lines = []
        for line, sug in zip(row.lines, suggestions, strict=False):
            current = line.get("match") or {}
            if current.get("status") == "confirmed":
                lines.append(line)
                continue
            if sug is not None:
                sug["suggested_position_id"] = sug.get("position_id")
            lines.append({**line, "match": sug})
        row.lines = lines

    # ── read ──────────────────────────────────────────────────────────────
    async def get(self, quote_id: uuid.UUID) -> CapturedQuote:
        row = await self.repo.get(quote_id)
        if row is None:
            raise _not_found()
        return row

    async def list(
        self, project_id: uuid.UUID, package_id: uuid.UUID | None = None, offset: int = 0, limit: int = 50
    ) -> tuple[list[CapturedQuote], int]:
        return await self.repo.page(project_id, package_id=package_id, offset=offset, limit=limit)

    async def snapshot(self, row: CapturedQuote) -> dict[str, Any]:
        project = await self._project(row.project_id)
        snap = logic.validation_snapshot(
            header=row.header,
            lines=row.lines,
            notes=row.notes,
            project_currency=getattr(project, "currency", ""),
            today=date.today().isoformat(),
        )
        snap["net_total"] = logic.tax_view(row.header, getattr(project, "country_code", None)).get("net")
        return snap

    async def findings(self, row: CapturedQuote) -> list[Any]:
        return await evaluate(await self.snapshot(row), target_id=str(row.id))

    async def tax(self, row: CapturedQuote) -> dict[str, Any]:
        project = await self._project(row.project_id)
        return logic.tax_view(row.header, getattr(project, "country_code", None))

    # ── review ────────────────────────────────────────────────────────────
    def _ensure_open(self, row: CapturedQuote) -> None:
        if row.status == "confirmed":
            raise HTTPException(status.HTTP_409_CONFLICT, "The quote is confirmed and can no longer be edited")

    async def update(self, row: CapturedQuote, data: Any, user_id: str | None) -> CapturedQuote:
        self._ensure_open(row)
        header = dict(row.header)
        for key, change in data.header.items():
            current = dict(header.get(key) or {"machine_value": None, "confidence": 0.0, "anchor": None})
            current["value"] = change.value
            current["reviewed_by"] = user_id
            current["source"] = (
                "human" if str(change.value) != str(current.get("machine_value")) else current.get("source")
            )
            header[key] = current
        row.header = header
        row.supplier_name = str(logic.header_value(header, "supplier") or row.supplier_name)[:255]
        row.currency = str(logic.header_value(header, "currency") or row.currency)[:10]
        row.quote_total = str(logic.header_value(header, "quote_total") or row.quote_total)
        if data.acknowledge_notes:
            wanted = set(data.acknowledge_notes)
            row.notes = [
                {**n, "acknowledged": True, "acknowledged_by": user_id, "acknowledged_at": logic.now_iso()}
                if n.get("id") in wanted
                else n
                for n in row.notes
            ]
        if data.package_id is not None and data.package_id != row.package_id:
            package = await self._package(data.package_id)
            if package is None or package.project_id != row.project_id:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Package not in this project")
            row.package_id, row.boq_id = package.id, package.boq_id
            await self._match(row, package)
        if data.status is not None:
            row.status = data.status
        await self.repo.save(row, "header", "notes", "lines")
        return row

    async def update_line(self, row: CapturedQuote, line_id: str, data: Any, user_id: str | None) -> CapturedQuote:
        self._ensure_open(row)
        changes = data.model_dump(exclude_unset=True)
        lines = []
        found = False
        for line in row.lines:
            if line.get("id") == line_id:
                found = True
                line = logic.apply_line_edit(line, changes, user_id)
                if changes.get("ignored") is not None:
                    line["ignored"] = bool(changes["ignored"])
            lines.append(line)
        if not found:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Line not found")
        row.lines = lines
        if row.status == "draft":
            row.status = "in_review"
        await self.repo.save(row, "lines")
        return row

    async def rematch(self, row: CapturedQuote) -> CapturedQuote:
        self._ensure_open(row)
        await self._match(row, await self._package(row.package_id))
        await self.repo.save(row, "lines")
        return row

    # ── confirm ───────────────────────────────────────────────────────────
    async def confirm(self, row: CapturedQuote, target: str, user_id: str | None, *, accept_warnings: bool) -> dict:
        self._ensure_open(row)
        findings = await self.findings(row)
        errors = [f for f in findings if str(f.severity) in {"error", "Severity.ERROR"}]
        warnings = [f for f in findings if f not in errors]
        if errors or (warnings and not accept_warnings):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "message": "The quote has open findings",
                    "findings": [
                        {"rule_id": f.rule_id, "severity": str(f.severity), "message": f.message, "ref": f.element_ref}
                        for f in findings
                    ],
                },
            )
        project = await self._project(row.project_id)
        factor = logic.net_factor(row.header, getattr(project, "country_code", None))
        lines = [ln for ln in row.lines if not ln.get("ignored")]
        audit = logic.audit_trail(row.header, lines)
        provenance = {
            "quote_id": str(row.id),
            "engine": row.extraction_engine,
            "confirmed_by": user_id,
            "confirmed_at": logic.now_iso(),
            "audit": audit,
        }
        if target == "bid":
            target_id = await self._to_bid(row, lines, factor, provenance)
        elif target == "price_list":
            target_id = await self._to_price_list(row, lines, factor, provenance)
        elif target == "po_draft":
            target_id = await self._to_po(row, lines, factor, provenance, user_id)
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown target")
        row.status = "confirmed"
        row.confirmation = {**provenance, "target": target, "target_id": target_id}
        await self.repo.save(row, "confirmation")
        await self._log(row, user_id, f"quote_capture.confirmed.{target}", target_id=target_id, changes=len(audit))
        return {"quote_id": row.id, "target": target, "target_id": target_id, "audit": audit}

    @staticmethod
    def _net(value: Any, factor: Decimal) -> Decimal:
        return (to_decimal(value) or Decimal("0")) * factor

    async def _to_bid(self, row: CapturedQuote, lines: list[dict], factor: Decimal, prov: dict) -> str:
        if row.package_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Link the quote to a tender package first")
        from app.modules.tendering.schemas import BidCreate, BidLineItem
        from app.modules.tendering.service import TenderingService

        items = []
        total = Decimal("0")
        for ln in lines:
            rate = self._net(ln.get("unit_rate"), factor)
            amount = self._net(ln.get("total"), factor)
            total += amount
            match = ln.get("match") or {}
            items.append(
                BidLineItem(
                    position_id=match.get("position_id") if match.get("status") in {"suggested", "confirmed"} else None,
                    description=str(ln.get("description") or "")[:1000],
                    unit=str(ln.get("unit") or ""),
                    quantity=float(to_decimal(ln.get("quantity")) or 0),
                    unit_rate=rate.quantize(Decimal("0.0001")),
                    total=float(amount.quantize(Decimal("0.01"))),
                )
            )
        bid = await TenderingService(self.session).create_bid(
            row.package_id,
            BidCreate(
                company_name=row.supplier_name or "Supplier",
                total_amount=plain(total.quantize(Decimal("0.01"))),
                currency=row.currency or "EUR",
                submitted_at=str(logic.header_value(row.header, "quote_date") or "")[:10] or None,
                status="submitted",
                notes="; ".join(n["text"] for n in row.notes if n.get("kind") == "exclusion")[:4000],
                line_items=items,
                metadata={"quote_capture": prov, "notes": row.notes},
            ),
        )
        return str(bid.id)

    async def _to_price_list(self, row: CapturedQuote, lines: list[dict], factor: Decimal, prov: dict) -> str:
        from sqlalchemy import func, select

        from app.modules.supplier_catalogs.models import CatalogEntry, CatalogItem, PriceList, Vendor

        name = row.supplier_name or "Supplier"
        vendor = (
            await self.session.execute(select(Vendor).where(func.lower(Vendor.name) == name.lower()).limit(1))
        ).scalar_one_or_none()
        if vendor is None:
            vendor = Vendor(code=f"QC-{uuid.uuid4().hex[:8].upper()}", name=name[:255], currency=row.currency or "EUR")
            self.session.add(vendor)
            await self.session.flush()
        plist = PriceList(
            vendor_id=vendor.id,
            name=f"{name} {logic.header_value(row.header, 'quote_date') or ''}".strip()[:255],
            valid_from=str(logic.header_value(row.header, "quote_date") or "")[:20] or None,
            valid_to=str(logic.header_value(row.header, "valid_until") or "")[:20] or None,
            currency=row.currency or vendor.currency,
            status="draft",
            uploaded_by=prov.get("confirmed_by"),
        )
        self.session.add(plist)
        await self.session.flush()
        for idx, ln in enumerate(lines, start=1):
            item = CatalogItem(
                sku=f"QC-{row.id.hex[:8].upper()}-{idx:03d}",
                name=str(ln.get("description") or "")[:255],
                description=str(ln.get("description") or ""),
                unit_of_measure=str(ln.get("unit") or "pcs")[:20],
                spec_json={"quote_capture": {"quote_id": str(row.id), "line_id": ln.get("id")}},
            )
            self.session.add(item)
            await self.session.flush()
            self.session.add(
                CatalogEntry(
                    price_list_id=plist.id,
                    catalog_item_id=item.id,
                    unit_price=self._net(ln.get("unit_rate"), factor).quantize(Decimal("0.0001")),
                    notes=f"Quote {row.original_filename} line {ln.get('id')}",
                )
            )
        await self.session.flush()
        return str(plist.id)

    async def _to_po(
        self, row: CapturedQuote, lines: list[dict], factor: Decimal, prov: dict, user_id: str | None
    ) -> str:
        from app.modules.procurement.schemas import POCreate, POItemCreate
        from app.modules.procurement.service import ProcurementService

        items = []
        for ln in lines:
            qty = to_decimal(ln.get("quantity")) or Decimal("0")
            rate = self._net(ln.get("unit_rate"), factor)
            match = ln.get("match") or {}
            items.append(
                POItemCreate(
                    description=str(ln.get("description") or "Item")[:500],
                    quantity=plain(qty),
                    unit=str(ln.get("unit") or "")[:20] or None,
                    unit_rate=plain(rate),
                    amount=plain((qty * rate).quantize(Decimal("0.01"))),
                    boq_position_id=match.get("position_id") if match.get("status") == "confirmed" else None,
                )
            )
        po = await ProcurementService(self.session).create_po(
            POCreate(
                project_id=row.project_id,
                currency_code=row.currency or "",
                status="draft",
                payment_terms=str(logic.header_value(row.header, "payment_terms") or "")[:100] or None,
                notes=f"From quote of {row.supplier_name}",
                items=items,
                metadata={"quote_capture": prov},
            ),
            user_id,
        )
        return str(po.id)

    # ── levelling ─────────────────────────────────────────────────────────
    async def levelling(self, package_id: uuid.UUID) -> dict[str, Any]:
        package = await self._package(package_id)
        if package is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not found")
        project = await self._project(package.project_id)
        currency = (getattr(project, "currency", "") or "").upper()
        country = getattr(project, "country_code", None)
        positions = await self.scope_positions(package)
        list_rates = await self._price_list_rates([p.description or "" for p in positions], currency)
        rows = [
            RefRow(
                position_id=str(p.id),
                ordinal=p.ordinal or "",
                description=p.description or "",
                unit=p.unit or "",
                quantity=to_decimal(p.quantity) or Decimal("0"),
                boq_rate=to_decimal(p.unit_rate) or Decimal("0"),
                price_list_rate=list_rates.get((p.description or "").strip().casefold()),
            )
            for p in positions
        ]
        quotes: list[QuoteInput] = []
        excluded: list[str] = []
        for q in await self.repo.list_for_package(package_id):
            if currency and q.currency and q.currency.upper() != currency:
                excluded.append(str(q.id))
                continue
            factor = logic.net_factor(q.header, country)
            net_lines = [
                {
                    **ln,
                    "unit_rate": str(self._net(ln.get("unit_rate"), factor)),
                    "total": str(self._net(ln.get("total"), factor)),
                }
                for ln in q.lines
                if not ln.get("ignored")
            ]
            quotes.append(
                QuoteInput(
                    quote_id=str(q.id),
                    supplier=q.supplier_name,
                    currency=q.currency,
                    lines=net_lines,
                    exclusions=sum(1 for n in q.notes if n.get("kind") == "exclusion"),
                )
            )
        result = level(rows, quotes)
        return {"package_id": package_id, "currency": currency, "excluded_off_currency": excluded, **result}

    async def _price_list_rates(self, descriptions: list[str], currency: str) -> dict[str, Decimal]:
        """Lowest active or draft price-list rate per item name, in the project currency."""
        keys = {d.strip().casefold() for d in descriptions if d.strip()}
        if not keys:
            return {}
        from sqlalchemy import func, select

        from app.modules.supplier_catalogs.models import CatalogEntry, CatalogItem, PriceList

        stmt = (
            select(func.lower(CatalogItem.name), func.min(CatalogEntry.unit_price))
            .join(CatalogEntry, CatalogEntry.catalog_item_id == CatalogItem.id)
            .join(PriceList, PriceList.id == CatalogEntry.price_list_id)
            .where(func.lower(CatalogItem.name).in_(keys), PriceList.status.in_(("active", "draft")))
            .group_by(func.lower(CatalogItem.name))
        )
        if currency:
            stmt = stmt.where(PriceList.currency == currency)
        try:
            rows = (await self.session.execute(stmt)).all()
        except Exception:  # noqa: BLE001 - the plug falls back to the BOQ rate
            logger.debug("price list lookup failed", exc_info=True)
            return {}
        return {name: Decimal(str(rate)) for name, rate in rows if rate is not None}

    # ── document ──────────────────────────────────────────────────────────
    async def page_png(self, row: CapturedQuote, page: int) -> bytes:
        if not row.storage_key or row.source_kind not in {"pdf", "scan"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No page image for this quote")
        from app.core import pdf_reader
        from app.core.storage import get_storage_backend

        payload = await get_storage_backend().get(row.storage_key)
        if payload[:5] != b"%PDF-":
            return payload
        with pdf_reader.open_pdf(payload) as doc:
            if page < 1 or page > doc.page_count:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
            return doc[page - 1].render(dpi=110).png()

    async def _log(self, row: CapturedQuote, user_id: str | None, action: str, **meta: Any) -> None:
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=user_id,
                entity_type="quote_capture.quote",
                entity_id=row.id,
                action=action,
                metadata=meta,
                module="oe_quote_capture",
            )
        except Exception:  # noqa: BLE001 - the audit log must not break a capture
            logger.debug("quote capture activity log failed", exc_info=True)

    async def delete(self, row: CapturedQuote) -> None:
        self._ensure_open(row)
        await self.repo.delete(row)
