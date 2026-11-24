import { describe, expect, it } from 'vitest';

import type { FlowCard, FlowModel } from '../flowModel';
import { findGaps, gapOf, liveCards, moduleNames } from '../storyModel';

const card = (over: Partial<FlowCard>): FlowCard => ({
  id: 'p',
  direction: 'in',
  module: 'oe_boq',
  moduleLabel: 'BOQ',
  entityLabel: 'Positions',
  count: 10,
  value: null,
  valueText: null,
  isMoney: false,
  state: 'ok',
  staleCount: null,
  staleLabel: null,
  importance: 'high',
  importanceLabel: 'High',
  breaksText: null,
  active: true,
  href: '/boq',
  tone: '',
  sentence: '',
  ...over,
});

const model = (inputs: FlowCard[], outputs: FlowCard[] = [], hasProject = true): FlowModel => ({
  module: 'oe_contracts',
  moduleLabel: 'Contracts',
  why: null,
  declared: true,
  hasProject,
  currency: 'EUR',
  inputs,
  outputs,
  entities: [],
  params: [],
  tone: '',
});

describe('storyModel', () => {
  it('an empty critical input is a gap, an empty supporting one is not', () => {
    const gaps = findGaps(
      model([card({ id: 'a', count: 0, importance: 'supporting' }), card({ id: 'b', count: 0, importance: 'critical' })]),
    );
    expect(gaps.map((g) => [g.card.id, g.kind])).toEqual([['b', 'empty']]);
  });

  it('without a project nothing is empty, broken links still are gaps', () => {
    expect(gapOf(card({ count: 0 }), false)).toBeNull();
    expect(gapOf(card({ state: 'broken' }), false)).toBe('broken');
  });

  it('stale copies are named before they are read as fine', () => {
    expect(gapOf(card({ staleCount: 3 }), true)).toBe('stale');
  });

  it('orders gaps critical first and live cards skip empty ones', () => {
    const m = model([card({ id: 'h', count: 0 })], [card({ id: 'c', direction: 'out', count: 0, importance: 'critical' })]);
    expect(findGaps(m).map((g) => g.card.id)).toEqual(['c', 'h']);
    expect(liveCards([card({ id: 'x', count: 0 }), card({ id: 'y', count: 4 })], true).map((c) => c.id)).toEqual(['y']);
  });

  it('names each module once and counts the rest', () => {
    const cards = ['A', 'B', 'B', 'C', 'D'].map((l, i) => card({ id: String(i), moduleLabel: l }));
    expect(moduleNames(cards)).toEqual({ names: ['A', 'B', 'C'], more: 1 });
  });
});
