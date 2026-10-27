# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync service: connections, mappings, push, pull, exports.

Sources (all through finance, the single document register):
    * receivable invoices, including those raised from certified interim payment
      certificates (``Invoice.source_claim_id``);
    * payable bills from subcontractor payment applications
      (``metadata.source == subcontract_payment_application``) and supplier invoices
      against purchase orders (``Invoice.purchase_order_id``);
    * annual bank fees of live guarantees with a commission rate (guarantees module).

The platform is master for the documents; the accounting system is master for the
ledger and payment status, so pulled payments are recorded in finance and mark the
invoice paid. Every push is idempotent through :class:`ExternalRef` and leaves one
:class:`SyncLogEntry` per record.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_secret, encrypt_secret
from app.modules.accounting_sync import templates
from app.modules.accounting_sync.exports import datev, journal, saft
from app.modules.accounting_sync.models import (
    AccountingConnection,
    AccountMapping,
    ExternalRef,
    SyncLogEntry,
    TaxCodeMapping,
)
from app.modules.accounting_sync.postings import (
    AP_BILL,
    AR_INVOICE,
    ZERO,
    Mapping,
    SyncContact,
    SyncDocument,
    SyncLine,
    journal_for,
    money,
    personal_accounts,
)
from app.modules.accounting_sync.providers import API_PROVIDERS, FILE_PROVIDERS
from app.modules.accounting_sync.providers.base import OAuthTokens, ProviderAdapter, ProviderContext, ProviderError
from app.modules.accounting_sync.validators import evaluate

logger = logging.getLogger(__name__)

PUSHABLE_STATUSES = ("approved", "sent", "paid")
BLOCKING_RULES = (
    "accounting_sync.unmapped_account",
    "accounting_sync.tax_code_mismatch",
    "accounting_sync.closed_period",
)
PAY_APP_SOURCE = "subcontract_payment_application"

#: Tests set this to an ``httpx.MockTransport`` factory; production leaves it None.
transport_factory: Callable[[str], httpx.AsyncBaseTransport | None] = lambda _provider: None  # noqa: E731


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


class AccountingSyncService:
    """Stateless service over one session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- connections ---------------------------------------------------------

    async def list_connections(self) -> list[AccountingConnection]:
        rows = await self.session.execute(select(AccountingConnection).order_by(AccountingConnection.name))
        return list(rows.scalars())

    async def get_connection(self, connection_id: uuid.UUID) -> AccountingConnection:
        row = await self.session.get(AccountingConnection, connection_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Connection not found")
        return row

    async def create_connection(self, data: dict[str, Any], actor_id: str | None = None) -> AccountingConnection:
        provider = data["provider"]
        template_key = data.get("chart_template") or self._default_template(provider, data.get("country_code"))
        conn = AccountingConnection(
            name=data["name"],
            provider=provider,
            country_code=(data.get("country_code") or None) and data["country_code"].upper(),
            chart_template=template_key,
            base_currency=(data.get("base_currency") or "EUR").upper(),
            is_sandbox=bool(data.get("is_sandbox", True)),
            client_id=data.get("client_id") or None,
            client_secret_enc=encrypt_secret(data.get("client_secret") or None),
            external_tenant_id=data.get("external_tenant_id") or None,
            lock_date=data.get("lock_date"),
            project_ids=[str(p) for p in data.get("project_ids") or []],
            settings_=dict(data.get("settings") or {}),
            status="draft" if provider in API_PROVIDERS else "ready",
            created_by=actor_id,
        )
        self.session.add(conn)
        await self.session.flush()
        await self.apply_template(conn, template_key)
        return conn

    @staticmethod
    def _default_template(provider: str, country_code: str | None) -> str:
        if provider == "datev":
            return "DE-SKR03"
        options = [t["key"] for t in templates.list_templates(country_code) if t["country_code"]]
        return options[0] if options and provider != "journal" else "generic"

    async def update_connection(self, conn: AccountingConnection, data: dict[str, Any]) -> AccountingConnection:
        for key in ("name", "is_sandbox", "client_id", "external_tenant_id", "lock_date", "base_currency"):
            if key in data and data[key] is not None:
                setattr(conn, key, data[key])
        if data.get("client_secret"):
            conn.client_secret_enc = encrypt_secret(data["client_secret"])
        if data.get("project_ids") is not None:
            conn.project_ids = [str(p) for p in data["project_ids"]]
        if data.get("settings") is not None:
            conn.settings_ = {**(conn.settings_ or {}), **data["settings"]}
        if data.get("clear_lock_date"):
            conn.lock_date = None
        await self.session.flush()
        return conn

    async def delete_connection(self, conn: AccountingConnection) -> None:
        await self.session.delete(conn)
        await self.session.flush()

    # -- mappings ------------------------------------------------------------

    async def apply_template(self, conn: AccountingConnection, template_key: str) -> None:
        """Replace the connection's mappings with a template from country data."""
        tpl = templates.get_template(template_key)
        conn.chart_template = template_key
        if tpl.get("country_code") and not conn.country_code:
            conn.country_code = tpl["country_code"]
        await self.session.execute(delete(AccountMapping).where(AccountMapping.connection_id == conn.id))
        await self.session.execute(delete(TaxCodeMapping).where(TaxCodeMapping.connection_id == conn.id))
        for cat in templates.categories():
            code, name = (tpl["accounts"].get(cat) or ["", ""])[:2]
            self.session.add(AccountMapping(connection_id=conn.id, category=cat, account_code=code, account_name=name))
        for row in templates.tax_codes(conn.country_code):
            for direction in ("sales", "purchase"):
                key = (tpl.get("tax_keys") or {}).get(direction, {}).get(row["tax_code"])
                if key is None:
                    continue
                self.session.add(
                    TaxCodeMapping(
                        connection_id=conn.id,
                        tax_code=row["tax_code"],
                        direction=direction,
                        external_code=key,
                        rate_pct=Decimal(row["rate_pct"]),
                    )
                )
        await self.session.flush()

    async def account_mappings(self, conn: AccountingConnection) -> list[AccountMapping]:
        rows = await self.session.execute(
            select(AccountMapping).where(AccountMapping.connection_id == conn.id).order_by(AccountMapping.category)
        )
        return list(rows.scalars())

    async def tax_mappings(self, conn: AccountingConnection) -> list[TaxCodeMapping]:
        rows = await self.session.execute(
            select(TaxCodeMapping)
            .where(TaxCodeMapping.connection_id == conn.id)
            .order_by(TaxCodeMapping.direction, TaxCodeMapping.tax_code)
        )
        return list(rows.scalars())

    async def set_account_mappings(self, conn: AccountingConnection, rows: list[dict[str, str]]) -> None:
        existing = {m.category: m for m in await self.account_mappings(conn)}
        for row in rows:
            m = existing.get(row["category"])
            if m is None:
                m = AccountMapping(connection_id=conn.id, category=row["category"])
                self.session.add(m)
            m.account_code = (row.get("account_code") or "").strip()
            m.account_name = (row.get("account_name") or "").strip()
        await self.session.flush()

    async def set_tax_mappings(self, conn: AccountingConnection, rows: list[dict[str, Any]]) -> None:
        existing = {(m.tax_code, m.direction): m for m in await self.tax_mappings(conn)}
        for row in rows:
            key = (row["tax_code"], row["direction"])
            m = existing.get(key)
            if m is None:
                m = TaxCodeMapping(connection_id=conn.id, tax_code=row["tax_code"], direction=row["direction"])
                self.session.add(m)
            m.external_code = (row.get("external_code") or "").strip()
            m.rate_pct = templates.tax_rate(conn.country_code, row["tax_code"])
        await self.session.flush()

    async def mapping(self, conn: AccountingConnection) -> Mapping:
        accounts = {
            m.category: (m.account_code, m.account_name) for m in await self.account_mappings(conn) if m.account_code
        }
        taxes = {(m.tax_code, m.direction): m.external_code for m in await self.tax_mappings(conn)}
        return Mapping(accounts=accounts, tax_keys=taxes)

    # -- documents -------------------------------------------------------------

    async def documents(
        self,
        conn: AccountingConnection,
        *,
        project_id: uuid.UUID | None = None,
        period: tuple[date, date] | None = None,
        record_ids: set[str] | None = None,
    ) -> list[SyncDocument]:
        """Neutral documents in the connection's scope."""
        from app.modules.finance.models import Invoice, InvoiceLineItem
        from app.modules.projects.models import Project

        scope = {uuid.UUID(p) for p in conn.project_ids or []}
        if project_id is not None:
            scope = {project_id} if not scope or project_id in scope else set()
            if not scope:
                return []
        stmt = select(Invoice).where(Invoice.status.in_(PUSHABLE_STATUSES))
        if scope:
            stmt = stmt.where(Invoice.project_id.in_(scope))
        invoices = list((await self.session.execute(stmt.order_by(Invoice.invoice_date))).scalars())
        project_ids = {inv.project_id for inv in invoices}
        lines_by_inv: dict[uuid.UUID, list[Any]] = {}
        if invoices:
            rows = await self.session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id.in_([i.id for i in invoices]))
                .order_by(InvoiceLineItem.sort_order)
            )
            for ln in rows.scalars():
                lines_by_inv.setdefault(ln.invoice_id, []).append(ln)
        fees = await self._guarantee_fee_docs(scope, period)
        project_ids |= {uuid.UUID(d.project_id) for d in fees if d.project_id}
        projects = {}
        if project_ids:
            projects = {
                p.id: p
                for p in (await self.session.execute(select(Project).where(Project.id.in_(project_ids)))).scalars()
            }
        contacts = await self._contacts({inv.contact_id for inv in invoices if inv.contact_id})
        docs: list[SyncDocument] = []
        for inv in invoices:
            doc = self._invoice_doc(conn, inv, lines_by_inv.get(inv.id, []), projects.get(inv.project_id), contacts)
            if doc is not None:
                docs.append(doc)
        for fee in fees:
            proj = projects.get(uuid.UUID(fee.project_id)) if fee.project_id else None
            if proj is not None:
                fee.project_code = proj.project_code or proj.name
                fee.project_name = proj.name
            docs.append(fee)
        if period is not None:
            docs = [d for d in docs if period[0] <= d.doc_date <= period[1]]
        if record_ids is not None:
            docs = [d for d in docs if d.record_id in record_ids]
        return docs

    async def _contacts(self, ids: set[str]) -> dict[str, SyncContact]:
        if not ids:
            return {}
        try:
            from app.modules.contacts.models import Contact
        except ImportError:  # pragma: no cover
            return {}
        out = {}
        for c in (await self.session.execute(select(Contact).where(Contact.id.in_(list(ids))))).scalars():
            name = c.company_name or c.legal_name or " ".join(x for x in (c.first_name, c.last_name) if x) or str(c.id)
            out[str(c.id)] = SyncContact(
                record_id=str(c.id),
                name=name,
                kind="customer",
                tax_id=c.vat_number or "",
                country_code=c.country_code or "",
                email=c.primary_email or "",
                is_business=(c.party_kind or "company") != "person",
            )
        return out

    def _tax_code_for(self, country: str | None, rate: Decimal, vat_category: str | None) -> tuple[str, Decimal | None]:
        if (vat_category or "").upper() == "AE":
            return "RC", ZERO
        if rate == ZERO:
            return "ZERO", ZERO
        for row in templates.tax_codes(country):
            if Decimal(row["rate_pct"]) == rate:
                return row["tax_code"], Decimal(row["rate_pct"])
        return "VAT", templates.tax_rate(country, "VAT")

    def _invoice_doc(
        self, conn: AccountingConnection, inv: Any, items: list[Any], project: Any, contacts: dict[str, SyncContact]
    ) -> SyncDocument | None:
        day = _parse_day(inv.invoice_date)
        if day is None:
            return None
        md = inv.metadata_ or {}
        sales = inv.invoice_direction == "receivable"
        if sales:
            source = "interim_payment" if inv.source_claim_id else "invoice"
        elif md.get("source") == PAY_APP_SOURCE:
            source = "subcontractor"
        elif inv.purchase_order_id or md.get("po_id"):
            source = "procurement"
        else:
            source = "invoice"
        base = contacts.get(str(inv.contact_id)) if inv.contact_id else None
        if base is not None:
            contact = SyncContact(**{**base.__dict__, "kind": "customer" if sales else "supplier"})
        else:
            label = md.get("counterparty") or md.get("subcontractor_name") or "Unknown counterparty"
            contact = SyncContact(record_id=f"name:{label}", name=str(label), kind="customer" if sales else "supplier")
        country = conn.country_code or getattr(project, "country_code", None)
        subtotal = money(inv.amount_subtotal)
        inv_rate = (money(inv.tax_amount) * 100 / subtotal).quantize(Decimal("0.01")) if subtotal else ZERO
        lines: list[SyncLine] = []
        for it in items:
            rate = Decimal(str(it.vat_rate)) if it.vat_rate is not None else inv_rate
            code, _seed = self._tax_code_for(country, rate, it.vat_category)
            lines.append(
                SyncLine(
                    description=it.description,
                    net=money(it.amount),
                    category=self._category(sales, source, it.cost_category, code),
                    tax_code=code,
                    tax_rate=rate,
                )
            )
        if not lines:
            code, _seed = self._tax_code_for(country, inv_rate, None)
            lines.append(
                SyncLine(
                    description=inv.notes or inv.invoice_number,
                    net=subtotal,
                    category=self._category(sales, source, None, code),
                    tax_code=code,
                    tax_rate=inv_rate,
                )
            )
        return SyncDocument(
            record_type=AR_INVOICE if sales else AP_BILL,
            record_id=str(inv.id),
            number=inv.invoice_number,
            doc_date=day,
            due_date=_parse_day(inv.due_date) if inv.due_date else None,
            contact=contact,
            currency=inv.currency_code or conn.base_currency,
            lines=lines,
            source=source,
            project_id=str(inv.project_id),
            project_code=(getattr(project, "project_code", None) or getattr(project, "name", "") or "")[:36],
            project_name=getattr(project, "name", "") or "",
            recorded_tax=money(inv.tax_amount),
            recorded_total=money(inv.amount_subtotal) + money(inv.tax_amount),
            reference=str(md.get("application_number") or ""),
        )

    @staticmethod
    def _category(sales: bool, source: str, cost_category: str | None, tax_code: str) -> str:
        if sales:
            return "revenue_reduced" if tax_code == "VAT_REDUCED" else "revenue"
        if source == "subcontractor" or "subcontract" in (cost_category or "").lower():
            return "subcontract_cost"
        return "material_cost"

    async def _guarantee_fee_docs(self, scope: set[uuid.UUID], period: tuple[date, date] | None) -> list[SyncDocument]:
        """Annual bank commission of each live given guarantee, one bill per guarantee and year."""
        try:
            from app.modules.guarantees.logic import LIVE_STATUSES
            from app.modules.guarantees.models import Guarantee
        except ImportError:  # pragma: no cover - optional module
            return []
        year = (period[1] if period else date.today()).year
        stmt = select(Guarantee).where(
            Guarantee.status.in_(LIVE_STATUSES),
            Guarantee.commission_rate_pct.is_not(None),
            Guarantee.direction == "given",
        )
        if scope:
            stmt = stmt.where(Guarantee.project_id.in_(scope))
        out = []
        for g in (await self.session.execute(stmt)).scalars():
            fee = money(Decimal(g.amount) * Decimal(g.commission_rate_pct) / Decimal("100"))
            if fee <= ZERO:
                continue
            start = date(year, 1, 1)
            day = max(start, g.issue_date) if g.issue_date and g.issue_date.year == year else start
            bank = g.issuer_bank or "Bank"
            out.append(
                SyncDocument(
                    record_type=AP_BILL,
                    record_id=f"{g.id}:{year}",
                    number=f"GF-{g.reference}-{year}"[:36],
                    doc_date=day,
                    contact=SyncContact(record_id=f"bank:{bank}", name=bank, kind="supplier", is_business=False),
                    currency=g.currency or "EUR",
                    lines=[
                        SyncLine(
                            description=f"Guarantee fee {g.reference} {g.commission_rate_pct}% p.a.",
                            net=fee,
                            category="guarantee_fees",
                            tax_code="ZERO",
                            tax_rate=ZERO,
                        )
                    ],
                    source="guarantee_fee",
                    project_id=str(g.project_id),
                    recorded_total=fee,
                )
            )
        return out

    # -- validation ------------------------------------------------------------

    async def validation_snapshot(self, conn: AccountingConnection, docs: list[SyncDocument]) -> dict[str, Any]:
        mapping = await self.mapping(conn)
        refs = await self._refs(conn, {d.record_id for d in docs})
        out = []
        for d in docs:
            cats = {"ar_control" if d.is_sales else "ap_control", *(ln.category for ln in d.lines)}
            if d.tax_total:
                cats.add("output_tax" if d.is_sales else "input_tax")
            if conn.provider in API_PROVIDERS:
                cats = {c for c in cats if c not in ("ar_control", "ap_control", "output_tax", "input_tax")}
            ref = refs.get((d.record_type, d.record_id))
            out.append(
                {
                    "record_id": d.record_id,
                    "record_type": d.record_type,
                    "number": d.number,
                    "doc_date": d.doc_date.isoformat(),
                    "categories": sorted(cats),
                    "accounts": {c: mapping.account(c)[0] for c in cats},
                    "lines": [
                        {
                            "tax_code": ln.tax_code,
                            "tax_rate": str(ln.tax_rate) if ln.tax_rate is not None else None,
                            "seed_rate": (
                                str(r)
                                if (r := templates.tax_rate(conn.country_code, ln.tax_code, d.doc_date)) is not None
                                else None
                            ),
                            "tax_key": mapping.tax_key(ln.tax_code, d.tax_direction),
                        }
                        for ln in d.lines
                    ],
                    "gross_total": str(d.gross_total),
                    "recorded_total": str(d.recorded_total) if d.recorded_total is not None else None,
                    "remote_total": str(ref.remote_total) if ref is not None and ref.remote_total is not None else None,
                    "contact": {
                        "record_id": d.contact.record_id,
                        "name": d.contact.name,
                        "tax_id": d.contact.tax_id,
                        "is_business": d.contact.is_business,
                    },
                }
            )
        return {"lock_date": conn.lock_date.isoformat() if conn.lock_date else None, "documents": out}

    async def findings(
        self, conn: AccountingConnection, docs: list[SyncDocument] | None = None
    ) -> list[dict[str, Any]]:
        docs = docs if docs is not None else await self.documents(conn)
        results = await evaluate(await self.validation_snapshot(conn, docs), target_id=str(conn.id))
        return [
            {
                "rule_id": r.rule_id,
                "severity": str(r.severity),
                "message": r.message,
                "element_ref": r.element_ref,
                "record_id": (r.details or {}).get("record_id"),
            }
            for r in results
        ]

    # -- refs and log ----------------------------------------------------------

    async def _refs(self, conn: AccountingConnection, record_ids: set[str]) -> dict[tuple[str, str], ExternalRef]:
        if not record_ids:
            return {}
        rows = await self.session.execute(
            select(ExternalRef).where(ExternalRef.connection_id == conn.id, ExternalRef.record_id.in_(list(record_ids)))
        )
        return {(r.record_type, r.record_id): r for r in rows.scalars()}

    async def _ref(self, conn: AccountingConnection, record_type: str, record_id: str) -> ExternalRef | None:
        row = await self.session.execute(
            select(ExternalRef).where(
                ExternalRef.connection_id == conn.id,
                ExternalRef.record_type == record_type,
                ExternalRef.record_id == record_id,
            )
        )
        return row.scalar_one_or_none()

    async def _store_ref(
        self, conn: AccountingConnection, record_type: str, record_id: str, **values: Any
    ) -> ExternalRef:
        ref = await self._ref(conn, record_type, record_id)
        if ref is None:
            ref = ExternalRef(connection_id=conn.id, record_type=record_type, record_id=record_id, external_id="")
            self.session.add(ref)
        for k, v in values.items():
            setattr(ref, k, v)
        ref.last_pushed_at = _now()
        await self.session.flush()
        return ref

    async def _log(
        self,
        conn: AccountingConnection,
        *,
        action: str,
        record_type: str,
        record_id: str = "",
        label: str = "",
        status_: str,
        reason: str | None = None,
        external_id: str | None = None,
        amount: Decimal | None = None,
        project_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> SyncLogEntry:
        prior = 0
        if record_id:
            prior = (
                await self.session.execute(
                    select(func.count()).where(
                        SyncLogEntry.connection_id == conn.id,
                        SyncLogEntry.record_type == record_type,
                        SyncLogEntry.record_id == record_id,
                        SyncLogEntry.action == action,
                        SyncLogEntry.resolved.is_(False),
                        SyncLogEntry.status == "failed",
                    )
                )
            ).scalar_one()
        if status_ == "success" and record_id:
            rows = await self.session.execute(
                select(SyncLogEntry).where(
                    SyncLogEntry.connection_id == conn.id,
                    SyncLogEntry.record_type == record_type,
                    SyncLogEntry.record_id == record_id,
                    SyncLogEntry.status == "failed",
                    SyncLogEntry.resolved.is_(False),
                )
            )
            for old in rows.scalars():
                old.resolved = True
        entry = SyncLogEntry(
            connection_id=conn.id,
            project_id=uuid.UUID(project_id) if project_id else None,
            action=action,
            record_type=record_type,
            record_id=record_id,
            record_label=label[:255],
            status=status_,
            attempt=prior + 1,
            error_reason=reason,
            external_id=external_id,
            amount=amount,
            details_=details or {},
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def list_log(
        self, conn: AccountingConnection, *, status_: str | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[list[SyncLogEntry], int]:
        base = select(SyncLogEntry).where(SyncLogEntry.connection_id == conn.id)
        if status_:
            base = base.where(SyncLogEntry.status == status_)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = await self.session.execute(base.order_by(SyncLogEntry.created_at.desc()).limit(limit).offset(offset))
        return list(rows.scalars()), total

    # -- adapters --------------------------------------------------------------

    def _tokens(self, conn: AccountingConnection) -> OAuthTokens:
        raw = decrypt_secret(conn.tokens_enc)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        return OAuthTokens(**{k: data[k] for k in ("access_token", "refresh_token", "expires_at") if k in data})

    async def adapter(self, conn: AccountingConnection) -> ProviderAdapter:
        cls = API_PROVIDERS.get(conn.provider)
        if cls is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{conn.provider} has no live API")
        tracking = {}
        rows = await self.session.execute(
            select(ExternalRef).where(ExternalRef.connection_id == conn.id, ExternalRef.record_type == "tracking")
        )
        for r in rows.scalars():
            tracking[r.record_id] = r.external_id
        ctx = ProviderContext(
            client_id=conn.client_id or "",
            client_secret=decrypt_secret(conn.client_secret_enc) or "",
            tokens=self._tokens(conn),
            tenant_id=conn.external_tenant_id or "",
            sandbox=conn.is_sandbox,
            mapping=await self.mapping(conn),
            tracking=tracking,
        )
        return cls(ctx, transport=transport_factory(conn.provider))

    def _save_tokens(self, conn: AccountingConnection, adapter: ProviderAdapter) -> None:
        if adapter.tokens_changed:
            conn.tokens_enc = encrypt_secret(json.dumps(adapter.ctx.tokens.as_dict()))

    async def authorization_url(self, conn: AccountingConnection, redirect_uri: str) -> str:
        if not conn.client_id or not conn.client_secret_enc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Enter the client id and secret first")
        return (await self.adapter(conn)).authorization_url(redirect_uri, str(conn.id))

    async def complete_oauth(
        self, conn: AccountingConnection, code: str, redirect_uri: str, tenant_id: str | None
    ) -> None:
        adapter = await self.adapter(conn)
        try:
            await adapter.exchange_code(code, redirect_uri)
        except ProviderError as exc:
            conn.status = "error"
            await self._log(conn, action="connect", record_type="connection", status_="failed", reason=exc.reason)
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=exc.reason) from exc
        self._save_tokens(conn, adapter)
        if tenant_id:
            conn.external_tenant_id = tenant_id
        conn.status = "connected"
        await self._log(conn, action="connect", record_type="connection", status_="success")

    # -- push ------------------------------------------------------------------

    async def push(
        self, conn: AccountingConnection, *, project_id: uuid.UUID | None = None, record_ids: set[str] | None = None
    ) -> dict[str, int]:
        """Push documents (and their contacts and projects) to a live provider."""
        adapter = await self.adapter(conn)
        docs = await self.documents(conn, project_id=project_id, record_ids=record_ids)
        findings = await self.findings(conn, docs)
        blocked: dict[str, list[str]] = {}
        for f in findings:
            if f["rule_id"] in BLOCKING_RULES and f.get("record_id"):
                blocked.setdefault(f["record_id"], []).append(f["message"])
        counts = {"success": 0, "failed": 0, "skipped": 0}
        for doc in docs:
            outcome = await self._push_one(conn, adapter, doc, blocked.get(doc.record_id))
            counts[outcome] += 1
        self._save_tokens(conn, adapter)
        conn.last_sync_at = _now()
        conn.last_sync_status = "failed" if counts["failed"] else "success"
        await self.session.flush()
        if counts["failed"]:
            await self._notify_failure(conn, counts["failed"])
        return counts

    async def _push_one(
        self, conn: AccountingConnection, adapter: ProviderAdapter, doc: SyncDocument, blocked: list[str] | None
    ) -> str:
        log = {
            "action": "push",
            "record_type": doc.record_type,
            "record_id": doc.record_id,
            "label": doc.number,
            "amount": doc.gross_total,
            "project_id": doc.project_id or None,
            "details": {"source": doc.source},
        }
        if blocked:
            await self._log(conn, **log, status_="failed", reason=" ".join(blocked))
            return "failed"
        ref = await self._ref(conn, doc.record_type, doc.record_id)
        digest = doc.payload_hash()
        if ref is not None and ref.payload_hash == digest:
            return "skipped"
        try:
            contact_ref = await self._ref(conn, "contact", doc.contact.record_id)
            contact = await adapter.push_contact(doc.contact, contact_ref.external_id if contact_ref else None)
            await self._store_ref(
                conn,
                "contact",
                doc.contact.record_id,
                external_id=contact.external_id,
                external_version=contact.external_version,
            )
            project_key = doc.project_code or doc.project_name
            if project_key and project_key not in adapter.ctx.tracking:
                tracking_id = await adapter.ensure_tracking(doc.project_code, doc.project_name)
                adapter.ctx.tracking[project_key] = tracking_id
                await self._store_ref(conn, "tracking", project_key, external_id=tracking_id)
            result = await adapter.push_document(
                doc, contact.external_id, ref.external_id if ref else None, ref.external_version if ref else None
            )
        except ProviderError as exc:
            await self._log(conn, **log, status_="failed", reason=exc.reason)
            return "failed"
        await self._store_ref(
            conn,
            doc.record_type,
            doc.record_id,
            external_id=result.external_id,
            external_version=result.external_version,
            payload_hash=digest,
            pushed_total=doc.gross_total,
            remote_total=result.remote_total,
        )
        if result.remote_total is not None and abs(result.remote_total - doc.gross_total) > Decimal("0.01"):
            await self._log(
                conn,
                **log,
                status_="failed",
                external_id=result.external_id,
                reason=f"Total mismatch after push: the accounting system shows {result.remote_total}, "
                f"the platform {doc.gross_total}.",
            )
            return "failed"
        await self._log(conn, **log, status_="success", external_id=result.external_id)
        return "success"

    async def retry(self, entry: SyncLogEntry) -> str:
        """Push the record of a failed log entry again."""
        conn = await self.get_connection(entry.connection_id)
        if entry.status != "failed" or entry.resolved:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only an open failure can be retried")
        ref = await self._ref(conn, entry.record_type, entry.record_id)
        if ref is not None:
            ref.payload_hash = ""  # force a resend
        counts = await self.push(conn, record_ids={entry.record_id})
        return "success" if counts["success"] else "failed"

    # -- pull ------------------------------------------------------------------

    async def pull_payments(self, conn: AccountingConnection) -> dict[str, int]:
        """Record remote payments in finance; the accounting system is master for payment status."""
        from app.modules.finance.models import Invoice, Payment
        from app.modules.finance.schemas import PaymentCreate
        from app.modules.finance.service import FinanceService

        adapter = await self.adapter(conn)
        rows = await self.session.execute(
            select(ExternalRef).where(
                ExternalRef.connection_id == conn.id, ExternalRef.record_type.in_([AR_INVOICE, AP_BILL])
            )
        )
        by_external = {r.external_id: r for r in rows.scalars() if ":" not in r.record_id}
        counts = {"success": 0, "failed": 0, "skipped": 0}
        try:
            payments = await adapter.pull_payments(
                {k: v.record_type for k, v in by_external.items()}, (conn.settings_ or {}).get("payments_since")
            )
        except ProviderError as exc:
            await self._log(conn, action="pull", record_type="payment", status_="failed", reason=exc.reason)
            counts["failed"] += 1
            await self._notify_failure(conn, 1)
            return counts
        finance = FinanceService(self.session)
        for p in payments:
            ref = by_external[p.external_document_id]
            key = f"acct:{p.external_payment_id}"[:64]
            exists = (await self.session.execute(select(Payment.id).where(Payment.idempotency_key == key))).first()
            if exists:
                counts["skipped"] += 1
                continue
            invoice = await self.session.get(Invoice, uuid.UUID(ref.record_id))
            if invoice is None:
                counts["skipped"] += 1
                continue
            try:
                await finance.create_payment(
                    PaymentCreate(
                        invoice_id=invoice.id,
                        payment_date=p.payment_date.isoformat(),
                        amount=str(money(p.amount)),
                        currency_code=invoice.currency_code or "",
                        reference=p.reference or None,
                        idempotency_key=key,
                        metadata={"source": "accounting_sync", "connection_id": str(conn.id)},
                    )
                )
                paid = (
                    await self.session.execute(
                        select(func.coalesce(func.sum(Payment.amount), 0)).where(
                            Payment.invoice_id == invoice.id, Payment.is_refund.is_(False)
                        )
                    )
                ).scalar_one()
                if money(paid) >= money(invoice.amount_total) and invoice.status in ("approved", "sent"):
                    await finance.pay_invoice(invoice.id, reason="Paid in the accounting system")
            except HTTPException as exc:
                await self._log(
                    conn,
                    action="pull",
                    record_type="payment",
                    record_id=ref.record_id,
                    label=invoice.invoice_number,
                    status_="failed",
                    reason=str(exc.detail),
                    amount=money(p.amount),
                )
                counts["failed"] += 1
                continue
            await self._log(
                conn,
                action="pull",
                record_type="payment",
                record_id=ref.record_id,
                label=invoice.invoice_number,
                status_="success",
                external_id=p.external_payment_id,
                amount=money(p.amount),
                project_id=str(invoice.project_id),
            )
            counts["success"] += 1
        self._save_tokens(conn, adapter)
        conn.settings_ = {**(conn.settings_ or {}), "payments_since": _now()}
        conn.last_sync_at = _now()
        await self.session.flush()
        if counts["failed"]:
            await self._notify_failure(conn, counts["failed"])
        return counts

    # -- exports ---------------------------------------------------------------

    async def export(
        self, conn: AccountingConnection, kind: str, period: tuple[date, date], columns: list[str] | None = None
    ) -> tuple[bytes, str, str]:
        """Build a file export; returns ``(content, filename, media_type)``."""
        tpl = templates.get_template(conn.chart_template)
        allowed = set(tpl["formats"]) | {"journal_csv", "journal_xlsx", "saft"}
        fmt_key = "datev_extf" if kind.startswith("datev") else kind
        if fmt_key not in allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{kind} is not available for this chart")
        docs = await self.documents(conn, period=period)
        mapping = await self.mapping(conn)
        settings = {**(conn.settings_ or {}), "account_length": tpl.get("account_length", 4)}
        stamp = f"{period[0]:%Y%m%d}_{period[1]:%Y%m%d}"
        if kind in ("datev_postings", "datev_master"):
            contacts = [d.contact for d in docs]
            accounts = personal_accounts(contacts, tuple(tpl["debtor_range"]), tuple(tpl["creditor_range"]))
            if kind == "datev_postings":
                content = datev.buchungsstapel(
                    docs,
                    mapping,
                    accounts,
                    settings=settings,
                    period=period,
                    skr=tpl.get("skr", ""),
                    currency=conn.base_currency,
                )
                name = f"EXTF_Buchungsstapel_{stamp}.csv"
            else:
                content = datev.stammdaten(contacts, accounts, settings=settings)
                name = f"EXTF_Stammdaten_{stamp}.csv"
            media = "text/csv; charset=windows-1252"
        elif kind in ("journal_csv", "journal_xlsx"):
            lines = journal_for(docs, mapping)
            cols = columns or (conn.settings_ or {}).get("journal_columns")
            if kind == "journal_csv":
                content, name, media = journal.to_csv(lines, cols), f"journal_{stamp}.csv", "text/csv; charset=utf-8"
            else:
                content = journal.to_xlsx(lines, cols)
                name = f"journal_{stamp}.xlsx"
                media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif kind == "saft":
            contacts = list({(c.kind, c.record_id): c for c in (d.contact for d in docs)}.values())
            content = saft.build(
                journal_for(docs, mapping),
                contacts,
                company_name=conn.name,
                country_code=conn.country_code or "",
                currency=conn.base_currency,
                period=period,
                tax_rows=templates.tax_codes(conn.country_code, period[1]),
            )
            name, media = f"SAF-T_{stamp}.xml", "application/xml"
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown export {kind}")
        await self._log(
            conn,
            action="export",
            record_type=kind,
            label=name,
            status_="success",
            amount=sum((d.gross_total for d in docs), ZERO),
            details={"documents": len(docs)},
        )
        conn.last_sync_at = _now()
        conn.last_sync_status = "success"
        return content, name, media

    # -- status and notifications ---------------------------------------------

    async def status_summary(self) -> dict[str, Any]:
        """Per-connection counts for the dashboard tile."""
        out = []
        for conn in await self.list_connections():
            rows = await self.session.execute(
                select(SyncLogEntry.status, func.count())
                .where(SyncLogEntry.connection_id == conn.id)
                .group_by(SyncLogEntry.status)
            )
            counts = dict(rows.all())
            open_failures = (
                await self.session.execute(
                    select(func.count()).where(
                        SyncLogEntry.connection_id == conn.id,
                        SyncLogEntry.status == "failed",
                        SyncLogEntry.resolved.is_(False),
                    )
                )
            ).scalar_one()
            out.append(
                {
                    "id": str(conn.id),
                    "name": conn.name,
                    "provider": conn.provider,
                    "status": conn.status,
                    "last_sync_at": conn.last_sync_at,
                    "last_sync_status": conn.last_sync_status,
                    "success": int(counts.get("success", 0)),
                    "failed": int(counts.get("failed", 0)),
                    "open_failures": int(open_failures),
                }
            )
        return {
            "connections": out,
            "open_failures": sum(c["open_failures"] for c in out),
            "providers": {"api": list(API_PROVIDERS), "file": list(FILE_PROVIDERS)},
        }

    async def _notify_failure(self, conn: AccountingConnection, failed: int) -> None:
        from app.core.events import event_bus

        try:
            event_bus.publish_detached(
                "accounting_sync.sync.failed",
                {"connection_id": str(conn.id), "provider": conn.provider, "failed": failed},
                source_module="accounting_sync",
            )
        except Exception:  # noqa: BLE001 - an alert never breaks the sync
            logger.warning("accounting_sync failure event not published", exc_info=True)
        if not conn.created_by:
            return
        try:
            from app.modules.notifications.service import NotificationService

            await NotificationService(self.session).notify_users(
                [conn.created_by],
                "error",
                "notification.accounting_sync_failed_title",
                entity_type="accounting_connection",
                entity_id=str(conn.id),
                body_key="notification.accounting_sync_failed_body",
                body_context={"connection": conn.name, "count": failed},
                action_url="/accounting-sync",
            )
        except Exception:  # noqa: BLE001
            logger.warning("accounting_sync failure notification failed for %s", conn.id, exc_info=True)
