/**
 * Phase C v2.7.0/C — formula engine extension tests.
 *
 * Covers:
 *   • every new operator (comparisons, member access)
 *   • every new built-in (pos, section, col, if, unit converters,
 *     round_up / round_down)
 *   • backwards-compatibility: every legacy expression still works
 *     when the context arg is omitted
 *   • error paths (unknown function, unresolved $VAR, type mismatch)
 */

import { describe, it, expect } from 'vitest';
import {
  evaluateFormula,
  evaluateFormulaRaw,
  isFormula,
  buildFormulaContext,
  type FormulaContext,
  type FormulaVariable,
} from '../grid/formula';
import type { Position } from '../api';

/* ── Test fixtures ──────────────────────────────────────────────── */

function makePosition(opts: Partial<Position> & { id: string; ordinal: string }): Position {
  return {
    id: opts.id,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: opts.ordinal,
    description: opts.description ?? `pos ${opts.ordinal}`,
    unit: opts.unit ?? 'm',
    quantity: opts.quantity ?? 0,
    unit_rate: opts.unit_rate ?? 0,
    total: (opts.quantity ?? 0) * (opts.unit_rate ?? 0),
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: opts.metadata ?? {},
  };
}

function makeContext(positions: Position[], variables: Record<string, FormulaVariable> = {}): FormulaContext {
  const varMap = new Map<string, FormulaVariable>();
  for (const [k, v] of Object.entries(variables)) varMap.set(k.toUpperCase(), v);
  return buildFormulaContext({ positions, variables: varMap });
}

/* ── Backwards-compat (no ctx) ──────────────────────────────────── */

describe('evaluateFormula — backwards-compat (single-arg)', () => {
  it('still evaluates basic math', () => {
    expect(evaluateFormula('2+3')).toBe(5);
    expect(evaluateFormula('=2*PI()^2*3')).toBeCloseTo(59.2176, 3);
    expect(evaluateFormula('=sqrt(144)')).toBe(12);
    expect(evaluateFormula('12 x 4')).toBe(48);
    expect(evaluateFormula('=2,5*4')).toBe(10);
  });

  it('returns null for negative results without ctx', () => {
    expect(evaluateFormula('=2-5')).toBeNull();
    expect(evaluateFormula('=-3')).toBeNull();
  });

  it('rejects $VAR and pos() without ctx', () => {
    expect(evaluateFormula('=$GFA')).toBeNull();
    expect(evaluateFormula('=pos("1.1").qty')).toBeNull();
  });
});

/* ── $VAR support ──────────────────────────────────────────────── */

describe('evaluateFormula — variables', () => {
  it('reads numeric variables', () => {
    const ctx = makeContext([], { GFA: { type: 'number', value: 1500 } });
    expect(evaluateFormula('=$GFA', ctx)).toBe(1500);
    expect(evaluateFormula('=$GFA * 0.15', ctx)).toBe(225);
  });

  it('case-insensitive variable names', () => {
    const ctx = makeContext([], { GFA: { type: 'number', value: 100 } });
    expect(evaluateFormula('=$gfa', ctx)).toBe(100);
    expect(evaluateFormula('=$Gfa', ctx)).toBe(100);
  });

  it('returns null for unknown variable', () => {
    const ctx = makeContext([], { GFA: { type: 'number', value: 100 } });
    expect(evaluateFormula('=$MISSING', ctx)).toBeNull();
  });

  it('returns null for unset variable', () => {
    const ctx = makeContext([], { GFA: { type: 'number', value: null } });
    expect(evaluateFormula('=$GFA', ctx)).toBeNull();
  });

  it('combines variables with cross-position refs', () => {
    const a = makePosition({ id: 'a', ordinal: '1.1', quantity: 10, unit_rate: 5 });
    const ctx = makeContext([a], { FACTOR: { type: 'number', value: 2 } });
    expect(evaluateFormula('=pos("1.1").qty * $FACTOR', ctx)).toBe(20);
  });
});

/* ── pos() ─────────────────────────────────────────────────────── */

describe('evaluateFormula — pos()', () => {
  const a = makePosition({ id: 'a', ordinal: '1.1.001', quantity: 12, unit_rate: 50 });
  const b = makePosition({ id: 'b', ordinal: '01.02', quantity: 4.5, unit_rate: 100 });
  const ctx = makeContext([a, b]);

  it('reads .qty', () => {
    expect(evaluateFormula('=pos("1.1.001").qty', ctx)).toBe(12);
  });

  it('reads .rate', () => {
    expect(evaluateFormula('=pos("1.1.001").rate', ctx)).toBe(50);
  });

  it('reads .total', () => {
    expect(evaluateFormula('=pos("1.1.001").total', ctx)).toBe(600);
    expect(evaluateFormula('=pos("01.02").total', ctx)).toBe(450);
  });

  it('supports both quote styles', () => {
    expect(evaluateFormula("=pos('1.1.001').qty", ctx)).toBe(12);
  });

  it('supports computed expressions', () => {
    expect(evaluateFormula('=pos("1.1.001").qty * 2 + pos("01.02").qty', ctx)).toBe(28.5);
  });

  it('returns null when ordinal not found', () => {
    expect(evaluateFormula('=pos("missing").qty', ctx)).toBeNull();
  });

  it('returns null on bad member', () => {
    expect(evaluateFormula('=pos("1.1.001").nosuchfield', ctx)).toBeNull();
  });

  it('aliases .quantity → .qty and .unit_rate → .rate', () => {
    expect(evaluateFormula('=pos("1.1.001").quantity', ctx)).toBe(12);
    expect(evaluateFormula('=pos("1.1.001").unit_rate', ctx)).toBe(50);
  });
});

/* ── section() ─────────────────────────────────────────────────── */

describe('evaluateFormula — section()', () => {
  const a = makePosition({ id: 'a', ordinal: '1.1', quantity: 10, unit_rate: 5 });
  const b = makePosition({ id: 'b', ordinal: '1.2', quantity: 4, unit_rate: 25 });

  it('aggregates .total across members', () => {
    const ctx = buildFormulaContext({
      positions: [a, b],
      sectionMembers: new Map([['Concrete', [a, b]]]),
    });
    expect(evaluateFormula('=section("Concrete").total', ctx)).toBe(150);
  });

  it('returns null when section not found', () => {
    const ctx = buildFormulaContext({ positions: [a, b] });
    expect(evaluateFormula('=section("Missing").total', ctx)).toBeNull();
  });
});

/* ── col() ─────────────────────────────────────────────────────── */

describe('evaluateFormula — col() in calculated columns', () => {
  it('reads from currentRow', () => {
    const ctx = buildFormulaContext({
      positions: [],
      currentRow: { quantity: 10, total: 500, custom_x: 3 },
    });
    expect(evaluateFormula('=col("quantity") * 2', ctx)).toBe(20);
    expect(evaluateFormula('=col("total") + col("custom_x")', ctx)).toBe(503);
  });

  it('returns null when no currentRow', () => {
    const ctx = buildFormulaContext({ positions: [] });
    expect(evaluateFormula('=col("quantity")', ctx)).toBeNull();
  });

  it('treats missing keys as 0', () => {
    const ctx = buildFormulaContext({
      positions: [],
      currentRow: { quantity: 10 },
    });
    expect(evaluateFormula('=col("nope") + 5', ctx)).toBe(5);
  });
});

/* ── if() ─────────────────────────────────────────────────────── */

describe('evaluateFormula — if() conditional', () => {
  const ctx = makeContext([], { N: { type: 'number', value: 5 } });

  it('evaluates the true branch', () => {
    expect(evaluateFormula('=if(1<2, 10, 20)', ctx)).toBe(10);
  });

  it('evaluates the false branch', () => {
    expect(evaluateFormula('=if(2<1, 10, 20)', ctx)).toBe(20);
  });

  it('uses comparisons against variables', () => {
    expect(evaluateFormula('=if($N > 3, 100, 50)', ctx)).toBe(100);
    expect(evaluateFormula('=if($N == 5, 100, 50)', ctx)).toBe(100);
    expect(evaluateFormula('=if($N != 5, 100, 50)', ctx)).toBe(50);
    expect(evaluateFormula('=if($N >= 5, 100, 50)', ctx)).toBe(100);
    expect(evaluateFormula('=if($N <= 4, 100, 50)', ctx)).toBe(50);
  });

  it('short-circuits — bad branch is skipped when not taken', () => {
    // The false branch references a missing variable; if we evaluated
    // it we'd throw and return null. Short-circuit means 100 wins.
    expect(evaluateFormula('=if(1<2, 100, $MISSING)', ctx)).toBe(100);
    expect(evaluateFormula('=if(1>2, $MISSING, 50)', ctx)).toBe(50);
  });

  it('nests if() correctly', () => {
    expect(evaluateFormula('=if(1<2, if(3<4, 7, 8), 9)', ctx)).toBe(7);
  });
});

/* ── unit converters ──────────────────────────────────────────── */

describe('evaluateFormula — unit conversion built-ins', () => {
  it('converts metric ↔ imperial length', () => {
    expect(evaluateFormula('=m_to_ft(1)')).toBeCloseTo(3.2808, 3);
    expect(evaluateFormula('=ft_to_m(10)')).toBeCloseTo(3.048, 3);
  });

  it('converts area', () => {
    expect(evaluateFormula('=m2_to_ft2(1)')).toBeCloseTo(10.7639, 3);
    expect(evaluateFormula('=ft2_to_m2(100)')).toBeCloseTo(9.2903, 3);
  });

  it('converts volume', () => {
    expect(evaluateFormula('=m3_to_yd3(1)')).toBeCloseTo(1.308, 3);
    expect(evaluateFormula('=yd3_to_m3(1)')).toBeCloseTo(0.7646, 3);
  });

  it('converts mass', () => {
    expect(evaluateFormula('=kg_to_lb(1)')).toBeCloseTo(2.2046, 3);
    expect(evaluateFormula('=lb_to_kg(10)')).toBeCloseTo(4.5359, 3);
  });

  it('round-trips with high precision', () => {
    const v = 12.34;
    const conv = evaluateFormula(`=ft_to_m(m_to_ft(${v}))`);
    expect(conv).toBeCloseTo(v, 4);
  });
});

/* ── round_up / round_down ─────────────────────────────────────── */

describe('evaluateFormula — round_up / round_down', () => {
  it('round_up to integer (n=0 default)', () => {
    expect(evaluateFormula('=round_up(3.1)')).toBe(4);
    expect(evaluateFormula('=round_up(3.9)')).toBe(4);
    expect(evaluateFormula('=round_up(3.0)')).toBe(3);
  });

  it('round_up with n decimals', () => {
    expect(evaluateFormula('=round_up(3.141, 1)')).toBeCloseTo(3.2, 4);
    expect(evaluateFormula('=round_up(3.141, 2)')).toBeCloseTo(3.15, 4);
  });

  it('round_down to integer', () => {
    expect(evaluateFormula('=round_down(3.9)')).toBe(3);
    expect(evaluateFormula('=round_down(3.0001)')).toBe(3);
  });

  it('round_down with n decimals', () => {
    expect(evaluateFormula('=round_down(3.149, 1)')).toBeCloseTo(3.1, 4);
    expect(evaluateFormula('=round_down(3.149, 2)')).toBeCloseTo(3.14, 4);
  });
});

/* ── Comparisons (raw) ────────────────────────────────────────── */

describe('evaluateFormulaRaw — comparisons return booleans', () => {
  const ctx = makeContext([], { N: { type: 'number', value: 5 } });

  it('returns boolean for comparison expressions', () => {
    expect(evaluateFormulaRaw('=$N > 3', ctx)).toBe(true);
    expect(evaluateFormulaRaw('=$N < 3', ctx)).toBe(false);
    expect(evaluateFormulaRaw('=$N == 5', ctx)).toBe(true);
    expect(evaluateFormulaRaw('=$N != 5', ctx)).toBe(false);
  });
});

/* ── isFormula sniff ──────────────────────────────────────────── */

describe('isFormula', () => {
  it('detects $VAR', () => {
    expect(isFormula('$GFA')).toBe(true);
    expect(isFormula('=$GFA')).toBe(true);
  });

  it('detects new built-ins', () => {
    expect(isFormula('pos("1.1").qty')).toBe(true);
    expect(isFormula('=if(1<2, 3, 4)')).toBe(true);
    expect(isFormula('=m_to_ft(1)')).toBe(true);
    expect(isFormula('=round_up(3.1)')).toBe(true);
  });

  it('still detects legacy formulas', () => {
    expect(isFormula('=2+3')).toBe(true);
    expect(isFormula('2*3')).toBe(true);
    expect(isFormula('sqrt(4)')).toBe(true);
    expect(isFormula('12.5')).toBe(false);
    expect(isFormula('')).toBe(false);
  });
});

/* ── Error paths ─────────────────────────────────────────────── */

describe('evaluateFormula — error paths', () => {
  it('returns null on unknown function', () => {
    expect(evaluateFormula('=nosuchfn(1)')).toBeNull();
  });

  it('returns null on unterminated string', () => {
    expect(evaluateFormula('=pos("oops')).toBeNull();
  });

  it('returns null on bad if() arity', () => {
    expect(evaluateFormula('=if(1<2)')).toBeNull();
    expect(evaluateFormula('=if(1<2, 3)')).toBeNull();
  });

  it('returns null on .member without record', () => {
    expect(evaluateFormula('=2.qty')).toBeNull();
  });
});

/* ── Pure-string variables (text/date) — only legal with raw ──── */

describe('evaluateFormulaRaw — text variables', () => {
  it('returns text values directly', () => {
    const ctx = makeContext([], {
      LABEL: { type: 'text', value: 'Concrete C30/37' },
    });
    expect(evaluateFormulaRaw('=$LABEL', ctx)).toBe('Concrete C30/37');
  });
});
