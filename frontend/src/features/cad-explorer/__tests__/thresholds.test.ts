import { describe, it, expect } from 'vitest';
import {
  resolveThresholdColor,
  applyRuleToBar,
  serialiseThresholds,
  parseThresholds,
  findRuleForColumn,
  createDefaultRule,
  isRuleValid,
  DEFAULT_LOW_COLOR,
  DEFAULT_MID_COLOR,
  DEFAULT_HIGH_COLOR,
  MAX_RULES,
  MAX_URL_LENGTH,
  type ThresholdRule,
} from '@/features/cad-explorer/thresholds';

function makeRule(overrides: Partial<ThresholdRule> = {}): ThresholdRule {
  return {
    column: 'volume',
    low: 0.8,
    high: 1,
    lowColor: '#ef4444',
    midColor: '#f59e0b',
    highColor: '#10b981',
    ...overrides,
  };
}

describe('thresholds — resolveThresholdColor', () => {
  const rule = makeRule();

  it('returns "low" when the value is strictly below low', () => {
    expect(resolveThresholdColor(0.5, rule)).toBe('low');
    expect(resolveThresholdColor(0.79, rule)).toBe('low');
    expect(resolveThresholdColor(-999, rule)).toBe('low');
  });

  it('returns "mid" when the value sits between low (inclusive) and high (exclusive)', () => {
    expect(resolveThresholdColor(0.8, rule)).toBe('mid'); // inclusive low
    expect(resolveThresholdColor(0.9, rule)).toBe('mid');
    expect(resolveThresholdColor(0.999, rule)).toBe('mid');
  });

  it('returns "high" when the value is at or above high', () => {
    expect(resolveThresholdColor(1, rule)).toBe('high'); // inclusive high
    expect(resolveThresholdColor(1.5, rule)).toBe('high');
    expect(resolveThresholdColor(1_000_000, rule)).toBe('high');
  });

  it('returns null when no rule is supplied', () => {
    expect(resolveThresholdColor(0.5, null)).toBeNull();
    expect(resolveThresholdColor(0.5, undefined)).toBeNull();
  });

  it('returns null when column is provided and does not match the rule', () => {
    expect(resolveThresholdColor(0.5, rule, 'other_column')).toBeNull();
    expect(resolveThresholdColor(0.5, rule, 'volume')).toBe('low');
  });

  it('returns null when value is null / undefined / NaN / Infinity', () => {
    expect(resolveThresholdColor(null, rule)).toBeNull();
    expect(resolveThresholdColor(undefined, rule)).toBeNull();
    expect(resolveThresholdColor(NaN, rule)).toBeNull();
    expect(resolveThresholdColor(Infinity, rule)).toBeNull();
    expect(resolveThresholdColor(-Infinity, rule)).toBeNull();
  });

  it('returns null when the rule has non-finite bounds', () => {
    expect(resolveThresholdColor(0.5, makeRule({ low: NaN, high: 1 }))).toBeNull();
    expect(resolveThresholdColor(0.5, makeRule({ low: 0.8, high: Infinity }))).toBeNull();
  });

  it('handles degenerate low == high by splitting at the pivot (no mid band)', () => {
    const degenerate = makeRule({ low: 5, high: 5 });
    expect(resolveThresholdColor(4.99, degenerate)).toBe('low');
    expect(resolveThresholdColor(5, degenerate)).toBe('high'); // value == high → high
    expect(resolveThresholdColor(10, degenerate)).toBe('high');
  });

  it('handles negative bounds', () => {
    const negative = makeRule({ low: -10, high: -5 });
    expect(resolveThresholdColor(-15, negative)).toBe('low');
    expect(resolveThresholdColor(-7, negative)).toBe('mid');
    expect(resolveThresholdColor(0, negative)).toBe('high');
  });
});

describe('thresholds — applyRuleToBar', () => {
  const rule = makeRule();

  it('returns neutral fallback when no zone matches', () => {
    const out = applyRuleToBar(0.5, null);
    expect(out.bar).toBeDefined();
    expect(out.bg).toBe('transparent');
  });

  it('returns the low colour for values below low', () => {
    const out = applyRuleToBar(0.5, rule);
    expect(out.bar).toBe('#ef4444');
    expect(out.bg).toMatch(/^rgba\(239, 68, 68, 0\.1\)$/);
    // Text should be a darker variant of the base colour, not the base itself.
    expect(out.text).not.toBe('#ef4444');
  });

  it('returns the mid colour for values in the mid band', () => {
    expect(applyRuleToBar(0.9, rule).bar).toBe('#f59e0b');
  });

  it('returns the high colour for values at or above high', () => {
    expect(applyRuleToBar(1.5, rule).bar).toBe('#10b981');
  });

  it('carries the cell background at 10% alpha', () => {
    const out = applyRuleToBar(0.9, rule);
    expect(out.bg).toContain('0.1');
  });
});

describe('thresholds — URL round-trip', () => {
  it('serialises an empty rule list to an empty string', () => {
    expect(serialiseThresholds([])).toBe('');
    expect(parseThresholds('')).toEqual([]);
    expect(parseThresholds(null)).toEqual([]);
    expect(parseThresholds(undefined)).toEqual([]);
  });

  it('round-trips a single rule', () => {
    const rules = [makeRule()];
    const s = serialiseThresholds(rules);
    expect(s).toBeTruthy();
    const parsed = parseThresholds(s);
    expect(parsed).toEqual(rules);
  });

  it('round-trips three rules', () => {
    const rules: ThresholdRule[] = [
      makeRule({ column: 'volume', low: 0.8, high: 1 }),
      makeRule({
        column: 'area',
        low: 50,
        high: 100,
        lowColor: '#123456',
        midColor: '#abcdef',
        highColor: '#00ff00',
      }),
      makeRule({ column: 'length', low: -10, high: 10 }),
    ];
    const s = serialiseThresholds(rules);
    const parsed = parseThresholds(s);
    expect(parsed).toEqual(rules);
    expect(parsed).toHaveLength(3);
  });

  it('survives a full encodeURIComponent/decodeURIComponent trip', () => {
    const rules: ThresholdRule[] = [
      makeRule({ column: 'volume', low: 0.8, high: 1 }),
      makeRule({ column: 'area', low: 50, high: 100 }),
      makeRule({ column: 'length', low: 1, high: 2 }),
    ];
    const raw = serialiseThresholds(rules);
    const wrapped = encodeURIComponent(raw);
    const unwrapped = decodeURIComponent(wrapped);
    expect(parseThresholds(unwrapped)).toEqual(rules);
  });

  it('caps the number of rules at MAX_RULES', () => {
    const many = Array.from({ length: 10 }, (_, i) =>
      makeRule({ column: `col_${i}` }),
    );
    const parsed = parseThresholds(serialiseThresholds(many));
    expect(parsed.length).toBeLessThanOrEqual(MAX_RULES);
    expect(parsed.length).toBe(MAX_RULES);
  });

  it('keeps the URL payload under the soft length cap', () => {
    const rules = Array.from({ length: MAX_RULES }, (_, i) =>
      makeRule({ column: `col_${i}`, low: 0.123456, high: 9.87654 }),
    );
    const s = serialiseThresholds(rules);
    expect(s.length).toBeLessThanOrEqual(MAX_URL_LENGTH);
  });

  it('tolerates malformed input gracefully', () => {
    expect(parseThresholds('junk')).toEqual([]);
    expect(parseThresholds('col~notanumber~2~ef4444~f59e0b~10b981')).toEqual([]);
    expect(parseThresholds('~0~1~aa~bb~cc')).toEqual([]);
    // A good rule followed by a bad one: good one survives.
    expect(parseThresholds('volume~0~1~ef4444~f59e0b~10b981;broken')).toHaveLength(1);
  });

  it('handles special characters in column names', () => {
    const rules = [makeRule({ column: 'col with;tilde~and~stuff' })];
    const s = serialiseThresholds(rules);
    const parsed = parseThresholds(s);
    expect(parsed[0]?.column).toBe('col with;tilde~and~stuff');
  });
});

describe('thresholds — findRuleForColumn', () => {
  it('returns null when no rules exist', () => {
    expect(findRuleForColumn([], 'volume')).toBeNull();
  });

  it('returns the matching rule', () => {
    const rules = [makeRule({ column: 'area' }), makeRule({ column: 'volume' })];
    expect(findRuleForColumn(rules, 'volume')?.column).toBe('volume');
  });

  it('returns null when no rule binds to the column', () => {
    const rules = [makeRule({ column: 'area' })];
    expect(findRuleForColumn(rules, 'volume')).toBeNull();
  });
});

describe('thresholds — isRuleValid', () => {
  it('accepts a well-formed rule whose column is present', () => {
    expect(isRuleValid(makeRule(), ['volume', 'area'])).toBe(true);
  });

  it('rejects when low >= high', () => {
    expect(isRuleValid(makeRule({ low: 1, high: 0.5 }), ['volume'])).toBe(false);
    expect(isRuleValid(makeRule({ low: 1, high: 1 }), ['volume'])).toBe(false);
  });

  it('rejects when the column is not in the available list', () => {
    expect(isRuleValid(makeRule({ column: 'ghost' }), ['volume'])).toBe(false);
  });

  it('rejects empty column names', () => {
    expect(isRuleValid(makeRule({ column: '' }), ['volume'])).toBe(false);
  });

  it('accepts any column when the available list is empty (no pivot yet)', () => {
    expect(isRuleValid(makeRule(), [])).toBe(true);
  });
});

describe('thresholds — createDefaultRule', () => {
  it('builds a rule with the canonical defaults', () => {
    const r = createDefaultRule('volume');
    expect(r.column).toBe('volume');
    expect(r.lowColor).toBe(DEFAULT_LOW_COLOR);
    expect(r.midColor).toBe(DEFAULT_MID_COLOR);
    expect(r.highColor).toBe(DEFAULT_HIGH_COLOR);
    expect(r.low).toBeLessThan(r.high);
  });
});
