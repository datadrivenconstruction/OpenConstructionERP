# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compose a record form from a template and one record's context.

The output is a :class:`app.core.register_export.RecordDocument`, drawn by the
same renderer as every hand-written record form. That is how a module's
standard template reproduces its old form exactly: the standard blocks compile
to the very rows, weights and titles the module used to build by hand.

Amounts, quantities and line items come from the context; a template chooses
which of them print, in which order and under which heading, never what they
are. Text is merged with :mod:`app.core.doc_templates.merge` and escaped by
:mod:`app.core.doc_templates.markup`, so a value can never become markup.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from reportlab.lib.pagesizes import A4, LEGAL, LETTER, landscape
from reportlab.lib.units import mm

from app.core.doc_templates.layout.expr import evaluate
from app.core.doc_templates.layout.spec import LayoutContext, LayoutSpec
from app.core.doc_templates.layout.template import text_in
from app.core.doc_templates.markup import to_plain, to_reportlab
from app.core.doc_templates.pdf import LegalNote, decode_png_data_url
from app.core.record_layout import PAGE_NUMBER, PAGE_TOTAL
from app.core.register_export import PageSetup, RecordBlock, RecordDocument, grid_rows

__all__ = ["compile_layout", "condition_holds"]

_SIZES = {"A4": A4, "Letter": LETTER, "Legal": LEGAL}
_WIDTH_WEIGHTS = {"S": 0.7, "M": 1.4, "L": 3.0}
_NUMERIC = {"money", "quantity", "number", "percent"}


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def condition_holds(condition: Mapping[str, Any] | None, raw: Mapping[str, Any]) -> bool:
    """Whether a block's condition is met. No condition always holds."""
    if not condition:
        return True
    value = raw.get(condition.get("field", ""))
    op = condition.get("op")
    target = str(condition.get("value") or "")
    empty = value is None or (isinstance(value, str) and not value.strip())
    if op == "empty":
        return empty
    if op == "not_empty":
        return not empty
    if op == "contains":
        return not empty and target.lower() in str(value).lower()
    left, right = _dec(value), _dec(target)
    if left is not None and right is not None:
        return {
            "eq": left == right,
            "ne": left != right,
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }.get(str(op), False)
    if op in {"gt", "gte", "lt", "lte"}:
        return False
    text = "" if value is None else str(value).strip().lower()
    return (text == target.strip().lower()) == (op == "eq")


class _Compiler:
    def __init__(
        self,
        template: Mapping[str, Any],
        spec: LayoutSpec,
        ctx: LayoutContext,
        clauses: Mapping[str, Mapping[str, Any]],
    ) -> None:
        self.t = template
        self.spec = spec
        self.ctx = ctx
        self.clauses = clauses
        self.primary = str(template.get("primary_locale") or "en")
        self.known = spec.field_paths

    # Wording ---------------------------------------------------------------

    def word(self, value: Mapping[str, str] | None, default: str) -> str:
        """User wording in the document language, merged; the default when the template has none."""
        text = text_in(value, self.ctx.locale, self.primary)
        if text is None:
            return default
        return to_plain(text, self.ctx.values, self.known)

    def markup(self, value: Mapping[str, str] | None) -> list[str]:
        text = text_in(value, self.ctx.locale, self.primary)
        return to_reportlab(text or "", self.ctx.values, self.known)

    def label(self, key: str, fallback: str = "") -> str:
        return self.ctx.labels.get(key, fallback)

    def shows(self, block: Mapping[str, Any]) -> bool:
        return not block.get("hidden") and condition_holds(block.get("condition"), self.ctx.raw)

    # Blocks ----------------------------------------------------------------

    def blocks(self, blocks: Sequence[Mapping[str, Any]]) -> list[RecordBlock]:
        out: list[RecordBlock] = []
        for block in blocks:
            if not self.shows(block):
                continue
            compiled = getattr(self, f"b_{block['type']}")(block)
            style = block.get("style")
            if style and compiled:
                compiled = [dataclasses.replace(compiled[0], style=style), *compiled[1:]]
            out.extend(compiled)
        return out

    def b_section(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        parts = list(self.ctx.sections.get(str(block.get("section")), []))
        if block.get("title") and parts:
            title = self.word(block.get("title"), parts[0].title)
            parts = [dataclasses.replace(parts[0], title=title), *parts[1:]]
        return parts

    def b_heading(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        text = self.word(block.get("text"), "")
        return [RecordBlock(text, kind="heading", level=int(block.get("level") or 1))] if text else []

    def b_text(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        title = self.word(block.get("title"), "")
        markup = self.markup(block.get("text"))
        return [RecordBlock(title, kind="rich", markup=markup)] if markup or title else []

    def b_notes(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        title = self.word(block.get("title"), "")
        text = self.word(block.get("text"), "")
        return [RecordBlock(title, kind="text", text=text, empty_text=" ")]

    def b_clause(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        clause = self.clauses.get(str(block.get("clause_id") or "")) or {}
        title = self.word(block.get("title") or clause.get("title"), "")
        markup = self.markup(block.get("text") or clause.get("text"))
        return [RecordBlock(title, kind="rich", markup=markup)] if markup else []

    def _pairs(self, block: Mapping[str, Any]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for entry in block.get("fields") or []:
            path = entry["field"]
            if not condition_holds(entry.get("condition"), self.ctx.raw):
                continue
            value = self.ctx.values.get(path, "")
            if entry.get("omit_empty") and not value.strip():
                continue
            label = self.word(entry.get("label"), self.label(f"field:{path}", path))
            pairs.append((label, value or self.ctx.empty))
        return pairs

    def b_fields(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        pairs = self._pairs(block)
        if not pairs:
            return []
        title = self.word(block.get("title"), self.label(f"section:{block['id']}"))
        if block.get("layout") == "rows":
            return [RecordBlock(title, kind="grid", rows=[[k, v] for k, v in pairs])]
        rows = grid_rows(pairs)
        return [RecordBlock(title, kind="grid", rows=rows)] if title else [RecordBlock("", kind="bare_grid", rows=rows)]

    def b_totals(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        rows: list[list[str]] = []
        for entry in block.get("rows") or []:
            if not condition_holds(entry.get("condition"), self.ctx.raw):
                continue
            if entry.get("field"):
                path = entry["field"]
                value = self.ctx.values.get(path, "") or self.ctx.empty
                default = self.label(f"field:{path}", path)
            else:
                value = self.ctx.format(entry.get("format") or "money", evaluate(entry["expr"], self.ctx.raw))
                value = value or self.ctx.empty
                default = ""
            rows.append([self.word(entry.get("label"), default), value])
        if not rows:
            return []
        title = self.word(block.get("title"), self.label(f"section:{block['id']}"))
        return [RecordBlock(title, kind="grid", rows=rows)]

    def b_signatures(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        signers = []
        for entry in block.get("signers") or []:
            path = entry.get("field") or ""
            name = self.ctx.values.get(path, "") if path else ""
            role = self.word(entry.get("role"), self.label(f"signer:{path}", ""))
            signers.append((role, name or self.ctx.empty))
        if not signers:
            return []
        title = self.word(block.get("title"), self.label(f"section:{block['id']}"))
        return [RecordBlock(title, kind="signatures", rows=self.ctx.signature_rows(signers))]

    def b_image(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        if block.get("source") == "signature":
            data = decode_png_data_url(block.get("data"))
        else:
            from app.core.pdf_branding import branded_logo_bytes

            data = branded_logo_bytes()
        if not data:
            return []
        return [RecordBlock("", kind="image", image=data, width=float(block.get("width_mm") or 40))]

    def b_qr(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        value = self.ctx.values.get(str(block.get("field") or ""), "")
        if not value:
            return []
        caption = value if block.get("caption") else ""
        return [RecordBlock(caption, kind="qr", text=value, width=float(block.get("size_mm") or 22))]

    def b_spacer(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        return [RecordBlock("", kind="spacer", height=float(block.get("height_mm") or 6))]

    def b_page_break(self, _block: Mapping[str, Any]) -> list[RecordBlock]:
        return [RecordBlock("", kind="page_break")]

    def b_columns(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        children = [self.blocks(column) for column in block.get("columns") or []]
        if not any(children):
            return []
        return [RecordBlock("", kind="columns", children=children, ratios=list(block.get("ratios") or []))]

    def b_table(self, block: Mapping[str, Any]) -> list[RecordBlock]:
        collection = self.spec.collection(str(block.get("collection")))
        if collection is None:
            return []
        title = self.word(block.get("title"), self.label(f"section:{block['id']}"))
        rows = self.ctx.collections.get(collection.id, [])
        if not rows:
            empty = self.word(block.get("empty_text"), self.label(f"empty:{block['id']}"))
            return [RecordBlock(title, empty_text=empty)]
        columns = []
        for column in block.get("columns") or []:
            if column.get("hidden"):
                continue
            declared = collection.column(column["id"])
            if declared is None and not column["id"].startswith("calc_"):
                continue
            fmt = column.get("format") or (declared.format if declared else "number")
            heading = self.word(column.get("label"), self.label(f"column:{collection.id}.{column['id']}", column["id"]))
            weight = _WIDTH_WEIGHTS.get(column.get("width") or "", declared.weight if declared else 1.0)
            right = declared.right if declared else fmt in _NUMERIC
            keep = declared.keep if declared else fmt in _NUMERIC
            columns.append((column, declared, fmt, heading, weight, right, keep))
        if not columns:
            return []
        group_by = block.get("group_by")
        if group_by:
            grouped: dict[str, list[dict[str, tuple[Any, str]]]] = {}
            for row in rows:
                grouped.setdefault((row.get(group_by) or (None, ""))[1] or self.ctx.empty, []).append(row)
            groups = list(grouped.items())
        else:
            groups = [("", list(rows))]
        out: list[RecordBlock] = []
        index = 0
        for group_title, group_rows in groups:
            table: list[list[str]] = [[c[3] for c in columns]]
            sums: dict[int, Decimal] = {}
            for row in group_rows:
                index += 1
                lookup = {k: v[0] for k, v in row.items()}
                lookup.update({k: v for k, v in self.ctx.raw.items() if "." in k})
                cells = []
                for pos, (column, declared, fmt, *_rest) in enumerate(columns):
                    if fmt == "index":
                        cells.append(str(index))
                        continue
                    if declared is None:
                        raw = evaluate(column.get("expr") or "", lookup)
                        lookup[column["id"]] = raw
                        cells.append(self.ctx.format(fmt, raw) or self.ctx.empty)
                    else:
                        raw, display = row.get(column["id"], (None, ""))
                        if column.get("format") and column.get("format") != declared.format:
                            display = self.ctx.format(fmt, raw)
                        cells.append(display or self.ctx.empty)
                    number = _dec(raw) if fmt in _NUMERIC else None
                    if number is not None:
                        sums[pos] = sums.get(pos, Decimal(0)) + number
                table.append(cells)
            total_rows = 0
            if group_by and block.get("subtotals"):
                total = [""] * len(columns)
                total[0] = self.label("subtotal", "Subtotal")
                for pos, value in sums.items():
                    if pos and columns[pos][2] in {"money", "quantity", "number"}:
                        total[pos] = self.ctx.format(columns[pos][2], value)
                table.append(total)
                total_rows = 1
            out.append(
                RecordBlock(
                    f"{title} · {group_title}" if group_title and title else (group_title or title),
                    kind="table",
                    rows=table,
                    weights=[c[4] for c in columns],
                    right_aligned=[c[5] for c in columns],
                    keep_together=[c[6] for c in columns],
                    total_rows=total_rows,
                )
            )
        return out


def _page(template: Mapping[str, Any]) -> PageSetup | None:
    page = template.get("page") or {}
    keys = ("margin_side_mm", "margin_top_mm", "margin_bottom_mm")
    if (
        page.get("size", "A4") == "A4"
        and page.get("orientation", "portrait") == "portrait"
        and not any(k in page for k in keys)
    ):
        return None
    size = _SIZES.get(str(page.get("size") or "A4"), A4)
    if page.get("orientation") == "landscape":
        size = landscape(size)
    return PageSetup(
        width=size[0],
        height=size[1],
        margin_side=float(page.get("margin_side_mm", 20)) * mm,
        margin_top=float(page.get("margin_top_mm", 18)) * mm,
        margin_bottom=float(page.get("margin_bottom_mm", 18)) * mm,
    )


def _furniture(c: _Compiler, lines: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str], ...]:
    out = []
    values = dict(c.ctx.values)
    values["page.number"] = PAGE_NUMBER
    values["page.total"] = PAGE_TOTAL
    for line in lines:
        text = text_in(line.get("text"), c.ctx.locale, c.primary)
        if text:
            out.append((str(line.get("align") or "left"), to_plain(text, values, c.known)))
    return tuple(out)


def compile_layout(
    template: Mapping[str, Any],
    spec: LayoutSpec,
    ctx: LayoutContext,
    *,
    clauses: Mapping[str, Mapping[str, Any]] | None = None,
    legal: Sequence[LegalNote] = (),
) -> RecordDocument:
    """The record form *template* prints for the record in *ctx*.

    Args:
        template: A normalised template (:func:`app.core.doc_templates.layout.template.normalise`).
        spec: The document's layout spec.
        ctx: One record's data.
        clauses: The clause library, ``id -> {"title": {lang: text}, "text": {lang: text}}``.
        legal: Locked notes from the country packs, printed after the body and never editable.
    """
    c = _Compiler(template, spec, ctx, clauses or {})
    base = ctx.base
    blocks = c.blocks(template.get("body") or [])
    grid: Sequence[Sequence[str]] = ()
    if blocks and blocks[0].kind == "bare_grid" and not blocks[0].style:
        # The record form prints its first grid under the subject; the standard templates start with it.
        grid, blocks = blocks[0].rows, blocks[1:]
    if legal:
        markup = [
            f"<b>{_esc(note.text)}</b>"
            + (f' <font size="7" color="#777777">({_esc(note.source)})</font>' if note.source else "")
            for note in legal
        ]
        blocks.append(RecordBlock("", kind="rich", markup=markup))
    branding = template.get("branding") or {}
    page = template.get("page") or {}
    watermark = ""
    status_text = (template.get("watermark") or {}).get((ctx.status or "").lower())
    if status_text:
        watermark = c.word(status_text, "")
    changes: dict[str, Any] = {
        "title": c.word(template.get("title"), base.title),
        "subject": c.word(template.get("subject"), base.subject),
        "blocks": blocks,
        "grid": grid,
        "page": _page(template),
        "watermark_text": watermark,
        "header_lines": _furniture(c, template.get("header") or []),
        "footer_lines": _furniture(c, template.get("footer") or []),
        "header_on_first_page": page.get("first_page_header", True) is not False,
        "page_numbers": page.get("page_numbers") if isinstance(page.get("page_numbers"), bool) else None,
        "accent": str(branding.get("accent") or ""),
        "serif": branding.get("font") == "serif",
        "letterhead": branding.get("letterhead", True) is not False,
        "show_subject": template.get("show_subject", True) is not False,
    }
    return dataclasses.replace(base, **changes)


def _esc(text: str) -> str:
    import html

    return html.escape(text or "", quote=False)
