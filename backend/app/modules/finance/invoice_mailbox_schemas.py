# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request / response shapes for the invoice mailbox settings."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MailboxUpdate(BaseModel):
    """Settings write. ``password`` None or empty keeps the stored one."""

    enabled: bool = False
    host: str = Field(default="", max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    use_ssl: bool = True
    username: str = Field(default="", max_length=255)
    password: str | None = Field(default=None, max_length=500)
    folder: str = Field(default="INBOX", max_length=255)
    processed_folder: str = Field(default="", max_length=255)
    intake_address: str = Field(default="", max_length=255)


class MailboxTest(BaseModel):
    host: str = Field(max_length=255)
    port: int = Field(default=993, ge=1, le=65535)
    use_ssl: bool = True
    username: str = Field(max_length=255)
    password: str | None = Field(default=None, max_length=500)
    folder: str = Field(default="INBOX", max_length=255)


class MailboxTestResult(BaseModel):
    ok: bool
    message_count: int | None = None
    error: str | None = None


class MailboxResponse(BaseModel):
    """Stored settings; the password is never returned."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID | None = None
    enabled: bool = False
    host: str = ""
    port: int = 993
    use_ssl: bool = True
    username: str = ""
    has_password: bool = False
    folder: str = "INBOX"
    processed_folder: str = ""
    intake_address: str = ""
    last_polled_at: str | None = None
    last_error: str | None = None
