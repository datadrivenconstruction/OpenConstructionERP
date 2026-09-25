# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List the second invoice an older release raised for each certified claim.

Until 18.1 two subscribers answered ``contracts.claim.certified``. Finance
raised the invoice linked to the claim through ``source_claim_id``, and a
notifications subscriber raised another one, numbered ``PC-<claim>``, linked
only through ``metadata.claim_id``, always as a receivable, and with the
retention taken off twice (``amount_total`` was already the net due and
``retention_amount`` was deducted again). The second subscriber is gone, but
installs that certified claims before then still carry those invoices.

This only reads. It prints every invoice with ``metadata.source`` set to
``contracts.claim.certified`` and no ``source_claim_id``, and says whether the
claim also has its linked invoice (a duplicate) or not (the only invoice the
claim has, which a person should relink rather than delete). Nothing is
changed or deleted: a paid or sent invoice is a record a person has to decide
about.

    python -m scripts.report_duplicate_claim_invoices
    python -m scripts.report_duplicate_claim_invoices --json

Exit code 0 when there is nothing to report, 1 when there is.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402 - after the sys.path bootstrap above
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

SOURCE = "contracts.claim.certified"


async def find_duplicate_claim_invoices(session: AsyncSession) -> list[dict[str, Any]]:
    """Every unlinked invoice the old claim subscriber raised, with what it duplicates.

    The metadata filter runs in Python so the query is the same on every
    dialect; the candidates are narrowed by the column the linked invoice
    always sets.
    """
    from app.modules.finance.models import Invoice  # noqa: PLC0415

    candidates = (await session.execute(select(Invoice).where(Invoice.source_claim_id.is_(None)))).scalars().all()
    found: list[dict[str, Any]] = []
    for invoice in candidates:
        meta = dict(invoice.metadata_ or {})
        if meta.get("source") != SOURCE:
            continue
        claim_id = meta.get("claim_id")
        linked = None
        try:
            claim_uuid = uuid.UUID(str(claim_id)) if claim_id else None
        except ValueError:
            claim_uuid = None
        if claim_uuid is not None:
            linked = (
                await session.execute(select(Invoice).where(Invoice.source_claim_id == claim_uuid).limit(1))
            ).scalar_one_or_none()
        found.append(
            {
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "project_id": str(invoice.project_id),
                "claim_id": claim_id,
                "claim_number": meta.get("claim_number"),
                "status": invoice.status,
                "direction": invoice.invoice_direction,
                "amount_total": str(invoice.amount_total),
                "retention_amount": str(invoice.retention_amount),
                "kind": "duplicate" if linked is not None else "only_invoice",
                "linked_invoice_id": str(linked.id) if linked is not None else None,
                "linked_invoice_number": linked.invoice_number if linked is not None else None,
            }
        )
    return found


async def _run(as_json: bool) -> int:
    from app.database import async_session_factory  # noqa: PLC0415

    async with async_session_factory() as session:
        rows = await find_duplicate_claim_invoices(session)
    if as_json:
        print(json.dumps(rows, indent=2))
    elif not rows:
        print("No unlinked claim invoices found.")
    else:
        for row in rows:
            twin = f"duplicates {row['linked_invoice_number']}" if row["kind"] == "duplicate" else "only invoice"
            print(
                f"{row['invoice_number']} ({row['status']}, {row['direction']}) claim {row['claim_number']}: "
                f"total {row['amount_total']}, retention {row['retention_amount']}, {twin}"
            )
    return 1 if rows else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="report_duplicate_claim_invoices",
        description="List unlinked invoices raised from certified claims by releases before 18.1. Read-only.",
    )
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.json))


if __name__ == "__main__":
    raise SystemExit(main())
