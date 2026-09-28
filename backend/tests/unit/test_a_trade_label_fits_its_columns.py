# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A trade label the demo seeder derives has to fit every column it is written to.

The seeder turns each bill section title into a short trade label and writes it
into the punch list's ``trade``, the finance budget's ``category`` and the other
registers that group by trade. Every one of those columns is ``String(100)``,
and the label was cut at 120. PostgreSQL does not round a value that is too long,
it rejects the row, so the Spanish and Italian country demos, whose section
titles carry a full Spanish or Italian heading plus an English gloss, failed to
install at all, and the two packs that install them came up with no demo project.
"""

from __future__ import annotations

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _clean_trade, _section_trades
from app.modules.finance.models import ProjectBudget
from app.modules.punchlist.models import PunchItem

_WIDTHS = {
    "oe_punchlist_item.trade": PunchItem.__table__.c.trade.type.length,
    "oe_finance_budget.category": ProjectBudget.__table__.c.category.type.length,
}


def test_the_widths_were_read() -> None:
    assert all(isinstance(w, int) and w > 0 for w in _WIDTHS.values()), _WIDTHS


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_every_trade_label_fits_the_narrowest_column(demo_id: str) -> None:
    narrowest = min(_WIDTHS.values())
    too_long = [t for _, t, _ in _section_trades(DEMO_TEMPLATES[demo_id]) if len(t) > narrowest]
    assert not too_long, f"{demo_id}: trade labels over {narrowest} characters: {too_long}"


def test_a_long_title_is_cut_at_a_word_and_not_mid_word() -> None:
    title = "Capitulo 1. Trabajos previos, contencion y movimiento de tierras " * 3
    label = _clean_trade(title)
    assert len(label) <= min(_WIDTHS.values())
    assert title.startswith(label)
    assert not label.endswith(" "), label
    assert title[len(label)] in " ,;:", f"cut inside a word: {label!r}"
