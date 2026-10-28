# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A photo category has to mean the same thing at all three places that state it.

The module said it three times and one of them disagreed. Uploading validated
against ``VALID_PHOTO_CATEGORIES`` in the service, which listed ``aerial``;
editing validated against a pattern written out by hand in the schema, which did
not; and the gallery offered ``aerial`` in its picker, gave it its own badge
colour and shipped a translated label for it in every locale. So a drone shot
could be uploaded, shown and filtered, and the moment anyone set that category
from the photo editor the API answered 422. Nothing in the module could see the
disagreement, because each of the three lists was locally consistent.

The schema owns the set now and the other two are checked against it here. The
frontend one is read out of the TypeScript union rather than mirrored into
Python: a copy in a fixture would be a fourth statement of the same thing and
would drift the same way.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.documents.schemas import PHOTO_CATEGORIES, PhotoUpdate
from app.modules.documents.service import VALID_PHOTO_CATEGORIES

_API_TS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "features" / "documents" / "api.ts"


def test_the_uploader_and_the_editor_accept_the_same_categories() -> None:
    assert set(PHOTO_CATEGORIES) == VALID_PHOTO_CATEGORIES


@pytest.mark.parametrize("category", PHOTO_CATEGORIES)
def test_every_category_the_uploader_keeps_survives_an_edit(category: str) -> None:
    """The upload path stores these unchanged, so the edit path must accept them.

    Before this, uploading with ``aerial`` stored ``aerial`` and editing to
    ``aerial`` was refused, which is the worst arrangement of the two: the value
    reaches the database and the screen, and only fails when a user touches it.
    """
    assert PhotoUpdate(category=category).category == category


def test_an_unknown_category_is_still_refused() -> None:
    """Widening the set must not have turned the field into a free-text column."""
    with pytest.raises(ValueError):
        PhotoUpdate(category="not_a_category")


def test_the_gallery_offers_exactly_what_the_api_accepts() -> None:
    """A picker option the API refuses is a button that answers 422.

    Read from the union the gallery's picker is typed by, so this fails if
    either side is edited alone.
    """
    if not _API_TS.exists():  # pragma: no cover - backend-only checkouts
        pytest.skip(f"frontend not present at {_API_TS}")
    source = _API_TS.read_text(encoding="utf-8")
    match = re.search(r"export type PhotoCategory\s*=\s*([^;]+);", source)
    assert match, "PhotoCategory union not found; this check has drifted, not passed"
    offered = {word.strip().strip("'") for word in match.group(1).split("|")}
    assert offered == set(PHOTO_CATEGORIES), (
        f"gallery offers {sorted(offered - set(PHOTO_CATEGORIES))} the API refuses, "
        f"and hides {sorted(set(PHOTO_CATEGORIES) - offered)} the API accepts"
    )
