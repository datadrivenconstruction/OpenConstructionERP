// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Undoable commands over the working feature set. A command is data (the
 * feature before and after), so it survives a reload through sessionStorage
 * and maps one-to-one onto server edit operations.
 */

import type { EditOp, FeatureMap, GridXY, PlanCommand, PlanFeature, PlanGeometry } from '../types';

export interface Change {
  before: PlanFeature | null;
  after: PlanFeature | null;
}

/** The serialisable form of a command. */
export interface CommandData {
  id: string;
  labelKey: string;
  defaultLabel: string;
  labelParams?: Record<string, string | number>;
  changes: Change[];
  note?: string;
}

function swap(features: FeatureMap, changes: readonly Change[], forward: boolean): FeatureMap {
  const out = new Map(features);
  const list = forward ? changes : [...changes].reverse();
  for (const c of list) {
    const from = forward ? c.before : c.after;
    const to = forward ? c.after : c.before;
    if (from && (!to || to.id !== from.id)) out.delete(from.id);
    if (to) out.set(to.id, to);
  }
  return out;
}

/** Server form of a feature: geometry in grid plus its properties. */
export function featurePayload(f: PlanFeature): Record<string, unknown> {
  return { layer: f.layer, geometry: f.geometry, properties: f.properties };
}

function toOps(data: CommandData): EditOp[] {
  return data.changes.map((c): EditOp => {
    const f = (c.after ?? c.before)!;
    const op: EditOp['op'] = !c.before ? 'create' : !c.after ? 'delete' : 'update';
    return {
      entity_type: f.entityType ?? 'sketch',
      entity_id: f.entityId ?? null,
      op,
      base_rev: c.before?.rev ?? null,
      after: c.after ? featurePayload(c.after) : null,
      note: data.note,
      client_id: f.id,
    };
  });
}

export function fromData(data: CommandData): PlanCommand & { data: CommandData } {
  return {
    id: data.id,
    labelKey: data.labelKey,
    defaultLabel: data.defaultLabel,
    labelParams: data.labelParams,
    note: data.note,
    data,
    apply: (features) => swap(features, data.changes, true),
    revert: (features) => swap(features, data.changes, false),
    toServer: () => toOps(data),
  };
}

let seq = 0;
export function newId(prefix: string): string {
  seq += 1;
  const rnd = Math.random().toString(36).slice(2, 8);
  return `${prefix}:new-${Date.now().toString(36)}${seq}${rnd}`;
}

export function createFeature(f: PlanFeature, label?: Partial<CommandData>): PlanCommand & { data: CommandData } {
  return fromData({
    id: newId('cmd'),
    labelKey: 'plan.cmd.create',
    defaultLabel: 'Feature added',
    ...label,
    changes: [{ before: null, after: f }],
  });
}

export function updateFeature(before: PlanFeature, after: PlanFeature, label?: Partial<CommandData>): PlanCommand & { data: CommandData } {
  return fromData({
    id: newId('cmd'),
    labelKey: 'plan.cmd.update',
    defaultLabel: 'Feature changed',
    ...label,
    changes: [{ before, after }],
  });
}

export function deleteFeatures(features: PlanFeature[]): PlanCommand & { data: CommandData } {
  return fromData({
    id: newId('cmd'),
    labelKey: 'plan.cmd.delete',
    defaultLabel: 'Deleted',
    labelParams: { count: features.length },
    changes: features.map((f) => ({ before: f, after: null })),
  });
}

/** Many changes as one undo step (drag of several features, an applied suggestion). */
export function batch(changes: Change[], label: Omit<CommandData, 'id' | 'changes'>): PlanCommand & { data: CommandData } {
  return fromData({ id: newId('cmd'), ...label, changes });
}

// ── Vertex edits ──────────────────────────────────────────────────────────

/** Paths of a geometry as mutable arrays: [path] for a line, rings for a polygon, [[p]] for a point. */
function paths(g: PlanGeometry): GridXY[][] {
  if (g.type === 'Point') return [[[g.coordinates[0], g.coordinates[1]]]];
  if (g.type === 'LineString') return [g.coordinates.map((p) => [p[0], p[1]] as GridXY)];
  return g.coordinates.map((r) => r.map((p) => [p[0], p[1]] as GridXY));
}

function rebuild(g: PlanGeometry, ps: GridXY[][]): PlanGeometry {
  if (g.type === 'Point') {
    const z = g.coordinates[2];
    const p = ps[0]![0]!;
    return { type: 'Point', coordinates: z == null ? [p[0], p[1]] : [p[0], p[1], z] };
  }
  if (g.type === 'LineString') return { type: 'LineString', coordinates: ps[0]! };
  return { type: 'Polygon', coordinates: ps };
}

/** Locate vertex `index` (counted across rings) as [path, position]. */
function locate(ps: GridXY[][], index: number): [number, number] | null {
  let i = index;
  for (let k = 0; k < ps.length; k++) {
    if (i < ps[k]!.length) return [k, i];
    i -= ps[k]!.length;
  }
  return null;
}

export function moveVertex(f: PlanFeature, index: number, to: GridXY): PlanFeature {
  const ps = paths(f.geometry);
  const at = locate(ps, index);
  if (!at) return f;
  const ring = ps[at[0]]!;
  const closed = f.geometry.type === 'Polygon' && ring.length > 1 && same(ring[0]!, ring[ring.length - 1]!);
  ring[at[1]] = to;
  // A closed ring keeps its closing repeat on the first vertex.
  if (closed && (at[1] === 0 || at[1] === ring.length - 1)) {
    ring[0] = to;
    ring[ring.length - 1] = to;
  }
  return { ...f, geometry: rebuild(f.geometry, ps) };
}

function same(a: GridXY, b: GridXY): boolean {
  return a[0] === b[0] && a[1] === b[1];
}

/** Insert a vertex after `index`. */
export function insertVertex(f: PlanFeature, index: number, at: GridXY): PlanFeature {
  if (f.geometry.type === 'Point') return f;
  const ps = paths(f.geometry);
  const loc = locate(ps, index);
  if (!loc) return f;
  ps[loc[0]]!.splice(loc[1] + 1, 0, at);
  return { ...f, geometry: rebuild(f.geometry, ps) };
}

/** Remove a vertex; refuses when the line would drop below 2 or a ring below 3 vertices. */
export function removeVertex(f: PlanFeature, index: number): PlanFeature | null {
  if (f.geometry.type === 'Point') return null;
  const ps = paths(f.geometry);
  const loc = locate(ps, index);
  if (!loc) return null;
  const ring = ps[loc[0]]!;
  const closed = f.geometry.type === 'Polygon' && ring.length > 1 && same(ring[0]!, ring[ring.length - 1]!);
  const min = f.geometry.type === 'Polygon' ? 3 : 2;
  if (ring.length - (closed ? 1 : 0) <= min) return null;
  const pos = closed && loc[1] === ring.length - 1 ? 0 : loc[1];
  ring.splice(pos, 1);
  if (closed && pos === 0) ring[ring.length - 1] = ring[0]!;
  return { ...f, geometry: rebuild(f.geometry, ps) };
}

export function translate(f: PlanFeature, de: number, dn: number): PlanFeature {
  const ps = paths(f.geometry).map((p) => p.map(([e, n]) => [e + de, n + dn] as GridXY));
  return { ...f, geometry: rebuild(f.geometry, ps) };
}

// ── Stack ─────────────────────────────────────────────────────────────────

export const MAX_COMMANDS = 200;

export interface Stack {
  undo: CommandData[];
  redo: CommandData[];
}

export function pushCommand(stack: Stack, cmd: CommandData): Stack {
  const undo = [...stack.undo, cmd];
  return { undo: undo.length > MAX_COMMANDS ? undo.slice(undo.length - MAX_COMMANDS) : undo, redo: [] };
}

/** Net server operations of the stack: one per feature, from its first `before` to its last `after`. */
export function netOps(undo: readonly CommandData[]): EditOp[] {
  const first = new Map<string, PlanFeature | null>();
  const last = new Map<string, PlanFeature | null>();
  const notes = new Map<string, string | undefined>();
  for (const cmd of undo) {
    for (const c of cmd.changes) {
      const id = (c.after ?? c.before)!.id;
      if (!first.has(id)) first.set(id, c.before);
      last.set(id, c.after);
      if (cmd.note) notes.set(id, cmd.note);
    }
  }
  const out: EditOp[] = [];
  for (const [id, before] of first) {
    const after = last.get(id) ?? null;
    if (!before && !after) continue;
    if (before && after && JSON.stringify(featurePayload(before)) === JSON.stringify(featurePayload(after))) continue;
    out.push(...toOps({ id: 'net', labelKey: '', defaultLabel: '', changes: [{ before, after }], note: notes.get(id) }));
  }
  return out;
}
