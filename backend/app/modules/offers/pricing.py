"""Exact-decimal arithmetic of a customer offer.

Pure functions, no database, no floats. Money crosses every boundary as a decimal string and is
rounded ROUND_HALF_UP to the currency's minor unit, once per printed figure. The printed figures
are the binding ones: the net is the sum of the printed, rounded line totals, never a re-derivation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
HUNDRED = Decimal("100")

#: ISO 4217 minor units that are not 2.
_MINOR_0 = frozenset(
    ["JPY", "KRW", "VND", "CLP", "ISK", "UGX", "PYG", "XAF", "XOF", "XPF", "RWF", "KMF", "DJF", "GNF", "VUV"]
)
_MINOR_3 = frozenset(["BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"])

COUNTED_ROLES = frozenset({"base", "lump_sum", "provisional_sum", "markup"})
PRICED_ROLES = frozenset({"base", "lump_sum", "provisional_sum", "optional", "alternative"})
LINE_ROLES = ("base", "optional", "alternative", "provisional_sum", "lump_sum", "daywork_rate")
MARKUP_PRESENTATIONS = ("spread", "lines", "section")
TAX_MODES = ("standard", "reverse_charge", "exempt")

PLACEHOLDERS: tuple[str, ...] = (
    "offer_number",
    "revision",
    "issue_date",
    "valid_until",
    "validity_days",
    "payment_days",
    "customer_name",
    "project_name",
    "site_address",
    "net_total",
    "gross_total",
    "currency",
    "retention_percent",
    "advance_percent",
)
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def dec(value: Any, default: Decimal = ZERO) -> Decimal:
    """A Decimal from a string or number; ``default`` for blank or unreadable input."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    text = str(value).strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    try:
        out = Decimal(text)
    except InvalidOperation:
        return default
    return out if out.is_finite() else default


def minor_unit(currency: str | None) -> int:
    """Decimal places of the currency's minor unit (ISO 4217), 2 when unknown."""
    code = (currency or "").strip().upper()
    if code in _MINOR_0:
        return 0
    if code in _MINOR_3:
        return 3
    return 2


def quantize(amount: Decimal, currency: str | None) -> Decimal:
    """ROUND_HALF_UP to the currency's minor unit."""
    return amount.quantize(Decimal(1).scaleb(-minor_unit(currency)), rounding=ROUND_HALF_UP)


def money_str(amount: Decimal, currency: str | None) -> str:
    """Fixed-point string at the currency's minor unit, the shape every API field carries."""
    return format(quantize(amount, currency), "f")


def plain(value: Decimal) -> str:
    """A decimal without exponent or trailing zeros past one place ('12.5', '3', '0.125')."""
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


# -- Lines -----------------------------------------------------------------------------------


def _line_total(qty: Decimal, rate: Decimal, currency: str) -> Decimal:
    return quantize(qty * rate, currency)


def build_lines(
    items: Sequence[Mapping[str, Any]],
    *,
    currency: str,
    markups: Sequence[Mapping[str, Any]] = (),
    presentation: str = "spread",
    markup_section_label: str = "",
    default_tax_rate: Decimal = ZERO,
) -> dict[str, Any]:
    """Price the offer lines the customer sees.

    ``items`` come in print order. A row with ``kind == "section"`` opens a section; any other row
    is an item with ``role`` (see :data:`LINE_ROLES`), ``quantity``, ``unit_rate`` and, for an
    alternative, ``alternative_of`` (the base item's ordinal). ``markups`` are the estimate's active
    markups as ``{label, amount}``; how they appear is ``presentation``: ``spread`` pro rata into the
    unit rates, ``lines`` as lines with their own customer-facing label, ``section`` as a section.
    Cost, direct cost and markup percentages never appear in the output.
    """
    pres = presentation if presentation in MARKUP_PRESENTATIONS else "spread"
    direct = ZERO
    for it in items:
        if it.get("kind") != "section" and (it.get("role") or "base") in COUNTED_ROLES:
            direct += _line_total(dec(it.get("quantity")), dec(it.get("unit_rate")), currency)
    markup_total = sum((quantize(dec(m.get("amount")), currency) for m in markups), ZERO)
    factor = ZERO
    if pres == "spread" and direct > 0 and markup_total != 0:
        factor = markup_total / direct

    lines: list[dict[str, Any]] = []
    section_ordinal = ""
    for it in items:
        if it.get("kind") == "section":
            section_ordinal = str(it.get("ordinal") or "")
            lines.append(
                {
                    "kind": "section",
                    "ordinal": section_ordinal,
                    "description": str(it.get("description") or ""),
                    "section": "",
                    "level": int(it.get("level") or 0),
                }
            )
            continue
        role = it.get("role") if it.get("role") in LINE_ROLES else "base"
        qty = dec(it.get("quantity"))
        raw_rate = dec(it.get("unit_rate"))
        rate = quantize(raw_rate * (1 + factor), currency) if factor and pres == "spread" else raw_rate
        total = _line_total(qty, rate, currency)
        tax_rate = it.get("tax_rate")
        lines.append(
            {
                "kind": "item",
                "ordinal": str(it.get("ordinal") or ""),
                "description": str(it.get("description") or ""),
                "unit": str(it.get("unit") or ""),
                "quantity": plain(qty),
                "unit_rate": "" if role == "lump_sum" else plain(rate),
                "total": "" if role == "daywork_rate" else money_str(total, currency),
                "role": role,
                "alternative_of": str(it.get("alternative_of") or "") if role == "alternative" else "",
                "by_others": bool(it.get("by_others")),
                "section": str(it.get("section") if it.get("section") is not None else section_ordinal),
                "tax_rate": plain(dec(tax_rate, default_tax_rate))
                if tax_rate not in (None, "")
                else plain(default_tax_rate),
                "position_id": str(it.get("position_id") or ""),
            }
        )

    if pres in ("lines", "section"):
        label_section = markup_section_label if pres == "section" else ""
        if label_section and any(m.get("amount") for m in markups):
            lines.append({"kind": "section", "ordinal": "M", "description": label_section, "section": "", "level": 0})
        for idx, m in enumerate(markups, start=1):
            amount = quantize(dec(m.get("amount")), currency)
            lines.append(
                {
                    "kind": "item",
                    "ordinal": f"M.{idx:02d}" if label_section else f"M{idx}",
                    "description": str(m.get("label") or ""),
                    "unit": "",
                    "quantity": "1",
                    "unit_rate": "",
                    "total": money_str(amount, currency),
                    "role": "markup",
                    "alternative_of": "",
                    "by_others": False,
                    "section": "M" if label_section else "",
                    "tax_rate": plain(default_tax_rate),
                    "position_id": "",
                }
            )

    estimate_net = direct + markup_total
    return {"lines": lines, "estimate_net": estimate_net, "direct_total": direct, "markup_total": markup_total}


# -- Totals ----------------------------------------------------------------------------------


def totals(
    lines: Sequence[Mapping[str, Any]],
    *,
    currency: str,
    tax_mode: str = "standard",
    estimate_net: Decimal | None = None,
) -> dict[str, Any]:
    """Section subtotals, net, tax per rate, gross and the 'not included' block.

    Net is the sum of the printed line totals of the counted roles. Tax is rounded once per rate on
    the sum of the net lines at that rate (EN 16931-1 BR-CO-17). Under ``reverse_charge`` and
    ``exempt`` every rate is zero.
    """
    net = ZERO
    by_section: dict[str, Decimal] = {}
    by_rate: dict[str, Decimal] = {}
    not_included: list[dict[str, str]] = []
    for ln in lines:
        if ln.get("kind") == "section":
            continue
        role = ln.get("role")
        amount = dec(ln.get("total"))
        if role in COUNTED_ROLES:
            net += amount
            by_section[ln.get("section", "")] = by_section.get(ln.get("section", ""), ZERO) + amount
            rate_key = plain(dec(ln.get("tax_rate"))) if tax_mode == "standard" else "0"
            by_rate[rate_key] = by_rate.get(rate_key, ZERO) + amount
        elif role in ("optional", "alternative"):
            not_included.append(
                {
                    "ordinal": str(ln.get("ordinal") or ""),
                    "description": str(ln.get("description") or ""),
                    "role": role,
                    "alternative_of": str(ln.get("alternative_of") or ""),
                    "total": money_str(amount, currency),
                }
            )
    tax_groups = []
    tax_total = ZERO
    for rate_key in sorted(by_rate, key=lambda k: Decimal(k)):
        base = by_rate[rate_key]
        tax = quantize(base * Decimal(rate_key) / HUNDRED, currency)
        tax_total += tax
        tax_groups.append({"rate": rate_key, "base": money_str(base, currency), "tax": money_str(tax, currency)})
    if not tax_groups:
        tax_groups = [{"rate": "0", "base": money_str(ZERO, currency), "tax": money_str(ZERO, currency)}]
    gap = ZERO if estimate_net is None else net - estimate_net
    return {
        "net": money_str(net, currency),
        "tax_groups": tax_groups,
        "tax_total": money_str(tax_total, currency),
        "gross": money_str(net + tax_total, currency),
        "section_subtotals": {k: money_str(v, currency) for k, v in by_section.items()},
        "not_included": not_included,
        "rounding_gap": money_str(gap, currency),
        "tax_mode": tax_mode,
    }


# -- Payment schedule ------------------------------------------------------------------------


def schedule(
    rows: Sequence[Mapping[str, Any]],
    *,
    net: Decimal,
    tax_total: Decimal,
    currency: str,
) -> list[dict[str, Any]]:
    """Resolve draft instalments to amounts. The last one takes the remainder.

    A row carries ``percent`` or a fixed ``value``. Percent rows are ``net x percent / 100`` rounded
    half up; the last percent row is ``net`` minus the rows above it, so the sum is exactly the net.
    A fixed last row keeps its value and ``payment_plan.sum_matches`` reports any gap. Tax is split in
    proportion to the net and the last row takes the tax remainder.
    """
    out: list[dict[str, Any]] = []
    paid = ZERO
    paid_tax = ZERO
    count = len(rows)
    for i, row in enumerate(rows):
        last = i == count - 1
        fixed = dec(row.get("value"), Decimal("NaN")) if row.get("value") not in (None, "") else None
        if fixed is not None and not fixed.is_nan():
            amount = quantize(fixed, currency)
        elif last:
            amount = net - paid
        else:
            amount = quantize(net * dec(row.get("percent")) / HUNDRED, currency)
        takes_rest = last and (fixed is None or fixed.is_nan())
        if net == 0:
            tax = ZERO
        elif last and takes_rest:
            tax = tax_total - paid_tax
        else:
            tax = quantize(tax_total * amount / net, currency)
        percent = (amount / net * HUNDRED).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if net else ZERO
        paid += amount
        paid_tax += tax
        out.append(
            {
                "code": str(row.get("code") or f"{i + 1}"),
                "name": str(row.get("name") or ""),
                "kind": str(row.get("kind") or ("final" if last else "progress")),
                "due": dict(row.get("due") or {"type": "date"}),
                "percent": format(percent, "f"),
                "net": money_str(amount, currency),
                "tax": money_str(tax, currency),
                "gross": money_str(amount + tax, currency),
                "lag_days": int(row.get("lag_days") or 0),
                "payment_terms_days": row.get("payment_terms_days"),
                "takes_rest": takes_rest,
                "fixed": fixed is not None and not fixed.is_nan(),
            }
        )
    return out


def before_acceptance_percent(rows: Iterable[Mapping[str, Any]]) -> Decimal:
    """Sum of the percent due before acceptance: every row except the final one."""
    return sum((dec(r.get("percent")) for r in rows if r.get("kind") != "final"), ZERO)


def compose(
    items: Sequence[Mapping[str, Any]],
    *,
    currency: str,
    markups: Sequence[Mapping[str, Any]] = (),
    presentation: str = "spread",
    markup_section_label: str = "",
    tax_mode: str = "standard",
    tax_rate: Decimal = ZERO,
    instalments: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Lines, totals and resolved schedule of an offer in one pass: what an offer record stores."""
    rate = tax_rate if tax_mode == "standard" else ZERO
    built = build_lines(
        items,
        currency=currency,
        markups=markups,
        presentation=presentation,
        markup_section_label=markup_section_label,
        default_tax_rate=rate,
    )
    summed = totals(built["lines"], currency=currency, tax_mode=tax_mode, estimate_net=built["estimate_net"])
    resolved = schedule(instalments, net=dec(summed["net"]), tax_total=dec(summed["tax_total"]), currency=currency)
    return {
        "lines": built["lines"],
        "totals": summed,
        "schedule": resolved,
        "estimate_net": money_str(built["estimate_net"], currency),
    }


def accepted_figures(
    lines: Sequence[Mapping[str, Any]],
    instalments: Sequence[Mapping[str, Any]],
    ticked: Iterable[str],
    *,
    currency: str,
    tax_mode: str = "standard",
) -> dict[str, Any]:
    """The figures an acceptance awards: optional items the customer ticked become base lines first.

    A ticked alternative replaces the base item it points to, which drops out of the sum. The sent
    record itself is never changed; these figures go to the contract.
    """
    chosen = set(ticked)
    replaced = {
        str(ln.get("alternative_of"))
        for ln in lines
        if ln.get("role") == "alternative" and str(ln.get("ordinal")) in chosen
    }
    out: list[dict[str, Any]] = []
    for ln in lines:
        row = dict(ln)
        if row.get("kind") != "section":
            ordinal = str(row.get("ordinal"))
            if row.get("role") in ("optional", "alternative") and ordinal in chosen:
                row["role"] = "base"
            elif ordinal in replaced and row.get("role") in COUNTED_ROLES:
                row["role"] = "optional"
        out.append(row)
    summed = totals(out, currency=currency, tax_mode=tax_mode)
    resolved = schedule(instalments, net=dec(summed["net"]), tax_total=dec(summed["tax_total"]), currency=currency)
    return {"lines": out, "totals": summed, "schedule": resolved}


# -- Texts, numbers, dates -------------------------------------------------------------------


def unknown_placeholders(text: str) -> list[str]:
    """Names in ``{braces}`` that are not on the whitelist, in order of appearance."""
    seen: list[str] = []
    for name in _PLACEHOLDER_RE.findall(text or ""):
        if name not in PLACEHOLDERS and name not in seen:
            seen.append(name)
    return seen


def resolve(text: str, values: Mapping[str, str]) -> str:
    """Plain substitution of whitelisted placeholders; unknown ones stay as written."""

    def sub(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(values[name]) if name in PLACEHOLDERS and name in values else match.group(0)

    return _PLACEHOLDER_RE.sub(sub, text or "")


_SEP_BY_LANG = {
    "de": (",", "."),
    "es": (",", "."),
    "it": (",", "."),
    "nl": (",", "."),
    "pt": (",", "."),
    "tr": (",", "."),
    "id": (",", "."),
    "da": (",", "."),
    "el": (",", "."),
    "hr": (",", "."),
    "fr": (",", " "),
    "ru": (",", " "),
    "uk": (",", " "),
    "pl": (",", " "),
    "cs": (",", " "),
    "sk": (",", " "),
    "bg": (",", " "),
    "fi": (",", " "),
    "sv": (",", " "),
    "nb": (",", " "),
    "hu": (",", " "),
}


def _lang(locale: str | None) -> str:
    return (locale or "en").replace("_", "-").split("-")[0].strip().lower() or "en"


def format_decimal(value: Decimal | str, locale: str | None, places: int | None = None) -> str:
    """Locale grouping and decimal marks applied to an exact decimal string, no float on the way."""
    d = dec(value)
    if places is not None:
        d = d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = format(d, ",f")
    point, group = _SEP_BY_LANG.get(_lang(locale), (".", ","))
    return text.replace(",", "\0").replace(".", point).replace("\0", group)


def format_money(value: Decimal | str, currency: str | None, locale: str | None, *, symbol: bool = False) -> str:
    text = format_decimal(value, locale, minor_unit(currency))
    return f"{text} {currency}".strip() if symbol and currency else text


def format_date(value: str | date | None, locale: str | None) -> str:
    """ISO date in the reader's order: 12.11.2026, 12/11/2026, 11/12/2026 (en-US) or ISO."""
    if not value:
        return ""
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    loc = (locale or "en").replace("_", "-")
    lang = _lang(loc)
    if loc.lower() in ("en-us", "en-ca"):
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if lang in ("de", "ru", "uk", "pl", "cs", "sk", "tr", "fi", "nb", "da", "hr", "bg"):
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    if lang in ("fr", "es", "it", "pt", "el", "id", "nl") or loc.lower() == "en-gb":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    return d.isoformat()


def valid_until(issue: date, days: int) -> date:
    return issue + timedelta(days=int(days))


def revision_letter(index: int) -> str:
    """0 -> A, 1 -> B ... 25 -> Z, 26 -> AA."""
    out = ""
    n = index
    while True:
        out = chr(ord("A") + n % 26) + out
        n = n // 26 - 1
        if n < 0:
            return out


def revision_index(letter: str) -> int:
    n = 0
    for ch in (letter or "A").upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


_SEQ_RE = re.compile(r"\{seq(?::(\d+))?\}")


def render_number(pattern: str, year: int, seq: int) -> str:
    """``OF-{YYYY}-{seq:3}`` -> ``OF-2026-014``."""
    text = pattern.replace("{YYYY}", f"{year:04d}").replace("{YY}", f"{year % 100:02d}")
    return _SEQ_RE.sub(lambda m: str(seq).zfill(int(m.group(1) or 1)), text)


def next_sequence(pattern: str, year: int, existing: Iterable[str]) -> int:
    """One past the highest sequence already used under the pattern for the year."""
    head = pattern.replace("{YYYY}", f"{year:04d}").replace("{YY}", f"{year % 100:02d}")
    parts = _SEQ_RE.split(head)
    # split with one capture group alternates literal, width, literal ...
    regex = "".join(re.escape(p or "") if i % 2 == 0 else r"(\d+)" for i, p in enumerate(parts))
    try:
        compiled = re.compile(f"^{regex}$")
    except re.error:
        return 1
    best = 0
    for number in existing:
        m = compiled.match(number or "")
        if m and m.groups():
            best = max(best, int(m.group(1)))
    return best + 1


def fingerprint(positions: Iterable[Mapping[str, Any]], markups: Iterable[Mapping[str, Any]] = ()) -> str:
    """Hash of everything on the estimate the offer prints, to tell a stale revision from a current one."""
    blob = json.dumps(
        {
            "p": [
                [
                    str(p.get("id")),
                    str(p.get("ordinal")),
                    str(p.get("description")),
                    str(p.get("unit")),
                    plain(dec(p.get("quantity"))),
                    plain(dec(p.get("unit_rate"))),
                    str(p.get("role") or ""),
                ]
                for p in positions
            ],
            "m": [[str(m.get("label")), plain(dec(m.get("amount")))] for m in markups],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# -- Award -----------------------------------------------------------------------------------


def contract_payload(offer: Mapping[str, Any]) -> dict[str, Any]:
    """What accepting an offer writes into a client contract, one instalment to one milestone."""
    milestones = []
    for row in offer.get("instalments") or []:
        due = row.get("due") or {}
        fixed = bool(row.get("fixed"))
        milestones.append(
            {
                "code": str(row.get("code") or ""),
                "name": str(row.get("name") or ""),
                "kind": str(row.get("kind") or "progress"),
                "percent_of_contract": None if fixed else row.get("percent"),
                "value": row.get("net"),
                "activity_id": due.get("activity_id") if due.get("type") == "activity" else None,
                "planned_date": due.get("date") if due.get("type") == "date" else None,
                "lag_days": int(row.get("lag_days") or 0),
                "payment_terms_days": row.get("payment_terms_days"),
            }
        )
    return {
        "counterparty_type": "client",
        "counterparty_id": offer.get("contact_id"),
        "total_value": offer["net"],
        "currency": offer["currency"],
        "retention_percent": offer.get("retention_percent") or "0",
        "terms": {
            "payment_terms_days": offer.get("payment_days"),
            "offer_id": str(offer.get("id") or ""),
            "offer_number": offer.get("number"),
            "revision": offer.get("revision"),
        },
        "milestones": milestones,
        "advance_security": bool(offer.get("advance_security")),
    }
