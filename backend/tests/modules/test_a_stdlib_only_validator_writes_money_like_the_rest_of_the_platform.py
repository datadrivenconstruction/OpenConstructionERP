# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The two dependency-free validator modules write money the way everything else does.

``procurement/validators.py`` and ``subcontractors/validators.py`` declare
themselves standard-library-only in their docstrings and mean it, so until
``app.core.currency_registry`` existed they could not ask how many decimals a
currency keeps: ``minor_units`` sat behind ``app.core.money``, which imports
pydantic and SQLAlchemy at module level. Both wrote every amount with a
hardcoded two decimals and no currency code at all.

Two decimals is wrong in two directions, and the tests below pin both. It is too
many for a currency with no subunit, which is why JPY and IDR are named here
explicitly: the platform has a standing decision that both keep zero, recorded
in ``app.core.currency_registry`` beside the table and pinned across all three
resolvers in ``tests/unit/test_every_money_resolver_asks_the_same_registry.py``.
It is too few for the Gulf dinars. A local ``,.2f`` in these modules would have
disagreed with ``_fmt_money`` on every one of those codes, which is the specific
way a second spelling of one idea goes wrong: never on the currency the author
tested with.

The contract itself is tested rather than trusted. A docstring saying "no
dependencies" is one careless import away from being untrue and nothing goes red
when it stops being so, so :class:`TestTheCurrencyRegistryIsStandardLibraryOnly`
runs a fresh interpreter and asks it what got imported.

What stays bare is pinned as hard as what changed: the retention templates glue
``%`` straight onto the slot, so an amount rendered there would read
``50.00 EUR%``. Those two messages are percentages, not money, and the tests
below fail if a later sweep converts them.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.validation.engine import ValidationContext
from app.core.validation.rules import (
    ProcurementPOLineAmount,
    ProcurementPORetentionWithinBounds,
    ProcurementPOSubtotalMatchesLines,
    ProcurementPOTotalMatchesSubtotal,
    SubcontractAgreementValuePositive,
    SubcontractPackagesWithinValue,
    SubcontractRetentionWithinBounds,
)

#: ``backend/``, the directory the subprocess probe runs in so that ``app``
#: resolves to this working tree rather than to anything installed.
BACKEND = Path(__file__).resolve().parents[2]


async def _only(rule: Any, data: dict[str, Any]) -> str:
    """The single failing message this rule produces for this payload."""
    context = ValidationContext(data=data, metadata={"locale": "en"})
    messages = [result.message for result in await rule.validate(context) if not result.passed]
    assert len(messages) == 1, f"expected exactly one failing result, got {messages}"
    return messages[0]


# ── The contract the two modules declare is executed, not read ──────────────


#: Run in a fresh interpreter. Snapshots ``sys.modules``, imports the registry,
#: and reports every name that appeared which is neither standard library nor
#: one of the three ``app`` packages the import path necessarily creates. An
#: allowlist rather than a denylist of known-heavy names: the failure this
#: guards against is an import nobody thought to enumerate.
_PROBE = """
import sys

before = set(sys.modules)
import app.core.currency_registry as registry
added = sorted(set(sys.modules) - before)

allowed = {"app", "app.core", "app.core.currency_registry"}
foreign = [
    name
    for name in added
    if name.split(".")[0] not in sys.stdlib_module_names and name not in allowed
]
print("FILE:" + registry.__file__)
print("FOREIGN:" + "|".join(foreign))
"""


def _imported_modules(path: Path) -> set[str]:
    """Every module this file imports, including imports deferred inside functions.

    Read off the syntax tree rather than grepped: a docstring that discusses
    ``app.core.validation.rules`` in prose is not an import of it, and the first
    version of this check could not tell the difference.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


class TestTheCurrencyRegistryIsStandardLibraryOnly:
    def test_a_fresh_interpreter_imports_nothing_but_the_standard_library(self) -> None:
        """``-S`` and a cleared ``PYTHONPATH``: no site hooks seed the answer.

        The two validator modules are only dependency-free for as long as what
        they import is, so this is the assertion that makes their docstrings
        true rather than aspirational.
        """
        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-S", "-c", _PROBE],
            cwd=BACKEND,
            env={"PATH": "", "SYSTEMROOT": ""},
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, f"probe failed:\n{completed.stderr}"
        printed = dict(line.split(":", 1) for line in completed.stdout.splitlines() if ":" in line)

        # Testing a wheel instead of the tree would make the rest vacuous.
        assert Path(printed["FILE"]).is_relative_to(BACKEND), printed["FILE"]

        foreign = [name for name in printed["FOREIGN"].split("|") if name]
        assert foreign == [], f"the registry dragged in non-stdlib modules: {foreign}"

    def test_the_two_validator_modules_import_only_the_registry_from_core(self) -> None:
        """Neither may reach ``app.core.money``: that is the module with the ORM in it."""
        for module in ("procurement", "subcontractors"):
            imported = _imported_modules(BACKEND / "app" / "modules" / module / "validators.py")
            foreign = {
                name
                for name in imported
                if name.split(".")[0] not in sys.stdlib_module_names and name != "app.core.currency_registry"
            }
            assert foreign == set(), f"{module} imports outside the standard library: {sorted(foreign)}"


# ── procurement: the purchase order states its own currency ─────────────────


def _po(**overrides: Any) -> dict[str, Any]:
    """A purchase order whose arithmetic disagrees with itself in every rule."""
    po = {
        "id": "po-1",
        "po_number": "PO-2026-0007",
        "currency_code": "EUR",
        "vendor_contact_id": "v1",
        "retention_percent": "5",
        "items": [
            {
                "description": "Steel frame",
                "quantity": "1000",
                "unit_rate": "1234.50",
                "amount": "1000.00",
            }
        ],
        "amount_subtotal": "1234567.89",
        "tax_amount": "1000.00",
        "amount_total": "1000.00",
    }
    po.update(overrides)
    return po


class TestProcurementQuotesMoneyInThePurchaseOrdersCurrency:
    async def test_the_line_amount_sentence_groups_and_codes_both_figures(self) -> None:
        assert await _only(ProcurementPOLineAmount(), _po()) == (
            "Line 1 (Steel frame) totals 1,000.00 EUR but its quantity times unit rate is 1,234,500.00 EUR"
        )

    async def test_the_subtotal_sentence_groups_and_codes_both_figures(self) -> None:
        assert await _only(ProcurementPOSubtotalMatchesLines(), _po()) == (
            "The subtotal is 1,234,567.89 EUR but the lines add up to 1,000.00 EUR"
        )

    async def test_the_total_sentence_groups_and_codes_both_figures(self) -> None:
        assert await _only(ProcurementPOTotalMatchesSubtotal(), _po()) == (
            "The total is 1,000.00 EUR but subtotal plus tax is 1,235,567.89 EUR"
        )

    async def test_a_zero_decimal_currency_keeps_no_cents(self) -> None:
        """JPY: the decimals come from the currency, never from the caller."""
        message = await _only(ProcurementPOLineAmount(), _po(currency_code="JPY"))
        assert message == ("Line 1 (Steel frame) totals 1,000 JPY but its quantity times unit rate is 1,234,500 JPY")
        assert "1,234,500.00" not in message

    async def test_the_rupiah_keeps_no_cents_either(self) -> None:
        """IDR: a standing decision, agreed by all three resolvers. Not a typo here."""
        message = await _only(ProcurementPOLineAmount(), _po(currency_code="IDR"))
        assert message == ("Line 1 (Steel frame) totals 1,000 IDR but its quantity times unit rate is 1,234,500 IDR")
        assert "1,234,500.00" not in message

    async def test_a_purchase_order_without_a_currency_is_grouped_but_uncoded(self) -> None:
        """A blank code is written as no code: the PO has its own rule for that."""
        message = await _only(ProcurementPOLineAmount(), _po(currency_code=""))
        assert message == ("Line 1 (Steel frame) totals 1,000.00 but its quantity times unit rate is 1,234,500.00")

    async def test_retention_is_a_percentage_and_stays_bare(self) -> None:
        """``Retention of {percent}%``: a currency code here would read ``1,234.50 EUR%``."""
        message = await _only(ProcurementPORetentionWithinBounds(), _po(retention_percent="1234.50"))
        assert message == "Retention of 1234.50% is outside the plausible range of 0 to 50.00%"
        assert "EUR" not in message
        assert "1,234" not in message


# ── subcontractors: the agreement states its own currency ───────────────────


def _agreement(**overrides: Any) -> dict[str, Any]:
    """A subcontract agreement under-funded against its own work packages."""
    agreement = {
        "id": "sc-1",
        "title": "Groundworks package",
        "currency": "GBP",
        "retention_percent": "5",
        "total_value": "1000.00",
        "work_packages": [
            {"name": "Excavation", "description": "Dig", "planned_value": "1234567.89"},
        ],
    }
    agreement.update(overrides)
    return agreement


class TestSubcontractQuotesMoneyInTheAgreementsCurrency:
    async def test_the_package_overrun_sentence_groups_and_codes_both_figures(self) -> None:
        assert await _only(SubcontractPackagesWithinValue(), _agreement()) == (
            "The work packages are worth 1,234,567.89 GBP but the contract is 1,000.00 GBP"
        )

    async def test_a_non_positive_contract_value_is_still_an_amount(self) -> None:
        assert await _only(SubcontractAgreementValuePositive(), _agreement(total_value="-1234.50")) == (
            "The contract value is -1,234.50 GBP, so retention and the schedule of values have nothing to work from"
        )

    async def test_a_zero_decimal_currency_rounds_rather_than_truncating(self) -> None:
        """``1234567.89`` in yen is ``1,234,568``, not ``1,234,567``.

        The trailing ``.89`` has to go somewhere, and it goes into the digit
        before it. That makes this the sharper of the two zero-decimal pins: it
        fails both for a renderer that kept the cents and for one that dropped
        them without rounding.
        """
        message = await _only(SubcontractPackagesWithinValue(), _agreement(currency="JPY"))
        assert message == "The work packages are worth 1,234,568 JPY but the contract is 1,000 JPY"
        assert "1,234,567" not in message

    async def test_an_agreement_without_a_currency_is_grouped_but_uncoded(self) -> None:
        message = await _only(SubcontractPackagesWithinValue(), _agreement(currency=""))
        assert message == "The work packages are worth 1,234,567.89 but the contract is 1,000.00"

    async def test_retention_is_a_percentage_and_stays_bare(self) -> None:
        message = await _only(SubcontractRetentionWithinBounds(), _agreement(retention_percent="1234.50"))
        assert message == "Retention of 1234.50% is outside the plausible range of 0 to 50.00%"
        assert "GBP" not in message
        assert "1,234" not in message
