# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Built-in document kinds of the platform modules.

The tendering letters already have a registry with ``{name}`` placeholders and
shipped wording in ten languages (:mod:`app.core.letter_templates`). They are
exposed here as document kinds by a two-way mapping between their placeholders
and merge field paths, so their generators keep working unchanged and read a
published document template through ``letter_templates.service.resolve``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from app.core.doc_templates.registry import DocumentKind, MergeField, register_kind

__all__ = [
    "LETTER_BLOCKS",
    "PASSWORD_RESET_KEY",
    "blocks_to_letter",
    "letter_to_blocks",
    "register_builtin_kinds",
]

PASSWORD_RESET_KEY = "users.password_reset"

#: Letter field -> document block, per channel.
LETTER_BLOCKS: dict[str, dict[str, str]] = {
    "pdf": {"heading": "title", "body": "body", "closing": "closing"},
    "email": {"subject": "subject", "heading": "preheader", "body": "body", "closing": "footer"},
}

#: Letter placeholder -> merge field (path, type, group).
_LETTER_FIELDS: dict[str, tuple[str, str, str]] = {
    "bidder": ("recipient.name", "text", "recipient"),
    "project": ("project.name", "text", "project"),
    "company": ("entity.legal_name", "text", "company"),
    "package": ("package.name", "text", "document"),
    "amount": ("doc.total", "money", "document"),
    "award_date": ("doc.date", "date", "document"),
    "date": ("doc.date", "date", "document"),
    "deadline": ("tender.deadline", "date", "document"),
    "sender": ("sender.name", "text", "sender"),
}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _to_fields(text: str, names: set[str]) -> str:
    return _PLACEHOLDER.sub(
        lambda m: (
            "{{" + _LETTER_FIELDS[m.group(1)][0] + "}}"
            if m.group(1) in names and m.group(1) in _LETTER_FIELDS
            else m.group(0)
        ),
        text or "",
    )


def _to_placeholders(text: str, names: set[str]) -> str:
    from app.core.doc_templates.merge import TOKEN_RE, _path

    reverse = {path: name for name, (path, _t, _g) in _LETTER_FIELDS.items() if name in names}

    def _sub(match: re.Match[str]) -> str:
        path = _path(match.group(1))
        return "{" + reverse[path] + "}" if path in reverse else ""

    return TOKEN_RE.sub(_sub, text or "")


def letter_to_blocks(text: Any, channel: str, names: set[str]) -> dict[str, str]:
    """A :class:`~app.core.letter_templates.LetterText` as document blocks."""
    return {block: _to_fields(getattr(text, field, "") or "", names) for field, block in LETTER_BLOCKS[channel].items()}


def blocks_to_letter(blocks: Mapping[str, str], channel: str, names: set[str], fallback: Any) -> Any:
    """Document blocks as a ``LetterText``; fields with no block keep *fallback*'s text."""
    from app.core.letter_templates import LetterText

    values = fallback.as_dict()
    for field, block in LETTER_BLOCKS[channel].items():
        own = blocks.get(block) or ""
        if own.strip():
            values[field] = _to_placeholders(own, names)
    return LetterText(**values)


def _letter_kind(key: str, label: str, record_lister: Any = None, record_preview: Any = None) -> DocumentKind:
    from app.core.letter_templates import LetterText, get_template

    template = get_template(key)
    assert template is not None
    names = template.placeholder_names
    seen: dict[str, MergeField] = {}
    for p in template.placeholders:
        path, ftype, group = _LETTER_FIELDS.get(p.name, (f"letter.{p.name}", "text", "document"))
        seen.setdefault(path, MergeField(path, ftype, p.sample, group))
    channel = template.kind

    def _defaults(lang: str) -> dict[str, str]:
        text = template.defaults.get(lang)
        return letter_to_blocks(text, channel, set(names)) if text else {}

    def _preview(blocks: Mapping[str, str], lang: str, _values: Mapping[str, str]) -> tuple[bytes, str]:
        fallback = template.defaults.get(lang) or template.defaults[template.default_language]
        text: LetterText = blocks_to_letter(blocks, channel, set(names), fallback)
        assert template.preview is not None
        return template.preview(text, lang)

    blocks = tuple(LETTER_BLOCKS[channel].values())
    return DocumentKind(
        key=key,
        channel=channel,
        module=template.module,
        label=label,
        blocks=blocks,
        fields=tuple(seen.values()),
        defaults=_defaults,
        languages=template.languages,
        required_blocks=("body",) + (("subject",) if channel == "email" else ()),
        preview=_preview if template.preview else None,
        appearance_type=None,
        records=record_lister,
        record_preview=record_preview,
    )


async def _award_bids(session: Any, project_ids: set[Any] | None) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.modules.tendering.models import TenderBid, TenderPackage

    stmt = (
        select(TenderBid.id, TenderBid.company_name, TenderPackage.name)
        .join(TenderPackage, TenderPackage.id == TenderBid.package_id)
        .order_by(TenderPackage.name, TenderBid.company_name)
        .limit(50)
    )
    if project_ids is not None:
        stmt = stmt.where(TenderPackage.project_id.in_(project_ids))
    return [(str(bid_id), f"{pkg} - {company}") for bid_id, company, pkg in (await session.execute(stmt)).all()]


def _letter_record_preview(key: str) -> Any:
    async def _render(session: Any, record_id: str, blocks: Mapping[str, str], lang: str) -> tuple[bytes, str, Any]:
        from app.core.letter_templates import get_template
        from app.modules.tendering.letter_texts import AWARD_KEY
        from app.modules.tendering.service import TenderingService

        template = get_template(key)
        assert template is not None
        bid_id = uuid.UUID(record_id)
        svc = TenderingService(session)
        bid = await svc.get_bid(bid_id)
        package = await svc.get_package(bid.package_id)
        fallback = template.defaults.get(lang) or template.defaults[template.default_language]
        text = blocks_to_letter(blocks, template.kind, set(template.placeholder_names), fallback)
        if key == AWARD_KEY:
            pdf, _name = await svc.build_award_letter_pdf(package.id, bid_id, text=text)
        else:
            pdf, _name = await svc.build_rejection_letter_pdf(package.id, bid_id, text=text)
        return pdf, "application/pdf", package.project_id

    return _render


def _password_reset_kind() -> DocumentKind:
    defaults = {
        "en": {
            "subject": "Reset your {{app.name}} password",
            "preheader": "Reset your password",
            "body": (
                "Hello {{recipient.name}},\n\nWe received a request to reset the password on your "
                "**{{app.name}}** account. Click the button below to choose a new one. "
                "The link is valid for {{link.minutes}} minutes.\n\n"
                "If you did not request a password reset, you can safely ignore this email - "
                "your password will not change."
            ),
            "cta_label": "Reset password",
            "footer": "",
        }
    }
    return DocumentKind(
        key=PASSWORD_RESET_KEY,
        channel="email",
        module="users",
        label="Password reset email",
        blocks=("subject", "preheader", "body", "cta_label", "footer"),
        fields=(
            MergeField("recipient.name", "text", "Jane Smith", "recipient"),
            MergeField("app.name", "text", "OpenConstructionERP", "company"),
            MergeField("entity.legal_name", "text", "Muster Hochbau GmbH", "company"),
            MergeField("link.minutes", "quantity", "60", "document"),
        ),
        defaults=lambda lang: defaults.get(lang, {}),
        languages=("en",),
        required_blocks=("subject", "body", "cta_label"),
    )


def register_builtin_kinds() -> None:
    """Register every built-in kind whose module is importable. Idempotent."""
    from app.core.doc_templates.registry import get_kind

    if get_kind(PASSWORD_RESET_KEY) is not None:
        return
    try:
        from app.modules.tendering.letter_texts import (
            AWARD_KEY,
            INVITATION_KEY,
            REJECTION_KEY,
            register_tendering_letter_templates,
        )

        register_tendering_letter_templates()
        register_kind(_letter_kind(AWARD_KEY, "Award letter", _award_bids, _letter_record_preview(AWARD_KEY)))
        register_kind(
            _letter_kind(REJECTION_KEY, "Rejection letter", _award_bids, _letter_record_preview(REJECTION_KEY))
        )
        register_kind(_letter_kind(INVITATION_KEY, "Invitation to tender"))
    except ImportError:
        pass
    from app.modules.doc_templates.documents import change_order_kind, invoice_kind, offer_kind

    register_kind(invoice_kind())
    register_kind(change_order_kind())
    try:
        register_kind(offer_kind())
    except (ImportError, KeyError):
        pass
    from app.modules.doc_templates.site_documents import minutes_kind, rfi_kind, transmittal_kind

    for factory in (rfi_kind, minutes_kind, transmittal_kind):
        register_kind(factory())
    register_kind(_password_reset_kind())
