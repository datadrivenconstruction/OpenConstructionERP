# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge business logic.

ONE payload builder stands behind the preview and the real draft, so what
the preview shows is byte-for-byte what opens in Outlook: two builders
drift, and what goes out stops being what was approved. Money-rail
stripping happens inside the builder, so no caller can leak an internal
figure by skipping a step.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.correspondence.models import Correspondence
from app.modules.outlook_bridge import outbound

logger = logging.getLogger(__name__)

_ATTACH_DIR = Path("uploads/outlook_bridge")


class BridgeError(Exception):
    """Router-facing errors (404s, bad state)."""


async def _contact_names_emails(session: AsyncSession, contact_ids: list[str]) -> list[tuple[str, str]]:
    """(display name, email) for each contact id; unknown ids are skipped.

    oe_contacts is an optional dependency - degrade to empty rather than
    refusing to build an email at all.
    """
    if not contact_ids:
        return []
    try:
        from app.modules.contacts.models import Contact
    except ImportError:  # pragma: no cover
        return []
    ids: list[uuid.UUID] = []
    for cid in contact_ids:
        try:
            ids.append(uuid.UUID(str(cid)))
        except ValueError:
            continue
    if not ids:
        return []
    rows = (await session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars().all()
    out: list[tuple[str, str]] = []
    for c in rows:
        name = c.company_name or " ".join(x for x in [c.first_name, c.last_name] if x) or (c.primary_email or "")
        if c.primary_email:
            out.append((name, c.primary_email))
    return out


async def build_email_payload(
    session: AsyncSession,
    correspondence_id: str,
    *,
    subject_override: str | None = None,
    body_override: str | None = None,
    extra_to: list[str] | None = None,
) -> dict[str, Any]:
    """The single source of truth for one register email.

    Returns ``{to, cc, bcc, subject, html, notified, attachments}``. Used
    verbatim by BOTH the preview endpoint and the open-draft endpoint.
    """
    try:
        cid = uuid.UUID(str(correspondence_id))
    except ValueError as exc:
        raise BridgeError("Correspondence not found") from exc
    row = (await session.execute(select(Correspondence).where(Correspondence.id == cid))).scalar_one_or_none()
    if row is None:
        raise BridgeError("Correspondence not found")

    recipients = await _contact_names_emails(session, list(row.to_contact_ids or []))
    to = [email for _n, email in recipients] + [a for a in (extra_to or []) if a]
    today = datetime.now(UTC).strftime("%d/%m/%Y")
    notified = [(name, today) for name, _e in recipients]

    # Project line for the navy2 sub-bar - the job named as it is on the
    # project, so a recipient recognises it without opening anything.
    project_name = ""
    try:
        from app.modules.projects.models import Project

        project_name = (
            await session.execute(select(Project.name).where(Project.id == row.project_id))
        ).scalar_one_or_none() or ""
    except Exception:  # noqa: BLE001 - the email builds without it
        pass

    # Subject convention, ported: TYPE - COMPANY - ref - short description.
    kind_map = {"letter": "LETTER", "email": "EMAIL", "notice": "NOTICE", "memo": "MEMO"}
    kind = kind_map.get((row.correspondence_type or "email").lower(), "EMAIL")
    company = recipients[0][0].upper() if recipients else ""
    ref = row.reference_number or ""
    subject_bits = [kind] + ([company] if company else []) + [ref, row.subject or ""]
    subject = subject_override or " - ".join(b for b in subject_bits if b)

    pairs: list[tuple[str, str]] = [
        ("Reference", ref),
        ("Date", today),
    ]
    if row.response_required_by:
        pairs.append(("Response required by", row.response_required_by))
    if row.contract_clause_ref:
        pairs.append(("Contract clause", row.contract_clause_ref))

    # The captured original, formatting intact - sanitised at capture time,
    # so it is already safe to embed. A typed body_override still wins.
    source_html = ""
    if body_override is None:
        source_html = str((row.metadata_ or {}).get("source_html") or "")
    # One dict of content, two renderings: the HTML part and the
    # text/plain alternative that rides beside it in the .eml. Built from
    # the same data rather than scraped from the markup - see
    # outbound.build_register_email_text.
    content = {
        "eyebrow": "Project correspondence",
        "title": row.subject or ref,
        "project_line": project_name or f"Register entry {ref}",
        "intro": "Please see the correspondence below and respond by return.",
        "pairs": pairs,
        "body_text": body_override if body_override is not None else (row.notes or ""),
        "body_html": source_html,
        "notified": notified,
        "footer_ref": ref,
        "greeting": f"Hi {recipients[0][0].split()[0]}," if recipients else "Hi,",
        "hero_right": ref,
    }
    html = outbound.build_register_email_html(**content)
    return {
        "correspondence_id": str(row.id),
        "reference_number": ref,
        "to": to,
        # The standing CC is how replies reach the ERP mailbox for capture:
        # without it a reply lands in one person's inbox and the record
        # never sees it. Env-overridable per install (OE_OUTLOOK_CC,
        # comma-sep; set it empty to disable).
        "cc": _standing_cc(),
        "bcc": [],
        "subject": subject,
        "html": html,
        "text": outbound.build_register_email_text(**content),
        "notified": [{"name": n, "date": d} for n, d in notified],
        "attachments": [],
    }


def _standing_cc() -> list[str]:
    import os

    raw = os.environ.get("OE_OUTLOOK_CC", "")
    return [a.strip() for a in raw.split(",") if a.strip()]


async def open_payload_in_outlook(
    session: AsyncSession, payload: dict[str, Any], *, user_id: str | None
) -> dict[str, Any]:
    """Open the payload as an Outlook draft and log it on the record.

    The 📧 log matters: it is what "sent to N" is counted from. It lands
    in the correspondence metadata under ``outlook_drafts`` and
    republishes ``correspondence.updated``.
    """
    run_dir = _ATTACH_DIR / "outbound"
    run_dir.mkdir(parents=True, exist_ok=True)
    html_path = run_dir / f"{uuid.uuid4().hex[:12]}.html"
    # utf-8-sig: the BOM lets Windows PowerShell 5.1 auto-detect UTF-8 even
    # if a reader forgets -Encoding UTF8 (its default is ANSI, which turned
    # every non-ASCII character in a draft body into mojibake).
    html_path.write_text(payload["html"], encoding="utf-8-sig")

    result = await outbound.open_draft(
        to=payload["to"],
        cc=payload.get("cc") or [],
        bcc=payload.get("bcc") or [],
        subject=payload["subject"],
        html_body_path=str(html_path),
        attachment_paths=payload.get("attachments") or [],
    )
    if not result.get("ok"):
        raise BridgeError(str(result.get("error", "Outlook draft failed")))

    # A register-item draft carries no correspondence UUID - its send is
    # logged by record_send on the item itself, so there is nothing to do
    # here and no warning to raise about it.
    try:
        cid = uuid.UUID(str(payload.get("correspondence_id") or ""))
    except ValueError:
        return {"opened": True, "attached": result.get("attached", []), "missing": result.get("missing", [])}
    try:
        row = (await session.execute(select(Correspondence).where(Correspondence.id == cid))).scalar_one_or_none()
        if row is not None:
            meta = dict(row.metadata_ or {})
            log = list(meta.get("outlook_drafts") or [])
            log.append(
                {
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "to": payload["to"],
                    "subject": payload["subject"],
                    "by": user_id,
                }
            )
            meta["outlook_drafts"] = log
            row.metadata_ = meta
            await session.flush()
    except Exception:  # noqa: BLE001 - the draft opened; logging is best-effort
        logger.warning("Outlook draft log skipped", exc_info=True)
    return {"opened": True, "attached": result.get("attached", []), "missing": result.get("missing", [])}
