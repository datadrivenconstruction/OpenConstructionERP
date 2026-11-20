# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The old tendering and RFQ routes, kept as deprecated adapters over the one tender model.

Founder decision (19.11.2026): the old routes and API stay for two minor
releases or 90 days, whichever is longer. Every response from them carries

* ``Deprecation`` (RFC 9745): the date the route was deprecated;
* ``Sunset`` (RFC 8594): the earliest date it may go (90 days later; removal
  also waits for the second minor release after deprecation);
* ``Link`` with ``rel="successor-version"``: the canonical tenders API.

The same handlers are also mounted under the canonical tenders API
(``/api/v1/bid-management/tenders/main-contract/`` and ``.../tenders/rfq/``, see
``tender_routes``). There they are current and send no deprecation headers; the
``Link`` header of an old route names the exact canonical path that replaces it.

A path id may be the old id or the canonical id of the same record: the route
class looks a canonical id up in ``oe_tender_legacy_map`` and hands the old
handler the id it knows.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import select

logger = logging.getLogger(__name__)

DEPRECATED_ON = datetime(2026, 11, 20, tzinfo=UTC)
SUNSET_DAYS = 90
#: The release that may first drop the routes: two minor releases after 19.9.
REMOVAL_NOT_BEFORE_VERSION = "20.1.0"
SUCCESSOR = "/api/v1/bid-management/tenders/"
#: Old mount -> canonical mount of the same handlers.
CANONICAL_MOUNTS: dict[str, str] = {
    "/api/v1/tendering": "/api/v1/bid-management/tenders/main-contract",
    "/api/v1/rfq-bidding": "/api/v1/bid-management/tenders/rfq",
    "/api/v1/rfq_bidding": "/api/v1/bid-management/tenders/rfq",
}
_CANONICAL_MARKERS = ("/bid-management/tenders/", "/bid_management/tenders/")


def sunset_at() -> datetime:
    """Earliest removal date of the deprecated routes."""
    return DEPRECATED_ON + timedelta(days=SUNSET_DAYS)


def successor_path(path: str) -> str:
    """The canonical path that replaces an old tendering or RFQ path."""
    for old, new in CANONICAL_MOUNTS.items():
        if path == old or path.startswith(old + "/"):
            return new + path[len(old) :]
    return SUCCESSOR


def is_canonical_path(path: str) -> bool:
    """Whether a route path sits under the canonical tenders API."""
    return any(marker in path for marker in _CANONICAL_MARKERS)


def deprecation_headers(path: str | None = None) -> dict[str, str]:
    """The three headers every deprecated tender route sends."""
    return {
        "Deprecation": f"@{int(DEPRECATED_ON.timestamp())}",
        "Sunset": format_datetime(sunset_at(), usegmt=True),
        "Link": f'<{successor_path(path) if path else SUCCESSOR}>; rel="successor-version"',
    }


def _uuid_or_none(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


async def old_ids_for(values: list[str], families: tuple[str, ...]) -> dict[str, str]:
    """Canonical id -> old id, for the values that are canonical ids of copied rows."""
    if not values:
        return {}
    from app.database import async_session_factory  # noqa: PLC0415
    from app.modules.bid_management.models import TenderLegacyMap  # noqa: PLC0415

    try:
        async with async_session_factory() as session:
            rows = (
                await session.execute(
                    select(TenderLegacyMap.target_id, TenderLegacyMap.source_id).where(
                        TenderLegacyMap.target_id.in_(values), TenderLegacyMap.source_table.in_(families)
                    )
                )
            ).all()
    except Exception:  # noqa: BLE001 - an unreadable map must not take the old route down
        logger.debug("tender legacy map lookup failed", exc_info=True)
        return {}
    return {str(t): str(s) for t, s in rows}


class _LegacyTenderRoute(APIRoute):
    """Route class of the deprecated routes: id translation plus deprecation headers."""

    families: tuple[str, ...] = ()

    def __init__(self, path: str, *args: Any, **kwargs: Any) -> None:
        super().__init__(path, *args, **kwargs)
        # Decided by the final path: an include copies the flag from the staging route.
        self.deprecated = self._is_deprecated()

    def _is_deprecated(self) -> bool:
        # The bidder portal stays: its links are already in bidders' mailboxes.
        return "/bid-portal/" not in self.path and not is_canonical_path(self.path)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        families = self.families
        deprecated = self._is_deprecated()

        async def handler(request: Request) -> Response:
            params = request.scope.get("path_params") or {}
            candidates = {k: v for k, v in params.items() if (u := _uuid_or_none(v)) and u == str(v).lower()}
            if candidates:
                found = await old_ids_for(list({str(v) for v in candidates.values()}), families)
                if found:
                    request.scope["path_params"] = {k: found.get(str(v), v) for k, v in params.items()}
            response = await original(request)
            if deprecated:
                for name, value in deprecation_headers(request.url.path).items():
                    response.headers.setdefault(name, value)
            return response

        return handler


class LegacyTenderingRoute(_LegacyTenderRoute):
    """Route class for ``/api/v1/tendering``."""

    families = (
        "oe_tendering_package",
        "oe_tendering_bid",
        "oe_tendering_bid_invitation",
        "oe_tendering_clarification",
    )


class LegacyRFQRoute(_LegacyTenderRoute):
    """Route class for ``/api/v1/rfq-bidding``."""

    families = ("oe_rfq_rfq", "oe_rfq_line", "oe_rfq_bid", "oe_rfq_bid_line", "oe_rfq_bid_adjustment", "oe_rfq_award")
