# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Demo seed values that a chart groups by, checked against their reader.

A panel that draws one category called "Not recorded" is not a picture of an
empty register. It is a picture of a full register grouped by a field nothing
populated - either because the writer left it null, or because the writer
spelled the key differently from the reader. The daily diary hit the second
case: the seeder wrote ``weather_summary.condition`` and the insights panel
selects ``weather_summary.conditions``, so four distinct weather codes were
seeded and none was ever found.

Nothing here needs a database. These are source-level drift checks, in the same
family as the vocabulary tests beside them: one value written down in two places
that can move apart.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_REPO = _BACKEND.parent
_DEMO_PROJECTS = _BACKEND / "app" / "core" / "demo_projects.py"
_DIARY_INSIGHTS = _REPO / "frontend" / "src" / "features" / "daily-diary" / "dailyDiaryInsights.ts"

# The key the insights panel selects. Pinned here so this file gates the
# regression on its own, without depending on the frontend tree being present -
# a check that silently skips is the failure mode this suite exists to avoid.
# The cross-check below keeps the pin honest when the frontend is available.
_WEATHER_DIMENSION = "conditions"


def _demo_projects_source() -> str:
    # Fail loudly rather than skip: if this path stops resolving the file has
    # moved, and a drift test that quietly stops running is worse than absent.
    assert _DEMO_PROJECTS.is_file(), f"demo seeder not found at {_DEMO_PROJECTS}"
    return _DEMO_PROJECTS.read_text(encoding="utf-8")


def test_the_diary_writer_uses_the_key_the_insights_reader_selects() -> None:
    """The seeded weather dimension is spelled the way the panel reads it."""
    source = _demo_projects_source()
    written = re.findall(r'"weather_summary":\s*\{\s*"([a-z_]+)"', source)

    assert written, 'no "weather_summary" payload found in the demo seeder'
    off_key = [key for key in written if key != _WEATHER_DIMENSION]
    assert not off_key, (
        f"the demo seeder writes weather_summary.{off_key[0]!r} but the insights "
        f"panel groups on {_WEATHER_DIMENSION!r}, so every diary lands in the "
        f'"Not recorded" bucket'
    )


def test_the_pinned_weather_key_is_what_the_frontend_actually_selects() -> None:
    """The pin above is not allowed to drift away from the real reader."""
    if not _DIARY_INSIGHTS.is_file():
        pytest.skip("frontend tree not present in this checkout")

    reader = _DIARY_INSIGHTS.read_text(encoding="utf-8")
    selected = re.findall(r"summary\?\.([a-z_]+)", reader)

    assert selected, f"no weather selection found in {_DIARY_INSIGHTS.name}"
    assert _WEATHER_DIMENSION in selected, (
        f"this test pins {_WEATHER_DIMENSION!r} but the panel now selects "
        f"{sorted(set(selected))} - update the pin and the seeder together"
    )
