# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules of an export batch (rule set ``accounting_export``).

* ``unbalanced`` - ERROR. Debit differs from credit on a document.
* ``datev_settings`` - ERROR. Consultant number, client number or fiscal year start is missing.
* ``account_length`` - ERROR. A ledger account is not numeric or not as long as the chart says.
* ``booking_text_length`` - WARNING. A booking text is cut at 60 characters.
* ``posting_key`` - ERROR. A BU key is not one to four digits.
* ``date_in_fiscal_year`` - ERROR. A document lies outside the fiscal year of the file.
* ``currency_iso`` - ERROR. A record has no valid three-letter currency.
* ``already_exported`` - ERROR. The record sits in another active batch.
* ``supplier_tax_id`` - WARNING. A counterparty tax id does not look like its country's.
* ``cost_centre_unmapped`` - ERROR. Cost centres are mapped but this project code has none.

Every result carries ``params`` so the client can show the message in the user's language.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)

logger = logging.getLogger(__name__)

EXPORT_RULE_SET = "accounting_export"
TOLERANCE = Decimal("0.01")
ZERO = Decimal("0")


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _docs(context: ValidationContext) -> list[dict[str, Any]]:
    rows = _data(context).get("documents")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _records(context: ValidationContext) -> list[dict[str, Any]]:
    rows = _data(context).get("records")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _fail(rule: ValidationRule, message: str, ref: Any, record_id: Any, **params: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=False,
        message=message,
        element_ref=None if ref is None else str(ref),
        details={"record_id": record_id, "params": params},
    )


def fiscal_year(settings: dict[str, Any]) -> tuple[date, date] | None:
    """First and last day of the fiscal year starting on ``fiscal_year_start`` (YYYYMMDD or ISO)."""
    raw = str(settings.get("fiscal_year_start") or "").replace("-", "")
    try:
        start = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    except (ValueError, IndexError):
        return None
    try:
        nxt = start.replace(year=start.year + 1)
    except ValueError:  # 29 February
        nxt = start.replace(year=start.year + 1, day=28)
    return start, nxt - timedelta(days=1)


class _ExportRule(ValidationRule):
    standard = "accounting"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR


class Unbalanced(_ExportRule):
    rule_id = "accounting_export.unbalanced"
    name = "Debit Equals Credit Per Document"
    description = "The journal of every exported document balances."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            _fail(
                self,
                f"Document {d.get('number')}: debit {d.get('debit')} differs from credit {d.get('credit')}.",
                d.get("number"),
                d.get("record_id"),
                number=d.get("number"),
                debit=str(d.get("debit")),
                credit=str(d.get("credit")),
            )
            for d in _docs(context)
            if abs(_dec(d.get("debit")) - _dec(d.get("credit"))) > TOLERANCE
        ]


class DatevSettings(_ExportRule):
    rule_id = "accounting_export.datev_settings"
    name = "DATEV Header Data Present"
    standard = "DATEV"
    category = RuleCategory.COMPLETENESS
    description = "A DATEV file needs the consultant number, the client number and the fiscal year start."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if data.get("format") != "datev":
            return []
        st = data.get("settings") or {}
        missing = [
            k for k in ("consultant_number", "client_number", "fiscal_year_start") if not str(st.get(k) or "").strip()
        ]
        if not missing:
            return []
        return [_fail(self, f"DATEV settings missing: {', '.join(missing)}.", None, None, fields=", ".join(missing))]


class AccountLength(_ExportRule):
    rule_id = "accounting_export.account_length"
    name = "Account Numbers Match The Account Length"
    standard = "DATEV"
    description = "Ledger accounts are numeric and as long as the account length of the chart."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if data.get("format") != "datev":
            return []
        length = int((data.get("settings") or {}).get("account_length") or 4)
        out = []
        for d in _docs(context):
            bad = [a for a in d.get("accounts") or [] if not (str(a).isdigit() and len(str(a)) == length)]
            if bad:
                out.append(
                    _fail(
                        self,
                        f"Document {d.get('number')}: account {', '.join(bad)} is not {length} digits.",
                        d.get("number"),
                        d.get("record_id"),
                        number=d.get("number"),
                        accounts=", ".join(bad),
                        length=length,
                    )
                )
        return out


class BookingTextLength(_ExportRule):
    rule_id = "accounting_export.booking_text_length"
    name = "Booking Text At Most 60 Characters"
    standard = "DATEV"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "DATEV cuts the booking text at 60 characters."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _data(context).get("format") != "datev":
            return []
        return [
            _fail(
                self,
                f"Document {d.get('number')}: a booking text is longer than 60 characters and is cut.",
                d.get("number"),
                d.get("record_id"),
                number=d.get("number"),
            )
            for d in _docs(context)
            if any(len(str(t)) > 60 for t in d.get("texts") or [])
        ]


class PostingKey(_ExportRule):
    rule_id = "accounting_export.posting_key"
    name = "Valid Posting Key"
    standard = "DATEV"
    description = "A DATEV posting key (BU key) is one to four digits."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _data(context).get("format") != "datev":
            return []
        out = []
        for d in _docs(context):
            bad = [str(k) for k in d.get("tax_keys") or [] if k and not re.fullmatch(r"\d{1,4}", str(k))]
            if bad:
                out.append(
                    _fail(
                        self,
                        f"Document {d.get('number')}: posting key {', '.join(bad)} is not valid.",
                        d.get("number"),
                        d.get("record_id"),
                        number=d.get("number"),
                        keys=", ".join(bad),
                    )
                )
        return out


class DateInFiscalYear(_ExportRule):
    rule_id = "accounting_export.date_in_fiscal_year"
    name = "Date Inside The Fiscal Year"
    standard = "DATEV"
    category = RuleCategory.COMPLIANCE
    description = "A DATEV file holds postings of one fiscal year only."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        year = fiscal_year(data.get("settings") or {})
        if data.get("format") != "datev" or year is None:
            return []
        lo, hi = year[0].isoformat(), year[1].isoformat()
        return [
            _fail(
                self,
                f"Document {d.get('number')} is dated {d.get('doc_date')}, outside the fiscal year {lo} to {hi}.",
                d.get("number"),
                d.get("record_id"),
                number=d.get("number"),
                date=d.get("doc_date"),
                start=lo,
                end=hi,
            )
            for d in _docs(context)
            if not lo <= str(d.get("doc_date")) <= hi
        ]


class CurrencyIso(_ExportRule):
    rule_id = "accounting_export.currency_iso"
    name = "ISO Currency Code"
    standard = "ISO 4217"
    description = "Every exported amount carries a three-letter currency code."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            _fail(
                self,
                f"Record {r.get('number')} has no valid currency code ({r.get('currency') or 'empty'}).",
                r.get("number"),
                r.get("record_id"),
                number=r.get("number"),
                currency=str(r.get("currency") or ""),
            )
            for r in _records(context)
            if r.get("record_type") != "cost_code"
            and (not re.fullmatch(r"[A-Z]{3}", str(r.get("currency") or "")) or r.get("currency") == "XXX")
        ]


class AlreadyExported(_ExportRule):
    rule_id = "accounting_export.already_exported"
    name = "Record Not In Another Active Batch"
    description = "A record is exported once; void the earlier batch to export it again."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            _fail(
                self,
                f"Record {r.get('number')} is already in batch {r.get('batch_no')}. Void that batch to export it again.",
                r.get("number"),
                r.get("record_id"),
                number=r.get("number"),
                batch=r.get("batch_no"),
            )
            for r in _records(context)
            if r.get("batch_no") is not None
        ]


class SupplierTaxId(_ExportRule):
    rule_id = "accounting_export.supplier_tax_id"
    name = "Counterparty Tax Id Has A Valid Shape"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A tax id looks like the numbers of its country."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out, seen = [], set()
        for d in _docs(context):
            c = d.get("contact") or {}
            if c.get("tax_id") and not c.get("tax_id_valid", True) and c.get("name") not in seen:
                seen.add(c.get("name"))
                out.append(
                    _fail(
                        self,
                        f"Tax id {c.get('tax_id')} of {c.get('name')} does not look valid.",
                        c.get("name"),
                        d.get("record_id"),
                        name=c.get("name"),
                        tax_id=c.get("tax_id"),
                    )
                )
        return out


class CostCentreUnmapped(_ExportRule):
    rule_id = "accounting_export.cost_centre_unmapped"
    name = "Cost Centre Is Mapped"
    category = RuleCategory.COMPLETENESS
    description = "When cost centres are mapped, every exported project code has one."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if not data.get("has_cost_code_map") or data.get("format") not in ("datev", "journal"):
            return []
        mapped = set(data.get("cost_codes_mapped") or [])
        return [
            _fail(
                self,
                f"Document {d.get('number')}: project code {d.get('project_code') or '-'} has no cost centre.",
                d.get("number"),
                d.get("record_id"),
                number=d.get("number"),
                code=d.get("project_code") or "",
            )
            for d in _docs(context)
            if d.get("project_code") not in mapped
        ]


_EXPORT_RULES: tuple[ValidationRule, ...] = (
    Unbalanced(),
    DatevSettings(),
    AccountLength(),
    BookingTextLength(),
    PostingKey(),
    DateInFiscalYear(),
    CurrencyIso(),
    AlreadyExported(),
    SupplierTaxId(),
    CostCentreUnmapped(),
)
EXPORT_RULE_IDS = tuple(r.rule_id for r in _EXPORT_RULES)


def register_export_rules() -> None:
    """Register the export rules with the core registry (idempotent)."""
    for rule in _EXPORT_RULES:
        rule_registry.register(rule, [EXPORT_RULE_SET])


async def evaluate_export(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the export rule set over a batch snapshot and return the failing results."""
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[EXPORT_RULE_SET], target_type="accounting_export", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("accounting_export validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]
