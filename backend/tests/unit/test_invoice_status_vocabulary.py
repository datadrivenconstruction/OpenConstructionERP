# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An invoice status must exist in the lifecycle and be sayable on screen.

Two failures met on the same row of the same table, and neither is visible from
one side alone.

The seed wrote ``submitted`` on receivable invoices. The finance FSM has no such
state, so the invoice could not be moved anywhere afterwards, and the schema does
not police the field (``status: str = Field(default="draft", max_length=50)``),
so nothing refused it on the way in. The wide seed-vocabulary scan cannot see
this one either: it reads vocabularies out of Pydantic patterns, and this field
has none, which is exactly why the value survived to the screen.

The other direction is ``sent``, a state the FSM has always had and the UI never
learned. It had no label key, so the badge printed the database word; no colour,
so an invoice the client is holding looked like an unsent draft; and no filter
entry, so it could not be found except by clearing the filter.

Both are the same defect seen from opposite ends, so both are asserted here as
one contract: the lifecycle is the vocabulary, the seed may only speak it, and
every word in it has a label, a colour and a filter entry. Read out of the
sources rather than restated, so a state added to the FSM tomorrow fails this
until the screen can say it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.core import demo_projects
from app.modules.finance.service import _INVOICE_STATUS_TRANSITIONS

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FINANCE_PAGE = _REPO_ROOT / "frontend" / "src" / "features" / "finance" / "FinancePage.tsx"
_LOCALES = _REPO_ROOT / "frontend" / "src" / "app" / "locales"

# Rendered by their own controls rather than the status badge: 'disputed' is a
# payment-side flag the page colours but the invoice FSM never holds.
_NON_LIFECYCLE_COLOURS = frozenset({"disputed"})


def _seeded_invoice_statuses() -> set[str]:
    """Statuses the demo seed writes on invoice records.

    Attributed by the keys of the dict literal each value sits in, because
    ``status`` belongs to nearly every entity in this file and a bare text
    search would collect change orders and tenders alongside invoices.
    """
    tree = ast.parse(demo_projects.__file__ and Path(demo_projects.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        if "invoice_direction" not in keys and "invoice_number" not in keys:
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and key.value == "status" and isinstance(value, ast.Constant):
                found.add(value.value)
    return found


def _frontend_status_colours() -> set[str]:
    text = _FINANCE_PAGE.read_text(encoding="utf-8")
    block = re.search(r"INVOICE_STATUS_COLORS[^=]*=\s*\{(.*?)\n\};", text, re.DOTALL)
    assert block, "INVOICE_STATUS_COLORS not found in FinancePage.tsx"
    return set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE))


def _frontend_status_order() -> set[str]:
    text = _FINANCE_PAGE.read_text(encoding="utf-8")
    block = re.search(r"INVOICE_STATUS_ORDER\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert block, "INVOICE_STATUS_ORDER not found in FinancePage.tsx"
    return set(re.findall(r"'([\w]+)'", block.group(1)))


def _filter_options() -> set[str]:
    text = _FINANCE_PAGE.read_text(encoding="utf-8")
    return set(re.findall(r'<option value="(\w+)">\s*\{t\(\'finance\.status_', text)) | set(
        re.findall(r'<option value="(\w+)">\s*\n\s*\{t\(\'finance\.status_', text)
    )


def test_the_seed_only_writes_statuses_the_lifecycle_knows():
    """A seeded state outside the FSM is a dead end no user action can leave."""
    seeded = _seeded_invoice_statuses()
    assert seeded, "no seeded invoice statuses found; the attribution broke"
    unknown = sorted(seeded - set(_INVOICE_STATUS_TRANSITIONS))
    assert not unknown, f"demo invoices are seeded with statuses the finance FSM refuses: {unknown}"


def test_every_lifecycle_status_can_be_named_on_screen():
    """A status with no label key prints the raw database word into the table."""
    for locale in ("en", "de"):
        text = (_LOCALES / f"{locale}.ts").read_text(encoding="utf-8")
        keys = set(re.findall(r'"finance\.status_(\w+)"', text))
        missing = sorted(s for s in _INVOICE_STATUS_TRANSITIONS if s not in keys)
        assert not missing, f"{locale}.ts has no finance.status_ entry for: {missing}"


def test_every_lifecycle_status_carries_a_colour_and_a_filter_entry():
    colours = _frontend_status_colours()
    missing_colour = sorted(s for s in _INVOICE_STATUS_TRANSITIONS if s not in colours)
    assert not missing_colour, f"INVOICE_STATUS_COLORS has no entry for: {missing_colour}"
    assert not (colours - set(_INVOICE_STATUS_TRANSITIONS) - _NON_LIFECYCLE_COLOURS), (
        "INVOICE_STATUS_COLORS colours a status the FSM does not have"
    )

    missing_option = sorted(s for s in _INVOICE_STATUS_TRANSITIONS if s not in _filter_options())
    assert not missing_option, f"the status filter cannot select: {missing_option}"

    missing_order = sorted(s for s in _INVOICE_STATUS_TRANSITIONS if s not in _frontend_status_order())
    assert not missing_order, f"INVOICE_STATUS_ORDER omits: {missing_order}"
