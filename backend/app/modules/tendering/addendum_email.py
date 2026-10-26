# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ catalogue for the tender addendum and clarification emails.

Like the invitation email, these go to firms outside the platform and are
written in the project's language. English lives here; every other language
comes from ``core/document_catalogues`` (section ``tender_addendum``) and falls
back to English key by key. Values are plain text; the renderer escapes them.
"""

from __future__ import annotations

import html
from typing import Any

from app.core.document_catalogue import is_rtl, merge_missing
from app.core.document_locale import normalize_document_locale, translate

DEFAULT_LOCALE = "en"

_TABLES: dict[str, dict[str, str]] = {
    "en": {
        "addendum_subject": "Addendum {number} to the tender {package}",
        "addendum_heading": "Tender addendum",
        "greeting": "Dear {company},",
        "greeting_generic": "Dear Sir or Madam,",
        "addendum_intro": "Addendum {number} to the tender package {package} has been issued: {title}.",
        "addendum_deadline": "The submission deadline has moved from {old} to {new}.",
        "addendum_boq": "The bill of quantities has changed (revision {revision}). Please price the current revision.",
        "addendum_documents": "Issued documents: {documents}",
        "addendum_ack": (
            "Please acknowledge receipt of this addendum. A bid that does not acknowledge "
            "every addendum may be treated as non-compliant."
        ),
        "answer_subject": "Clarification {number} on the tender {package}",
        "answer_heading": "Tender clarification",
        "answer_intro": "A question on the tender package {package} has been answered. The answer applies to all bidders.",
        "question_label": "Question",
        "answer_label": "Answer",
    },
}

merge_missing(_TABLES, "tender_addendum")

SUPPORTED_LOCALES: tuple[str, ...] = tuple(_TABLES)


def _t(locale: str | None, key: str, **params: str) -> str:
    lang = normalize_document_locale(locale, SUPPORTED_LOCALES, DEFAULT_LOCALE)
    return translate(_TABLES, lang, key, DEFAULT_LOCALE, **params)


def _lang(locale: str | None) -> str:
    return normalize_document_locale(locale, SUPPORTED_LOCALES, DEFAULT_LOCALE)


def _para(text: str) -> str:
    return f"<p>{html.escape(text)}</p>"


def _greeting(locale: str | None, company: str) -> str:
    return _para(_t(locale, "greeting", company=company) if company else _t(locale, "greeting_generic"))


def addendum_subject(locale: str | None, package_name: str, number: int) -> str:
    return _t(locale, "addendum_subject", package=package_name, number=str(number))


def addendum_html(*, locale: str | None, company_name: str, package_name: str, entry: dict[str, Any]) -> str:
    """The addendum notice: what changed, the new deadline, and the request to acknowledge."""
    from app.core.email import wrap

    parts = [
        _greeting(locale, company_name),
        _para(
            _t(
                locale,
                "addendum_intro",
                number=str(entry.get("revision_no", "")),
                package=package_name,
                title=str(entry.get("title", "")),
            )
        ),
    ]
    if entry.get("body"):
        parts.append(
            "<blockquote style='border-left:3px solid #0071e3; padding-left:12px; margin:12px 0;'>"
            f"{html.escape(str(entry['body']))}</blockquote>"
        )
    if entry.get("new_deadline"):
        parts.append(
            _para(
                _t(
                    locale,
                    "addendum_deadline",
                    old=str(entry.get("previous_deadline") or ""),
                    new=str(entry["new_deadline"]),
                )
            )
        )
    if entry.get("boq_revision_no"):
        parts.append(_para(_t(locale, "addendum_boq", revision=str(entry["boq_revision_no"]))))
    docs = [
        " ".join(x for x in (d.get("drawing_number"), d.get("title"), d.get("revision")) if x)
        for d in entry.get("document_changes") or []
        if isinstance(d, dict)
    ]
    if any(docs):
        parts.append(_para(_t(locale, "addendum_documents", documents="; ".join(d for d in docs if d))))
    parts.append(_para(_t(locale, "addendum_ack")))
    lang = _lang(locale)
    return wrap(html.escape(_t(locale, "addendum_heading")), "".join(parts), lang=lang, rtl=is_rtl(lang))


def answer_subject(locale: str | None, package_name: str, number: int) -> str:
    return _t(locale, "answer_subject", package=package_name, number=str(number))


def answer_html(*, locale: str | None, company_name: str, package_name: str, question: str, answer: str) -> str:
    """A published answer. It never names the firm that asked."""
    from app.core.email import wrap

    parts = [
        _greeting(locale, company_name),
        _para(_t(locale, "answer_intro", package=package_name)),
        f"<p><strong>{html.escape(_t(locale, 'question_label'))}</strong><br>{html.escape(question)}</p>",
        f"<p><strong>{html.escape(_t(locale, 'answer_label'))}</strong><br>{html.escape(answer)}</p>",
    ]
    lang = _lang(locale)
    return wrap(html.escape(_t(locale, "answer_heading")), "".join(parts), lang=lang, rtl=is_rtl(lang))
