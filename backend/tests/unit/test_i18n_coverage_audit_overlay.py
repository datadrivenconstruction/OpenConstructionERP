# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The coverage audit measures a regional variant against its base language.

en-US, es-MX, es-CL, es-CO and pt-BR carry only the words that differ from en,
es and pt. Every other key is answered by the base file, and a reader of the
variant sees their own language. scripts/audit_i18n_coverage.py used to compare
all 43 locale files against en.ts, so it reported the one deliberate overlay we
own as 33643 keys short and printed RED beside it. That line is an instruction
to destroy the overlay: the cheapest way to make it go away is to paste a full
copy of English into en-US.ts, which is exactly what the orphan guard's own
history warns about.

Both directions are asserted here, because the cheap way to stop printing the
false line is to stop looking at variants at all, and that tool would be just
as wrong. A variant covered by its base must be clean, a base that is genuinely
missing a key must still be caught in the base AND in the variant riding on it,
and a language that is nobody's variant must stay measured against English.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_AUDIT = Path(__file__).resolve().parents[3] / "scripts" / "audit_i18n_coverage.py"
_spec = importlib.util.spec_from_file_location("audit_i18n_coverage", _AUDIT)
assert _spec and _spec.loader, f"audit script not found at {_AUDIT}"
audit = importlib.util.module_from_spec(_spec)
sys.modules["audit_i18n_coverage"] = audit
_spec.loader.exec_module(audit)


def _write_locale(path: Path, pairs: dict[str, str]) -> None:
    """A locale file in the shape the audit's line reader expects."""
    lines = ["const resource = {", '  "translation": {']
    lines += [f'    "{key}": "{value}",' for key, value in pairs.items()]
    lines += ["  },", "};", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_the_variant_rule_is_imported_not_restated() -> None:
    """One definition of "which file answers a variant", not two.

    Two copies of this rule would drift, and the drift is silent because each
    copy reads correctly on its own.
    """
    assert audit.base_of.__module__ == "check_i18n_orphan_keys"


def test_a_key_the_base_answers_is_not_missing_from_the_variant() -> None:
    en = {"boq.title", "boq.total"}
    assert audit.unanswered_keys(en, loc_keys=set(), base_keys=en) == []


def test_a_key_neither_file_answers_is_still_missing() -> None:
    """The negative control: silencing the false positive must not silence this."""
    en = {"boq.title", "boq.total"}
    assert audit.unanswered_keys(en, loc_keys=set(), base_keys={"boq.title"}) == ["boq.total"]


def test_a_language_with_no_base_is_measured_against_english() -> None:
    """en.ts answering a key is not coverage; it is the fallback being counted."""
    en = {"boq.title"}
    assert audit.unanswered_keys(en, loc_keys=set(), base_keys=None) == ["boq.title"]


def test_the_variant_keeps_its_own_words_and_inherits_the_rest() -> None:
    en = {"boq.title", "boq.total"}
    assert audit.unanswered_keys(en, loc_keys={"boq.total"}, base_keys={"boq.title"}) == []


def test_the_report_clears_the_overlay_and_still_names_the_real_gap(tmp_path, monkeypatch) -> None:
    """End to end, on a tree built to contain one overlay and one real gap.

    es answers everything en does except boq.total, so that key is a genuine
    hole for every Spanish reader including the Mexican one. es-MX says one
    thing its own way, repeats es once for nothing, and inherits the rest,
    which is every column this report has to tell apart.
    """
    locales = tmp_path / "locales"
    locales.mkdir()
    _write_locale(
        locales / "en.ts",
        {
            "boq.title": "Bill of quantities",
            "boq.total": "Total",
            "boq.unit": "Unit",
            "boq.qty": "Quantity",
        },
    )
    _write_locale(
        locales / "es.ts",
        {"boq.title": "Presupuesto", "boq.unit": "Unidad", "boq.qty": "Cantidad"},
    )
    _write_locale(
        locales / "es-MX.ts",
        {"boq.title": "Catalogo de conceptos", "boq.qty": "Cantidad"},
    )
    report = tmp_path / "report.txt"
    monkeypatch.setattr(audit, "LOCALES_DIR", locales)
    monkeypatch.setattr(audit, "REPORT_PATH", report)

    audit.main()
    text = report.read_text(encoding="utf-8")

    # The overlay is not short of boq.unit, which it never declares and does
    # not need to, and its repeat of boq.qty is counted as carrying nothing
    # rather than as work anyone has to do.
    assert (
        "es-MX: 2 own keys, 1 of them (50.0%) repeating what es already "
        "resolves to and carrying nothing, 1 more inherited from es, "
        "1 answered by nobody" in text
    )
    # The real gap survives, in the base and in the variant riding on it.
    assert "### es (1 missing" in text
    assert "### es-MX (1 missing" in text
    assert "boq.total" in text
    # And the variant was measured, not skipped. A tool that ignored variants
    # would also stop printing a false line, and would be just as wrong.
    assert "es-MX via es" in text
    row = next(line for line in text.splitlines() if line.startswith("es-MX "))
    assert row.split()[1] == "es", f"the summary table lost the base column: {row!r}"


def test_a_repeat_of_a_key_english_does_not_have_still_counts_as_redundant(tmp_path, monkeypatch) -> None:
    """Redundancy is judged against the chain, not against English's key set.

    Spanish needs plural forms English has no word for, so es.ts carries
    thousands of keys en.ts does not. An es-MX line repeating one of those
    carries exactly as little as any other repeat, but scoping the check to
    keys en happens to have would score it as translation work. That
    undercounted each Spanish variant by roughly 3700 lines, and the number it
    printed was the one a reader would use to decide whether the overlay is
    real.
    """
    locales = tmp_path / "locales"
    locales.mkdir()
    _write_locale(locales / "en.ts", {"boq.title": "Bill of quantities"})
    _write_locale(
        locales / "es.ts",
        {"boq.title": "Presupuesto", "boq.count_many": "%s partidas"},
    )
    _write_locale(
        locales / "es-MX.ts",
        {"boq.title": "Presupuesto", "boq.count_many": "%s partidas"},
    )
    report = tmp_path / "report.txt"
    monkeypatch.setattr(audit, "LOCALES_DIR", locales)
    monkeypatch.setattr(audit, "REPORT_PATH", report)

    audit.main()
    text = report.read_text(encoding="utf-8")

    assert "es-MX: 2 own keys, 2 of them (100.0%) repeating what es already resolves to" in text
    assert "On disk this file is a copy of its base." in text


def test_a_base_that_parses_to_nothing_is_refused(tmp_path, monkeypatch) -> None:
    """The quiet way this whole fix reverts.

    Keys are found by a line regex, not by parsing TypeScript. A base file
    written in some other shape parses to nothing, answers nothing, and every
    variant riding on it goes back to being measured against English, printing
    the same false tens of thousands with nothing on the page saying why. An
    empty parse is a broken scan, not a clean one.
    """
    locales = tmp_path / "locales"
    locales.mkdir()
    _write_locale(locales / "en.ts", {"boq.title": "Bill of quantities"})
    (locales / "es.ts").write_text(
        "const resource = {\n  'translation': {\n    'boq.title': 'Presupuesto',\n  }\n};\n",
        encoding="utf-8",
    )
    _write_locale(locales / "es-MX.ts", {"boq.title": "Catalogo de conceptos"})
    monkeypatch.setattr(audit, "LOCALES_DIR", locales)
    monkeypatch.setattr(audit, "REPORT_PATH", tmp_path / "report.txt")

    with pytest.raises(SystemExit, match="parsed to zero keys"):
        audit.main()


def test_the_report_records_what_it_was_measured_on(tmp_path, monkeypatch) -> None:
    """Locale files are edited by several people at once, so a count here is an
    instant, not a settled state. Without a basis the file reads as current
    forever."""
    locales = tmp_path / "locales"
    locales.mkdir()
    _write_locale(locales / "en.ts", {"boq.title": "Bill of quantities"})
    _write_locale(locales / "de.ts", {"boq.title": "Leistungsverzeichnis"})
    report = tmp_path / "report.txt"
    monkeypatch.setattr(audit, "LOCALES_DIR", locales)
    monkeypatch.setattr(audit, "REPORT_PATH", report)

    audit.main()
    text = report.read_text(encoding="utf-8")

    assert "## Basis" in text
    assert "Repo commit:" in text
    assert "Locale input digest:" in text
