"""Contacts API routes.

Endpoints:
    GET    /                — List contacts with filters
    POST   /                — Create contact (auth required)
    GET    /search          — Text search across name, company, email
    GET    /{contact_id}    — Get single contact
    PATCH  /{contact_id}    — Update contact (auth required)
    DELETE /{contact_id}    — Soft-delete contact (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactListResponse,
    ContactResponse,
    ContactUpdate,
)
from app.modules.contacts.service import ContactService

router = APIRouter()


def _get_service(session: SessionDep) -> ContactService:
    return ContactService(session)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get("/", response_model=ContactListResponse)
async def list_contacts(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    contact_type: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    is_active: bool = Query(default=True),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ContactService = Depends(_get_service),
) -> ContactListResponse:
    """List contacts with optional filters."""
    items, total = await service.list_contacts(
        contact_type=contact_type,
        country_code=country_code,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return ContactListResponse(
        items=[ContactResponse.model_validate(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


# ── Search ────────────────────────────────────────────────────────────────────


@router.get("/search", response_model=ContactListResponse)
async def search_contacts(
    q: str = Query(..., min_length=1, max_length=200),
    contact_type: str | None = Query(default=None),
    is_active: bool = Query(default=True),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ContactService = Depends(_get_service),
) -> ContactListResponse:
    """Search contacts across name, company, email."""
    items, total = await service.list_contacts(
        search=q,
        contact_type=contact_type,
        is_active=is_active,
        offset=offset,
        limit=limit,
    )
    return ContactListResponse(
        items=[ContactResponse.model_validate(c) for c in items],
        total=total,
        offset=offset,
        limit=limit,
    )


# ── Create ────────────────────────────────────────────────────────────────────


@router.post("/", response_model=ContactResponse, status_code=201)
async def create_contact(
    data: ContactCreate,
    user_id: CurrentUserId,
    service: ContactService = Depends(_get_service),
) -> ContactResponse:
    """Create a new contact."""
    contact = await service.create_contact(data, user_id=user_id)
    return ContactResponse.model_validate(contact)


# ── Get ───────────────────────────────────────────────────────────────────────


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ContactService = Depends(_get_service),
) -> ContactResponse:
    """Get a single contact by ID."""
    contact = await service.get_contact(contact_id)
    return ContactResponse.model_validate(contact)


# ── Update ────────────────────────────────────────────────────────────────────


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: uuid.UUID,
    data: ContactUpdate,
    user_id: CurrentUserId,
    service: ContactService = Depends(_get_service),
) -> ContactResponse:
    """Update a contact."""
    contact = await service.update_contact(contact_id, data)
    return ContactResponse.model_validate(contact)


# ── Delete (soft) ─────────────────────────────────────────────────────────────


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ContactService = Depends(_get_service),
) -> None:
    """Soft-delete a contact (set is_active=False)."""
    await service.deactivate_contact(contact_id)
