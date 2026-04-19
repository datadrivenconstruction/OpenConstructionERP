# CLAUDE.md — CAD Converter Service

Parent: [../../CLAUDE.md](../../CLAUDE.md)

## Purpose

Converts ALL CAD formats to the canonical JSON format.
No IfcOpenShell. No BCF. No native IFC processing.

## Pipeline

```
DWG  → DDC cad2data → Python bridge → Canonical JSON
DGN  → DDC cad2data → Python bridge → Canonical JSON
RVT  → DDC cad2data → Python bridge → Canonical JSON
IFC  → DDC cad2data → Python bridge → Canonical JSON
PDF  → PyMuPDF → vector/raster extraction → elements
```

## Output

Every conversion produces:
1. `canonical.json` — structured elements, levels, zones
2. `metadata.json` — source info, converter version, warnings
3. `quantities.parquet` — DuckDB-queryable quantities table

## RVT Parser

RVT import is handled by the DDC cad2data pipeline. Accuracy against
the upstream RVT ground truth is tracked in the pipeline's regression
suite.

## Important

- Output ALWAYS goes through validation pipeline before storage
- All measurements in metric internally
- Classification auto-mapping is best-effort (confidence scores)
