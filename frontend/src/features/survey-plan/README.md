# survey-plan: the shared plan canvas

One canvas for every Survey & Land screen. All geometry is project grid `[E, N]` in metres;
MapLibre only draws. The public contract is `types.ts`, `units/`, `planLayers.ts`,
`cartography.ts`, the `engine/` functions and `usePlanEditStore`. Anything else may change.

## Files

| File | What it is |
|---|---|
| `types.ts` | `PlanFeature`, `PlanLayerSpec`, `PlanTool`, `ToolContext`, `PlanCommand`, `EditOp`, `SnapResult`, `PrecisionFields`, `PlanCanvasProps` |
| `units/` | Angles (dms/deg/gon), directions (azimuth, quadrant, zero north/south), axes (E/N, N/E, X/Y, Y/X), distances (m, ft, US ft), areas, chainage, grid/ground. One module, used by every package |
| `planLayers.ts` | Fixed layer ids with title, draw order, snap/select defaults; `layer()` and `mergeLayers()` |
| `cartography.ts` | `--oe-map-*` palette, built-in styles, SDF symbols, overlay styles |
| `engine/geometry.ts` | Plane geometry: distances, intersections, area, arcs, offsets |
| `engine/snap.ts`, `engine/spatialIndex.ts` | Snap engine (endpoint > intersection > midpoint > perpendicular > nearest > grid) |
| `engine/precisionInput.ts` | Keyboard input: bearing+distance, dE/dN, E/N, polar from a station |
| `engine/commands.ts` | Data commands (before/after), vertex edits, net server operations |
| `engine/viewTransform.ts` | Grid <-> view (backend polynomial or local-grid mapping), scale |
| `engine/linework.ts` | Linework from feature codes and the code library |
| `engine/liveChecks.ts` | Client checks mirroring server rules; `registerLiveCheck()` |
| `usePlanEditStore.ts` | Selection, undo/redo (200), unsaved edits in sessionStorage |
| `api.ts` | survey_core endpoints: view transform, codes, plan settings, points, sketch, edits |

## Units and conventions

Never format an angle, a coordinate, a distance, an area or a chainage by hand. Read the
conventions from the canvas (`ToolContext.conventions`, or `usePlanConventions(projectId)`) and call:

```ts
import { formatDirection, formatDistance, formatArea, formatCoordPair, formatChainage, parseDirection, parseDistance } from '@/features/survey-plan/units';

formatDirection(azimuth, conv);        // "N 45°30'00.0" E" or "50.55556 gon"
formatDistance(metres, conv);          // "25.000 m", "82.02 ft"
formatArea(m2, conv);                  // "1.2046 ha"
formatCoordPair(e, n, conv);           // "X 5 819 004.210  Y 389 012.345" under geodetic axes
formatChainage(m, conv.chainage, conv) // "1+234.568", "40+50.00", "km 1.235"
```

Internally an azimuth is degrees clockwise from grid north and a distance is grid metres. A
typed ground distance becomes grid with `groundToGrid(d, csf)` when `conv.distanceInput` is
`ground`. Defaults come from the project country (`core/country_data/survey_plan.json`); the
project can override them (`PUT survey_core/projects/{id}/plan-settings`) and a user can override
the display locally.

## Adding a layer

A screen builds its layers and passes them to the canvas. A package that only adds a layer to
someone else's screen passes it in `extraLayers`.

```tsx
import { PlanCanvas } from '@/features/survey-plan/PlanCanvas';
import { layer } from '@/features/survey-plan/planLayers';

const parcels = layer('parcels', parcelFeatures, {
  editable: canWrite,
  legend: [{ kind: 'line', colour: planColour('parcel'), labelKey: 'plan.parcel.legend', defaultLabel: 'Parcel' }],
  // Optional: own MapLibre styles (no `source`); colours from readPalette() tokens only.
  style: [{ id: 'line', type: 'line', paint: { 'line-color': palette.parcel, 'line-width': 1.5 } }],
});

<PlanCanvas projectId={pid} layers={[points, parcels]} extraLayers={[ellipsesLayer]} activeLayer="parcels" />
```

- `PlanFeature.id` must be unique across layers: prefix it with the entity (`parcel:<uuid>`).
- Set `entityType`, `entityId` and `rev` on features that map to a server record. Save sends
  `base_rev` and the server answers 409 if someone changed it meanwhile.
- A known id (`parcels`, `stakes`, ...) in `extraLayers` never replaces the screen's own layer.
- Served WGS 84 data (heat maps) goes in `viewFeatures`; it is drawn but never snapped.

## Adding a tool

```ts
import type { PlanTool } from '@/features/survey-plan/types';
import { createFeature } from '@/features/survey-plan/engine/commands';

export const ipTool: PlanTool = {
  id: 'align.ip',
  icon: Spline,
  labelKey: 'plan.align.tool_ip',
  defaultLabel: 'Alignment by IP',
  shortcut: 'Shift+L',
  group: 'draw',
  edits: true,
  collects: 'line',                       // the canvas collects clicks, snaps and precision input
  onFinish(vertices, ctx) {
    ctx.commit(createFeature({ id: ctx.newId('alignment'), layer: 'alignment', entityType: 'alignment',
      geometry: { type: 'LineString', coordinates: vertices }, properties: {} }));
  },
  preview(ctx) { return []; },            // optional live features on the overlay
};

<PlanCanvas tools={['select', 'pan', 'measure_distance']} extraTools={[ipTool]} ... />
```

- `collects`: `point`, `line`, `ring`, `arc3` get the generic handler (snap, precision input,
  Enter/double-click to finish, Esc twice to leave). `none` means the tool handles `onClick` itself.
- Every change goes through `ctx.commit(command)`, so undo, history and save work for free.
  Use `createFeature`, `updateFeature`, `deleteFeatures` or `batch` from `engine/commands.ts`.
- Tool shortcuts appear in the `?` overlay and in Ctrl+K automatically.
- Drawing tools (`edits: true`) are hidden for viewers and on phones.

## Saving

The canvas batches the net operations of the undo stack and calls `onSave(ops)`. Without
`onSave` it posts them to `POST survey_core/projects/{id}/edits`, which stores points and sketch
features and writes one `oe_survey_edit` row per record. A package with its own records saves
them itself and calls `record_edit()` (backend `survey_core/plan_service.py`) so the History tab
shows them.

## Live checks

```ts
import { registerLiveCheck } from '@/features/survey-plan/engine/liveChecks';
registerLiveCheck('parcel.ring', ({ features }) => [...]);   // returns LiveFinding[]
```

Client checks mirror the server rule of the same id; the server result on save is the record.

## Strings

`plan.*` belongs to the canvas. Packages use their own namespace: `plan.parcel.*`, `plan.tin.*`,
`plan.print.*` (P2), `plan.trav.*`, `plan.align.*`, `plan.section.*`, `plan.stake.*`, `plan.mon.*`
(P3). Add keys with `scripts/i18n.py add`, translate all locales in the same commit.
