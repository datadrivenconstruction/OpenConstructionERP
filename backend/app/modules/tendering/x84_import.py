# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read a priced GAEB X84 bid return into a tender package's bid comparison.

A bidder that prices the bill in its own estimating software sends back an
X84 file. The file is parsed by the regular GAEB importer and every priced
line is matched to the package's bill by its ordinal (OZ). A line is only
taken when it names a position of the package, keeps its unit and keeps its
quantity: a bidder may price the bill, not change it. Anything else is
reported per line, and an import with a blocking issue is refused, so the
comparison never reads a bid for a different bill.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tendering.schemas import BidCreate, BidLineItem, X84ImportPreview, X84LineCheck

#: Upper bound for one uploaded X84 file.
MAX_X84_BYTES = 20 * 1024 * 1024

#: Line issues that stop the import; ``unpriced`` only leaves the line out.
BLOCKING_LINE_ISSUES = frozenset({"unknown_position", "unit_mismatch", "quantity_changed", "duplicate_position"})
#: File issues that stop the import.
BLOCKING_FILE_ISSUES = frozenset({"not_x84", "currency_mismatch", "no_bill", "nothing_priced"})

_ORDINAL_SPLIT = re.compile(r"[.\s/]+")
_THOUSANDTH = Decimal("0.001")


def normalise_ordinal(value: object) -> str:
    """``"01.0010"`` and ``"1.10"`` name the same OZ: compare parts without leading zeros."""
    parts = [p.lstrip("0") or "0" for p in _ORDINAL_SPLIT.split(str(value or "").strip()) if p]
    return ".".join(parts).upper()


def _unit_key(value: object) -> str:
    return re.sub(r"[\s.]", "", str(value or "")).lower()


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _quantity_text(value: Decimal | None) -> str:
    return "" if value is None else format(value.normalize(), "f")


def check_lines(
    imported_positions: list[Any],
    priceable: dict[str, Any],
) -> tuple[list[X84LineCheck], dict[str, Decimal], list[str]]:
    """Match the file's lines to the bill.

    Returns:
        ``(lines, prices, missing)``: one check per file line, the accepted unit
        price per package position id, and the ordinals of package positions
        the file does not name.
    """
    by_ordinal: dict[str, Any] = {}
    for position in priceable.values():
        meta = getattr(position, "metadata_", None)
        gaeb_ordinal = meta.get("gaeb_ordinal") if isinstance(meta, dict) else None
        for raw in (getattr(position, "ordinal", ""), gaeb_ordinal):
            key = normalise_ordinal(raw)
            if key and key not in by_ordinal:
                by_ordinal[key] = position

    checks: list[X84LineCheck] = []
    prices: dict[str, Decimal] = {}
    seen: set[str] = set()
    for row in imported_positions:
        if getattr(row, "is_section", False):
            continue
        meta = getattr(row, "metadata", None) or {}
        ordinal = str(meta.get("gaeb_ordinal") or getattr(row, "ordinal", "") or "")
        rate = _decimal(meta.get("gaeb_up")) if meta.get("gaeb_up") else _decimal(repr(getattr(row, "unit_rate", 0)))
        file_qty = _decimal(repr(getattr(row, "quantity", 0)))
        check = X84LineCheck(
            ordinal=ordinal,
            description=str(getattr(row, "description", "") or ""),
            unit=str(meta.get("gaeb_unit_original") or getattr(row, "unit", "") or ""),
            quantity=_quantity_text(file_qty),
            unit_rate=format(rate, "f") if rate is not None else None,
        )
        position = by_ordinal.get(normalise_ordinal(ordinal))
        if position is None:
            check.issues.append("unknown_position")
            checks.append(check)
            continue
        pid = str(position.id)
        check.position_id = pid
        if pid in seen:
            check.issues.append("duplicate_position")
        seen.add(pid)
        if check.unit and _unit_key(check.unit) != _unit_key(getattr(position, "unit", "")):
            check.issues.append("unit_mismatch")
        bill_qty = _decimal(getattr(position, "quantity", None))
        if file_qty and bill_qty is not None and file_qty.quantize(_THOUSANDTH) != bill_qty.quantize(_THOUSANDTH):
            check.issues.append("quantity_changed")
        if rate is None or rate <= 0:
            check.issues.append("unpriced")
        elif not check.issues:
            prices[pid] = rate
        checks.append(check)

    missing = [str(getattr(p, "ordinal", "") or pid) for pid, p in priceable.items() if pid not in seen]
    return checks, prices, missing


class X84BidImportService:
    """Check an X84 file against a package and write it as a bid."""

    def __init__(self, session: AsyncSession) -> None:
        from app.modules.tendering.service import TenderingService

        self.session = session
        self.tendering = TenderingService(session)

    async def _priceable(self, package: Any) -> dict[str, Any]:
        from app.modules.boq.repository import PositionRepository
        from app.modules.tendering.bid_portal import bidder_lines

        if package.boq_id is None:
            return {}
        positions = await PositionRepository(self.session).list_all_for_boq(package.boq_id)
        return bidder_lines(positions, package.metadata_)[1]

    async def check(self, package_id: uuid.UUID, filename: str, content: bytes) -> tuple[X84ImportPreview, Any, dict]:
        """Parse and match the file; nothing is stored."""
        from app.modules.boq.importers._base import ImporterParseError
        from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

        if len(content) > MAX_X84_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="file_too_large")
        package = await self.tendering.get_package(package_id)
        try:
            imported = await GAEBXMLImporter.parse(content)
        except ImporterParseError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="unreadable_file") from exc

        _, tender_currency = await self.tendering._project_name_and_currency(package)
        if not tender_currency:
            meta_currency = (package.metadata_ or {}).get("currency")
            tender_currency = meta_currency.strip().upper() if isinstance(meta_currency, str) else ""

        da_kind = ""
        file_currency = ""
        for row in imported.positions:
            meta = row.metadata or {}
            da_kind = da_kind or str(meta.get("gaeb_da_kind") or "")
            file_currency = file_currency or str(meta.get("gaeb_currency") or "").strip().upper()

        priceable = await self._priceable(package)
        lines, prices, missing = check_lines(imported.positions, priceable)
        total = sum(
            (prices[pid] * (_decimal(priceable[pid].quantity) or Decimal("0")) for pid in prices),
            Decimal("0"),
        )

        file_issues: list[str] = []
        if da_kind != "x84":
            file_issues.append("not_x84")
        if not priceable:
            file_issues.append("no_bill")
        if file_currency and tender_currency and file_currency != tender_currency:
            file_issues.append("currency_mismatch")
        if not prices:
            file_issues.append("nothing_priced")

        blocking = bool(set(file_issues) & BLOCKING_FILE_ISSUES) or any(
            set(line.issues) & BLOCKING_LINE_ISSUES for line in lines
        )
        preview = X84ImportPreview(
            filename=filename,
            sha256=hashlib.sha256(content).hexdigest(),
            da_kind=da_kind,
            currency=file_currency,
            tender_currency=tender_currency,
            file_issues=file_issues,
            lines=lines,
            matched=sum(1 for line in lines if line.position_id),
            priced=len(prices),
            missing_ordinals=missing,
            total_amount=format(total.quantize(Decimal("0.01")), "f"),
            blocking=blocking,
        )
        return preview, package, {"prices": prices, "priceable": priceable, "currency": tender_currency}

    async def import_bid(
        self,
        package_id: uuid.UUID,
        filename: str,
        content: bytes,
        *,
        company_name: str,
        contact_email: str = "",
    ) -> Any:
        """Write the file as a submitted bid; refused while any blocking issue remains."""
        preview, package, ctx = await self.check(package_id, filename, content)
        if preview.blocking:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="x84_has_blocking_issues")
        prices: dict[str, Decimal] = ctx["prices"]
        priceable: dict[str, Any] = ctx["priceable"]
        items: list[BidLineItem] = []
        for pid, position in priceable.items():
            if pid not in prices:
                continue
            quantity = _decimal(position.quantity) or Decimal("0")
            items.append(
                BidLineItem(
                    position_id=pid,
                    description=position.description or "",
                    unit=position.unit or "",
                    quantity=float(quantity),
                    unit_rate=prices[pid],
                    total=float(prices[pid] * quantity),
                )
            )
        unpriced = [pid for pid in priceable if pid not in prices]
        return await self.tendering.create_bid(
            package.id,
            BidCreate(
                company_name=company_name,
                contact_email=contact_email,
                total_amount=preview.total_amount,
                currency=ctx["currency"] or preview.currency,
                status="submitted",
                line_items=items,
                metadata={
                    "source": "gaeb_x84",
                    "file_name": filename[:255],
                    "file_sha256": preview.sha256,
                    "unpriced_position_ids": unpriced,
                    "unpriced_count": len(unpriced),
                },
            ),
        )
