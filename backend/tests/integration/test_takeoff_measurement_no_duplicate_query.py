# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pin the Round-6 N+1 fix on the measurement PATCH / DELETE / link path.

Pre-fix, ``service.update_measurement`` / ``delete_measurement`` /
``link_measurement_to_boq`` each ran ``self.get_measurement(...)`` even
though the router had *already* fetched the row for the IDOR check via
``verify_project_access``. That doubled the ``SELECT`` count on every
mutation — visible as a 2× SQL load when an estimator was bulk-editing
measurements on a large takeoff.

This test patches ``MeasurementRepository.get_by_id`` and asserts the
service uses the pre-fetched row when one is supplied via the new
``existing=`` kwarg — so the production code path stays at exactly one
lookup per request.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_update_measurement_with_existing_row_skips_lookup() -> None:
    """When the router pre-fetches the row, the service must not re-query."""
    from unittest.mock import AsyncMock, patch

    from app.modules.takeoff.models import TakeoffMeasurement
    from app.modules.takeoff.schemas import TakeoffMeasurementUpdate
    from app.modules.takeoff.service import TakeoffService

    fake_session = AsyncMock()
    service = TakeoffService(fake_session)

    # Hand-build a "row" with the attributes that update_measurement
    # touches when no geometry-relevant patch fields are present.
    row = TakeoffMeasurement(
        type="area",
        points=[],
        scale_pixels_per_unit=None,
        count_value=None,
        measurement_value=None,
    )

    with (
        patch.object(
            service.measurement_repo,
            "get_by_id",
            new=AsyncMock(),
        ) as get_mock,
        patch.object(
            service.measurement_repo,
            "update_fields",
            new=AsyncMock(),
        ),
    ):
        await service.update_measurement(
            measurement_id=row.id if row.id else __import__("uuid").uuid4(),
            data=TakeoffMeasurementUpdate(annotation="updated"),
            existing=row,
        )
        # With ``existing`` supplied, the service must not call get_by_id
        # at all (the router already did it for the IDOR gate).
        assert get_mock.await_count == 0, (
            f"update_measurement re-fetched the row {get_mock.await_count}× "
            "despite ``existing=`` being passed. That re-introduces the "
            "duplicate-query regression Round-6 caught."
        )


@pytest.mark.asyncio
async def test_delete_measurement_with_existing_row_skips_lookup() -> None:
    """delete_measurement must accept ``existing`` and skip the re-fetch."""
    from unittest.mock import AsyncMock, patch

    from app.modules.takeoff.models import TakeoffMeasurement
    from app.modules.takeoff.service import TakeoffService

    fake_session = AsyncMock()
    service = TakeoffService(fake_session)

    row = TakeoffMeasurement()

    with (
        patch.object(
            service.measurement_repo,
            "get_by_id",
            new=AsyncMock(),
        ) as get_mock,
        patch.object(
            service.measurement_repo,
            "delete",
            new=AsyncMock(),
        ),
    ):
        import uuid as _uuid

        await service.delete_measurement(
            measurement_id=_uuid.uuid4(),
            existing=row,
        )
        assert get_mock.await_count == 0, (
            f"delete_measurement re-fetched the row {get_mock.await_count}× despite ``existing=`` being passed."
        )


@pytest.mark.asyncio
async def test_link_measurement_to_boq_with_existing_row_skips_lookup() -> None:
    """link_measurement_to_boq must accept ``existing`` and skip the re-fetch."""
    import uuid as _uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from app.modules.boq.repository import PositionRepository
    from app.modules.boq.service import BOQService
    from app.modules.takeoff.models import TakeoffMeasurement
    from app.modules.takeoff.service import TakeoffService

    fake_session = AsyncMock()
    service = TakeoffService(fake_session)

    project_id = _uuid.uuid4()
    row = TakeoffMeasurement(project_id=project_id)

    # ``boq_position_id`` arrives as a plain string - ``LinkToBoqRequest``
    # types it ``str`` and the column is ``String(255)`` - so the service
    # parses it into a UUID before it may touch the BOQ repository, and
    # answers 422 on anything that is not one. Hand it a real UUID: with a
    # placeholder the call stops at that format guard and never reaches the
    # lookup this test is about.
    position_id = _uuid.uuid4()
    position = SimpleNamespace(id=position_id, boq_id=_uuid.uuid4())
    # Same project as the measurement, so the IDOR guard passes for the right
    # reason rather than because it was stubbed out.
    boq = SimpleNamespace(project_id=project_id)

    with (
        # ``return_value=row`` keeps the re-fetch path fully working, so the
        # await count below is the ONLY thing separating a service that uses
        # ``existing`` from one that queries again.
        patch.object(
            service.measurement_repo,
            "get_by_id",
            new=AsyncMock(return_value=row),
        ) as get_mock,
        patch.object(
            service.measurement_repo,
            "update_fields",
            new=AsyncMock(),
        ),
        patch.object(
            PositionRepository,
            "get_by_id",
            new=AsyncMock(return_value=position),
        ),
        patch.object(
            BOQService,
            "get_boq",
            new=AsyncMock(return_value=boq),
        ),
    ):
        await service.link_measurement_to_boq(
            measurement_id=_uuid.uuid4(),
            boq_position_id=str(position_id),
            existing=row,
        )
        assert get_mock.await_count == 0, (
            f"link_measurement_to_boq re-fetched the row {get_mock.await_count}× despite ``existing=`` being passed."
        )
