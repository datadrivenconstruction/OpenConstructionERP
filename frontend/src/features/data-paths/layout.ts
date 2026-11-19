// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Layered layout for the data path maps, written in-house (no layout library):
// columns are workflow stages, order inside a column comes from barycentre
// sweeps that pull linked modules level with each other, which is what keeps
// the picture free of spaghetti. Platform modules go to a band underneath.

export interface LayoutNode {
  id: string;
  stage: number;
  /** Tie-breaker for the first order (family, then name). */
  sortKey?: string;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export interface Placed {
  x: number;
  y: number;
}

export interface LayoutOptions {
  nodeWidth: number;
  nodeHeight: number;
  columnGap: number;
  rowGap: number;
  /** Stage index whose nodes form the bottom band instead of a column. */
  bandStage?: number;
  bandColumns?: number;
  sweeps?: number;
}

const DEFAULTS: LayoutOptions = {
  nodeWidth: 208,
  nodeHeight: 68,
  columnGap: 112,
  rowGap: 18,
  bandStage: 6,
  bandColumns: 6,
  sweeps: 8,
};

function barycentre(id: string, neighbours: Map<string, string[]>, rank: Map<string, number>): number | null {
  const ns = (neighbours.get(id) ?? []).map((n) => rank.get(n)).filter((r): r is number => r !== undefined);
  if (ns.length === 0) return null;
  return ns.reduce((a, b) => a + b, 0) / ns.length;
}

/** Number of edge crossings between consecutive columns; used by tests and to keep the better sweep. */
export function countCrossings(columns: string[][], edges: LayoutEdge[]): number {
  const col = new Map<string, number>();
  const pos = new Map<string, number>();
  columns.forEach((ids, c) => ids.forEach((id, i) => { col.set(id, c); pos.set(id, i); }));
  let crossings = 0;
  for (let c = 0; c < columns.length - 1; c += 1) {
    const between = edges
      .map((e) => {
        const [a, b] = (col.get(e.source) ?? -1) <= (col.get(e.target) ?? -1) ? [e.source, e.target] : [e.target, e.source];
        return { a, b };
      })
      .filter(({ a, b }) => col.get(a) === c && col.get(b) === c + 1)
      .map(({ a, b }) => [pos.get(a) ?? 0, pos.get(b) ?? 0] as const);
    for (let i = 0; i < between.length; i += 1) {
      for (let j = i + 1; j < between.length; j += 1) {
        const [a1, b1] = between[i]!;
        const [a2, b2] = between[j]!;
        if ((a1 - a2) * (b1 - b2) < 0) crossings += 1;
      }
    }
  }
  return crossings;
}

/** Column order per stage after barycentre sweeps (exported for tests). */
export function orderColumns(nodes: LayoutNode[], edges: LayoutEdge[], stageCount: number, sweeps = 8): string[][] {
  const columns: string[][] = Array.from({ length: stageCount }, () => []);
  const sorted = [...nodes].sort((a, b) => (a.sortKey ?? a.id).localeCompare(b.sortKey ?? b.id));
  for (const n of sorted) columns[Math.min(Math.max(n.stage, 0), stageCount - 1)]!.push(n.id);
  const neighbours = new Map<string, string[]>();
  for (const e of edges) {
    if (e.source === e.target) continue;
    neighbours.set(e.source, [...(neighbours.get(e.source) ?? []), e.target]);
    neighbours.set(e.target, [...(neighbours.get(e.target) ?? []), e.source]);
  }
  let best = columns.map((c) => [...c]);
  let bestCrossings = countCrossings(best, edges);
  for (let s = 0; s < sweeps; s += 1) {
    const order = s % 2 === 0 ? columns.map((_, i) => i) : columns.map((_, i) => columns.length - 1 - i);
    for (const c of order) {
      const rank = new Map<string, number>();
      columns.forEach((ids, ci) => {
        if (ci !== c) ids.forEach((id, i) => rank.set(id, i / Math.max(1, ids.length - 1 || 1)));
      });
      const current = columns[c]!;
      const keyed = current.map((id, i) => ({ id, i, b: barycentre(id, neighbours, rank) }));
      keyed.sort((x, y) => (x.b ?? x.i / Math.max(1, current.length)) - (y.b ?? y.i / Math.max(1, current.length)) || x.i - y.i);
      columns[c] = keyed.map((k) => k.id);
    }
    const crossings = countCrossings(columns, edges);
    if (crossings < bestCrossings) {
      bestCrossings = crossings;
      best = columns.map((c) => [...c]);
    }
  }
  return best;
}

/** Positions for every node: stage columns, centred vertically, plus a bottom band. */
export function layeredLayout(nodes: LayoutNode[], edges: LayoutEdge[], options: Partial<LayoutOptions> = {}): Map<string, Placed> {
  const o = { ...DEFAULTS, ...options };
  const band = nodes.filter((n) => o.bandStage !== undefined && n.stage === o.bandStage);
  const main = nodes.filter((n) => !(o.bandStage !== undefined && n.stage === o.bandStage));
  const stageCount = Math.max(1, ...main.map((n) => n.stage + 1));
  const ids = new Set(main.map((n) => n.id));
  const columns = orderColumns(main, edges.filter((e) => ids.has(e.source) && ids.has(e.target)), stageCount, o.sweeps);
  const tallest = Math.max(1, ...columns.map((c) => c.length));
  const fullHeight = tallest * (o.nodeHeight + o.rowGap) - o.rowGap;
  const out = new Map<string, Placed>();
  columns.forEach((col, c) => {
    const height = col.length * (o.nodeHeight + o.rowGap) - o.rowGap;
    const top = (fullHeight - height) / 2;
    col.forEach((id, i) => out.set(id, { x: c * (o.nodeWidth + o.columnGap), y: top + i * (o.nodeHeight + o.rowGap) }));
  });
  const bandTop = fullHeight + o.nodeHeight * 1.5;
  const perRow = Math.max(1, Math.max(o.bandColumns ?? 6, stageCount));
  [...band]
    .sort((a, b) => (a.sortKey ?? a.id).localeCompare(b.sortKey ?? b.id))
    .forEach((n, i) => {
      out.set(n.id, {
        x: (i % perRow) * (o.nodeWidth + o.columnGap),
        y: bandTop + Math.floor(i / perRow) * (o.nodeHeight + o.rowGap),
      });
    });
  return out;
}

/** Everything upstream and downstream of one node (the chain a hover lights up). */
export function chainOf(id: string, edges: LayoutEdge[]): { up: Set<string>; down: Set<string> } {
  const walk = (start: string, forward: boolean): Set<string> => {
    const seen = new Set<string>();
    const stack = [start];
    while (stack.length) {
      const cur = stack.pop()!;
      for (const e of edges) {
        const [from, to] = forward ? [e.source, e.target] : [e.target, e.source];
        if (from === cur && !seen.has(to) && to !== start) {
          seen.add(to);
          stack.push(to);
        }
      }
    }
    return seen;
  };
  return { up: walk(id, false), down: walk(id, true) };
}

/** Modules within `hops` links of `id`, in either direction. */
export function neighbourhood(id: string, edges: LayoutEdge[], hops: number): Set<string> {
  let frontier = new Set([id]);
  const seen = new Set([id]);
  for (let h = 0; h < hops; h += 1) {
    const next = new Set<string>();
    for (const e of edges) {
      if (frontier.has(e.source) && !seen.has(e.target)) next.add(e.target);
      if (frontier.has(e.target) && !seen.has(e.source)) next.add(e.source);
    }
    next.forEach((n) => seen.add(n));
    frontier = next;
  }
  return seen;
}
