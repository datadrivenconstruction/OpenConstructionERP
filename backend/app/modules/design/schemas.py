"""Request and response bodies of /api/v1/design (contract ddc-erp-link/1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LinkCodeRequest(BaseModel):
    project_id: uuid.UUID
    action: Literal["open", "new", "generate"]
    revision_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _open_needs_revision(self) -> LinkCodeRequest:
        if self.action == "open" and self.revision_id is None:
            raise ValueError("revision_id is required when action is 'open'")
        return self


class LinkFile(BaseModel):
    """``ddc-link/1``; the UI saves it as a .ddclink file."""

    schema_: Literal["ddc-link/1"] = Field("ddc-link/1", alias="schema")
    erp_url: str
    project_id: uuid.UUID
    project_name: str
    code: str
    expires_at: datetime
    action: Literal["open", "new", "generate"]
    revision_id: uuid.UUID | None = None

    model_config = {"populate_by_name": True}


class ClientInfo(BaseModel):
    name: str = Field(default="", max_length=100)
    version: str = Field(default="", max_length=40)
    os: str = Field(default="", max_length=40)


class ExchangeRequest(BaseModel):
    code: str = Field(min_length=32, max_length=128)
    client: ClientInfo = ClientInfo()


class ExchangeResponse(BaseModel):
    token: str
    expires_at: datetime
    project_id: uuid.UUID


class LockView(BaseModel):
    held_by: str
    mine: bool
    expires_at: datetime


class RevisionView(BaseModel):
    """A stored revision: the manifest as uploaded plus what the ERP decided about it."""

    revision_id: uuid.UUID
    project_id: uuid.UUID
    number: int
    parent_revision_id: uuid.UUID | None
    status: Literal["shared", "published", "rejected", "archived"]
    source_kind: str
    depth_level: str | None
    brief_version: int | None
    message: str
    bim_model_id: uuid.UUID | None
    author_user_id: uuid.UUID
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_comment: str | None
    package_sha256: str
    package_bytes: int
    created_at: datetime
    manifest: dict

    @classmethod
    def of(cls, rev) -> RevisionView:
        return cls(
            revision_id=rev.id,
            project_id=rev.project_id,
            number=rev.number,
            parent_revision_id=rev.parent_id,
            status=rev.status,
            source_kind=rev.source_kind,
            depth_level=rev.depth_level or None,  # "" is stored for an import nobody rated (R16)
            brief_version=((rev.manifest or {}).get("source") or {}).get("brief_version"),
            message=rev.message,
            bim_model_id=rev.bim_model_id,
            author_user_id=rev.author_user_id,
            decided_by=rev.decided_by,
            decided_at=rev.decided_at,
            decision_comment=rev.decision_comment,
            package_sha256=rev.package_sha256,
            package_bytes=rev.package_bytes,
            created_at=rev.created_at,
            manifest=rev.manifest,
        )


class RevisionListResponse(BaseModel):
    items: list[RevisionView]
    total: int
    offset: int = 0
    limit: int = 50


class AcceptRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)
    # Project setting "ask": the person's answer to "also create a draft change order?" (R9).
    change_order: bool | None = None


class RejectRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)
