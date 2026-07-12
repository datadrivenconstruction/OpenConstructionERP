"""Build a draft ``FloorPlan`` dict from the Gemini vision extraction JSON.

This is a pure-function, testable offline layer: given an extraction result from
:func:`app.modules.acap.vision.client.extract_floor_plan`, it constructs a
FloorPlan-shaped dict with proper CCW polygons, computed area_m2, and runs the
layout validator. The result can be inspected, edited in ConfirmStep, and
persisted via ``saveLayout``.

The extractor NEVER writes to the database — the draft is returned to the
caller (the extract endpoint) which hands it to the frontend. Only
``saveLayout`` (manual user action) persists.
"""

from __future__ import annotations

from typing import Any

from app.modules.acap.vision.client import _model


def build_draft_plan(extract: dict) -> tuple[dict, bool, list[str]]:
    """Convert a Gemini vision extraction dict into a FloorPlan-shaped dict.

    Returns:
        A 3-tuple ``(draft_plan, valid, reasons)`` where:
        - ``draft_plan`` is a dict matching the FloorPlan schema.
        - ``valid`` is True when the layout passes all validator checks.
        - ``reasons`` is the list of validator error messages (empty when valid).
    """
    # Seed a minimal draft so a partial/garbled LLM payload still yields a
    # returnable dict on the error path (missing/None fields must degrade to
    # (draft, False, [reason]), NEVER a 500). All raw-field access lives inside
    # the try below.
    draft: dict[str, Any] = {
        "kavling": {},
        "levels": [],
        "requirement_text": "",
        "jumlah_lantai": 1,
        "generated_by": f"vision:{_model()}",
        "notes": "",
    }

    try:
        draft["kavling"] = {
            "width_m": extract["kavling_width_m"],
            "length_m": extract["kavling_length_m"],
        }
        draft["jumlah_lantai"] = len(extract.get("levels", [])) or 1
        draft["notes"] = "; ".join(extract.get("notes", []) or [])

        for level_data in extract.get("levels", []):
            rooms = []
            for room_data in level_data.get("rooms", []):
                x = room_data["x_m"]
                y = room_data["y_m"]
                w = room_data["width_m"]
                l = room_data["length_m"]

                room_type = room_data.get("type", "other")
                if room_type not in _VALID_ROOM_TYPES:
                    room_type = "other"

                rooms.append(
                    {
                        "name": room_data["name"],
                        "type": room_type,
                        "polygon": [
                            {"x": x, "y": y},
                            {"x": x + w, "y": y},
                            {"x": x + w, "y": y + l},
                            {"x": x, "y": y + l},
                        ],
                        "area_m2": round(w * l, 3),
                    }
                )

            draft["levels"].append(
                {
                    "level": level_data.get("level", 1),
                    "rooms": rooms,
                    "walls": [],
                    "openings": [],
                }
            )

        from app.modules.acap.layout.schema import FloorPlan
        from app.modules.acap.layout.validator import is_valid

        plan = FloorPlan.model_validate(draft)
        valid, reasons = is_valid(plan)
    except Exception as exc:
        return (draft, False, [str(exc)])

    return (draft, valid, list(reasons))


_VALID_ROOM_TYPES = frozenset(
    {
        "kamar_tidur_utama",
        "kamar_tidur",
        "kamar_mandi",
        "dapur",
        "ruang_tamu",
        "ruang_keluarga",
        "ruang_makan",
        "carport",
        "garasi",
        "musholla",
        "gudang",
        "teras",
        "taman",
        "sirkulasi",
        "other",
    }
)
