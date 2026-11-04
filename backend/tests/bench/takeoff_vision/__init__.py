"""Accuracy benchmark for the vision plan reader, the DWG takeoff and the text analyzer.

Ground truth is generated, never hand-measured: ``plans`` draws floor plans as
real PDFs with known rooms, openings and scale; ``dwg_cases`` writes DXF files
with known areas, lengths and counts. ``mock_model`` stands in for the vision
model with recorded-style responses, realistic and adversarial. ``score``
turns proposals into metrics and ``run_bench`` appends one JSON line per run to
``ledger.jsonl``. ``live_run`` is the opt-in slice against a real provider.
"""
