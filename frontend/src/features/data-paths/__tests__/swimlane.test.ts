// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import {
  COLUMNS,
  columnOf,
  flowEdges,
  impactOf,
  laneOrder,
  nextNode,
  pathsBetween,
  stagesFrom,
  swimlaneLayout,
  traceEdges,
  fadeFor,
} from '../swimlane';
import { countCrossings } from '../layout';

// The survey-to-payment spine plus a side branch and an unrelated module.
const E = [
  { source: 'oe_survey_core', target: 'oe_surfaces_volumes', kind: 'declared' as const },
  { source: 'oe_surfaces_volumes', target: 'oe_boq', kind: 'declared' as const },
  { source: 'oe_takeoff', target: 'oe_boq', kind: 'declared' as const },
  { source: 'oe_boq', target: 'oe_tendering', kind: 'declared' as const },
  { source: 'oe_boq', target: 'oe_progress', kind: 'fk' as const },
  { source: 'oe_tendering', target: 'oe_contracts', kind: 'declared' as const },
  { source: 'oe_contracts', target: 'oe_finance', kind: 'declared' as const },
  { source: 'oe_finance', target: 'oe_costmodel', kind: 'declared' as const },
  { source: 'oe_costmodel', target: 'oe_full_evm', kind: 'declared' as const },
  { source: 'oe_full_evm', target: 'oe_reporting', kind: 'declared' as const },
  { source: 'oe_boq', target: 'oe_documents', kind: 'depends' as const },
];

describe('stagesFrom', () => {
  it('walks two steps back and four forward from the focus', () => {
    const stages = stagesFrom('oe_boq', flowEdges(E));
    expect(stages.get('oe_boq')).toBe(0);
    expect(stages.get('oe_surfaces_volumes')).toBe(-1);
    expect(stages.get('oe_takeoff')).toBe(-1);
    expect(stages.get('oe_survey_core')).toBe(-2);
    expect(stages.get('oe_tendering')).toBe(1);
    expect(stages.get('oe_progress')).toBe(1);
    expect(stages.get('oe_contracts')).toBe(2);
    expect(stages.get('oe_costmodel')).toBe(4);
    // Five steps forward is beyond the window.
    expect(stages.has('oe_full_evm')).toBe(false);
  });

  it('leaves dependency-only links out unless asked', () => {
    expect(stagesFrom('oe_boq', flowEdges(E)).has('oe_documents')).toBe(false);
    expect(stagesFrom('oe_boq', flowEdges(E, { technical: true })).get('oe_documents')).toBe(1);
  });

  it('maps stages onto the five named columns', () => {
    expect(COLUMNS.map((c) => c.id)).toEqual(['sources', 'supplies', 'here', 'uses', 'result']);
    expect(columnOf(-2)).toBe('sources');
    expect(columnOf(0)).toBe('here');
    expect(columnOf(3)).toBe('result');
  });
});

describe('impactOf', () => {
  it('counts everything downstream, the end results and the sources at the start', () => {
    const impact = impactOf('oe_boq', flowEdges(E), 12);
    expect(impact.affected).toBe(7);
    expect(impact.results.sort()).toEqual(['oe_progress', 'oe_reporting']);
    expect(impact.roots.sort()).toEqual(['oe_survey_core', 'oe_takeoff']);
    expect(impact.level).toBe('high');
    expect(impact.percent).toBe(64);
  });

  it('calls a module with nothing downstream an endpoint', () => {
    const impact = impactOf('oe_reporting', flowEdges(E), 12);
    expect(impact.affected).toBe(0);
    expect(impact.level).toBe('endpoint');
  });

  it('is medium between one and five modules with fewer than three results', () => {
    expect(impactOf('oe_finance', flowEdges(E), 12).level).toBe('medium');
  });
});

describe('pathsBetween', () => {
  it('lights every module and link between a hovered source and the focus', () => {
    const lit = pathsBetween('oe_survey_core', 'oe_boq', flowEdges(E));
    expect([...lit.nodes].sort()).toEqual(['oe_boq', 'oe_surfaces_volumes', 'oe_survey_core']);
    expect(lit.edges.has('oe_survey_core>oe_surfaces_volumes')).toBe(true);
    expect(lit.edges.has('oe_takeoff>oe_boq')).toBe(false);
  });

  it('works downstream too', () => {
    const lit = pathsBetween('oe_finance', 'oe_boq', flowEdges(E));
    expect(lit.nodes.has('oe_contracts')).toBe(true);
    expect(lit.nodes.has('oe_progress')).toBe(false);
  });
});

describe('swimlaneLayout', () => {
  const lanes: Record<string, string> = {
    oe_survey_core: 'grp_survey',
    oe_surfaces_volumes: 'grp_survey',
    oe_takeoff: 'grp_takeoff',
    oe_boq: 'grp_estimating',
    oe_tendering: 'grp_procurement',
    oe_progress: 'grp_site',
    oe_contracts: 'grp_commercial',
    oe_finance: 'grp_finance',
    oe_costmodel: 'grp_finance',
  };
  const edges = flowEdges(E);
  const stages = stagesFrom('oe_boq', edges);
  const nodes = [...stages].map(([id, stage]) => ({ id, stage, lane: lanes[id] ?? 'platform' }));

  it('puts each lane in its own band and each stage in its own column', () => {
    const out = swimlaneLayout(nodes, edges, { orientation: 'landscape' });
    const survey = out.lanes.find((l) => l.id === 'grp_survey')!;
    const pos = out.nodes.get('oe_survey_core')!;
    expect(pos.y).toBeGreaterThanOrEqual(survey.y);
    expect(pos.y).toBeLessThan(survey.y + survey.height);
    expect(out.nodes.get('oe_survey_core')!.x).toBeLessThan(out.nodes.get('oe_surfaces_volumes')!.x);
    expect(out.nodes.get('oe_boq')!.x).toBeLessThan(out.nodes.get('oe_tendering')!.x);
  });

  it('turns the picture when portrait is asked for', () => {
    const out = swimlaneLayout(nodes, edges, { orientation: 'portrait' });
    expect(out.nodes.get('oe_survey_core')!.y).toBeLessThan(out.nodes.get('oe_boq')!.y);
    const survey = out.lanes.find((l) => l.id === 'grp_survey')!;
    expect(out.nodes.get('oe_survey_core')!.x).toBeGreaterThanOrEqual(survey.x);
  });

  it('orders lanes so the flow reads top to bottom', () => {
    const order = laneOrder(nodes);
    expect(order.indexOf('grp_survey')).toBeLessThan(order.indexOf('grp_finance'));
  });

  it('keeps a chain free of crossings', () => {
    const out = swimlaneLayout(nodes, edges, { orientation: 'landscape' });
    expect(countCrossings(out.columns, edges)).toBe(0);
  });
});

describe('fade, keyboard and traces', () => {
  it('fades modules far from the focus', () => {
    expect(fadeFor(0)).toBe(1);
    expect(fadeFor(1)).toBe(1);
    expect(fadeFor(4)).toBeLessThan(fadeFor(2));
  });

  it('moves to the nearest module in the pressed direction', () => {
    const pos = new Map([
      ['a', { x: 0, y: 0 }],
      ['b', { x: 300, y: 10 }],
      ['c', { x: 300, y: 400 }],
      ['d', { x: 0, y: 200 }],
    ]);
    expect(nextNode('a', 'right', pos)).toBe('b');
    expect(nextNode('a', 'down', pos)).toBe('d');
    expect(nextNode('b', 'left', pos)).toBe('a');
    expect(nextNode('a', 'up', pos)).toBe('a');
  });

  it('lists the links a trace walks up to the current step, skipping steps inside one module', () => {
    const steps = ['oe_survey_core', 'oe_surfaces_volumes', 'oe_surfaces_volumes', 'oe_boq'].map((module) => ({ module }));
    expect(traceEdges(steps, 3)).toEqual(['oe_survey_core>oe_surfaces_volumes', 'oe_surfaces_volumes>oe_boq']);
    expect(traceEdges(steps, 1)).toEqual(['oe_survey_core>oe_surfaces_volumes']);
  });
});
