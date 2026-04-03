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
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Random per-process hash — no machine identification, GDPR compliant
_INSTANCE_HASH = hashlib.sha256(f"DDC-OE-{uuid.uuid4()}".encode()).hexdigest()[:16]


class DDCFingerprintMiddleware(BaseHTTPMiddleware):
    """Adds origin headers to all API responses.

    Internal reference: DDC-CWICR-OE-2026-FP
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Powered-By"] = "OpenConstructionERP"
        response.headers["X-DDC-Engine"] = "CWICR/1.0"
        response.headers["X-DDC-Build"] = _INSTANCE_HASH
        return response
