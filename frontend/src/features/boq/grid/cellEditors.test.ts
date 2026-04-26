/**
 * Tests for the BOQ Quantity formula evaluator (Issue #90).
 *
 * The parser is hand-written (no `eval`, no `new Function`) and must:
 *   • accept Excel-style `=` prefix
 *   • support + - * / ^  and `**` as exponent alias
 *   • support `x` / `×` as multiplication aliases
 *   • support `,` as decimal separator (es/de locales)
 *   • support PI, E constants
 *   • support sqrt, abs, round, floor, ceil, pow, min, max, sin, cos, tan, log, exp
 *   • reject identifiers it doesn't know (CSP / safety guard)
 *   • clamp negative results to null (BOQ quantities are non-negative)
 */

import { describe, it, expect } from 'vitest';
import { evaluateFormula } from './cellEditors';

describe('evaluateFormula — basic arithmetic', () => {
  it('evaluates + - * /', () => {
    expect(evaluateFormula('2+3')).toBe(5);
    expect(evaluateFormula('10-4')).toBe(6);
    expect(evaluateFormula('6*7')).toBe(42);
    expect(evaluateFormula('20/4')).toBe(5);
  });

  it('respects operator precedence', () => {
    expect(evaluateFormula('2+3*4')).toBe(14);
    expect(evaluateFormula('(2+3)*4')).toBe(20);
    expect(evaluateFormula('10-2-3')).toBe(5); // left-associative
  });

  it('handles decimals', () => {
    expect(evaluateFormula('1.5*2')).toBe(3);
    expect(evaluateFormula('0.1+0.2')).toBeCloseTo(0.3, 4);
  });

  it('returns null for empty input', () => {
    expect(evaluateFormula('')).toBeNull();
    expect(evaluateFormula('   ')).toBeNull();
  });
});

describe('evaluateFormula — Excel-style "=" prefix', () => {
  it('accepts a leading equals sign', () => {
    expect(evaluateFormula('=2+3')).toBe(5);
    expect(evaluateFormula('= 12 * 4')).toBe(48);
  });
});

describe('evaluateFormula — exponent', () => {
  it('supports ^ as right-associative exponent', () => {
    expect(evaluateFormula('2^3')).toBe(8);
    expect(evaluateFormula('2^3^2')).toBe(512); // right-assoc: 2^(3^2)
    expect(evaluateFormula('=2*PI()^2*3')).toBeCloseTo(59.2176, 3);
  });

  it('supports ** as exponent alias (Python)', () => {
    expect(evaluateFormula('2**3')).toBe(8);
  });
});

describe('evaluateFormula — multiplication aliases', () => {
  it('accepts x as multiplication', () => {
    expect(evaluateFormula('12 x 4')).toBe(48);
    expect(evaluateFormula('=2 X 3')).toBe(6);
  });

  it('accepts × (Unicode multiplication sign)', () => {
    expect(evaluateFormula('5 × 6')).toBe(30);
  });
});

describe('evaluateFormula — locale decimal separator', () => {
  it('accepts comma as decimal point', () => {
    expect(evaluateFormula('=2,5 * 4')).toBe(10);
    expect(evaluateFormula('1,5 + 0,5')).toBe(2);
  });
});

describe('evaluateFormula — constants', () => {
  it('supports PI and E (case-insensitive)', () => {
    expect(evaluateFormula('=PI()')).toBeCloseTo(Math.PI, 4);
    expect(evaluateFormula('=pi')).toBeCloseTo(Math.PI, 4);
    expect(evaluateFormula('=E()')).toBeCloseTo(Math.E, 4);
    expect(evaluateFormula('=e * 2')).toBeCloseTo(Math.E * 2, 4);
  });
});

describe('evaluateFormula — functions', () => {
  it('supports sqrt', () => {
    expect(evaluateFormula('=sqrt(144)')).toBe(12);
    expect(evaluateFormula('=sqrt(144) + 5')).toBe(17);
  });

  it('supports abs/round/floor/ceil', () => {
    expect(evaluateFormula('=abs(0-5)')).toBe(5);
    expect(evaluateFormula('=round(3.6)')).toBe(4);
    expect(evaluateFormula('=floor(3.9)')).toBe(3);
    expect(evaluateFormula('=ceil(3.1)')).toBe(4);
  });

  it('supports pow with two args', () => {
    expect(evaluateFormula('=pow(2,10)')).toBe(1024);
  });

  it('supports min/max with multiple args', () => {
    expect(evaluateFormula('=min(3,1,2)')).toBe(1);
    expect(evaluateFormula('=max(3,1,2)')).toBe(3);
  });
});

describe('evaluateFormula — safety / rejection', () => {
  it('returns null for unknown identifiers', () => {
    expect(evaluateFormula('=window')).toBeNull();
    expect(evaluateFormula('=alert(1)')).toBeNull();
    expect(evaluateFormula('=document.cookie')).toBeNull();
  });

  it('returns null for negative results (BOQ quantities are >= 0)', () => {
    expect(evaluateFormula('=2-5')).toBeNull();
    expect(evaluateFormula('=-3')).toBeNull();
  });

  it('returns null for non-finite results', () => {
    expect(evaluateFormula('=1/0')).toBeNull();
  });

  it('returns null for malformed input', () => {
    expect(evaluateFormula('=2+')).toBeNull();
    expect(evaluateFormula('=(2+3')).toBeNull(); // missing )
    expect(evaluateFormula('=2*3)')).toBeNull(); // extra )
  });
});

describe('evaluateFormula — Issue #90 examples', () => {
  it('matches the user-reported example', () => {
    // The user wrote =2xPI()^2x3 with `x` instead of `*`.
    expect(evaluateFormula('=2xPI()^2x3')).toBeCloseTo(59.2176, 3);
    expect(evaluateFormula('=2*PI()^2*3')).toBeCloseTo(59.2176, 3);
  });
});
