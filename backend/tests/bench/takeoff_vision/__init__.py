"""Accuracy benchmark for the DWG takeoff and the document text analyzer.

Ground truth is generated, never hand-measured: ``dwg_cases`` writes DXF files
with known areas, lengths and counts; ``analyze_cases`` writes specification
texts with a mock model answer that invents and repeats items.
"""
