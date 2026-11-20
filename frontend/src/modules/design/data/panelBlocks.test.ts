import { beforeEach, describe, expect, it } from 'vitest';
import { BLOCKS, DEFAULT_LAYOUT, loadLayout, moveBlock, normalize, saveLayout, toggleBlock, visibleBlocks } from './panelBlocks';

beforeEach(() => localStorage.clear());

describe('selection panel blocks', () => {
  it('moves, hides and keeps the layout per user', () => {
    let l = moveBlock(DEFAULT_LAYOUT, 'remarks', -1);
    expect(l.order.slice(-2)).toEqual(['remarks', 'field_reports']);
    expect(moveBlock(l, 'estimate', -1)).toBe(l); // already first
    l = toggleBlock(l, 'quantities');
    expect(visibleBlocks(l)).not.toContain('quantities');
    saveLayout('u1', l);
    expect(loadLayout('u1')).toEqual(l);
    expect(loadLayout('u2')).toEqual(DEFAULT_LAYOUT);
  });

  it('drops unknown blocks, appends new ones, survives junk in storage', () => {
    expect(normalize({ order: ['remarks', 'nope', 'remarks'], hidden: ['x', 'boq'] })).toEqual({
      order: ['remarks', ...BLOCKS.filter((b) => b !== 'remarks')], hidden: ['boq'],
    });
    localStorage.setItem('ddc-design-selection-panel:u1', '{not json');
    expect(loadLayout('u1')).toEqual(DEFAULT_LAYOUT);
  });
});
