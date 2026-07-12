# Plan-image extraction eval

Evaluates the Gemini-vision extraction path for floor-plan images.

## Regression evals (always run, deterministic, no live API)

| Test | Location | Assertion |
|------|----------|-----------|
| `build_draft_plan` constructs correct polygon | `test_acap_vision.py::test_build_draft_plan` | Room polygon is CCW `[(0,0),(5.92,0),(5.92,4.2),(0,4.2)]`, area 24.864 |
| `vision_service_configured` reflects env | `test_acap_vision.py::test_vision_service_configured` | False when key absent, True when set |
| Extract endpoint key-gate | `test_acap_vision.py::test_extract_endpoint_returns_400_when_key_absent` | 400 + `reason == "GOOGLE_API_KEY not set"` |

Run: `cd backend && pytest -x -q tests/integration/test_acap_vision.py`

## Capability eval (needs GOOGLE_API_KEY + fixture image, manual)

Requires:
- `GOOGLE_API_KEY` set in the environment
- Real floor-plan image at `backend/tests/fixtures/plan_sample.jpeg` (SketchUp export; ~300 KB)

Decorated with `@pytest.mark.skipif(not os.environ.get("GOOGLE_API_KEY") or not FIXTURE.exists(), ...)`.

```python
@pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY")
    or not Path("tests/fixtures/plan_sample.jpeg").exists(),
    reason="needs GOOGLE_API_KEY + tests/fixtures/plan_sample.jpeg",
)
@pytest.mark.asyncio
async def test_capability_extract_floor_plan():
    from app.modules.acap.vision.client import extract_floor_plan

    image_bytes = Path("tests/fixtures/plan_sample.jpeg").read_bytes()
    result = await extract_floor_plan(image_bytes, "image/jpeg")

    # Assert >= 5 rooms found
    all_rooms = [r for lvl in result["levels"] for r in lvl["rooms"]]
    assert len(all_rooms) >= 5, f"Expected >=5 rooms, got {len(all_rooms)}: {[r['name'] for r in all_rooms]}"

    # Assert kavling within ±10% of 12.32 × 12.47
    kw, kl = result["kavling_width_m"], result["kavling_length_m"]
    assert 11.0 < kw < 13.6, f"kavling_width_m {kw} outside ±10% of 12.32"
    assert 11.2 < kl < 13.7, f"kavling_length_m {kl} outside ±10% of 12.47"

    # Assert every room type is in ROOM_TYPES enum
    VALID = {
        "kamar_tidur_utama","kamar_tidur","kamar_mandi","dapur","ruang_tamu",
        "ruang_keluarga","ruang_makan","carport","garasi","musholla","gudang",
        "teras","taman","sirkulasi","other",
    }
    for r in all_rooms:
        assert r["type"] in VALID, f"Unexpected room type {r['type']!r} in {r['name']}"

    # build_draft_plan pass@2
    from app.modules.acap.vision.extractor import build_draft_plan
    draft, valid, reasons = build_draft_plan(result)
    assert valid, f"build_draft_plan invalid: {reasons}"
```

## pass@k

- pass@2 on regression: always 1.0 (deterministic).
- pass@2 on capability: 2 consecutive successful extractions with >=5 rooms each.
