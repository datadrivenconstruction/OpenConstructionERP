# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure, DB-free logic for the invoice-approval DMS.

Everything here is a pure function over plain values so it can be unit-tested
without a database, an HTTP client, an OCR engine or an LLM:

* :func:`extract_fields_from_text` - heuristic header extraction from the text
  layer / OCR output (the graceful-degradation path when no LLM is available).
* :func:`propose_booking` - suggest the debit/credit accounts and cost code for
  a payable invoice from a chart of accounts (AI-augmented, human-confirmed).
* :func:`build_journal_lines` - turn a confirmed booking into balanced
  double-entry journal lines (net + tax = gross).
* :func:`validate_capture` - first-class validation: amount tie-out, booking
  completeness, readiness to post, plus duplicate detection over a supplied
  candidate list.
* :func:`content_sha256` / :func:`compute_archive_hash` - the tamper-evident
  seal maths.

Money is Decimal end to end here; the service/schema layer converts to and from
the Decimal-as-string wire format.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Amounts must tie out within this absolute tolerance (rounding noise across
# OCR / multi-line VAT). Two cents covers per-line half-cent rounding.
AMOUNT_TOLERANCE = Decimal("0.02")

# Default GoBD-style retention: 10 years from posting.
DEFAULT_RETENTION_YEARS = 10


# ── Findings (validation result records) ─────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    """One validation result. ``severity`` is error | warning | info."""

    severity: str
    code: str
    message: str
    field: str | None = None

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


@dataclass
class BookingProposal:
    """A suggested booking for a payable invoice (human-confirmed before post)."""

    expense_account: str | None = None
    tax_account: str | None = None
    payable_account: str | None = None
    cost_code: str | None = None
    confidence: float = 0.0
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "expense_account": self.expense_account,
            "tax_account": self.tax_account,
            "payable_account": self.payable_account,
            "cost_code": self.cost_code,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale,
        }


# ── Decimal helpers ──────────────────────────────────────────────────────────


def to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """Coerce an arbitrary value to a finite Decimal, never raising."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else default
    if value is None:
        return default
    try:
        d = Decimal(str(value).strip().replace(",", "") or "0")
    except (InvalidOperation, ValueError, TypeError):
        return default
    return d if d.is_finite() else default


def money_str(value: object) -> str:
    """Render a Decimal-ish value as a canonical plain money string."""
    return format(to_decimal(value), "f")


# ── Heuristic extraction (no-LLM fallback) ───────────────────────────────────

# Amount tokens like 1.234,56 / 1,234.56 / 1234.56 / 1234,56.
_AMOUNT_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d+[.,]\d{2})(?![\w])")
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})"
    r"|(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})"
)
_INVOICE_NO_RE = re.compile(
    r"(?:invoice|rechnung|facture|factura|fattura|inv|re)[\s.#:no-]{0,6}"
    r"([A-Z0-9][A-Z0-9\-/]{2,29})",
    re.IGNORECASE,
)
_TAX_ID_RE = re.compile(
    r"(?:vat|ust|tax|nif|cif|tva|p\.?iva|steuernummer)[\s.:#-]{0,4}"
    r"([A-Z]{0,2}\d[\d A-Z\-]{5,18})",
    re.IGNORECASE,
)
_NET_LABEL_RE = re.compile(r"(net|netto|subtotal|zwischensumme|base)", re.IGNORECASE)
_TAX_LABEL_RE = re.compile(r"(vat|tax|mwst|ust|iva|tva|steuer)", re.IGNORECASE)
_GROSS_LABEL_RE = re.compile(r"(gross|brutto|total|gesamt|amount due|balance due|zu zahlen)", re.IGNORECASE)


def _parse_amount_token(token: str) -> Decimal:
    """Parse a localized amount token (handles 1.234,56 and 1,234.56)."""
    t = token.strip()
    if "," in t and "." in t:
        # The rightmost separator is the decimal separator.
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        # Comma as decimal (1234,56) vs thousands (1,234) - decide by position.
        if re.search(r",\d{2}$", t):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    return to_decimal(t)


def _amount_on_labelled_line(text: str, label_re: re.Pattern[str]) -> Decimal | None:
    """Return the last amount on the last line matching ``label_re``."""
    best: Decimal | None = None
    for line in text.splitlines():
        if not label_re.search(line):
            continue
        tokens = _AMOUNT_RE.findall(line)
        if tokens:
            best = _parse_amount_token(tokens[-1])
    return best


def extract_fields_from_text(text: str) -> tuple[dict, dict[str, float]]:
    """Best-effort header extraction from an invoice's text layer / OCR.

    Returns ``(fields, confidence)`` where ``fields`` may contain
    ``supplier_name, supplier_tax_id, invoice_number, invoice_date, amount_net,
    amount_tax, amount_gross`` (money as strings) and ``confidence`` maps each
    populated field to a 0.0-1.0 score. Missing fields are simply absent so the
    caller (and the human reviewer) can see what still needs entering.

    This is deliberately conservative: it never invents a value, and the low
    confidences signal that a human must confirm. It is the fallback used when
    no LLM is configured, so the capture flow still works with zero AI.
    """
    fields: dict = {}
    conf: dict[str, float] = {}
    if not text or not text.strip():
        return fields, conf

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Supplier name: first non-numeric, reasonably short line near the top.
    for line in lines[:8]:
        letters = sum(c.isalpha() for c in line)
        if letters >= 3 and letters >= len(line) * 0.5 and len(line) <= 60:
            fields["supplier_name"] = line
            conf["supplier_name"] = 0.4
            break

    if m := _INVOICE_NO_RE.search(text):
        fields["invoice_number"] = m.group(1).strip()
        conf["invoice_number"] = 0.6

    if m := _TAX_ID_RE.search(text):
        fields["supplier_tax_id"] = re.sub(r"\s+", "", m.group(1)).strip()
        conf["supplier_tax_id"] = 0.55

    if m := _DATE_RE.search(text):
        iso = _normalize_date(m.group(0))
        if iso:
            fields["invoice_date"] = iso
            conf["invoice_date"] = 0.5

    net = _amount_on_labelled_line(text, _NET_LABEL_RE)
    tax = _amount_on_labelled_line(text, _TAX_LABEL_RE)
    gross = _amount_on_labelled_line(text, _GROSS_LABEL_RE)

    # If only two of the three are found, derive the third.
    if gross is None and net is not None and tax is not None:
        gross = net + tax
    if net is None and gross is not None and tax is not None:
        net = gross - tax
    if tax is None and gross is not None and net is not None:
        tax = gross - net

    if net is not None and net > 0:
        fields["amount_net"] = money_str(net)
        conf["amount_net"] = 0.5
    if tax is not None and tax >= 0:
        fields["amount_tax"] = money_str(tax)
        conf["amount_tax"] = 0.5
    if gross is not None and gross > 0:
        fields["amount_gross"] = money_str(gross)
        conf["amount_gross"] = 0.55

    return fields, conf


def _normalize_date(raw: str) -> str | None:
    """Normalize a matched date token to ISO ``YYYY-MM-DD`` (best effort)."""
    raw = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    parts = re.split(r"[./-]", raw)
    if len(parts) != 3:
        return None
    a, b, c = (p for p in parts)
    try:
        if len(a) == 4:  # YYYY/MM/DD
            y, mo, d = int(a), int(b), int(c)
        else:  # DD/MM/YYYY (European default)
            d, mo, y = int(a), int(b), int(c)
            if y < 100:
                y += 2000
    except ValueError:
        return None
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2200):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


# ── Booking proposal ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChartAccount:
    """The minimal account shape :func:`propose_booking` needs."""

    code: str
    name: str
    account_type: str  # asset | liability | equity | revenue | expense
    is_active: bool = True


def _first_match(
    accounts: list[ChartAccount],
    *,
    account_type: str | None = None,
    name_contains: tuple[str, ...] = (),
    code_prefix: tuple[str, ...] = (),
) -> ChartAccount | None:
    """Pick the first active account matching the given hints (in order)."""
    for prefix in code_prefix:
        for acc in accounts:
            if acc.is_active and acc.code.startswith(prefix):
                return acc
    for needle in name_contains:
        for acc in accounts:
            if acc.is_active and needle in acc.name.lower():
                if account_type and acc.account_type != account_type:
                    continue
                return acc
    if account_type:
        for acc in accounts:
            if acc.is_active and acc.account_type == account_type:
                return acc
    return None


def propose_booking(
    *,
    accounts: list[ChartAccount],
    supplier_name: str = "",
    description_text: str = "",
    has_tax: bool = False,
    cost_code: str | None = None,
) -> BookingProposal:
    """Suggest a payable booking (expense / tax / payable accounts) from a chart.

    The debit expense account is picked from context (subcontractor vs material
    vs generic construction cost); the payable account is the liability
    "Accounts Payable"; the tax account is only proposed when the invoice
    carries tax. Every choice comes with a rationale and an overall confidence
    so the reviewer sees why - nothing posts without confirmation.
    """
    proposal = BookingProposal(cost_code=cost_code)
    if not accounts:
        proposal.rationale.append("No chart of accounts is seeded yet - seed the default chart to enable booking.")
        return proposal

    haystack = f"{supplier_name} {description_text}".lower()
    expense: ChartAccount | None = None
    if any(w in haystack for w in ("subcontract", "sub-contract", "nachunternehmer", "sub ")):
        expense = _first_match(accounts, name_contains=("subcontractor",), code_prefix=("5030",))
        if expense:
            proposal.rationale.append("Matched 'subcontractor' in the supplier / description.")
    elif any(w in haystack for w in ("material", "supply", "supplies", "concrete", "steel", "timber")):
        expense = _first_match(accounts, name_contains=("direct materials", "materials"), code_prefix=("5020",))
        if expense:
            proposal.rationale.append("Matched a materials keyword in the supplier / description.")
    if expense is None:
        expense = _first_match(
            accounts,
            account_type="expense",
            name_contains=("cost of construction", "cogs", "cost of"),
            code_prefix=("5000",),
        )
        if expense:
            proposal.rationale.append(f"Defaulted the cost to expense account {expense.code} {expense.name}.")

    payable = _first_match(
        accounts,
        account_type="liability",
        name_contains=("accounts payable", "payable", "creditor"),
        code_prefix=("2000",),
    )
    if payable:
        proposal.rationale.append(f"Credit to {payable.code} {payable.name}.")

    tax_acct: ChartAccount | None = None
    if has_tax:
        tax_acct = _first_match(
            accounts,
            name_contains=("input vat", "vat recoverable", "input tax", "taxes payable", "vat", "tax"),
            code_prefix=("2300",),
        )
        if tax_acct:
            proposal.rationale.append(f"Recoverable tax to {tax_acct.code} {tax_acct.name}.")

    proposal.expense_account = expense.code if expense else None
    proposal.payable_account = payable.code if payable else None
    proposal.tax_account = tax_acct.code if tax_acct else None

    # Confidence: full booking with a keyword-matched expense is the strongest.
    score = 0.0
    if expense:
        score += 0.5 if proposal.rationale and "Defaulted" not in proposal.rationale[0] else 0.35
    if payable:
        score += 0.3
    if not has_tax or tax_acct:
        score += 0.2
    proposal.confidence = min(score, 0.95)
    return proposal


def build_journal_lines(
    *,
    net: Decimal,
    tax: Decimal,
    expense_account: str,
    payable_account: str,
    tax_account: str | None,
    description: str,
) -> list[dict]:
    """Build balanced double-entry lines for a payable invoice.

    Dr expense + Dr tax (when a tax account is given) = Cr payable (gross).
    When the invoice carries tax but no tax account is chosen, the tax folds
    into the expense debit (expense = net + tax) so the entry still balances -
    this mirrors the "the tax will fold into the expense" validation warning.
    Returns line dicts shaped for ``JournalLineInput`` (account_code / debit /
    credit / description), money as strings. The caller feeds these to
    ``FinanceService.post_journal_entry`` which re-checks the balance.
    """
    has_tax_leg = tax > 0 and bool(tax_account)
    expense_debit = net if has_tax_leg else net + tax
    lines: list[dict] = [
        {
            "account_code": expense_account,
            "debit": money_str(expense_debit),
            "credit": "0",
            "description": description,
        }
    ]
    if has_tax_leg:
        lines.append(
            {
                "account_code": tax_account,
                "debit": money_str(tax),
                "credit": "0",
                "description": f"{description} (recoverable tax)",
            }
        )
    gross = net + tax
    lines.append(
        {
            "account_code": payable_account,
            "debit": "0",
            "credit": money_str(gross),
            "description": description,
        }
    )
    return lines


# ── Validation (first-class) ─────────────────────────────────────────────────


def validate_amounts(net: Decimal, tax: Decimal, gross: Decimal) -> list[Finding]:
    """Gross must equal net + tax within tolerance; amounts non-negative."""
    findings: list[Finding] = []
    for name, val in (("amount_net", net), ("amount_tax", tax), ("amount_gross", gross)):
        if val < 0:
            findings.append(Finding("error", "amount_negative", f"{name} cannot be negative.", name))
    if gross <= 0:
        findings.append(
            Finding("error", "gross_required", "The gross (total) amount must be greater than zero.", "amount_gross")
        )
    diff = abs((net + tax) - gross)
    if diff > AMOUNT_TOLERANCE:
        findings.append(
            Finding(
                "error",
                "amount_mismatch",
                f"Net + tax ({money_str(net + tax)}) does not equal gross ({money_str(gross)}).",
                "amount_gross",
            )
        )
    return findings


def negative_line_findings(line_items: list[dict]) -> list[Finding]:
    """A negative line (discount, credit) is legitimate but must be seen: flag it as a warning, never drop it."""
    out: list[Finding] = []
    for idx, li in enumerate(line_items, start=1):
        if to_decimal(li.get("amount")) < 0:
            out.append(
                Finding(
                    "warning",
                    "negative_line",
                    f"Line {idx} is a negative amount ({money_str(li.get('amount'))}): a discount or credit.",
                    f"line_items[{idx}]",
                )
            )
    return out


def validate_booking_complete(
    *,
    expense_account: str | None,
    payable_account: str | None,
    tax_account: str | None,
    tax: Decimal,
) -> list[Finding]:
    """A bookable invoice needs an expense and a payable account (+ tax acct)."""
    findings: list[Finding] = []
    if not expense_account:
        findings.append(Finding("error", "no_expense_account", "Choose an expense / cost account.", "expense_account"))
    if not payable_account:
        findings.append(
            Finding("error", "no_payable_account", "Choose the accounts-payable account.", "payable_account")
        )
    if tax > 0 and not tax_account:
        findings.append(
            Finding(
                "warning",
                "no_tax_account",
                "This invoice has tax but no tax account is set; the tax will fold into the expense.",
                "tax_account",
            )
        )
    return findings


def find_duplicate(
    *,
    supplier_name: str,
    invoice_number: str,
    candidates: list[dict],
) -> dict | None:
    """Return the first candidate that is the same supplier + invoice number.

    ``candidates`` are ``{"id", "supplier_name", "invoice_number"}`` dicts of
    other captures in the project. Matching is case/space-insensitive. An empty
    invoice number never matches (a draft with no number is not a duplicate).
    """
    number = _norm(invoice_number)
    if not number:
        return None
    supplier = _norm(supplier_name)
    for cand in candidates:
        if _norm(cand.get("invoice_number", "")) != number:
            continue
        # Same number is a strong signal; require supplier to agree only when
        # both sides carry one (tolerates a blank supplier on either draft).
        cand_supplier = _norm(cand.get("supplier_name", ""))
        if supplier and cand_supplier and supplier != cand_supplier:
            continue
        return cand
    return None


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def validate_capture(
    *,
    status: str,
    net: Decimal,
    tax: Decimal,
    gross: Decimal,
    expense_account: str | None,
    payable_account: str | None,
    tax_account: str | None,
    invoice_number: str,
    supplier_name: str,
    has_approver: bool,
    duplicate: dict | None = None,
    require_booking: bool = False,
    require_approval: bool = False,
) -> list[Finding]:
    """Full validation report for a captured invoice at its current stage.

    ``require_booking`` / ``require_approval`` escalate the relevant checks to
    errors when the caller is gating a transition (code / post). Duplicate
    detection is passed in (the DB lookup happens in the service).
    """
    findings: list[Finding] = []
    findings.extend(validate_amounts(net, tax, gross))

    if not invoice_number.strip():
        sev = "error" if require_booking or require_approval else "warning"
        findings.append(Finding(sev, "no_invoice_number", "The invoice number is missing.", "invoice_number"))
    if not supplier_name.strip():
        findings.append(Finding("warning", "no_supplier", "The supplier name is missing.", "supplier_name"))

    if duplicate is not None:
        findings.append(
            Finding(
                "error",
                "duplicate_invoice",
                f"An invoice with number '{invoice_number}' from this supplier already exists in the project.",
                "invoice_number",
            )
        )

    if require_booking or require_approval:
        findings.extend(
            validate_booking_complete(
                expense_account=expense_account,
                payable_account=payable_account,
                tax_account=tax_account,
                tax=tax,
            )
        )

    if require_approval and not has_approver:
        findings.append(
            Finding("error", "no_approver", "The invoice must be approved before it can be posted.", "approver_id")
        )

    return findings


# ── Order link (PO + goods-receipt match) ────────────────────────────────────

#: Order statuses an invoice may be billed against (draft and cancelled orders commit nothing).
BILLABLE_PO_STATUSES = frozenset({"issued", "partially_received", "completed"})

_PO_REF_RE = re.compile(
    r"(?:purchase\s+order|order\s+(?:no|number|ref)|bestell(?:ung)?(?:s)?(?:\s*-?\s*(?:nr|nummer))?|PO)"
    r"\s*(?:no\.?|nr\.?|number|#|:)?\s*[:#]?\s*([A-Z0-9][A-Z0-9/_-]{2,40})",
    re.IGNORECASE,
)


def extract_po_reference(text: str) -> str:
    """Best-effort order reference from OCR text; empty when none is labelled as one."""
    for match in _PO_REF_RE.finditer(text or ""):
        token = match.group(1).strip("-/_")
        if any(ch.isdigit() for ch in token):
            return token[:100]
    return ""


def validate_po_link(
    *,
    po: dict | None,
    po_reference: str,
    supplier_contact_id: str | None,
    currency_code: str,
) -> list[Finding]:
    """Check the order a capture is linked to (``po`` is its summary dict, ``None`` = no link).

    ``po`` carries ``number``, ``status``, ``vendor_contact_id``, ``currency_code``; ``{}`` means the linked
    order no longer exists.
    """
    if po is None:
        if (po_reference or "").strip():
            return [
                Finding(
                    "warning",
                    "po_reference_unresolved",
                    f"The invoice names order '{po_reference}', but no such order exists on this project. "
                    "Link the order by hand or correct the reference.",
                    "purchase_order_id",
                )
            ]
        return []
    if not po:
        return [Finding("error", "po_missing", "The linked purchase order no longer exists.", "purchase_order_id")]
    findings: list[Finding] = []
    number = po.get("number") or "?"
    if po.get("status") not in BILLABLE_PO_STATUSES:
        findings.append(
            Finding(
                "error",
                "po_not_open",
                f"Order {number} is '{po.get('status')}'; only an issued order can be invoiced.",
                "purchase_order_id",
            )
        )
    vendor = (po.get("vendor_contact_id") or "").strip()
    if vendor and supplier_contact_id and vendor != supplier_contact_id.strip():
        findings.append(
            Finding(
                "error",
                "po_supplier_mismatch",
                f"Order {number} was placed with a different supplier than the one on this invoice.",
                "supplier_contact_id",
            )
        )
    po_ccy = (po.get("currency_code") or "").strip().upper()
    inv_ccy = (currency_code or "").strip().upper()
    if po_ccy and inv_ccy and po_ccy != inv_ccy:
        findings.append(
            Finding(
                "error",
                "po_currency_mismatch",
                f"Order {number} is in {po_ccy}, the invoice is in {inv_ccy}.",
                "currency_code",
            )
        )
    return findings


def match_report_findings(results: list[dict]) -> list[Finding]:
    """Failed ``invoice_po_match`` rule results (procurement's matcher) as inbox findings."""
    return [
        Finding(
            "error" if str(r.get("severity")) == "error" else "warning",
            f"po_match:{r.get('rule_id')}",
            str(r.get("message") or ""),
            "purchase_order_id",
        )
        for r in results
        if not r.get("passed", True)
    ]


def match_unacknowledged(findings: list[Finding], acknowledged_codes: set[str]) -> list[Finding]:
    """An error for every order-match warning nobody has acknowledged yet."""
    open_codes = [f.code for f in findings if f.code.startswith("po_match:") and f.code not in acknowledged_codes]
    if not open_codes:
        return []
    return [
        Finding(
            "error",
            "po_match_unacknowledged",
            "The invoice does not match its order or goods receipts. An approver must acknowledge the "
            "mismatch before the invoice can be approved.",
            "purchase_order_id",
        )
    ]


def has_errors(findings: list[Finding]) -> bool:
    return any(f.is_error for f in findings)


def findings_to_dicts(findings: list[Finding]) -> list[dict]:
    return [{"severity": f.severity, "code": f.code, "message": f.message, "field": f.field} for f in findings]


# ── Tamper-evident archive seal ──────────────────────────────────────────────


def content_sha256(data: bytes) -> str:
    """SHA-256 hex digest of raw document bytes (the archive anchor)."""
    return hashlib.sha256(data).hexdigest()


def compute_archive_hash(
    *,
    content_hash: str | None,
    supplier_name: str,
    invoice_number: str,
    invoice_date: str,
    currency_code: str,
    net: Decimal,
    tax: Decimal,
    gross: Decimal,
    expense_account: str | None,
    tax_account: str | None,
    payable_account: str | None,
    cost_code: str | None,
    transaction_ref: str | None,
) -> str:
    """Deterministic seal over the original document hash + confirmed booking.

    Any later change to the amounts, the booking accounts or the linked GL
    reference produces a different hash, so :func:`verify` can prove the archive
    has not been altered since it was posted.
    """
    payload = {
        "content_sha256": content_hash or "",
        "supplier_name": _norm(supplier_name),
        "invoice_number": _norm(invoice_number),
        "invoice_date": invoice_date or "",
        "currency_code": (currency_code or "").upper(),
        "net": money_str(net),
        "tax": money_str(tax),
        "gross": money_str(gross),
        "expense_account": expense_account or "",
        "tax_account": tax_account or "",
        "payable_account": payable_account or "",
        "cost_code": cost_code or "",
        "transaction_ref": transaction_ref or "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
