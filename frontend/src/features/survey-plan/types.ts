// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Public contract of the plan canvas. Packages that add layers, tools and
 * screens build on these types only; everything else in the folder is an
 * implementation detail. All geometry is project grid [E, N] (or [E, N, Z])
 * in metres. Map coordinates never leave the canvas.
 */

import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import type { FeatureCollection } from 'geojson';
import type { PlanConventions } from './units/conventions';

// ── Geometry ──────────────────────────────────────────────────────────────

/** [E, N] in metres on the project grid. */
export type GridXY = [number, number];
/** [E, N] or [E, N, Z]. */
export type GridXYZ = [number, number] | [number, number, number];

export type PlanGeometry =
  | { type: 'Point'; coordinates: GridXYZ }
  | { type: 'LineString'; coordinates: GridXYZ[] }
  /** Rings are closed implicitly: the last vertex is not repeated. */
  | { type: 'Polygon'; coordinates: GridXYZ[][] };

export interface PlanFeature {
  /** Stable id, unique across layers (e.g. `point:<uuid>`, `parcel:<uuid>`, `sketch:<uuid>`). */
  id: string;
  layer: PlanLayerId;
  geometry: PlanGeometry;
  /** Free properties; `label`, `code`, `kind`, `z` are read by the default styles. */
  properties: Record<string, unknown>;
  /** Server revision the client holds; sent back as `base_rev` on save. */
  rev?: number;
  /** Entity type in the edit history (`point`, `parcel`, `work_zone`, ...). */
  entityType?: string;
  /** Server id of the record the feature stands for. */
  entityId?: string;
}

// ── Layers ────────────────────────────────────────────────────────────────

/** Fixed layer ids of the survey group. Extra layers use any other string. */
export const PLAN_LAYER_IDS = [
  'control',
  'points',
  'linework',
  'surfaces',
  'tin',
  'contours',
  'heat',
  'breaklines',
  'parcels',
  'zones',
  'pads',
  'traverse',
  'alignment',
  'sections',
  'stakes',
  'monitoring',
  'ellipses',
  'pointcloud_heat',
  'sketch',
  'measure',
] as const;
export type KnownPlanLayerId = (typeof PLAN_LAYER_IDS)[number];
export type PlanLayerId = KnownPlanLayerId | (string & {});

/** A MapLibre style layer without `source`; `id` is prefixed by the canvas. */
export interface PlanStyleLayer {
  id: string;
  type: 'circle' | 'line' | 'fill' | 'symbol' | 'fill-extrusion' | 'heatmap';
  filter?: unknown[];
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
  minzoom?: number;
  maxzoom?: number;
}

export interface LegendItem {
  /** `swatch`: filled square; `line`: stroke; `symbol`: a glyph name from cartography. */
  kind: 'swatch' | 'line' | 'symbol';
  /** A CSS colour, normally `var(--oe-map-...)`. */
  colour: string;
  labelKey: string;
  defaultLabel: string;
  dashed?: boolean;
}

export interface PlanLayerSpec {
  id: PlanLayerId;
  titleKey: string;
  defaultTitle: string;
  /** Draw order: higher is on top. Built-in layers use 10..200 in steps of 10. */
  order: number;
  /** Grid features of the layer. */
  features: PlanFeature[];
  /**
   * Style layers. Omit to get the built-in style for a known id. Colours come
   * from `planColour()` in cartography.ts (CSS variables, never hex).
   */
  style?: PlanStyleLayer[];
  /** Features already in WGS 84 (served heat maps); drawn as given, never snapped. */
  viewFeatures?: FeatureCollection;
  snappable?: boolean;
  selectable?: boolean;
  /** The edit tools may change features of this layer. */
  editable?: boolean;
  /** Hidden at start; the user can switch it on in the layer popover. */
  defaultHidden?: boolean;
  legend?: LegendItem[];
  /** Label priority for collision (higher wins): control 100, parcels 80, stakes 60, topo 40. */
  labelPriority?: number;
}

export interface LayerViewState {
  visible: boolean;
  locked: boolean;
  /** 0..1 */
  opacity: number;
}

// ── Snapping ──────────────────────────────────────────────────────────────

export type SnapKind = 'endpoint' | 'midpoint' | 'intersection' | 'perpendicular' | 'nearest' | 'grid';
export const SNAP_KINDS: SnapKind[] = ['endpoint', 'midpoint', 'intersection', 'perpendicular', 'nearest', 'grid'];
/** Earlier wins when two candidates are within the radius. */
export const SNAP_PRIORITY: SnapKind[] = ['endpoint', 'intersection', 'midpoint', 'perpendicular', 'nearest', 'grid'];

export interface SnapResult {
  kind: SnapKind;
  point: GridXY;
  /** Feature that produced the snap (absent for grid). */
  featureId?: string;
  /** Human name of the target for the tooltip and the live region, e.g. "CP2". */
  targetLabel?: string;
  /** Distance from the cursor in grid metres. */
  distance: number;
}

export interface SnapSettings {
  enabled: boolean;
  modes: Record<SnapKind, boolean>;
  /** Grid step in metres. */
  gridStep: number;
}

// ── Commands (undo/redo and save) ─────────────────────────────────────────

/** One server operation; the store batches these on Save. */
export interface EditOp {
  entity_type: string;
  entity_id: string | null;
  op: 'create' | 'update' | 'delete' | 'revert';
  base_rev: number | null;
  after: Record<string, unknown> | null;
  note?: string;
  /** Client feature id, so the response can map new server ids back. */
  client_id: string;
}

export interface PlanCommand {
  id: string;
  /** i18n key and params of the history label ("Vertex 4 added"). */
  labelKey: string;
  defaultLabel: string;
  labelParams?: Record<string, string | number>;
  apply(features: FeatureMap): FeatureMap;
  revert(features: FeatureMap): FeatureMap;
  /** Server operations of this command; empty for view-only commands. */
  toServer(): EditOp[];
  /** `suggested` when it came from a suggestion; written to the history note. */
  note?: string;
}

/** Feature id -> feature, the working set the commands operate on. */
export type FeatureMap = ReadonlyMap<string, PlanFeature>;

// ── Precision input ───────────────────────────────────────────────────────

export type InputMode = 'brg_dist' | 'delta' | 'abs' | 'polar';
export const INPUT_MODES: InputMode[] = ['brg_dist', 'delta', 'abs', 'polar'];

/** Raw text of the fields of each mode, in the order the fields render. */
export type PrecisionFields =
  | { mode: 'brg_dist'; bearing: string; distance: string }
  | { mode: 'delta'; first: string; second: string }
  | { mode: 'abs'; first: string; second: string; z?: string }
  | { mode: 'polar'; station: string; backsight: string; angle: string; distance: string };

export type PrecisionResult =
  | { ok: true; point: GridXY; z?: number }
  | { ok: false; field: string; errorKey: string; defaultError: string };

export interface PrecisionContext {
  conventions: PlanConventions;
  /** Last committed vertex of the tool, if any. */
  last: GridXY | null;
  /** Point register lookup by point id (for polar). */
  lookup: (pointId: string) => GridXY | null;
  /** Combined scale factor; typed ground distances become grid with it. */
  csf: number | null;
}

// ── Tools ─────────────────────────────────────────────────────────────────

export type ToolGroup = 'select' | 'draw' | 'measure' | 'annotate';

/** What a tool may use; handed to every handler. */
export interface ToolContext {
  conventions: PlanConventions;
  activeLayer: PlanLayerId;
  /** Snapped grid position of the pointer, or null off the map. */
  cursor: GridXY | null;
  snap: SnapResult | null;
  /** Vertices placed so far by the active tool. */
  vertices: GridXY[];
  setVertices(next: GridXY[]): void;
  /** Push an undoable command (it is applied at once). */
  commit(command: PlanCommand): void;
  /** Finish the tool's current shape and reset its vertices. */
  finish(): void;
  /** Announce text in the canvas live region. */
  announce(text: string): void;
  features: FeatureMap;
  selection: ReadonlySet<string>;
  setSelection(ids: Iterable<string>): void;
  /** Report a measurement to the inspector (and Ctrl+C). */
  setMeasure(result: MeasureResult | null): void;
  newId(prefix: string): string;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export interface PlanTool {
  id: string;
  icon: LucideIcon;
  labelKey: string;
  defaultLabel: string;
  /** Shortcut text in the shortcuts grammar: `V`, `Shift+M`, `Mod+M`. */
  shortcut?: string;
  group: ToolGroup;
  /** Drawing tools are hidden for viewers and on phones. */
  edits?: boolean;
  /** Geometry the generic draw handler collects; tools may handle input themselves instead. */
  collects?: 'point' | 'line' | 'ring' | 'arc3' | 'none';
  /** Called with the finished vertices (Enter, double-click, or the third click of an arc). */
  onFinish?(vertices: GridXY[], ctx: ToolContext): void;
  /** Click on the map (after snapping). Return true when handled, to skip the generic handler. */
  onClick?(at: GridXY, ctx: ToolContext): boolean;
  /** Live preview features drawn on the `measure` overlay while the tool runs. */
  preview?(ctx: ToolContext): PlanFeature[];
  /** Options bar extras for this tool. */
  options?(ctx: ToolContext): ReactNode;
}

export interface MeasureResult {
  kind: 'distance' | 'area' | 'angle';
  /** Grid metres, square metres or degrees. */
  value: number;
  perimeter?: number;
  /** Text copied by Ctrl+C. */
  text: string;
}

// ── View transform ────────────────────────────────────────────────────────

export interface ViewTransformDTO {
  kind: 'polynomial' | 'local';
  epsg: number | null;
  crs_name: string;
  /** Centre and scale of the normalised coordinates: u = (E - e0) / s, v = (N - n0) / s. */
  e0: number;
  n0: number;
  s: number;
  /** 6 coefficients each: c0 + c1 u + c2 v + c3 u² + c4 uv + c5 v². */
  lon: number[];
  lat: number[];
  /** Inverse, in normalised lon/lat: p = (lon - lon0) / q, r = (lat - lat0) / q. */
  lon0: number;
  lat0: number;
  q: number;
  e: number[];
  n: number[];
  residual_mm: number;
  /** Geographic azimuth of grid north at the centre: the map bearing for "grid north up". */
  grid_north_bearing: number;
  extent: [number, number, number, number] | null;
}

// ── Canvas props ──────────────────────────────────────────────────────────

export interface PlanCanvasProps {
  projectId: string;
  layers: PlanLayerSpec[];
  /** Layers from parallel work (`ellipses`, `pointcloud_heat`, `forecast`). */
  extraLayers?: PlanLayerSpec[];
  /** Tool ids to render; default: the built-ins that suit `editable`. */
  tools?: string[];
  /** Tools a package adds (alignment IP tool, section tool). */
  extraTools?: PlanTool[];
  /** False hides every editing tool (viewers). */
  editable?: boolean;
  /** Layer the draw tools write to at start. */
  activeLayer?: PlanLayerId;
  /** Show the inspector at start (desktop). */
  inspector?: boolean;
  /** Extra inspector sections of the screen (rendered under Properties). */
  inspectorSlot?: ReactNode;
  /** Controls the screen puts at the end of the options bar (export, print). */
  toolbarSlot?: ReactNode;
  /** Called when the selection changes. */
  onSelect?: (ids: string[]) => void;
  /** Called on Save with the batched operations; resolves when the server accepted them. */
  onSave?: (ops: EditOp[]) => Promise<void>;
  /** Fit to this feature at start (`focus` / `id` of `/survey/plan`). */
  focusFeatureId?: string;
  /** Height of the canvas frame; the editor page uses the full viewport. */
  heightClass?: string;
  /** Override the conventions (tests and print). */
  conventions?: Partial<PlanConventions>;
  /** Empty state when no layer has features. */
  empty?: { title: string; action?: ReactNode };
  testId?: string;
}
