# CLAUDE.md — CAD Converter Service

Parent: [../../CLAUDE.md](../../CLAUDE.md)

## Purpose

Converts ALL CAD formats to the canonical JSON format.
No IfcOpenShell. No BCF. No native IFC processing.

## Pipeline

```
DWG  → ODA SDK (C++) → Python bridge → Canonical JSON
DGN  → ODA SDK (C++) → Python bridge → Canonical JSON
RVT  → Rust parser (reverse engineering) → Canonical JSON
IFC  → ODA SDK (C++) → Python bridge → Canonical JSON
PDF  → PyMuPDF → vector/raster extraction → elements
```

## Output

Every conversion produces:
1. `canonical.json` — structured elements, levels, zones
2. `metadata.json` — source info, converter version, warnings
3. `quantities.parquet` — DuckDB-queryable quantities table

## Rust RVT Parser

Our own reverse-engineered parser for Autodesk Revit files.
Currently ~82% accuracy against C# MCP server ground truth.
Located in `rvt-parser/`.

## Important

- Output ALWAYS goes through validation pipeline before storage
- All measurements in metric internally
- Classification auto-mapping is best-effort (confidence scores)
