# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Classification rules of the v3304 stock-cost-currency migration.

The migration decides, per stock balance, whether its stored average cost was
denominated in one currency all along ("single", keep the number), blended two
or more ("mixed", withdraw it), or cannot be traced ("unknown", withdraw it).
That decision is a pure function over the currencies of the balance's inbound
movements, so it is tested here without a database.

The cases that matter are the ones where a wrong answer is silent: an empty
list must not read as agreement, and one unresolvable movement among many good
ones must not be outvoted, because the stored average was computed over all of
them.
"""

from __future__ import annotations

from pathlib import Path


def _load_migration():
    """Load the v3304 migration module from its path.

    ``alembic/versions`` has no ``__init__.py``, so it is not importable as a
    package; the alembic runner loads these files by path and so do we.
    """
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3304_stock_balance_currency.py"
    spec = importlib.util.spec_from_file_location("v3304_stock_balance_currency", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MIG = _load_migration()


def test_one_currency_is_single_and_keeps_its_code():
    assert _MIG._classify(["EUR"]) == ("single", "EUR")
    assert _MIG._classify(["EUR", "EUR", "EUR"]) == ("single", "EUR")


def test_two_currencies_are_mixed_and_name_neither():
    state, currency = _MIG._classify(["EUR", "USD"])
    assert state == "mixed"
    # Naming one of them would be worse than naming none: it would make the
    # blended average look like a price in that currency.
    assert currency is None


def test_a_balance_with_no_inbound_movements_is_unknown_not_single():
    """An empty set is not agreement.

    A balance whose average came from somewhere untraceable has no evidence
    behind it, and "everything I found agreed" is a claim about nothing here.
    """
    assert _MIG._classify([]) == ("unknown", None)


def test_one_unresolvable_movement_makes_the_whole_balance_unknown():
    """The stored average was computed over every receipt, including this one.

    A movement whose purchase order is gone contributed a price to the average
    in some currency nobody can now name, so the rest agreeing proves nothing.
    """
    assert _MIG._classify(["EUR", None]) == ("unknown", None)
    assert _MIG._classify([None]) == ("unknown", None)
    # Unresolvable outranks disagreement: this balance is not merely mixed,
    # it is mixed with an unknown quantity of something unidentified.
    assert _MIG._classify(["EUR", "USD", None]) == ("unknown", None)


def test_blank_currency_codes_are_not_currencies():
    """A blank must not let two unlabelled orders agree with each other."""
    assert _MIG._norm_currency(None) is None
    assert _MIG._norm_currency("") is None
    assert _MIG._norm_currency("   ") is None
    assert _MIG._norm_currency(" eur ") == "EUR"


def test_movement_and_receipt_ids_compare_as_text():
    """``reference_id`` stores ``str(gr.id)``; the driver may hand back a UUID.

    If these two stopped matching, every movement would silently fall into the
    unresolvable bucket and the migration would report a clean-looking result
    while classifying the entire estate as unknown.
    """
    import uuid as _uuid

    real = _uuid.uuid4()
    assert _MIG._norm_key(real) == _MIG._norm_key(str(real))
    assert _MIG._norm_key(str(real).upper()) == _MIG._norm_key(str(real).lower())


def test_the_revision_chains_onto_the_recorded_head():
    """A migration that names the wrong parent forks the history silently."""
    assert _MIG.revision == "v3304_stock_balance_currency"
    assert _MIG.down_revision == "v3303_work_calendar_iso_weekdays"
