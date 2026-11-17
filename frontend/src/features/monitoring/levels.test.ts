// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { SeriesEntry } from './api';
import { bandLines, chartGeometry, fmtMm, fmtRate, levelVariant } from './levels';

const entry = (at: string, mm: number, level: SeriesEntry['level'] = 'ok'): SeriesEntry => ({
  at, e: null, n: null, z: null, value: null, displacement_mm: mm, rate_mm_day: null, level,
});

describe('monitoring levels', () => {
  it('formats the course numbers with a real minus sign', () => {
    expect(fmtMm(-23)).toBe('−23.0');
    expect(fmtRate(-1.14)).toBe('−1.14');
    expect(fmtMm(null)).toBe('');
  });

  it('maps levels to badge colours', () => {
    expect(levelVariant('alarm')).toBe('error');
    expect(levelVariant('alert')).toBe('warning');
    expect(levelVariant('ok')).toBe('success');
    expect(levelVariant('none')).toBe('neutral');
  });

  it('draws only the limits that are set, rising', () => {
    const t = { alert_mm: 10, action_mm: 20, alarm_mm: null, rate_alert: null, rate_action: null, rate_alarm: null };
    expect(bandLines(t)).toEqual([
      { level: 'alert', mm: 10 },
      { level: 'action', mm: 20 },
    ]);
    expect(bandLines(null)).toEqual([]);
  });

  it('puts the bands on the side settlement moves and keeps them in range', () => {
    const series = [entry('2026-10-09', 0), entry('2026-10-16', -15), entry('2026-10-23', -21)];
    const g = chartGeometry(series, [{ mm: 10 }, { mm: 20 }, { mm: 30 }], 400, 200);
    expect(g.sign).toBe(-1);
    expect(g.points[0]!.y).toBeLessThan(g.points[2]!.y);
    expect(g.yOf(-30)).toBeGreaterThanOrEqual(0);
    expect(g.yOf(-30)).toBeLessThanOrEqual(200);
    expect(g.points[0]!.x).toBeLessThan(g.points[2]!.x);
  });

  it('centres a single reading', () => {
    const g = chartGeometry([entry('2026-10-09', 0)], [], 400, 200);
    expect(g.points[0]!.x).toBe(200);
  });
});
