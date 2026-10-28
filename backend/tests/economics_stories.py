# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The economics stories shipped in the eleven-areas pack, read from the pack files as a test double for the pack lookup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEMO_DIR = (
    Path(__file__).resolve().parents[2]
    / "packs"
    / "eleven-areas-framework"
    / "src"
    / "openconstructionerp_eleven_areas_framework"
    / "demo"
)
DEMO_IDS = ("residential-regensburg", "school-ludwigsburg")


def story_for(demo_id: str) -> dict[str, Any]:
    return json.loads((DEMO_DIR / f"{demo_id}-economics.json").read_text(encoding="utf-8"))


def fake_demo_module_story(demo_id: str | None, module: str) -> dict[str, Any]:
    """What ``demo_module_story`` answers with the eleven-areas pack active."""
    return story_for(demo_id) if module == "economics" and demo_id in DEMO_IDS else {}
