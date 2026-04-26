/**
 * Drag-and-drop helpers for the EAC visual block editor canvas (EAC §3.2).
 *
 * Two responsibilities live here:
 *
 *  1. **Slot type compatibility** — the canvas must reject connections
 *     between slots whose data types are incompatible (e.g. you can't pipe
 *     a `predicate` slot into a `selector` slot). The compatibility matrix
 *     is exported as a pure function so it can be unit-tested in isolation.
 *  2. **Canvas drop translation** — convert a palette drop event coming from
 *     `@dnd-kit/core` into the canonical `{ blockKind, payload, position }`
 *     shape the store consumes. Keeping this pure means tests don't need a
 *     full DnD context.
 *
 * No React imports — keep this file framework-agnostic so future migrations
 * to a different graph library (xyflow alternatives) only touch the canvas
 * components, not the data plumbing.
 */
import type { BlockColor } from '../types';

// ── Slot data types ──────────────────────────────────────────────────────

/**
 * Logical data type travelling along a wire. Mirrors EAC §1.5 / RFC 35 §3
 * categories. Kept narrow on purpose — adding a new type requires an
 * entry in `SLOT_TYPE_COMPATIBILITY` so the matrix stays exhaustive.
 */
export type SlotDataType =
  | 'selector'    // EntitySelector — leaf or composed
  | 'predicate'   // Predicate — triplet / and / or / not
  | 'attribute'   // AttributeRef — exact / alias / regex
  | 'constraint'  // Constraint — operator + value(s)
  | 'variable'    // LocalVariableDefinition output
  | 'number'      // numeric scalar (formula input)
  | 'string'      // string literal (formula input)
  | 'boolean'     // boolean scalar
  | 'any';        // wildcard — used by formula composer

/** Slot direction relative to its parent block. */
export type SlotDirection = 'input' | 'output';

/** A single slot definition on a block node. */
export interface SlotDefinition {
  id: string;
  /** Display label shown next to the slot handle. */
  label: string;
  direction: SlotDirection;
  dataType: SlotDataType;
  /** Optional multiplicity for inputs that accept many wires (e.g. AND). */
  multi?: boolean;
}

// ── Compatibility matrix ─────────────────────────────────────────────────

/**
 * Symmetric compatibility: which output types may feed into which inputs.
 * `'any'` is a wildcard on either side.
 *
 * Rules (from EAC spec):
 *   - `predicate` outputs feed `predicate` inputs (logic composition).
 *   - `attribute` + `constraint` together build a `triplet` (handled in
 *     the store; the wire type is per-slot — attribute→attribute slot,
 *     constraint→constraint slot — never mixed across the slot pair).
 *   - `selector` outputs only feed `selector` inputs (top-level selector
 *     plus AND/OR/NOT selector composition).
 *   - `variable` outputs feed `number` / `any` inputs (formula integration).
 *   - Scalars (`number`, `string`, `boolean`) feed only their own types or
 *     `any`.
 */
export const SLOT_TYPE_COMPATIBILITY: Record<SlotDataType, ReadonlySet<SlotDataType>> = {
  selector: new Set<SlotDataType>(['selector', 'any']),
  predicate: new Set<SlotDataType>(['predicate', 'any']),
  attribute: new Set<SlotDataType>(['attribute', 'any']),
  constraint: new Set<SlotDataType>(['constraint', 'any']),
  variable: new Set<SlotDataType>(['variable', 'number', 'any']),
  number: new Set<SlotDataType>(['number', 'variable', 'any']),
  string: new Set<SlotDataType>(['string', 'any']),
  boolean: new Set<SlotDataType>(['boolean', 'any']),
  any: new Set<SlotDataType>([
    'selector',
    'predicate',
    'attribute',
    'constraint',
    'variable',
    'number',
    'string',
    'boolean',
    'any',
  ]),
};

/**
 * Return true when an output of type `source` can be wired into an input of
 * type `target`. Symmetric — but we keep argument order explicit because the
 * canvas always knows which side is the source.
 */
export function isSlotCompatible(source: SlotDataType, target: SlotDataType): boolean {
  const allowed = SLOT_TYPE_COMPATIBILITY[source];
  if (!allowed) return false;
  return allowed.has(target);
}

/**
 * Return true when a connection between two specific slot definitions is
 * allowed. Enforces directionality (output → input) and type compatibility.
 */
export function canConnectSlots(source: SlotDefinition, target: SlotDefinition): boolean {
  if (source.direction !== 'output') return false;
  if (target.direction !== 'input') return false;
  return isSlotCompatible(source.dataType, target.dataType);
}

// ── Block kind ↔ color mapping ───────────────────────────────────────────

/**
 * Maps a palette/block "kind" string to its visual color. Kept here because
 * the dnd payload uses `kind` strings directly and the store consumes them.
 */
export const BLOCK_KIND_TO_COLOR: Record<string, BlockColor> = {
  selector: 'selector',
  ifc_class: 'selector',
  category: 'selector',
  classification: 'selector',
  spatial: 'selector',
  and: 'logic',
  or: 'logic',
  not: 'logic',
  triplet: 'attribute',
  attribute: 'attribute',
  exact: 'attribute',
  alias: 'attribute',
  regex: 'attribute',
  constraint: 'constraint',
  eq: 'constraint',
  gte: 'constraint',
  between: 'constraint',
  in: 'constraint',
  matches: 'constraint',
  variable: 'variable',
};

/** Resolve a palette kind to a block color, falling back to "selector". */
export function colorForKind(kind: string): BlockColor {
  return BLOCK_KIND_TO_COLOR[kind] ?? 'selector';
}

// ── Canvas drop translation ──────────────────────────────────────────────

/** Shape produced by the drop translator and consumed by the store. */
export interface CanvasDropPayload {
  /** Block kind string, e.g. "and", "ifc_class", "triplet". */
  kind: string;
  /** Block color derived from the kind. */
  color: BlockColor;
  /** Free-form palette payload, passed through unchanged. */
  payload: Record<string, unknown>;
  /** Drop position in canvas coordinates. */
  position: { x: number; y: number };
  /** Display label used as the initial block title. */
  label: string;
}

/**
 * Build a drop payload from a palette item + drop coordinates.
 *
 * Pure — does not touch the store; callers (BlockCanvas drop handler) wire
 * the result into `useBlockCanvasStore.addBlock`.
 */
export function buildDropPayload(args: {
  paletteItemId: string;
  paletteLabel: string;
  paletteColor: BlockColor;
  paletteRawPayload?: Record<string, unknown>;
  position: { x: number; y: number };
}): CanvasDropPayload {
  const { paletteItemId, paletteLabel, paletteColor, paletteRawPayload, position } = args;
  const rawType = (paletteRawPayload?.['type'] ?? paletteRawPayload?.['kind'] ?? paletteRawPayload?.['operator']) as
    | string
    | undefined;
  const kind = rawType ?? paletteItemId.split('.').pop() ?? 'selector';
  return {
    kind,
    color: paletteColor,
    payload: paletteRawPayload ?? {},
    position,
    label: paletteLabel,
  };
}
