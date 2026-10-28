"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo seed's area ownership map must name the areas of the catalogue it pins, and leave none unowned."""

from __future__ import annotations

import uuid

from app.modules.project_governance import seed
from app.modules.project_governance.catalogue import get_catalogue


def test_every_mapped_code_exists_in_the_pinned_catalogue() -> None:
    codes = {a.code for a in get_catalogue(seed.DEMO_CATALOGUE).areas}
    assert set(seed.AREA_OWNERS) - codes == set()


def test_every_area_of_the_pinned_catalogue_is_mapped() -> None:
    # A new area in the catalogue would otherwise fall back silently instead of being placed on purpose.
    codes = {a.code for a in get_catalogue(seed.DEMO_CATALOGUE).areas}
    assert codes - set(seed.AREA_OWNERS) == set()


def test_the_estimator_owns_at_least_one_area() -> None:
    assert "cost" in set(seed.AREA_OWNERS.values())


def test_an_unmapped_area_goes_to_the_project_owner_never_unowned_never_the_decider() -> None:
    owner, cost = uuid.uuid4(), uuid.uuid4()
    assert seed.owner_for("not_in_the_map", owner=owner, cost_owner=cost) == owner
    assert seed.owner_for("cost_finance", owner=owner, cost_owner=cost) == cost
    assert seed.owner_for("risk", owner=owner, cost_owner=cost) == owner
