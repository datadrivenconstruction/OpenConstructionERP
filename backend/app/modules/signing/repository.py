# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠E-signature registry data-access layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.signing.models import Signature, SigningSession


class SigningRepository:
    """Data access for :class:`SigningSession` and :class:`Signature` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Sessions ────────────────────────────────────────────────────────

    async def get_session(self, session_id: uuid.UUID) -> SigningSession | None:
        return await self.session.get(SigningSession, session_id)

    async def list_sessions(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        capability: str | None = None,
    ) -> list[SigningSession]:
        stmt = select(SigningSession).where(SigningSession.project_id == project_id)
        if status is not None:
            stmt = stmt.where(SigningSession.status == status)
        if capability is not None:
            stmt = stmt.where(SigningSession.provider_capability == capability)
        stmt = stmt.order_by(SigningSession.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_sessions_for_document(self, document_ref: str) -> list[SigningSession]:
        """Every session opened against one document, newest first.

        The register is shared by every module that puts paper up for signature,
        so a subject module asks for its own document by reference rather than
        filtering a whole project's sessions itself. ``document_ref`` is indexed.
        """
        stmt = (
            select(SigningSession)
            .where(SigningSession.document_ref == document_ref)
            .order_by(SigningSession.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create_session(self, session: SigningSession) -> SigningSession:
        self.session.add(session)
        await self.session.flush()
        return session

    async def delete_session(self, session_id: uuid.UUID) -> None:
        row = await self.get_session(session_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    # ── Signatures ──────────────────────────────────────────────────────

    async def list_signatures_for_session(self, session_id: uuid.UUID) -> list[Signature]:
        stmt = select(Signature).where(Signature.session_id == session_id).order_by(Signature.signed_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_signatures_for_project(self, project_id: uuid.UUID) -> list[Signature]:
        stmt = select(Signature).where(Signature.project_id == project_id).order_by(Signature.signed_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_signature(self, signature: Signature) -> Signature:
        self.session.add(signature)
        await self.session.flush()
        return signature
