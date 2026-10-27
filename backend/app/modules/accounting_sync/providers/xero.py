# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Xero​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ accounting API adapter (OAuth2, Accounting API 2.0).

AR documents post as ``ACCREC`` invoices, AP documents as ``ACCPAY`` bills, both
``AUTHORISED`` with exclusive line amounts. Each project is an option of one
tracking category (default name ``Project``). Payments come back from
``GET /Payments`` filtered to the invoices the platform pushed.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.modules.accounting_sync.postings import SyncContact, SyncDocument, money
from app.modules.accounting_sync.providers.base import ProviderAdapter, ProviderError, PushResult, RemotePayment

API = "https://api.xero.com/api.xro/2.0"
TRACKING_NAME = "Project"


def _xero_date(value: Any) -> date:
    """Parse ``/Date(1700000000000+0000)/`` or ISO dates."""
    text = str(value or "")
    m = re.search(r"/Date\((\d+)", text)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=UTC).date()
    return date.fromisoformat(text[:10])


class XeroAdapter(ProviderAdapter):
    """Push invoices, bills, contacts and tracking; pull payments."""

    provider = "xero"
    authorize_url = "https://login.xero.com/identity/connect/authorize"
    token_url = "https://identity.xero.com/connect/token"
    scopes = "offline_access accounting.transactions accounting.contacts accounting.settings"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.ctx.tokens.access_token}",
            "xero-tenant-id": self.ctx.tenant_id,
            "Accept": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{API}/{path.lstrip('/')}"

    def _error_reason(self, resp: Any) -> str:
        try:
            body = resp.json()
        except ValueError:
            return f"HTTP {resp.status_code}"
        msgs = [
            err.get("Message")
            for el in body.get("Elements") or []
            for err in el.get("ValidationErrors") or []
            if err.get("Message")
        ]
        return f"Xero {resp.status_code}: " + ("; ".join(msgs) or str(body.get("Message") or body.get("Detail") or ""))

    async def push_contact(self, contact: SyncContact, external_id: str | None) -> PushResult:
        body: dict[str, Any] = {"Name": contact.name}
        if contact.tax_id:
            body["TaxNumber"] = contact.tax_id
        if contact.email:
            body["EmailAddress"] = contact.email
        if external_id:
            body["ContactID"] = external_id
        data = await self.request("POST", "Contacts", json={"Contacts": [body]})
        return PushResult(external_id=data["Contacts"][0]["ContactID"])

    async def ensure_tracking(self, project_code: str, project_name: str) -> str:
        option = (project_code or project_name)[:100]
        data = await self.request("GET", "TrackingCategories")
        category = next((c for c in data.get("TrackingCategories") or [] if c.get("Name") == TRACKING_NAME), None)
        if category is None:
            created = await self.request("PUT", "TrackingCategories", json={"Name": TRACKING_NAME})
            category = created["TrackingCategories"][0]
        for opt in category.get("Options") or []:
            if opt.get("Name") == option:
                return str(opt["TrackingOptionID"])
        added = await self.request(
            "PUT", f"TrackingCategories/{category['TrackingCategoryID']}/Options", json={"Name": option}
        )
        return str(added["Options"][0]["TrackingOptionID"])

    def document_body(self, doc: SyncDocument, contact_external_id: str, external_id: str | None) -> dict[str, Any]:
        """The Xero invoice JSON for a document (exposed for contract tests)."""
        mapping = self.ctx.mapping
        tracking_option = doc.project_code or doc.project_name
        lines = []
        for ln in doc.lines:
            item: dict[str, Any] = {
                "Description": ln.description[:4000] or doc.number,
                "Quantity": "1",
                "UnitAmount": f"{money(ln.net):.2f}",
                "AccountCode": mapping.account(ln.category)[0],
                "TaxType": mapping.tax_key(ln.tax_code, doc.tax_direction) or "",
            }
            if tracking_option:
                item["Tracking"] = [{"Name": TRACKING_NAME, "Option": tracking_option[:100]}]
            lines.append(item)
        body: dict[str, Any] = {
            "Type": "ACCREC" if doc.is_sales else "ACCPAY",
            "Contact": {"ContactID": contact_external_id},
            "Date": doc.doc_date.isoformat(),
            "LineAmountTypes": "Exclusive",
            "LineItems": lines,
            "CurrencyCode": doc.currency,
            "Status": "AUTHORISED",
            "Reference": doc.reference or doc.number,
            "InvoiceNumber": doc.number,
        }
        if doc.due_date:
            body["DueDate"] = doc.due_date.isoformat()
        if external_id:
            body["InvoiceID"] = external_id
        return body

    async def push_document(
        self, doc: SyncDocument, contact_external_id: str, external_id: str | None, external_version: str | None
    ) -> PushResult:
        body = self.document_body(doc, contact_external_id, external_id)
        data = await self.request(
            "POST",
            "Invoices",
            json={"Invoices": [body]},
            headers={"Idempotency-Key": f"{doc.record_id}-{doc.payload_hash()[:16]}"},
        )
        inv = data["Invoices"][0]
        if inv.get("HasErrors") or inv.get("ValidationErrors"):
            reasons = "; ".join(e.get("Message", "") for e in inv.get("ValidationErrors") or [])
            raise ProviderError(f"Xero rejected {doc.number}: {reasons}", retryable=False)
        total = inv.get("Total")
        return PushResult(external_id=inv["InvoiceID"], remote_total=money(total) if total is not None else None)

    async def pull_payments(self, document_ids: dict[str, str], since: str | None) -> list[RemotePayment]:
        headers = {"If-Modified-Since": since} if since else {}
        data = await self.request("GET", "Payments", headers=headers)
        out: list[RemotePayment] = []
        for p in data.get("Payments") or []:
            inv_id = str((p.get("Invoice") or {}).get("InvoiceID") or "")
            if inv_id not in document_ids or p.get("Status") == "DELETED":
                continue
            out.append(
                RemotePayment(
                    external_payment_id=str(p["PaymentID"]),
                    external_document_id=inv_id,
                    amount=Decimal(str(p.get("Amount") or "0")),
                    payment_date=_xero_date(p.get("Date")),
                    reference=str(p.get("Reference") or ""),
                )
            )
        return out
