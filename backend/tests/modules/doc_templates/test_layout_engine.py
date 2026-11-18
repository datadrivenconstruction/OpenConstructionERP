# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layout engine: expressions, normalisation, checks, locks, compile, diff, validation rules."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from app.core.doc_templates.layout import template as tpl
from app.core.doc_templates.layout.compile import compile_layout, condition_holds
from app.core.doc_templates.layout.expr import ExprError, evaluate, names_in, parse
from app.core.register_export import build_record_pdf
from app.modules.doc_templates.layout_service import diff_templates
from app.modules.procurement.layouts import GOODS_RECEIPT, PURCHASE_ORDER, purchase_order_standard


def _po() -> dict[str, Any]:
    return tpl.normalise(purchase_order_standard())


def _rules(template: dict[str, Any], countries: tuple[str, ...] = ()) -> set[str]:
    return {i.rule_id for i in tpl.check(template, PURCHASE_ORDER, tpl.locks_for(PURCHASE_ORDER, countries))}


def _block(template: dict[str, Any], block_id: str) -> dict[str, Any]:
    return next(b for b in template["body"] if b["id"] == block_id)


# ── Expressions ──────────────────────────────────────────────────────────


def test_expression_multiplies_decimals_exactly() -> None:
    assert evaluate("quantity * unit_rate", {"quantity": Decimal("400"), "unit_rate": Decimal("98.50")}) == Decimal(
        "39400.00"
    )


def test_expression_functions_and_comparisons() -> None:
    lookup = {"a": Decimal("2.345"), "b": None, "doc.total": Decimal("10")}
    assert evaluate("round(a, 2)", lookup) == Decimal("2.35") or evaluate("round(a, 2)", lookup) == Decimal("2.34")
    assert evaluate("coalesce(b, 5)", lookup) == Decimal("5")
    assert evaluate("if(doc.total > 5, 1, 0)", lookup) == Decimal("1")
    assert names_in(parse("a + doc.total")) == {"a", "doc.total"}


def test_expression_never_raises_on_bad_data() -> None:
    assert evaluate("a / 0", {"a": Decimal(1)}) is None
    assert evaluate("a + ", {"a": Decimal(1)}) is None


@pytest.mark.parametrize("text", ["__import__('os')", "a.__class__", "open('x')", "[1, 2]", "lambda: 1", "a" * 400])
def test_expression_language_is_closed(text: str) -> None:
    with pytest.raises(ExprError):
        parse(text)


# ── Normalise and check ──────────────────────────────────────────────────


def test_standard_template_has_no_issues_and_survives_normalise() -> None:
    template = _po()
    assert tpl.normalise(template) == template
    assert _rules(template) == set()


def test_normalise_drops_unknown_blocks_keys_and_bad_colours() -> None:
    raw = {
        "branding": {"accent": "red; drop", "font": "comic"},
        "body": [{"type": "script", "id": "x"}, {"type": "text", "id": "t", "text": {"en": "Hi"}, "onclick": "x"}],
    }
    out = tpl.normalise(raw)
    assert out["branding"] == {}
    assert [b["type"] for b in out["body"]] == ["text"]
    assert "onclick" not in out["body"][0]


def test_hiding_a_locked_section_is_an_error() -> None:
    template = _po()
    _block(template, "line_items")["hidden"] = True
    assert tpl.REQUIRED_SECTION_HIDDEN in _rules(template)


def test_deleting_a_locked_section_is_an_error() -> None:
    template = _po()
    template["body"] = [b for b in template["body"] if b["id"] != "totals"]
    assert tpl.REQUIRED_SECTION_HIDDEN in _rules(template)


def test_hiding_a_locked_column_is_an_error_but_an_optional_one_is_not() -> None:
    template = _po()
    table = _block(template, "line_items")
    table["columns"] = [c for c in table["columns"] if c["id"] != "no"]
    assert _rules(template) == set()
    table["columns"] = [c for c in table["columns"] if c["id"] != "amount"]
    assert tpl.REQUIRED_COLUMN_HIDDEN in _rules(template)


def test_removing_a_locked_field_is_an_error() -> None:
    template = _po()
    details = _block(template, "order_details")
    details["fields"] = [f for f in details["fields"] if f["field"] != "supplier.name"]
    assert tpl.REQUIRED_FIELD_REMOVED in _rules(template)


def test_unknown_merge_field_and_html_are_errors() -> None:
    template = _po()
    template["body"].append({"id": "intro", "type": "text", "hidden": False, "text": {"en": "Dear {{doc.nope}}"}})
    template["body"].append({"id": "bad", "type": "text", "hidden": False, "text": {"en": "<script>x</script>"}})
    rules = _rules(tpl.normalise(template))
    assert "doctpl.unknown_merge_field" in rules
    assert "doctpl.raw_html" in rules


def test_invalid_formula_is_an_error() -> None:
    template = _po()
    _block(template, "line_items")["columns"].append({"id": "calc_x", "expr": "quantity *"})
    assert tpl.INVALID_EXPRESSION in _rules(tpl.normalise(template))


def test_too_many_blocks_is_an_error() -> None:
    template = _po()
    template["body"] += [{"type": "spacer"} for _ in range(tpl.MAX_BLOCKS)]
    assert tpl.CUSTOM_BLOCK_LIMIT in _rules(tpl.normalise(template))


def test_pack_locks_add_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.doc_templates import legal

    def fake(kind: str, countries: Any, extra: Any = None) -> list[dict]:
        if kind == PURCHASE_ORDER.key and "XX" in countries:
            return [{"sections": ["terms"], "fields": ["supplier.tax_id"], "source": "Pack rule 12"}]
        return []

    monkeypatch.setattr(legal, "pack_layout_locks", fake)
    locks = tpl.locks_for(PURCHASE_ORDER, ["XX"])
    assert locks.sections["terms"] == "Pack rule 12"
    assert locks.fields["supplier.tax_id"] == "Pack rule 12"
    template = _po()
    _block(template, "terms")["hidden"] = True
    assert tpl.REQUIRED_SECTION_HIDDEN in _rules(template, ("XX",))
    assert tpl.REQUIRED_SECTION_HIDDEN not in _rules(template)


# ── Compile ──────────────────────────────────────────────────────────────


def _ctx(locale: str = "en") -> Any:
    return PURCHASE_ORDER.sample(locale)


def test_normalised_standard_compiles_like_the_raw_standard() -> None:
    for locale in ("en", "de", "ru"):
        ctx = _ctx(locale)
        assert compile_layout(_po(), PURCHASE_ORDER, ctx) == compile_layout(
            purchase_order_standard(), PURCHASE_ORDER, ctx
        )


def test_reordering_and_hiding_blocks() -> None:
    template = _po()
    template["body"].reverse()
    _block(template, "terms")["hidden"] = True
    doc = compile_layout(template, PURCHASE_ORDER, _ctx())
    titles = [b.title for b in doc.blocks]
    assert titles.index("Signatures") < titles.index("Line items")
    assert "Terms" not in titles


def test_renamed_reordered_and_computed_columns() -> None:
    template = _po()
    table = _block(template, "line_items")
    table["columns"] = [
        {"id": "amount", "label": {"en": "Net", "de": "Netto"}},
        {"id": "description", "width": "L"},
        {"id": "quantity"},
        {"id": "unit"},
        {"id": "unit_rate"},
        {"id": "calc_vat", "label": {"en": "VAT"}, "expr": "amount * 0.19", "format": "money"},
    ]
    doc = compile_layout(tpl.normalise(template), PURCHASE_ORDER, _ctx("de"))
    rows = next(b for b in doc.blocks if b.kind == "table").rows
    assert rows[0][0] == "Netto"
    assert rows[0][-1] == "VAT"
    assert rows[1][-1].startswith("7.486")


def test_grouping_with_subtotals() -> None:
    template = _po()
    table = _block(template, "line_items")
    table["group_by"] = "unit"
    table["subtotals"] = True
    doc = compile_layout(tpl.normalise(template), PURCHASE_ORDER, _ctx())
    tables = [b for b in doc.blocks if b.kind == "table"]
    assert len(tables) == 2
    assert all(t.total_rows == 1 for t in tables)


def test_conditional_block_and_rich_text_language_fallback() -> None:
    template = _po()
    template["body"].insert(
        1,
        {
            "id": "big",
            "type": "text",
            "text": {"en": "Order over budget: **{{doc.total}}**", "de": "Auftrag über Budget"},
            "condition": {"field": "doc.total", "op": "gt", "value": "1000"},
        },
    )
    template = tpl.normalise(template)
    fr = compile_layout(template, PURCHASE_ORDER, _ctx("fr"))
    rich = [b for b in fr.blocks if b.kind == "rich"]
    assert rich and "<b>" in rich[0].markup[0]
    template["body"][1]["condition"]["value"] = "1000000"
    assert not [b for b in compile_layout(template, PURCHASE_ORDER, _ctx()).blocks if b.kind == "rich"]


def test_condition_operators() -> None:
    raw = {"x": Decimal("5"), "s": "Hamburg", "n": None}
    assert condition_holds({"field": "x", "op": "gte", "value": "5"}, raw)
    assert condition_holds({"field": "s", "op": "contains", "value": "burg"}, raw)
    assert condition_holds({"field": "n", "op": "empty"}, raw)
    assert not condition_holds({"field": "x", "op": "lt", "value": "5"}, raw)


def test_page_setup_watermark_and_furniture() -> None:
    template = _po()
    template["page"] = {"size": "Letter", "orientation": "landscape", "margin_side_mm": 12, "page_numbers": True}
    template["watermark"] = {"draft": {"en": "DRAFT"}}
    template["footer"] = [{"text": {"en": "{{doc.number}} · page {{page.number}} of {{page.total}}"}}]
    template["branding"] = {"accent": "#0A5C36", "font": "serif"}
    doc = compile_layout(tpl.normalise(template), PURCHASE_ORDER, _ctx())
    assert doc.page is not None and doc.page.width > doc.page.height
    assert doc.watermark_text == "DRAFT"
    assert doc.footer_lines and "PO-2026-0142" in doc.footer_lines[0][1]
    assert doc.accent == "#0A5C36" and doc.serif


def test_every_block_type_renders_a_pdf() -> None:
    template = _po()
    template["header"] = [{"text": {"en": "{{entity.legal_name}}"}}]
    template["body"] += [
        {"type": "heading", "text": {"en": "Scope"}, "level": 2, "style": {"align": "center", "font_size": 12}},
        {"type": "notes", "title": {"en": "Remarks"}, "text": {"en": "Gate B"}},
        {"type": "clause", "clause_id": "warranty"},
        {
            "type": "columns",
            "columns": [
                [{"type": "fields", "fields": [{"field": "doc.number"}], "layout": "rows"}],
                [{"type": "qr", "field": "doc.number", "caption": True}],
            ],
        },
        {"type": "spacer", "height_mm": 10},
        {"type": "page_break"},
        {"type": "image", "source": "logo"},
        {"type": "totals", "rows": [{"expr": "doc.total - doc.tax", "label": {"en": "Net"}}]},
    ]
    clauses = {"warranty": {"title": {"en": "Warranty"}, "text": {"en": "Five years from acceptance."}}}
    doc = compile_layout(tpl.normalise(template), PURCHASE_ORDER, _ctx(), clauses=clauses)
    assert any(b.kind == "columns" for b in doc.blocks)
    pdf = build_record_pdf(doc)
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000


def test_goods_receipt_standard_is_clean() -> None:
    template = tpl.normalise(GOODS_RECEIPT.standard(None))
    assert tpl.check(template, GOODS_RECEIPT, tpl.locks_for(GOODS_RECEIPT)) == []
    assert build_record_pdf(compile_layout(template, GOODS_RECEIPT, GOODS_RECEIPT.sample("en"))).startswith(b"%PDF")


# ── Diff ─────────────────────────────────────────────────────────────────


def test_diff_names_added_removed_changed_and_moved_blocks() -> None:
    old = _po()
    new = copy.deepcopy(old)
    new["body"] = [b for b in new["body"] if b["id"] != "notes"]
    _block(new, "terms")["hidden"] = True
    new["body"].insert(0, new["body"].pop(new["body"].index(_block(new, "signatures"))))
    new["body"].append({"id": "intro", "type": "text", "hidden": False, "text": {"en": "Hi"}})
    new["page"] = {"size": "Letter", "orientation": "portrait"}
    changes = {(c["id"], c["change"]) for c in diff_templates(old, new)}
    assert {("notes", "removed"), ("terms", "changed"), ("intro", "added"), ("page", "changed")} <= changes
    assert ("signatures", "moved") in changes


# ── Validation rules ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_layout_rules_run_through_the_validation_registry() -> None:
    from app.core.validation.engine import ValidationContext, rule_registry
    from app.modules.doc_templates.validators import register_doc_template_rules
    from app.modules.procurement.layouts import register_procurement_layouts

    register_doc_template_rules()
    register_procurement_layouts()
    template = _po()
    _block(template, "line_items")["hidden"] = True
    rule = rule_registry.get_rule("doctpl.required_section_hidden")
    results = await rule.validate(
        ValidationContext(data={"layout": PURCHASE_ORDER.key, "template": template}, standard="doc_templates")
    )
    assert [r.element_ref for r in results if not r.passed] == ["line_items"]
