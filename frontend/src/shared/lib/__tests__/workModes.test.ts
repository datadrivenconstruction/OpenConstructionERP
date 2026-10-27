// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';
import { WORK_MODES, WORK_MODE_IDS, applyWorkMode, matchWorkMode } from '../workModes';
import { readTablePrefs } from '../tablePrefs';
import { readComfort } from '../comfort';

describe('work modes', () => {
  it('sets every part of the bundle', () => {
    const setAppearance = vi.fn();
    const setMenu = vi.fn();
    applyWorkMode('spreadsheet', { setAppearance, setMenu });
    expect(setAppearance).toHaveBeenCalledWith(expect.objectContaining({ look: 'classic', density: 'compact' }));
    expect(setMenu).toHaveBeenCalledWith(WORK_MODES.spreadsheet.menu);
    expect(readTablePrefs()).toEqual({ excel: true, keyboard: true });
    expect(readComfort().motion).toBe('reduced');
  });

  it('recognises each mode and a custom mix', () => {
    for (const id of WORK_MODE_IDS) {
      const m = WORK_MODES[id];
      expect(matchWorkMode({ ...m.appearance }, { ...m.menu }, { ...m.tables })).toBe(id);
    }
    const s = WORK_MODES.standard;
    expect(matchWorkMode({ ...s.appearance, density: 'compact' }, s.menu, s.tables)).toBeNull();
  });

  it('keeps the standard look unchanged', () => {
    expect(WORK_MODES.standard.appearance.look).toBe('standard');
    expect(WORK_MODES.field.appearance.look).toBe('standard');
  });
});
