// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { formatPredecessors, formatResources, visibleColumns } from './ganttColumns';

describe('formatPredecessors', () => {
  it('writes them the way a planner does', () => {
    expect(
      formatPredecessors([
        { code: '01.02', type: 'FS', lag: 3 },
        { code: '01.04', type: 'SS', lag: 0 },
      ]),
    ).toBe('01.02 FS+3; 01.04 SS');
  });

  it('leaves a plain finish-to-start link as the bare code', () => {
    expect(formatPredecessors([{ code: '02.01', type: 'FS', lag: 0 }])).toBe('02.01');
    expect(formatPredecessors([{ code: '02.01' }])).toBe('02.01');
    expect(formatPredecessors([{ code: '02.01', type: null, lag: null }])).toBe('02.01');
  });

  it('shows a lead with its sign and normalises the type', () => {
    expect(formatPredecessors([{ code: 'A', type: 'ff', lag: -2 }])).toBe('A FF-2');
    expect(formatPredecessors([{ code: 'A', type: 'FS', lag: -1 }])).toBe('A FS-1');
  });

  it('is empty without links', () => {
    expect(formatPredecessors([])).toBe('');
    expect(formatPredecessors(undefined)).toBe('');
  });
});

describe('formatResources', () => {
  it('names a crew by its size', () => {
    expect(formatResources([{ name: 'Labour', count: 4 }, { name: 'Crane', count: 1 }])).toBe('Labour ×4, Crane');
    expect(formatResources(undefined)).toBe('');
  });
});

describe('visibleColumns', () => {
  it('keeps table order and always has the name', () => {
    expect(visibleColumns(['progress', 'wbs']).map((c) => c.id)).toEqual(['wbs', 'name', 'progress']);
  });
});
