/**
 * Linear undo/redo stack for DWG takeoff annotation mutations.
 *
 * Each entry captures enough information to reverse the mutation:
 *   - ``create`` → undo deletes the persisted annotation
 *   - ``delete`` → undo re-creates from the captured snapshot
 *   - ``edit``   → undo patches back to ``before``; redo applies ``after``
 *
 * Kept framework-agnostic (plain TS) so the reducer is trivially testable.
 * Execution of each undo/redo entry is delegated to the caller via the
 * handler object it passes to ``apply``. The reducer itself only tracks
 * the entries and cursors.
 *
 * Standard linear behaviour: pushing a new entry after undoing wipes the
 * redo tail — but see task note: we are told standard linear-undo is
 * fine. We DO wipe redo on new pushes (that's standard), but we don't
 * wipe redo when branching is what the user wants to preserve.
 *
 * Capacity is bounded to ``MAX_STACK`` (50 by spec); oldest entries drop
 * off the tail when we exceed it.
 */

import type { DwgAnnotation } from '../api';

export const MAX_STACK = 50;

/** Minimal snapshot used to rehydrate a deleted annotation. Mirrors the
 *  fields the create endpoint accepts. */
export interface AnnotationSnapshot {
  id: string;
  annotation_type: DwgAnnotation['type'];
  points: { x: number; y: number }[];
  text: string | null;
  color: string;
  measurement_value: number | null;
  measurement_unit: string | null;
  layer_name: string | null | undefined;
  thickness?: number;
  line_width?: number;
  scale_override?: number | null;
  metadata?: Record<string, unknown>;
}

export type UndoEntry =
  | { kind: 'create'; id: string; snapshot: AnnotationSnapshot }
  | { kind: 'delete'; snapshot: AnnotationSnapshot }
  | {
      kind: 'edit';
      id: string;
      before: Partial<AnnotationSnapshot>;
      after: Partial<AnnotationSnapshot>;
    };

export interface UndoState {
  undo: UndoEntry[];
  redo: UndoEntry[];
}

export function emptyUndoState(): UndoState {
  return { undo: [], redo: [] };
}

/** Push a new entry onto the undo stack. Standard linear behaviour:
 *  pushing clears the redo tail. The undo stack is capped at
 *  ``MAX_STACK`` — oldest entries drop. */
export function pushUndo(state: UndoState, entry: UndoEntry): UndoState {
  const nextUndo = [...state.undo, entry];
  while (nextUndo.length > MAX_STACK) {
    nextUndo.shift();
  }
  return { undo: nextUndo, redo: [] };
}

/** Move the top undo entry onto the redo stack. Returns the new state
 *  plus the moved entry so the caller can execute the inverse mutation. */
export function popUndo(state: UndoState): {
  state: UndoState;
  entry: UndoEntry | null;
} {
  if (state.undo.length === 0) return { state, entry: null };
  const entry = state.undo[state.undo.length - 1]!;
  const nextUndo = state.undo.slice(0, -1);
  const nextRedo = [...state.redo, entry];
  // Redo stack is similarly bounded — a long undo run shouldn't grow
  // the redo list beyond MAX_STACK either.
  while (nextRedo.length > MAX_STACK) {
    nextRedo.shift();
  }
  return { state: { undo: nextUndo, redo: nextRedo }, entry };
}

/** Move the top redo entry back onto the undo stack. Returns the new
 *  state plus the moved entry so the caller can replay the mutation. */
export function popRedo(state: UndoState): {
  state: UndoState;
  entry: UndoEntry | null;
} {
  if (state.redo.length === 0) return { state, entry: null };
  const entry = state.redo[state.redo.length - 1]!;
  const nextRedo = state.redo.slice(0, -1);
  const nextUndo = [...state.undo, entry];
  while (nextUndo.length > MAX_STACK) {
    nextUndo.shift();
  }
  return { state: { undo: nextUndo, redo: nextRedo }, entry };
}

/** Convenience predicates for wiring toolbar button ``disabled`` state. */
export function canUndo(state: UndoState): boolean {
  return state.undo.length > 0;
}

export function canRedo(state: UndoState): boolean {
  return state.redo.length > 0;
}

/** Build a snapshot from a live annotation so it can be replayed later.
 *
 *  Callers feed two subtly different shapes in: the viewer-side
 *  ``DwgAnnotation`` (``type`` / ``points``) from locally-constructed
 *  annotations, and the raw backend response (``annotation_type`` /
 *  ``geometry.points``) which arrives via the create-annotation mutation's
 *  ``onSuccess`` handler. Treating one shape as the other blew up the undo
 *  stack with ``Cannot read properties of undefined (reading 'map')`` on
 *  every successful mutation — and because the crash happens inside a
 *  ``setUndoState`` callback on render, ANY subsequent re-render (e.g.
 *  clicking Snap, switching tools) re-entered the same state update and
 *  re-threw, making every tool appear to crash.
 *
 *  We now read both shapes and normalise, so the snapshot survives
 *  regardless of which field naming the input uses. Kept defensive about
 *  ``points`` being missing entirely (legacy rows / truncated responses) —
 *  we fall back to an empty array rather than crashing, since an empty
 *  snapshot is still a valid undo-placeholder. */
export function snapshotFrom(
  ann: DwgAnnotation | BackendAnnotationResponse,
): AnnotationSnapshot {
  const a = ann as DwgAnnotation & BackendAnnotationResponse;
  const type = a.type ?? a.annotation_type;
  const rawPoints = a.points ?? a.geometry?.points ?? [];
  return {
    id: a.id,
    annotation_type: type,
    points: rawPoints.map((p) => ({ x: p.x, y: p.y })),
    text: a.text,
    color: a.color,
    measurement_value: a.measurement_value,
    measurement_unit: a.measurement_unit,
    layer_name: a.layer_name ?? null,
    thickness: a.thickness,
    line_width: a.line_width,
    scale_override: a.scale_override ?? null,
    metadata: a.metadata,
  };
}

/** Shape of the raw create/update response from the backend. We only model
 *  the fields ``snapshotFrom`` consumes — the rest come through unchanged
 *  and are typed as ``DwgAnnotation`` elsewhere (a known-broken contract
 *  tracked separately; ``snapshotFrom`` here is the crash-path fix). */
interface BackendAnnotationResponse {
  id: string;
  annotation_type?: DwgAnnotation['type'];
  geometry?: { points?: { x: number; y: number }[] };
  text?: string | null;
  color?: string;
  measurement_value?: number | null;
  measurement_unit?: string | null;
  layer_name?: string | null;
  thickness?: number;
  line_width?: number;
  scale_override?: number | null;
  metadata?: Record<string, unknown>;
}
