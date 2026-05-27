"""Webhook Leads API routes.

Mounted at ``/api/v1/webhook-leads/``.

The public ingestion endpoint ``POST /incoming/{source_slug}/`` is NOT
gated by the platform JWT — it authenticates against the per-source
credential inside the service. Every other (admin) endpoint is gated
through ``RequirePermission`` like the rest of the platform.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.webhook_leads.schemas import (
    IngestionResponse,
    PayloadMappingCreate,
    PayloadMappingResponse,
    PayloadMappingUpdate,
    SecretRotateResponse,
    WebhookLogResponse,
    WebhookSourceCreate,
    WebhookSourceCreatedResponse,
    WebhookSourceResponse,
    WebhookSourceUpdate,
)
from app.modules.webhook_leads.service import WebhookLeadsService

router = APIRouter()


def _get_service(session: SessionDep) -> WebhookLeadsService:
    return WebhookLeadsService(session)


def _ingestion_url(request: Request, slug: str) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/webhook-leads/incoming/{slug}/"


# ── Public ingestion endpoint (per-source credential auth) ────────────────


@router.post(
    "/incoming/{source_slug}/",
    response_model=IngestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_webhook(
    source_slug: str,
    request: Request,
    response: Response,
    service: WebhookLeadsService = Depends(_get_service),
) -> IngestionResponse:
    """Public ingestion endpoint — auth via the source's configured method.

    Reads the RAW request body bytes (required for correct HMAC
    verification) and only then parses JSON. Every attempt is audit
    logged inside the service before any response is returned.
    """
    raw_body = await request.body()
    try:
        parsed = json.loads(raw_body) if raw_body else {}
    except (ValueError, TypeError):
        parsed = {"_raw": raw_body[:2000].decode("utf-8", "replace")}

    # Lower-case header map; resolve client IP the same way the platform
    # rate limiter does (honour X-Forwarded-For behind a proxy).
    from app.core.rate_limiter import client_identifier

    headers = {k.lower(): v for k, v in request.headers.items()}
    remote_ip = client_identifier(request)

    log, lead_id = await service.ingest(
        source_slug=source_slug,
        raw_body=raw_body,
        parsed_payload=parsed,
        headers=headers,
        remote_ip=remote_ip,
    )
    response.headers["X-Webhook-Log-Id"] = str(log.id)
    return IngestionResponse(status="accepted", lead_id=lead_id, log_id=log.id)


# ── Sources CRUD (admin) ──────────────────────────────────────────────────


@router.get("/sources/", response_model=list[WebhookSourceResponse])
async def list_sources(
    is_active: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("webhook_leads.read")),
    service: WebhookLeadsService = Depends(_get_service),
) -> list[WebhookSourceResponse]:
    items, _ = await service.source_repo.list_all(offset=offset, limit=limit, is_active=is_active)
    return [WebhookSourceResponse.model_validate(s) for s in items]


@router.post(
    "/sources/",
    response_model=WebhookSourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source(
    data: WebhookSourceCreate,
    request: Request,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("webhook_leads.create")),
    service: WebhookLeadsService = Depends(_get_service),
) -> WebhookSourceCreatedResponse:
    source, secret = await service.create_source(data, user_id=user_id)
    body = WebhookSourceResponse.model_validate(source).model_dump()
    return WebhookSourceCreatedResponse(
        **body,
        secret=secret,
        ingestion_url=_ingestion_url(request, source.slug),
    )


@router.get("/sources/{source_id}", response_model=WebhookSourceResponse)
async def get_source(
    source_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("webhook_leads.read")),
    service: WebhookLeadsService = Depends(_get_service),
) -> WebhookSourceResponse:
    return WebhookSourceResponse.model_validate(await service.get_source(source_id))


@router.patch("/sources/{source_id}", response_model=WebhookSourceResponse)
async def update_source(
    source_id: uuid.UUID,
    data: WebhookSourceUpdate,
    _perm: None = Depends(RequirePermission("webhook_leads.update")),
    service: WebhookLeadsService = Depends(_get_service),
) -> WebhookSourceResponse:
    return WebhookSourceResponse.model_validate(await service.update_source(source_id, data))


@router.post(
    "/sources/{source_id}/rotate-secret",
    response_model=SecretRotateResponse,
)
async def rotate_secret(
    source_id: uuid.UUID,
    request: Request,
    _perm: None = Depends(RequirePermission("webhook_leads.update")),
    service: WebhookLeadsService = Depends(_get_service),
) -> SecretRotateResponse:
    source, secret = await service.rotate_secret(source_id)
    return SecretRotateResponse(
        id=source.id,
        secret=secret,
        ingestion_url=_ingestion_url(request, source.slug),
    )


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("webhook_leads.delete")),
    service: WebhookLeadsService = Depends(_get_service),
) -> None:
    await service.delete_source(source_id)


# ── Mappings CRUD (admin) ─────────────────────────────────────────────────


@router.get(
    "/sources/{source_id}/mappings/",
    response_model=list[PayloadMappingResponse],
)
async def list_mappings(
    source_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("webhook_leads.read")),
    service: WebhookLeadsService = Depends(_get_service),
) -> list[PayloadMappingResponse]:
    items = await service.list_mappings(source_id)
    return [PayloadMappingResponse.model_validate(m) for m in items]


@router.post(
    "/sources/{source_id}/mappings/",
    response_model=PayloadMappingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mapping(
    source_id: uuid.UUID,
    data: PayloadMappingCreate,
    _perm: None = Depends(RequirePermission("webhook_leads.create")),
    service: WebhookLeadsService = Depends(_get_service),
) -> PayloadMappingResponse:
    return PayloadMappingResponse.model_validate(await service.create_mapping(source_id, data))


@router.patch("/mappings/{mapping_id}", response_model=PayloadMappingResponse)
async def update_mapping(
    mapping_id: uuid.UUID,
    data: PayloadMappingUpdate,
    _perm: None = Depends(RequirePermission("webhook_leads.update")),
    service: WebhookLeadsService = Depends(_get_service),
) -> PayloadMappingResponse:
    return PayloadMappingResponse.model_validate(await service.update_mapping(mapping_id, data))


@router.delete("/mappings/{mapping_id}", status_code=204)
async def delete_mapping(
    mapping_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("webhook_leads.delete")),
    service: WebhookLeadsService = Depends(_get_service),
) -> None:
    await service.delete_mapping(mapping_id)


# ── Logs (admin, read-only audit) ─────────────────────────────────────────


@router.get("/logs/", response_model=list[WebhookLogResponse])
async def list_logs(
    source_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("webhook_leads.read")),
    service: WebhookLeadsService = Depends(_get_service),
) -> list[WebhookLogResponse]:
    items, _ = await service.log_repo.list_all(
        offset=offset,
        limit=limit,
        source_id=source_id,
        status=status_filter,
    )
    return [WebhookLogResponse.model_validate(li) for li in items]
