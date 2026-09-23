# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every route that renders a document declares the language it rendered.

The defect this file exists to stop is not a wrong header, it is an absent one.
``AcceptLanguageMiddleware`` sets ``Content-Language`` on every response with
``setdefault``, so a route that stays silent does not ship an undeclared
document: it ships one labelled with whatever the reader asked for. A German
reader downloading an English tender package receives bytes that say they are
German, and nothing in the request, the response or the archive records that a
fallback happened.

Two tests rather than one, because they fail for opposite reasons.

The first names every rendering route and asserts it declares. It fails when a
declaration is removed, and it is deliberately a list rather than a search, so
that it cannot be weakened by the same predicate bug twice.

The second searches for PDF-serving routes and asserts the search finds nothing
the list does not already hold. It fails when a route is *added*, which is the
case a list alone can never catch, and it is where the sixteenth export lands
the day somebody writes one. Its predicate is deliberately over-broad: a route
that serves a stored file will trip it, and answering that is one line in the
serves-stored list below, which is cheaper than the alternative of a narrow
predicate that quietly misses a real renderer. Three separate predicates written
against the *shape* of these calls have already missed real routes: a literal
media type misses ``media_type=media_type``, a verb list of render/generate/
build misses ``export_report_file``, and keying on a reportlab import misses the
two exports that assemble PDF syntax by hand.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import app as app_pkg

APP_ROOT = pathlib.Path(app_pkg.__file__).resolve().parent


#: Routes that render a document in the request and must declare its language.
#: Each entry is ``module path relative to app/`` -> function name.
RENDERING_ROUTES: dict[str, set[str]] = {
    "core/branding_router.py": {"get_document_appearance_sample", "get_document_type_sample"},
    # The Excel export is not a PDF, but it builds a document in the request, and
    # the search below finds it through a comment that mentions the PDF export.
    # Listing it here rather than narrowing the search keeps the search broad.
    "modules/boq/router.py": {"export_boq_pdf", "export_boq_excel"},
    "modules/contracts/router.py": {"export_aia_application_pdf"},
    "modules/daily_diary/router.py": {"diary_pdf"},
    "modules/einvoice/router.py": {"generate_invoice"},
    "modules/fieldreports/router.py": {"export_pdf"},
    "modules/finance/router.py": {"export_invoice_br_pdf", "export_invoice_einvoice"},
    "modules/forms/router.py": {"export_submission_pdf"},
    "modules/meetings/router.py": {"export_meeting_pdf", "export_minutes_pdf"},
    "modules/methodology/router.py": {"export_methodology_pdf"},
    "modules/property_dev/router.py": {
        "compliance_regulator_report",
        "stream_propdev_document",
        "warranty_claim_pdf",
    },
    "modules/punchlist/router.py": {"export_pdf"},
    "modules/reporting/router.py": {"download_report"},
    "modules/rfi/router.py": {"export_rfi_pdf"},
    "modules/tendering/router.py": {
        "export_award_letter_pdf",
        "export_award_record_pdf",
        "export_rejection_letter_pdf",
        "export_tender_pdf",
    },
}

#: PDF-serving routes that stream bytes somebody else produced. These have no
#: language of their own to declare: the document was rendered elsewhere, or
#: uploaded, and its language is a property of the stored file rather than of
#: this request. Listed so the discovery test below can tell "classified as not
#: ours" apart from "nobody has looked at it yet".
SERVES_STORED_ROUTES: dict[str, set[str]] = {
    "modules/bi_dashboards/router.py": {"download_report_file"},
    "modules/documents/router.py": {"download_document"},
    "modules/file_approvals/router.py": {"download_stamped"},
    "modules/file_transmittals/router.py": {"download_cover"},
    "modules/portal/router.py": {"portal_me_document_content"},
    "modules/property_dev/portal_router.py": {"download_buyer_document"},
    "modules/record_publishing/router.py": {"download_record", "download_record_public"},
    "modules/takeoff/router.py": {"download_document"},
}


def _function_source(path: pathlib.Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
    raise AssertionError(f"{path.name} no longer defines {name}(); update the list in this file")


@pytest.mark.parametrize(
    ("rel", "func"),
    sorted((rel, func) for rel, funcs in RENDERING_ROUTES.items() for func in funcs),
)
def test_a_rendering_route_declares_the_language_it_produced(rel: str, func: str) -> None:
    source = _function_source(APP_ROOT / rel, func)
    assert "Content-Language" in source, (
        f"{rel}::{func} renders a document and sets no Content-Language, so the "
        "Accept-Language middleware will label its bytes with the language the "
        "reader asked for rather than the one they were written in"
    )


def test_no_pdf_route_escapes_classification() -> None:
    """A new PDF route must be classified rather than merely appear."""
    known = {
        f"{rel}::{func}"
        for table in (RENDERING_ROUTES, SERVES_STORED_ROUTES)
        for rel, funcs in table.items()
        for func in funcs
    }

    found: set[str] = set()
    for path in sorted(APP_ROOT.rglob("*router*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        if "pdf" not in src.lower():
            continue
        rel = path.relative_to(APP_ROOT).as_posix()
        lines = src.splitlines()
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            body = "\n".join(lines[node.lineno - 1 : (node.end_lineno or node.lineno)])
            if "Response(" not in body or "pdf" not in body.lower():
                continue
            if "media_type" not in body:
                continue
            found.add(f"{rel}::{node.name}")

    missing = found - known
    assert not missing, (
        "these routes serve a PDF and are in neither list: "
        + ", ".join(sorted(missing))
        + ". Add each to RENDERING_ROUTES if the route builds the document in "
        "the request, or to SERVES_STORED_ROUTES if it streams bytes produced "
        "elsewhere. A route that renders must declare its language."
    )

    stale = {name for name in known if name not in found}
    assert not stale, (
        "these routes are listed but the search no longer finds them, so either "
        "they were removed or the search stopped seeing them: " + ", ".join(sorted(stale))
    )


def test_the_regulator_report_declares_russian_for_the_russian_filing() -> None:
    """The one route whose language is keyed on jurisdiction, not on a literal.

    Reading the field off the report is the whole point: three of the four
    regulator reports are drafted in English and the 214-FZ one is drafted in
    Russian, so a literal would mislabel one of the four for every reader.
    """
    source = (APP_ROOT / "modules/property_dev/regulatory.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    languages: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "RegulatorReport":
            continue
        by_name = {kw.arg: kw.value for kw in node.keywords}
        regulator = by_name.get("regulator")
        language = by_name.get("language")
        assert isinstance(language, ast.Constant), (
            "every RegulatorReport must state the language its prose is in; "
            "a missing one would be labelled by the route instead"
        )
        assert isinstance(regulator, ast.Constant)
        languages[str(regulator.value)] = str(language.value)

    assert languages == {"RERA": "en", "MAHARERA": "en", "214FZ": "ru", "CMA": "en"}

    route = _function_source(APP_ROOT / "modules/property_dev/router.py", "compliance_regulator_report")
    assert "report.language" in route, (
        "the route must read the language off the report rather than repeat a "
        "literal, or the two can drift apart and only the Russian filing will "
        "be wrong"
    )
