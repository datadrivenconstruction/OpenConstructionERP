/**
 * Phase C v2.7.0/C — cycle detection tests.
 *
 * Tarjan's SCC implementation, ported from `service.py:1148-1240`. We
 * test:
 *   • length-2 cycles (A → B → A)
 *   • length-3 cycles (A → B → C → A)
 *   • length-N generated cycles
 *   • self-loops (A → A)
 *   • cycle-NOT-cycle: chain that converges but doesn't loop
 *   • mixed graphs with both cyclic and acyclic components
 *   • the warn-and-allow contract: cycle participants get yellow ⚠
 *     (cycleIds), DAG nodes don't, and cyclePathById has the full path.
 */

import { describe, it, expect } from 'vitest';
import { buildDependencyGraph, transitiveDependents } from '../grid/formula';
import type { Position } from '../api';

function pos(id: string, ordinal: string, formula: string | null): Position {
  return {
    id,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal,
    description: '',
    unit: 'm',
    quantity: 1,
    unit_rate: 1,
    total: 1,
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: formula ? { formula } : {},
  };
}

function buildGraph(positions: Position[]) {
  const ordToId = new Map<string, string>();
  for (const p of positions) ordToId.set(p.ordinal, p.id);
  return buildDependencyGraph(positions, {
    resolveOrdinal: (ord) => ordToId.get(ord),
  });
}

/* ── Self-loop ───────────────────────────────────────────────── */

describe('cycle detection — self-loop', () => {
  it('detects A → A', () => {
    const a = pos('a', '1.1', '=pos("1.1").qty + 1');
    const g = buildGraph([a]);
    expect(g.cycleIds.has('a')).toBe(true);
    expect(g.cyclePathById.get('a')).toEqual(['a']);
  });
});

/* ── Length 2 ────────────────────────────────────────────────── */

describe('cycle detection — length 2', () => {
  it('detects A ↔ B', () => {
    const a = pos('a', '1.1', '=pos("1.2").qty');
    const b = pos('b', '1.2', '=pos("1.1").qty');
    const g = buildGraph([a, b]);
    expect(g.cycleIds.has('a')).toBe(true);
    expect(g.cycleIds.has('b')).toBe(true);
    const path = g.cyclePathById.get('a')!;
    expect(path.length).toBe(2);
    expect(path).toContain('a');
    expect(path).toContain('b');
  });
});

/* ── Length 3 ────────────────────────────────────────────────── */

describe('cycle detection — length 3', () => {
  it('detects A → B → C → A', () => {
    const a = pos('a', '1.1', '=pos("1.2").qty');
    const b = pos('b', '1.2', '=pos("1.3").qty');
    const c = pos('c', '1.3', '=pos("1.1").qty');
    const g = buildGraph([a, b, c]);
    expect(g.cycleIds.has('a')).toBe(true);
    expect(g.cycleIds.has('b')).toBe(true);
    expect(g.cycleIds.has('c')).toBe(true);
  });
});

/* ── Length N generated ───────────────────────────────────────── */

describe('cycle detection — length N', () => {
  it.each([4, 5, 8, 16, 32])('detects an N=%i cycle', (n) => {
    const positions: Position[] = [];
    for (let i = 0; i < n; i++) {
      const next = (i + 1) % n;
      positions.push(pos(`p${i}`, `${i + 1}`, `=pos("${next + 1}").qty`));
    }
    const g = buildGraph(positions);
    expect(g.cycleIds.size).toBe(n);
    for (let i = 0; i < n; i++) {
      expect(g.cycleIds.has(`p${i}`)).toBe(true);
    }
  });
});

/* ── DAG (no cycle) ──────────────────────────────────────────── */

describe('cycle detection — acyclic graphs', () => {
  it('returns empty cycleIds for a chain A → B → C', () => {
    const a = pos('a', '1.1', '=pos("1.2").qty + 1');
    const b = pos('b', '1.2', '=pos("1.3").qty + 1');
    const c = pos('c', '1.3', null);
    const g = buildGraph([a, b, c]);
    expect(g.cycleIds.size).toBe(0);
  });

  it('returns empty cycleIds for a diamond (A → B,C → D)', () => {
    const a = pos('a', '1.1', '=pos("1.2").qty + pos("1.3").qty');
    const b = pos('b', '1.2', '=pos("1.4").qty');
    const c = pos('c', '1.3', '=pos("1.4").qty');
    const d = pos('d', '1.4', null);
    const g = buildGraph([a, b, c, d]);
    expect(g.cycleIds.size).toBe(0);
  });
});

/* ── Mixed: cycle + DAG ──────────────────────────────────────── */

describe('cycle detection — mixed graphs', () => {
  it('isolates the cycle from the rest of the DAG', () => {
    // Cycle: A ↔ B.
    // DAG:   C → D, where C reads B (cycle output), D is independent.
    const a = pos('a', '1.1', '=pos("1.2").qty');
    const b = pos('b', '1.2', '=pos("1.1").qty');
    const c = pos('c', '1.3', '=pos("1.2").qty * 2');
    const d = pos('d', '1.4', '=2 + 3');
    const g = buildGraph([a, b, c, d]);
    expect(g.cycleIds.has('a')).toBe(true);
    expect(g.cycleIds.has('b')).toBe(true);
    expect(g.cycleIds.has('c')).toBe(false);
    expect(g.cycleIds.has('d')).toBe(false);
  });
});

/* ── transitiveDependents ────────────────────────────────────── */

describe('transitiveDependents', () => {
  it('walks the reverse-edge graph', () => {
    // A → B → C → D (D reads C, C reads B, B reads A)
    const a = pos('a', '1.1', null);
    const b = pos('b', '1.2', '=pos("1.1").qty * 2');
    const c = pos('c', '1.3', '=pos("1.2").qty * 2');
    const d = pos('d', '1.4', '=pos("1.3").qty * 2');
    const g = buildGraph([a, b, c, d]);
    const tx = transitiveDependents(g, 'a');
    expect(tx.has('b')).toBe(true);
    expect(tx.has('c')).toBe(true);
    expect(tx.has('d')).toBe(true);
    expect(tx.has('a')).toBe(false);
  });

  it('returns empty set for a leaf', () => {
    const a = pos('a', '1.1', null);
    const b = pos('b', '1.2', '=pos("1.1").qty');
    const g = buildGraph([a, b]);
    expect(transitiveDependents(g, 'b').size).toBe(0);
  });
});

/* ── Variable users ──────────────────────────────────────────── */

describe('variable users', () => {
  it('tracks which positions reference a $VAR', () => {
    const a = pos('a', '1.1', '=$GFA * 0.15');
    const b = pos('b', '1.2', '=$GFA + $RATE');
    const c = pos('c', '1.3', '=42');
    const g = buildGraph([a, b, c]);
    expect(g.variableUsers.get('GFA')!.has('a')).toBe(true);
    expect(g.variableUsers.get('GFA')!.has('b')).toBe(true);
    expect(g.variableUsers.get('GFA')!.has('c')).toBe(false);
    expect(g.variableUsers.get('RATE')!.has('b')).toBe(true);
  });
});

/* ── Robustness ──────────────────────────────────────────────── */

describe('cycle detection — robustness', () => {
  it('handles broken formulas without throwing', () => {
    const a = pos('a', '1.1', '=this is bad syntax');
    const b = pos('b', '1.2', '=pos("1.1").qty');
    const g = buildGraph([a, b]);
    expect(g.cycleIds.size).toBe(0);
  });

  it('ignores references to non-existent ordinals', () => {
    const a = pos('a', '1.1', '=pos("nonexistent").qty');
    const g = buildGraph([a]);
    expect(g.cycleIds.size).toBe(0);
  });

  it('handles empty positions list', () => {
    const g = buildGraph([]);
    expect(g.cycleIds.size).toBe(0);
    expect(g.dependsOn.size).toBe(0);
  });
});
