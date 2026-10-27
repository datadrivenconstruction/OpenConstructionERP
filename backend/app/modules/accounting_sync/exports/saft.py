# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""OECD​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ SAF-T 2.0 export (Standard Audit File for Tax).

Writes the general-ledger subset of the OECD schema: Header, MasterFiles
(GeneralLedgerAccounts, Customers, Suppliers, TaxTable) and GeneralLedgerEntries
built from the neutral journal. National SAF-T variants extend this structure;
their extra elements belong in the country pack.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, date, datetime
from decimal import Decimal
from xml.etree import ElementTree as ET  # noqa: N817 - stdlib writer only, no parsing of input

from app.modules.accounting_sync.postings import ZERO, JournalLine, SyncContact

NS = "urn:OECD:StandardAuditFile-Tax:2.00"


def _sub(parent: ET.Element, tag: str, text: object | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = str(text)
    return el


def _amount(parent: ET.Element, tag: str, value: Decimal) -> None:
    _sub(_sub(parent, tag), "Amount", f"{value:.2f}")


def build(
    lines: list[JournalLine],
    contacts: list[SyncContact],
    *,
    company_name: str,
    country_code: str,
    currency: str,
    period: tuple[date, date],
    tax_rows: list[dict[str, str]],
    software_version: str = "",
    namespace: str = NS,
    audit_file_version: str = "2.00",
) -> bytes:
    """Encode a SAF-T AuditFile as UTF-8 XML in the given variant's namespace."""
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}AuditFile")
    q = lambda t: f"{{{namespace}}}{t}"  # noqa: E731

    header = ET.SubElement(root, q("Header"))
    for tag, val in (
        ("AuditFileVersion", audit_file_version),
        ("AuditFileCountry", country_code or "XX"),
        ("AuditFileDateCreated", datetime.now(UTC).date().isoformat()),
        ("SoftwareCompanyName", "DataDrivenConstruction"),
        ("SoftwareID", "OpenConstructionERP"),
        ("SoftwareVersion", software_version or "1"),
    ):
        _sub(header, q(tag), val)
    company = _sub(header, q("Company"))
    _sub(company, q("Name"), company_name)
    _sub(header, q("DefaultCurrencyCode"), currency)
    crit = _sub(header, q("SelectionCriteria"))
    _sub(crit, q("SelectionStartDate"), period[0].isoformat())
    _sub(crit, q("SelectionEndDate"), period[1].isoformat())
    _sub(header, q("TaxAccountingBasis"), "A")

    master = _sub(root, q("MasterFiles"))
    gla = _sub(master, q("GeneralLedgerAccounts"))
    accounts: OrderedDict[str, str] = OrderedDict()
    for ln in lines:
        accounts.setdefault(ln.account, ln.account_name)
    for code, name in accounts.items():
        acc = _sub(gla, q("Account"))
        _sub(acc, q("AccountID"), code)
        _sub(acc, q("AccountDescription"), name or code)
        _sub(acc, q("AccountType"), "GL")
    for kind, block, item, id_tag in (
        ("customer", "Customers", "Customer", "CustomerID"),
        ("supplier", "Suppliers", "Supplier", "SupplierID"),
    ):
        rows = [c for c in contacts if c.kind == kind]
        if not rows:
            continue
        holder = _sub(master, q(block))
        for c in rows:
            el = _sub(holder, q(item))
            _sub(el, q(id_tag), c.record_id)
            _sub(el, q("Name"), c.name)
            if c.tax_id:
                _sub(el, q("TaxRegistrationNumber"), c.tax_id)
    table = _sub(master, q("TaxTable"))
    entry = _sub(table, q("TaxTableEntry"))
    _sub(entry, q("TaxType"), "VAT")
    _sub(entry, q("Description"), "Value added tax")
    for row in tax_rows:
        det = _sub(entry, q("TaxCodeDetails"))
        _sub(det, q("TaxCode"), row["tax_code"])
        _sub(det, q("Description"), row.get("name") or row["tax_code"])
        _sub(det, q("TaxPercentage"), row["rate_pct"])
        _sub(det, q("Country"), country_code or "XX")

    gle = _sub(root, q("GeneralLedgerEntries"))
    by_entry: OrderedDict[int, list[JournalLine]] = OrderedDict()
    for ln in lines:
        by_entry.setdefault(ln.entry_no, []).append(ln)
    _sub(gle, q("NumberOfEntries"), len(by_entry))
    _sub(gle, q("TotalDebit"), f"{sum((ln.debit for ln in lines), ZERO):.2f}")
    _sub(gle, q("TotalCredit"), f"{sum((ln.credit for ln in lines), ZERO):.2f}")
    journal = _sub(gle, q("Journal"))
    _sub(journal, q("JournalID"), "OE")
    _sub(journal, q("Description"), "OpenConstructionERP documents")
    _sub(journal, q("Type"), "GL")
    for no, group in by_entry.items():
        first = group[0]
        tx = _sub(journal, q("Transaction"))
        _sub(tx, q("TransactionID"), first.document_number or str(no))
        _sub(tx, q("Period"), first.posting_date.month)
        _sub(tx, q("PeriodYear"), first.posting_date.year)
        _sub(tx, q("TransactionDate"), first.posting_date.isoformat())
        _sub(tx, q("Description"), first.document_number)
        _sub(tx, q("SystemEntryDate"), first.posting_date.isoformat())
        _sub(tx, q("GLPostingDate"), first.posting_date.isoformat())
        for i, ln in enumerate(group, start=1):
            tl = _sub(tx, q("TransactionLine"))
            _sub(tl, q("RecordID"), i)
            _sub(tl, q("AccountID"), ln.account)
            if ln.counterparty_id:
                _sub(tl, q("CustomerID" if first.record_type == "ar_invoice" else "SupplierID"), ln.counterparty_id)
            _sub(tl, q("Description"), ln.description or ln.document_number)
            if ln.debit:
                _amount(tl, q("DebitAmount"), ln.debit)
            else:
                _amount(tl, q("CreditAmount"), ln.credit)
            if ln.tax_code:
                ti = _sub(tl, q("TaxInformation"))
                _sub(ti, q("TaxType"), "VAT")
                _sub(ti, q("TaxCode"), ln.tax_code)
                _sub(ti, q("TaxPercentage"), ln.tax_rate if ln.tax_rate is not None else "0")
                _amount(ti, q("TaxAmount"), ln.tax_amount)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
