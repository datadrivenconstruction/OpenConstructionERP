# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Zero-cost heuristic analysis of a correspondence record.

Pure stdlib, no model and no network call (same stance as
``inbound_email.delay_detection``). Runs on EVERY inbound message the
moment it is captured, so the review queue is never empty just because
no AI key is configured; the LLM pass, when requested, merges over this
floor and can only raise the quality, never lose these facts.

All money amounts are returned as canonical STRINGS ("12480.50") - money
is kept exact end to end, never a float.

The package-price scanner is deliberately fussy, rule for rule - each
rule below exists because its absence once produced a wrong figure
inside a gate that awards work.
"""

from __future__ import annotations

import re
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from typing import Any

# ── Category keywords ────────────────────────────────────────────────────
# First matching category wins, so order the list by specificity: a
# "revised quotation for variation 12" is a quote (a price you can act
# on), not a variation notice.

_CATEGORY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "quote",
        re.compile(
            r"\b(quotation|quote\s*(no|number|ref|#)|our\s+price|we\s+are\s+pleased\s+to\s+(offer|quote)|pricing\s+for|tender\s+sum)\b",
            re.I,
        ),
    ),
    (
        "rfi_response",
        re.compile(
            r"\b(rfi\s*[-#]?\s*\d+|in\s+response\s+to\s+your\s+(rfi|request\s+for\s+information)|answer\s+to\s+(query|rfi))\b",
            re.I,
        ),
    ),
    (
        "variation_notice",
        re.compile(
            r"\b(variation|change\s+order|scope\s+change|vo\s*[-#]?\s*\d+|extra\s+over|additional\s+works?)\b", re.I
        ),
    ),
    (
        "delay_notice",
        re.compile(
            r"\b(delay|extension\s+of\s+time|eot\b|behind\s+(schedule|programme)|standdown|inclement\s+weather)\b", re.I
        ),
    ),
    ("claim", re.compile(r"\b(claim|notice\s+of\s+dispute|liquidated\s+damages|back\s*charge|set[- ]?off)\b", re.I)),
    (
        "instruction",
        re.compile(
            r"\b(site\s+instruction|direction\s+to\s+proceed|you\s+are\s+(instructed|directed)|si\s*[-#]?\s*\d+)\b",
            re.I,
        ),
    ),
    (
        "approval",
        re.compile(r"\b(approved?|no\s+objection|released\s+for\s+construction|accepted\s+subject\s+to)\b", re.I),
    ),
    ("delivery", re.compile(r"\b(delivery|dispatch(ed)?|eta\b|consignment|tracking\s+number|freight)\b", re.I)),
)

# ── Fact extraction patterns ─────────────────────────────────────────────

# "$12,480.50", "AUD 12,480", "12,480.00 AUD", "€1.234,56" is out of scope
# (EU decimal comma) - keep to the en-AU shapes suppliers actually send.
#: The ``\d+`` in the decimal branch was unbounded and backtracked
#: quadratically over a long digit run with no decimal point after it:
#: 1.4 seconds on 32KB, ~55 seconds extrapolated to a 200KB body - and
#: this runs on every inbound message, so one long email stalled the
#: poller. Bounded to twelve digits, which is a trillion dollars.
_MONEY_RX = re.compile(
    r"(?:(?P<cur1>AUD|USD|NZD|EUR|GBP|\$|€|£)\s?)?"
    r"(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{1,12}\.\d{2})"
    r"(?:\s?(?P<cur2>AUD|USD|NZD|EUR|GBP))?",
)
_CURRENCY_MAP = {"$": "AUD", "€": "EUR", "£": "GBP"}

# The "No/number/ref/#/:" qualifier is REQUIRED and the id must contain a
# digit - "Quotation for supply" must not yield quote number "for".
_QUOTE_NO_RX = re.compile(
    r"\b(?:quote|quotation|qtn)\s*(?:no\.?|number|ref\.?|#|:)\s*[:\-]?\s*"
    r"((?=[A-Z0-9\-\/]*\d)[A-Z0-9][A-Z0-9\-\/]{1,19})\b",
    re.I,
)

# An UNLABELLED quote-number mention ("further to quote 274119"). Only
# trusted when the document names exactly ONE - two candidates means the
# right one is unknowable from the words, and taking the first once handed
# the SUPERSEDED number to put on a PO.
_WEAK_QNO_RX = re.compile(
    r"\b(?:quot(?:e|ation)|our\s+ref(?:erence)?|ref)\s*"
    r"(?:n[o0]\.?|number|nbr|num|#)?\s*[:#-]?\s*"
    r"([A-Z]{0,4}[-/]?\d{3,10}[A-Z]?)\b",
    re.I,
)

# Register-style references other modules mint (COR-005, RFI-12, VO#3,
# REG-RFQ-000123 style compound refs).
_REFERENCE_RX = re.compile(
    r"\b((?:COR|RFI|RFQ|VO|SI|PO|NCR|EOT|DEL|ORD)[-#/ ]?\d{1,6}|[A-Z]{2,5}-(?:RFI|RFQ|ORD|VO|DEL|TBX|T)-?\d{4,8})\b"
)

# "please respond by 21/08/2026", "reply no later than 2026-08-21",
# "response required by 21 August 2026"
_RESPOND_BY_RX = re.compile(
    r"(?:respon[dse]+|reply|answer|confirm|advise)[^.\n]{0,40}?\b(?:by|before|no\s+later\s+than|within)\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9},?\s+\d{4})",
    re.I,
)

_MONTHS = {
    m: i + 1
    for i, group in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ]
    )
    for m in group
}

# A question mark or an explicit ask strongly signals a reply is owed.
_REPLY_NEEDED_RX = re.compile(
    r"\?|\b(please\s+(advise|confirm|respond|reply|provide)|await(ing)?\s+your|let\s+us\s+know|kindly\s+(confirm|revert)|require\s+your\s+(response|approval|confirmation))\b",
    re.I,
)

# ── Package-price scanner ────────────────────────────────────────────────

#: A dollar figure, optionally written "4.12k".
_PKG_MONEY_RX = re.compile(
    r"(?:\$|\bAUD\s*)\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{1,12}(?:\.\d{1,2})?)\s*(k\b)?",
    re.I,
)
#: A figure with NO "$" but plainly labelled as the total - what most real
#: PDF text extraction gives back ("Total (ex GST)    4,120.00").
#: The label vocabulary is wide because a priced quote that reads as
#: unpriced is worse than a missed figure: it never counts toward
#: "2 of 3 quoted", so the gate blocks an award that should have gone
#: through. The gap allows dot leaders in PDF tables.
#:
#: THE NUMBER SHAPE, and the reason it is this fussy. Accepting a bare run
#: of three-or-more digits after a label word looked like a harmless
#: widening and was the worst bug in this file:
#:   "Total 1.234.567,89"      -> $1.23     (a $1.2M package)
#:   "Quoted ref 100042 ..."   -> $279,276  (a quote NUMBER as money)
#:   "Price list 2026 rev 3"   -> $2,026    (a year)
#: So a figure must carry a thousands separator or cents. The leading
#: lookbehind and trailing lookahead stop a European-grouped number being
#: read as its own first three digits.
_PKG_NUM = r"(?<![\d.,])(?:\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d{1,12}\.\d{2})(?![\d,]|\.\d)"
#: The one bare-integer case worth keeping: a round figure written right
#: up against its label ("Total: 48000"), close enough that it cannot be a
#: page number or a year further along the line, and not introduced by a
#: reference word.
_PKG_BARE = r"(?<![\d.,])\d{3,12}(?![\d.,])"
_REF_WORD_RX = re.compile(
    r"\b(?:ref|reference|no|number|nbr|num|page|pages|rev|revision|version|order|invoice|abn|acn|ph|phone|fax|item)\b[^\n]{0,12}$",
    re.I,
)

_PKG_TOTAL_RX = re.compile(
    r"\b(?:total|totals?\s+due|amount\s+(?:due|payable)|contract\s+sum|quoted?"
    r"|price|lump\s+sum|tender\s+sum|nett?|balance\s+due)\b"
    r"[^\n]{0,60}?(" + _PKG_NUM + r")\s*(k\b)?",
    re.I,
)
#: Same labels, bare integer, but the gap is tight - a bare number far from
#: its label is almost always something else on the same line.
_PKG_TOTAL_BARE_RX = re.compile(
    r"\b(?:total|totals?\s+due|amount\s+(?:due|payable)|contract\s+sum|quoted?"
    r"|price|lump\s+sum|tender\s+sum|nett?|balance\s+due)\b"
    r"[^\n]{0,3}?(" + _PKG_BARE + r")\s*(k\b)?",
    re.I,
)
#: European grouping, detected so it can be REPORTED rather than misread.
#: "1.234.567,89" and "4 120,00" are not en-AU shapes, so the scanner
#: declines the figure and says why instead of returning its first three
#: digits as dollars.
_EU_NUM_RX = re.compile(r"(?<![\d.,])\d{1,3}(?:[. ]\d{3})+,\d{1,2}(?![\d.,])")

#: A credit, a discount or an allowance REDUCES the total - it is never
#: the total. Without this the pre-discount figure won on every quote
#: that itemised its discount, overstating what the supplier asked for.
_CREDIT_RX = re.compile(
    r"\b(?:less|discount(?:ed)?|credit|rebate|deduct(?:ion)?|allowance|adjustment|refund)\b[^\n]{0,20}$",
    re.I,
)

#: Labels that mark a figure as a PART payment, never the package price.
#: Without this, "Total 40,115.46 … Deposit 4,011.55" would take the
#: deposit once we prefer the last labelled figure.
_PART_PAYMENT_RX = re.compile(r"\b(?:deposit|instal?ment|progress\s+claim|retention|part\s+payment|upfront)\b", re.I)
#: THE CLASSIC AUSTRALIAN TOTALS BLOCK, in the order suppliers print it:
#:   Total Ex 36,468.60 / GST 3,646.86 / Total 40,115.46
_NUM9 = r"(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})"
_TOTALS_RX = re.compile(
    r"\b(?:sub\s*)?total\s*(?:\(?\s*ex(?:cl(?:uding)?)?\.?\s*(?:gst)?\s*\)?|nett?)?"
    r"[^\d\n]{0,14}"
    + _NUM9
    + r"[^\d\n]{0,24}\bgst\b[^\d\n]{0,14}"
    + _NUM9
    + r"[^\d\n]{0,30}?\b(?:total|amount\s+payable|balance\s+due)\b"
    r"[^\d\n]{0,20}" + _NUM9,
    re.I,
)
_GST_RX = re.compile(r"\b(ex(?:cl(?:uding)?)?\.?\s*gst|inc(?:l(?:uding)?)?\.?\s*gst|plus\s*gst|\+\s*gst)\b", re.I)
#: A figure followed by a rate marker is a unit rate, not the package
#: price. The marker must be followed by a REAL UNIT: bare "per" ate the
#: total in "Total $48,000.00 per the schedule", handing the gate a
#: $2,500 line item and switching it off on a $48,000 package.
_UNITS = r"(?:m2|m3|m|lm|ea|each|hr|hour|day|week|month|item|unit|kg|t|km|l|pt|point|way|circuit|outlet)"
_RATE_RX = re.compile(
    r"\s*(?:/\s*" + _UNITS + r"\b|per\s+" + _UNITS + r"\b|\b" + _UNITS + r"\b|p/?h\b)",
    re.I,
)
#: Words that mark a figure as THE total rather than a passing number.
_WEIGHT_RX = re.compile(r"\b(?:total|quote|quoted|price|supply|amount|inc|incl|ex|excl|nett?|sum)\b", re.I)
#: Percentages are never money. "10% GST included, total $36,468.60" once
#: read as $10 and SWITCHED THE QUOTE GATE OFF on a $36,000 package.
#: Bounded on purpose: the unbounded form backtracked quadratically on a
#: long digit run with no '%' after it - 20 seconds on a 32KB body, and
#: this runs on EVERY inbound message.
_PERCENT_RX = re.compile(r"\d{1,12}(?:\.\d{1,4})?\s{0,4}%")

#: Currency markers. A quote in USD/GBP/NZD compared against AUD quotes
#: is a silent 1.5x error, so the scanner reports what it saw and the
#: caller can refuse it.
_CURRENCY_RX = re.compile(r"\b(AUD|USD|NZD|EUR|GBP|SGD|CAD)\b|([$€£¥])", re.I)
_NON_AUD = {"USD", "NZD", "EUR", "GBP", "SGD", "CAD", "€", "£", "¥"}

_LEAD_RX_A = re.compile(
    r"\b(?:lead\s*time|delivery|eta|available)\D{0,18}?"
    r"(\d{1,2}\s*(?:-|to|/)\s*\d{1,2}\s*(?:(?:business|working)\s*)?(?:day|week)s?"
    r"|\d{1,2}\s*(?:(?:business|working)\s*)?(?:day|week)s?)",
    re.I,
)
_LEAD_RX_B = re.compile(
    r"\b(\d{1,2}\s*(?:-|to|/)\s*\d{1,2}\s*(?:(?:business|working)\s*)?(?:day|week)s?"
    r"|\d{1,2}\s*(?:(?:business|working)\s*)?(?:day|week)s?)"
    r"\s*(?:lead|delivery|eta)",
    re.I,
)
_LEAD_RX_C = re.compile(r"\b(ex[- ]?stock|in stock|off the shelf|same day)\b", re.I)

#: A real quote document. Signature logos (image001.png) deliberately do
#: NOT count - counting them once let a supplier's question satisfy the
#: compare gate on a package with no prices at all.
_DOCLIKE_RX = re.compile(r"\.(pdf|docx?|xlsx?|xlsm|csv|rtf)$", re.I)

#: They are asking us something, whatever came stapled to it.
_QUERY_RX = re.compile(
    r"\b(can you (confirm|clarify|advise|send)|could you|please (confirm|clarify|advise)"
    r"|before we (quote|price)|do you (have|need|want)|which |what (is|are|size|type)"
    r"|any (drawings?|specs?|details?)|need (more|the) (info|detail|drawing|spec)"
    r"|not clear|unclear|query|question)\b",
    re.I,
)


def _num(s: str) -> float:
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return 0.0


def _dec(s: str) -> Decimal:
    """A figure as an exact decimal.

    Cents are the unit of the answer here: the totals block reconciles by
    comparing ex + gst against inc, and in binary floats that comparison
    fails on figures that are correct to the cent.
    """
    try:
        return Decimal(str(s).replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _result(val: Decimal, basis: str, evidence: str, warnings: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"amount": f"{val:.2f}", "basis": basis, "evidence": evidence}
    if warnings:
        # Surfaced rather than swallowed: every extracted figure is a
        # suggestion a human confirms, and the doubts are what they need
        # to see in order to confirm it honestly.
        out["warnings"] = warnings
    return out


def _fmt_amount(val: float) -> str:
    """Canonical exact-decimal string ("36468.60"), no float artefacts."""
    s = f"{val:.2f}"
    return s[:-3] if s.endswith(".00") and "." not in f"{val:g}" else s


def scan_package_price(text: str) -> dict[str, Any] | None:
    """The single authoritative price of a quote, with its evidence span.

    Returns ``{"amount", "basis", "evidence"}`` or None. Rules, each one a
    scar from a quote that was once read wrong:
    - Percentages stripped before anything reads as money.
    - A figure trailed by a rate marker (/hr, per, ea) is a unit rate - skip.
    - "$4.12k" is $4,120.
    - A LABELLED total outranks a loose figure; among equals the biggest wins.
    - The Australian totals block (Ex / GST / Inc) wins outright, but ONLY
      when ex + gst == inc reconciles (tolerance max(0.02, inc*0.001)); among
      multiple reconciling blocks the biggest wins (beats page-1 subtotals);
      the EX-GST figure is taken and labelled "ex gst".
    - Otherwise the GST basis is the marker NEAREST the figure within ±40
      chars - never one taken from anywhere in the document.
    - Evidence is the verbatim ±90 chars around the figure, because every
      extracted value is a suggestion until a person can see the words it
      came from.
    """
    # Horizontal whitespace only: the line structure is load-bearing. The
    # GST basis has to come from the figure's OWN line, or a "Freight
    # (ex GST)" line above the total relabels the total.
    t = re.sub(r"[^\S\n]+", " ", str(text or ""))
    t_money = _PERCENT_RX.sub(" ", t)

    def _evidence(s0: int, e0: int) -> str:
        return re.sub(r"\s+", " ", t[max(0, s0 - 90) : min(len(t), e0 + 90)]).strip()

    def _line_around(pos: int) -> tuple[int, int]:
        start = t.rfind("\n", 0, pos) + 1
        end = t.find("\n", pos)
        return start, (len(t) if end < 0 else end)

    warnings: list[str] = []

    # A non-AUD figure compared against AUD quotes is a silent 1.5x error,
    # so it is reported and the caller can refuse it.
    def _currency_note(s0: int, e0: int) -> None:
        lo, hi = _line_around(s0)
        for cm in _CURRENCY_RX.finditer(t[lo : max(hi, e0)]):
            token = (cm.group(1) or cm.group(2) or "").upper()
            if token in _NON_AUD:
                warnings.append(f"figure appears to be in {token}, not AUD")
                return

    # The totals block wins outright when it reconciles. Decimal, because
    # the reconciliation compares sums of cents and binary floats do not
    # add cents up exactly.
    best9: tuple[Decimal, re.Match[str]] | None = None
    for mt9 in _TOTALS_RX.finditer(t_money):
        ex9, gst9, inc9 = (_dec(mt9.group(i)) for i in (1, 2, 3))
        if not (ex9 and inc9):
            continue
        if abs((ex9 + gst9) - inc9) > max(Decimal("0.02"), inc9 / 1000):
            continue  # does not reconcile - not trusted
        if best9 is None or inc9 > best9[0]:
            best9 = (inc9, mt9)
    if best9:
        mt9 = best9[1]
        _currency_note(mt9.start(1), mt9.end(1))
        return _result(_dec(mt9.group(1)), "ex gst", _evidence(mt9.start(1), mt9.end(1)), warnings)

    # A figure written in European grouping cannot be read as en-AU, and
    # taking its first three digits gave "$1.23" for a $1.2M package.
    # Decline it out loud instead.
    eu = [m for m in _EU_NUM_RX.finditer(t_money) if _WEIGHT_RX.search(t_money[max(0, m.start() - 34) : m.start()])]

    cands: list[tuple[int, Decimal, int, int]] = []
    seen: list[tuple[int, int]] = []

    def _add(m: re.Match[str], kx: str | None, labelled: bool) -> None:
        s0, e0 = m.start(1), m.end(1)
        if any(s0 < e and s < e0 for s, e in seen):
            return  # already counted this figure
        val = _dec(m.group(1))
        if not val:
            return
        if kx:
            val *= 1000  # "$4.12k" is $4,120, not $4.12
        if _RATE_RX.match(t_money[m.end() :][:26]):
            return  # a unit rate, not the package price
        head = t_money[max(0, m.start() - 34) : m.start()]
        # A deposit / progress claim / retention is a slice of the price,
        # never the price - and it is usually printed last, which is
        # exactly where the "prefer the final total" rule looks.
        if _PART_PAYMENT_RX.search(head):
            return
        # A credit or a discount line reduces the total; it is not one.
        if _CREDIT_RX.search(head) or t_money[max(0, s0 - 2) : s0].rstrip().endswith("-"):
            return
        seen.append((s0, e0))
        cands.append((2 if (labelled or _WEIGHT_RX.search(head)) else 1, val, s0, e0))

    for m in _PKG_MONEY_RX.finditer(t_money):
        _add(m, m.group(2), False)
    for m in _PKG_TOTAL_RX.finditer(t_money):
        _add(m, m.group(2), True)
    for m in _PKG_TOTAL_BARE_RX.finditer(t_money):
        # A bare integer is only money when nothing introduces it as a
        # reference: "Quoted ref 100042" is a quote number, not $279,276.
        if not _REF_WORD_RX.search(t_money[max(0, m.start(1) - 20) : m.start(1)]):
            _add(m, m.group(2), True)

    if not cands:
        if eu:
            return {
                "amount": "",
                "basis": "",
                "evidence": _evidence(eu[-1].start(), eu[-1].end()),
                "warnings": ["the total is written in a format this cannot read - check it by hand"],
            }
        return None

    top = max(c[0] for c in cands)
    best = [c for c in cands if c[0] == top]
    # PREFER THE LAST labelled total, not the biggest. "Total $10,000 /
    # less discount $500 / Total $9,500" took the pre-discount figure
    # under a biggest-wins rule, which overstates every discounted quote.
    _w, val, s0, e0 = max(best, key=lambda c: c[2])
    biggest = max(c[1] for c in best)
    if biggest > val:
        warnings.append(f"a larger figure of {biggest:.2f} also appears - check which is the total")
    if eu:
        warnings.append("a figure in this quote uses a format this cannot read - check it by hand")

    # THE BASIS COMES FROM THE FIGURE'S OWN LINE. Reading a window either
    # side of it scavenged "(ex GST)" off the freight line above and
    # labelled an inc-GST total as ex-GST, understating it by 10%.
    basis = ""
    lo, hi = _line_around(s0)
    gsts = list(_GST_RX.finditer(t[lo:hi]))
    if gsts:
        gst = min(gsts, key=lambda g: min(abs(lo + g.start() - e0), abs(lo + g.end() - s0)))
        basis = re.sub(r"\s+", " ", gst.group(1)).lower()
    _currency_note(s0, e0)
    return _result(val, basis, _evidence(s0, e0), warnings)


def scan_lead_time(text: str) -> str:
    t = re.sub(r"\s+", " ", str(text or ""))
    m = _LEAD_RX_A.search(t) or _LEAD_RX_B.search(t)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    if _LEAD_RX_C.search(t):
        return "ex stock"
    return ""


def scan_quote_number(text: str, price_amount: str = "") -> str | None:
    """Their quote number - what goes on the order and the invoice.

    A LABELLED "Quote No: 100042" form beats a passing "further to quote
    274119" mention anywhere in the document; an unlabelled number only
    counts when the document names exactly one; and a number equal to the
    price digits is the money, not a reference.
    """
    t = re.sub(r"\s+", " ", str(text or ""))
    m = _QUOTE_NO_RX.search(t)
    if not m:
        seen = {mm.group(1).upper(): mm for mm in _WEAK_QNO_RX.finditer(t)}
        m = next(iter(seen.values())) if len(seen) == 1 else None
    if not m:
        m = re.search(r"\b(QU[-/]?\d{4,10}|Q[-/]\d{3,10})\b", t, re.I)
    if not m:
        return None
    qno = m.group(1).strip().upper()
    if qno.isdigit() and len(qno) >= 5 and qno in re.sub(r"\D", "", str(price_amount or "")):
        return None  # that was the money, not a reference
    return qno


def reply_kind(text: str, attachment_names: list[str] | None = None) -> str:
    """quote | query | other - the counting rule behind "2 of 3 quoted".

    A price outranks the question test ("here's our price, can you confirm
    delivery?" is a quote). A question outranks a stapled document. A real
    quote-like document (pdf/doc/xls/csv/rtf - never a signature logo)
    makes it a quote even with no price in the prose.
    """
    t = str(text or "")
    if scan_package_price(t):
        return "quote"
    if _QUERY_RX.search(t) or (t.count("?") >= 1 and len(t) < 1200):
        return "query"
    names = [str(n).strip() for n in (attachment_names or []) if str(n).strip()]
    if any(_DOCLIKE_RX.search(n) for n in names):
        return "quote"
    return "other"


# ── Date + list-price helpers ────────────────────────────────────────────


def _to_iso_date(raw: str) -> str | None:
    """Normalise a matched date string to yyyy-mm-dd, or None if implausible.

    d/m/y is the assumed order for slash dates - this register's users are
    Australian; an ambiguous 03/04 is March 4 in the US and 3 April here,
    and guessing US order would file deadlines a month wrong.
    """
    raw = raw.strip().rstrip(",.")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", raw)
        if m:
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if year < 100:
                year += 2000
        else:
            m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})", raw)
            if not m:
                return None
            day, year = int(m.group(1)), int(m.group(3))
            month = _MONTHS.get(m.group(2).lower(), 0)
    if not (2000 <= year <= 2100):
        return None
    # BUILD THE DATE RATHER THAN RANGE-CHECK IT. "31 February" and
    # "31/04/2026" both passed a 1-31 day check and were stored as a
    # deadline no calendar has, which then sorted oddly and could never be
    # met. `date()` is the only thing that actually knows the month
    # lengths and the leap years.
    try:
        return _date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_prices(text: str) -> list[dict[str, str]]:
    """Every marked price in the text (context chips for the reviewer).

    Percentages are stripped first so "10% GST" never lists as $10; a bare
    number with no currency marker is a quantity or a phone number more
    often than a price - only marked amounts are kept.
    """
    text = _PERCENT_RX.sub(" ", text)
    prices: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _MONEY_RX.finditer(text):
        cur = m.group("cur1") or m.group("cur2") or ""
        if not cur:
            continue
        if _RATE_RX.match(text[m.end() :][:26]):
            continue  # unit rate - shown nowhere as a package figure
        amount = m.group("amount").replace(",", "")
        if amount in seen:
            continue
        seen.add(amount)
        start = max(0, m.start() - 60)
        context = " ".join(text[start : m.end() + 60].split())
        prices.append({"amount": amount, "currency": _CURRENCY_MAP.get(cur, cur), "context": context})
        if len(prices) >= 10:
            break
    return prices


def analyze_text(subject: str, body: str, attachment_names: list[str] | None = None) -> dict[str, Any]:
    """Run every heuristic over a message and return an analysis verdict.

    Returns the same verdict shape the AI pass produces so the service
    layer stores both through one code path:
    ``{category, confidence, summary, extracted, reply_needed, suggestions}``.
    """
    text = f"{subject}\n{body}"

    kind = reply_kind(text, attachment_names)
    package_price = scan_package_price(text)
    lead_time = scan_lead_time(text)

    category = "general"
    confidence = 0.2  # a floor: "we looked, nothing matched"
    for cat, rx in _CATEGORY_PATTERNS:
        if rx.search(text):
            category = cat
            # Keyword hits are decent but never review-free: cap under the
            # suggest band ceiling so a heuristic verdict always renders as
            # "needs a person" (RFC 34 grading: <0.65 skip, 0.65-0.85
            # suggest, >=0.85 auto-apply - which this module doesn't do).
            confidence = 0.7
            break
    # A reconciled/priced reply is a quote even without the keyword - the
    # price test is the stronger signal (same precedence as _reply_kind).
    # Only the commercially-loaded categories survive a price: a variation
    # notice or claim legitimately carries money; "3 weeks delivery" beside
    # a package price does not make the message a delivery docket.
    if kind == "quote" and category in ("general", "delivery", "approval"):
        category = "quote"
        confidence = max(confidence, 0.7)

    prices = _extract_prices(text)
    quote_no = scan_quote_number(text, package_price["amount"] if package_price else "")
    references = sorted({m.group(1).strip() for m in _REFERENCE_RX.finditer(text)})

    respond_by: str | None = None
    m = _RESPOND_BY_RX.search(text)
    if m:
        respond_by = _to_iso_date(m.group("date"))

    reply_needed = bool(_REPLY_NEEDED_RX.search(text)) or respond_by is not None

    extracted = {
        "prices": prices,
        "package_price": package_price,
        "lead_time": lead_time,
        "reply_kind": kind,
        "quote_number": quote_no,
        "reference_numbers": references,
        "dates": {"response_requested_by": respond_by, "event_date": None},
        "commitments": [],
    }

    suggestions: dict[str, Any] = {
        "set_status": "awaiting_response" if reply_needed else None,
        "response_required_by": respond_by,
        "link_rfi_id": None,
        "correspondence_type": None,
    }

    # Quote with a price found → nudge category confidence up: two
    # independent signals agreeing is materially better than one.
    if category == "quote" and (package_price or prices):
        confidence = 0.8

    summary_bits: list[str] = []
    if package_price:
        basis = f" {package_price['basis']}" if package_price["basis"] else ""
        summary_bits.append(f"package price ${package_price['amount']}{basis}")
    elif prices:
        summary_bits.append(f"{len(prices)} price(s), first {prices[0]['currency']} {prices[0]['amount']}")
    if lead_time:
        summary_bits.append(f"lead time {lead_time}")
    if quote_no:
        summary_bits.append(f"quote no. {quote_no}")
    if references:
        summary_bits.append("refs " + ", ".join(references[:3]))
    if respond_by:
        summary_bits.append(f"response requested by {respond_by}")
    if kind == "query":
        summary_bits.append("they are asking a question (not a quote)")
    summary = "; ".join(summary_bits)

    return {
        "category": category,
        "confidence": confidence,
        "summary": summary,
        "extracted": extracted,
        "reply_needed": reply_needed,
        "suggestions": suggestions,
    }
