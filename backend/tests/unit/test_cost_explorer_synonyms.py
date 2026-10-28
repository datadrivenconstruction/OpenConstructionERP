"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for construction-vocabulary synonym expansion.

``app.modules.catalog.synonyms`` is pure (stdlib only), so it is loaded here
directly from its file path - independent of the FastAPI dependency graph, and
identical here and in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "app" / "modules" / "catalog" / "synonyms.py"
_spec = importlib.util.spec_from_file_location("catalog_synonyms", _PATH)
assert _spec and _spec.loader
synonyms = importlib.util.module_from_spec(_spec)
sys.modules["catalog_synonyms"] = synonyms
_spec.loader.exec_module(synonyms)
expand_query = synonyms.expand_query


def test_rebar_expands_to_reinforcement() -> None:
    out = [t.lower() for t in expand_query("rebar")]
    assert out[0] == "rebar"
    assert "reinforcement" in out


def test_formwork_expands_to_shuttering() -> None:
    assert "shuttering" in [t.lower() for t in expand_query("formwork")]


def test_plant_and_equipment_are_interchangeable() -> None:
    assert "equipment" in [t.lower() for t in expand_query("plant")]
    assert "plant" in [t.lower() for t in expand_query("equipment")]


def test_us_uk_spelling_pairs_expand_both_ways() -> None:
    assert "labour" in [t.lower() for t in expand_query("labor")]
    assert "labor" in [t.lower() for t in expand_query("labour")]


def test_original_is_first_and_case_preserved() -> None:
    out = expand_query("Plant")
    assert out[0] == "Plant"  # original preserved verbatim so it ranks itself


def test_unknown_term_returns_itself_only() -> None:
    assert expand_query("gizmo") == ["gizmo"]


def test_blank_returns_empty() -> None:
    assert expand_query("   ") == []


def test_multiword_query_is_not_expanded() -> None:
    # A descriptive phrase must not accidentally match a short synonym term.
    assert expand_query("reinforced concrete wall") == ["reinforced concrete wall"]


def test_expansion_is_deduped_and_capped() -> None:
    out = expand_query("rebar", limit=3)
    assert len(out) <= 3
    assert len(out) == len({t.lower() for t in out})


def test_distinct_materials_are_never_merged() -> None:
    # Guard against over-broadening: a brick must not pull in blocks, nor a
    # door windows. These are separate resources, not synonyms.
    assert "block" not in [t.lower() for t in expand_query("brick")]
    assert "window" not in [t.lower() for t in expand_query("door")]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print("ok", fn.__name__)
    print(f"\n{len(fns)} synonym tests passed")
