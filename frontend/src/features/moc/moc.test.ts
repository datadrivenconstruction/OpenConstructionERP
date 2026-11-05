import { describe, expect, it } from 'vitest';
import { buildMocInsights } from './mocInsights';

const t = ((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k) as never;

describe('buildMocInsights', () => {
  const byCode = () => {
    const all = buildMocInsights(
      [
        { code: 'MOC-2', title: 'Slab', status: 'accepted', change_category: 'design', risk_level: 'high', cost_impact: '1500.5', schedule_delta_days: 4, proposed_at: '2026-03-10T00:00:00Z' },
        { code: 'MOC-1', title: 'Pump', status: 'proposed', risk_level: 'low' },
        { code: 'MOC-3', title: 'Duct', status: 'implemented', change_category: 'zzz_new', risk_level: 'critical', cost_impact: 'n/a' },
      ],
      'EUR',
      t,
    ).datasets[0]!.rows;
    return (c: string) => all.find((r) => r.code === c)!;
  };

  it('flags open, accepted, implemented and high-risk changes', () => {
    const r = byCode();
    const [a, b, c] = [r('MOC-2'), r('MOC-1'), r('MOC-3')];
    expect(a).toMatchObject({ accepted: 1, open: 0, highrisk: 1, status: 'Accepted', category: 'Design' });
    expect(b).toMatchObject({ open: 1, highrisk: 0, category: 'Other' });
    expect(c).toMatchObject({ implemented: 1, highrisk: 1 });
  });
  it('coerces money and days, and humanizes an unknown category', () => {
    const r = byCode();
    const [a, c] = [r('MOC-2'), r('MOC-3')];
    expect(a).toMatchObject({ cost: 1500.5, schedule: 4, month: '2026-03' });
    expect(c).toMatchObject({ cost: 0, schedule: 0, category: 'Zzz new' });
  });
  it('carries the currency and an empty register gives no rows', () => {
    expect(buildMocInsights([], 'EUR', t).datasets[0]).toMatchObject({ currency: 'EUR', rows: [] });
  });
});
