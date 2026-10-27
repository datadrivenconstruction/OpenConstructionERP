# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""QuickBooks​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ Online accounting API adapter (OAuth2, API v3).

AR documents post as ``Invoice`` with sales item lines (the mapped account code
is the QuickBooks Item id, because QuickBooks books revenue through items), AP
documents as ``Bill`` with account-based expense lines. Each project is a
``Class``. Payments come back from ``Payment`` (invoices) and ``BillPayment``
(bills) through the query endpoint.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.accounting_sync.postings import SyncContact, SyncDocument, money
from app.modules.accounting_sync.providers.base import ProviderAdapter, ProviderError, PushResult, RemotePayment

PROD = "https://quickbooks.api.intuit.com"
SANDBOX = "https://sandbox-quickbooks.api.intuit.com"
MINOR_VERSION = "75"


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


class QuickBooksAdapter(ProviderAdapter):
    """Push invoices, bills, customers, vendors and classes; pull payments."""

    provider = "qbo"
    authorize_url = "https://appcenter.intuit.com/connect/oauth2"
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    scopes = "com.intuit.quickbooks.accounting"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.ctx.tokens.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        base = SANDBOX if self.ctx.sandbox else PROD
        sep = "&" if "?" in path else "?"
        return f"{base}/v3/company/{self.ctx.tenant_id}/{path.lstrip('/')}{sep}minorversion={MINOR_VERSION}"

    def _error_reason(self, resp: Any) -> str:
        try:
            errors = resp.json().get("Fault", {}).get("Error") or []
        except ValueError:
            errors = []
        detail = "; ".join(f"{e.get('Message', '')} {e.get('Detail', '')}".strip() for e in errors)
        return f"QuickBooks {resp.status_code}: {detail}".strip()

    async def query(self, statement: str) -> dict[str, Any]:
        data = await self.request("GET", "query", params={"query": statement})
        return data.get("QueryResponse") or {}

    async def push_contact(self, contact: SyncContact, external_id: str | None) -> PushResult:
        entity = "Customer" if contact.kind == "customer" else "Vendor"
        body: dict[str, Any] = {"DisplayName": contact.name[:100]}
        if contact.email:
            body["PrimaryEmailAddr"] = {"Address": contact.email}
        if contact.tax_id and entity == "Vendor":
            body["TaxIdentifier"] = contact.tax_id
        if external_id:
            found = await self.query(f"select * from {entity} where Id = '{_q(external_id)}'")
            rows = found.get(entity) or []
            if rows:
                body.update({"Id": external_id, "SyncToken": rows[0]["SyncToken"], "sparse": True})
        else:
            found = await self.query(f"select * from {entity} where DisplayName = '{_q(body['DisplayName'])}'")
            rows = found.get(entity) or []
            if rows:
                return PushResult(external_id=str(rows[0]["Id"]), external_version=str(rows[0].get("SyncToken")))
        data = await self.request("POST", entity.lower(), json=body)
        row = data[entity]
        return PushResult(external_id=str(row["Id"]), external_version=str(row.get("SyncToken")))

    async def ensure_tracking(self, project_code: str, project_name: str) -> str:
        name = (project_code or project_name)[:100]
        found = await self.query(f"select * from Class where Name = '{_q(name)}'")
        rows = found.get("Class") or []
        if rows:
            return str(rows[0]["Id"])
        data = await self.request("POST", "class", json={"Name": name})
        return str(data["Class"]["Id"])

    def document_body(self, doc: SyncDocument, contact_external_id: str) -> dict[str, Any]:
        """The QuickBooks Invoice or Bill JSON for a document (exposed for contract tests)."""
        mapping = self.ctx.mapping
        class_id = self.ctx.tracking.get(doc.project_code or doc.project_name)
        lines = []
        for ln in doc.lines:
            detail: dict[str, Any] = {}
            tax_key = mapping.tax_key(ln.tax_code, doc.tax_direction)
            if tax_key:
                detail["TaxCodeRef"] = {"value": tax_key}
            if class_id:
                detail["ClassRef"] = {"value": class_id}
            if doc.is_sales:
                detail["ItemRef"] = {"value": mapping.account(ln.category)[0]}
                detail["Qty"] = 1
                detail["UnitPrice"] = f"{money(ln.net):.2f}"
                kind = "SalesItemLineDetail"
            else:
                detail["AccountRef"] = {"value": mapping.account(ln.category)[0]}
                kind = "AccountBasedExpenseLineDetail"
            lines.append(
                {
                    "DetailType": kind,
                    "Amount": f"{money(ln.net):.2f}",
                    "Description": ln.description[:4000],
                    kind: detail,
                }
            )
        ref_key = "CustomerRef" if doc.is_sales else "VendorRef"
        body: dict[str, Any] = {
            ref_key: {"value": contact_external_id},
            "Line": lines,
            "DocNumber": doc.number[:21],
            "TxnDate": doc.doc_date.isoformat(),
            "CurrencyRef": {"value": doc.currency},
        }
        if doc.due_date:
            body["DueDate"] = doc.due_date.isoformat()
        return body

    async def push_document(
        self, doc: SyncDocument, contact_external_id: str, external_id: str | None, external_version: str | None
    ) -> PushResult:
        entity = "Invoice" if doc.is_sales else "Bill"
        body = self.document_body(doc, contact_external_id)
        if external_id:
            body.update({"Id": external_id, "SyncToken": external_version or "0", "sparse": False})
        data = await self.request(
            "POST", f"{entity.lower()}?requestid={doc.record_id[:36]}-{doc.payload_hash()[:12]}", json=body
        )
        row = data.get(entity)
        if not row:
            raise ProviderError(f"QuickBooks returned no {entity} for {doc.number}", retryable=False)
        total = row.get("TotalAmt")
        return PushResult(
            external_id=str(row["Id"]),
            external_version=str(row.get("SyncToken")),
            remote_total=money(total) if total is not None else None,
        )

    async def pull_payments(self, document_ids: dict[str, str], since: str | None) -> list[RemotePayment]:
        where = f" where MetaData.LastUpdatedTime > '{_q(since)}'" if since else ""
        out: list[RemotePayment] = []
        for entity, txn_type in (("Payment", "Invoice"), ("BillPayment", "Bill")):
            rows = (await self.query(f"select * from {entity}{where}")).get(entity) or []
            for p in rows:
                for line in p.get("Line") or []:
                    for link in line.get("LinkedTxn") or []:
                        doc_id = str(link.get("TxnId"))
                        if link.get("TxnType") != txn_type or doc_id not in document_ids:
                            continue
                        out.append(
                            RemotePayment(
                                external_payment_id=f"{entity}:{p['Id']}:{doc_id}",
                                external_document_id=doc_id,
                                amount=Decimal(str(line.get("Amount") or "0")),
                                payment_date=date.fromisoformat(str(p.get("TxnDate"))[:10]),
                                reference=str(p.get("PaymentRefNum") or p.get("DocNumber") or ""),
                            )
                        )
        return out
