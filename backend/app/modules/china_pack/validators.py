# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Chinese bill, VAT, 预缴 and 数电票 rules, registered under ``cn_vat``.

Every rule reads one plain dict with ``record_type == "cn_vat_check"``, built
by :func:`app.modules.china_pack.service.build_record` from a stored project
or posted directly. Messages are English; the page translates by rule id with
the values in ``details``.

=============================== ======= ==========================================
rule                            sev     what it catches
=============================== ======= ==========================================
cn.code_format                  warning code fits no pattern of the bill's edition
cn.code_unique                  error   one code twice in a sub-project
cn.edition_mismatch             warning 2013 bill tendered after a known switch date
cn.guifei_head_2024             warning 规费 as its own head on a 2024 bill
cn.vat_base_pc_sum              error   VAT charged on 专业工程暂估价
cn.vat_rate_line                warning a line's stated rate is not its category's
cn.simplified_jiagong           error   new 甲供 3% election from 2026-01-01
cn.simplified_sunset            warning 清包工/老项目 3% invoice after 2027-12-31
cn.simplified_lock              error   method change inside the 36-month lock
cn.prepay_calc                  error   recorded 预缴 differs from the formula
cn.prepay_subcontract_invoice   warning subcontract deduction without site invoices
cn.fapiao_site                  error   construction 数电票 lacks site or project
cn.fapiao_number                error   number not 20 digits or wrong year prefix
cn.unlimited_risk               warning open-ended contract risk clause
cn.fee.noncompetitive_below_floor error safety fee rate below the provincial floor
cn.fee.schedule_not_in_force    error   fee schedule not in force on the tender date
cn.fee.guifei_after_abolition   error   规费 priced after the province dropped it
cn.fee.rate_outside_band        warning rate outside the published band
cn.fee.unsourced_rate           info    rate entered by the user, no official source
cn.labour.double_social_insurance warning labour factor on labour incl. social insurance
cn.tax.method_mixed             error   9% and 3% lines in one bill
cn.sc.safety_base_includes_lumpsum error safety base keeps a term the source excludes
cn.price.source_missing         warning material price without source or period
cn.standard.edition_mismatch    warning 2013 label after the national 2024 date
=============================== ======= ==========================================
"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any

from app.core.item_codes import code_patterns, shared_code_patterns
from app.core.line_tax import check_item_codes, method_change_locked, parse_date, to_decimal
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.modules.china_pack import service
from app.modules.china_pack.config import CN_TAX
from app.modules.tax_withholding.place_of_supply import PrepaymentPeriod, prepayment_schedule

logger = logging.getLogger(__name__)

CN_VAT_RULE_SET = "cn_vat"
_ZERO = Decimal(0)
_RISK_OPEN = {"unlimited", "open", "open_ended", "所有风险", "一切风险"}


def _record(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    if isinstance(data, dict) and data.get("record_type") == "cn_vat_check":
        return data
    return {}


def _profile(record: dict[str, Any]) -> dict[str, Any]:
    profile = record.get("profile")
    return profile if isinstance(profile, dict) else {}


def _edition(record: dict[str, Any]) -> str:
    return str(_profile(record).get("standard_edition") or CN_TAX["default_edition_key"])


def _election(record: dict[str, Any], basis: str) -> dict[str, Any]:
    for row in CN_TAX["simplified_elections"]:
        if row["basis"] == basis:
            return row
    return {}


def _fmt(amount: Decimal) -> str:
    return f"{amount:,.2f}"


class _CnRule(ValidationRule):
    standard = CN_VAT_RULE_SET

    def fail(self, message: str, details: dict[str, Any], ref: str | None = None) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=message,
            element_ref=ref,
            details=details,
        )

    def ok(self) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="OK",
        )

    def verdict(self, findings: list[RuleResult], applies: bool = True) -> list[RuleResult]:
        if findings:
            return findings
        return [self.ok()] if applies else []


# ── Bill ─────────────────────────────────────────────────────────────────────


def _code_findings(record: dict[str, Any]) -> list[Any]:
    profile = _profile(record)
    entries = [
        (str(line.get("ref") or ""), str(line.get("code") or ""), str(line.get("sub_project") or ""))
        for line in record.get("lines") or []
    ]
    patterns = code_patterns("gb50500", _edition(record), profile.get("site_subdivision"))
    return check_item_codes(entries, patterns, shared_code_patterns("gb50500"))


class CodeFormat(_CnRule):
    rule_id = "cn.code_format"
    name = "GB 50500 Item Code Format"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Item codes are 9 or 12 digits, or a supplementary code such as 01B001"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record:
            return []
        edition = _edition(record)
        found = [
            self.fail(
                f"Item code {f.code} matches no national or supplementary pattern for edition {edition}",
                {"code": f.code, "ed": edition},
                f.ref,
            )
            for f in _code_findings(record)
            if f.kind == "format"
        ]
        return self.verdict(found, bool(record.get("lines")))


class CodeUnique(_CnRule):
    rule_id = "cn.code_unique"
    name = "GB 50500 Item Code Unique In Sub-project"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "An item code is used once inside one sub-project (单项工程)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record:
            return []
        found = [
            self.fail(
                f"Item code {f.code} is used twice in sub-project {f.scope}",
                {"code": f.code, "sp": f.scope, "first": f.other_refs[0] if f.other_refs else ""},
                f.ref,
            )
            for f in _code_findings(record)
            if f.kind == "duplicate"
        ]
        return self.verdict(found, bool(record.get("lines")))


class EditionMismatch(_CnRule):
    rule_id = "cn.edition_mismatch"
    name = "Bill Edition Matches The Tender Date"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "A bill tendered after the province or city switched is on GB/T 50500-2024"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        profile = _profile(record)
        tendered = parse_date(profile.get("tender_date"))
        if not record or tendered is None or _edition(record) != service.EDITION_2013:
            return []
        switch = service.tender_switch_date(profile.get("site_subdivision"), profile.get("site_city"))
        if switch is None:
            return []
        place = str(profile.get("site_city") or profile.get("site_subdivision") or "")
        if tendered >= switch:
            return [
                self.fail(
                    f"Project tendered {tendered.isoformat()} in {place}: the bill uses GB 50500-2013, "
                    "expected GB/T 50500-2024",
                    {"date": tendered.isoformat(), "prov": place, "switch": switch.isoformat()},
                )
            ]
        return [self.ok()]


class GuifeiHead2024(_CnRule):
    rule_id = "cn.guifei_head_2024"
    name = "No 规费 Head On A 2024 Bill"
    severity = Severity.WARNING
    category = RuleCategory.STRUCTURE
    description = "GB/T 50500-2024 has four heads; 规费 is folded into labour and management fee"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record or _edition(record) != service.EDITION_2024:
            return []
        on_lines = [str(line.get("ref") or "") for line in record.get("lines") or [] if line.get("head") == "guifei"]
        in_markups = [n for n in record.get("markup_names") or [] if "规费" in str(n)]
        if on_lines or in_markups:
            return [
                self.fail(
                    "规费 is a separate head on a GB/T 50500-2024 bill. Move it into labour and management fee",
                    {"lines": len(on_lines), "markups": in_markups},
                    on_lines[0] if on_lines else None,
                )
            ]
        return [self.ok()]


class VatBasePcSum(_CnRule):
    rule_id = "cn.vat_base_pc_sum"
    name = "No VAT On The Specialist Prime-Cost Sum"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "专业工程暂估价 is priced VAT-inclusive and stays out of the VAT base"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record:
            return []
        pc_lines = [line for line in record.get("lines") or [] if line.get("kind") == service.PC_SUM_KIND]
        found = []
        for line in pc_lines:
            if line.get("tax_inclusive"):
                continue
            amount = to_decimal(line.get("amount"))
            found.append(
                self.fail(
                    f"VAT has been charged on 专业工程暂估价 {_fmt(amount)}, which already includes VAT",
                    {"amt": str(amount)},
                    str(line.get("ref") or ""),
                )
            )
        return self.verdict(found, bool(pc_lines))


class VatRateLine(_CnRule):
    rule_id = "cn.vat_rate_line"
    name = "Line VAT Rate Fits Its Category"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Works 9%, goods (including goods supplied with installation) 13%, services 6%"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        profile = _profile(record)
        if not record or profile.get("tax_method", "general") != "general":
            return []
        on = parse_date(profile.get("contract_date")) or parse_date(record.get("on")) or date.today()
        found = []
        stated = 0
        for line in record.get("lines") or []:
            if line.get("rate_pct") in (None, "") or line.get("kind") == service.PC_SUM_KIND:
                continue
            stated += 1
            category = str(line.get("tax_category") or "works")
            expected = service.line_rate(category, on)
            rate = to_decimal(line.get("rate_pct"))
            if expected is not None and rate != expected:
                found.append(
                    self.fail(
                        f"Line type {category} carries {rate.normalize()}%. Expected 9 (works), 13 (goods, "
                        "including goods supplied with installation) or 6 (services)",
                        {"t": category, "r": str(rate.normalize()), "expected": str(expected.normalize())},
                        str(line.get("ref") or ""),
                    )
                )
        return self.verdict(found, stated > 0)


# ── Tax method ───────────────────────────────────────────────────────────────


class SimplifiedJiagong(_CnRule):
    rule_id = "cn.simplified_jiagong"
    name = "No New 甲供 Simplified Election"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A 甲供 project contracted on or after 2026-01-01 cannot use the 3% simplified method"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        profile = _profile(record)
        jiagong = bool(profile.get("employer_supplied")) or profile.get("simplified_basis") == "employer_supplied"
        if not record or not jiagong or profile.get("tax_method") != "simplified":
            return []
        cutoff = parse_date(_election(record, "employer_supplied").get("no_new_election_from"))
        contracted = parse_date(profile.get("contract_date"))
        if profile.get("grandfathered") or cutoff is None or contracted is None or contracted < cutoff:
            return [self.ok()]
        return [
            self.fail(
                "甲供 project with a contract date on or after 2026-01-01 cannot use the 3% simplified method",
                {"contract_date": contracted.isoformat(), "cutoff": cutoff.isoformat()},
            )
        ]


class SimplifiedSunset(_CnRule):
    rule_id = "cn.simplified_sunset"
    name = "清包工 / 老项目 Election Still In Force"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "The 3% election for labour-only and old projects lapses on 2027-12-31"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        profile = _profile(record)
        basis = str(profile.get("simplified_basis") or "")
        if not record or profile.get("tax_method") != "simplified" or basis not in ("labour_only", "old_project"):
            return []
        ends = parse_date(_election(record, basis).get("valid_to"))
        if ends is None:
            return []
        found = []
        for inv in record.get("invoices") or []:
            issued = parse_date(inv.get("date"))
            rates = [str(r) for r in inv.get("rates") or []]
            if issued is None or issued <= ends or (rates and "3" not in rates):
                continue
            found.append(
                self.fail(
                    f"3% election for 清包工/老项目 lapses {ends.isoformat()}. Invoice date {issued.isoformat()}",
                    {"d": issued.isoformat(), "ends": ends.isoformat()},
                    str(inv.get("ref") or ""),
                )
            )
        return self.verdict(found, bool(record.get("invoices")))


class SimplifiedLock(_CnRule):
    rule_id = "cn.simplified_lock"
    name = "Tax Method Kept For 36 Months"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A simplified-method election cannot be left within 36 months"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        profile = _profile(record)
        history = [h for h in profile.get("method_history") or [] if isinstance(h, dict)]
        if not record or not history:
            return []
        lock = profile.get("lock_months") or CN_TAX["simplified_lock_months"]
        found = []
        for entry in history:
            if entry.get("method") != "simplified":
                continue
            election = parse_date(entry.get("election_date"))
            changed = parse_date(entry.get("changed_on"))
            if election and changed and method_change_locked(election, int(lock), changed):
                found.append(
                    self.fail(
                        f"Tax method changed within {lock} months of the election on {election.isoformat()}",
                        {"d": election.isoformat(), "changed_on": changed.isoformat(), "months": int(lock)},
                    )
                )
        return self.verdict(found)


# ── 预缴 ─────────────────────────────────────────────────────────────────────


def prepayment_rates(tax_method: str | None) -> tuple[Decimal, Decimal]:
    """(tax rate, prepayment rate) of a method, from the pack."""
    cfg = CN_TAX["prepayment"]
    if tax_method == "simplified":
        return to_decimal(cfg["simplified_tax_rate_pct"]), to_decimal(cfg["simplified_pct"])
    return to_decimal(cfg["general_tax_rate_pct"]), to_decimal(cfg["general_pct"])


def _periods(record: dict[str, Any]) -> list[dict[str, Any]]:
    prepayment = record.get("prepayment") if isinstance(record.get("prepayment"), dict) else {}
    return [p for p in prepayment.get("periods") or [] if isinstance(p, dict)]


class PrepayCalc(_CnRule):
    rule_id = "cn.prepay_calc"
    name = "预缴 Matches The Formula"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "(receipts - subcontract paid) / (1 + rate) x prepayment rate, shortfalls carried forward"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        periods = _periods(record)
        if not record or not periods:
            return []
        tax_rate, prepay_rate = prepayment_rates(_profile(record).get("tax_method"))
        schedule = prepayment_schedule(
            [
                PrepaymentPeriod(
                    period=str(p.get("period") or i + 1),
                    receipts=to_decimal(p.get("receipts")),
                    subcontract_paid=to_decimal(p.get("subcontract_paid")),
                    recorded_prepaid=None if p.get("recorded_prepaid") in (None, "") else p.get("recorded_prepaid"),
                )
                for i, p in enumerate(periods)
            ],
            tax_rate_pct=tax_rate,
            prepay_rate_pct=prepay_rate,
            carried_in=to_decimal((record.get("prepayment") or {}).get("carried_in")),
        )
        found = [
            self.fail(
                f"Prepayment {_fmt(r.recorded_prepaid or _ZERO)} differs from (receipts - subcontract)/"
                f"(1+{tax_rate.normalize()}%) x {prepay_rate.normalize()}% = {_fmt(r.prepaid)}",
                {
                    "period": r.period,
                    "got": str(r.recorded_prepaid),
                    "exp": str(r.prepaid),
                    "r": str(tax_rate.normalize()),
                    "p": str(prepay_rate.normalize()),
                },
            )
            for r in schedule
            if r.matches is False
        ]
        return self.verdict(found, any(r.recorded_prepaid is not None for r in schedule))


class PrepaySubcontractInvoice(_CnRule):
    rule_id = "cn.prepay_subcontract_invoice"
    name = "Subcontract Deduction Backed By Site Invoices"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A subcontract payment deducted from 预缴 has subcontractor invoices naming the site"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        periods = [p for p in _periods(record) if to_decimal(p.get("subcontract_paid")) > _ZERO]
        if not record or not periods:
            return []
        prepayment = record.get("prepayment") or {}
        site = str(prepayment.get("site_location") or _profile(record).get("site_city") or "").strip()
        found = []
        for p in periods:
            paid = to_decimal(p.get("subcontract_paid"))
            backed = sum(
                (
                    to_decimal(inv.get("amount"))
                    for inv in p.get("subcontract_invoices") or []
                    if isinstance(inv, dict) and (not site or site in str(inv.get("site_location") or ""))
                ),
                _ZERO,
            )
            if backed < paid:
                found.append(
                    self.fail(
                        f"A subcontract deduction of {_fmt(paid - backed)} has no subcontractor invoice naming "
                        f"site {site or '?'}",
                        {"amt": str(paid - backed), "loc": site, "period": str(p.get("period") or "")},
                    )
                )
        return self.verdict(found)


# ── 数电票 ───────────────────────────────────────────────────────────────────


class FapiaoSite(_CnRule):
    rule_id = "cn.fapiao_site"
    name = "Construction 数电票 Names Site And Project"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A construction-services invoice carries the site location and the project name"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        invoices = [i for i in record.get("invoices") or [] if i.get("construction", True)] if record else []
        if not invoices:
            return []
        found = []
        for inv in invoices:
            missing = [f for f in CN_TAX["fapiao"]["required_construction_fields"] if not str(inv.get(f) or "").strip()]
            if missing:
                found.append(
                    self.fail(
                        "Construction 数电票 without site location or project name",
                        {"missing": missing},
                        str(inv.get("ref") or ""),
                    )
                )
        return self.verdict(found)


class FapiaoNumber(_CnRule):
    rule_id = "cn.fapiao_number"
    name = "数电票 Number Format"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "20 digits, the first two being the year of issue"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        numbered = [i for i in record.get("invoices") or [] if str(i.get("number") or "").strip()] if record else []
        if not numbered:
            return []
        pattern = re.compile(CN_TAX["fapiao"]["number_pattern"])
        found = []
        for inv in numbered:
            number = str(inv["number"]).strip()
            issued = parse_date(inv.get("date"))
            yy = f"{issued.year % 100:02d}" if issued else ""
            if not pattern.fullmatch(number) or (yy and not number.startswith(yy)):
                found.append(
                    self.fail(
                        f"Invoice number {number} is not 20 digits or its year prefix is not {yy or '?'}",
                        {"n": number, "yy": yy},
                        str(inv.get("ref") or ""),
                    )
                )
        return self.verdict(found)


# ── Contract ─────────────────────────────────────────────────────────────────


class UnlimitedRisk(_CnRule):
    rule_id = "cn.unlimited_risk"
    name = "Contract Risk Is Bounded"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "The pricing-risk clause states bands; an open-ended clause is not allowed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        contract = record.get("contract") if record and isinstance(record.get("contract"), dict) else {}
        if not contract:
            return []
        clause = str(contract.get("risk_clause") or "").strip().lower()
        if contract.get("risk_unlimited") or clause in _RISK_OPEN:
            return [self.fail("The contract risk clause is open-ended (forbidden, S7 3.3.1)", {"clause": clause})]
        return [self.ok()]


# ── Provincial fee programme ─────────────────────────────────────────────────


def _fee(record: dict[str, Any]) -> dict[str, Any]:
    fee = record.get("fee")
    return fee if isinstance(fee, dict) and fee.get("result") else {}


def _fee_lines(fee: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    meta = ((fee.get("schedule") or {}).get("lines")) or {}
    return [(row, meta.get(row["code"]) or {}) for row in (fee.get("result") or {}).get("lines") or []]


def _doc(fee: dict[str, Any], meta: dict[str, Any] | None = None) -> str:
    return str((meta or {}).get("doc") or (fee.get("schedule") or {}).get("doc") or "")


def _place(fee: dict[str, Any]) -> str:
    return str(fee.get("jurisdiction_name_zh") or fee.get("jurisdiction") or "")


def _line_name(meta: dict[str, Any], code: str) -> str:
    return str(meta.get("name_zh") or meta.get("name_en") or code)


class FeeBelowFloor(_CnRule):
    rule_id = "cn.fee.noncompetitive_below_floor"
    name = "Non-Competitive Fee Not Below Its Floor"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A safety or civilised construction fee may not be discounted below the provincial minimum"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fee = _fee(_record(context))
        if not fee:
            return []
        found = []
        checked = 0
        for row, meta in _fee_lines(fee):
            if not meta.get("non_competitive") or row.get("floor") is None or row.get("rate") is None:
                continue
            checked += 1
            rate, floor = to_decimal(row["rate"]), to_decimal(row["floor"])
            if rate < floor:
                name = _line_name(meta, row["code"])
                found.append(
                    self.fail(
                        f"{name} {rate.normalize()}% is below the {_place(fee)} minimum {floor.normalize()}% "
                        f"({_doc(fee, meta)}); the bid is non-responsive",
                        {
                            "line": name,
                            "rate": str(rate.normalize()),
                            "floor": str(floor.normalize()),
                            "prov": _place(fee),
                            "doc": _doc(fee, meta),
                        },
                        row["code"],
                    )
                )
        return self.verdict(found, checked > 0)


class FeeScheduleNotInForce(_CnRule):
    rule_id = "cn.fee.schedule_not_in_force"
    name = "Fee Schedule In Force On The Tender Date"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "The provincial fee schedule is picked by the tender date, not by the newest edition"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fee = _fee(_record(context))
        if not fee or not fee.get("date"):
            return []
        if fee.get("in_force") is False:
            successor = str(fee.get("successor") or "")
            nxt = next((s for s in fee.get("schedules") or [] if s and s.get("key") == successor), None)
            succ_name = str((nxt or {}).get("name_zh") or successor or "-")
            return [
                self.fail(
                    f"Fee schedule {_doc(fee)} is not in force on the tender date {fee['date']}; use {succ_name}",
                    {"doc": _doc(fee), "date": fee["date"], "successor": succ_name},
                )
            ]
        return [self.ok()]


class GuifeiAfterAbolition(_CnRule):
    rule_id = "cn.fee.guifei_after_abolition"
    name = "No 规费 Line After The Province Dropped It"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Where 规费 was abolished as a line, social insurance sits in labour and management fee"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        fee = record.get("fee") if isinstance(record.get("fee"), dict) else {}
        abolished = parse_date(fee.get("guifei_abolished_from"))
        on = parse_date(fee.get("date"))
        if abolished is None or on is None or on < abolished:
            return []
        priced = [
            row["code"]
            for row, meta in _fee_lines(fee)
            if (meta.get("kind") == "guifei" or row.get("group") == "guifei") and to_decimal(row.get("amount")) > 0
        ]
        marked = [n for n in fee.get("markup_names") or record.get("markup_names") or [] if "规费" in str(n)]
        if priced or marked:
            return [
                self.fail(
                    f"{_place(fee)} dropped 规费 as a separate line from {abolished.isoformat()}; "
                    "move social insurance into labour/management",
                    {"prov": _place(fee), "date": abolished.isoformat(), "lines": priced, "markups": marked},
                    priced[0] if priced else None,
                )
            ]
        return [self.ok()]


class FeeRateOutsideBand(_CnRule):
    rule_id = "cn.fee.rate_outside_band"
    name = "Fee Rate Inside The Published Band"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A rate the user picked lies outside the band the provincial document publishes"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fee = _fee(_record(context))
        if not fee:
            return []
        found = []
        banded = 0
        for row, meta in _fee_lines(fee):
            band = meta.get("band") or {}
            if not band or row.get("rate") is None:
                continue
            banded += 1
            rate = to_decimal(row["rate"])
            low = to_decimal(band["min"]) if band.get("min") else None
            high = to_decimal(band["max"]) if band.get("max") else None
            if (low is not None and rate < low) or (high is not None and rate > high):
                name = _line_name(meta, row["code"])
                found.append(
                    self.fail(
                        f"{name} {rate.normalize()}% is outside the published band "
                        f"{band.get('min')}-{band.get('max')}% ({_doc(fee, meta)})",
                        {
                            "line": name,
                            "rate": str(rate.normalize()),
                            "min": str(band.get("min")),
                            "max": str(band.get("max")),
                            "doc": _doc(fee, meta),
                        },
                        row["code"],
                    )
                )
        return self.verdict(found, banded > 0)


class FeeUnsourcedRate(_CnRule):
    rule_id = "cn.fee.unsourced_rate"
    name = "User-Entered Rate Without An Official Source"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "Rates we hold no official text for are the user's own and are not checked"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fee = _fee(_record(context))
        if not fee:
            return []
        return [
            self.fail(
                f"{_line_name(meta, row['code'])} has no official source; it was entered by the user and is not "
                "checked",
                {"line": _line_name(meta, row["code"]), "status": row.get("status")},
                row["code"],
            )
            for row, meta in _fee_lines(fee)
            if meta.get("user_input") and row.get("status") == "user"
        ]


class DoubleSocialInsurance(_CnRule):
    rule_id = "cn.labour.double_social_insurance"
    name = "Labour Factor Not On Labour With Social Insurance"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A labour uplift for social insurance must not be applied to labour that already includes it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        fee = _fee(_record(context))
        if not fee:
            return []
        result = fee.get("result") or {}
        if result.get("labour_factor_applied") and fee.get("labour_includes_social_insurance"):
            factor = str((fee.get("schedule") or {}).get("labour_factor") or "")
            return [
                self.fail(
                    f"The x{factor} labour factor is applied to labour already marked as including social insurance",
                    {"factor": factor},
                )
            ]
        return [self.ok()]


class TaxMethodMixed(_CnRule):
    rule_id = "cn.tax.method_mixed"
    name = "One Tax Method Per Bill"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "General-method (9%) and simplified (3%) lines cannot sit in one bill"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        rates = {
            to_decimal(line.get("rate_pct")).normalize()
            for line in record.get("lines") or []
            if line.get("rate_pct") not in (None, "") and line.get("kind") != service.PC_SUM_KIND
        }
        if not rates:
            return []
        if Decimal(3) in rates and Decimal(9) in rates:
            return [self.fail("General (9%) and simplified (3%) tax methods are mixed in one bill", {})]
        return [self.ok()]


class SafetyBaseExcludes(_CnRule):
    rule_id = "cn.sc.safety_base_includes_lumpsum"
    name = "Safety Fee Base Leaves Out What The Source Excludes"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Where the document takes the safety fee on cost excluding lump-sum measures, the base must too"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from app.modules.china_pack.fees import effective_bases  # noqa: PLC0415

        fee = _fee(_record(context))
        if not fee:
            return []
        bases = effective_bases(fee)
        found = []
        checked = 0
        for row, meta in _fee_lines(fee):
            if not meta.get("excludes"):
                continue
            checked += 1
            base = bases.get(row["code"]) or {}
            kept = [t for t in meta["excludes"] if to_decimal(base.get(t))]
            if kept:
                name = _line_name(meta, row["code"])
                found.append(
                    self.fail(
                        f"{name} base must exclude lump-sum measure items",
                        {"line": name, "terms": kept, "prov": _place(fee)},
                        row["code"],
                    )
                )
        return self.verdict(found, checked > 0)


class PriceSourceMissing(_CnRule):
    rule_id = "cn.price.source_missing"
    name = "Material Prices Name Their Source"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A material price needs a source and period: the CWICR version or the user's price-file month"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        prices = record.get("prices") if isinstance(record.get("prices"), dict) else {}
        if not prices.get("material_positions"):
            return []
        missing = list(prices.get("unsourced_material") or [])
        if missing:
            return [
                self.fail(
                    f"{len(missing)} material price(s) have no source/period (CWICR version or the user's "
                    "price-file month)",
                    {"count": len(missing)},
                    missing[0],
                )
            ]
        return [self.ok()]


class StandardEditionMismatch(_CnRule):
    rule_id = "cn.standard.edition_mismatch"
    name = "National Edition Matches The Project Date"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "GB/T 50500-2024 applies nationally from its in-force date where no local switch date is known"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        profile = _profile(record)
        on = parse_date(profile.get("tender_date")) or parse_date(profile.get("contract_date"))
        if not record or on is None or _edition(record) != service.EDITION_2013:
            return []
        if service.tender_switch_date(profile.get("site_subdivision"), profile.get("site_city")) is not None:
            return []  # cn.edition_mismatch judges against the local date
        national = service.national_switch_date()
        if national is None:
            return []
        if on >= national:
            return [
                self.fail(
                    f"Project dated {on.isoformat()} is labelled GB 50500-2013; GB/T 50500-2024 applies from "
                    f"{national.isoformat()}",
                    {"date": on.isoformat(), "from": national.isoformat()},
                )
            ]
        return [self.ok()]


_RULES: tuple[ValidationRule, ...] = (
    CodeFormat(),
    CodeUnique(),
    EditionMismatch(),
    GuifeiHead2024(),
    VatBasePcSum(),
    VatRateLine(),
    SimplifiedJiagong(),
    SimplifiedSunset(),
    SimplifiedLock(),
    PrepayCalc(),
    PrepaySubcontractInvoice(),
    FapiaoSite(),
    FapiaoNumber(),
    UnlimitedRisk(),
    FeeBelowFloor(),
    FeeScheduleNotInForce(),
    GuifeiAfterAbolition(),
    FeeRateOutsideBand(),
    FeeUnsourcedRate(),
    DoubleSocialInsurance(),
    TaxMethodMixed(),
    SafetyBaseExcludes(),
    PriceSourceMissing(),
    StandardEditionMismatch(),
)

RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_cn_vat_rules() -> None:
    """Register the rules with the core registry. Idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, [CN_VAT_RULE_SET])


async def evaluate(record: dict[str, Any]) -> list[RuleResult]:
    """Run the ``cn_vat`` rules over one record and return the failing results."""
    register_cn_vat_rules()
    try:
        report = await validation_engine.validate(
            data=record,
            rule_sets=[CN_VAT_RULE_SET],
            target_type="cn_vat_check",
            target_id=str(record.get("ref") or ""),
        )
    except Exception:  # noqa: BLE001 - a check must report, not crash the page
        logger.warning("cn_vat validation failed", exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]


# Registered at import as well as at startup, so a registry read without the app sees the set.
register_cn_vat_rules()
