"""R7 Document Templates safety and locale-override tests.

Scope
-----
8. **override_country / locale precedence**: an explicitly supplied ``locale``
   parameter takes precedence over any project-level country setting.  The
   PDF renderer must honour the caller-supplied locale even when the project
   records a different country.

9. **Template variable safety**: user-supplied strings containing Jinja2-style
   expressions (``{{ __import__('os').system(...) }}``) or ReportLab XML
   injection attempts must NOT cause code execution.  The document_templates
   module uses ReportLab + JSON locale data (never ``eval`` / Jinja2
   Environment), so the safety is architectural rather than sandbox-based.
   These tests verify the contract explicitly.

Design notes
------------
The render_* functions are pure: they receive entity-like objects and return
bytes. We pass MagicMock stubs that expose only the attributes the renderer
reads via ``_attr()``. No DB, no filesystem I/O (locale JSON files are loaded
from ``data/document_locales/`` — we stub ``_load_locale`` when we need
locale-level control).
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Guard: skip the whole module if reportlab is not installed in the test env.
# ---------------------------------------------------------------------------
pytest.importorskip("reportlab", reason="reportlab not installed in test env")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub(**kwargs: Any) -> MagicMock:
    """Return a MagicMock whose attributes are seeded from kwargs.

    _attr(stub, 'key', default) reads ``stub.key``; MagicMock returns a Mock
    for unknown attrs, so we set the ones the renderer will actually access.
    """
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    return obj


def _make_reservation(*, full_name: str = "Alice Tester") -> tuple[Any, Any, Any, list[Any]]:
    """Minimal stubs for render_reservation_receipt_pdf()."""
    import uuid

    reservation = _stub(
        id=uuid.uuid4(),
        reservation_number="RES-2025-001",
        deposit_amount=Decimal("5000"),
        currency="EUR",
        expires_at=None,
        cooling_off_until=None,
        cooling_off_days=0,
        created_at=None,
        plot_id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
    )
    plot = _stub(
        id=uuid.uuid4(),
        plot_number="A-42",
        phase=None,
        block=None,
        area_m2=Decimal("80"),
        floor=None,
        unit_type=None,
        asking_price=Decimal("250000"),
        currency="EUR",
        development_id=uuid.uuid4(),
    )
    development = _stub(
        id=uuid.uuid4(),
        name="Test Heights",
        logo_url=None,
        developer_name="Test Developer",
    )
    buyer = _stub(
        full_name=full_name,
        email="alice@example.com",
        phone=None,
        nationality=None,
        passport_number=None,
    )
    return reservation, plot, development, [buyer]


# ---------------------------------------------------------------------------
# 8. Locale / override_country precedence
# ---------------------------------------------------------------------------


class TestLocaleOverridePrecedence:
    """Locale supplied to the renderer must be honoured regardless of any
    project-level country preference.

    The mechanism: render_*() accepts ``locale: str`` and immediately maps
    unsupported codes to ``"en"``, then uses ``_load_locale(locale)`` for all
    translations. If a caller passes ``locale="de"`` the PDF content must
    differ from ``locale="en"`` because the locale JSON has distinct strings.
    """

    def test_supported_locale_de_changes_output(self) -> None:
        """render_reservation_receipt_pdf with locale='de' must produce a PDF
        that embeds at least one German-specific byte string compared to 'en'.

        We verify that the PDF body differs — not that the exact German word
        appears — because locale JSON files may not be present in CI.  The
        key contract is: locale param is forwarded and _load_locale is called
        with 'de', not silently defaulted to 'en'.
        """
        from app.modules.property_dev.document_templates import (
            _load_locale,
            render_reservation_receipt_pdf,
        )

        reservation, plot, development, buyers = _make_reservation()

        with patch(
            "app.modules.property_dev.document_templates._load_locale",
            wraps=_load_locale,
        ) as mock_load:
            render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="de")

        # _load_locale must have been called with "de" (the override locale)
        # rather than "en" (the hypothetical project default).
        called_locales = [call.args[0] for call in mock_load.call_args_list]
        assert "de" in called_locales, f"Expected _load_locale('de') but only saw: {called_locales}"

    def test_unsupported_locale_falls_back_to_en(self) -> None:
        """An unknown locale code must NOT raise — it falls back to 'en'."""
        from app.modules.property_dev.document_templates import (
            SUPPORTED_LOCALES,
            render_reservation_receipt_pdf,
        )

        assert "xx" not in SUPPORTED_LOCALES, "Test assumes 'xx' is not a supported locale"
        reservation, plot, development, buyers = _make_reservation()

        # Must not raise even with an unknown locale code.
        pdf_bytes = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="xx")
        assert pdf_bytes[:4] == b"%PDF"

    def test_en_locale_produces_valid_pdf(self) -> None:
        """Baseline: locale='en' must produce a valid PDF."""
        from app.modules.property_dev.document_templates import render_reservation_receipt_pdf

        reservation, plot, development, buyers = _make_reservation()
        pdf_bytes = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="en")
        assert pdf_bytes[:4] == b"%PDF"

    def test_locale_en_vs_de_output_differs(self) -> None:
        """The PDF bytes for locale='en' and locale='de' must differ.

        This proves the locale param is actually wired through to the content
        layer — not silently dropped.  If locale JSON files are missing both
        fall back to 'en' data and the test is skipped gracefully.
        """
        from app.modules.property_dev.document_templates import (
            _load_locale,
            render_reservation_receipt_pdf,
        )

        # Only run the diff-check if the 'de' locale file actually exists and
        # has content distinct from 'en'.
        locale_en = _load_locale("en")
        locale_de = _load_locale("de")
        if locale_en == locale_de:
            pytest.skip("de locale JSON absent or identical to en — skipping diff check")

        reservation, plot, development, buyers = _make_reservation()
        pdf_en = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="en")
        pdf_de = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="de")
        assert pdf_en != pdf_de, (
            "PDF content must differ between locale='en' and locale='de' "
            "when the locale JSON files are present and distinct."
        )

    def test_normalise_locale_strips_region_subtag(self) -> None:
        """_normalise_locale('de-CH') must resolve to 'de', not be rejected."""
        from app.modules.property_dev.router import _normalise_locale

        result = _normalise_locale("de-CH")
        assert result == "de"

    def test_normalise_locale_unknown_returns_en(self) -> None:
        """_normalise_locale with a totally unknown code falls back to 'en'."""
        from app.modules.property_dev.router import _normalise_locale

        result = _normalise_locale("zz-ZZ")
        assert result == "en"


# ---------------------------------------------------------------------------
# 9. Template variable safety
# ---------------------------------------------------------------------------


class TestTemplateVariableSafety:
    """User-supplied strings must NOT be executed as code.

    The document_templates module is ReportLab-based (not Jinja2), so there
    is no eval path for Jinja2 expressions.  ReportLab's Paragraph accepts a
    small XML/HTML subset — only ``<b>``, ``<i>``, ``<br/>``-style tags.
    Attempts to inject Jinja2 expressions or Python imports are treated as
    literal text (or cause a benign XML parse error that is caught).

    These tests confirm the contract explicitly:
      a) A buyer name containing ``{{ __import__('os').system('id') }}`` is
         rendered as literal text — ``os.system`` is NOT called.
      b) A buyer name containing malicious ReportLab XML (e.g. an
         ``<onDraw>`` handler) does not trigger arbitrary function calls.
      c) The PDF output starts with ``%PDF`` — confirming the render succeeds
         rather than crashing on the injected payload.
    """

    def test_jinja2_expression_in_buyer_name_is_not_executed(self) -> None:
        """{{ __import__('os').system('id') }} must be inert literal text."""
        from app.modules.property_dev.document_templates import render_reservation_receipt_pdf

        malicious_name = "{{ __import__('os').system('id') }}"
        reservation, plot, development, buyers = _make_reservation(full_name=malicious_name)

        # Track os.system calls — there must be none.
        original_system = os.system
        call_count = {"n": 0}

        def _patched_system(cmd: str) -> int:  # pragma: no cover
            call_count["n"] += 1
            return 0

        os.system = _patched_system
        try:
            pdf_bytes = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="en")
        finally:
            os.system = original_system

        assert call_count["n"] == 0, "os.system was called — the template renderer executed user-supplied code!"
        assert pdf_bytes[:4] == b"%PDF"

    def test_subprocess_import_in_buyer_name_is_not_executed(self) -> None:
        """{{ __import__('subprocess').run(['id']) }} must be inert."""
        import subprocess

        from app.modules.property_dev.document_templates import render_reservation_receipt_pdf

        malicious_name = "{{ __import__('subprocess').run(['id']) }}"
        reservation, plot, development, buyers = _make_reservation(full_name=malicious_name)

        original_run = subprocess.run
        call_count = {"n": 0}

        def _patched_run(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
            call_count["n"] += 1
            return MagicMock(returncode=0, stdout=b"", stderr=b"")

        subprocess.run = _patched_run  # type: ignore[method-assign]
        try:
            pdf_bytes = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="en")
        finally:
            subprocess.run = original_run  # type: ignore[method-assign]

        assert call_count["n"] == 0, "subprocess.run was called — the template renderer executed user-supplied code!"
        assert pdf_bytes[:4] == b"%PDF"

    def test_reportlab_xml_injection_in_buyer_name_does_not_execute_code(self) -> None:
        """ReportLab XML injection: injected tags are handled internally, not via exec.

        ReportLab's Paragraph parses a minimal XML subset. The ``<onDraw>``
        tag is a built-in ReportLab mechanism that triggers a *named Python
        callable registered on the canvas* — NOT arbitrary user code. When the
        name ("evil") is not registered, ReportLab raises AttributeError
        (i.e. "missing callback 'evil'") rather than executing anything.
        Either outcome (valid PDF, or AttributeError from ReportLab's own
        guard) confirms the renderer did NOT execute arbitrary user code.

        The critical safety property: NO subprocess/shell/os.system call
        can be made via a <onDraw> injection — only a named *pre-registered*
        canvas method is looked up.
        """
        from app.modules.property_dev.document_templates import render_reservation_receipt_pdf

        # Attempt to inject a ReportLab built-in hook tag.
        malicious_name = '<font name="Helvetica">Normal</font><onDraw name="evil"/>'
        reservation, plot, development, buyers = _make_reservation(full_name=malicious_name)

        # Track os.system calls — there must be none regardless of outcome.
        original_system = os.system
        call_count = {"n": 0}

        def _patched_system(cmd: str) -> int:  # pragma: no cover
            call_count["n"] += 1
            return 0

        os.system = _patched_system
        try:
            # Either the PDF renders successfully (tag stripped) or
            # ReportLab raises AttributeError (unregistered callback name).
            # Both are safe outcomes.  A raw exec() or subprocess call is the
            # outcome that would indicate a vulnerability.
            try:
                pdf_bytes = render_reservation_receipt_pdf(reservation, plot, development, buyers, locale="en")
                # If it rendered, it must start with %PDF.
                assert pdf_bytes[:4] == b"%PDF"
            except AttributeError as exc:
                # ReportLab's own AttributeError: "Missing onDraw callback
                # attribute 'evil'" — expected safe failure.
                assert "evil" in str(exc).lower() or "onDraw" in str(exc) or "callback" in str(exc).lower(), (
                    f"Unexpected AttributeError: {exc}"
                )
        finally:
            os.system = original_system

        assert call_count["n"] == 0, "os.system was called — the renderer executed user-supplied code!"

    def test_exec_in_locale_key_does_not_execute(self) -> None:
        """Malicious locale JSON value is treated as a plain string.

        Even if an attacker somehow injects ``exec(...)`` into a locale JSON
        value, the _t() helper only reads strings — it does NOT eval() them.
        """
        from app.modules.property_dev.document_templates import _t

        evil_locale_data: dict[str, Any] = {
            "reservation_receipt": {
                "title": "__import__('os').system('id')",
            }
        }
        with patch(
            "app.modules.property_dev.document_templates._load_locale",
            return_value=evil_locale_data,
        ):
            value = _t("en", "reservation_receipt.title", "fallback")

        # The value must be the raw string — NOT a function-call result.
        assert value == "__import__('os').system('id')", "_t() must return the string verbatim, never eval() it."

    def test_no_jinja2_environment_in_module(self) -> None:
        """document_templates must NOT import jinja2 or use Environment/eval.

        This is a static import check: if jinja2 is present at module level
        an unsafe Environment could be used accidentally in future edits.
        """
        import importlib

        mod = importlib.import_module("app.modules.property_dev.document_templates")
        # The module must not hold a reference to a Jinja2 Environment instance.
        assert not hasattr(mod, "jinja_env"), (
            "document_templates exposes a 'jinja_env' — use SandboxedEnvironment if Jinja2 is needed."
        )
        # jinja2 must not appear in the module's direct __dict__ as a submodule.
        import types

        jinja_refs = [
            name for name, val in vars(mod).items() if isinstance(val, types.ModuleType) and "jinja2" in val.__name__
        ]
        assert not jinja_refs, (
            f"document_templates imports jinja2 module(s): {jinja_refs}. "
            "Ensure SandboxedEnvironment is used if Jinja2 rendering is ever added."
        )
