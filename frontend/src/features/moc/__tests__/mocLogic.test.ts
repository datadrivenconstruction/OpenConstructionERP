// Pure-logic tests for the MoC module: REST helpers, status transitions,
// insights builder and guide i18n keys.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  ...apiMocks,
}));

import {
  fetchMoCEntries,
  getMoCEntry,
  createMoCEntry,
  updateMoCEntry,
  deleteMoCEntry,
  transitionMoCEntry,
  addMoCImpact,
  deleteMoCImpact,
  type MoCTransition,
} from '../api';
import { buildMocInsights } from '../mocInsights';
import { mocGuide } from '../mocGuide';

const t = ((key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key) as never;

describe('moc api', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.apiGet.mockResolvedValue([]);
    apiMocks.apiPost.mockResolvedValue({});
    apiMocks.apiPatch.mockResolvedValue({});
    apiMocks.apiDelete.mockResolvedValue(undefined);
  });

  it('lists by project and adds the status filter only when set', async () => {
    await fetchMoCEntries('p1');
    expect(apiMocks.apiGet).toHaveBeenLastCalledWith('/v1/moc/?project_id=p1');
    await fetchMoCEntries('p1', '');
    expect(apiMocks.apiGet).toHaveBeenLastCalledWith('/v1/moc/?project_id=p1');
    await fetchMoCEntries('p1', 'accepted');
    expect(apiMocks.apiGet).toHaveBeenLastCalledWith('/v1/moc/?project_id=p1&status=accepted');
  });

  it('get, create, update and delete use the entry routes', async () => {
    await getMoCEntry('m1');
    expect(apiMocks.apiGet).toHaveBeenLastCalledWith('/v1/moc/m1');
    await createMoCEntry({ project_id: 'p1', title: 'Swap pump' });
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/moc/', { project_id: 'p1', title: 'Swap pump' });
    await updateMoCEntry('m1', { risk_level: 'high' });
    expect(apiMocks.apiPatch).toHaveBeenLastCalledWith('/v1/moc/m1', { risk_level: 'high' });
    await deleteMoCEntry('m1');
    expect(apiMocks.apiDelete).toHaveBeenLastCalledWith('/v1/moc/m1');
  });

  it.each<[MoCTransition, string]>([
    ['review', '/v1/moc/m1/review'],
    ['accept', '/v1/moc/m1/accept'],
    ['decline', '/v1/moc/m1/decline'],
    ['implement', '/v1/moc/m1/implement'],
  ])('transition %s posts to the matching FSM route', async (action, url) => {
    await transitionMoCEntry('m1', action, 'ok');
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith(url, { notes: 'ok' });
  });

  it('an empty transition note is sent as undefined, not an empty string', async () => {
    await transitionMoCEntry('m1', 'review', '');
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/moc/m1/review', { notes: undefined });
  });

  it('adds and removes impact lines under the entry', async () => {
    await addMoCImpact('m1', { impact_area: 'cost' });
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/moc/m1/impacts', { impact_area: 'cost' });
    await deleteMoCImpact('m1', 'i1');
    expect(apiMocks.apiDelete).toHaveBeenLastCalledWith('/v1/moc/m1/impacts/i1');
  });
});

describe('buildMocInsights', () => {
  it('returns an empty dataset for no entries', () => {
    const r = buildMocInsights([], '', t);
    expect(r.datasets[0]!.rows).toEqual([]);
    expect(r.datasets[0]!.currency).toBe('');
    expect(r.builtins.length).toBeGreaterThan(0);
  });

  it('derives the open / accepted / implemented / high-risk flags', () => {
    const r = buildMocInsights(
      [
        { code: 'A', status: 'proposed', risk_level: 'critical', cost_impact: '1500.50', proposed_at: '2026-03-02T00:00:00Z' },
        { code: 'B', status: 'reviewed', risk_level: 'low' },
        { code: 'C', status: 'accepted', risk_level: 'high', schedule_delta_days: 7 },
        { code: 'D', status: 'implemented' },
        { code: 'E', status: 'declined', cost_impact: 'abc' },
      ],
      'EUR',
      t,
    );
    const rows = Object.fromEntries(r.datasets[0]!.rows.map((x) => [x.code, x]));
    expect(rows.A).toMatchObject({ open: 1, highrisk: 1, cost: 1500.5, month: '2026-03' });
    expect(rows.B).toMatchObject({ open: 1, highrisk: 0 });
    expect(rows.C).toMatchObject({ accepted: 1, highrisk: 1, schedule: 7 });
    expect(rows.D).toMatchObject({ implemented: 1, open: 0, risk: 'Medium' });
    expect(rows.E).toMatchObject({ cost: 0, open: 0, accepted: 0 });
    expect(r.datasets[0]!.currency).toBe('EUR');
  });

  it('uses English fallbacks for known codes and humanizes unknown ones', () => {
    const r = buildMocInsights(
      [
        { code: 'A', status: 'proposed', change_category: 'organizational' },
        { code: 'B', status: 'on_hold', change_category: 'site_logistics' },
        { code: 'C', status: 'proposed' },
      ],
      '',
      t,
    );
    const rows = Object.fromEntries(r.datasets[0]!.rows.map((x) => [x.code, x]));
    expect(rows.A).toMatchObject({ status: 'Proposed', category: 'Organisational' });
    expect(rows.B).toMatchObject({ status: 'On hold', category: 'Site logistics' });
    expect(rows.C!.category).toBe('Other');
  });

  it('sorts by proposed date; undated entries come first and get n/a month', () => {
    const r = buildMocInsights(
      [
        { code: 'late', proposed_at: '2026-05-01T00:00:00Z' },
        { code: 'none' },
        { code: 'early', proposed_at: '2026-01-01T00:00:00Z' },
      ],
      '',
      t,
    );
    expect(r.datasets[0]!.rows.map((x) => x.code)).toEqual(['none', 'early', 'late']);
    expect(r.datasets[0]!.rows[0]!.month).toBe('n/a');
  });

  it('reads labels through moc.* i18n keys only', () => {
    const seen: string[] = [];
    const spy = ((k: string, o?: { defaultValue?: string }) => {
      seen.push(k);
      return o?.defaultValue ?? k;
    }) as never;
    buildMocInsights([{ code: 'A', status: 'accepted', change_category: 'safety', risk_level: 'high' }], '', spy);
    expect(seen.filter((k) => !k.startsWith('moc.'))).toEqual([]);
    expect(seen).toEqual(expect.arrayContaining(['moc.status_accepted', 'moc.category_safety', 'moc.risk_high']));
  });

  it('builtins reference only existing dataset fields', () => {
    const r = buildMocInsights([], '', t);
    const keys = new Set(r.datasets[0]!.fields.map((f) => f.key));
    for (const b of r.builtins) {
      if (b.dimension) expect(keys.has(b.dimension)).toBe(true);
      if (b.measure) expect(keys.has(b.measure)).toBe(true);
    }
  });
});

describe('mocGuide', () => {
  it('uses only guide.moc.* keys with English defaults', () => {
    const entries: [string, string][] = [[mocGuide.titleKey, mocGuide.titleDefault]];
    if (mocGuide.ctaKey) entries.push([mocGuide.ctaKey, mocGuide.ctaDefault ?? '']);
    for (const s of mocGuide.sections) {
      entries.push([s.titleKey, s.titleDefault], [s.bodyKey, s.bodyDefault]);
    }
    for (const [k, d] of entries) {
      expect(k.startsWith('guide.moc.')).toBe(true);
      expect(d.trim().length).toBeGreaterThan(0);
    }
    expect(new Set(entries.map(([k]) => k)).size).toBe(entries.length);
  });
});
