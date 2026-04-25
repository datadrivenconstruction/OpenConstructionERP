# ADR 002 — No IfcOpenShell, DDC canonical format is single source of truth

**Status:** accepted
**Date:** 2026-04-25
**Supersedes:** confirms the existing ban in `.claude/CLAUDE.md` §"Важные ограничения" #1
**Related:** RFC 34 (OCE global spec integration)

## Context

`OCE_TECH_SPEC_GLOBAL.md` recommends **`ifcopenshell`** as the core IFC parser for Modules 2 (BIM Diff), 3 (Validation EAC), 4 (Classification ML), and 5 (QTO). Every code example in the spec assumes direct IFC parsing.

OpenConstructionERP has explicitly banned IfcOpenShell since project inception (`CLAUDE.md` line: «НЕ используем IfcOpenShell — весь BIM/CAD через DDC cad2data pipeline»). The reasoning:

- DDC `cad2data` already converts DWG, DGN, RVT, **and IFC** into one canonical format (Parquet + JSON).
- A single canonical schema means downstream code (diff, validation, QTO) handles all formats identically — DWG-only projects work the same as IFC-only projects.
- IfcOpenShell would add a heavy native dependency (~80 MB compiled) and a second parser path that diverges over time.
- Reading Parquet is faster than parsing 5 GB IFC each time a diff is requested.

The user has now reconfirmed the ban (2026-04-25): «cad2data используем только, IfcOpenShell нам не нужен».

## Decision

**Use DDC `cad2data` canonical format as the single source of truth for ALL BIM operations.** No IfcOpenShell, no `ifctester`, no `web-ifc` on the backend. The frontend BIM viewer (Three.js) consumes the same canonical Parquet/JSON and never touches IFC directly.

Where the spec uses IfcOpenShell APIs, we map to the canonical-format equivalents:

| Spec assumes | We use instead |
|---|---|
| `ifc.by_type("IfcWall")` | DuckDB query on canonical Parquet: `SELECT * FROM elements WHERE category='IfcWall'` |
| `entity.GlobalId` | `BIMElement.stable_id` (DDC-assigned, derived from RVT ElementId or IFC GlobalId) |
| `IfcPropertySet` traversal | `BIMElement.properties: JSONB` (already flat) |
| `IfcElementQuantity` | `BIMElement.quantities: JSONB` populated by DDC |
| `ifcopenshell.geom.create_shape` | DDC pre-computes `geometry_signature` (volume, surface_area, bbox, mesh_hash) per element |
| `IfcRelAssociatesClassification` | `element_classification` table (our schema) |

For requirements where DDC currently does **not** emit the equivalent (e.g., per-property change history, geometry mesh-hash), we extend the DDC adapter rather than adding IfcOpenShell.

## Consequences

**Positive**
- One CAD format pipeline, one canonical schema, one query layer (DuckDB).
- BIM Diff / QTO / Validation work identically across DWG / DGN / RVT / IFC.
- No new heavy native deps; existing `bim_hub/ifc_processor.py` remains the only IFC entry point.
- Server can run on a 2 GB VPS (DDC binary bundled; no IfcOpenShell).

**Negative / mitigated**
- We re-implement what `ifcopenshell.geom` does (mesh hashing, area/volume from geometry). Mitigation: extend DDC to emit these once per element (it already emits triangulated meshes for the Three.js viewer; we add SHA-256 of the deduplicated vertex set).
- Some IDS validators in the wild are written against IfcOpenShell APIs. Mitigation: our IDS round-trip operates on canonical entities; a thin shim can adapt when needed.
- Spec code samples need translation. Mitigation: RFC 34 §5 provides the canonical-format equivalent for every spec algorithm.

## Implementation note

Where the spec mentions tools that internally use IfcOpenShell (e.g., `ifctester` for IDS validation), we either:
1. Use them in **read-only** mode, parsing the IDS XML schema only (no IFC bytes go through them), or
2. Reimplement the small surface we need on top of canonical entities.

Option 1 is acceptable because the dependency stays at the IDS-spec level, never at the BIM-data level — and it doesn't ship runtime bytes from real models through IfcOpenShell.

## Verification

- `pip-audit` and `pyproject.toml` MUST NOT contain `ifcopenshell`, `ifc-openshell`, `ifctester`, `pythonocc-core`, `pyifcopenshell` in any environment (dev, test, prod).
- CI gate: ruff custom rule rejects `import ifcopenshell` or `from ifcopenshell` anywhere under `backend/`.
- Documentation gate: any RFC referencing IfcOpenShell as a runtime parser is rejected by the RFC review template.
