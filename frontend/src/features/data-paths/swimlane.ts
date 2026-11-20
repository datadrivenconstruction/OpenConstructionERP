// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The focused-module picture as pure functions: which modules are in it
// (breadth-first, two steps back and four forward), which column and lane
// each sits in, the crossing-free order inside each cell (the same barycentre
// sweeps as the platform map), the impact rule, the paths a hover lights and
// the links a data trace walks. No React here, so all of it is unit tested.

import { orderColumns } from './layout';

export type FlowKind = 'declared' | 'depends' | 'fk' | 'event';

export interface FlowEdge {
  source: string;
  target: string;
  kind: FlowKind;
}

export const BACK = 2;
export const FORWARD = 4;

/** The five named columns, left to right; "On to the result" holds steps two to four. */
export const COLUMNS = [
  { id: 'sources', stages: [-2] },
  { id: 'supplies', stages: [-1] },
  { id: 'here', stages: [0] },
  { id: 'uses', stages: [1] },
  { id: 'result', stages: [2, 3, 4] },
] as const;

export type ColumnId = (typeof COLUMNS)[number]['id'];

export function columnOf(stage: number): ColumnId {
  if (stage <= -2) return 'sources';
  if (stage === -1) return 'supplies';
  if (stage === 0) return 'here';
  if (stage === 1) return 'uses';
  return 'result';
}

export function edgeKey(source: string, target: string): string {
  return `${source}>${target}`;
}

/**
 * Links that carry data: declared ones, record links and events. Dependencies
 * only say one module needs another, so they join only when asked for.
 */
export function flowEdges(
  edges: { source: string; target: string; kind: string }[],
  options: { technical?: boolean } = {},
): FlowEdge[] {
  const seen = new Map<string, FlowEdge>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    if (e.kind === 'depends' && !options.technical) continue;
    const key = edgeKey(e.source, e.target);
    const prev = seen.get(key);
    // One link per pair; a declared one wins over a derived one.
    if (!prev || (e.kind === 'declared' && prev.kind !== 'declared')) {
      seen.set(key, { source: e.source, target: e.target, kind: e.kind as FlowKind });
    }
  }
  return [...seen.values()];
}

function adjacency(edges: FlowEdge[]): { out: Map<string, string[]>; inc: Map<string, string[]> } {
  const out = new Map<string, string[]>();
  const inc = new Map<string, string[]>();
  for (const e of edges) {
    out.set(e.source, [...(out.get(e.source) ?? []), e.target]);
    inc.set(e.target, [...(inc.get(e.target) ?? []), e.source]);
  }
  return { out, inc };
}

function bfs(start: string, next: Map<string, string[]>, limit: number): Map<string, number> {
  const dist = new Map<string, number>([[start, 0]]);
  let frontier = [start];
  for (let d = 1; d <= limit && frontier.length; d += 1) {
    const nxt: string[] = [];
    for (const id of frontier) {
      for (const n of next.get(id) ?? []) {
        if (!dist.has(n)) {
          dist.set(n, d);
          nxt.push(n);
        }
      }
    }
    frontier = nxt;
  }
  return dist;
}

/** Stage of every module in the window: negative upstream, 0 the focus, positive downstream. */
export function stagesFrom(focus: string, edges: FlowEdge[], back = BACK, forward = FORWARD): Map<string, number> {
  const { out, inc } = adjacency(edges);
  const up = bfs(focus, inc, back);
  const down = bfs(focus, out, forward);
  const stages = new Map<string, number>([[focus, 0]]);
  for (const [id, d] of up) if (id !== focus) stages.set(id, -d);
  for (const [id, d] of down) {
    if (id === focus) continue;
    const prev = stages.get(id);
    // A module both upstream and downstream (a loop) sits where it is nearer.
    if (prev === undefined || d < -prev) stages.set(id, d);
  }
  return stages;
}

export type ImpactLevel = 'high' | 'medium' | 'endpoint';

export interface Impact {
  /** Modules downstream at any distance. */
  affected: number;
  /** Downstream modules nothing else reads: the end results. */
  results: string[];
  /** Upstream modules nothing feeds: where the chain starts. */
  roots: string[];
  /** Share of the other modules on the map this one reaches. */
  percent: number;
  level: ImpactLevel;
}

/** Rule: high when it reaches 3 or more end results or 6 or more modules; endpoint when it reaches none. */
export function impactOf(focus: string, edges: FlowEdge[], totalModules: number): Impact {
  const { out, inc } = adjacency(edges);
  const down = [...bfs(focus, out, Number.POSITIVE_INFINITY).keys()].filter((id) => id !== focus);
  const up = [...bfs(focus, inc, Number.POSITIVE_INFINITY).keys()].filter((id) => id !== focus);
  const results = down.filter((id) => !(out.get(id) ?? []).length);
  const roots = up.filter((id) => !(inc.get(id) ?? []).length);
  const affected = down.length;
  const level: ImpactLevel = affected === 0 ? 'endpoint' : results.length >= 3 || affected >= 6 ? 'high' : 'medium';
  const percent = totalModules > 1 ? Math.round((affected / (totalModules - 1)) * 100) : 0;
  return { affected, results, roots, percent, level };
}

/** Modules and links on any path between `node` and `focus`, whichever way the data runs. */
export function pathsBetween(node: string, focus: string, edges: FlowEdge[]): { nodes: Set<string>; edges: Set<string> } {
  const { out, inc } = adjacency(edges);
  const reach = (start: string, next: Map<string, string[]>) => new Set(bfs(start, next, Number.POSITIVE_INFINITY).keys());
  const downNode = reach(node, out);
  const upFocus = reach(focus, inc);
  const downFocus = reach(focus, out);
  const upNode = reach(node, inc);
  const nodes = new Set<string>();
  if (downNode.has(focus)) for (const id of downNode) if (upFocus.has(id)) nodes.add(id);
  if (downFocus.has(node)) for (const id of downFocus) if (upNode.has(id)) nodes.add(id);
  const lit = new Set<string>();
  if (nodes.size) {
    nodes.add(node);
    nodes.add(focus);
    for (const e of edges) if (nodes.has(e.source) && nodes.has(e.target)) lit.add(edgeKey(e.source, e.target));
  }
  return { nodes, edges: lit };
}

/** Opacity by distance from the focus: the nearest two rings stay full, the far ones fade. */
export function fadeFor(stage: number): number {
  const d = Math.abs(stage);
  if (d <= 1) return 1;
  if (d === 2) return 0.78;
  if (d === 3) return 0.58;
  return 0.42;
}

export interface LaneNode {
  id: string;
  stage: number;
  lane: string;
}

export const EXTERNAL_LANE = 'external';

/** Lanes ordered so the flow reads top to bottom: outside sources first, then by earliest stage. */
export function laneOrder(nodes: LaneNode[]): string[] {
  const first = new Map<string, number>();
  for (const n of nodes) first.set(n.lane, Math.min(first.get(n.lane) ?? Number.POSITIVE_INFINITY, n.stage));
  return [...first.keys()].sort((a, b) => {
    if (a === EXTERNAL_LANE) return -1;
    if (b === EXTERNAL_LANE) return 1;
    return (first.get(a) ?? 0) - (first.get(b) ?? 0) || a.localeCompare(b);
  });
}

export type Orientation = 'landscape' | 'portrait';

export interface SwimlaneOptions {
  orientation: Orientation;
  cardWidth?: number;
  cardHeight?: number;
  gapMain?: number;
  gapCross?: number;
  lanePad?: number;
  laneHeader?: number;
}

export interface LaneBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SwimlaneResult {
  nodes: Map<string, { x: number; y: number }>;
  lanes: LaneBox[];
  /** x (landscape) or y (portrait) of every stage column, for the headers. */
  stageAt: Map<number, number>;
  /** Node ids per stage in drawing order, for the crossing count. */
  columns: string[][];
  width: number;
  height: number;
}

/**
 * Stages along the main axis, lanes across it. Inside one lane the order of a
 * cell comes from barycentre sweeps over that lane's links, so the bands keep
 * their colour and the curves still do not cross.
 */
export function swimlaneLayout(nodes: LaneNode[], edges: FlowEdge[], options: SwimlaneOptions): SwimlaneResult {
  const o = { cardWidth: 216, cardHeight: 96, gapMain: 72, gapCross: 16, lanePad: 14, laneHeader: 132, ...options };
  const portrait = o.orientation === 'portrait';
  const stageList = [...new Set(nodes.map((n) => n.stage))].sort((a, b) => a - b);
  const minStage = stageList[0] ?? 0;
  const stageCount = (stageList[stageList.length - 1] ?? 0) - minStage + 1;
  const lanes = laneOrder(nodes);
  const ids = new Set(nodes.map((n) => n.id));
  const inner = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
  const mainStep = (portrait ? o.cardHeight : o.cardWidth) + o.gapMain;
  const crossStep = (portrait ? o.cardWidth : o.cardHeight) + o.gapCross;
  const mainOffset = o.laneHeader;
  const columns: string[][] = Array.from({ length: stageCount }, () => []);
  const placed = new Map<string, { x: number; y: number }>();
  const boxes: LaneBox[] = [];
  let cross = 0;
  for (const lane of lanes) {
    const members = nodes.filter((n) => n.lane === lane);
    const ordered = orderColumns(
      members.map((n) => ({ id: n.id, stage: n.stage - minStage, sortKey: n.id })),
      inner,
      stageCount,
    );
    const depth = Math.max(1, ...ordered.map((c) => c.length));
    const size = depth * crossStep - o.gapCross + o.lanePad * 2;
    ordered.forEach((col, s) => {
      col.forEach((id, i) => {
        const main = mainOffset + s * mainStep;
        const at = cross + o.lanePad + i * crossStep;
        placed.set(id, portrait ? { x: at, y: main } : { x: main, y: at });
        columns[s]!.push(id);
      });
    });
    const length = mainOffset + stageCount * mainStep - o.gapMain + o.lanePad;
    boxes.push(portrait ? { id: lane, x: cross, y: 0, width: size, height: length } : { id: lane, x: 0, y: cross, width: length, height: size });
    cross += size + o.gapCross;
  }
  const stageAt = new Map<number, number>();
  for (let s = 0; s < stageCount; s += 1) stageAt.set(s + minStage, mainOffset + s * mainStep);
  const mainLength = mainOffset + stageCount * mainStep - o.gapMain + o.lanePad;
  return {
    nodes: placed,
    lanes: boxes,
    stageAt,
    columns,
    width: portrait ? cross : mainLength,
    height: portrait ? mainLength : cross,
  };
}

export type Direction = 'left' | 'right' | 'up' | 'down';

/** Arrow-key navigation: the nearest module in the pressed direction, or the same one at the edge. */
export function nextNode(current: string, dir: Direction, positions: Map<string, { x: number; y: number }>): string {
  const from = positions.get(current);
  if (!from) return current;
  let best: { id: string; score: number } | null = null;
  for (const [id, p] of positions) {
    if (id === current) continue;
    const dx = p.x - from.x;
    const dy = p.y - from.y;
    const along = dir === 'right' ? dx : dir === 'left' ? -dx : dir === 'down' ? dy : -dy;
    const across = dir === 'left' || dir === 'right' ? Math.abs(dy) : Math.abs(dx);
    if (along <= 0) continue;
    const score = along + across * 2;
    if (!best || score < best.score) best = { id, score };
  }
  return best?.id ?? current;
}

/** Links a trace has walked up to and including step `upto` (steps inside one module draw no link). */
export function traceEdges(steps: { module: string }[], upto: number): string[] {
  const out: string[] = [];
  for (let i = 1; i <= Math.min(upto, steps.length - 1); i += 1) {
    const a = steps[i - 1]!.module;
    const b = steps[i]!.module;
    if (a !== b && !out.includes(edgeKey(a, b))) out.push(edgeKey(a, b));
  }
  return out;
}
