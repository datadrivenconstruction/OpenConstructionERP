# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner bid schedule engine: read, detect, diff and write back. Pure, no session.

* :func:`read_grid` turns an xlsx or csv file into a grid of cell values.
* :func:`detect` scores every candidate profile against the file.
* :func:`parse` reads the pay items of a file under one profile.
* :func:`diff_items` compares a schedule with a revised one (an addendum).
* :func:`price_lines` applies the owner's rounding so the lines sum to the total exactly.
* :func:`write_back` writes priced values into the owner's own file and leaves
  every other cell, formula, style and protection as it was.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

from app.modules.owner_schedule.profile import ROLES, ScheduleProfile

MAX_SCAN_ROWS = 40
MAX_FILE_BYTES = 10 * 1024 * 1024


class ScheduleFileError(ValueError):
    """The file cannot be read as a bid schedule."""


@dataclass
class Grid:
    file_type: str
    sheet: str | None
    rows: list[list[Any]]  # rows[r-1][c-1] = value of cell (r, c), 1-based in the file
    sheets: list[str] = field(default_factory=list)

    def cell(self, row: int, col: int) -> Any:
        if row < 1 or row > len(self.rows):
            return None
        r = self.rows[row - 1]
        return r[col - 1] if 0 < col <= len(r) else None


@dataclass
class ScheduleLine:
    row: int
    item_no: str
    description: str
    unit: str
    quantity: Decimal | None
    is_section: bool = False
    is_alternate: bool = False
    is_lump_sum: bool = False
    given_amount: Decimal | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quantity"] = None if self.quantity is None else str(self.quantity)
        d["given_amount"] = None if self.given_amount is None else str(self.given_amount)
        return d


@dataclass
class ParseResult:
    profile_key: str
    sheet: str | None
    header_row: int | None
    columns: dict[str, int]
    lines: list[ScheduleLine]
    total_row: int | None
    issues: list[dict[str, Any]]


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower().rstrip(":")


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    text = str(value).strip().replace(" ", "").replace(" ", "")
    if not text or text.startswith("="):
        return None
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".") if len(text.split(",")[-1]) != 3 else text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _item_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip() if value is not None else ""


def read_grid(content: bytes, file_name: str, sheet: str | None = None) -> Grid:
    """Read an xlsx or csv file into a grid (csv by extension, xlsx by zip magic)."""
    if len(content) > MAX_FILE_BYTES:
        raise ScheduleFileError("file is larger than 10 MB")
    name = file_name.lower()
    if content[:2] == b"PK":
        try:
            wb = load_workbook(io.BytesIO(content), data_only=False, read_only=True)
        except Exception as exc:  # noqa: BLE001 - any openpyxl failure means unreadable
            raise ScheduleFileError(f"not a readable workbook: {exc}") from exc
        names = wb.sheetnames
        ws = wb[sheet] if sheet and sheet in names else wb[names[0]]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return Grid("xlsx", ws.title, rows, names)
    if name.endswith(".xml") or content.lstrip()[:5] == b"<?xml":
        return Grid("xml", None, [])
    if name.endswith((".csv", ".txt", ".tsv")) or not name:
        return Grid("csv", None, _csv_rows(content, None, None))
    raise ScheduleFileError("unsupported file type; use xlsx, csv or GAEB xml")


def _csv_rows(content: bytes, delimiter: str | None, encoding: str | None) -> list[list[Any]]:
    text = None
    for enc in [encoding] if encoding else ["utf-8-sig", "cp1252", "latin-1"]:
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ScheduleFileError("cannot decode the CSV file")
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _match_headers(grid: Grid, profile: ScheduleProfile) -> tuple[int | None, dict[str, int]]:
    """Find the header row and the column of each role by aliases."""
    best: tuple[int, int | None, dict[str, int]] = (0, None, {})
    aliases = {role: {_norm(a) for a in names} for role, names in profile.header_aliases.items()}
    rows = [profile.header_row] if profile.header_row else range(1, min(len(grid.rows), MAX_SCAN_ROWS) + 1)
    for r in rows:
        found: dict[str, int] = {}
        for c, value in enumerate(grid.rows[r - 1] if r <= len(grid.rows) else [], start=1):
            text = _norm(value)
            if not text:
                continue
            for role, names in aliases.items():
                if role not in found and text in names:
                    found[role] = c
                    break
        if len(found) > best[0]:
            best = (len(found), r, found)
    return best[1], best[2]


def resolve_columns(grid: Grid, profile: ScheduleProfile) -> tuple[int | None, dict[str, int]]:
    header_row, found = _match_headers(grid, profile) if profile.header_aliases else (profile.header_row, {})
    for role, letter in profile.columns.items():
        found[role] = column_index_from_string(letter)
    return header_row, found


def _is_alternate(value: Any, item_no: str, profile: ScheduleProfile) -> bool:
    tokens = {_norm(t) for t in profile.alternate_tokens}
    if value not in (None, ""):
        text = _norm(value)
        return text in tokens or text in {"yes", "y", "x", "true", "1"}
    return bool(re.match(r"^(alt|alternate|option)\b", item_no, re.I))


def parse(content: bytes, file_name: str, profile: ScheduleProfile, grid: Grid | None = None) -> ParseResult:
    """Read the pay items of a file under one profile."""
    if profile.handled_by == "gaeb":
        raise ScheduleFileError("GAEB XML schedules are imported through GAEB exchange")
    if grid is None:
        if profile.file_type == "csv":
            grid = Grid("csv", None, _csv_rows(content, profile.csv_delimiter, profile.csv_encoding))
        else:
            grid = read_grid(content, file_name, profile.sheet)
    header_row, cols = resolve_columns(grid, profile)
    issues: list[dict[str, Any]] = []
    for role in ("item_no", "description", "quantity"):
        if role not in cols:
            issues.append({"severity": "error", "code": "column_missing", "role": role, "row": None})
    if issues:
        return ParseResult(profile.key, grid.sheet, header_row, cols, [], None, issues)
    pattern = re.compile(profile.numbering_pattern) if profile.numbering_pattern else None
    totals = {_norm(t) for t in profile.total_markers}
    lump_tokens = {_norm(t) for t in profile.lump_sum.unit_tokens}
    lines: list[ScheduleLine] = []
    seen: set[str] = set()
    total_row = None
    for r in range(profile.data_start(header_row), len(grid.rows) + 1):

        def get(role: str, _r: int = r) -> Any:
            return grid.cell(_r, cols[role]) if role in cols else None

        item_no = _item_text(get("item_no"))
        desc = str(get("description") or "").strip()
        if not item_no and not desc:
            continue
        if _norm(item_no) in totals or (not item_no and _norm(desc) in totals):
            total_row = r
            continue
        if not item_no:
            continue  # continuation text or a note; the owner's file keeps it, we do not need it
        unit = str(get("unit") or "").strip()
        qty_raw = get("quantity")
        qty = to_decimal(qty_raw)
        is_lump = _norm(unit) in lump_tokens
        is_section = qty is None and not unit and not is_lump
        if is_lump and qty is None:
            qty = Decimal(1)
        line = ScheduleLine(
            row=r,
            item_no=item_no,
            description=desc,
            unit=unit,
            quantity=qty,
            is_section=is_section,
            is_alternate=_is_alternate(get("alternate_flag"), item_no, profile),
            is_lump_sum=is_lump,
            given_amount=to_decimal(get("amount")),
        )
        if not is_section:
            if pattern and not line.is_alternate and not pattern.fullmatch(item_no):
                issues.append({"severity": "warning", "code": "numbering_mismatch", "row": r, "item_no": item_no})
            if item_no in seen:
                issues.append({"severity": "error", "code": "duplicate_item", "row": r, "item_no": item_no})
            if qty_raw not in (None, "") and qty is None:
                issues.append({"severity": "error", "code": "quantity_unreadable", "row": r, "item_no": item_no})
            if not unit:
                issues.append({"severity": "warning", "code": "unit_missing", "row": r, "item_no": item_no})
            seen.add(item_no)
        lines.append(line)
    if not [ln for ln in lines if not ln.is_section]:
        issues.append({"severity": "error", "code": "no_items", "row": None})
    return ParseResult(profile.key, grid.sheet, header_row, cols, lines, total_row, issues)


def detect(content: bytes, file_name: str, profiles: list[ScheduleProfile]) -> list[dict[str, Any]]:
    """Score every profile against the file, best first. Confidence is 0..1; the user confirms."""
    try:
        grid = read_grid(content, file_name)
    except ScheduleFileError:
        return []
    out = []
    for p in profiles:
        if p.file_type != grid.file_type:
            continue
        if p.handled_by == "gaeb":
            out.append({"profile_key": p.key, "name": p.name, "source": p.source, "confidence": 0.95, "reasons": []})
            continue
        reasons: list[str] = []
        sheet_grid = grid
        if grid.file_type == "xlsx" and p.sheet:
            if p.sheet not in grid.sheets:
                continue
            sheet_grid = read_grid(content, file_name, p.sheet)
            reasons.append("sheet")
        header_row, cols = resolve_columns(sheet_grid, p)
        required = [r for r in ("item_no", "description", "quantity") if r in cols]
        fill = [r for r in p.fill_back if r in cols]
        score = 0.5 * len(required) / 3 + 0.15 * (1 if fill else 0)
        if p.header_aliases:
            matched = len([r for r in cols if r in p.header_aliases])
            score += 0.1 * matched / max(1, len([r for r in ROLES if r in p.header_aliases]))
        try:
            res = parse(content, file_name, p, sheet_grid)
        except ScheduleFileError:
            continue
        items = [ln for ln in res.lines if not ln.is_section]
        if items:
            with_qty = len([ln for ln in items if ln.quantity is not None]) / len(items)
            score += 0.1 * with_qty
            if p.numbering_pattern:
                rx = re.compile(p.numbering_pattern)
                base = [ln for ln in items if not ln.is_alternate] or items
                ratio = len([ln for ln in base if rx.fullmatch(ln.item_no)]) / len(base)
                score += 0.15 * ratio
                if ratio > 0.8:
                    reasons.append("numbering")
        else:
            score *= 0.3
        if p.columns:
            reasons.append("fixed_columns")
        if header_row:
            reasons.append("headers")
        if p.source != "platform":
            score += 0.02  # a specific profile wins a tie against the generic one
        out.append(
            {
                "profile_key": p.key,
                "name": p.name,
                "source": p.source,
                "confidence": round(min(score, 1.0), 2),
                "reasons": reasons,
                "item_count": len(items),
            }
        )
    out.sort(key=lambda d: d["confidence"], reverse=True)
    return out


def diff_items(current: list[dict[str, Any]], revised: list[ScheduleLine]) -> list[dict[str, Any]]:
    """Compare the schedule on file with a revised one, keyed by owner item number."""
    old = {c["item_no"]: c for c in current if not c.get("is_section") and not c.get("removed")}
    new = {ln.item_no: ln for ln in revised if not ln.is_section}
    changes: list[dict[str, Any]] = []
    for no, ln in new.items():
        if no not in old:
            changes.append({"kind": "added", "item_no": no, "new": ln.as_dict()})
            continue
        o = old[no]
        fields = []
        oq = None if o.get("quantity") is None else Decimal(str(o["quantity"]))
        if oq != ln.quantity:
            fields.append("quantity")
        if (o.get("unit") or "") != ln.unit:
            fields.append("unit")
        if (o.get("description") or "") != ln.description:
            fields.append("description")
        if fields:
            changes.append(
                {
                    "kind": "quantity_changed" if "quantity" in fields else "changed",
                    "item_no": no,
                    "fields": fields,
                    "old": {
                        "quantity": None if oq is None else str(oq),
                        "unit": o.get("unit"),
                        "description": o.get("description"),
                    },
                    "new": ln.as_dict(),
                }
            )
    for no, o in old.items():
        if no not in new:
            changes.append(
                {
                    "kind": "removed",
                    "item_no": no,
                    "old": {"quantity": o.get("quantity"), "unit": o.get("unit"), "description": o.get("description")},
                }
            )
    return changes


def _q(value: Decimal, decimals: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


@dataclass
class PricedLine:
    item_no: str
    row: int
    unit_price: Decimal | None
    amount: Decimal | None
    is_lump_sum: bool
    is_alternate: bool


def price_lines(
    lines: list[ScheduleLine], prices: dict[str, Decimal | None], profile: ScheduleProfile
) -> tuple[list[PricedLine], Decimal, Decimal]:
    """Apply the owner's rounding. Returns lines, base total (alternates excluded) and alternates total.

    The total is the sum of the rounded line amounts, so it equals the sum of the
    lines exactly whatever the owner's rounding is.
    """
    out: list[PricedLine] = []
    base = Decimal(0)
    alts = Decimal(0)
    rr = profile.rounding
    for ln in lines:
        if ln.is_section:
            continue
        price = prices.get(ln.item_no)
        if price is None:
            out.append(PricedLine(ln.item_no, ln.row, None, None, ln.is_lump_sum, ln.is_alternate))
            continue
        if ln.is_lump_sum:
            amount = _q(price * (ln.quantity or Decimal(1)), rr.amount_decimals)
            unit_price = _q(price, rr.unit_price_decimals)
        else:
            unit_price = _q(price, rr.unit_price_decimals)
            amount = _q(unit_price * (ln.quantity or Decimal(0)), rr.amount_decimals)
        out.append(PricedLine(ln.item_no, ln.row, unit_price, amount, ln.is_lump_sum, ln.is_alternate))
        if ln.is_alternate:
            alts += amount
        else:
            base += amount
    return out, base, alts


def _is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


def write_back(
    content: bytes, file_name: str, profile: ScheduleProfile, priced: list[PricedLine], total: Decimal
) -> tuple[bytes, list[dict[str, Any]]]:
    """Write priced values into the owner's file. Returns the new bytes and what was written.

    Only the fill-back cells of priced rows and the total cell change. A cell that
    holds a formula is left alone (the owner's sheet computes it), and so is a
    lump sum's unit price when the profile says amount only.
    """
    res = parse(content, file_name, profile)
    cols = res.columns
    log: list[dict[str, Any]] = []
    writes: list[tuple[int, int, Decimal, str]] = []
    for p in priced:
        if p.unit_price is None:
            continue
        if "unit_price" in profile.fill_back and "unit_price" in cols:
            if not (p.is_lump_sum and profile.lump_sum.mode == "amount_only"):
                writes.append((p.row, cols["unit_price"], p.unit_price, p.item_no))
        if "amount" in profile.fill_back and "amount" in cols:
            writes.append((p.row, cols["amount"], p.amount, p.item_no))  # type: ignore[arg-type]
    if profile.write_total and res.total_row and "amount" in cols:
        writes.append((res.total_row, cols["amount"], total, "total"))

    if profile.file_type == "csv":
        rows = _csv_rows(content, profile.csv_delimiter, profile.csv_encoding)
        for r, c, value, ref in writes:
            row = rows[r - 1]
            while len(row) < c:
                row.append("")
            row[c - 1] = format(value, "f")
            log.append({"cell": f"{get_column_letter(c)}{r}", "item_no": ref, "value": format(value, "f")})
        buf = io.StringIO()
        csv.writer(buf, delimiter=profile.csv_delimiter, lineterminator="\r\n").writerows(rows)
        enc = "utf-8" if profile.csv_encoding.lower() == "utf-8-sig" else profile.csv_encoding
        prefix = b"\xef\xbb\xbf" if content.startswith(b"\xef\xbb\xbf") else b""
        return prefix + buf.getvalue().encode(enc), log

    keep_vba = file_name.lower().endswith(".xlsm")
    wb = load_workbook(io.BytesIO(content), keep_vba=keep_vba)
    ws = wb[res.sheet] if res.sheet else wb.worksheets[0]
    for r, c, value, ref in writes:
        cell = ws.cell(row=r, column=c)
        letter = f"{get_column_letter(c)}{r}"
        if _is_formula(cell.value):
            log.append({"cell": letter, "item_no": ref, "value": None, "kept_formula": True})
            continue
        cell.value = value
        log.append({"cell": letter, "item_no": ref, "value": format(value, "f")})
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue(), log
