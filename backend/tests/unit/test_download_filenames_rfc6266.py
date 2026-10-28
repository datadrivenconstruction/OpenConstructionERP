"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The download-filename sweep: converted sites must not mangle non-ASCII names.

One shared regression class, many endpoints: export routes used to build
``Content-Disposition`` from ``name.encode("ascii", errors="replace")`` (or fed
a raw user string into an f-string header), so "Bürogebäude Prüfung.pdf"
reached the browser as ``B?rogeb?ude Pr?fung.pdf`` and was saved with
underscores. Every converted site now routes the finished filename through
:func:`app.core.content_disposition.attachment_disposition`, which emits the
RFC 6266 pair. Inline dispositions used to come from a second helper with its
own ASCII fallback; it was folded into this one, which is why the guard below
names a single function.

Covered here:
    * the per-module filename builders that used to do the mangling keep the
      real characters now, and are byte-identical to before for ASCII input;
    * representative converted names produce both header parameters;
    * a closed-set source guard over every converted file - the mangle pattern
      cannot quietly return, and each header-building file still calls a
      shared helper.
"""

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from app.core.content_disposition import attachment_disposition

APP_DIR = Path(__file__).resolve().parents[2] / "app"

# Files whose Content-Disposition headers were converted to a shared helper.
# Each must call one of the helpers and must not contain the mangle pattern.
_HEADER_FILES = [
    "modules/boq/router.py",
    "modules/bimlv/router.py",
    "modules/validation/router.py",
    "modules/methodology/router.py",
    "modules/finance/router.py",
    "modules/finance/invoice_capture_router.py",
    "modules/reporting/router.py",
    "modules/estimate_basis/router.py",
    "modules/clash/router.py",
    "modules/contracts/router.py",
    "modules/takeoff/router.py",
    "modules/requirements/router.py",
    "modules/bim_requirements/router.py",
    "modules/meetings/router.py",
    "modules/record_publishing/router.py",
    "modules/file_transmittals/router.py",
    "modules/projects/router.py",
    "modules/property_dev/router.py",
]

# Files that only build the download name (the header lives in a router above);
# the mangle pattern must be gone from these too.
_NAME_BUILDER_FILES = [
    "modules/bimlv/service.py",
    "modules/einvoice/service.py",
    "modules/methodology/service.py",
    "modules/reporting/exporters.py",
]

# property_dev/router.py keeps interpolated attachment headers whose names are
# ASCII by construction (an enum-mapped doc type + uuid hex, a validated
# regulator code + quarter, a service-slugged plot number); every other
# converted file must have zero interpolated Content-Disposition left.
_INTERPOLATION_EXEMPT = {"modules/property_dev/router.py"}


# ── The filename builders keep real characters, unchanged for ASCII ────────


def test_methodology_export_filename_keeps_umlauts_and_ascii_behaviour():
    from app.modules.methodology.service import MethodologyService

    assert MethodologyService.export_filename({"methodology_name": "Bürogebäude Prüfung"}, "pdf") == (
        "Bürogebäude Prüfung.pdf"
    )
    # ASCII input is byte-identical to the pre-sweep output.
    assert MethodologyService.export_filename({"methodology_name": "Steel frame estimate"}, "xlsx") == (
        "Steel frame estimate.xlsx"
    )
    assert MethodologyService.export_filename({}, "pdf") == "methodology.pdf"


def test_einvoice_safe_token_keeps_umlauts_and_stays_single_line():
    from app.modules.einvoice.service import _safe_token

    assert _safe_token("RE-Bürogebäude 2026") == "RE-Bürogebäude_2026"
    # ASCII behaviour is unchanged: quote swap, slash swap, space swap.
    assert _safe_token('INV/2026 "A"') == "INV-2026_'A'"
    assert _safe_token("NR\r\n01") == "NR01"
    assert _safe_token("") == "invoice"
    assert len(_safe_token("Ä" * 200)) == 80


def test_reporting_safe_filename_keeps_umlauts_and_ascii_behaviour():
    from app.modules.reporting.exporters import _safe_filename

    assert _safe_filename("Kostenbericht Bürogebäude") == "Kostenbericht Bürogebäude"
    # ASCII input is byte-identical to the pre-sweep output.
    assert _safe_filename("Cost / Report") == "Cost - Report"
    assert _safe_filename("a\r\n\tb") == "ab"
    assert _safe_filename("") == "report"


def test_validation_export_filename_keeps_umlauts_and_ascii_behaviour():
    from app.modules.validation.router import _export_filename

    report = SimpleNamespace(target_id="Bürogebäude/LV-1", id="unused")
    assert _export_filename(report, "csv") == "validation_Bürogebäude-LV-1.csv"
    # ASCII input (the usual UUID-shaped target) is byte-identical to before.
    ascii_report = SimpleNamespace(target_id="8c9f2a4e-1111-2222-3333-444455556666", id="unused")
    assert _export_filename(ascii_report, "xlsx") == "validation_8c9f2a4e-1111-2222-3333-444455556666.xlsx"
    # Control characters still cannot reach the header line.
    crlf_report = SimpleNamespace(target_id="evil\r\nX-Inject: 1", id="unused")
    name = _export_filename(crlf_report, "csv")
    assert "\r" not in name and "\n" not in name


# ── Every converted name yields the RFC 6266 pair ──────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "Bürogebäude Prüfung.pdf",  # boq / methodology shape
        "Bürogebäude Prüfung.bimlv",  # bimlv container
        "validation_Bürogebäude-LV-1.csv",  # validation export
        "einvoice_RE-Bürogebäude_2026_xrechnung.xml",  # einvoice via finance
        "RPS_NF-São-Paulo-0042.pdf",  # finance Brazil RPS
        "Kostenbericht Bürogebäude.xlsx",  # reporting
        "basis_of_estimate_Anbau_Süd.md",  # estimate basis
        "clash_Türen_gegen_Lüftung.csv",  # clash run
        "transmittal_TRN-Übergabe-01.pdf",  # file transmittals
        "meeting_M-007_Baubesprechung_Köln.pdf",  # meetings
    ],
)
def test_converted_download_names_produce_both_header_parameters(name: str):
    header = attachment_disposition(name)
    assert header.startswith('attachment; filename="')
    assert "filename*=UTF-8''" in header
    # The fallback parameter never carries the old question marks.
    fallback = header.split('filename="', 1)[1].split('"', 1)[0]
    assert "?" not in fallback
    # The real name round-trips through the RFC 5987 parameter.
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == name


def test_pure_ascii_names_keep_their_exact_fallback_bytes():
    """The ``filename="..."`` parameter is what pre-sweep headers pinned."""
    header = attachment_disposition("RPS_INV-2026-01.pdf")
    assert header.startswith('attachment; filename="RPS_INV-2026-01.pdf"')

    inline = attachment_disposition("scan_0042.pdf", inline=True)
    assert inline.startswith('inline; filename="scan_0042.pdf"')


# ── Closed-set source guard over the converted files ───────────────────────


@pytest.mark.parametrize("rel", _HEADER_FILES + _NAME_BUILDER_FILES)
def test_the_ascii_mangle_cannot_return_to_a_converted_file(rel: str):
    text = (APP_DIR / rel).read_text(encoding="utf-8")
    assert 'encode("ascii", errors="replace")' not in text, rel
    assert 'encode("ascii", "replace")' not in text, rel


@pytest.mark.parametrize("rel", _HEADER_FILES)
def test_each_converted_header_file_calls_a_shared_disposition_helper(rel: str):
    text = (APP_DIR / rel).read_text(encoding="utf-8")
    assert "attachment_disposition(" in text, rel


@pytest.mark.parametrize("rel", [f for f in _HEADER_FILES if f not in _INTERPOLATION_EXEMPT])
def test_no_interpolated_disposition_header_remains(rel: str):
    text = (APP_DIR / rel).read_text(encoding="utf-8")
    assert "f'attachment; filename=" not in text, rel
    assert 'f"attachment; filename=' not in text, rel
    assert "f'inline; filename=" not in text, rel
    assert 'f"inline; filename=' not in text, rel
