# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Record Publishing API routes.

Mounted by the module loader at ``/api/v1/record-publishing``.

Endpoints
~~~~~~~~~
* ``GET  /kinds/``                       - which record kinds can be published
* ``POST /publish/``                     - render + store + transmit a record
* ``GET  /record/{token}``               - public, token-gated record PDF
* ``GET  /{transmittal_id}/record.pdf``  - project-member record PDF download
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.record_publishing.schemas import (
    PublishRecordRequest,
    PublishRecordResponse,
    SupportedKindsResponse,
)
from app.modules.record_publishing.service import RecordPublishingService, supported_kinds

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Record Publishing"])


def _get_service(session: SessionDep) -> RecordPublishingService:
    return RecordPublishingService(session)


@router.get("/kinds/", response_model=SupportedKindsResponse)
async def list_kinds() -> SupportedKindsResponse:
    """List the record kinds that can currently be published."""
    return SupportedKindsResponse(kinds=supported_kinds())


@router.post(
    "/publish/",
    response_model=PublishRecordResponse,
    dependencies=[Depends(RequirePermission("record_publishing.publish"))],
)
async def publish_record(
    data: PublishRecordRequest,
    user_id: CurrentUserId,
    service: RecordPublishingService = Depends(_get_service),
) -> PublishRecordResponse:
    """Render a project record as a PDF and distribute it with acknowledgement.

    Project access is enforced inside the service against the record's own
    project, so a caller cannot publish a record from a project they cannot
    reach. The response carries, per recipient, the record download URL and the
    acknowledgement URL to forward.
    """
    payload = await service.publish_and_distribute(data, user_id=user_id)
    return PublishRecordResponse(**payload)


@router.get("/record/{token}")
async def download_record_public(
    token: str,
    service: RecordPublishingService = Depends(_get_service),
) -> Response:
    """Return the published record PDF for a recipient's token (public).

    Token-gated, no auth: the acknowledgement token minted per recipient is the
    bearer credential, mirroring the public acknowledgement endpoint on the
    transmittals module.
    """
    data, media_type, filename = await service.read_record_by_token(token)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": attachment_disposition(filename, inline=True)},
    )


@router.get(
    "/{transmittal_id}/record.pdf",
    dependencies=[Depends(RequirePermission("record_publishing.read"))],
)
async def download_record(
    transmittal_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RecordPublishingService = Depends(_get_service),
) -> Response:
    """Download a published record PDF as an authenticated project member."""
    data, media_type, filename = await service.read_record(transmittal_id, user_id)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": attachment_disposition(filename)},
    )
