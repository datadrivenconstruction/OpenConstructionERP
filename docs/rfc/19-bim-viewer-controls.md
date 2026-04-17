# RFC 19 — BIM viewer control panel expansion

**Status:** draft
**Related items:** ROADMAP_v1.9.md #19 (R2 → v1.9.1)
**Date:** 2026-04-17

## 1. Context

The user asks for more useful and understandable controls in the BIM viewer at `/bim/:modelId`. The current viewer (`frontend/src/shared/ui/BIMViewer/BIMViewer.tsx`) already has a reasonable toolbar — the question is **what to add without cloning Navisworks.**

### Current controls inventory

- **Left toolbar** (`BIMViewer.tsx:1449-1508`): Zoom-to-fit, ISO / Top / Front / Side views, Zoom-to-selection, Wireframe (W), Grid (G), Bounding-boxes (B).
- **Selection toolbar** (`BIMViewer.tsx:1537-1565`, dynamic): multi-select info, Hide (H), Isolate (I), Clear (Esc).
- **Context menu** (`BIMContextMenu.tsx:183-283`): zoom-to-element, copy properties, add-to-BOQ, create quantity rule, link to document / activity / task, isolate, hide, color-by-category, show in filter panel, show similar.
- **Right panel** — `BIMFilterPanel.tsx`: search, storey / type filters, group-by, smart chips, save-as-group, Link-to-BOQ (just fixed in v1.9.0 #18).
- **Three.js primitives already available** (`SceneManager.ts`): OrbitControls with damping, grid helper, on-demand rendering, camera presets, BoxHelper (L241), dark-mode background.

### Industry features we don't have

| Feature | Estimator value | Complexity |
|---------|-----------------|------------|
| Section box (3-plane clipping) | Medium | High (shaders + UI) |
| Exploded view | Low | Medium |
| Walk-through FPS | Low | Low |
| Measure tool (distance 3D) | **High** | Medium |
| Markup / pin comments | Medium | High (storage + screenshots) |
| Saved views / bookmarks | **High** | **Low** |
| Layer / phase filter (beyond category) | Medium (high for 4D) | Medium |
| Ghosting non-selection | Medium | Low |
| Element-properties diff | Low | Low |
| Clash detection | High for coordination | High |
| Bounding box of selection | Medium | **Low** (THREE.BoxHelper) |
| Transparency slider per category | **Medium** | **Low** |
| Element-count sidebar | Medium | Low |
| Units toggle (mm / m / ft) | Low | Low |

## 2. Options considered

### Option A — Ship a small number of high-ROI features (recommended)

Four features chosen by value × complexity: saved views, per-category transparency, bounding-box outline on selection, measure-distance tool.

### Option B — Full parity with Navisworks

Section box, clash detection, markup, 4D phasing, walk-through. Large effort; scope creep; not aligned with "lightweight" philosophy.

### Option C — Only reorganise existing controls

Consolidate toolbar, move color-by to context menu, add tabs to right panel. No new behaviour.

## 3. Decision

**Option A** — four high-ROI features plus a small right-panel reorganisation (Option C piggy-backed for free).

### Selected features for v1.9.1

1. **Saved views / camera bookmarks.** `camera.position` + `controls.target` + active filter set → stored in `localStorage["bim_views_{modelId}"]` for v1.9.1; migrate to backend table in a later round if users share views across machines.
2. **Per-category transparency slider.** Category list with a 0–100% opacity slider per row; applied via material opacity in `ElementManager`.
3. **Bounding-box outline on selection.** `THREE.BoxHelper` attached in `SelectionManager.selectElement`, disposed in `deselectElement`. Dashed white outline.
4. **Measure tool — distance v1.** Click two 3D points → line + distance label. Uses existing raycaster; no shaders. Area / angle deferred to v1.9.2.

### Right-panel redesign (free)

Replace current single-purpose right panel with 4 tabs:
- Properties (existing, default)
- Layers (new — categories + transparency sliders + hide toggles)
- Tools (new — measure + saved views)
- Groups (existing saved groups surface)

## 4. Implementation sketch

### 4.1 Saved views

New file `frontend/src/shared/ui/BIMViewer/SavedViewsStore.ts`:
```ts
type Viewpoint = { id: string; name: string; cameraPos: [number, number, number]; target: [number, number, number]; filterState?: BIMFilterState; createdAt: string };
const key = (modelId: string) => `oe_bim_views_${modelId}`;
```

UI lives in the new "Tools" tab, list + add/load/delete buttons. Keyboard shortcut `S` toggles the tab.

### 4.2 Per-category transparency

`ElementManager.setCategoryOpacity(category: string, opacity: number)` — clones the base material if the category doesn't have its own, then sets `material.opacity` and `material.transparent`. Store a `categoryOpacity: Record<string, number>` in a new Zustand store so it survives re-renders.

### 4.3 Bounding-box outline

In `SelectionManager`:
```ts
selectElement(handle: ElementHandle) {
  // existing highlight logic ...
  if (this.boxHelper) scene.remove(this.boxHelper);
  this.boxHelper = new THREE.BoxHelper(handle.mesh, 0xffffff);
  (this.boxHelper.material as THREE.LineBasicMaterial).transparent = true;
  (this.boxHelper.material as THREE.LineBasicMaterial).opacity = 0.8;
  scene.add(this.boxHelper);
}
deselectElement() {
  if (this.boxHelper) { scene.remove(this.boxHelper); this.boxHelper.geometry.dispose(); this.boxHelper = null; }
}
```

### 4.4 Measure tool (distance)

New file `frontend/src/shared/ui/BIMViewer/MeasureManager.ts`:
- State: `'idle' | 'awaiting-first' | 'awaiting-second' | 'done'`
- On canvas click while tool active → raycast → world point → push into `points: THREE.Vector3[]`
- When 2 points collected → draw `THREE.Line` + overlay label with `points[0].distanceTo(points[1]).toFixed(2)` m
- Measurement persists in a list inside the "Tools" tab until cleared
- `Escape` cancels active measurement; `M` toggles the tool

### 4.5 Toolbar + panel reshuffle

`BIMPage.tsx` — change right-panel from single component to tab container. `Properties` component unchanged. `Layers` + `Tools` new.

## 5. Testing plan

**Unit** (`BIMViewer/__tests__/`):
- `SavedViewsStore.add` / `remove` / `get` under localStorage quota
- `MeasureManager` state transitions on clicks + escape
- `ElementManager.setCategoryOpacity` doesn't leak materials on repeated calls

**E2E** (`frontend/e2e/v1.9/19-bim-viewer-controls.spec.ts`):
- Save a view, navigate away, return, click the view → camera fits expected bbox
- Slide "Walls" to 30% → selected wall still interactive but visually faded
- Select element → white bbox overlay visible
- Measure mode: click two element corners → distance label renders with m unit

**Visual regression:** screenshots of the right-panel tabs; bounding-box outline on a selected element.

**Performance:** on a 5 000-element model, dragging transparency slider keeps 30+ fps (on-demand rendering helps — `SceneManager:121-126`).

## 6. Risks / follow-ups

- **localStorage quota.** Saved views are lightweight (~200 B each), but cap at 100 per model and warn thereafter; backend migration tracked as R3.
- **Material leak.** `setCategoryOpacity` must dispose cloned materials on model unload. Add to `ElementManager.dispose()`.
- **Measure precision.** Raycasting against instanced meshes can snap to triangle centroids, not edges. Good enough for rough quantity verification; edge snapping is a R4 polish.
- **Toolbar reshuffle UX.** Existing users trained on current panel. Ship a one-time tooltip ("We moved filters into the Layers tab") on first v1.9.1 load.
