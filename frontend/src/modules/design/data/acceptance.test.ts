import { describe, expect, it } from 'vitest';
import { attentionRows, baseOf, blockers, collapsedByNoMatch, money, movingRows, pending, qty, unitLabel, type Impact, type ImpactRow } from './acceptance';
import type { RevisionView } from './revisions';

const rev = (n: number, over: Partial<RevisionView> = {}): RevisionView => ({
  revision_id: `r${n}`, project_id: 'p', number: n, parent_revision_id: n > 1 ? `r${n - 1}` : null, status: 'shared',
  source_kind: 'editor', depth_level: 'D2', message: '', bim_model_id: `m${n}`, decided_by: null, decided_at: null,
  decision_comment: null, created_at: '2026-01-01T00:00:00Z', ...over,
});
const row = (rule: string, over: Partial<ImpactRow> = {}): ImpactRow => ({
  rule, label: rule, cost_group: '331', unit: 'm2', position_id: 'x', ordinal: '1', new_position: false,
  current_quantity: '10', model_quantity_now: '10', model_quantity_new: '10', new_quantity: '10', quantity_delta: '0',
  override: false, override_quantity: null, unit_rate: '100', cost_delta: '0', flags: [],
  elements: { before: 1, after: 1, added: [], removed: [], added_count: 0, removed_count: 0 }, ...over,
});

describe('rows', () => {
  const rows = [
    row('same'),
    row('moves', { quantity_delta: '2', cost_delta: '200' }),
    row('override', { override: true, flags: ['override'] }),
    row('nomatch', { flags: ['no_match'] }),
    row('new', { new_position: true, new_quantity: '5', cost_delta: '500' }),
  ];

  it('needs-a-look rows are overrides and anything flagged', () => {
    expect(attentionRows(rows).map((r) => r.rule)).toEqual(['override', 'nomatch']);
  });

  it('moving rows change a quantity or cost, or are new; unchanged ones are left out', () => {
    expect(movingRows(rows).map((r) => r.rule)).toEqual(['moves', 'new']);
  });

  it('an empty impact has neither', () => {
    expect(attentionRows([])).toEqual([]);
    expect(movingRows([])).toEqual([]);
  });
});

describe('blockers', () => {
  const r1 = rev(1, { status: 'published' });
  const r2 = rev(2);

  it('nothing blocks a manager on a pending revision built on the latest accepted one', () => {
    expect(blockers(r2, true, r1)).toEqual([]);
  });

  it('a first revision is never stale when nothing was accepted yet', () => {
    expect(blockers(rev(1), true, null)).toEqual([]);
  });

  it('a non-manager is blocked by role', () => {
    expect(blockers(r2, false, r1)).toEqual(['role']);
  });

  it('while the role is still loading nothing is claimed about it', () => {
    expect(blockers(r2, undefined, r1)).toEqual([]);
  });

  it('a decided revision is blocked by status, not by being stale', () => {
    expect(blockers({ ...r2, status: 'rejected' }, true, r1)).toEqual(['status']);
    expect(blockers({ ...r2, status: 'published' }, true, r1)).toEqual(['status']);
  });

  it('a revision based on something that is no longer the latest accepted one is stale', () => {
    expect(blockers(rev(3, { parent_revision_id: 'r1' }), true, rev(2, { status: 'published' }))).toEqual(['stale']);
    expect(blockers(rev(2, { parent_revision_id: null }), true, r1)).toEqual(['stale']);
  });

  it('a revision built on one that still waits is next in line, not stale', () => {
    const r3 = rev(3, { parent_revision_id: 'r2' });
    expect(blockers(r3, true, r1, [r3, r2, r1])).toEqual(['waiting']);
    expect(blockers(r3, true, r1, [r3, { ...r2, status: 'rejected' }, r1])).toEqual(['stale']);
  });

  it('collects every reason in the order a person can fix them', () => {
    expect(blockers(rev(3, { parent_revision_id: 'r1' }), false, rev(2, { status: 'published' }))).toEqual(['role', 'stale']);
  });

  it('no revision, no reasons', () => {
    expect(blockers(null, false, null)).toEqual([]);
  });
});

describe('lists', () => {
  it('pending revisions come oldest first and exclude decided ones', () => {
    const all = [rev(4), rev(3, { status: 'rejected' }), rev(2), rev(1, { status: 'published' })];
    expect(pending(all).map((r) => r.number)).toEqual([2, 4]);
  });

  it('the base is the parent revision, or none for the first', () => {
    const all = [rev(1), rev(2)];
    expect(baseOf(all[1]!, all)?.number).toBe(1);
    expect(baseOf(all[0]!, all)).toBeNull();
  });
});

describe('money', () => {
  it('groups digits and keeps the sign', () => {
    expect(money('-1234.5', 'en')).toBe('-1,234.50');
    expect(money('0', 'en')).toBe('0.00');
  });

  it('follows the language', () => {
    expect(money('1234.5', 'de')).toBe('1.234,50');
  });

  it('hands back what it cannot read', () => {
    expect(money('n/a')).toBe('n/a');
  });
});

describe('quantities and units', () => {
  it('formats in the page language without padded zeros', () => {
    expect(qty('28.4000', 'de')).toBe('28,4');
    expect(qty('0.0000', 'en')).toBe('0');
    expect(qty('1234.5', 'en')).toBe('1,234.5');
    expect(qty('n/a')).toBe('n/a');
  });
  it('writes exponents and pieces', () => {
    expect(unitLabel('m2')).toBe('m\u00b2');
    expect(unitLabel('m3')).toBe('m\u00b3');
    expect(unitLabel('pcs', 'de')).toBe('Stk');
    expect(unitLabel('pcs', 'en')).toBe('pcs');
    expect(unitLabel('kg')).toBe('kg');
  });
});

describe('collapsedByNoMatch', () => {
  const impact = (rows: ImpactRow[], current: string, after: string): Impact => ({
    schema: 'ddc-impact/1', revision_id: 'r', estimate: true, rows, model_delta_by_type: [],
    totals: { current, after, delta: String(Number(after) - Number(current)), unpriced_positions: 0 },
  });
  it('is true when the total falls to zero', () => {
    expect(collapsedByNoMatch(impact([row('a')], '1000', '0'))).toBe(true);
  });
  it('is true when a no-match position lowers the cost', () => {
    expect(collapsedByNoMatch(impact([row('a', { flags: ['no_match'], cost_delta: '-5' })], '1000', '995'))).toBe(true);
  });
  it('is false for an ordinary change', () => {
    expect(collapsedByNoMatch(impact([row('a', { cost_delta: '-5' })], '1000', '995'))).toBe(false);
  });
});
