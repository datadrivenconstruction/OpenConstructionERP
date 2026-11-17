# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Ledger lines and payment status read back from the books, and the reconciliation report.

A books file (CSV or Excel) is streamed row by row and written in chunks of 50 000 lines,
so a year of postings never sits in memory. Columns are found by header name in any of
the common spellings (English and German), so a DATEV or journal re-export reads as is.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import IO, Any

from fastapi import HTTPException, status
from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting_sync.models import AccountingConnection, LedgerImportLine
from app.modules.accounting_sync.postings import ZERO, money

CHUNK = 50_000
MAX_ERRORS = 50
TOLERANCE = Decimal("0.01")

_ALIASES: dict[str, tuple[str, ...]] = {
    "document_number": ("document_number", "document", "number", "belegfeld 1", "belegnummer", "invoice", "reference"),
    "posting_date": ("posting_date", "date", "booking_date", "belegdatum", "buchungsdatum"),
    "account": ("account", "konto", "account_code"),
    "debit": ("debit", "soll"),
    "credit": ("credit", "haben"),
    "amount": ("amount", "umsatz", "umsatz (ohne soll/haben-kz)", "betrag"),
    "dc": ("soll/haben-kennzeichen", "dc", "debit_credit"),
    "currency": ("currency", "wkz umsatz", "waehrung", "währung"),
    "payment_status": ("payment_status", "status", "paid"),
    "description": ("description", "buchungstext", "text", "memo"),
}
_PAID = {"paid", "bezahlt", "settled", "closed", "1", "true", "yes"}


@dataclass
class ImportResult:
    import_id: uuid.UUID
    file_name: str
    lines: int
    skipped: int
    errors: list[dict[str, Any]]


def _norm(header: str) -> str:
    return re.sub(r"\s+", " ", str(header or "").strip().lower().lstrip("﻿"))


def _map_columns(header: list[str]) -> dict[str, int]:
    names = [_norm(h) for h in header]
    out: dict[str, int] = {}
    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in names:
                out[field] = names.index(alias)
                break
    return out


def parse_amount(value: Any) -> Decimal | None:
    """Decimal from ``1234.56``, ``1,234.56``, ``1.234,56``, ``1234,56`` or a number cell."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float | Decimal):
        return money(value)
    text = str(value).strip().replace(" ", "").replace(" ", "").strip('"')
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")") or text.endswith("-")
    text = text.strip("()").rstrip("-").lstrip("+")
    if "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
    elif "," in text:
        tail = text.rpartition(",")[2]
        decimal_sep = "," if text.count(",") == 1 and len(tail) != 3 else ""
    else:
        decimal_sep = "." if text.count(".") == 1 else ""
    for sep in ".,":
        if sep != decimal_sep:
            text = text.replace(sep, "")
    if decimal_sep == ",":
        text = text.replace(",", ".")
    try:
        d = money(Decimal(text))
    except (InvalidOperation, ValueError):
        return None
    return -d if negative else d


def parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y%m%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).date()
        except ValueError:
            continue
    return None


def _csv_rows(stream: IO[bytes]) -> Iterator[list[Any]]:
    head = stream.read(8192)
    stream.seek(0)
    try:
        text = head.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "cp1252"
        text = head.decode(encoding, errors="replace")
    delim = max(";,\t", key=lambda d: text.split("\n", 1)[0].count(d))
    wrapper = io.TextIOWrapper(stream, encoding=encoding, errors="replace", newline="")
    yield from csv.reader(wrapper, delimiter=delim)


def _xlsx_rows(stream: IO[bytes]) -> Iterator[list[Any]]:
    from openpyxl import load_workbook

    wb = load_workbook(stream, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        for row in ws.iter_rows(values_only=True):
            yield list(row)
    finally:
        wb.close()


def parse_lines(stream: IO[bytes], file_name: str) -> Iterator[tuple[int, dict[str, Any] | None, str | None]]:
    """Yield ``(line_no, values, error)`` per data row; headers are found in the first non-empty row."""
    rows = _xlsx_rows(stream) if file_name.lower().endswith((".xlsx", ".xlsm")) else _csv_rows(stream)
    cols: dict[str, int] | None = None
    for n, row in enumerate(rows, start=1):
        if cols is None:
            if not any(str(c or "").strip() for c in row):
                continue
            cols = _map_columns([str(c or "") for c in row])
            if "document_number" not in cols or not ({"amount", "debit", "credit"} & set(cols)):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="The file needs a document number column and an amount, debit or credit column",
                )
            continue
        if not any(str(c or "").strip() for c in row):
            continue

        def cell(field: str, row: list[Any] = row) -> Any:
            i = cols.get(field) if cols else None
            return row[i] if i is not None and i < len(row) else None

        debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
        amount = parse_amount(cell("amount"))
        if debit is None and credit is None:
            if amount is None:
                yield n, None, "amount"
                continue
            side = str(cell("dc") or "").strip().strip('"').upper()
            if side in ("H", "C", "CR"):
                credit = abs(amount)
            elif side in ("S", "D", "DR"):
                debit = abs(amount)
            else:
                debit, credit = (amount, ZERO) if amount >= 0 else (ZERO, -amount)
        number = str(cell("document_number") or "").strip().strip('"')
        if not number:
            yield n, None, "document_number"
            continue
        status_raw = str(cell("payment_status") or "").strip().lower()
        yield (
            n,
            {
                "posting_date": parse_day(cell("posting_date")),
                "document_number": number[:80],
                "account": str(cell("account") or "").strip()[:40],
                "debit": debit or ZERO,
                "credit": credit or ZERO,
                "currency": str(cell("currency") or "").strip().strip('"').upper()[:3],
                "payment_status": ("paid" if status_raw in _PAID else status_raw[:20]),
                "description": str(cell("description") or "").strip().strip('"')[:255],
            },
            None,
        )


class LedgerImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def import_file(
        self, conn: AccountingConnection, stream: IO[bytes], file_name: str, *, replace_period: bool = False
    ) -> ImportResult:
        """Stream a books file into ``oe_acctsync_import`` in chunks."""
        import_id = uuid.uuid4()
        buffer: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        total = skipped = 0
        for n, values, error in parse_lines(stream, file_name):
            if values is None:
                skipped += 1
                if len(errors) < MAX_ERRORS:
                    errors.append({"line": n, "field": error})
                continue
            buffer.append(
                {
                    "id": uuid.uuid4(),
                    "connection_id": conn.id,
                    "import_id": import_id,
                    "file_name": file_name[:200],
                    "line_no": n,
                    **values,
                }
            )
            if len(buffer) >= CHUNK:
                total += await self._flush(buffer)
        total += await self._flush(buffer)
        if total == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="No ledger lines found in the file")
        return ImportResult(import_id=import_id, file_name=file_name, lines=total, skipped=skipped, errors=errors)

    async def _flush(self, buffer: list[dict[str, Any]]) -> int:
        n = len(buffer)
        if n:
            await self.session.execute(insert(LedgerImportLine), buffer)
            await self.session.flush()
            buffer.clear()
        return n

    async def list_imports(self, conn: AccountingConnection) -> list[dict[str, Any]]:
        rows = await self.session.execute(
            select(
                LedgerImportLine.import_id,
                func.max(LedgerImportLine.file_name),
                func.count(),
                func.min(LedgerImportLine.posting_date),
                func.max(LedgerImportLine.posting_date),
                func.max(LedgerImportLine.created_at),
            )
            .where(LedgerImportLine.connection_id == conn.id)
            .group_by(LedgerImportLine.import_id)
            .order_by(func.max(LedgerImportLine.created_at).desc())
        )
        return [
            {
                "import_id": str(i),
                "file_name": name,
                "lines": int(n),
                "date_from": lo.isoformat() if lo else None,
                "date_to": hi.isoformat() if hi else None,
                "created_at": created.isoformat() if created else None,
            }
            for i, name, n, lo, hi, created in rows.all()
        ]

    async def delete_import(self, conn: AccountingConnection, import_id: uuid.UUID) -> int:
        res = await self.session.execute(
            delete(LedgerImportLine).where(
                LedgerImportLine.connection_id == conn.id, LedgerImportLine.import_id == import_id
            )
        )
        return int(res.rowcount or 0)

    async def books_totals(self, conn: AccountingConnection, period: tuple[date, date]) -> dict[str, dict[str, Any]]:
        """Per document number: gross as booked (sum of debits), booking date, payment status."""
        rows = await self.session.execute(
            select(
                LedgerImportLine.document_number,
                func.sum(LedgerImportLine.debit),
                func.sum(LedgerImportLine.credit),
                func.min(LedgerImportLine.posting_date),
                func.max(LedgerImportLine.payment_status),
            )
            .where(
                LedgerImportLine.connection_id == conn.id,
                (LedgerImportLine.posting_date.is_(None))
                | ((LedgerImportLine.posting_date >= period[0]) & (LedgerImportLine.posting_date <= period[1])),
            )
            .group_by(LedgerImportLine.document_number)
        )
        out: dict[str, dict[str, Any]] = {}
        for number, debit, credit, day, paid in rows.all():
            amount = max(Decimal(str(debit or 0)), Decimal(str(credit or 0)))
            out[number] = {"amount": amount, "date": day, "payment_status": paid or ""}
        return out


def reconcile(platform: Iterable[dict[str, Any]], books: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare platform documents (number, amount) with booked totals by document number."""
    matched, mismatches, platform_only = [], [], []
    seen: set[str] = set()
    for p in sorted(platform, key=lambda r: r["number"]):
        b = books.get(p["number"])
        seen.add(p["number"])
        row = {
            "number": p["number"],
            "record_id": p.get("record_id"),
            "counterparty": p.get("counterparty", ""),
            "doc_date": p.get("doc_date"),
            "platform_amount": str(p["amount"]),
        }
        if b is None:
            platform_only.append(row)
            continue
        row["books_amount"] = str(b["amount"])
        row["payment_status"] = b["payment_status"]
        diff = money(b["amount"]) - money(p["amount"])
        row["difference"] = str(diff)
        (mismatches if abs(diff) > TOLERANCE else matched).append(row)
    books_only = [
        {
            "number": n,
            "books_amount": str(b["amount"]),
            "doc_date": b["date"].isoformat() if b["date"] else None,
            "payment_status": b["payment_status"],
        }
        for n, b in sorted(books.items())
        if n not in seen
    ]
    return {
        "matched": matched,
        "mismatches": mismatches,
        "platform_only": platform_only,
        "books_only": books_only,
        "counts": {
            "matched": len(matched),
            "mismatches": len(mismatches),
            "platform_only": len(platform_only),
            "books_only": len(books_only),
        },
    }
