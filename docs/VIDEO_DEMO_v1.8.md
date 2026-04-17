# OpenConstructionERP v1.8 — 6-Minute Demo Storyboard

Walkthrough for showing the full platform to prospects, investors, and potential contributors.
Target duration: 5–7 minutes. Shot list + voiceover cues + key numbers to hit.

---

## Scene 1 — Hook (0:00–0:30)

**Visual.** Dashboard landing page. Soft fade-in on the project cards grid.
Cursor hovers the "New Project" button but doesn't click — the weather widget
pulses as live data loads.

**Voiceover.**
> "Every estimator knows the pain: drawings in one tool, quantities in a second,
> prices in a third, schedule in a fourth. Switching costs you a day per week.
> OpenConstructionERP replaces all of them — open source, self-hosted, AI-native."

**Numbers on screen.**
- 55,000+ cost items (CWICR) · 21 languages · 20 standards · 4D/5D · BIM/CAD

---

## Scene 2 — CAD/BIM takeoff in 30 seconds (0:30–1:30)

**Visual.** Drag a `.rvt` file onto `/bim`. Upload progress runs in the corner.
Cut to the loaded 3D viewer — elements paint in, filter panel slides open.
Click a wall — Linked BOQ panel populates with area/volume/length.

**Voiceover.**
> "Drop a Revit or IFC model. Our in-house cad2data pipeline — not
> IfcOpenShell — converts it to a canonical JSON in seconds. Three hundred
> thousand elements, searchable, filterable, linkable to your BOQ."

**Show.**
- Filter by storey / discipline / type
- Color-by validation / BOQ coverage (traffic-light)
- "Add to BOQ" modal → quantities auto-fill

---

## Scene 3 — PDF Takeoff & BOQ linking (1:30–2:45) ⭐ NEW in v1.8

**Visual.** Navigate to `/takeoff`. Click a previously uploaded PDF from the
bottom filmstrip. Draw a polygon around a floor slab — area appears.
Click the measurement's "Link to BOQ" button — picker opens.

**Voiceover.**
> "PDF takeoff isn't a separate island anymore. Every measurement you draw
> links to a BOQ position — or creates one on the spot. The quantity flows
> across, the PDF page reference is stored, and the BOQ grid shows a red PDF
> icon next to that row. One click later, you're back in the drawing."

**Show.**
- Pick existing position OR create-and-link with auto `TK.NNN` ordinal
- Unit normalization (`m²` ↔ `m2`)
- BOQ grid: red PDF icon + amber DWG icon next to linked rows
- Click icon → opens document in same tab (auth preserved)

---

## Scene 4 — BOQ editor + AI assist (2:45–4:00)

**Visual.** Open the BOQ. AG Grid with assemblies, DIN 276 tree, inline edit.
Select a position with a BIM link — open Linked Geometry popover.
Hover a BIM parameter — "Set as quantity" button appears — click it.

**Voiceover.**
> "The BOQ editor is a proper spreadsheet — AG Grid, keyboard nav, assemblies,
> DIN 276, GAEB X83 export. But it's also live-connected to your BIM model:
> any property on the 3D element — wall thickness, fire rating, area — is one
> click from becoming a quantity."

**Show.**
- Σ aggregation for area/volume/length
- GAEB X83 export
- AI panel suggests cost codes with confidence scores

---

## Scene 5 — Validation, tender, report (4:00–5:00)

**Visual.** `/validation` dashboard — traffic light: green/yellow/red.
Drill into a red rule, jump to the offending position. Fix it.
Go to `/tendering` — generate bid package → compare bids.

**Voiceover.**
> "Validation isn't optional — DIN 276, GAEB, boq_quality rules run on every
> import. Before you send a tender to subcontractors, you know it's complete
> and compliant. Bids come back, spread analysis flags outliers, award in a
> click."

**Numbers on screen.**
- 8 built-in rule sets · custom rules via Python

---

## Scene 6 — 4D/5D + ecosystem (5:00–6:00)

**Visual.** `/schedule` Gantt — drag bar → budget reflows in `/cost-model`.
`/dashboard` map widget shows live weather at the site.
Cut to `/settings` → plugin marketplace tab.

**Voiceover.**
> "Schedule drives budget — drag a Gantt bar, the 5D curve updates. Weather
> at the site, live. And everything is a plugin — drop a module folder, reload,
> it shows up. RSMeans, BKI, BCIS, n8n — all community."

**Closing card (5:50–6:00).**
> "Self-hosted. AGPL-3.0. `pip install openconstructionerp`. Or use the
> hosted demo. Your data, your call."
>
> `github.com/datadrivenconstruction/OpenConstructionERP`
> `openconstructionerp.com`

---

## Production notes

- **Screen resolution.** Record at 1920×1080, 60fps. Crop to 1600×900 for
  final so UI breathes.
- **Cursor.** Use a yellow/orange highlighter cursor (e.g. Mouseposé) so
  clicks are visible on the speed-up cuts.
- **Speed ramps.** Upload & processing cuts — ramp to 4x. Drawing/clicking —
  keep 1x so viewers can follow.
- **Audio.** Quiet ambient bed (Artlist: "Evolving Roots"), no music under
  voiceover.
- **B-roll.** Before the hook, 3 seconds of construction-site drone footage
  with the logo overlay.
- **Captions.** Burn in EN captions; auto-translate to DE / RU / ES / ZH for
  YouTube.

## Key numbers to hit on screen

| Metric | Value |
|---|---|
| Cost items in CWICR | 55,000+ |
| Languages | 21 |
| Standards supported | 20 |
| BIM formats | RVT / IFC / DWG / DGN / DXF / RFA |
| Validation rule sets | 8 built-in + custom |
| Open-source license | AGPL-3.0 |
| Self-hosted RAM floor | 2 GB |
