# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Provider​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ adapter interface for live accounting APIs.

An adapter turns a neutral :class:`SyncDocument` into the provider's API calls.
It never touches the database: the service hands it the mapping, the stored
external id (for an update) and the OAuth tokens, and stores what it returns.
HTTP goes through one ``httpx.AsyncClient``; tests inject a ``MockTransport``.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar
from urllib.parse import urlencode

import httpx

from app.modules.accounting_sync.postings import Mapping, SyncContact, SyncDocument


class ProviderError(Exception):
    """A provider call failed; ``reason`` is shown in the sync log."""

    def __init__(self, reason: str, *, retryable: bool = True, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable
        self.status_code = status_code


@dataclass
class OAuthTokens:
    """Access and refresh token pair with absolute expiry (epoch seconds)."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        return not self.access_token or time.time() > self.expires_at - 60

    def as_dict(self) -> dict[str, Any]:
        return {"access_token": self.access_token, "refresh_token": self.refresh_token, "expires_at": self.expires_at}


@dataclass
class PushResult:
    """What a push returned: the remote id, its version and the total the provider computed."""

    external_id: str
    external_version: str | None = None
    remote_total: Decimal | None = None


@dataclass
class RemotePayment:
    """A payment the accounting system recorded against a pushed document."""

    external_payment_id: str
    external_document_id: str
    amount: Decimal
    payment_date: date
    reference: str = ""


@dataclass
class ProviderContext:
    """Everything an adapter call needs, assembled by the service."""

    client_id: str
    client_secret: str
    tokens: OAuthTokens
    tenant_id: str = ""
    sandbox: bool = True
    mapping: Mapping = field(default_factory=Mapping)
    tracking: dict[str, str] = field(default_factory=dict)  # project code -> remote tracking/class id


class ProviderAdapter(ABC):
    """Base class of the Xero and QuickBooks Online adapters."""

    provider: ClassVar[str] = ""
    authorize_url: ClassVar[str] = ""
    token_url: ClassVar[str] = ""
    scopes: ClassVar[str] = ""

    def __init__(self, ctx: ProviderContext, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.ctx = ctx
        self._transport = transport
        self.tokens_changed = False

    # -- OAuth ---------------------------------------------------------------

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        """URL the admin opens to grant access."""
        query = {
            "response_type": "code",
            "client_id": self.ctx.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.scopes,
            "state": state,
        }
        return f"{self.authorize_url}?{urlencode(query)}"

    async def _token_request(self, data: dict[str, str]) -> OAuthTokens:
        async with self._client() as client:
            resp = await client.post(
                self.token_url,
                data=data,
                auth=(self.ctx.client_id, self.ctx.client_secret),
                headers={"Accept": "application/json"},
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"OAuth token request failed ({resp.status_code})", retryable=False, status_code=resp.status_code
            )
        body = resp.json()
        self.ctx.tokens = OAuthTokens(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token") or self.ctx.tokens.refresh_token,
            expires_at=time.time() + float(body.get("expires_in") or 1800),
        )
        self.tokens_changed = True
        return self.ctx.tokens

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthTokens:
        """Swap the authorization code for tokens."""
        return await self._token_request(
            {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        )

    async def ensure_token(self) -> None:
        """Refresh the access token when it is missing or about to expire."""
        if not self.ctx.tokens.expired:
            return
        if not self.ctx.tokens.refresh_token:
            raise ProviderError("Not connected: authorise the connection first", retryable=False)
        await self._token_request({"grant_type": "refresh_token", "refresh_token": self.ctx.tokens.refresh_token})

    # -- HTTP ------------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=30.0)

    @abstractmethod
    def _headers(self) -> dict[str, str]: ...

    @abstractmethod
    def _url(self, path: str) -> str: ...

    async def request(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        """Authenticated JSON call; maps HTTP failures to :class:`ProviderError`."""
        await self.ensure_token()
        headers = {**self._headers(), **kw.pop("headers", {})}
        try:
            async with self._client() as client:
                resp = await client.request(method, self._url(path), headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Network error: {exc.__class__.__name__}") from exc
        if resp.status_code >= 400:
            raise ProviderError(
                self._error_reason(resp),
                retryable=resp.status_code in (408, 429) or resp.status_code >= 500,
                status_code=resp.status_code,
            )
        return resp.json() if resp.content else {}

    def _error_reason(self, resp: httpx.Response) -> str:
        return f"HTTP {resp.status_code}: {resp.text[:300]}"

    # -- Domain ----------------------------------------------------------------

    @abstractmethod
    async def push_contact(self, contact: SyncContact, external_id: str | None) -> PushResult:
        """Create or update a customer or supplier."""

    @abstractmethod
    async def ensure_tracking(self, project_code: str, project_name: str) -> str:
        """Create (or find) the project's tracking option or class and return its id."""

    @abstractmethod
    async def push_document(
        self, doc: SyncDocument, contact_external_id: str, external_id: str | None, external_version: str | None
    ) -> PushResult:
        """Create or update an AR invoice or AP bill."""

    @abstractmethod
    async def pull_payments(self, document_ids: dict[str, str], since: str | None) -> list[RemotePayment]:
        """Payments recorded remotely against the given ``{external_id: record_type}`` documents."""
