// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Site sensor​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ helper tests.
import { describe, expect, it } from 'vitest';
import { failedRules, ruleLight, ruleMessage, tallyRules, type RuleResult } from '@/shared/lib/ruleResults';
import {
  countOnline,
  groupByKind,
  isOnline,
  isoFromLocal,
  overLimit,
  strengthProgressPct,
  struckBelowTarget,
} from './sensorData';

const NOW = Date.parse('2026-10-26T12:00:00Z');
const dev = (kind: string, minutesAgo: number | null, active = true) => ({
  kind,
  active,
  offline_after_minutes: 60,
  last_seen_at: minutesAgo === null ? null : new Date(NOW - minutesAgo * 60_000).toISOString(),
});

describe('groupByKind', () => {
  it('orders groups by the fixed kind order and drops empty ones', () => {
    const groups = groupByKind([dev('weather', 1), dev('concrete_maturity', 1), dev('weather', 2), dev('unknown', 1)]);
    expect(groups.map((g) => g.kind)).toEqual(['concrete_maturity', 'weather']);
    expect(groups[1]?.devices).toHaveLength(2);
  });
});

describe('isOnline', () => {
  it('is online only when active and inside the offline window', () => {
    expect(isOnline(dev('noise', 30), NOW)).toBe(true);
    expect(isOnline(dev('noise', 61), NOW)).toBe(false);
    expect(isOnline(dev('noise', null), NOW)).toBe(false);
    expect(isOnline(dev('noise', 5, false), NOW)).toBe(false);
  });
  it('counts online devices', () => {
    expect(countOnline([dev('noise', 5), dev('noise', 500)], NOW)).toBe(1);
  });
});

describe('strengthProgressPct', () => {
  it('is a share of the target, clamped to 0-100', () => {
    expect(strengthProgressPct(10, 20)).toBe(50);
    expect(strengthProgressPct(30, 20)).toBe(100);
    expect(strengthProgressPct(-1, 20)).toBe(0);
  });
  it('is null when strength or target is unknown', () => {
    expect(strengthProgressPct(null, 20)).toBeNull();
    expect(strengthProgressPct(10, null)).toBeNull();
    expect(strengthProgressPct(10, 0)).toBeNull();
  });
});

describe('limits and strikes', () => {
  it('flags a reading above the limit', () => {
    expect(overLimit(81, '80')).toBe(true);
    expect(overLimit(80, '80')).toBe(false);
    expect(overLimit(90, null)).toBe(false);
  });
  it('flags formwork struck below the target', () => {
    const base = { struck_at: '2026-10-26T10:00:00Z', target_strength_mpa: '20' };
    expect(struckBelowTarget({ ...base, strength_at_strike_mpa: '15.5' })).toBe(true);
    expect(struckBelowTarget({ ...base, strength_at_strike_mpa: '20.0' })).toBe(false);
    expect(struckBelowTarget({ ...base, struck_at: null, strength_at_strike_mpa: '1' })).toBe(false);
  });
  it('parses local date-time values', () => {
    expect(isoFromLocal('')).toBeNull();
    expect(isoFromLocal('not a date')).toBeNull();
    expect(isoFromLocal('2026-10-26T08:30')).toMatch(/^2026-10-26T/);
  });
});

describe('rule results traffic lights', () => {
  const r = (passed: boolean, severity: string, details?: Record<string, unknown>): RuleResult => ({
    rule_id: 'x',
    passed,
    severity,
    message: 'm',
    details,
  });
  it('maps severity to a light and passed to green', () => {
    expect(ruleLight(r(true, 'error'))).toBe('green');
    expect(ruleLight(r(false, 'error'))).toBe('red');
    expect(ruleLight(r(false, 'warning'))).toBe('amber');
    expect(ruleLight(r(false, 'info'))).toBe('blue');
  });
  it('tallies and orders failures worst first', () => {
    const list = [r(false, 'info'), r(true, 'error'), r(false, 'error'), r(false, 'warning')];
    expect(tallyRules(list)).toEqual({ red: 1, amber: 1, blue: 1, green: 1 });
    expect(failedRules(list).map((x) => ruleLight(x))).toEqual(['red', 'amber', 'blue']);
  });
  it('splits the message key from its params', () => {
    const msg = ruleMessage(r(false, 'error', { message_key: 'siteSensors.rules.sensor_online', device: 'S1' }));
    expect(msg).toEqual({ key: 'siteSensors.rules.sensor_online', params: { device: 'S1' } });
    expect(ruleMessage(r(false, 'error')).key).toBeNull();
  });
});
