# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed submittal register and the printed form of one submittal.

A contractor's submittal register is a contractual record: it shows what was
submitted for approval (shop drawings, product data, method statements), in
which revision, when it was required, when it came back and with which
decision. It is printed and attached to letters, so it carries the project,
the generation date and "page x of y", and its columns are the ones the
submittal row stores, not ones a template would like to have.

The builders are pure, like :mod:`app.modules.rfi.pdf_export`: they take
rows plus already-resolved names and never touch the database, so the routes
do the lookups and the tests drive them with plain namespaces. The layout
is the shared one in :mod:`app.core.register_export`.

Two layouts, one register
-------------------------
The register also carries what procurement runs on: discipline, manufacturer,
model, origin, supplier, the reviewer's code, days in review, required on
site, lead time and the date an approval is needed by. That is twenty-nine
columns, which a workbook holds and a landscape sheet does not. So the
workbook (``layout="full"``) gets one column per fact, and the printed sheet
(``layout="print"``, the default) gets fifteen: the product is one cell
(manufacturer, model, origin), two date pairs share a cell each and wrap onto
two lines, and the reviewer and approver, who are on the form of each
submittal, are left to the workbook. Every cell is still a stored value or a
figure derived from stored values; nothing is invented to fill a column.

Rows written before these columns existed have none of them, and every read
below defaults, so such a register prints dashes in the new cells and nothing
else changes.
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from app.core.regional_format import NBSP
from app.core.register_export import (
    EMPTY,
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    RegisterColumn,
    RegisterDocument,
    build_record_pdf,
    build_register_pdf,
    build_register_xlsx,
    caps,
    format_count,
    format_stored_date,
    grid_rows,
    person_name,
)
from app.modules.submittals.pdf_translations import (
    CATALOGUE,
    DEFAULT_PDF_LOCALE,
    doc_title,
    normalize_pdf_locale,
    register_title,
    tr,
)
from app.modules.submittals.tracking import Tracking, track

__all__ = [
    "build_submittal_pdf",
    "build_submittal_register_pdf",
    "build_submittal_register_xlsx",
    "submittal_record",
    "submittal_register",
]


@dataclass(frozen=True)
class _Row:
    """One submittal with everything a cell may need already worked out."""

    item: Any
    figures: Tracking
    locale: str
    people: Mapping[str, str] | None
    drawings: Mapping[str, str] | None
    date_format: str

    def get(self, name: str) -> Any:
        return getattr(self.item, name, None)

    def text(self, name: str) -> str | None:
        value = str(self.get(name) or "").strip()
        return value or None

    def day(self, value: Any) -> str:
        return format_stored_date(value, self.date_format)

    def days(self, *values: Any) -> str | None:
        """Several dates in one cell, in order; a missing one keeps its dash."""
        if all(value in (None, "") for value in values):
            return None
        return " ".join(self.day(value) for value in values)

    def product(self) -> str | None:
        parts = [self.text("manufacturer"), self.text("model_reference"), self.text("country_of_origin")]
        return ", ".join(part for part in parts if part) or None

    def drawing_names(self) -> str | None:
        return "; ".join(_drawing_names(self.get("linked_drawing_ids"), self.drawings)) or None


@dataclass(frozen=True)
class _Spec:
    """One register column: its heading, how wide it is, and what goes in it."""

    key: str
    value: Callable[[_Row], Any]
    kind: str = "text"
    weight: float = 1.0
    xlsx_width: float = 16.0
    wrap: bool = False
    nobreak: bool | None = None


def _drawing_names(ids: Any, drawings: Mapping[str, str] | None) -> list[str]:
    """Names of the linked drawings that could be resolved, in link order."""
    names = drawings or {}
    return [names[str(i)] for i in ids if str(i) in names] if isinstance(ids, list) else []


def _label(table: str, attribute: str) -> Callable[[_Row], str]:
    return lambda row: CATALOGUE.label(table, row.get(attribute), row.locale)


def _person(attribute: str) -> Callable[[_Row], str]:
    return lambda row: person_name(row.get(attribute), row.people)


def _attr(attribute: str) -> Callable[[_Row], Any]:
    return lambda row: row.get(attribute)


def _outcome(row: _Row) -> str:
    return CATALOGUE.label("status", row.figures.outcome, row.locale)


#: The section number a specification reference opens with: "23 64 00", "26.05.19".
_SPEC_NUMBER = re.compile(r"^\d[\d .]*\d")


def _spec_print(row: _Row) -> str | None:
    """The spec section for the printed sheet: its number on one line, its words free to wrap.

    "23 64 00" broken after "23" reads as three values, so the spaces inside
    the number do not break. A section name typed after the number still
    wraps at its own spaces; holding the whole reference on one line made
    this column the widest of the sheet and left the title a third of it.
    """
    text = row.text("spec_section")
    if not text:
        return None
    match = _SPEC_NUMBER.match(text)
    if match is None:
        return text
    return match.group(0).replace(" ", NBSP) + text[match.end() :]


def _long_lead(row: _Row) -> str | None:
    # Only a marked item says so; a blank cell is easier to scan than a
    # column of "No".
    return CATALOGUE.yes_no(True, row.locale) if row.get("long_lead") is True else None


#: The printed sheet: thirteen columns on a landscape page. The shared
#: renderer sizes each column from what it holds (see
#: ``register_export.table_layout``); a weight here is only the column's
#: share of the width left over. Numbers, codes and single dates are kept on
#: one line, the title takes the slack. The date the review is required by
#: and the ball in court are left to the workbook and the form, so that the
#: title keeps a readable width.
_PRINT_COLUMNS: tuple[_Spec, ...] = (
    _Spec("col_number", _attr("submittal_number"), weight=54, nobreak=True),
    _Spec("col_rev", _attr("current_revision"), kind="count", weight=29),
    _Spec("col_title", _attr("title"), weight=125, wrap=True),
    _Spec("col_type", _label("type", "submittal_type"), weight=55),
    _Spec("col_discipline", _label("discipline", "discipline"), weight=65),
    _Spec("col_spec", _spec_print, weight=54),
    _Spec("col_product", lambda row: row.product(), weight=64),
    _Spec("status", _label("status", "status"), weight=57),
    _Spec("col_review_code", lambda row: row.figures.code, weight=42, nobreak=True),
    _Spec(
        "col_submitted_returned", lambda row: row.days(row.get("date_submitted"), row.get("date_returned")), weight=57
    ),
    _Spec("col_days_in_review_print", lambda row: row.figures.days_in_review, kind="count", weight=51),
    _Spec(
        "col_on_site_needed_by",
        lambda row: row.days(row.get("required_on_site_date"), row.figures.approval_needed_by),
        weight=57,
    ),
    _Spec("col_lead_time", _attr("lead_time_weeks"), kind="count", weight=46),
)

#: The workbook: one column per fact, in the order a register is read.
_FULL_COLUMNS: tuple[_Spec, ...] = (
    _Spec("col_number", _attr("submittal_number"), xlsx_width=14),
    _Spec("col_rev", _attr("current_revision"), kind="count", xlsx_width=7),
    _Spec("col_title", _attr("title"), weight=3.0, xlsx_width=42, wrap=True),
    _Spec("col_type", _label("type", "submittal_type"), xlsx_width=18),
    _Spec("col_discipline", _label("discipline", "discipline"), xlsx_width=20),
    _Spec("col_spec", _attr("spec_section"), xlsx_width=16),
    _Spec("col_manufacturer", _attr("manufacturer"), xlsx_width=24),
    _Spec("col_model", _attr("model_reference"), xlsx_width=22),
    _Spec("col_origin", _attr("country_of_origin"), xlsx_width=10),
    _Spec("col_supplier", _person("supplier"), xlsx_width=24),
    _Spec("status", _label("status", "status"), xlsx_width=22),
    _Spec("col_review_code", lambda row: row.figures.code, xlsx_width=10),
    _Spec("col_outcome", _outcome, xlsx_width=22),
    _Spec("col_date_submitted", _attr("date_submitted"), kind="date", xlsx_width=14),
    _Spec("col_date_required", _attr("date_required"), kind="date", xlsx_width=14),
    _Spec("col_date_returned", _attr("date_returned"), kind="date", xlsx_width=14),
    _Spec("col_review_period", _attr("review_period_days"), kind="count", xlsx_width=12),
    _Spec("col_review_due", lambda row: row.figures.review_due_date, kind="date", xlsx_width=14),
    _Spec("col_days_in_review", lambda row: row.figures.days_in_review, kind="count", xlsx_width=12),
    _Spec("col_review_overdue", lambda row: row.figures.review_overdue_days, kind="count", xlsx_width=12),
    _Spec("col_required_on_site", _attr("required_on_site_date"), kind="date", xlsx_width=16),
    _Spec("col_long_lead", _long_lead, xlsx_width=12),
    _Spec("col_lead_time", _attr("lead_time_weeks"), kind="count", xlsx_width=12),
    _Spec("col_needed_by", lambda row: row.figures.approval_needed_by, kind="date", xlsx_width=16),
    _Spec("col_approval_late", lambda row: row.figures.approval_late_days, kind="count", xlsx_width=12),
    _Spec("col_reviewer", _person("reviewer_id"), xlsx_width=20),
    _Spec("col_approver", _person("approver_id"), xlsx_width=20),
    _Spec("col_ball_in_court", _person("ball_in_court"), xlsx_width=20),
    _Spec("col_drawings", lambda row: row.drawing_names(), xlsx_width=36, wrap=True),
)

_LAYOUTS: dict[str, tuple[_Spec, ...]] = {"print": _PRINT_COLUMNS, "full": _FULL_COLUMNS}


def _as_of(value: Any) -> date:
    """The day the derived figures are measured from: the one given, or today."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return datetime.now(tz=UTC).date()


def _filter_details(locale: str, filters: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    """The filters a register was cut by, as label and value pairs for its header.

    A register that shows part of the log has to say which part, or the next
    reader takes forty rows for the whole of it.
    """
    chosen = filters or {}
    details: list[tuple[str, str]] = []
    if chosen.get("submittal_type"):
        details.append((tr(locale, "col_type"), CATALOGUE.label("type", chosen["submittal_type"], locale)))
    if chosen.get("discipline"):
        details.append((tr(locale, "col_discipline"), CATALOGUE.label("discipline", chosen["discipline"], locale)))
    if chosen.get("status"):
        details.append((tr(locale, "status"), CATALOGUE.label("status", chosen["status"], locale)))
    if chosen.get("review_outcome"):
        details.append((tr(locale, "col_outcome"), CATALOGUE.label("status", chosen["review_outcome"], locale)))
    if chosen.get("review_code"):
        details.append((tr(locale, "col_review_code"), str(chosen["review_code"])))
    for flag, key in (
        ("long_lead", "col_long_lead"),
        ("review_overdue", "col_review_overdue"),
        ("approval_late", "col_approval_late"),
    ):
        if chosen.get(flag) is not None:
            details.append((tr(locale, key), CATALOGUE.yes_no(chosen[flag], locale)))
    return details


def submittal_register(
    submittals: Sequence[Any],
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    layout: str = "print",
    filters: Mapping[str, Any] | None = None,
    drawings: Mapping[str, str] | None = None,
    as_of: Any = None,
) -> RegisterDocument:
    """Describe the submittal register of one project.

    Args:
        submittals: :class:`~app.modules.submittals.models.Submittal` rows, or
            objects with the same attributes, in the order to print them.
        project: The project the register belongs to.
        people: Display names keyed by ``str(id)`` for reviewers, approvers,
            suppliers and whoever holds the ball.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        layout: ``"print"`` for the columns that fit a landscape sheet,
            ``"full"`` for every column (the workbook).
        filters: The filters the rows were selected by, printed in the header.
            ``submittal_type`` also picks the title: filtered to shop drawings
            this is the shop drawing register.
        drawings: Names of linked drawings keyed by ``str(id)``.
        as_of: The day "days in review" and the late figures are measured
            from; today when omitted.

    Returns:
        The register, ready for the PDF or the workbook renderer.
    """
    locale = normalize_pdf_locale(locale)
    specs = _LAYOUTS.get(layout, _PRINT_COLUMNS)
    today = _as_of(as_of)
    date_format = CATALOGUE.date_format(locale, project)
    columns = [
        RegisterColumn(
            tr(locale, spec.key),
            kind=spec.kind,
            weight=spec.weight,
            xlsx_width=spec.xlsx_width,
            wrap=spec.wrap,
            nobreak=spec.nobreak,
        )
        for spec in specs
    ]
    rows = []
    for item in submittals:
        row = _Row(item, track(item, today), locale, people, drawings, date_format)
        rows.append([spec.value(row) for spec in specs])
    chosen_type = (filters or {}).get("submittal_type")
    return RegisterDocument(
        title=register_title(locale, chosen_type),
        columns=columns,
        rows=rows,
        details=[*CATALOGUE.register_details(locale, project, count=len(rows)), *_filter_details(locale, filters)],
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty_register"),
        **CATALOGUE.furniture(locale, project),
    )


def build_submittal_register_pdf(submittals: Sequence[Any], **context: Any) -> bytes:
    """Render the submittal register as a PDF; see :func:`submittal_register`."""
    return build_register_pdf(submittal_register(submittals, **{**context, "layout": "print"}))


def build_submittal_register_xlsx(submittals: Sequence[Any], **context: Any) -> io.BytesIO:
    """Render the submittal register as a workbook; see :func:`submittal_register`."""
    return build_register_xlsx(submittal_register(submittals, **{**context, "layout": "full"}))


def _history_blocks(row: _Row) -> list[RecordBlock]:
    """The earlier review cycles as a table, or nothing when there are none.

    A submittal revised in place keeps only its current dates on the row. The
    history is where a reader of the printed form sees that revision 1 came
    back "revise and resubmit" before revision 2 was approved.
    """
    history = row.get("review_history")
    entries = [entry for entry in history if isinstance(entry, dict)] if isinstance(history, list) else []
    if not entries:
        return []
    locale = row.locale
    header = [
        tr(locale, "col_rev"),
        tr(locale, "hist_submitted"),
        tr(locale, "hist_returned"),
        tr(locale, "col_review_code"),
        tr(locale, "col_outcome"),
        tr(locale, "col_reviewer"),
    ]
    body = [
        [
            format_count(entry.get("revision")),
            row.day(entry.get("date_submitted")),
            row.day(entry.get("date_returned")),
            str(entry.get("code") or EMPTY),
            CATALOGUE.label("status", entry.get("outcome"), locale),
            person_name(entry.get("reviewer_id"), row.people),
        ]
        for entry in entries
    ]
    return [
        RecordBlock(
            tr(locale, "review_history"),
            kind="table",
            rows=[header, *body],
            weights=(0.6, 1.2, 1.2, 0.9, 1.8, 1.8),
            right_aligned=(True, False, False, False, False, False),
        )
    ]


def submittal_record(
    submittal: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
    drawings: Mapping[str, str] | None = None,
    as_of: Any = None,
) -> RecordDocument:
    """Describe the printable form of one submittal.

    Args:
        submittal: The submittal row, or any object with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)``.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
        drawings: Names of linked drawings keyed by ``str(id)``.
        as_of: The day the derived figures are measured from; today when
            omitted.

    Returns:
        The form, ready for the PDF renderer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = CATALOGUE.date_format(locale, project)
    figures = track(submittal, _as_of(as_of))
    row = _Row(submittal, figures, locale, people, drawings, date_format)
    metadata = getattr(submittal, "metadata_", None)
    notes = str((metadata if isinstance(metadata, dict) else {}).get("review_notes") or "")
    reviewer = person_name(getattr(submittal, "reviewer_id", None), people)
    approver = person_name(getattr(submittal, "approver_id", None), people)
    submitter = person_name(getattr(submittal, "submitted_by_org", None), people)
    submittal_type = getattr(submittal, "submittal_type", None)
    # The project is in the line under the title, with the submittal number,
    # so the grid does not repeat it, and a form with an ordinary title keeps
    # its signatures on the page that holds the figures.
    grid = grid_rows(
        [
            (tr(locale, "col_type"), CATALOGUE.label("type", submittal_type, locale)),
            (tr(locale, "col_rev"), format_count(row.get("current_revision"))),
            (tr(locale, "col_spec"), row.text("spec_section") or EMPTY),
            (tr(locale, "col_discipline"), _label("discipline", "discipline")(row)),
            (tr(locale, "submitted_by_org"), submitter),
            (tr(locale, "col_ball_in_court"), person_name(row.get("ball_in_court"), people)),
            (tr(locale, "col_date_submitted"), row.day(row.get("date_submitted"))),
            (tr(locale, "col_date_required"), row.day(row.get("date_required"))),
            (tr(locale, "col_date_returned"), row.day(row.get("date_returned"))),
            (tr(locale, "col_reviewer"), reviewer),
            (tr(locale, "col_approver"), approver),
            (tr(locale, "col_supplier"), person_name(row.get("supplier"), people)),
            (tr(locale, "col_manufacturer"), row.text("manufacturer") or EMPTY),
            (tr(locale, "col_model"), row.text("model_reference") or EMPTY),
            (tr(locale, "col_origin"), row.text("country_of_origin") or EMPTY),
            (tr(locale, "col_long_lead"), CATALOGUE.yes_no(row.get("long_lead") is True, locale)),
            (tr(locale, "col_outcome"), _outcome(row)),
            (tr(locale, "col_review_code"), figures.code or EMPTY),
            (tr(locale, "col_review_period"), format_count(row.get("review_period_days"))),
            (tr(locale, "col_days_in_review"), format_count(figures.days_in_review)),
            (tr(locale, "col_required_on_site"), row.day(row.get("required_on_site_date"))),
            (tr(locale, "col_lead_time"), format_count(row.get("lead_time_weeks"))),
            (tr(locale, "col_needed_by"), row.day(figures.approval_needed_by)),
        ]
    )
    linked = row.get("linked_drawing_ids")
    names = _drawing_names(linked, drawings)
    if names or (isinstance(linked, list) and linked):
        missing = len(linked) - len(names) if isinstance(linked, list) else 0
        if missing:
            names.append(tr(locale, "drawings_missing_one" if missing == 1 else "drawings_missing_other", n=missing))
        grid.append([tr(locale, "col_drawings"), "; ".join(names), "", ""])  # a row of its own: names run long
    if figures.resubmit_for_record:
        notes = f"{tr(locale, 'resubmit_for_record')}. {notes}".strip()
    signatures = CATALOGUE.signature_rows(
        locale,
        [
            (tr(locale, "sig_submitted"), submitter),
            (tr(locale, "sig_reviewed"), reviewer),
            (tr(locale, "sig_approved"), approver),
        ],
    )
    status = CATALOGUE.label("status", getattr(submittal, "status", None) or "draft", locale)
    return RecordDocument(
        title=doc_title(locale, submittal_type),
        number=str(getattr(submittal, "submittal_number", "") or ""),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=str(getattr(submittal, "title", "") or ""),
        grid=grid,
        blocks=[
            RecordBlock(tr(locale, "review_notes"), text=notes, empty_text=tr(locale, "no_review_notes")),
            *_history_blocks(row),
            RecordBlock(tr(locale, "signatures"), kind="signatures", rows=signatures),
        ],
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )


def build_submittal_pdf(submittal: Any, **context: Any) -> bytes:
    """Render one submittal as a PDF form; see :func:`submittal_record`."""
    return build_record_pdf(submittal_record(submittal, **context))
