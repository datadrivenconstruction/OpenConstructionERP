# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for supplier prices, discounts, price list imports and item links.

Each rule is a pure check function plus a :class:`ValidationRule` wrapper. The
service calls the check functions on every write and refuses the write on an
error, the rule set ``supplier_catalogs`` runs the same checks over a data dict
for the validation dashboard, so the two can never disagree.

``context.data`` keys the rules read (all optional):
    ``prices``: list of ``{"ref", "gross", "net"}``
    ``discounts``: list of ``{"ref", "discount_pct"}``
    ``po_price_lists``: list of ``{"ref", "valid_to", "status"}`` plus ``order_date``
    ``price_list_rows``: list of ``{"ref", "vendor_sku"}``
    ``urls``: list of ``{"ref", "url"}``
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

RULE_SET = "supplier_catalogs"
MAX_URL_LENGTH = 1000


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def net_above_gross(gross: Any, net: Any) -> bool:
    """True when a net price is higher than the list price it was discounted from."""
    g, n = _dec(gross), _dec(net)
    return g is not None and n is not None and n > g


def discount_out_of_range(pct: Any) -> bool:
    """True when a discount percentage is below 0 or above 100."""
    p = _dec(pct)
    return p is not None and (p < 0 or p > 100)


def price_list_expired(valid_to: str | None, on: date) -> bool:
    """True when a price list's last valid day lies before ``on``."""
    if not valid_to:
        return False
    try:
        return date.fromisoformat(str(valid_to)[:10]) < on
    except ValueError:
        return False


def duplicate_skus(skus: list[str | None]) -> list[str]:
    """Vendor SKUs that occur more than once (case and surrounding space ignored)."""
    counts = Counter(s.strip().upper() for s in skus if s and s.strip())
    return sorted(k for k, n in counts.items() if n > 1)


def url_problem(url: str | None) -> str | None:
    """Why a product link is unsafe, or ``None`` when it is an http(s) URL with a host.

    Returns one of ``scheme`` (not http/https, e.g. ``javascript:``), ``host``
    (no host), ``length`` or ``whitespace``. Plain ``http`` is accepted for
    links but reported as a warning by :class:`ProductUrlSafe`.
    """
    if url is None or url == "":
        return None
    if len(url) > MAX_URL_LENGTH:
        return "length"
    if any(ch.isspace() for ch in url) or any(ord(ch) < 32 for ch in url):
        return "whitespace"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "host"
    if parts.scheme.lower() not in {"http", "https"}:
        return "scheme"
    if not parts.hostname:
        return "host"
    return None


class _Rule(ValidationRule):
    standard = RULE_SET
    category = RuleCategory.CONSISTENCY

    def _result(self, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=message,
            element_ref=ref,
            details=details,
            suggestion=None if passed else self.suggestion_text,
        )

    suggestion_text = ""

    @staticmethod
    def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
        data = context.data if isinstance(context.data, dict) else {}
        rows = data.get(key) or []
        return [r for r in rows if isinstance(r, dict)]


class NetNotAboveGross(_Rule):
    rule_id = "supplier_catalogs.net_not_above_gross"
    name = "Net price not above list price"
    severity = Severity.ERROR
    description = "A discounted net price must not be higher than the vendor's list (gross) price."
    suggestion_text = "Check the fixed net price or the list price."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self._result(False, f"Net {r.get('net')} is above list price {r.get('gross')}.", r.get("ref"))
            for r in self._rows(context, "prices")
            if net_above_gross(r.get("gross"), r.get("net"))
        ]
        return out or [self._result(True, "Every net price is at or below its list price.")]


class DiscountInRange(_Rule):
    rule_id = "supplier_catalogs.discount_in_range"
    name = "Discount between 0 and 100 %"
    severity = Severity.ERROR
    description = "A discount percentage must lie between 0 and 100."
    suggestion_text = "Enter the discount as a percentage, e.g. 12.5 for 12.5 %."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self._result(False, f"Discount {r.get('discount_pct')} % is outside 0-100 %.", r.get("ref"))
            for r in self._rows(context, "discounts")
            if discount_out_of_range(r.get("discount_pct"))
        ]
        return out or [self._result(True, "Every discount lies between 0 and 100 %.")]


class NoExpiredPriceListOnNewOrder(_Rule):
    rule_id = "supplier_catalogs.no_expired_price_list_on_po"
    name = "No expired price list on a new order"
    severity = Severity.ERROR
    description = "A new purchase order must not take prices from a price list whose validity has ended."
    suggestion_text = "Import the vendor's current price list or enter the agreed price by hand."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        raw = data.get("order_date")
        try:
            on = date.fromisoformat(str(raw)[:10]) if raw else date.today()
        except ValueError:
            on = date.today()
        out = [
            self._result(False, f"Price list expired on {r.get('valid_to')}.", r.get("ref"))
            for r in self._rows(context, "po_price_lists")
            if price_list_expired(r.get("valid_to"), on)
        ]
        return out or [self._result(True, "Every order price comes from a price list in force.")]


class NoDuplicateSkuInPriceList(_Rule):
    rule_id = "supplier_catalogs.no_duplicate_sku_in_price_list"
    name = "Vendor SKU unique in a price list"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "One vendor SKU may appear only once in a price list."
    suggestion_text = "Remove or merge the repeated rows before importing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        dups = duplicate_skus([r.get("vendor_sku") for r in self._rows(context, "price_list_rows")])
        if dups:
            return [self._result(False, f"Repeated vendor SKU: {', '.join(dups[:10])}.", None, skus=dups)]
        return [self._result(True, "No vendor SKU repeats in the price list.")]


class ProductUrlSafe(_Rule):
    rule_id = "supplier_catalogs.product_url_safe"
    name = "Product link is a safe web address"
    severity = Severity.ERROR
    description = "Product links must be http or https web addresses; https is expected."
    suggestion_text = "Paste the full address starting with https://."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for r in self._rows(context, "urls"):
            url = r.get("url")
            problem = url_problem(url)
            if problem:
                out.append(self._result(False, f"Unsafe link ({problem}): {str(url)[:80]}", r.get("ref")))
            elif url and urlsplit(url).scheme.lower() == "http":
                out.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=Severity.WARNING,
                        category=self.category,
                        passed=False,
                        message=f"Link is not encrypted (http): {url[:80]}",
                        element_ref=r.get("ref"),
                        suggestion="Use the https address of the page if the vendor offers one.",
                    )
                )
        return out or [self._result(True, "Every product link is an https address.")]


RULES: tuple[type[ValidationRule], ...] = (
    NetNotAboveGross,
    DiscountInRange,
    NoExpiredPriceListOnNewOrder,
    NoDuplicateSkuInPriceList,
    ProductUrlSafe,
)


def register_supplier_catalogs_rules() -> None:
    """Register the supplier-catalogs rule set (idempotent, the registry overwrites by id)."""
    for rule in RULES:
        rule_registry.register(rule(), rule_sets=[RULE_SET])


__all__ = [
    "RULES",
    "discount_out_of_range",
    "duplicate_skus",
    "net_above_gross",
    "price_list_expired",
    "register_supplier_catalogs_rules",
    "url_problem",
]
