# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mailbox settings and the poller that turns unseen e-mail into invoice captures."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.modules.finance import invoice_mailbox_logic as logic
from app.modules.finance.invoice_capture_service import InvoiceCaptureService
from app.modules.finance.invoice_mailbox_models import InvoiceMailbox
from app.modules.finance.invoice_mailbox_schemas import MailboxTest, MailboxUpdate

logger = logging.getLogger(__name__)

_ERROR_CAP = 500


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _config_of(row: InvoiceMailbox) -> logic.MailboxConfig:
    return logic.MailboxConfig(
        host=row.host,
        port=row.port,
        use_ssl=row.use_ssl,
        username=row.username,
        password=decrypt_secret(row.password_encrypted) or "",
        folder=row.folder or "INBOX",
        processed_folder=row.processed_folder or "",
    )


class InvoiceMailboxService:
    def __init__(self, session: AsyncSession, client_factory: logic.ClientFactory | None = None) -> None:
        self.session = session
        self.client_factory = client_factory or logic.default_client_factory

    async def get(self, project_id: uuid.UUID) -> InvoiceMailbox | None:
        stmt = select(InvoiceMailbox).where(InvoiceMailbox.project_id == project_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def upsert(self, project_id: uuid.UUID, data: MailboxUpdate) -> InvoiceMailbox:
        row = await self.get(project_id)
        has_password = bool(data.password) or bool(row and row.password_encrypted)
        errors = logic.validate_mailbox_settings(
            enabled=data.enabled,
            host=data.host,
            port=data.port,
            use_ssl=data.use_ssl,
            username=data.username,
            has_password=has_password,
            folder=data.folder,
            processed_folder=data.processed_folder,
            intake_address=data.intake_address,
        )
        if errors:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{"field": f, "code": c} for f, c in errors],
            )
        if row is None:
            row = InvoiceMailbox(project_id=project_id)
            self.session.add(row)
        row.enabled = data.enabled
        row.host = data.host.strip()
        row.port = data.port
        row.use_ssl = data.use_ssl
        row.username = data.username.strip()
        row.folder = data.folder.strip() or "INBOX"
        row.processed_folder = data.processed_folder.strip()
        row.intake_address = data.intake_address.strip()
        if data.password:
            row.password_encrypted = encrypt_secret(data.password)
        await self.session.flush()
        return row

    async def test(self, project_id: uuid.UUID, data: MailboxTest) -> dict[str, Any]:
        """Try the given (or stored) settings; never raises for a bad server."""
        row = await self.get(project_id)
        password = data.password or (decrypt_secret(row.password_encrypted) if row else "") or ""
        errors = logic.validate_mailbox_settings(
            enabled=True,
            host=data.host,
            port=data.port,
            use_ssl=data.use_ssl,
            username=data.username,
            has_password=bool(password),
            folder=data.folder,
            processed_folder="",
            intake_address="",
        )
        if errors:
            return {"ok": False, "message_count": None, "error": ", ".join(f"{f}:{c}" for f, c in errors)}
        cfg = logic.MailboxConfig(
            host=data.host.strip(),
            port=data.port,
            use_ssl=data.use_ssl,
            username=data.username.strip(),
            password=password,
            folder=data.folder.strip() or "INBOX",
        )
        try:
            count = await asyncio.to_thread(logic.check_connection, cfg, self.client_factory)
        except Exception as exc:  # noqa: BLE001 - report any transport failure to the caller
            return {"ok": False, "message_count": None, "error": str(exc)[:_ERROR_CAP]}
        return {"ok": True, "message_count": count, "error": None}

    async def poll(self, row: InvoiceMailbox) -> dict[str, int]:
        """Fetch unseen messages, capture their attachments, mark them done. Never raises."""
        counts = {"messages": 0, "created": 0, "duplicates": 0, "rejected": 0, "failed": 0}
        cfg = _config_of(row)
        try:
            fetched = await asyncio.to_thread(logic.fetch_unseen, cfg, self.client_factory)
            capture = InvoiceCaptureService(self.session)
            done: list[str] = []
            for msg in fetched:
                counts["messages"] += 1
                try:
                    async with self.session.begin_nested():
                        out = await capture.capture_from_email(project_id=row.project_id, raw=msg.raw, user_id=None)
                except Exception:  # noqa: BLE001 - one bad message must not stop the batch
                    logger.exception("invoice mailbox: message %s of project %s failed", msg.uid, row.project_id)
                    counts["failed"] += 1
                    continue  # stays unseen, retried on the next poll
                counts["created"] += len(out["created"])
                counts["duplicates"] += len(out["duplicates"])
                counts["rejected"] += len(out["rejected"])
                done.append(msg.uid)
            await asyncio.to_thread(logic.finish_messages, cfg, done, self.client_factory)
            row.last_error = f"{counts['failed']} message(s) failed" if counts["failed"] else None
        except Exception as exc:  # noqa: BLE001 - a dead mailbox is a status, not a crash
            logger.warning("invoice mailbox poll failed for project %s: %s", row.project_id, exc)
            row.last_error = str(exc)[:_ERROR_CAP]
        row.last_polled_at = _now_iso()
        await self.session.flush()
        return counts

    async def poll_all(self) -> dict[str, int]:
        total = {"mailboxes": 0, "created": 0, "failed": 0}
        rows = (await self.session.execute(select(InvoiceMailbox).where(InvoiceMailbox.enabled.is_(True)))).scalars()
        for row in list(rows):
            total["mailboxes"] += 1
            counts = await self.poll(row)
            total["created"] += counts["created"]
            total["failed"] += counts["failed"]
            await self.session.commit()
        return total
