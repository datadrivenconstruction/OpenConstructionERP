# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo portfolio files each project under a delivery region it belongs to."""

from __future__ import annotations

from app.modules.portfolio.seed import _region_for

#: The six members of the Gulf Cooperation Council.
_GCC = ("AE", "SA", "QA", "KW", "OM", "BH")


def test_the_gulf_programme_holds_the_gulf_states_and_nothing_else() -> None:
    for country in _GCC:
        assert _region_for(country)[0] == "GULF", country


def test_turkey_is_filed_under_europe_middle_east_and_africa() -> None:
    # Turkey is not a Gulf state, and the Istanbul demo used to land in a
    # subprogramme named "Gulf states".
    assert _region_for("TR") == ("EMEA", "Europe, Middle East and Africa")
