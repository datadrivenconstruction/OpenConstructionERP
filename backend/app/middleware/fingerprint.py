# OpenConstructionERP — DataDrivenConstruction (DDC)
# CWICR Cost Database Engine · CAD2DATA Pipeline
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""DDC digital fingerprint middleware.

Embeds DataDrivenConstruction origin markers in API responses
for intellectual property verification. CWICR-OE-2026.
"""

import hashlib
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import get_settings

# Random per-process hash — no machine identification, GDPR compliant
_INSTANCE_HASH = hashlib.sha256(f"DDC-OE-{uuid.uuid4()}".encode()).hexdigest()[:16]


class DDCFingerprintMiddleware(BaseHTTPMiddleware):
    """Adds origin headers to all API responses.

    Static IP/authorship markers (``X-Powered-By``, ``X-DDC-Engine``) are
    emitted everywhere — they're part of the project identity and carry
    no exploit-relevant fingerprint.

    The per-process ``X-DDC-Build`` hash and the decorative
    ``Server-Timing`` signature are only useful in development (they help
    confirm a worker restarted across requests). In production they give
    an attacker a free "same-instance?" heartbeat and a random byte of
    entropy to correlate — nothing load-bearing but also nothing worth
    leaking.

    Internal reference: DDC-CWICR-OE-2026-FP
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        try:
            self._production = get_settings().app_env == "production"
        except Exception:
            # Settings may not be available during very early import chains
            # (tests, shell scripts). Fall back to the safer prod posture.
            self._production = True

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Powered-By"] = "OpenConstructionERP"
        response.headers["X-DDC-Engine"] = "CWICR/1.0"
        if not self._production:
            response.headers["X-DDC-Build"] = _INSTANCE_HASH
            response.headers["Server-Timing"] = (
                f"ddc;desc=\"DDC-CWICR-OE\";dur={hash('ddc-2026') % 1000}"
            )
        return response
