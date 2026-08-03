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

**Merge the tool responses into one file.** Getting all three tiers means
one dump holding `analyze_model_statistics`, `get_material_quantities` *and*
a `get_current_view_elements` taken from a model view. If you collected
them in separate sessions (a sheet-view pass, then a 3D pass), merge the
objects — the converter takes whatever keys are present, and the project
name comes from `analyze_model_statistics`, so a 3D-only dump falls back to
naming the model after the active view.

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

The Revit API reports lengths in feet internally, and the MCP servers
forward the numbers with no unit field. Nothing in the dump *states* the
unit, so the converter does not assume one:

- `--units raw` (default) — numbers kept verbatim as `length_raw` /
  `area_raw` / `volume_raw`, coordinates unscaled, and
  `metadata.units = "unverified"`.
- `--units imperial` — read as ft/ft²/ft³, emitted as `length_m` /
  `area_m2` / `volume_m3` with coordinates and bounding boxes scaled to
  metres by the same factor.

Quantities and coordinates always share one scale. A row whose `length_m`
is metric while its `bounding_box` stayed in feet would read as consistent
and not be — the kind of mismatch a spatial consumer cannot detect.

**How to check your own dump.** Two tests, both cheap:

1. Look at `analyze_model_statistics.levels[].elevation`. If the project
   was designed in metric, feet values land on exact metric round numbers.
   In one real model, `-0.984256293145908` → `-0.300 m`,
   `16.404199475065617` → `5.000 m` and `36.089238845144358` → `11.000 m`
   after `× 0.3048` — conclusive.
2. For a line-based element, compare the reported `Length` against the
   distance between its start and end points after conversion. They must
   agree; if they do, both were in the same unit you assumed.

Plausible-looking magnitudes on their own are not confirmation.

### Locale-formatted numbers

Element property values are formatted through the workstation's Windows
regional settings. A Revit session on an id-ID or de-DE machine emits
`"-202,83"` where an en-US one emits `"-202.83"`, so `float()` raises on
every coordinate and length in the dump. The converter handles both, plus
grouped forms like `"1.234,56"` and `"1,234.56"`.

One shape is genuinely ambiguous: a lone comma with exactly three trailing
digits. `"1,234"` is 1234 under en-US grouping and 1.234 under a
decimal-comma locale, and guessing wrong is a 1000× error. Those values are
**declined** rather than guessed — the row loses that quantity, the raw
strings are preserved in `properties.revit_raw_geometry`, and the count
appears in the warnings.

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
(`revit_category`, `revit_element_id`, `revit_unique_id`, `revit_type_id`,
plus `revit_mark` and `revit_comments` when set).

Point-based elements carry `properties.revit_location`. Line-based ones
carry `revit_start` / `revit_end`, a real `bounding_box` and a `length`
quantity. A point-based fixture gets **no** bounding box: a zero-volume box
at its position reads as a bug downstream.

### Joining instances to their types is not reliable by name

Revit's `Element.Name` returns the *instance* name where the instance has
one and the type name otherwise, and nothing in the dump distinguishes the
two cases. In one real electrical model, Lighting Fixtures reported type
names (`HIGHBAY 120W NRML`, which matches `analyze_model_statistics`)
while Electrical Equipment reported panel designations (`MCC`,
`DB-UTILTY`, `CONTROL PANEL`, none of which appear as types).

So the converter files that value in the `name` column only and never
claims it is a type name. Two consequences:

- `properties.revit_type_id` — the numeric type ElementId — is the one
  reliable way to group instances by type, because it does not depend on
  how `Element.Name` resolved. Note that `Properties.Family` and
  `Properties.Type` both hold this same id; neither is a family name.
- Joining the instance tier to the type tier by name covered about 70% of
  instances in that model. The rest were either equipment carrying its own
  name, or system families (Cable Trays, Cable Tray Fittings) that
  `analyze_model_statistics` reports with `typeCount: 0` and therefore
  produce no type rows at all.

The readable family name exists only in `analyze_model_statistics`.

Categories resolve to canonical IFC classes through
`app.modules.match_elements.revit_ifc_map`, so imported rows inherit the
same trade and DIN 276 hints an IFC import gets. A category with no
confident mapping keeps its raw Revit name rather than being forced into a
wrong class — Revit's `Security Devices`, which mixes cameras, door
contacts and panic buttons, is the deliberate example.

Three things this route cannot give you:

- **No geometry.** The MCP read tools return properties, not meshes, so
  imported elements have no `mesh_ref` and will not appear in the 3D
  viewer. Upload the `.rvt`/`.ifc` through the normal CAD pipeline for that.
- **No storey.** `get_current_view_elements` reports no level or storey
  field, so `BIMElement.storey` stays `NULL` and per-floor filters will not
  see these rows. The converter reports the count in its warnings rather
  than inferring a level from the Z coordinate — level boundaries are not
  in the dump, so any such assignment would be a guess.
- **No per-element quantities from the material tier.** Material area and
  volume are aggregates across every element that uses the material. The
  element ids are preserved as `properties.revit_element_ids` so a later
  instance-tier import can attach composition per element, but splitting an
  aggregate across its consumers would be invention, so the converter
  does not do it.

## Field-name tolerance

`mcp-server-for-revit` nests per-element parameters under `Properties`
while other builds put them alongside the id, so the converter flattens
both into one namespace before reading. Within that, it probes several
spellings per field (`Id`/`ElementId`/`elementId`/`id`,
`Category`/`categoryName`, `Level`/`levelName`, …) because the servers in
circulation disagree on casing.

Rows with no recognisable element id are skipped and counted in the
warnings rather than silently dropped. Unknown categories are kept, not
filtered — only categories positively recognised as drafting are excluded.
