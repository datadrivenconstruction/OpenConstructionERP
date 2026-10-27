# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contract​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tests of the Xero and QuickBooks Online adapters against mocked HTTP.

Each test pins the request the provider documents (URL, headers, JSON shape)
and the response the adapter reads back. No network, no real credentials.
"""

from __future__ import annotations

import json
import time
from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.modules.accounting_sync.postings import Mapping, SyncContact, SyncDocument, SyncLine
from app.modules.accounting_sync.providers.base import OAuthTokens, ProviderContext, ProviderError
from app.modules.accounting_sync.providers.qbo import QuickBooksAdapter
from app.modules.accounting_sync.providers.xero import XeroAdapter

MAPPING = Mapping(
    accounts={"revenue": ("200", "Sales"), "subcontract_cost": ("310", "Subcontractors")},
    tax_keys={("VAT", "sales"): "OUTPUT2", ("VAT", "purchase"): "INPUT2"},
)


def _ctx(**kw) -> ProviderContext:
    tokens = OAuthTokens(access_token="AT", refresh_token="RT", expires_at=time.time() + 3600)
    return ProviderContext(
        client_id="cid", client_secret="csecret", tokens=tokens, tenant_id="T1", mapping=MAPPING, **kw
    )


def _doc(kind: str = "ar_invoice") -> SyncDocument:
    return SyncDocument(
        record_type=kind,
        record_id="rec-1",
        number="INV-9",
        doc_date=date(2026, 5, 1),
        due_date=date(2026, 5, 31),
        contact=SyncContact("c1", "Client Ltd", "customer" if kind == "ar_invoice" else "supplier", tax_id="GB1"),
        currency="GBP",
        lines=[
            SyncLine(
                "Valuation 4",
                Decimal("1000.005"),
                "revenue" if kind == "ar_invoice" else "subcontract_cost",
                "VAT",
                Decimal("20"),
            )
        ],
        project_code="PRJ-1",
    )


@pytest.mark.asyncio
async def test_xero_invoice_push_shape_and_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        inv = body["Invoices"][0]
        return httpx.Response(200, json={"Invoices": [{"InvoiceID": "X-1", "Total": "1200.01", **inv}]})

    adapter = XeroAdapter(_ctx(), transport=httpx.MockTransport(handler))
    result = await adapter.push_document(_doc(), "C-1", None, None)
    req = seen[0]
    assert req.url == "https://api.xero.com/api.xro/2.0/Invoices"
    assert req.headers["xero-tenant-id"] == "T1" and req.headers["Authorization"] == "Bearer AT"
    assert req.headers["Idempotency-Key"].startswith("rec-1-")
    inv = json.loads(req.content)["Invoices"][0]
    assert inv["Type"] == "ACCREC" and inv["Status"] == "AUTHORISED" and inv["LineAmountTypes"] == "Exclusive"
    assert inv["Contact"] == {"ContactID": "C-1"} and inv["InvoiceNumber"] == "INV-9"
    line = inv["LineItems"][0]
    assert line["UnitAmount"] == "1000.01" and line["AccountCode"] == "200" and line["TaxType"] == "OUTPUT2"
    assert line["Tracking"] == [{"Name": "Project", "Option": "PRJ-1"}]
    assert result.external_id == "X-1" and result.remote_total == Decimal("1200.01")


@pytest.mark.asyncio
async def test_xero_bill_update_carries_invoice_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        inv = json.loads(request.content)["Invoices"][0]
        assert inv["Type"] == "ACCPAY" and inv["InvoiceID"] == "X-9"
        assert inv["LineItems"][0]["TaxType"] == "INPUT2"
        return httpx.Response(200, json={"Invoices": [{"InvoiceID": "X-9"}]})

    adapter = XeroAdapter(_ctx(), transport=httpx.MockTransport(handler))
    assert (await adapter.push_document(_doc("ap_bill"), "C-2", "X-9", None)).external_id == "X-9"


@pytest.mark.asyncio
async def test_xero_validation_error_becomes_a_readable_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"Elements": [{"ValidationErrors": [{"Message": "Account code '200' is not a valid code"}]}]},
        )

    adapter = XeroAdapter(_ctx(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as exc:
        await adapter.push_document(_doc(), "C-1", None, None)
    assert "is not a valid code" in exc.value.reason and exc.value.retryable is False


@pytest.mark.asyncio
async def test_xero_refreshes_an_expired_token_first() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "identity.xero.com" in str(request.url):
            assert b"grant_type=refresh_token" in request.content and b"refresh_token=RT" in request.content
            return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "RT2", "expires_in": 1800})
        assert request.headers["Authorization"] == "Bearer NEW"
        return httpx.Response(200, json={"Contacts": [{"ContactID": "C-7"}]})

    ctx = _ctx()
    ctx.tokens.expires_at = 0
    adapter = XeroAdapter(ctx, transport=httpx.MockTransport(handler))
    assert (await adapter.push_contact(_doc().contact, None)).external_id == "C-7"
    assert adapter.tokens_changed and ctx.tokens.refresh_token == "RT2"
    assert calls[0] == "https://identity.xero.com/connect/token"


@pytest.mark.asyncio
async def test_xero_tracking_option_created_once() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200, json={"TrackingCategories": [{"Name": "Project", "TrackingCategoryID": "TC", "Options": []}]}
            )
        assert request.url.path.endswith("/TrackingCategories/TC/Options")
        return httpx.Response(200, json={"Options": [{"TrackingOptionID": "OPT-1", "Name": "PRJ-1"}]})

    adapter = XeroAdapter(_ctx(), transport=httpx.MockTransport(handler))
    assert await adapter.ensure_tracking("PRJ-1", "Project one") == "OPT-1"


@pytest.mark.asyncio
async def test_xero_pull_payments_keeps_only_pushed_invoices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["If-Modified-Since"] == "2026-05-01T00:00:00"
        return httpx.Response(
            200,
            json={
                "Payments": [
                    {
                        "PaymentID": "P1",
                        "Amount": 600.5,
                        "Date": "/Date(1780272000000+0000)/",
                        "Invoice": {"InvoiceID": "X-1"},
                    },
                    {"PaymentID": "P2", "Amount": 10, "Date": "2026-06-01", "Invoice": {"InvoiceID": "OTHER"}},
                    {"PaymentID": "P3", "Amount": 5, "Status": "DELETED", "Invoice": {"InvoiceID": "X-1"}},
                ]
            },
        )

    adapter = XeroAdapter(_ctx(), transport=httpx.MockTransport(handler))
    pays = await adapter.pull_payments({"X-1": "ar_invoice"}, "2026-05-01T00:00:00")
    assert [(p.external_payment_id, p.amount) for p in pays] == [("P1", Decimal("600.5"))]
    assert pays[0].payment_date == date(2026, 6, 1)


@pytest.mark.asyncio
async def test_qbo_invoice_and_bill_shapes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if request.url.path.endswith("/invoice"):
            return httpx.Response(200, json={"Invoice": {"Id": "77", "SyncToken": "0", "TotalAmt": 1200.01, **body}})
        return httpx.Response(200, json={"Bill": {"Id": "88", "SyncToken": "3", "TotalAmt": 1200.01}})

    adapter = QuickBooksAdapter(_ctx(tracking={"PRJ-1": "CL-5"}), transport=httpx.MockTransport(handler))
    res = await adapter.push_document(_doc(), "CU-1", None, None)
    req = seen[0]
    assert str(req.url).startswith("https://sandbox-quickbooks.api.intuit.com/v3/company/T1/invoice?requestid=rec-1-")
    assert req.url.params["minorversion"] == "75"
    body = json.loads(req.content)
    line = body["Line"][0]
    assert body["CustomerRef"] == {"value": "CU-1"} and body["DocNumber"] == "INV-9"
    assert line["DetailType"] == "SalesItemLineDetail" and line["Amount"] == "1000.01"
    assert line["SalesItemLineDetail"]["ItemRef"] == {"value": "200"}
    assert line["SalesItemLineDetail"]["ClassRef"] == {"value": "CL-5"}
    assert line["SalesItemLineDetail"]["TaxCodeRef"] == {"value": "OUTPUT2"}
    assert res.external_id == "77" and res.remote_total == Decimal("1200.01")

    res = await adapter.push_document(_doc("ap_bill"), "V-1", "88", "2")
    body = json.loads(seen[1].content)
    assert body["VendorRef"] == {"value": "V-1"} and body["Id"] == "88" and body["SyncToken"] == "2"
    assert body["Line"][0]["AccountBasedExpenseLineDetail"]["AccountRef"] == {"value": "310"}
    assert res.external_version == "3"


@pytest.mark.asyncio
async def test_qbo_contact_reuses_an_existing_vendor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and "DisplayName" in request.url.params["query"]
        return httpx.Response(200, json={"QueryResponse": {"Vendor": [{"Id": "V-9", "SyncToken": "1"}]}})

    adapter = QuickBooksAdapter(_ctx(), transport=httpx.MockTransport(handler))
    contact = SyncContact("s1", "Steel O'Brien", "supplier")
    assert (await adapter.push_contact(contact, None)).external_id == "V-9"


@pytest.mark.asyncio
async def test_qbo_pull_payments_from_payment_and_billpayment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        if q.startswith("select * from Payment"):
            return httpx.Response(
                200,
                json={"QueryResponse": {"Payment": [{"Id": "1", "TxnDate": "2026-06-02", "Line": [
                    {"Amount": 1200.01, "LinkedTxn": [{"TxnId": "77", "TxnType": "Invoice"}]}]}]}},
            )  # fmt: skip
        return httpx.Response(
            200,
            json={"QueryResponse": {"BillPayment": [{"Id": "2", "TxnDate": "2026-06-03", "Line": [
                {"Amount": 50, "LinkedTxn": [{"TxnId": "88", "TxnType": "Bill"}]}]}]}},
        )  # fmt: skip

    adapter = QuickBooksAdapter(_ctx(), transport=httpx.MockTransport(handler))
    pays = await adapter.pull_payments({"77": "ar_invoice", "88": "ap_bill"}, None)
    assert [(p.external_document_id, p.amount) for p in pays] == [("77", Decimal("1200.01")), ("88", Decimal("50"))]


@pytest.mark.asyncio
async def test_qbo_fault_is_retryable_on_5xx_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"Fault": {"Error": [{"Message": "Service unavailable"}]}})

    adapter = QuickBooksAdapter(_ctx(), transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as exc:
        await adapter.ensure_tracking("PRJ-1", "")
    assert exc.value.retryable and "Service unavailable" in exc.value.reason


def test_authorization_url_carries_scope_and_state() -> None:
    url = XeroAdapter(_ctx()).authorization_url("https://app.example/cb", "conn-1")
    assert url.startswith("https://login.xero.com/identity/connect/authorize?")
    assert "state=conn-1" in url and "offline_access" in url and "client_id=cid" in url
