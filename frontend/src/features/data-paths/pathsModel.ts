// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pure model of the three data path views: the module diagram geometry, the
// trace of one parameter, and the platform map columns by project phase.
// Everything here reads the API payload; nothing is invented.

import type { MapModule, ModulePaths, ParamOut, PathOut, PlatformMap, StaleOut } from './api';

// ── Module diagram geometry ───────────────────────────────────────────────

export const SIDE_CARD_H = 104;
export const SIDE_GAP = 16;
export const MIN_CARD_W = 220;
export const MIN_LINK_W = 120;

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Link {
  path: PathOut;
  card: Box;
  /** Where the curve leaves the centre card. */
  anchor: { x: number; y: number };
  /** Where the label pill sits, on the card's own row so labels never collide. */
  pill: { x: number; y: number };
  d: string;
}

export interface Diagram {
  /** False when the width cannot hold three columns; the view stacks instead. */
  wide: boolean;
  height: number;
  centre: Box;
  links: Link[];
}

function column(n: number): number {
  return n ? n * SIDE_CARD_H + (n - 1) * SIDE_GAP : 0;
}

/** Geometry for sources left, the module centre, consumers right. */
export function layoutDiagram(width: number, centreH: number, paths: PathOut[]): Diagram {
  const ins = paths.filter((p) => p.direction === 'in');
  const outs = paths.filter((p) => p.direction === 'out');
  const linkW = Math.min(180, Math.max(MIN_LINK_W, width * 0.14));
  const cardW = (width - 2 * linkW) / 3;
  const wide = cardW >= MIN_CARD_W;
  const height = Math.max(column(ins.length), column(outs.length), centreH);
  const centre: Box = { x: cardW + linkW, y: (height - centreH) / 2, w: cardW, h: centreH };
  if (!wide) return { wide, height: 0, centre, links: [] };

  const place = (list: PathOut[], side: 'in' | 'out'): Link[] => {
    const top = (height - column(list.length)) / 2;
    return list.map((path, i) => {
      const card: Box = { x: side === 'in' ? 0 : centre.x + cardW + linkW, y: top + i * (SIDE_CARD_H + SIDE_GAP), w: cardW, h: SIDE_CARD_H };
      const cy = card.y + SIDE_CARD_H / 2;
      const ay = centre.y + ((i + 1) / (list.length + 1)) * centreH;
      const ax = side === 'in' ? centre.x : centre.x + cardW;
      const cardEdge = side === 'in' ? card.x + cardW : card.x;
      // The pill sits a third of the gap from the card; the curve bends between pill and centre.
      const px = side === 'in' ? cardEdge + linkW * 0.38 : cardEdge - linkW * 0.38;
      const mx = (px + ax) / 2;
      const d = `M ${cardEdge} ${cy} L ${px} ${cy} C ${mx} ${cy}, ${mx} ${ay}, ${ax} ${ay}`;
      return { path, card, anchor: { x: ax, y: ay }, pill: { x: px, y: cy }, d };
    });
  };
  return { wide, height, centre, links: [...place(ins, 'in'), ...place(outs, 'out')] };
}

// ── Selected path detail ──────────────────────────────────────────────────

export interface DrivingField {
  field: string;
  label: string;
  drives: string[];
}

function touches(ref: string, path: PathOut): boolean {
  return ref.startsWith(`${path.module}:`) || ref.split('.')[0] === path.entity;
}

/** Parameters that drive numbers on this path, with only the targets on it. */
export function drivingFields(data: ModulePaths, path: PathOut): DrivingField[] {
  return data.parameters
    .filter((p) => p.drives_paths.includes(path.id))
    .map((p) => {
      const own = p.drives.filter((d) => touches(d, path));
      return { field: p.field, label: p.label, drives: own.length ? own : p.drives };
    });
}

export function freshnessOf(data: ModulePaths, path: PathOut): StaleOut[] {
  return data.stale.filter((s) => s.path_id === path.id);
}

// ── Field trace ───────────────────────────────────────────────────────────

export interface TraceConsumer {
  module: string;
  path: PathOut | null;
  refs: string[];
}

export interface FieldTrace {
  param: ParamOut;
  sources: PathOut[];
  derived: string[];
  consumers: TraceConsumer[];
  stale: StaleOut[];
}

/** Where one parameter comes from and what it changes, from the module's own declaration. */
export function traceField(data: ModulePaths, field: string): FieldTrace | null {
  const param = data.parameters.find((p) => p.field === field);
  if (!param) return null;
  const hit = data.paths.filter((p) => param.drives_paths.includes(p.id));
  const sources = hit.filter((p) => p.direction === 'in');
  const outs = hit.filter((p) => p.direction === 'out');
  const ownModels = new Set(data.entities.map((e) => e.model));
  const derived = param.drives.filter((d) => !d.includes(':') && ownModels.has(d.split('.')[0] ?? ''));
  const consumers: TraceConsumer[] = outs.map((path) => ({ module: path.module, path, refs: param.drives.filter((d) => touches(d, path)) }));
  // A derived concept in a module with no declared path still names its consumer.
  for (const ref of param.drives) {
    const mod = ref.includes(':') ? ref.split(':')[0] ?? '' : '';
    if (mod && !consumers.some((c) => c.module === mod)) consumers.push({ module: mod, path: null, refs: [ref] });
  }
  const ids = new Set(hit.map((p) => p.id));
  const stale = data.stale.filter((s) => s.path_id !== null && ids.has(s.path_id));
  return { param, sources, derived, consumers, stale };
}

// ── Platform map by phase ─────────────────────────────────────────────────

export type Relation = 'focus' | 'in' | 'out' | null;

export interface PhaseColumn {
  phase: string;
  modules: { module: MapModule; relation: Relation }[];
}

/** Declared modules in the map's phase order; `in` = the focus reads from it, `out` = it reads from the focus. */
export function phaseColumns(map: PlatformMap, focus: string | null, label: (m: MapModule) => string): PhaseColumn[] {
  const rel = new Map<string, Relation>();
  if (focus) {
    for (const e of map.edges) {
      if (e.kind !== 'declared') continue;
      if (e.target === focus && e.source !== focus) rel.set(e.source, 'in');
      if (e.source === focus && e.target !== focus && rel.get(e.target) !== 'in') rel.set(e.target, 'out');
    }
    rel.set(focus, 'focus');
  }
  const order = map.phases.length ? map.phases : [...new Set(map.modules.map((m) => m.phase))];
  return order
    .map((phase) => ({
      phase,
      modules: map.modules
        .filter((m) => m.declared && m.phase === phase)
        .sort((a, b) => label(a).localeCompare(label(b)))
        .map((module) => ({ module, relation: rel.get(module.name) ?? null })),
    }))
    .filter((c) => c.modules.length > 0);
}
