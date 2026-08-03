# Importing Revit data via revit-mcp

Bring element, type and material data out of an open Revit session and into
BIM Hub, without a `.rvt` upload and without an Autodesk cloud round trip.

## Why a file, not a live connection

`revit-mcp` and `mcp-server-for-revit` are **stdio** MCP servers. The MCP
client launches them as a child process, and they then talk to a Revit
add-in over a loopback socket. Both halves must live on the machine where
Revit is running.

That means no remote process can call them — not the ERP backend, not a CI
job, not a cloud agent session. Running the server elsewhere starts fine
and then fails on every tool call with `connect to revit client failed`,
because nothing is listening on the other end of the socket.

So the bridge is a file. You run the read tools next to Revit, save the raw
JSON, and the converter turns it into a BIM Hub bulk-import payload.

## 1. Dump on the Revit workstation

With the model open in Revit and `revit-mcp` configured in your local MCP
client, run the read-only tools and save each response under its tool name:

```json
{
  "get_current_view_info":     { ... },
  "get_current_view_elements": { ... },
  "get_material_quantities":   { ... },
  "analyze_model_statistics":  { ... }
}
```

Any subset works. What each contributes:

| Tool | Produces | Notes |
| --- | --- | --- |
| `analyze_model_statistics` | one row per family **type** | always available; carries category, family, instance count |
| `get_material_quantities` | one row per **material** | area/volume plus the element ids consuming it |
| `get_current_view_elements` | one row per **instance** | richest tier, but see the view caveat below |
| `get_current_view_info` | model metadata only | active view name/type/scale |

**Pick a model view before dumping.** `get_current_view_elements` returns
the elements of the *active* view. If a sheet is active you get its
viewports and nothing else — `FilteredElementCount: 0` with no error. Open a
3D view or a plan view first.

**Ask for categories the model actually has.** A request for
`OST_Walls`/`OST_Floors` against an electrical model returns zero rows and
looks like a broken dump. Run `analyze_model_statistics` first and pick the
categories it reports.

## 2. Convert

```bash
cd backend
python -m app.scripts.import_revit_mcp_dump revit_dump.json \
    --out payload.json \
    --model-out model.json \
    --units imperial
```

The script is read-only: no database, no network. It prints a per-tier row
count and a warning list, and exits `1` only when the dump yields nothing.

### Units

The Revit API reports areas in ft² and volumes in ft³ internally, and the
MCP servers forward those numbers with no unit field. Nothing in the dump
lets the converter *verify* which unit it received, so it does not guess:

- `--units raw` (default) — numbers kept verbatim as `area_raw` /
  `volume_raw`, with `metadata.units = "unverified"`.
- `--units imperial` — read as ft²/ft³, emitted as `area_m2` / `volume_m3`.

Confirm against a known quantity in Revit before trusting converted totals
downstream. Plausible-looking magnitudes are not confirmation.

### Annotation categories

Tags, title blocks, sheets, dimensions and detail items are dropped by
default. `BIMElement` doubles as the project asset register, and drafting
entities can never carry geometry, quantity or cost. Pass
`--include-annotation` if you want them anyway.

Unknown categories are **kept**, not dropped — the filter only excludes
categories it positively recognises as drafting.

## 3. Import

Create (or pick) the target model, then POST the payload:

```
POST /api/v1/bim/models/{model_id}/elements/
Content-Type: application/json

<contents of payload.json>
```

The endpoint **replaces** the model's existing elements and needs the
`bim.create` permission. `model.json` holds suggested `BIMModel` field
values (name, storey count, level list, Revit totals) for the model record
itself.

## What lands, and what does not

Each row records its origin in `metadata.tier` (`instance` / `type` /
`material`) and keeps its Revit provenance in `properties`
(`revit_category`, `revit_family`, `revit_type`, `revit_element_id`).

Categories resolve to canonical IFC classes through
`app.modules.match_elements.revit_ifc_map`, so imported rows inherit the
same trade and DIN 276 hints an IFC import gets. A category with no
confident mapping keeps its raw Revit name rather than being forced into a
wrong class — Revit's `Security Devices`, which mixes cameras, door
contacts and panic buttons, is the deliberate example.

Two things this route cannot give you:

- **No geometry.** The MCP read tools return properties, not meshes, so
  imported elements have no `mesh_ref` and will not appear in the 3D
  viewer. Upload the `.rvt`/`.ifc` through the normal CAD pipeline for that.
- **No per-element quantities from the material tier.** Material area and
  volume are aggregates across every element that uses the material. The
  element ids are preserved as `properties.revit_element_ids` so a later
  instance-tier import can attach composition per element, but splitting an
  aggregate across its consumers would be invention, so the converter
  does not do it.

## Field-name tolerance

The instance tier probes several spellings for each field
(`Id`/`ElementId`/`elementId`/`id`, `Category`/`categoryName`, …) because
the MCP servers in circulation disagree on casing. Rows with no
recognisable element id are skipped and counted in the warnings rather
than silently dropped.
