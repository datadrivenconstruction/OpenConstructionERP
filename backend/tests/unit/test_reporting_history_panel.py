"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wave V_REPORTING — backend invariants the new history panel relies on.

The frontend ``<GeneratedReportsHistory>`` hits
``GET /api/v1/reporting/reports/?project_id=X&limit=10`` and renders
``title``/``report_type``/``format``/``created_at``. These tests pin
the schema layer's HTML-strip guard and the response-field contract so
neither can regress without a red test.
"""

from __future__ import annotations

import uuid

from app.modules.reporting.schemas import (
    GeneratedReportResponse,
    GenerateReportRequest,
    ReportTemplateCreate,
)

PROJECT_ID = uuid.uuid4()


def test_generate_report_title_strips_script_tags() -> None:
    """Sanitiser MUST swallow ``<script>...</script>`` so future
    renderers that forget ``{{ value | e }}`` can't execute it.
    """
    req = GenerateReportRequest(
        project_id=PROJECT_ID,
        report_type="cost_report",
        title='<script>alert("xss")</script>Q1 costs',
        format="pdf",
    )
    assert "<script>" not in req.title
    assert req.title.endswith("Q1 costs")


def test_generate_report_title_strips_raw_brackets() -> None:
    """Anything between ``<`` and ``>`` is eaten as a tag. Raw HTML
    brackets MUST NOT survive into downstream PDF/HTML renderers."""
    req = GenerateReportRequest(
        project_id=PROJECT_ID,
        report_type="cost_report",
        title="<b>bold</b> safe text",
        format="pdf",
    )
    assert "<" not in req.title
    assert ">" not in req.title
    assert "safe text" in req.title


def test_template_name_and_description_are_sanitised() -> None:
    tmpl = ReportTemplateCreate(
        name="<img src=x onerror=alert(1)>Quarterly",
        report_type="cost_report",
        description="<b>Bold</b> and <script>bad()</script>",
    )
    assert "<img" not in tmpl.name
    assert "Quarterly" in tmpl.name
    assert "<script>" not in (tmpl.description or "")


def test_generated_report_response_exposes_panel_fields() -> None:
    """Contract test: if a backend rename drops one of these fields the
    panel goes blank in production. Flip red here first."""
    panel_required = {"id", "project_id", "report_type", "title", "format", "created_at"}
    schema_fields = set(GeneratedReportResponse.model_fields.keys())
    missing = panel_required - schema_fields
    assert not missing, f"missing fields: {missing}"
