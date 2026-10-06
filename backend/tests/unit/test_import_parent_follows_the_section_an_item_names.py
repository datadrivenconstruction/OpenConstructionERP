# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An imported row lands under the section it names, whichever importer wrote it.

``_resolve_import_parent`` reads three signals: a section's dotted ordinal, a
GAEB item's ``gaeb_section`` and, since the XPWE importer, the neutral
``metadata.import_section``. The XPWE importer groups a bill by its category
tree, so an item is not always under the section row printed just above it;
without its own signal it would fall back to "the last section", which is the
wrong one whenever a section's items follow its sub-sections.

The GAEB, BC3 and spreadsheet cases are pinned beside it so the new key cannot
change what they resolve to.
"""

from __future__ import annotations

import uuid

from app.modules.boq.router import _resolve_import_parent

SECTIONS = {"1": uuid.uuid4(), "1.1": uuid.uuid4(), "2": uuid.uuid4()}
LAST = SECTIONS["2"]


def test_an_item_naming_its_section_attaches_to_it_not_to_the_last_one() -> None:
    row = {"is_section": False, "ordinal": "1.3", "metadata": {"import_section": "1"}}
    assert _resolve_import_parent(row, SECTIONS, LAST) == SECTIONS["1"]


def test_an_item_naming_no_section_is_top_level() -> None:
    row = {"is_section": False, "ordinal": "3", "metadata": {"import_section": ""}}
    assert _resolve_import_parent(row, SECTIONS, LAST) is None


def test_a_section_still_nests_by_its_ordinal() -> None:
    row = {"is_section": True, "ordinal": "1.1.2", "metadata": {"import_section": "2"}}
    assert _resolve_import_parent(row, SECTIONS, LAST) == SECTIONS["1.1"]


def test_gaeb_section_is_unchanged_and_wins_over_the_neutral_key() -> None:
    row = {"is_section": False, "metadata": {"gaeb_section": "1.1", "import_section": "2"}}
    assert _resolve_import_parent(row, SECTIONS, LAST) == SECTIONS["1.1"]
    in_classification = {"is_section": False, "metadata": {}, "classification": {"gaeb_section": "1"}}
    assert _resolve_import_parent(in_classification, SECTIONS, LAST) == SECTIONS["1"]
    explicit_top = {"is_section": False, "metadata": {"gaeb_section": ""}}
    assert _resolve_import_parent(explicit_top, SECTIONS, LAST) is None


def test_a_flat_spreadsheet_or_bc3_row_still_follows_the_section_above_it() -> None:
    row = {"is_section": False, "ordinal": "01.01", "metadata": {"import_row_index": 4}, "classification": {}}
    assert _resolve_import_parent(row, SECTIONS, LAST) == LAST
    assert _resolve_import_parent(row, {}, None) is None
