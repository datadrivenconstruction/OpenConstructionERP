# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accept-Language header parsing middleware.

Inspects the incoming ``Accept-Language`` HTTP header (RFC 7231) and an
optional ``?locale=`` query parameter to determine the best matching
locale for each request.  The resolved locale is pushed into the i18n
context via :func:`app.core.i18n.set_locale` and echoed back on the
response as a ``Content-Language`` header, unless the handler already
declared one of its own.

Priority:
  1. ``?locale=XX`` query parameter  (explicit override)
  2. ``Accept-Language`` header       (browser preference)
  3. ``"en"``                         (fallback)

What this resolves is what the reader *asked for*. What a handler serves
can be narrower - see :class:`AcceptLanguageMiddleware` on why the
handler's own answer wins when it sets one.
"""

import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.i18n import SUPPORTED_LOCALES, set_locale
from app.core.regional_format import reset_document_digits, set_document_digits

__all__ = [
    "AcceptLanguageMiddleware",
    "match_locale",
    "parse_accept_language",
]

# Pre-compiled pattern for a single Accept-Language tag.
# Matches: ``en``, ``en-US``, ``de-DE``, ``zh-Hant-TW``, etc.,
# with an optional ``;q=0.8`` quality suffix.
_TAG_RE = re.compile(
    r"^\s*"
    r"(?P<tag>[a-zA-Z]{1,8}(?:-[a-zA-Z0-9]{1,8})*|\*)"
    r"\s*(?:;\s*q=(?P<q>[01](?:\.\d{0,3})?))?"
    r"\s*$"
)


def parse_accept_language(header: str) -> list[tuple[str, float]]:
    """Parse an RFC 7231 ``Accept-Language`` header value.

    Args:
        header: Raw header string, e.g.
            ``"de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"``.

    Returns:
        A list of ``(language_tag, quality)`` tuples sorted by quality
        in descending order.  Returns an empty list for malformed or
        empty headers.
    """
    if not header or not header.strip():
        return []

    results: list[tuple[str, float]] = []
    for part in header.split(","):
        match = _TAG_RE.match(part)
        if match is None:
            continue
        tag = match.group("tag").strip()
        raw_q = match.group("q")
        try:
            quality = float(raw_q) if raw_q is not None else 1.0
        except ValueError:
            quality = 1.0
        # Clamp quality to [0.0, 1.0]
        quality = max(0.0, min(1.0, quality))
        results.append((tag, quality))

    # Stable sort by quality descending (preserves header order for ties).
    results.sort(key=lambda pair: pair[1], reverse=True)
    return results


def match_locale(
    tags: list[tuple[str, float]],
    supported: list[str] | None = None,
) -> str:
    """Match parsed language tags against the supported locale list.

    The algorithm tries, for each tag in priority order:
      1. Exact (case-insensitive) match: ``de`` == ``de``
      2. Prefix match: ``de-DE`` → ``de``, ``pt-BR`` → ``pt``

    Args:
        tags: Output of :func:`parse_accept_language`.
        supported: Override list of supported locale codes.  Falls back to
            :data:`app.core.i18n.SUPPORTED_LOCALES`.

    Returns:
        The best matching locale code, or ``"en"`` if nothing matches.
    """
    available = supported if supported is not None else SUPPORTED_LOCALES

    for tag, _quality in tags:
        tag_lower = tag.lower()

        # 1. Exact match (e.g. "de" in supported)
        if tag_lower in available:
            return tag_lower

        # 2. Prefix match (e.g. "de-DE" → "de", "zh-CN" → "zh")
        prefix = tag_lower.split("-")[0]
        if prefix in available:
            return prefix

    return "en"


class AcceptLanguageMiddleware(BaseHTTPMiddleware):
    """Sets the i18n context locale based on the incoming request.

    Inspects the ``?locale=`` query parameter first; if absent, falls
    back to parsing the ``Accept-Language`` header.  The resolved locale
    is stored in the async context via :func:`set_locale` and reflected
    back as a ``Content-Language`` response header *unless the handler
    already set one*.

    The exception matters for documents. This middleware resolves against
    :data:`app.core.i18n.SUPPORTED_LOCALES`, but a PDF renderer draws on
    its own, much smaller string catalogue. When the two disagree the
    renderer is right, so a handler that declares the language it really
    produced keeps it.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        locale = self._resolve_locale(request)
        set_locale(locale)
        # The digit shapes documents print in, when the reader chose them
        # (see app.core.regional_format). ``?digits=`` wins over the header the
        # web client sends, the same order the locale itself follows. An
        # unknown value is recorded as no choice, so the market decides.
        digits = request.query_params.get("digits") or request.headers.get("x-digit-system")
        token = set_document_digits(digits)
        try:
            response = await call_next(request)
        finally:
            reset_document_digits(token)
        # ``setdefault``, not assignment: this middleware knows what the
        # reader asked for, not what the handler was able to produce. A
        # document route that renders from a narrower catalogue than
        # SUPPORTED_LOCALES sets the header to the language it actually
        # rendered, and that answer must survive. Overwriting it here made
        # every PDF served in an unsupported language claim to be in that
        # language while carrying English text.
        response.headers.setdefault("Content-Language", locale)
        return response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_locale(request: Request) -> str:
        """Determine the best locale for *request*.

        Priority:
          1. ``?locale=`` query parameter
          2. ``Accept-Language`` header
          3. ``"en"`` fallback
        """
        # 1. Explicit query parameter override
        query_locale = request.query_params.get("locale")
        if query_locale:
            normalized = query_locale.strip().lower()
            if normalized in SUPPORTED_LOCALES:
                return normalized
            # Try prefix (e.g. "de-DE" → "de")
            prefix = normalized.split("-")[0]
            if prefix in SUPPORTED_LOCALES:
                return prefix

        # 2. Accept-Language header
        accept = request.headers.get("accept-language", "")
        if accept:
            tags = parse_accept_language(accept)
            return match_locale(tags)

        # 3. Default
        return "en"
