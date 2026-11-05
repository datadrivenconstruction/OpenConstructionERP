"""Customer offer validation rules (rule set ``offer``).

Every rule reads one snapshot built by the service, ``{"offer": {...}, "pack": {...}, "facts": {...}}``,
so the rules run against a plain dict with no database. Pack rules (``de.``, ``fr.``, ``uk.``,
``us_ca.``) only fire when the project's pack lists them: a German project never sees the
California licence warning. Pack rules warn and never block.

The deposit cap reuses :func:`app.modules.contracts.payment_plan.check_deposit` and reports under
the existing id ``payment_plan.consumer_deposit_cap``. It is appended by :func:`evaluate` and not
registered, because registering that id again would replace the contract rule of the same name.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
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
from app.modules.contracts.payment_plan import check_deposit, deposit_limit_for
from app.modules.offers import pack as pack_mod
from app.modules.offers import pricing

logger = logging.getLogger(__name__)

OFFER_RULE_SET = "offer"
DEPOSIT_CAP_RULE_ID = "payment_plan.consumer_deposit_cap"

#: Keys that would print cost or markup data if they reached a customer-facing line.
FORBIDDEN_LINE_KEYS = frozenset(
    {"net_cost_rate", "target_rate", "cost", "direct_cost", "markup", "markup_percent", "overhead_percent", "resources"}
)
_PERCENT_IN_LABEL = re.compile(r"\d\s*%")

#: A finding: (element_ref, message, details).
Finding = tuple[str, str, dict[str, Any]]
Check = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], list[Finding]]


def _money(value: Any) -> Decimal:
    return pricing.dec(value)


def _is_private(offer: dict[str, Any]) -> bool:
    return offer.get("customer_kind") == "private"


def _parse(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _body(offer: dict[str, Any], kind: str) -> str:
    entry = (offer.get("texts") or {}).get(kind) or {}
    return str(entry.get("body") or "").strip()


# -- Checks ----------------------------------------------------------------------------------


def _customer_present(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    customer = offer.get("customer") or {}
    if offer.get("contact_id") or customer.get("name"):
        return []
    return [("customer", "The offer has no customer. Pick a contact.", {})]


def _billing_address_present(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    customer = offer.get("customer") or {}
    if not (offer.get("contact_id") or customer.get("name")):
        return []
    addr = customer.get("billing_address") or {}
    if addr.get("street") and addr.get("city"):
        return []
    return [("customer", "The customer has no billing address.", {})]


def _site_address_present(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    site = offer.get("site_address") or {}
    if offer.get("site_same_as_billing") or site.get("street") or site.get("city"):
        return []
    return [("site", "The project has no site address.", {})]


def _number_unique(offer: dict[str, Any], _pack: dict[str, Any], facts: dict[str, Any]) -> list[Finding]:
    if not facts.get("number_taken"):
        return []
    return [("number", f"Offer number {offer.get('number')} is already used.", {"number": offer.get("number")})]


def _valid_until_present(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    return [] if offer.get("valid_until") else [("valid_until", "The offer has no validity date.", {})]


def _valid_until_after_issue(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    issue, until = _parse(offer.get("issue_date")), _parse(offer.get("valid_until"))
    if issue and until and until <= issue:
        return [("valid_until", "Valid until must be after the issue date.", {})]
    return []


def _payment_terms_present(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    return [] if _body(offer, "payment_terms") else [("texts.payment_terms", "The offer has no payment terms.", {})]


def _placeholders_resolved(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for kind, entry in (offer.get("texts") or {}).items():
        for name in pricing.unknown_placeholders(str((entry or {}).get("body") or "")):
            out.append(
                (
                    f"texts.{kind}",
                    f'Text "{kind}" uses unknown placeholder {{{name}}}.',
                    {"block": kind, "placeholder": name},
                )
            )
    return out


def _no_cost_columns(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for ln in offer.get("lines") or []:
        leaked = sorted(FORBIDDEN_LINE_KEYS & set(ln))
        label_bad = ln.get("role") == "markup" and (
            not str(ln.get("description") or "").strip() or _PERCENT_IN_LABEL.search(str(ln.get("description")))
        )
        if leaked or label_bad:
            out.append(
                (
                    str(ln.get("ordinal") or ""),
                    "Cost or markup data would print. Spread or label the markups.",
                    {"keys": leaked},
                )
            )
    return out


def _totals_consistent(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    totals = offer.get("totals") or {}
    if not totals:
        return []
    currency = offer.get("currency")
    printed = [ln for ln in offer.get("lines") or [] if ln.get("kind") != "section"]
    net = sum((_money(ln.get("total")) for ln in printed if ln.get("role") in pricing.COUNTED_ROLES), Decimal(0))
    tax = sum((_money(g.get("tax")) for g in totals.get("tax_groups") or []), Decimal(0))
    ok = (
        pricing.money_str(net, currency) == pricing.money_str(_money(totals.get("net")), currency)
        and pricing.money_str(tax, currency) == pricing.money_str(_money(totals.get("tax_total")), currency)
        and pricing.money_str(net + tax, currency) == pricing.money_str(_money(totals.get("gross")), currency)
    )
    return [] if ok else [("totals", "Net, tax and gross do not add up from the printed lines.", {})]


def _rounding_gap(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    gap = _money((offer.get("totals") or {}).get("rounding_gap"))
    if offer.get("markup_presentation") != "spread" or gap == 0:
        return []
    shown = pricing.format_money(gap, offer.get("currency"), "en")
    return [("items", f"Spread rates move the net by {shown} from the estimate.", {"delta": str(gap)})]


def _unpriced_line(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for ln in offer.get("lines") or []:
        if ln.get("kind") == "section" or ln.get("role") not in ("base", "lump_sum", "provisional_sum"):
            continue
        qty, total = _money(ln.get("quantity")), _money(ln.get("total"))
        if qty > 0 and total == 0 and not ln.get("by_others"):
            ordinal = str(ln.get("ordinal") or "")
            out.append(
                (
                    ordinal,
                    f'Item {ordinal} has a quantity and no price. Price it, or mark it optional or "by others".',
                    {"ordinal": ordinal, "position_id": ln.get("position_id")},
                )
            )
    return out


def _alternative_target(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    items = [ln for ln in offer.get("lines") or [] if ln.get("kind") != "section"]
    bases = {str(ln.get("ordinal")) for ln in items if ln.get("role") in pricing.COUNTED_ROLES}
    out: list[Finding] = []
    for ln in items:
        if ln.get("role") == "alternative" and str(ln.get("alternative_of") or "") not in bases:
            o, t = str(ln.get("ordinal") or ""), str(ln.get("alternative_of") or "")
            out.append(
                (o, f"Alternative {o} points to item {t}, which is not in the offer.", {"ordinal": o, "target": t})
            )
    return out


def _single_currency(_offer: dict[str, Any], _pack: dict[str, Any], facts: dict[str, Any]) -> list[Finding]:
    currencies = {c for c in facts.get("currencies") or [] if c}
    return [("items", "The offer mixes currencies.", {"currencies": sorted(currencies)})] if len(currencies) > 1 else []


def _tax_rate_known(offer: dict[str, Any], pack: dict[str, Any], facts: dict[str, Any]) -> list[Finding]:
    if offer.get("tax_mode") != "standard" or not pack.get("key"):
        return []
    on = _parse(offer.get("issue_date")) or date.today()
    if pack_mod.tax_rates(pack, on):
        return []
    country, day = facts.get("country") or pack.get("key"), on.isoformat()
    return [("tax", f"No tax rate for {country} on {day} in the pack.", {"country": country, "date": day})]


def _reverse_charge_tax_id(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    if offer.get("tax_mode") != "reverse_charge" or (offer.get("customer") or {}).get("vat_id"):
        return []
    return [("customer", "Reverse charge needs the customer's VAT id.", {})]


def _consumer_gross(offer: dict[str, Any], pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    needs = (pack.get("consumer") or {}).get("gross_total")
    if needs and _is_private(offer) and not (offer.get("options") or {}).get("show_gross", True):
        return [("layout", "Consumer customer: show the gross total (pack rule).", {})]
    return []


def _stale_revision(offer: dict[str, Any], _pack: dict[str, Any], facts: dict[str, Any]) -> list[Finding]:
    if offer.get("status") in ("sent", "accepted") and facts.get("boq_changed"):
        r = offer.get("revision")
        return [("items", f"The BOQ changed after revision {r} was sent. Issue a new revision.", {"revision": r})]
    return []


def _sum_matches(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    rows = offer.get("schedule") or []
    if not rows:
        return []
    currency = offer.get("currency")
    total = sum((_money(r.get("net")) for r in rows), Decimal(0))
    net = _money((offer.get("totals") or {}).get("net"))
    if pricing.money_str(total, currency) == pricing.money_str(net, currency):
        return []
    s, n = pricing.money_str(total, currency), pricing.money_str(net, currency)
    return [("schedule", f"Instalments total {s}, the offer net is {n}.", {"sum": s, "net": n})]


def _non_negative(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    return [
        (str(r.get("code")), f"Instalment {r.get('code')} is negative.", {"code": r.get("code")})
        for r in offer.get("schedule") or []
        if _money(r.get("net")) < 0
    ]


def _dates_ordered(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    last: date | None = None
    for r in offer.get("schedule") or []:
        due = r.get("due") or {}
        day = _parse(due.get("date")) if due.get("type") == "date" else None
        if day is None:
            continue
        if last and day < last:
            out.append(
                (
                    str(r.get("code")),
                    f"Instalment {r.get('code')} falls due before the one above it.",
                    {"code": r.get("code")},
                )
            )
        last = day
    return out


def _final_last(offer: dict[str, Any], _pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    rows = offer.get("schedule") or []
    if any(r.get("kind") == "final" for r in rows[:-1]):
        return [("schedule", "The final instalment must be the last one.", {})]
    return []


def _abschlag_90(offer: dict[str, Any], pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    spec = pack_mod.rule(pack, "de.offer.abschlag_90")
    if not spec or not _is_private(offer):
        return []
    cap = Decimal(str(spec.get("value") or "90"))
    if pricing.before_acceptance_percent(offer.get("schedule") or []) > cap:
        return [("schedule", f"Instalments before acceptance exceed {cap}% (BGB §650m).", {"cap": str(cap)})]
    return []


def _insurance_named(offer: dict[str, Any], pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    if not pack_mod.rule(pack, "fr.offer.insurance_named"):
        return []
    body = _body(offer, "legal_notice")
    default = {v.strip() for v in ((pack.get("texts") or {}).get("legal_notice") or {}).values()}
    if body and body not in default:
        return []
    return [("texts.legal_notice", "The devis does not name the mandatory insurance.", {})]


def _reduced_vat_attestation(offer: dict[str, Any], pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    if not pack_mod.rule(pack, "fr.offer.reduced_vat_attestation") or offer.get("tax_mode") != "standard":
        return []
    rate = pricing.dec(offer.get("tax_rate"))
    needs = any(
        r.get("needs_attestation") and Decimal(str(r["rate"])) == rate for r in (pack.get("tax") or {}).get("rates", [])
    )
    if needs and not (offer.get("options") or {}).get("attestation_received"):
        return [("tax", "A reduced VAT rate needs the customer's attestation.", {})]
    return []


def _cancellation_notice(offer: dict[str, Any], pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    if not pack_mod.rule(pack, "uk.offer.cancellation_notice") or not _is_private(offer):
        return []
    if (offer.get("options") or {}).get("cancellation_notice"):
        return []
    return [("layout", "Off-premises consumer offer without a cancellation notice.", {})]


def _licence_number(offer: dict[str, Any], pack: dict[str, Any], _facts: dict[str, Any]) -> list[Finding]:
    if not pack_mod.rule(pack, "us_ca.offer.licence_number") or str(offer.get("licence_number") or "").strip():
        return []
    return [("details", "The licence number is missing (BPC §7030.5).", {})]


def _address_window_fit(_offer: dict[str, Any], _pack: dict[str, Any], facts: dict[str, Any]) -> list[Finding]:
    if facts.get("address_fit") == "overflow":
        return [("customer", "Address does not fit the envelope window.", {})]
    return []


# (rule_id, name, severity, category, check)
_SPEC: tuple[tuple[str, str, Severity, RuleCategory, Check], ...] = (
    ("offer.customer_present", "Offer has a customer", Severity.ERROR, RuleCategory.COMPLETENESS, _customer_present),
    (
        "offer.billing_address_present",
        "Customer has a billing address",
        Severity.ERROR,
        RuleCategory.COMPLETENESS,
        _billing_address_present,
    ),
    (
        "offer.site_address_present",
        "Project has a site address",
        Severity.WARNING,
        RuleCategory.COMPLETENESS,
        _site_address_present,
    ),
    ("offer.number_unique", "Offer number is unique", Severity.ERROR, RuleCategory.CONSISTENCY, _number_unique),
    (
        "offer.valid_until_present",
        "Offer has a validity date",
        Severity.WARNING,
        RuleCategory.COMPLETENESS,
        _valid_until_present,
    ),
    (
        "offer.valid_until_after_issue",
        "Validity ends after the issue date",
        Severity.ERROR,
        RuleCategory.CONSISTENCY,
        _valid_until_after_issue,
    ),
    (
        "offer.payment_terms_present",
        "Offer has payment terms",
        Severity.WARNING,
        RuleCategory.COMPLETENESS,
        _payment_terms_present,
    ),
    (
        "offer.placeholders_resolved",
        "Text placeholders are known",
        Severity.ERROR,
        RuleCategory.CONSISTENCY,
        _placeholders_resolved,
    ),
    (
        "offer.no_cost_columns",
        "No cost or markup data prints",
        Severity.ERROR,
        RuleCategory.COMPLIANCE,
        _no_cost_columns,
    ),
    (
        "offer.totals_consistent",
        "Totals add up from the printed lines",
        Severity.ERROR,
        RuleCategory.CONSISTENCY,
        _totals_consistent,
    ),
    (
        "offer.rounding_gap",
        "Spread rates keep the estimate net",
        Severity.WARNING,
        RuleCategory.CONSISTENCY,
        _rounding_gap,
    ),
    ("offer.unpriced_line", "Every item is priced", Severity.ERROR, RuleCategory.COMPLETENESS, _unpriced_line),
    (
        "offer.alternative_target",
        "Alternative points to an item",
        Severity.ERROR,
        RuleCategory.CONSISTENCY,
        _alternative_target,
    ),
    ("offer.single_currency", "One currency per offer", Severity.ERROR, RuleCategory.CONSISTENCY, _single_currency),
    ("offer.tax_rate_known", "Tax rate known to the pack", Severity.WARNING, RuleCategory.COMPLIANCE, _tax_rate_known),
    (
        "offer.reverse_charge_tax_id",
        "Reverse charge has a VAT id",
        Severity.ERROR,
        RuleCategory.COMPLIANCE,
        _reverse_charge_tax_id,
    ),
    (
        "offer.consumer_gross",
        "Consumer sees the gross total",
        Severity.WARNING,
        RuleCategory.COMPLIANCE,
        _consumer_gross,
    ),
    ("offer.stale_revision", "Revision matches the BOQ", Severity.WARNING, RuleCategory.CONSISTENCY, _stale_revision),
    (
        "offer.address_window_fit",
        "Address fits the envelope window",
        Severity.WARNING,
        RuleCategory.STRUCTURE,
        _address_window_fit,
    ),
    (
        "payment_plan.sum_matches",
        "Instalments add up to the net",
        Severity.ERROR,
        RuleCategory.CONSISTENCY,
        _sum_matches,
    ),
    (
        "payment_plan.non_negative",
        "Instalments are not negative",
        Severity.ERROR,
        RuleCategory.CONSISTENCY,
        _non_negative,
    ),
    (
        "payment_plan.dates_ordered",
        "Instalment dates are in order",
        Severity.WARNING,
        RuleCategory.CONSISTENCY,
        _dates_ordered,
    ),
    ("payment_plan.final_last", "Final instalment is last", Severity.WARNING, RuleCategory.CONSISTENCY, _final_last),
    (
        "de.offer.abschlag_90",
        "Instalments before acceptance within 90%",
        Severity.WARNING,
        RuleCategory.COMPLIANCE,
        _abschlag_90,
    ),
    (
        "fr.offer.insurance_named",
        "Devis names the insurance",
        Severity.WARNING,
        RuleCategory.COMPLIANCE,
        _insurance_named,
    ),
    (
        "fr.offer.reduced_vat_attestation",
        "Reduced VAT has an attestation",
        Severity.WARNING,
        RuleCategory.COMPLIANCE,
        _reduced_vat_attestation,
    ),
    (
        "uk.offer.cancellation_notice",
        "Consumer offer has a cancellation notice",
        Severity.WARNING,
        RuleCategory.COMPLIANCE,
        _cancellation_notice,
    ),
    (
        "us_ca.offer.licence_number",
        "Offer carries the licence number",
        Severity.WARNING,
        RuleCategory.COMPLIANCE,
        _licence_number,
    ),
)

#: Rules that only run when the project's pack lists them.
PACK_RULE_IDS = frozenset(r[0] for r in _SPEC if r[0].split(".")[0] in ("de", "fr", "uk", "us_ca"))


class _OfferRule(ValidationRule):
    standard = OFFER_RULE_SET

    def __init__(self, rule_id: str, name: str, severity: Severity, category: RuleCategory, check: Check) -> None:
        self.rule_id = rule_id
        self.name = name
        self.severity = severity
        self.category = category
        self.description = name
        self._check = check

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        offer, pack, facts = data.get("offer") or {}, data.get("pack") or {}, data.get("facts") or {}
        if self.rule_id in PACK_RULE_IDS and self.rule_id not in pack_mod.rule_ids(pack):
            return []
        findings = self._check(offer, pack, facts)
        if not findings:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=message,
                element_ref=ref,
                details=details,
            )
            for ref, message, details in findings
        ]


_RULES: tuple[ValidationRule, ...] = tuple(_OfferRule(*spec) for spec in _SPEC)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_offer_rules() -> None:
    """Register the rules with the core registry (idempotent: the registry overwrites by id)."""
    for rule in _RULES:
        rule_registry.register(rule, [OFFER_RULE_SET])


def _deposit_cap_findings(snapshot: dict[str, Any]) -> list[RuleResult]:
    offer, pack = snapshot.get("offer") or {}, snapshot.get("pack") or {}
    spec = pack_mod.rule(pack, DEPOSIT_CAP_RULE_ID)
    if not spec or not _is_private(offer):
        return []
    limit = deposit_limit_for(spec.get("jurisdiction"))
    rows = [r for r in offer.get("schedule") or [] if r.get("kind") == "deposit"]
    if limit is None or not rows:
        return []
    currency = str(offer.get("currency") or "")
    price = _money((offer.get("totals") or {}).get("gross"))
    deposit = sum((_money(r.get("gross")) for r in rows), Decimal(0))
    check = check_deposit(limit, price=price, deposit=deposit, currency=currency)
    if check.outcome != "over":
        return []
    cap = pricing.money_str(check.ceiling or Decimal(0), currency)
    return [
        RuleResult(
            rule_id=DEPOSIT_CAP_RULE_ID,
            rule_name="Deposit within the statutory limit",
            severity=Severity.WARNING,
            category=RuleCategory.COMPLIANCE,
            passed=False,
            message=f"The deposit exceeds the statutory cap of {cap}.",
            element_ref="schedule",
            details={"cap": cap, "reference": limit.reference, "verified": limit.verified},
        )
    ]


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the offer rule set and return the failing results only; never raises."""
    try:
        register_offer_rules()
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[OFFER_RULE_SET], target_type="offer", target_id=target_id
        )
        failed = [r for r in report.results if not r.passed and not r.is_engine_error]
        return failed + _deposit_cap_findings(snapshot)
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("offer validation failed for %s", target_id, exc_info=True)
        return []


__all__ = ["DEPOSIT_CAP_RULE_ID", "OFFER_RULE_SET", "PACK_RULE_IDS", "RULE_IDS", "evaluate", "register_offer_rules"]
