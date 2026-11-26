import { describe, expect, it } from 'vitest';

import type { Live, ModulePaths, PathOut, PlatformMap } from '../api';
import { drivingFields, freshnessOf, layoutDiagram, MIN_CARD_W, phaseColumns, SIDE_CARD_H, traceField } from '../pathsModel';

const live: Live = { count: 3, value: null, latest_at: null, state: 'ok', stale_count: null, active: false, reason: null };

const path = (over: Partial<PathOut>): PathOut => ({
  id: 'x',
  direction: 'out',
  module: 'oe_x',
  entity: 'X',
  via: 'X.id',
  label: '',
  measure: 'count',
  measure_field: null,
  route: '',
  importance: 'supporting',
  breaks: '',
  live,
  ...over,
});

const boq: ModulePaths = {
  module: 'oe_boq',
  declared: true,
  installed: true,
  why: '',
  roles: [],
  project_id: null,
  currency: '',
  entities: [{ id: 'e', model: 'Position', label: '', route: '/boq', measure: 'sum:total', live }],
  paths: [
    path({ id: 'in:costs', direction: 'in', module: 'oe_costs', entity: 'CostItemUsage', via: 'CostItemUsage.cost_item_id' }),
    path({ id: 'out:tender', module: 'oe_tendering', entity: 'TenderPackage', via: 'TenderPackage.boq_id', importance: 'critical' }),
    path({ id: 'out:cost', module: 'oe_costmodel', entity: 'CostLine', via: 'CostLine.boq_position_id' }),
  ],
  parameters: [
    {
      field: 'Position.unit_rate',
      label: '',
      drives: ['Position.total', 'oe_tendering:package_value', 'CostLine.estimate_amount', 'oe_cashflow:curve'],
      drives_paths: ['in:costs', 'out:tender', 'out:cost'],
    },
  ],
  stale: [{ source: 'Position.updated_at', copy_field: 'TenderPackage.metadata_.last_distributed_at', label: '', path_id: 'out:tender', count: 2 }],
  technical: [],
  neighbours: [],
  generated_at: '',
};

describe('module diagram', () => {
  it('puts sources left, consumers right, one pill per card row', () => {
    const g = layoutDiagram(1200, 300, boq.paths);
    expect(g.wide).toBe(true);
    const [src, ...outs] = g.links;
    expect(src!.card.x).toBe(0);
    expect(outs.every((l) => l.card.x > g.centre.x + g.centre.w)).toBe(true);
    expect(g.links.map((l) => l.pill.y)).toEqual(g.links.map((l) => l.card.y + SIDE_CARD_H / 2));
    expect(g.centre.w).toBeGreaterThanOrEqual(MIN_CARD_W);
  });

  it('stacks when three columns do not fit', () => {
    expect(layoutDiagram(600, 300, boq.paths).wide).toBe(false);
  });

  it('draws a module with no paths as the centre alone', () => {
    const g = layoutDiagram(1200, 200, []);
    expect(g.links).toEqual([]);
    expect(g.height).toBe(200);
  });
});

describe('selected path', () => {
  it('lists the fields that drive it, only their targets on that path', () => {
    const tender = boq.paths[1]!;
    expect(drivingFields(boq, tender)).toEqual([{ field: 'Position.unit_rate', label: '', drives: ['oe_tendering:package_value'] }]);
    expect(freshnessOf(boq, tender)).toHaveLength(1);
    expect(freshnessOf(boq, boq.paths[2]!)).toEqual([]);
  });
});

describe('field trace', () => {
  it('follows unit rate from the cost database to tendering and the cost model', () => {
    const tr = traceField(boq, 'Position.unit_rate')!;
    expect(tr.sources.map((p) => p.module)).toEqual(['oe_costs']);
    expect(tr.derived).toEqual(['Position.total']);
    expect(tr.consumers.map((c) => c.module)).toEqual(['oe_tendering', 'oe_costmodel', 'oe_cashflow']);
    expect(tr.consumers[1]!.refs).toEqual(['CostLine.estimate_amount']);
    expect(tr.consumers[2]!.path).toBeNull();
    expect(tr.stale).toHaveLength(1);
  });

  it('returns nothing for a field the module does not declare', () => {
    expect(traceField(boq, 'Position.nope')).toBeNull();
  });
});

describe('platform map', () => {
  const mod = (name: string, phase: string, declared = true) => ({
    name, display_name: name, category: 'core', phase, declared, installed: true, why: '', roles: [], count: null, counts: {},
  });
  const map: PlatformMap = {
    project_id: null,
    currency: '',
    modules: [mod('oe_boq', 'estimate'), mod('oe_takeoff', 'estimate'), mod('oe_tendering', 'tender'), mod('oe_users', 'platform', false)],
    edges: [
      { source: 'oe_takeoff', target: 'oe_boq', kind: 'declared', details: [], importance: 'high', label: '', count: null, active: false, state: 'ok' },
      { source: 'oe_boq', target: 'oe_tendering', kind: 'declared', details: [], importance: 'critical', label: '', count: null, active: false, state: 'ok' },
      { source: 'oe_boq', target: 'oe_users', kind: 'fk', details: [], importance: 'supporting', label: '', count: null, active: false, state: 'ok' },
    ],
    health: [],
    phases: ['site', 'estimate', 'tender', 'platform'],
    generated_at: '',
  };

  it('groups declared modules by the phase from the API, empty phases dropped', () => {
    const cols = phaseColumns(map, 'oe_boq', (m) => m.name);
    expect(cols.map((c) => c.phase)).toEqual(['estimate', 'tender']);
    const rel = Object.fromEntries(cols.flatMap((c) => c.modules.map((m) => [m.module.name, m.relation])));
    expect(rel).toEqual({ oe_boq: 'focus', oe_takeoff: 'in', oe_tendering: 'out' });
  });
});
