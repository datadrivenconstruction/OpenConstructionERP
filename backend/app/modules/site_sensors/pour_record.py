# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pour record of a formwork strike, as CSV and as a PDF record form.

The record a site files with the pour: element, mix, when it was cast and
struck, the strength at strike against the target, who struck and why, and
the temperature and maturity curve up to the strike. The PDF goes through
:func:`app.core.register_export.build_record_pdf`; the labels live in ``backend/locales``, the
page furniture there.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.core.document_forms_i18n import form_strings
from app.core.register_export import RecordBlock, RecordDocument, build_record_pdf, grid_rows

__all__ = ["LABELS", "pour_record_csv", "pour_record_pdf"]

#: The record's own words per language, from ``backend/locales/<code>.json`` (document_forms.site_sensors_pour_record);
#: a language without them prints in English.
LABELS: dict[str, dict[str, str]] = form_strings("site_sensors_pour_record")

_MAX_CURVE_ROWS = 48


def written_language(lang: str) -> str:
    """Return the language the pour record is actually written in."""
    code = (lang or "en").split("-")[0].lower()
    return code if code in LABELS else "en"


def _labels(lang: str) -> dict[str, str]:
    return LABELS[written_language(lang)]


def _thin(series: list[dict[str, Any]], n: int = _MAX_CURVE_ROWS) -> list[dict[str, Any]]:
    if len(series) <= n:
        return series
    step = (len(series) - 1) / (n - 1)
    return [series[round(i * step)] for i in range(n)]


def _index_label(record: dict[str, Any], lab: dict[str, str]) -> str:
    return lab["index_h"] if record.get("index_unit") == "h" else lab["index_c_h"]


def pour_record_csv(record: dict[str, Any], lang: str = "en") -> bytes:
    """Header facts as label/value rows, a blank row, then the full curve."""
    lab = _labels(lang)
    buf = io.StringIO()
    w = csv.writer(buf)
    for key, field in (
        ("element", "element"),
        ("sensor", "device_code"),
        ("pour", "pour_ref"),
        ("mix", "mix_code"),
        ("cast_at", "cast_at"),
        ("struck_at", "struck_at"),
        ("target", "target_strength_mpa"),
        ("strength", "strength_at_strike_mpa"),
        ("maturity", "maturity_at_strike"),
        ("struck_by", "struck_by"),
        ("reason", "strike_reason"),
    ):
        value = record.get(field)
        w.writerow([lab[key], "" if value is None else value])
    w.writerow([])
    w.writerow([lab["time"], lab["temp"], _index_label(record, lab)])
    for p in record.get("series") or []:
        w.writerow([p.get("t", ""), p.get("temp", ""), p.get("maturity", "")])
    return buf.getvalue().encode("utf-8-sig")


def pour_record_pdf(record: dict[str, Any], lang: str = "en") -> bytes:
    """The record form: facts grid, the reason box and the curve table."""
    lab = _labels(lang)

    def v(field: str) -> str:
        value = record.get(field)
        return "-" if value in (None, "") else str(value)

    grid = grid_rows(
        [
            (lab["sensor"], v("device_code")),
            (lab["pour"], v("pour_ref")),
            (lab["mix"], v("mix_code")),
            (lab["cast_at"], v("cast_at")),
            (lab["struck_at"], v("struck_at")),
            (lab["struck_by"], v("struck_by")),
            (lab["target"], v("target_strength_mpa")),
            (lab["strength"], v("strength_at_strike_mpa")),
            (lab["maturity"], v("maturity_at_strike")),
        ]
    )
    curve = [[lab["time"], lab["temp"], _index_label(record, lab)]] + [
        [
            str(p.get("t", ""))[:16].replace("T", " "),
            f"{float(p.get('temp', 0)):.1f}",
            f"{float(p.get('maturity', 0)):.0f}",
        ]
        for p in _thin(list(record.get("series") or []))
    ]
    doc = RecordDocument(
        title=lab["title"],
        number=v("device_code"),
        project_label="",
        status_text=lab["status"],
        subject=v("element"),
        grid=grid,
        blocks=[
            RecordBlock(lab["reason"], text=record.get("strike_reason") or "", empty_text=lab["no_reason"]),
            RecordBlock(lab["curve"], kind="table", rows=curve, weights=(2, 1, 1), right_aligned=(False, True, True)),
        ],
        page_label=lab["page"],
        generated_label=lab["generated"],
    )
    return build_record_pdf(doc)
