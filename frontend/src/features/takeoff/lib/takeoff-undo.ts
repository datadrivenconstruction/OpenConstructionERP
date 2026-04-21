/**
 * Pure undo/redo reducer for measurement operations.
 *
 * Split out from TakeoffViewerModule so the reversal logic can be unit
 * tested without mounting React.  The reducer takes a snapshot of the
 * surfaces the viewer mutates (measurements + active points) and returns
 * the next snapshot after applying / reversing an operation.
 */

import type { Measurement, Point, UndoOperation } from './takeoff-types';

export interface TakeoffState {
  measurements: Measurement[];
  activePoints: Point[];
}

/**
 * Reverse a single operation — used by Undo.  Pure: does NOT mutate the
 * input state; returns a fresh object.
 */
export function reverseOperation(
  state: TakeoffState,
  op: UndoOperation,
): TakeoffState {
  switch (op.kind) {
    case 'add_point':
      return {
        ...state,
        activePoints: state.activePoints.slice(0, -1),
      };

    case 'complete_measurement':
      return {
        measurements: state.measurements.filter(
          (m) => m.id !== op.measurement.id,
        ),
        activePoints: [...op.previousActivePoints],
      };

    case 'add_count_point':
      if (op.wasNew) {
        return {
          ...state,
          measurements: state.measurements.filter(
            (m) => m.id !== op.measurementId,
          ),
        };
      }
      return {
        ...state,
        measurements: state.measurements.map((m) =>
          m.id === op.measurementId && op.previousMeasurement
            ? { ...op.previousMeasurement }
            : m,
        ),
      };

    case 'delete_measurement':
      return {
        ...state,
        measurements: [...state.measurements, op.measurement],
      };

    case 'change_annotation':
      return {
        ...state,
        measurements: state.measurements.map((m) =>
          m.id === op.measurementId
            ? { ...m, annotation: op.previousAnnotation }
            : m,
        ),
      };
  }
}

/**
 * Re-apply a single operation — used by Redo.  Takes the operation that
 * was previously reversed and produces the state AFTER the operation
 * took effect.  Pure.
 *
 * For most ops we can invert the reverse; for `change_annotation` we
 * can't know the "new" annotation from just the previous one, so the
 * caller (React side) should capture the forward delta at the moment of
 * reversal and feed it through a dedicated path.  Here we at least
 * handle the common geometric ops needed by the redo stack.
 */
export function applyOperation(
  state: TakeoffState,
  op: UndoOperation,
): TakeoffState {
  switch (op.kind) {
    case 'add_point':
      return {
        ...state,
        activePoints: [...state.activePoints, op.point],
      };

    case 'complete_measurement':
      return {
        measurements: [...state.measurements, op.measurement],
        activePoints: [],
      };

    case 'add_count_point':
      if (op.wasNew) {
        // Reconstruct the count measurement from the previous snapshot if we
        // have one, or fall back to a minimal singleton.
        const base = op.previousMeasurement ?? {
          id: op.measurementId,
          type: 'count' as const,
          points: [] as Point[],
          value: 0,
          unit: 'pcs',
          label: '',
          annotation: '',
          page: 1,
          group: 'General',
        };
        const restored: Measurement = {
          ...base,
          id: op.measurementId,
          points: [...base.points, op.point],
          value: base.points.length + 1,
        };
        return {
          ...state,
          measurements: [...state.measurements, restored],
        };
      }
      // Existing count measurement — append the point back.
      return {
        ...state,
        measurements: state.measurements.map((m) =>
          m.id === op.measurementId
            ? {
                ...m,
                points: [...m.points, op.point],
                value: m.points.length + 1,
              }
            : m,
        ),
      };

    case 'delete_measurement':
      return {
        ...state,
        measurements: state.measurements.filter(
          (m) => m.id !== op.measurement.id,
        ),
      };

    case 'change_annotation':
      // Without a "newAnnotation" field we can't deterministically redo
      // this op from the typed payload alone.  The React layer handles
      // annotation redo by pushing a synthetic op onto the undo stack
      // and clearing redo — so this branch should rarely fire in
      // practice.  We leave the state unchanged as a safe default.
      return state;
  }
}
