# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-free unit tests for sheet-completeness reconciliation (item #46).

Covers the pure parse + normalize + set-diff core in
``documents.sheet_index`` and the three ``sheet_completeness`` validation
rules that read a pre-computed expected/actual diff off the context. Nothing
here touches the database or the FastAPI app, so it runs standalone with
``pytest <file> -q``. The one PDF-table test is guarded with
``importorskip("reportlab")`` so the meaningful reconciliation gate still runs
where PDF generation is unavailable.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext, rule_registry
from app.core.validation.messages import is_key_present, reload_bundle, translate
from app.core.validation.rules import (
    SheetCompletenessExtra,
    SheetCompletenessMissing,
    SheetRevisionMismatch,
    register_builtin_rules,
)
from app.modules.documents.sheet_index import (
    ExpectedSheet,
    normalize_sheet_number,
    parse_index_tables,
    parse_pasted_index,
    reconcile,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _exp(number: str, rev: str | None = None, title: str | None = None) -> dict:
    """An expected-sheet dict in the exact shape the service hands the engine."""
    return ExpectedSheet(number, normalize_sheet_number(number), title, rev).__dict__


def _act(number: str | None, rev: str | None = None, id_: str = "sheet-x") -> dict:
    """An actual ``Sheet`` row dict as the service builds it."""
    return {
        "id": id_,
        "sheet_number": number,
        "revision": rev,
        "sheet_title": None,
        "discipline": None,
        "page_number": 1,
    }


def _ctx(expected: list[dict], actual: list[dict], **metadata: object) -> ValidationContext:
    return ValidationContext(data={"expected": expected, "actual": actual}, metadata=metadata)


# ── normalize_sheet_number ──────────────────────────────────────────────────


class TestNormalize:
    def test_normalize_sheet_number_variants(self) -> None:
        # Style-only differences collapse to one key.
        assert (
            normalize_sheet_number("A-101")
            == normalize_sheet_number("A 101")
            == normalize_sheet_number("a.101")
            == normalize_sheet_number(" A101 ")
            == "A101"
        )

    def test_distinct_numbers_stay_distinct(self) -> None:
        assert normalize_sheet_number("A-101") != normalize_sheet_number("A-102")
        assert normalize_sheet_number("A-101") != normalize_sheet_number("S-101")

    def test_blank_and_none(self) -> None:
        assert normalize_sheet_number(None) == ""
        assert normalize_sheet_number("   ") == ""

    def test_leading_zeros_key_like_the_revision_stack(self) -> None:
        # The register stacks A-01 and A-1 as one drawing, so the completeness
        # check has to count them as one sheet too, or it reports missing a
        # sheet the stack shows as present.
        assert normalize_sheet_number("A-01") == normalize_sheet_number("A-1") == normalize_sheet_number("a_001")
        assert normalize_sheet_number("TAV_01") == normalize_sheet_number("TAV-1")
        assert normalize_sheet_number("A-10") != normalize_sheet_number("A-1")

    def test_reconcile_matches_a_number_written_with_leading_zeros(self) -> None:
        # The expected key is recomputed from the number, so a key stored by an
        # older normaliser ("A01") cannot keep the two apart either.
        result = reconcile([ExpectedSheet("A-01", "A01", revision="B")], [_act("A-1", rev="B")])
        assert result.missing == []
        assert result.extra == []
        assert result.matched == ["A-01"]


# ── reconcile ───────────────────────────────────────────────────────────────


class TestReconcile:
    def test_missing(self) -> None:
        result = reconcile(
            [ExpectedSheet("A-101", "A101"), ExpectedSheet("A-204", "A204")],
            [_act("A-101")],
        )
        assert result.missing == ["A-204"]
        assert result.extra == []
        assert result.matched == ["A-101"]

    def test_extra(self) -> None:
        result = reconcile([ExpectedSheet("A-101", "A101")], [_act("A-101"), _act("A-999")])
        assert result.extra == ["A-999"]
        assert result.missing == []

    def test_all_matched(self) -> None:
        expected = [ExpectedSheet("A-101", "A101"), ExpectedSheet("A-102", "A102")]
        result = reconcile(expected, [_act("A-101"), _act("A-102")])
        assert result.missing == []
        assert result.extra == []
        assert result.rev_mismatch == []
        assert len(result.matched) == 2
        assert result.expected_count == 2
        assert result.actual_count == 2

    def test_revision_mismatch(self) -> None:
        result = reconcile([ExpectedSheet("A-101", "A101", revision="C")], [_act("A-101", rev="B")])
        assert result.rev_mismatch == [{"sheet_number": "A-101", "expected_rev": "C", "actual_rev": "B"}]

    def test_revision_equal_is_not_a_mismatch(self) -> None:
        # Case-insensitive, so 'c' == 'C'.
        result = reconcile([ExpectedSheet("A-101", "A101", revision="C")], [_act("A-101", rev="c")])
        assert result.rev_mismatch == []

    def test_revision_missing_on_either_side_is_not_a_mismatch(self) -> None:
        no_actual_rev = reconcile([ExpectedSheet("A-101", "A101", revision="C")], [_act("A-101", rev=None)])
        no_expected_rev = reconcile([ExpectedSheet("A-101", "A101", revision=None)], [_act("A-101", rev="B")])
        assert no_actual_rev.rev_mismatch == []
        assert no_expected_rev.rev_mismatch == []

    def test_normalization_symmetry(self) -> None:
        # Expected 'A-101' and actual 'A101' must match, not read as missing+extra.
        result = reconcile([ExpectedSheet("A-101", "A101")], [_act("A101")])
        assert result.missing == []
        assert result.extra == []
        assert result.matched == ["A-101"]

    def test_unnumbered_actual_is_dropped_from_the_set(self) -> None:
        # A sheet whose number never parsed is not counted as "extra".
        result = reconcile([ExpectedSheet("A-101", "A101")], [_act("A-101"), _act(None)])
        assert result.extra == []
        assert result.actual_count == 1


# ── parse_pasted_index ──────────────────────────────────────────────────────


class TestParsePasted:
    def test_bare_newline_list(self) -> None:
        sheets = parse_pasted_index("A-101\nA-102\nS-201\n")
        assert [s.sheet_number for s in sheets] == ["A-101", "A-102", "S-201"]

    def test_csv_with_title_and_rev(self) -> None:
        sheets = parse_pasted_index("A-101, GA Plan L1, C\nA-102, GA Plan L2, C")
        assert sheets[0].sheet_number == "A-101"
        assert sheets[0].sheet_title == "GA Plan L1"
        assert sheets[0].revision == "C"

    def test_tsv(self) -> None:
        sheets = parse_pasted_index("A-101\tGA Plan L1\tC")
        assert sheets[0].sheet_number == "A-101"
        assert sheets[0].revision == "C"

    def test_inline_revision_token(self) -> None:
        sheets = parse_pasted_index("A-101 Ground Floor Plan Rev C")
        assert sheets[0].sheet_number == "A-101"
        assert sheets[0].revision == "C"

    def test_header_row_is_skipped(self) -> None:
        # First cell has no digit, so the header row drops out.
        sheets = parse_pasted_index("Sheet, Title, Rev\nA-101, GA Plan, C")
        assert [s.sheet_number for s in sheets] == ["A-101"]

    def test_blank_lines_ignored(self) -> None:
        sheets = parse_pasted_index("\n\nA-101\n\n")
        assert [s.sheet_number for s in sheets] == ["A-101"]

    def test_duplicate_numbers_deduped_last_wins(self) -> None:
        sheets = parse_pasted_index("A-101, First, A\nA-101, Second, B")
        assert len(sheets) == 1
        assert sheets[0].sheet_title == "Second"
        assert sheets[0].revision == "B"

    def test_empty_text(self) -> None:
        assert parse_pasted_index("") == []


# ── parse_index_tables (pdfplumber) ─────────────────────────────────────────


class TestParseIndexTables:
    def test_index_table_pdf(self, tmp_path: object) -> None:
        pytest.importorskip("reportlab")
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

        pdf_path = tmp_path / "index.pdf"  # type: ignore[operator]
        rows = [
            ["Sheet No", "Title", "Rev"],
            ["A-101", "GA Plan Level 1", "C"],
            ["A-102", "GA Plan Level 2", "C"],
            ["S-201", "Foundation Plan", "B"],
        ]
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        table = Table(rows)
        table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
        doc.build([table])

        parsed = parse_index_tables(str(pdf_path))
        numbers = {normalize_sheet_number(s.sheet_number) for s in parsed}
        assert {"A101", "A102", "S201"} <= numbers
        by_norm = {normalize_sheet_number(s.sheet_number): s for s in parsed}
        assert by_norm["A101"].revision == "C"
        assert "Foundation" in (by_norm["S201"].sheet_title or "")

    def test_pdf_without_a_table_returns_empty(self, tmp_path: object) -> None:
        pytest.importorskip("reportlab")
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        pdf_path = tmp_path / "prose.pdf"  # type: ignore[operator]
        c = canvas.Canvas(str(pdf_path), pagesize=A4)
        c.drawString(72, 720, "This drawing has no sheet index table on it at all.")
        c.showPage()
        c.save()

        assert parse_index_tables(str(pdf_path)) == []


# ── Validation rules (async, DB-free) ───────────────────────────────────────


class TestRules:
    @pytest.mark.asyncio
    async def test_missing_rule_emits_error(self) -> None:
        rule = SheetCompletenessMissing()
        results = await rule.validate(_ctx([_exp("A-101"), _exp("A-204")], [_act("A-101")]))
        fails = [r for r in results if not r.passed]
        assert len(fails) == 1
        assert fails[0].severity == Severity.ERROR
        assert fails[0].category == RuleCategory.COMPLETENESS
        assert fails[0].element_ref == "A-204"

    @pytest.mark.asyncio
    async def test_extra_rule_emits_warning(self) -> None:
        rule = SheetCompletenessExtra()
        results = await rule.validate(_ctx([_exp("A-101")], [_act("A-101"), _act("A-999")]))
        fails = [r for r in results if not r.passed]
        assert len(fails) == 1
        assert fails[0].severity == Severity.WARNING
        assert fails[0].element_ref == "A-999"

    @pytest.mark.asyncio
    async def test_revision_mismatch_emits_warning(self) -> None:
        rule = SheetRevisionMismatch()
        results = await rule.validate(_ctx([_exp("A-101", rev="C")], [_act("A-101", rev="B")]))
        fails = [r for r in results if not r.passed]
        assert len(fails) == 1
        assert fails[0].severity == Severity.WARNING
        assert fails[0].category == RuleCategory.CONSISTENCY
        assert fails[0].details["expected_rev"] == "C"
        assert fails[0].details["actual_rev"] == "B"

    @pytest.mark.asyncio
    async def test_clean_set_emits_single_pass_row_per_rule(self) -> None:
        expected = [_exp("A-101", rev="C"), _exp("A-102", rev="C")]
        actual = [_act("A-101", rev="C"), _act("A-102", rev="C")]
        for rule in (SheetCompletenessMissing(), SheetCompletenessExtra(), SheetRevisionMismatch()):
            results = await rule.validate(_ctx(expected, actual))
            assert len(results) == 1
            assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_reconcile_result_is_cached_on_context(self) -> None:
        ctx = _ctx([_exp("A-101"), _exp("A-204")], [_act("A-101")])
        await SheetCompletenessMissing().validate(ctx)
        assert "_sc_result" in ctx.metadata
        # A second rule reusing the same context still reads a correct diff.
        extra = await SheetCompletenessExtra().validate(ctx)
        assert all(r.passed for r in extra)


# ── Rule-set registration + i18n coverage ───────────────────────────────────


class TestRegistrationAndMessages:
    def test_rule_set_registered(self) -> None:
        register_builtin_rules()
        assert rule_registry.has_rules("sheet_completeness")
        supported, unsupported = rule_registry.resolve_rule_sets(["sheet_completeness"])
        assert supported == ["sheet_completeness"]
        assert unsupported == []
        ids = {r["rule_id"] for r in rule_registry.list_rules("sheet_completeness")}
        assert ids == {
            "sheet_completeness.missing",
            "sheet_completeness.extra",
            "sheet_completeness.revision_mismatch",
        }

    def test_rule_messages_present_in_every_bundle_locale(self) -> None:
        reload_bundle()
        keys = [
            "sheet_completeness.missing.fail",
            "sheet_completeness.missing.suggestion",
            "sheet_completeness.extra.fail",
            "sheet_completeness.extra.suggestion",
            "sheet_completeness.revision_mismatch.fail",
            "sheet_completeness.revision_mismatch.suggestion",
        ]
        for locale in ("en", "de", "es", "ru"):
            for key in keys:
                assert is_key_present(key, locale), f"{key} missing for {locale}"

    def test_message_interpolation(self) -> None:
        reload_bundle()
        rendered = translate("sheet_completeness.missing.fail", locale="en", sheet="A-101")
        assert "A-101" in rendered
        rev = translate(
            "sheet_completeness.revision_mismatch.fail",
            locale="en",
            sheet="A-101",
            expected_rev="C",
            actual_rev="B",
        )
        assert "A-101" in rev and "C" in rev and "B" in rev
