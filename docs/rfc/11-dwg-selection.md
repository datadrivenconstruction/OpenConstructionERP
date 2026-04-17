# RFC 11 — DWG polyline / layer selection rework

**Status:** draft
**Related items:** ROADMAP_v1.9.md #11 (R2 → v1.9.1)
**Date:** 2026-04-17

## 1. Context

At `/dwg-takeoff`, the user reports three painful limitations when working with DXF drawings:

1. **"Outer polyline always wins."** Clicking anywhere inside a nested structure picks the largest enclosing polyline, not the inner element.
2. **No per-entity hide.** User can't say "hide this one line" — only layer-level visibility is available.
3. **No multi-select / no group-to-BOQ link.** Selection is always one entity; no way to pick a set of entities, see their combined area / perimeter / length, and link the group to a BOQ position (this capability exists in the BIM viewer — `BIMFilterPanel.tsx` has Save-as-Group and Link-to-BOQ).

### Current implementation

**Hit-testing** — `frontend/src/features/dwg-takeoff/components/DxfViewer.tsx:431-520`

Brute-force linear iteration with first-wins tie-break:

```tsx
for (const ent of entities) {                     // L437
  if (!visibleLayers.has(ent.layer)) continue;    // L438
  const d = closestDistance(click, ent);
  if (closed && pointInPolygon(click, ent)) d = 0; // L454-456
  if (d < closestDist) {                          // L512 — first-wins
    closestDist = d;
    closest = ent.id;
  }
}
```

Tolerance is fixed at `10 / vpRef.current.scale` (L435). The outer-polyline bias is structural: closed polylines get `d = 0` via `pointInPolygon`, and iteration order determines which `d = 0` wins — outer ones often come first.

**Layers** — `DwgTakeoffPage.tsx:282` — `visibleLayers: Set<string>` (local React state; layer metadata from `/v1/dwg_takeoff/drawings/{id}/entities/`). Layer-level hide works.

**Selection state** — `DwgTakeoffPage.tsx:284-285` — single-select only (`selectedEntityId: string | null`).

**Measurement primitives** — `lib/measurement.ts` — `calculateDistance`, `calculatePerimeter`, `calculateArea` all exist and are used for per-entity overlays in `DxfViewer.tsx:873-1045`. They can be composed for group aggregation with no new math.

**Per-entity hide** — does not exist. Only layer-level.

**Group-to-BOQ link** — does not exist for DWG. Single-entity linking does: `DwgTakeoffPage.tsx:642-770` (`handleOpenLinkToBoq`, `ensureAnnotationForEntity`). BIM reference: `BIMFilterPanel.tsx` quick-takeoff and save-as-group flows.

## 2. Options considered

### Option A — Modifier-key multi-select (familiar CAD pattern)

Shift+Click adds to selection; Ctrl+Click toggles; Escape clears. Right-click opens a context menu with Hide / Link to BOQ / Save Group.

- **Pros:** matches Revit / AutoCAD / Rhino convention; no picker redesign; backward-compatible single-click behaviour.
- **Cons:** does not on its own solve the outer-polyline bias — still picks "closest," just picks it multiple times.

### Option B — Area / proximity ranking in hit-test (fixes outer-polyline bias)

Replace first-wins with a ranked score:
```
score = 0.5 · normalizedDistance  +  0.5 · (isInside ? 0 : 1)
       − 0.1 · log(area + 1) · (isInside ? 1 : 0)
```
Smaller polylines that contain the click outrank larger enclosing polylines. Repeated clicks at the same spot cycle through ranked candidates.

- **Pros:** solves the root cause at the algorithm level; no UX learning required; works equally well for single and multi-select.
- **Cons:** area computation is O(n vertices) per candidate → cache per-entity area at load time. Cycle-through needs a small last-click-position buffer (300 ms timeout).

### Option C — Two-step "layer first, then entity"

Selecting a layer isolates it; subsequent clicks only pick entities on the active layer.

- **Pros:** mirrors BIM's "storey → element" pattern; great when drawings are organised by layer.
- **Cons:** brittle for messy DWGs where one logical shape is split across layers; changes selection mental model.

## 3. Decision

**Option B (area/proximity ranking) as the primary hit-test change, with Option A (modifier keys) layered on top for true multi-select.**

Option C is rejected: it only helps clean drawings and forces an extra click for the common case.

### Rationale

- B is the only option that actually fixes the reported bug ("outer polyline always wins"). Modifier keys alone do not.
- A is cheap to add once B is in place and unblocks the group aggregation + link-to-BOQ features the user asked for.
- Together they are still a single-commit scope for R2 — selection rework is cohesive.

## 4. Implementation sketch

### 4.1 Cache entity areas at load time

`DwgTakeoffPage.tsx` entity load / `lib/measurement.ts`:
```ts
// On entities fetched, annotate each closed polyline with precomputed area.
const annotatedEntities = useMemo(
  () => entities.map((e) =>
    e.type === 'LWPOLYLINE' && e.closed
      ? { ...e, _area: calculateArea(e.vertices) }
      : e,
  ),
  [entities],
);
```

### 4.2 Ranked hit-test

`DxfViewer.tsx:handleMouseDown` (around L517):
```ts
type HitCandidate = { id: string; distance: number; inside: boolean; area: number };
const candidates: HitCandidate[] = [];

for (const ent of entities) {
  if (!visibleLayers.has(ent.layer)) continue;
  const d = closestDistance(click, ent);
  if (d > tolerance && !(closed(ent) && pointInPolygon(click, ent))) continue;
  candidates.push({
    id: ent.id,
    distance: d / tolerance,
    inside: closed(ent) && pointInPolygon(click, ent),
    area: (ent as { _area?: number })._area ?? Number.POSITIVE_INFINITY,
  });
}
candidates.sort((a, b) =>
  scoreOf(a) - scoreOf(b),
);

function scoreOf(c: HitCandidate): number {
  return 0.5 * Math.min(c.distance, 1)
       + 0.5 * (c.inside ? 0 : 1)
       - (c.inside ? 0.1 * Math.log((c.area || 1) + 1) : 0);
}
```

Cycle-through: remember `lastHit = { x, y, index, ts }`. If next click is within 6 px and ts + 300 ms, advance `index`; otherwise reset.

### 4.3 Multi-select state

`DwgTakeoffPage.tsx`:
```ts
const [selectedEntityIds, setSelectedEntityIds] = useState<Set<string>>(new Set());
// Single-select remains: a one-item Set. No props-shape change — refactor in one go.
```

`handleSelectEntity(id, event)`:
- `event.shiftKey` → toggle `id` in set
- otherwise → replace set with `{ id }`
- `Escape` → clear set

### 4.4 Per-entity hide (right-click menu)

Add `hiddenEntityIds: Set<string>` state, filter it out in both hit-test and renderer. Context menu with "Hide" (one entity) and "Isolate" (hide everything else).

### 4.5 Group aggregation UI

New right-panel sub-section when `selectedEntityIds.size > 1`:
- Σ perimeter (sum over closed polylines and polylines)
- Σ area (sum over closed polylines only)
- Σ length (sum over line / polyline segments for open shapes)
- Entity count by type

### 4.6 Group-to-BOQ link

Reuses the existing single-entity pipeline:
1. **Backend:** new endpoint `POST /v1/dwg_takeoff/groups/` storing `{ drawing_id, entity_ids: string[], name, metadata }` → returns `group_id`.
2. **Backend:** extend existing link-position logic to accept `dwg_group_id` in position metadata alongside `dwg_entity_id`.
3. **Frontend:** "Link N to BOQ" button in the group sub-section opens the same position picker already used for single entities (`handleOpenLinkToBoq`).
4. Aggregate quantity auto-filled from group's Σ area / Σ perimeter depending on BOQ position unit.

## 5. Testing plan

**Unit** (`frontend/src/features/dwg-takeoff/__tests__/hit-test.test.ts`):
- Nested polylines: inner selected over outer (both contain click)
- Ranked ordering stable for same input
- Cycle-through advances after repeated clicks within time / distance window, resets after
- Multi-select Set semantics under shift / ctrl modifiers

**E2E** (`frontend/e2e/v1.9/11-dwg-selection.spec.ts`):
- Inner polyline selection after click at centroid of two nested closed polys
- Shift+Click adds second entity to selection
- Group panel shows summed perimeter + area
- Link group to BOQ → position metadata carries `dwg_group_id`
- Hide single entity, verify no longer hit-testable and not rendered

**Visual regression:**
- Selected-group halo rendering
- Group aggregation panel screenshot

**Performance budget:**
- Hit-test on 10 000-entity drawing stays under 50 ms (cached areas)
- Render unaffected (selection overlay is additive)

## 6. Risks / follow-ups

- **No spatial index.** Brute-force scan is O(n). For DXFs > 50 k entities this becomes sluggish. Not in scope for v1.9.1 — add RBush index only if profiler flags it. Tracked as R3+.
- **Shift-key discoverability.** Add inline tooltip "Shift-click to add to selection" on the first multi-select attempt per session.
- **Backend `dwg_groups` persistence.** Decision: separate table rather than JSON blob in position metadata — supports future features (group rename, group audit log).
- **Annotation-of-group vs annotations-of-entities.** Current text pins attach to one entity. A group link creates a single centroid annotation referencing the `dwg_group_id`, not per-entity pins. Keeps the drawing visually clean.
