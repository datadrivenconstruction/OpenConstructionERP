# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo: one customised invoice template, published in German and English.

The demo firm words its invoices its own way (serif type, a site-specific
intro, a cash discount term), so the editor opens on a real version history
and every invoice printed in the demo shows the template at work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.doc_templates.documents import INVOICE_KEY

__all__ = ["DEMO_INVOICE_BLOCKS", "seed_doc_templates_demo"]

_SEED_USER = "00000000-0000-0000-0000-000000000000"
_NOTE = "Demo wording"

DEMO_INVOICE_BLOCKS: dict[str, dict[str, str]] = {
    "de": {
        "intro": "Sehr geehrte Damen und Herren,\n\nfür die im Leistungszeitraum am Bauvorhaben {{project.name}} "
        "ausgeführten Arbeiten stellen wir Ihnen folgende Leistungen in Rechnung.",
        "terms": "Zahlbar bis {{doc.due_date}} ohne Abzug. Bei Zahlung innerhalb von 10 Tagen gewähren wir "
        "2 % Skonto auf den Nettobetrag.",
        "closing": "Wir bedanken uns für die gute Zusammenarbeit.\n\nMit freundlichen Grüßen\n{{entity.legal_name}}",
    },
    "en": {
        "intro": "Dear Sir or Madam,\n\nfor the work carried out on {{project.name}} in the period of service "
        "we invoice you as follows.",
        "terms": "Payable by {{doc.due_date}} without deduction. Payment within 10 days earns a 2 % cash "
        "discount on the net amount.",
        "closing": "Thank you for the good cooperation.\n\nKind regards\n{{entity.legal_name}}",
    },
}


async def seed_doc_templates_demo(session: Any) -> int:
    """Publish the demo invoice wording once; returns the number of versions written.

    A workspace that already has any invoice template, demo or the user's own,
    is left alone, so a re-run never overwrites real wording.
    """
    from app.modules.doc_templates import service
    from app.modules.doc_templates.models import DocTemplate

    if (await session.execute(select(DocTemplate.id).where(DocTemplate.kind == INVOICE_KEY).limit(1))).first():
        return 0
    kind = service.require_kind(INVOICE_KEY)
    written = 0
    for locale, blocks in DEMO_INVOICE_BLOCKS.items():
        await service.save_draft(session, kind, locale, blocks, {"font": "serif"}, _SEED_USER)
        await service.publish(session, kind, locale, _NOTE, _SEED_USER)
        written += 1
    return written
