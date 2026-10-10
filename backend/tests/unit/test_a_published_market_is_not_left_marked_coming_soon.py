# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""A market DDC ships must not read as unpublished in the v3 registry.

``_HF_PUBLISHED`` in :mod:`app.modules.costs.cwicr_v3_catalogue` is the hand
kept record of which regions DDC has actually published a v3 BGE-M3 snapshot
for. A region missing from it stays ``available=False``, so the setup grid
renders a "coming soon" card with the Install CTA disabled and the install
endpoint answers 409, while the file sits on the CDN. Nothing in the module
notices, because every other check in the registry's own test file reads that
same mapping and therefore agrees with it by construction.

The check here reads a second structure that knows nothing about publication
status: :mod:`app.modules.costs.base_registry`, whose global markets are
derived from its own family tables and which names the market by the id the
published file carries (``ZH_SHANGHAI``, ``TR_ISTANBUL``). The v3 rows for those
two once sat under the national ids ``ZH_CHINA`` and ``TR_NATIONAL``, which name
different catalogues, and now carry the market ids themselves.
Two tables written at different times for different jobs, so agreement between
them is evidence rather than a tautology.

That is not a hypothetical. Both Chinese and Turkish snapshots were published
on 2026-05-11, in the same batch as the forty rows that work, and were left out
of the mapping.
"""

from __future__ import annotations

from app.modules.costs import base_registry
from app.modules.costs.cwicr_v3_catalogue import (
    _HF_PUBLISHED,
    _REGION_ALIASES,
    CWICR_V3_CATALOGUES,
)


def _published_v3_regions() -> set[str]:
    """Every id that reaches a v3 row the registry offers for install.

    A market can be named three ways: by the platform region id, by the id it
    was renamed from (recorded in ``_REGION_ALIASES``), or by the stem of the
    file DDC published it under (the second half of an ``_HF_PUBLISHED``
    value, e.g. ``ENG_TORONTO`` for ``CA_TORONTO``).
    """

    names: set[str] = set(_HF_PUBLISHED)
    names |= {stem for _folder, stem in _HF_PUBLISHED.values()}
    names |= {old for old, new in _REGION_ALIASES.items() if new in _HF_PUBLISHED}
    return names


def test_every_shipped_global_market_reaches_a_published_v3_row() -> None:
    """No market may ship work items while its v3 card says coming soon."""

    markets = set(base_registry.github_snapshot_files())
    assert len(markets) == 30, (
        f"the global base ships {len(markets)} markets, not 30 - reread this guard "
        "before adjusting the number, because a market list that shrank to nothing "
        "would satisfy the assertion below for the wrong reason"
    )

    unpublished = sorted(markets - _published_v3_regions())
    assert not unpublished, (
        f"{unpublished} ship work items but no v3 row of theirs is in _HF_PUBLISHED, "
        "so the setup grid offers them as coming soon while the snapshot is live. "
        "Add the region to _HF_PUBLISHED with the folder and file stem DDC published."
    )


def test_the_two_registries_name_markets_differently() -> None:
    """Guard the guard: the comparison above must not be a self comparison.

    If the two modules ever came to hold the same ids, the check would still
    pass and would have stopped meaning anything. The ids genuinely differ
    today - the v3 registry renamed several regions after DDC published them -
    so assert that the sets are not equal rather than that they are.
    """

    markets = set(base_registry.github_snapshot_files())
    v3_regions = {cat.region for cat in CWICR_V3_CATALOGUES}
    assert markets != v3_regions, (
        "base_registry and the v3 registry now carry identical region ids, so the "
        "market check above compares a table with itself and can no longer fail"
    )
    assert markets - v3_regions, "every published market id is also a v3 region id - see above"
