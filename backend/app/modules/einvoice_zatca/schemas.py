# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes for the ZATCA onboarding API.

No response shape has a field for a private key, a secret or a token: the
unit's credentials never leave the service.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UnitCreateRequest(BaseModel):
    profile_id: uuid.UUID
    unit_key: str = Field(min_length=1, max_length=120)
    # Organisation, branch, invoice types ("1100" = standard and simplified), location, industry.
    csr_fields: dict[str, Any] = Field(default_factory=dict)
    signer_kind: str = Field(default="stored_key", max_length=32)
    signer_config: dict[str, Any] = Field(default_factory=dict)
    # Empty: the developer portal for a sandbox registration, production for a live one.
    environment: str = Field(default="", max_length=32)


class CsrRequest(BaseModel):
    # Only for a unit stamped by a signing service, which makes its own CSR.
    csr_pem: str = ""


class OtpRequest(BaseModel):
    otp: str = Field(min_length=1, max_length=32)
    # Renewal of a unit stamped by a signing service brings the service's new CSR.
    csr_pem: str = ""


class UnitResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    profile_id: str
    unit_key: str
    csr_fields: dict[str, Any]
    state: str
    environment: str
    signer_kind: str
    signer_config: dict[str, Any]
    has_private_key: bool
    csr_pem: str
    compliance_request_id: str
    production_request_id: str
    certificate_not_after: str | None
    compliance_results: dict[str, Any]
    last_icv: int
    last_hash: str
    last_error: str


class EinvoiceZatcaListResponse(BaseModel):
    items: list[UnitResponse]
    total: int
    offset: int = 0
    limit: int = 50


class ApiPathResponse(BaseModel):
    name: str
    path: str
    method: str
    source: str
    needs_expert_review: bool


class EnvironmentResponse(BaseModel):
    key: str
    label: str
    base_url: str
    live: bool


class MetaResponse(BaseModel):
    states: list[str]
    transitions: dict[str, list[str]]
    signer_kinds: list[str]
    environments: list[EnvironmentResponse]
    api_paths: list[ApiPathResponse]
    unconfirmed: list[str]
