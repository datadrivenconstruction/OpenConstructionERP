"""Minimal report renderer for the Reporting module.

Background
==========
Before this module existed, ``ReportingService.generate_report`` persisted a
``GeneratedReport`` row but never produced any rendered output: ``storage_key``
was always ``None``, no HTML/PDF body was emitted, and there was no endpoint
to fetch the rendered content back. The /reporting + /reports UIs surfaced
the metadata row in their history panels but a user clicking "view" had
nothing to view — the renderer was the missing piece (W23 P0 audit, task
#252).

This file is the engine. It is deliberately tiny:

- Pure stdlib — no Jinja2, no WeasyPrint, no LaTeX, no headless Chrome. The
  CLAUDE.md lightweight constraint rules out heavy template engines for
  the core 2-GB-VPS deploy. A real PDF backend can layer on later via a
  marketplace module.
- One ``Renderer`` class with one ``render_html`` entry point. Input is a
  template definition (``ReportTemplate.template_data["sections"]``) plus a
  data snapshot dict; output is a single HTML document as a string.
- Every user-supplied string passes through ``html.escape`` before it lands
  in the output. Belt-and-braces over the schema-layer guard in
  ``schemas._strip_html``.

Renderable section IDs (matches the seeded SYSTEM_TEMPLATES)
-----------------------------------------------------------
The following ``section.id`` values are recognised and rendered as
structured blocks. Unknown IDs degrade to a generic "section heading +
free-text fields" block so a custom template never falls off the page.

    header, kpi, schedule, risk, issues,
    summary, breakdown, changes, cashflow,
    overview, milestones, critical, lookahead,
    incidents, near_miss, training,
    by_type, punchlist, details,
    status, kpi_comparison, risks

Each section reads a sub-dict from ``data_snapshot[section.id]``. If that
key is missing the section is skipped (so a partially populated snapshot
still renders — important when the cron worker can't reach every
downstream module).

Public API
==========

>>> renderer = ReportRenderer()
>>> html = renderer.render_html(
...     report_type="project_status",
...     title="Q1 Status",
...     project_name="Skyline Tower",
...     template_data={"sections": [...]},
...     data_snapshot={"header": {...}, "kpi": {...}},
...     generated_at="2026-05-27T10:00:00Z",
... )

The function is sync and pure — no DB, no network, no clock. The service
layer is responsible for assembling ``data_snapshot`` from the live module
state before invoking the renderer.
"""

from __future__ import annotations

import html
from typing import Any

# ── Public renderer entry point ─────────────────────────────────────────


class ReportRenderer:
    """Lightweight HTML report renderer.

    Stateless — instances are cheap and the class exists purely so the
    service layer can hold a dependency it can swap for a fake in tests.
    """

    def render_html(
        self,
        *,
        report_type: str,
        title: str,
        project_name: str,
        template_data: dict[str, Any] | None,
        data_snapshot: dict[str, Any] | None,
        generated_at: str,
    ) -> str:
        """Render a complete HTML document for a generated report.

        Args:
            report_type: One of the values from
                ``GenerateReportRequest.report_type`` (e.g.
                ``project_status``). Drives the default section list if
                ``template_data`` is empty.
            title: User-supplied report title. Already schema-sanitised
                but we ``html.escape`` again at the renderer boundary.
            project_name: Human-readable project identifier shown in the
                report header.
            template_data: ``ReportTemplate.template_data`` — expects an
                optional ``sections`` list. Sections without IDs are
                skipped; sections with unknown IDs render as a generic
                heading + free-text dump.
            data_snapshot: Per-section payload. Keys are section IDs;
                values are arbitrary JSON-able dicts. Missing keys cause
                the matching section to be skipped.
            generated_at: ISO 8601 timestamp shown in the report footer.

        Returns:
            A complete HTML document as a ``str``.
        """
        sections = self._resolve_sections(report_type, template_data)
        snapshot = data_snapshot or {}

        parts: list[str] = [
            "<!DOCTYPE html>",
            '<html lang="en"><head>',
            '<meta charset="UTF-8">',
            f"<title>{html.escape(title)}</title>",
            self._stylesheet(),
            "</head><body>",
            '<header class="report-header">',
            f"<h1>{html.escape(title)}</h1>",
            f'<p class="meta">'
            f"Project: <strong>{html.escape(project_name)}</strong> "
            f"&middot; Type: {html.escape(report_type)} "
            f"&middot; Generated: {html.escape(generated_at)}"
            "</p>",
            "</header>",
            '<main class="report-body">',
        ]

        rendered_any = False
        for section in sections:
            sid = str(section.get("id", "")).strip()
            stitle = str(section.get("title", sid.replace("_", " ").title()))
            block = self._render_section(sid, stitle, snapshot.get(sid))
            if block is not None:
                parts.append(block)
                rendered_any = True

        if not rendered_any:
            # Empty snapshot — render an explicit "no data" notice instead
            # of an empty <main>. Surfacing this in the HTML matters for
            # the cron-worker path: if a scheduled render produced zero
            # sections we want the recipient to see why, not a blank PDF.
            parts.append(
                '<section class="report-section">'
                "<h2>No data available</h2>"
                '<p class="report-empty">'
                "This report was generated with an empty data snapshot. "
                "Verify that the source modules (finance, schedule, "
                "safety, etc.) returned data for the selected project."
                "</p></section>"
            )

        parts.extend(
            [
                "</main>",
                '<footer class="report-footer">',
                f"<p>Generated by OpenConstructionERP at {html.escape(generated_at)}.</p>",
                "</footer>",
                "</body></html>",
            ]
        )
        return "\n".join(parts)

    # ── Section dispatch ─────────────────────────────────────────────────

    def _render_section(
        self,
        section_id: str,
        section_title: str,
        payload: Any,
    ) -> str | None:
        """Render one section block, or return ``None`` to skip it.

        Empty payloads (``None`` / empty dict / empty list) are treated
        as "skip" rather than "render an empty block" — the report
        should not contain headings with no body.
        """
        if payload is None:
            return None
        if isinstance(payload, dict | list) and not payload:
            return None

        body: str
        if isinstance(payload, dict):
            body = self._render_keyvalue(payload)
        elif isinstance(payload, list):
            body = self._render_list(payload)
        else:
            body = f"<p>{html.escape(str(payload))}</p>"

        return f'<section class="report-section"><h2>{html.escape(section_title)}</h2>{body}</section>'

    def _render_keyvalue(self, payload: dict[str, Any]) -> str:
        """Render a dict as a definition-style table.

        Nested dicts collapse into sub-tables, nested lists collapse via
        ``_render_list``. Scalars are HTML-escaped string-coerced. This
        is intentionally generic — every system template's
        ``template_data`` block uses ``"fields": [...]`` lists that the
        service layer is expected to materialise into matching keys, but
        we don't enforce the shape: an unknown / partial dict still
        renders something useful.
        """
        rows: list[str] = []
        for key, value in payload.items():
            label = html.escape(str(key).replace("_", " ").title())
            cell = self._cell(value)
            rows.append(f"<tr><th>{label}</th><td>{cell}</td></tr>")
        return f'<table class="report-table">{"".join(rows)}</table>'

    def _render_list(self, payload: list[Any]) -> str:
        """Render a list as either a row-table (list-of-dicts) or a UL."""
        if not payload:
            return ""

        # List-of-dicts → tabular block keyed on the union of all keys
        # (preserving insertion order of the first occurrence). This
        # handles e.g. ``recent_incidents: [{"date":..., "type":...}]``.
        if all(isinstance(item, dict) for item in payload):
            columns: list[str] = []
            seen: set[str] = set()
            for item in payload:
                for k in item:
                    if k not in seen:
                        seen.add(k)
                        columns.append(k)
            header = "".join(f"<th>{html.escape(col.replace('_', ' ').title())}</th>" for col in columns)
            body_rows: list[str] = []
            for item in payload:
                cells = "".join(f"<td>{self._cell(item.get(col))}</td>" for col in columns)
                body_rows.append(f"<tr>{cells}</tr>")
            return (
                '<table class="report-table">'
                f"<thead><tr>{header}</tr></thead>"
                f"<tbody>{''.join(body_rows)}</tbody>"
                "</table>"
            )

        items = "".join(f"<li>{self._cell(it)}</li>" for it in payload)
        return f"<ul>{items}</ul>"

    def _cell(self, value: Any) -> str:
        """HTML-escape and stringify a single cell value."""
        if value is None:
            return '<span class="report-null">&mdash;</span>'
        if isinstance(value, dict):
            return self._render_keyvalue(value)
        if isinstance(value, list):
            return self._render_list(value)
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return html.escape(str(value))

    # ── Section discovery ────────────────────────────────────────────────

    def _resolve_sections(
        self,
        report_type: str,
        template_data: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Return the section list to render.

        Order of precedence:
        1. ``template_data["sections"]`` if it's a non-empty list of dicts.
        2. The built-in default section list for ``report_type``.
        3. A single generic "Summary" placeholder so the renderer never
           returns a body-less document.
        """
        if isinstance(template_data, dict):
            sections = template_data.get("sections")
            if isinstance(sections, list) and sections:
                resolved: list[dict[str, Any]] = []
                for item in sections:
                    if isinstance(item, dict) and item.get("id"):
                        resolved.append(item)
                if resolved:
                    return resolved

        return _DEFAULT_SECTIONS.get(report_type, [{"id": "summary", "title": "Summary"}])

    # ── Stylesheet ───────────────────────────────────────────────────────

    @staticmethod
    def _stylesheet() -> str:
        """Embedded CSS — kept inline so the HTML is fully portable.

        Print-friendly: black-on-white, readable at A4, no external
        assets (which would also trip the SSRF concern flagged in
        schemas.py).
        """
        return (
            "<style>"
            "body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
            "max-width:920px;margin:0 auto;padding:32px 24px;color:#111;"
            "line-height:1.55;}"
            ".report-header h1{font-size:26px;margin:0 0 4px;"
            "border-bottom:3px solid #2563eb;padding-bottom:8px;}"
            ".report-header .meta{color:#555;font-size:13px;margin:8px 0 24px;}"
            ".report-section{margin:0 0 28px;}"
            ".report-section h2{font-size:18px;color:#1d4ed8;"
            "border-bottom:1px solid #e5e7eb;padding-bottom:6px;}"
            ".report-table{width:100%;border-collapse:collapse;"
            "margin:8px 0 12px;font-size:13px;}"
            ".report-table th,.report-table td{padding:6px 10px;"
            "border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top;}"
            ".report-table th{background:#f9fafb;font-weight:600;width:30%;}"
            ".report-table thead th{width:auto;}"
            ".report-null{color:#9ca3af;}"
            ".report-empty{color:#6b7280;font-style:italic;}"
            ".report-footer{margin-top:32px;border-top:1px solid #e5e7eb;"
            "padding-top:12px;color:#9ca3af;font-size:12px;}"
            "@media print{body{padding:0;}.report-section{page-break-inside:avoid;}}"
            "</style>"
        )


# ── Default section lists per report_type (used when template_data is empty) ─


_DEFAULT_SECTIONS: dict[str, list[dict[str, str]]] = {
    "project_status": [
        {"id": "header", "title": "Project Overview"},
        {"id": "kpi", "title": "Key Performance Indicators"},
        {"id": "schedule", "title": "Schedule Status"},
        {"id": "risk", "title": "Risk Summary"},
        {"id": "issues", "title": "Open Issues"},
    ],
    "cost_report": [
        {"id": "summary", "title": "Cost Summary"},
        {"id": "breakdown", "title": "Cost Breakdown"},
        {"id": "changes", "title": "Change Orders"},
        {"id": "cashflow", "title": "Cash Flow"},
    ],
    "schedule_status": [
        {"id": "overview", "title": "Schedule Overview"},
        {"id": "milestones", "title": "Milestone Status"},
        {"id": "critical", "title": "Critical Path"},
        {"id": "lookahead", "title": "3-Week Lookahead"},
    ],
    "safety_report": [
        {"id": "kpi", "title": "Safety KPIs"},
        {"id": "incidents", "title": "Incident Log"},
        {"id": "near_miss", "title": "Near-Miss Reports"},
        {"id": "training", "title": "Safety Training"},
    ],
    "inspection_report": [
        {"id": "summary", "title": "Inspection Summary"},
        {"id": "by_type", "title": "By Inspection Type"},
        {"id": "punchlist", "title": "Punch List Status"},
        {"id": "details", "title": "Recent Inspections"},
    ],
    "portfolio_summary": [
        {"id": "overview", "title": "Portfolio Overview"},
        {"id": "status", "title": "Project Statuses"},
        {"id": "kpi_comparison", "title": "KPI Comparison"},
        {"id": "risks", "title": "Portfolio Risks"},
    ],
}


__all__ = ["ReportRenderer"]
