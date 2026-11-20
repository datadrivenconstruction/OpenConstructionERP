import { describe, expect, it } from 'vitest';
import { acknowledgeable, bandRange, fmtMm, hasBlockingFinding, outShare, verticalProfiles } from './scanDesign';
import { deviationExportUrl, deviationPointsPath } from './scanDesignApi';
import type { ToleranceProfile } from '@/features/setting-out/api';

const profile = (key: string, items: ToleranceProfile['items']): ToleranceProfile => ({
  key,
  name: key,
  source: 'demo',
  country: '',
  reference: '',
  items,
});

describe('scan against design helpers', () => {
  it('reads the riverside share out of tolerance', () => {
    expect(outShare({ within_pct: 93.09, points_compared: 24321 })).toBe(6.91);
    expect(outShare({ within_pct: null, points_compared: 0 })).toBeNull();
  });

  it('labels the bands at the tolerance and twice the tolerance', () => {
    expect(bandRange('within', 10)).toBe('±10');
    expect(bandRange('high', 10)).toBe('+10 .. +20');
    expect(bandRange('far_low', 7.5)).toBe('< -15');
  });

  it('keeps only profiles with a vertical tolerance, item first then default', () => {
    const rows = verticalProfiles([
      profile('demo', { default: { h_mm: 10, v_mm: 10 } }),
      profile('plan', { default: { h_mm: 5, v_mm: null } }),
      profile('slab', { other: { h_mm: 5, v_mm: 4 }, default: { h_mm: 5, v_mm: 9 } }),
    ]);
    expect(rows.map((r) => [r.key, r.vMm])).toEqual([
      ['demo', 10],
      ['slab', 4],
    ]);
  });

  it('formats millimetres without trailing zeros', () => {
    expect(fmtMm(11.91)).toBe('11.9');
    expect(fmtMm(44)).toBe('44');
    expect(fmtMm(null)).toBe('-');
  });

  it('acknowledges warnings and stops on errors', () => {
    const f = [
      { rule_id: 'SRV-080', severity: 'warning' },
      { rule_id: 'SRV-001', severity: 'info' },
    ];
    expect(acknowledgeable(f)).toEqual(['SRV-080']);
    expect(hasBlockingFinding(f)).toBe(false);
    expect(hasBlockingFinding([{ severity: 'error' }])).toBe(true);
  });

  it('builds the report urls', () => {
    expect(deviationPointsPath('r1')).toBe('/v1/pointcloud/deviation-reports/r1/points');
    expect(deviationExportUrl('r1', 'csv', 'de')).toBe('/api/v1/pointcloud/deviation-reports/r1/export?format=csv&locale=de');
  });
});
