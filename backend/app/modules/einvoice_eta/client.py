# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ETA REST API, the calls this platform needs and nothing more.

Every call is documented on https://sdk.invoicing.eta.gov.eg/ (read
2026-10-19):

* login:              ``POST {identity}/connect/token`` (/api/01-login-as-taxpayer-system/)
* submit:             ``POST {api}/api/v1.0/documentsubmissions/`` (/einvoicingapi/01-submit-documents/)
* get submission:     ``GET  {api}/api/v1.0/documentsubmissions/{uuid}`` (/einvoicingapi/09-get-submission/)
* document details:   ``GET  {api}/api/v1.0/documents/{uuid}/details`` (/einvoicingapi/11-get-document-details/)
* document types:     ``GET  {api}/api/v1.0/documenttypes[/{id}]`` (/api/02-, /api/03-get-document-type/)
* cancel and reject:  ``PUT  {api}/api/v1.0/documents/state/{uuid}/state`` (/einvoicingapi/02-, 03-)

Tokens are cached for their lifetime, per identity host, client id, secret
(as a hash) and represented taxpayer, because ETA lists "a new token with every
call" as an anti-pattern it throttles (/integrationpractices/). The secret is
part of the key so that a registration naming someone else's client id is
never handed the token their secret earned. A 401 drops the cached token and
retries once.

Both base URLs come from a registration, so they pass
:func:`app.core.url_safety.resolve_and_validate_external_url` before the first
request: ETA is a public service, and an internal address (a proxy, say) has to
be opened by an administrator through ``OE_WEBHOOK_INTERNAL_ALLOWLIST``.

The transport is injectable, and the tests use :class:`httpx.MockTransport`
with responses shaped like the SDK's examples. Nothing in the test suite ever
reaches ETA.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.url_safety import UnsafeUrlError, resolve_and_validate_external_url

DEFAULT_TIMEOUT = 30.0
# Renew a little before ETA's stated expiry, so a token never dies mid-call.
TOKEN_MARGIN_SECONDS = 60


@dataclass(frozen=True)
class EtaEnvironment:
    """The two base URLs ETA hands out at onboarding."""

    identity_base_url: str
    api_base_url: str


class EtaApiError(RuntimeError):
    """ETA answered with an error, or did not answer.

    ``code`` is ETA's own error code (``BadStructure``, ``OperationPeriodOver``,
    ...) when it sent one.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "",
        details: Any = None,
        retry_after: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details
        self.retry_after = retry_after


class EtaDuplicateSubmission(EtaApiError):
    """ETA saw an identical submission from this taxpayer within the last 10 minutes."""


class EtaUrlRefused(EtaApiError):
    """A base URL failed the outbound URL policy. Nothing was sent."""


UrlGuard = Callable[[str], Awaitable[str]]

_TOKENS: dict[tuple[str, str, str, str], tuple[str, float]] = {}


def clear_token_cache() -> None:
    """Forget every cached token (tests; credential rotation)."""
    _TOKENS.clear()


def _error_from(response: httpx.Response) -> EtaApiError:
    code = ""
    message = response.text[:500]
    details: Any = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error") if isinstance(body.get("error"), dict) else body
        code = str(error.get("code") or body.get("error") or "")
        message = str(error.get("message") or body.get("error_description") or message)
        details = error.get("details")
    retry_after = response.headers.get("Retry-After", "")
    kind = (
        EtaDuplicateSubmission
        if code == "DuplicateSubmission" or (response.status_code == 422 and "duplicate" in message.lower())
        else EtaApiError
    )
    return kind(
        f"ETA answered {response.status_code}{f' {code}' if code else ''}: {message}",
        status=response.status_code,
        code=code,
        details=details,
        retry_after=retry_after,
    )


class EtaClient:
    """One taxpayer's (or intermediary's) session with ETA."""

    def __init__(
        self,
        environment: EtaEnvironment,
        *,
        client_id: str,
        client_secret: str,
        on_behalf_of: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
        url_guard: UrlGuard | None = None,
    ) -> None:
        if not environment.identity_base_url or not environment.api_base_url:
            raise EtaApiError("Both ETA base URLs (identity and API) must be configured.")
        if not client_id or not client_secret:
            raise EtaApiError("The ETA client id and secret are not available.")
        self.environment = environment
        self._client_id = client_id
        self._client_secret = client_secret
        self.on_behalf_of = on_behalf_of
        self._transport = transport
        self._timeout = timeout
        self._clock = clock
        self._url_guard = url_guard or resolve_and_validate_external_url
        self._urls_checked = False

    # ── Session ──────────────────────────────────────────────────────────────

    def _cache_key(self) -> tuple[str, str, str, str]:
        secret = hashlib.sha256(self._client_secret.encode("utf-8")).hexdigest()
        return (self.environment.identity_base_url.rstrip("/"), self._client_id, secret, self.on_behalf_of)

    async def _check_urls(self) -> None:
        if self._urls_checked:
            return
        for name, url in (
            ("identity", self.environment.identity_base_url),
            ("API", self.environment.api_base_url),
        ):
            if not url.strip().lower().startswith("https://"):
                raise EtaUrlRefused(
                    f"The ETA {name} base URL {url} is refused: it must be an https URL.", code="UnsafeUrl"
                )
            try:
                await self._url_guard(url)
            except UnsafeUrlError as exc:
                raise EtaUrlRefused(f"The ETA {name} base URL {url} is refused: {exc}", code="UnsafeUrl") from exc
        self._urls_checked = True

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def access_token(self, *, fresh: bool = False) -> str:
        """A bearer token, from the cache while it is still good."""
        await self._check_urls()
        key = self._cache_key()
        cached = _TOKENS.get(key)
        if cached and not fresh and cached[1] > self._clock():
            return cached[0]
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode("ascii")
        headers = {"Authorization": f"Basic {basic}"}
        if self.on_behalf_of:
            headers["onbehalfof"] = self.on_behalf_of
        url = f"{self.environment.identity_base_url.rstrip('/')}/connect/token"
        try:
            async with self._http() as http:
                response = await http.post(
                    url,
                    data={"grant_type": "client_credentials", "scope": "InvoicingAPI"},
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            raise EtaApiError(f"ETA login could not be reached: {exc}") from exc
        if response.status_code != 200:
            raise _error_from(response)
        body = response.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise EtaApiError("ETA login answered without an access token.")
        lifetime = float(body.get("expires_in") or 3600)
        _TOKENS[key] = (token, self._clock() + max(lifetime - TOKEN_MARGIN_SECONDS, 0))
        return token

    async def _call(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        ok: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        url = f"{self.environment.api_base_url.rstrip('/')}{path}"
        for attempt in (0, 1):
            token = await self.access_token(fresh=attempt == 1)
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            if content is not None:
                headers["Content-Type"] = "application/json"
            try:
                async with self._http() as http:
                    response = await http.request(
                        method, url, content=content, json=json_body, params=params, headers=headers
                    )
            except httpx.HTTPError as exc:
                raise EtaApiError(f"ETA could not be reached: {exc}") from exc
            if response.status_code == 401 and attempt == 0:
                # The token expired early or was revoked: log in again, once.
                _TOKENS.pop(self._cache_key(), None)
                continue
            if response.status_code not in ok:
                raise _error_from(response)
            return response
        raise EtaApiError("ETA refused the credentials twice.", status=401)

    # ── Calls ────────────────────────────────────────────────────────────────

    @staticmethod
    def submission_body(documents: list[str]) -> bytes:
        """``{"documents":[...]}`` around document texts, embedded verbatim.

        Not ``json.dumps`` of parsed documents: re-encoding would rewrite the
        number literals, and the bytes sent would stop being the bytes stored.
        """
        for text in documents:
            json.loads(text)  # refuse anything that is not JSON before it goes out
        return ('{"documents":[' + ",".join(text.strip() for text in documents) + "]}").encode("utf-8")

    async def submit(self, documents: list[str]) -> dict[str, Any]:
        """Submit signed documents. ETA answers 202 before it has validated them."""
        response = await self._call(
            "POST",
            "/api/v1.0/documentsubmissions/",
            content=self.submission_body(documents),
            ok=(200, 202),
        )
        return response.json()

    async def get_submission(self, submission_uuid: str, *, page_no: int = 1, page_size: int = 100) -> dict[str, Any]:
        response = await self._call(
            "GET",
            f"/api/v1.0/documentsubmissions/{submission_uuid}",
            params={"pageNo": page_no, "pageSize": page_size},
        )
        return response.json()

    async def get_document_details(self, document_uuid: str) -> dict[str, Any]:
        response = await self._call("GET", f"/api/v1.0/documents/{document_uuid}/details")
        return response.json()

    async def get_document_types(self) -> list[dict[str, Any]]:
        body = (await self._call("GET", "/api/v1.0/documenttypes")).json()
        if isinstance(body, dict):
            body = body.get("result") or body.get("documentTypes") or []
        return [row for row in body if isinstance(row, dict)] if isinstance(body, list) else []

    async def get_document_type(self, type_id: int | str) -> dict[str, Any]:
        return (await self._call("GET", f"/api/v1.0/documenttypes/{type_id}")).json()

    async def set_document_state(self, document_uuid: str, *, status: str, reason: str) -> None:
        """Cancel (as issuer) or reject (as receiver) a document."""
        await self._call(
            "PUT",
            f"/api/v1.0/documents/state/{document_uuid}/state",
            json_body={"status": status, "reason": reason},
        )

    async def cancel_document(self, document_uuid: str, reason: str) -> None:
        await self.set_document_state(document_uuid, status="cancelled", reason=reason)

    async def reject_document(self, document_uuid: str, reason: str) -> None:
        await self.set_document_state(document_uuid, status="rejected", reason=reason)


__all__ = [
    "EtaApiError",
    "EtaClient",
    "EtaDuplicateSubmission",
    "EtaEnvironment",
    "EtaUrlRefused",
    "clear_token_cache",
]
