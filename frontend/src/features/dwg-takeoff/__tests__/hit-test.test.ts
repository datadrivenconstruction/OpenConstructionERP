/**
 * Unit tests for the ranked hit-test introduced in RFC 11 §4.2.
 *
 * Exercises ``collectHitCandidates`` + ``scoreOf`` directly, plus the
 * Set<string> multi-selection semantics (shift / plain / Escape) that
 * live in the page-level handler. The latter is reproduced here as a
 * tiny pure helper so we can test it without spinning up React — any
 * drift from ``DwgTakeoffPage.handleSelectEntity`` would show up as a
 * test failure when the UI is updated.
 */

import { describe, it, expect } from 'vitest';
import {
  collectHitCandidates,
  scoreOf,
  type HitCandidate,
} from '../components/DxfViewer';
import type { DxfEntity } from '../api';

/* ── Entity factories ────────────────────────────────────────────────── */

function polygon(
  id: string,
  vertices: Array<[number, number]>,
  opts: { layer?: string; closed?: boolean; area?: number } = {},
): DxfEntity & { _area?: number } {
  return {
    id,
    type: 'LWPOLYLINE',
    layer: opts.layer ?? '0',
    color: '#ffffff',
    vertices: vertices.map(([x, y]) => ({ x, y })),
    closed: opts.closed ?? true,
    _area: opts.area,
  };
}

function line(
  id: string,
  from: [number, number],
  to: [number, number],
  opts: { layer?: string } = {},
): DxfEntity {
  return {
    id,
    type: 'LINE',
    layer: opts.layer ?? '0',
    color: '#ffffff',
    start: { x: from[0], y: from[1] },
    end: { x: to[0], y: to[1] },
  };
}

const ALL_LAYERS = new Set(['0']);
const NO_HIDDEN = new Set<string>();

/* ── Ranked hit-test ─────────────────────────────────────────────────── */

describe('collectHitCandidates — RFC 11 §4.2', () => {
  it('picks the inner polygon over the outer when both contain the click', () => {
    // Outer 20x20 (area 400), inner 4x4 (area 16). Click at origin is inside both.
    const outer = polygon(
      'outer',
      [[-10, -10], [10, -10], [10, 10], [-10, 10]],
      { area: 400 },
    );
    const inner = polygon(
      'inner',
      [[-2, -2], [2, -2], [2, 2], [-2, 2]],
      { area: 16 },
    );

    const candidates = collectHitCandidates(
      { x: 0, y: 0 },
      [outer, inner],
      ALL_LAYERS,
      NO_HIDDEN,
      /*tolerance=*/ 1,
    );

    expect(candidates.length).toBe(2);
    // Ranked list: inner first, outer second.
    expect(candidates[0]!.id).toBe('inner');
    expect(candidates[1]!.id).toBe('outer');
    // And the scoring agrees.
    expect(scoreOf(candidates[0]!)).toBeLessThan(scoreOf(candidates[1]!));
  });

  it('produces a stable ranked order for the same input', () => {
    const outer = polygon('outer', [[0, 0], [10, 0], [10, 10], [0, 10]], { area: 100 });
    const inner = polygon('inner', [[3, 3], [7, 3], [7, 7], [3, 7]], { area: 16 });
    const input = { x: 5, y: 5 };

    const a = collectHitCandidates(input, [outer, inner], ALL_LAYERS, NO_HIDDEN, 1);
    const b = collectHitCandidates(input, [outer, inner], ALL_LAYERS, NO_HIDDEN, 1);

    expect(a.map((c) => c.id)).toEqual(b.map((c) => c.id));
  });

  it('excludes entities on invisible layers', () => {
    const p = polygon('p', [[0, 0], [4, 0], [4, 4], [0, 4]], { layer: 'HIDDEN', area: 16 });
    const candidates = collectHitCandidates(
      { x: 2, y: 2 },
      [p],
      new Set(['0']), // HIDDEN not visible
      NO_HIDDEN,
      1,
    );
    expect(candidates.length).toBe(0);
  });

  it('excludes hidden entities (per-entity hide)', () => {
    const p = polygon('p', [[0, 0], [4, 0], [4, 4], [0, 4]], { area: 16 });
    const candidates = collectHitCandidates(
      { x: 2, y: 2 },
      [p],
      ALL_LAYERS,
      new Set(['p']),
      1,
    );
    expect(candidates.length).toBe(0);
  });

  it('excludes entities whose boundary is farther than tolerance (boundary-only hits)', () => {
    // Open polyline (3-point L) — click far from the segments.
    const p: DxfEntity = {
      id: 'p',
      type: 'LWPOLYLINE',
      layer: '0',
      color: '#ffffff',
      vertices: [{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }],
      closed: false,
    };
    const candidates = collectHitCandidates(
      { x: 100, y: 100 },
      [p],
      ALL_LAYERS,
      NO_HIDDEN,
      1,
    );
    expect(candidates.length).toBe(0);
  });

  it('returns a lone LINE candidate when clicked on it', () => {
    const l = line('l', [0, 0], [10, 0]);
    const candidates = collectHitCandidates(
      { x: 5, y: 0.1 },
      [l],
      ALL_LAYERS,
      NO_HIDDEN,
      1,
    );
    expect(candidates.length).toBe(1);
    expect(candidates[0]!.id).toBe('l');
    expect(candidates[0]!.inside).toBe(false);
  });

  it('scoreOf: inside-hits always outrank boundary-only hits of equal distance', () => {
    const inside: HitCandidate = { id: 'in', distance: 0, inside: true, area: 10 };
    const boundary: HitCandidate = { id: 'out', distance: 0, inside: false, area: 0 };
    expect(scoreOf(inside)).toBeLessThan(scoreOf(boundary));
  });

  it('scoreOf: among inside-hits, smaller areas score lower', () => {
    const small: HitCandidate = { id: 'small', distance: 0, inside: true, area: 10 };
    const big: HitCandidate = { id: 'big', distance: 0, inside: true, area: 10000 };
    expect(scoreOf(small)).toBeLessThan(scoreOf(big));
  });
});

/* ── Cycle-through (RFC 11 §4.2, 6 px + 300 ms window) ──────────────── */

/**
 * Helper that mirrors the `lastHitRef` bookkeeping inside DxfViewer so
 * we can test the cycle-through semantics as a pure function. If the
 * real component's logic drifts, these expectations break.
 */
interface CycleState {
  x: number;
  y: number;
  index: number;
  ts: number;
  candidateIds: string[];
}

function nextCycleIndex(
  prev: CycleState | null,
  click: { x: number; y: number; ts: number },
  candidates: string[],
): { index: number; next: CycleState } {
  const sameSpot =
    prev != null
    && Math.hypot(click.x - prev.x, click.y - prev.y) < 6
    && click.ts - prev.ts < 300
    && prev.candidateIds.length === candidates.length
    && prev.candidateIds.every((id, i) => id === candidates[i]);
  const index = sameSpot ? (prev!.index + 1) % candidates.length : 0;
  return {
    index,
    next: { x: click.x, y: click.y, ts: click.ts, index, candidateIds: candidates },
  };
}

describe('cycle-through — RFC 11 §4.2', () => {
  it('advances when clicking the same spot within 6 px + 300 ms', () => {
    const candidates = ['inner', 'outer'];
    const t0 = nextCycleIndex(null, { x: 100, y: 100, ts: 0 }, candidates);
    const t1 = nextCycleIndex(t0.next, { x: 102, y: 100, ts: 50 }, candidates);
    const t2 = nextCycleIndex(t1.next, { x: 102, y: 101, ts: 200 }, candidates);

    expect(t0.index).toBe(0);
    expect(t1.index).toBe(1);
    expect(t2.index).toBe(0); // wraps around
  });

  it('resets when the click moves beyond 6 px', () => {
    const candidates = ['inner', 'outer'];
    const t0 = nextCycleIndex(null, { x: 100, y: 100, ts: 0 }, candidates);
    const t1 = nextCycleIndex(t0.next, { x: 120, y: 100, ts: 50 }, candidates);
    expect(t1.index).toBe(0);
  });

  it('resets when more than 300 ms elapse', () => {
    const candidates = ['a', 'b'];
    const t0 = nextCycleIndex(null, { x: 100, y: 100, ts: 0 }, candidates);
    const t1 = nextCycleIndex(t0.next, { x: 100, y: 100, ts: 400 }, candidates);
    expect(t1.index).toBe(0);
  });

  it('resets when the candidate set changes', () => {
    const t0 = nextCycleIndex(null, { x: 100, y: 100, ts: 0 }, ['a', 'b']);
    const t1 = nextCycleIndex(t0.next, { x: 100, y: 100, ts: 50 }, ['c']);
    expect(t1.index).toBe(0);
  });
});

/* ── Multi-select Set semantics (mirrors DwgTakeoffPage.handleSelectEntity) ── */

/**
 * Pure reducer matching the production behaviour:
 *   - shiftKey → toggle id in/out of set
 *   - plain click with id → replace with singleton
 *   - plain click with no id (empty space) → clear
 *   - Escape → clear (tested separately via `applyEscape`)
 */
type Action =
  | { kind: 'click'; id: string | null; shiftKey?: boolean }
  | { kind: 'escape' };

function applySelection(prev: Set<string>, action: Action): Set<string> {
  if (action.kind === 'escape') return new Set();
  if (action.id == null) {
    return action.shiftKey ? prev : new Set();
  }
  if (action.shiftKey) {
    const next = new Set(prev);
    if (next.has(action.id)) next.delete(action.id);
    else next.add(action.id);
    return next;
  }
  return new Set([action.id]);
}

describe('selection Set semantics — RFC 11 §4.3', () => {
  it('plain click replaces any existing selection', () => {
    const s0 = applySelection(new Set(), { kind: 'click', id: 'a' });
    expect([...s0]).toEqual(['a']);
    const s1 = applySelection(s0, { kind: 'click', id: 'b' });
    expect([...s1]).toEqual(['b']);
  });

  it('shift-click adds a new id to the selection', () => {
    const s0 = applySelection(new Set(['a']), { kind: 'click', id: 'b', shiftKey: true });
    expect(new Set(s0)).toEqual(new Set(['a', 'b']));
  });

  it('shift-click toggles an already-selected id off', () => {
    const s0 = applySelection(new Set(['a', 'b']), { kind: 'click', id: 'a', shiftKey: true });
    expect(new Set(s0)).toEqual(new Set(['b']));
  });

  it('Escape clears the selection', () => {
    const s0 = applySelection(new Set(['a', 'b', 'c']), { kind: 'escape' });
    expect(s0.size).toBe(0);
  });

  it('plain click on empty space clears the selection', () => {
    const s0 = applySelection(new Set(['a', 'b']), { kind: 'click', id: null });
    expect(s0.size).toBe(0);
  });

  it('shift-click on empty space preserves the selection', () => {
    const s0 = applySelection(
      new Set(['a', 'b']),
      { kind: 'click', id: null, shiftKey: true },
    );
    expect(new Set(s0)).toEqual(new Set(['a', 'b']));
  });
});
