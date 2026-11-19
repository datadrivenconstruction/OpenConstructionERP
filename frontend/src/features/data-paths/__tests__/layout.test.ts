import { describe, expect, it } from 'vitest';

import { chainOf, countCrossings, layeredLayout, neighbourhood, orderColumns } from '../layout';

describe('data path layout', () => {
  const edges = [
    { source: 'a', target: 'y' },
    { source: 'b', target: 'x' },
  ];

  it('control: the naive order crosses, the sweeps untangle it', () => {
    expect(countCrossings([['a', 'b'], ['x', 'y']], edges)).toBe(1);
    const cols = orderColumns(
      [
        { id: 'a', stage: 0 },
        { id: 'b', stage: 0 },
        { id: 'x', stage: 1 },
        { id: 'y', stage: 1 },
      ],
      edges,
      2,
    );
    expect(countCrossings(cols, edges)).toBe(0);
  });

  it('puts stages left to right and platform modules in a band below', () => {
    const pos = layeredLayout(
      [
        { id: 'boq', stage: 1 },
        { id: 'takeoff', stage: 0 },
        { id: 'users', stage: 6 },
      ],
      [{ source: 'takeoff', target: 'boq' }],
    );
    expect(pos.get('takeoff')!.x).toBeLessThan(pos.get('boq')!.x);
    expect(pos.get('users')!.y).toBeGreaterThan(pos.get('boq')!.y);
  });

  it('a chain reaches every module upstream and downstream', () => {
    const chain = [
      { source: 'takeoff', target: 'boq' },
      { source: 'boq', target: 'tendering' },
      { source: 'tendering', target: 'contracts' },
    ];
    const { up, down } = chainOf('boq', chain);
    expect([...up]).toEqual(['takeoff']);
    expect([...down].sort()).toEqual(['contracts', 'tendering']);
    expect([...neighbourhood('boq', chain, 1)].sort()).toEqual(['boq', 'takeoff', 'tendering']);
  });
});
