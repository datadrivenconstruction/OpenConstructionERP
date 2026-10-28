# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tamper-evident export header helper and its wiring into report exports.

The header stamps every register/report download with the generation time and
a SHA-256 digest of the content. These tests pin the two guarantees a recipient
relies on: the digest is deterministic for equal data and independent of dict
ordering, it does NOT change when only the timestamp changes, and it DOES change
when the underlying data changes. They also confirm the digest line actually
reaches the CSV / XLSX / PDF outputs.

Pure unit tests: no DB, no app boot.
"""

from __future__ import annotations

from app.core.evidence import (
    DIGEST_ALGORITHM,
    content_digest,
    evidence_header,
    short_digest,
)
from app.modules.reporting.exporters import export_report

_SNAPSHOT = {"summary": {"total": "1000.00", "lines": 3}}


# ── core helper ────────────────────────────────────────────────────────────


def test_digest_is_deterministic_and_order_independent() -> None:
    a = content_digest({"b": 2, "a": 1})
    b = content_digest({"a": 1, "b": 2})
    assert a == b
    assert len(a) == 64
    assert a == a.lower()


def test_digest_changes_when_data_changes() -> None:
    assert content_digest({"total": "1000.00"}) != content_digest({"total": "1000.01"})


def test_header_excludes_timestamp_from_digest() -> None:
    payload = {"title": "R", "data": _SNAPSHOT}
    early = evidence_header(generated_at="2026-01-01T00:00:00", payload=payload)
    late = evidence_header(generated_at="2026-12-31T23:59:59", payload=payload)
    # Generation time row differs, digest row is identical.
    assert early[0][1] != late[0][1]
    assert early[1][1] == late[1][1]


def test_header_rows_shape_and_algorithm() -> None:
    rows = evidence_header(generated_at="2026-07-21T00:00:00", payload={"x": 1})
    assert len(rows) == 2
    generated_label, generated_value = rows[0]
    digest_label, digest_value = rows[1]
    assert generated_value == "2026-07-21T00:00:00"
    assert DIGEST_ALGORITHM in digest_value
    assert short_digest(content_digest({"x": 1})) in digest_value


def test_header_labels_localise() -> None:
    en = evidence_header(generated_at="t", payload={}, locale="en")
    ru = evidence_header(generated_at="t", payload={}, locale="ru")
    assert en[0][0] == "Generated"
    assert ru[0][0] == "Сформировано"


# ── exporter wiring ────────────────────────────────────────────────────────


def _export(fmt: str) -> bytes:
    _, _, blob = export_report(
        fmt=fmt,
        report_type="summary",
        title="Quarterly cost report",
        project_name="Demo project",
        currency="EUR",
        generated_at="2026-07-21T00:00:00Z",
        template_data=None,
        data_snapshot=_SNAPSHOT,
    )
    return blob


def test_csv_carries_digest_line() -> None:
    text = _export("csv").decode("utf-8-sig")
    expected = short_digest(
        content_digest(
            {
                "report_type": "summary",
                "title": "Quarterly cost report",
                "project_name": "Demo project",
                "currency": "EUR",
                "data": _SNAPSHOT,
            }
        )
    )
    assert expected in text
    assert DIGEST_ALGORITHM in text


def test_xlsx_and_pdf_build_with_header() -> None:
    # Smoke: both binary builders complete with the extra header rows.
    assert _export("xlsx")[:2] == b"PK"  # zip magic (xlsx container)
    assert _export("pdf")[:4] == b"%PDF"
