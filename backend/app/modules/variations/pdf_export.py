# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The printed variation, claim and notice registers, and one variation request.

* The variation register lists every variation request with the amount
  claimed (the estimated cost impact), the amount agreed, and the time it
  costs.
* The claims register puts disruption claims and extension of time claims in
  one list, because that is how a claim schedule is read: what was claimed in
  money and days, and what was decided. A claim row has no number of its own
  in this module, so the register numbers its rows in print order and does
  not pretend that number is a claim reference.
* The notice register lists the contractual notices with who they went to
  and when an answer was expected and received.

Amounts stay ``Decimal`` from the row to the page and are written in the
separators of the project's market, with the currency in its own column.

The builders are pure, like :mod:`app.modules.rfi.pdf_export`. The layout is
the shared one in :mod:`app.core.register_export`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.core.register_export import (
    ProjectHeader,
    RecordBlock,
    RecordDocument,
    RegisterColumn,
    RegisterDocument,
    build_record_pdf,
    caps,
    format_amount,
    format_stored_date,
    person_name,
)
from app.modules.variations.pdf_translations import CATALOGUE, DEFAULT_PDF_LOCALE, normalize_pdf_locale, tr

__all__ = [
    "build_variation_pdf",
    "claim_register",
    "notice_register",
    "variation_record",
    "variation_register",
]


def _currency(row: Any, project: ProjectHeader) -> str:
    """The row's own currency, else the project's."""
    return (str(getattr(row, "currency", "") or "").strip().upper()) or project.currency


def _register(
    title_key: str,
    columns: list[RegisterColumn],
    rows: list[list[Any]],
    *,
    project: ProjectHeader,
    locale: str,
    generated: str,
    with_currency: bool = False,
) -> RegisterDocument:
    return RegisterDocument(
        title=tr(locale, title_key),
        columns=columns,
        rows=rows,
        details=CATALOGUE.register_details(locale, project, count=len(rows), with_currency=with_currency),
        locale=locale,
        number_style=project.number_style,
        generated=generated,
        empty_text=tr(locale, "empty_register"),
        **CATALOGUE.furniture(locale),
    )


def variation_register(
    requests: Sequence[Any],
    *,
    project: ProjectHeader,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the variation register of one project.

    Args:
        requests: :class:`~app.modules.variations.models.VariationRequest`
            rows, or objects with the same attributes, in print order.
        project: The project the register belongs to.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_code"), weight=1.1, xlsx_width=13),
        RegisterColumn(tr(locale, "col_title"), weight=3.0, xlsx_width=42, wrap=True),
        RegisterColumn(tr(locale, "col_classification"), weight=1.5, xlsx_width=22),
        RegisterColumn(tr(locale, "col_urgency"), weight=0.9, xlsx_width=11),
        RegisterColumn(tr(locale, "status"), weight=1.3, xlsx_width=18),
        RegisterColumn(tr(locale, "col_requested"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_claimed_amount"), kind="money", weight=1.6, xlsx_width=18),
        RegisterColumn(tr(locale, "col_agreed_amount"), kind="money", weight=1.6, xlsx_width=18),
        RegisterColumn(tr(locale, "currency"), weight=0.8, xlsx_width=10),
        RegisterColumn(tr(locale, "col_time_impact"), kind="count", weight=0.9, xlsx_width=12),
        RegisterColumn(tr(locale, "col_response_due"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_clause"), weight=1.2, xlsx_width=18),
    ]
    rows = [
        [
            getattr(item, "code", ""),
            getattr(item, "title", ""),
            CATALOGUE.label("classification", getattr(item, "classification", None), locale),
            CATALOGUE.label("urgency", getattr(item, "urgency", None), locale),
            CATALOGUE.label("request_status", getattr(item, "status", None), locale),
            getattr(item, "requested_at", None),
            getattr(item, "estimated_cost_impact", None),
            getattr(item, "agreed_cost_impact", None),
            _currency(item, project),
            getattr(item, "estimated_schedule_days", None),
            getattr(item, "response_due_date", None),
            getattr(item, "contract_clause_ref", None),
        ]
        for item in requests
    ]
    return _register(
        "variation_register_title",
        columns,
        rows,
        project=project,
        locale=locale,
        generated=generated,
        with_currency=True,
    )


def claim_register(
    disruption_claims: Sequence[Any],
    eot_claims: Sequence[Any],
    *,
    project: ProjectHeader,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the claims register of one project.

    Args:
        disruption_claims: :class:`~app.modules.variations.models.DisruptionClaim`
            rows, or objects with the same attributes.
        eot_claims: :class:`~app.modules.variations.models.ExtensionOfTimeClaim`
            rows, or objects with the same attributes.
        project: The project the register belongs to.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_row"), kind="count", weight=0.6, xlsx_width=8),
        RegisterColumn(tr(locale, "col_claim_type"), weight=1.3, xlsx_width=18),
        RegisterColumn(tr(locale, "col_raised"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_period_start"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_period_end"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_description"), weight=3.4, xlsx_width=48, wrap=True),
        RegisterColumn(tr(locale, "status"), weight=1.3, xlsx_width=16),
        RegisterColumn(tr(locale, "col_claimed_amount"), kind="money", weight=1.5, xlsx_width=18),
        RegisterColumn(tr(locale, "col_decided_amount"), kind="money", weight=1.5, xlsx_width=18),
        RegisterColumn(tr(locale, "currency"), weight=0.8, xlsx_width=10),
        RegisterColumn(tr(locale, "col_days_requested"), kind="count", weight=0.9, xlsx_width=12),
        RegisterColumn(tr(locale, "col_days_granted"), kind="count", weight=0.9, xlsx_width=12),
    ]
    # One list in the order the claims were raised, whichever kind they are.
    claims = [("disruption", claim) for claim in disruption_claims] + [("eot", claim) for claim in eot_claims]
    claims.sort(key=lambda pair: str(getattr(pair[1], "raised_at", None) or ""))
    rows: list[list[Any]] = []
    for index, (kind, claim) in enumerate(claims, 1):
        is_disruption = kind == "disruption"
        rows.append(
            [
                index,
                CATALOGUE.label("claim_type", kind, locale),
                getattr(claim, "raised_at", None),
                getattr(claim, "claim_period_start", None),
                getattr(claim, "claim_period_end", None),
                getattr(claim, "description", ""),
                CATALOGUE.label("claim_status", getattr(claim, "status", None), locale),
                getattr(claim, "cost_amount", None) if is_disruption else None,
                getattr(claim, "decided_amount", None) if is_disruption else None,
                _currency(claim, project) if is_disruption else None,
                getattr(claim, "schedule_days", None) if is_disruption else getattr(claim, "requested_days", None),
                None if is_disruption else getattr(claim, "granted_days", None),
            ]
        )
    return _register("claim_register_title", columns, rows, project=project, locale=locale, generated=generated)


def notice_register(
    notices: Sequence[Any],
    *,
    project: ProjectHeader,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RegisterDocument:
    """Describe the notice register of one project.

    Args:
        notices: :class:`~app.modules.variations.models.Notice` rows, or
            objects with the same attributes, in print order.
        project: The project the register belongs to.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    columns = [
        RegisterColumn(tr(locale, "col_code"), weight=1.1, xlsx_width=13),
        RegisterColumn(tr(locale, "col_title"), weight=3.4, xlsx_width=46, wrap=True),
        RegisterColumn(tr(locale, "col_recipient_type"), weight=1.2, xlsx_width=14),
        RegisterColumn(tr(locale, "col_recipient"), weight=2.0, xlsx_width=26),
        RegisterColumn(tr(locale, "col_raised"), kind="date", weight=1.3, xlsx_width=14),
        RegisterColumn(tr(locale, "col_target_response"), kind="date", weight=1.4, xlsx_width=16),
        RegisterColumn(tr(locale, "col_response_received"), kind="date", weight=1.4, xlsx_width=16),
        RegisterColumn(tr(locale, "status"), weight=1.2, xlsx_width=14),
    ]
    rows = [
        [
            getattr(item, "code", ""),
            getattr(item, "title", ""),
            CATALOGUE.label("recipient_type", getattr(item, "recipient_type", None), locale),
            getattr(item, "recipient_name", None),
            getattr(item, "raised_at", None),
            getattr(item, "target_response_date", None),
            getattr(item, "response_received_at", None),
            CATALOGUE.label("notice_status", getattr(item, "status", None), locale),
        ]
        for item in notices
    ]
    return _register("notice_register_title", columns, rows, project=project, locale=locale, generated=generated)


def variation_record(
    request: Any,
    *,
    project: ProjectHeader,
    people: Mapping[str, str] | None = None,
    locale: str = DEFAULT_PDF_LOCALE,
    generated: str = "",
) -> RecordDocument:
    """Describe the printable form of one variation request.

    Args:
        request: The variation request row, or any object with the same attributes.
        project: The owning project.
        people: Display names keyed by ``str(id)`` for who requested and decided.
        locale: Document language; unsupported values fall back to English.
        generated: The timestamp printed in the footer.
    """
    locale = normalize_pdf_locale(locale)
    date_format = tr(locale, "date_format")
    style = project.number_style
    currency = _currency(request, project)

    def _date(name: str) -> str:
        return format_stored_date(getattr(request, name, None), date_format)

    requester = person_name(getattr(request, "requested_by", None), people)
    decider = person_name(getattr(request, "decided_by", None), people)
    grid = [
        [
            tr(locale, "project"),
            project.label,
            tr(locale, "col_classification"),
            CATALOGUE.label("classification", getattr(request, "classification", None), locale),
        ],
        [
            tr(locale, "col_urgency"),
            CATALOGUE.label("urgency", getattr(request, "urgency", None), locale),
            tr(locale, "col_clause"),
            str(getattr(request, "contract_clause_ref", None) or "-"),
        ],
        [
            tr(locale, "col_claimed_amount"),
            format_amount(getattr(request, "estimated_cost_impact", None), style, currency),
            tr(locale, "col_agreed_amount"),
            format_amount(getattr(request, "agreed_cost_impact", None), style, currency),
        ],
        [
            tr(locale, "col_time_impact"),
            CATALOGUE.days(getattr(request, "estimated_schedule_days", None), locale),
            tr(locale, "col_response_due"),
            _date("response_due_date"),
        ],
        [tr(locale, "requested_by"), requester, tr(locale, "col_requested"), _date("requested_at")],
        [tr(locale, "date_submitted"), _date("submitted_at"), tr(locale, "date_decided"), _date("decision_at")],
        [tr(locale, "decided_by"), decider, "", ""],
    ]
    status = CATALOGUE.label("request_status", getattr(request, "status", None) or "draft", locale)
    return RecordDocument(
        title=tr(locale, "doc_title"),
        number=str(getattr(request, "code", "") or ""),
        project_label=project.label,
        status_text=caps(status, locale),
        subject=str(getattr(request, "title", "") or ""),
        grid=grid,
        blocks=[
            RecordBlock(
                tr(locale, "description"),
                text=str(getattr(request, "description", None) or ""),
                empty_text=tr(locale, "no_description"),
            ),
            RecordBlock(
                tr(locale, "decision_notes"),
                text=str(getattr(request, "decision_notes", None) or ""),
                empty_text=tr(locale, "no_decision_notes"),
            ),
            RecordBlock(
                tr(locale, "signatures"),
                kind="signatures",
                rows=[
                    ["", tr(locale, "name"), tr(locale, "signature"), tr(locale, "date")],
                    [tr(locale, "requested_by"), "" if requester == "-" else requester, "", ""],
                    [tr(locale, "decided_by"), "" if decider == "-" else decider, "", ""],
                ],
            ),
        ],
        page_label=tr(locale, "footer_page"),
        generated_label=tr(locale, "footer_generated"),
        generated=generated,
    )


def build_variation_pdf(request: Any, **context: Any) -> bytes:
    """Render one variation request as a PDF form; see :func:`variation_record`."""
    return build_record_pdf(variation_record(request, **context))
