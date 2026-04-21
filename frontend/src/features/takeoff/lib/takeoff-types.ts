/**
 * Shared takeoff types — kept here (not in the module) so lib helpers and
 * tests can import without pulling the whole TakeoffViewerModule graph.
 *
 * Mirrors the types defined in
 * `frontend/src/modules/pdf-takeoff/TakeoffViewerModule.tsx`.
 */

export type MeasureTool =
  | 'select'
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
  depth?: number;
  area?: number;
  text?: string;
  color?: string;
  width?: number;
  height?: number;
  /** Free-form notes entered via the properties panel. */
  notes?: string;
  serverId?: string;
  linkedPositionId?: string;
  linkedPositionOrdinal?: string;
  linkedBoqId?: string;
  linkedPositionLabel?: string;
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
