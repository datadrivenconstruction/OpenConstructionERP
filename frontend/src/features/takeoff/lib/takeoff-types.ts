// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared takeoff types — kept here (not in the module) so lib helpers and
 * tests can import without pulling the whole TakeoffViewerModule graph.
 *
 * Mirrors the types defined in
 * `frontend/src/modules/pdf-takeoff/TakeoffViewerModule.tsx`.
 */

// Type-only, so it is erased at compile time and this file still pulls no
// runtime graph. The scale-source vocabulary is the backend's, so it is
// defined once next to the API contract rather than restated here.
import type { ScaleSource } from '../api';

export type MeasureTool =
  | 'select'
  | 'distance'
  | 'polyline'
  | 'area'
  // Measured rectangle: a 2-click area tool that produces a `type: 'area'`
  // measurement (it is a tool, never a stored measurement type).
  | 'rectarea'
  | 'volume'
  | 'count'
  | 'cloud'
  | 'arrow'
  | 'text'
  | 'rectangle'
  | 'highlight';

export type MeasurementType =
  | 'distance'
  | 'polyline'
  | 'area'
  | 'volume'
  | 'count'
  | 'cloud'
  | 'arrow'
  | 'text'
  | 'rectangle'
  | 'highlight';

export interface Point {
  x: number;
  y: number;
}

/** One opening (door, window, cut-out) deducted from a wall's gross area.
 *  Width and height are canonical metres; `count` repeats the same opening
 *  (three identical windows are one entry with count 3). */
export interface WallOpening {
  width: number;
  height: number;
  count: number;
}

export interface Measurement {
  id: string;
  type: MeasurementType;
  points: Point[];
  value: number;
  unit: string;
  label: string;
  annotation: string;
  page: number;
  group: string;
  /** This measurement's copy of its group's band, deciding where the group's
   *  block sits relative to the other groups (issues #393/#394). Mirrored onto
   *  every measurement so a pinned group order round-trips via the metadata blob
   *  like the group colour scheme, with no schema change. The map held by the
   *  viewer is authoritative; this is a cache of it, read back only when
   *  rehydrating a document. Undefined means the group was never pinned and its
   *  band is derived from first appearance. */
  groupBand?: number;
  depth?: number;
  area?: number;
  text?: string;
  color?: string;
  width?: number;
  height?: number;
  /** Per-measurement fill opacity override (issue #311, 0..1). */
  fillAlpha?: number;
  /** Per-measurement stroke width override in CSS px (issue #312). */
  strokeWidth?: number;
  /** Per-measurement STROKE (line) opacity override for LINEAR types
   *  (distance, polyline), 0..1 (issue #332). Undefined = fully opaque, so a
   *  measurement drawn before this field existed renders exactly as before. */
  strokeAlpha?: number;
  /** True-surface slope / pitch factor for an AREA measurement (roofs, ramps):
   *  true surface qty = plan area x slopeFactor (>= 1). Undefined = 1 (flat). */
  slopeFactor?: number;
  /** Material wastage / allowance percent added on top of the reported
   *  quantity (e.g. 10 = +10%). Undefined = 0 (no allowance). */
  wastagePct?: number;
  /** Typical-multiplier: this measurement stands for N identical repeats
   *  (typical floors / bays). Effective qty = base x multiplier. Undefined = 1. */
  multiplier?: number;
  /** Wall height in canonical metres for a LINEAR measurement (distance /
   *  polyline). When set (> 0) the row reports wall area: length x height,
   *  in m2. Undefined = a plain length, exactly as before. */
  wallHeight?: number;
  /** Openings deducted from the wall area (only read while `wallHeight` is
   *  set). Undefined or empty = no deduction. */
  openings?: WallOpening[];
  /** Where this row's captured scale ratio came from, as the server recorded
   *  it, or undefined when it was never recorded. Written together with the
   *  ratio it describes and never on its own, so the two always refer to the
   *  same capture. Surfaces render a missing value as "Unknown" rather than as
   *  a blank, because "we do not know" is the useful answer when a sheet turns
   *  out to be mis-scaled. */
  scaleSource?: ScaleSource;
  /** Explicit paint (z) order key (issue #379). Higher = painted later = on
   *  top; drives the canvas paint pass, the click hit-test, the sidebar list
   *  and the PDF export. Undefined = fall back to array (creation) order, so
   *  measurements the user never reordered are unchanged. Round-trips via the
   *  measurement metadata blob. */
  order?: number;
  /** Free-form notes entered via the properties panel. */
  notes?: string;
  /** Opening deduction: an `area` measurement representing a void (door,
   *  window, cut-out) whose area is subtracted from its group's gross
   *  area so net = gross - openings. Stored as a positive gross area. */
  isDeduction?: boolean;
  serverId?: string;
  linkedPositionId?: string;
  linkedPositionOrdinal?: string;
  linkedBoqId?: string;
  linkedPositionLabel?: string;
  /** AI-suggested but unconfirmed (issue #194 Recognize); never persisted
   *  until accepted (which clears the flag). */
  suggested?: boolean;
  /** Recognition confidence 0..1 on AI-sourced measurements. */
  confidence?: number;
}

/** Describes a reversible measurement operation for the undo stack. */
export type UndoOperation =
  | { kind: 'add_point'; tool: MeasureTool; point: Point }
  | {
      kind: 'complete_measurement';
      measurement: Measurement;
      previousActivePoints: Point[];
    }
  | {
      kind: 'add_count_point';
      measurementId: string;
      point: Point;
      wasNew: boolean;
      previousMeasurement: Measurement | null;
    }
  | { kind: 'delete_measurement'; measurement: Measurement }
  | {
      kind: 'change_annotation';
      measurementId: string;
      previousAnnotation: string;
    };
