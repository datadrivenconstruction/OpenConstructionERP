// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  DOCK_WIDTH_DEFAULT,
  DOCK_WIDTH_MAX,
  DOCK_WIDTH_MIN,
  DOCK_WIDTH_STORAGE_KEY,
  clampDockWidth,
  useTrainerUiStore,
} from './useTrainerUiStore';

const store = () => useTrainerUiStore.getState();

beforeEach(() => {
  localStorage.clear();
  store().reset();
  store().resetDockWidth();
});

describe('dock width', () => {
  it('has the design defaults', () => {
    expect([DOCK_WIDTH_DEFAULT, DOCK_WIDTH_MIN, DOCK_WIDTH_MAX]).toEqual([380, 320, 560]);
    expect(DOCK_WIDTH_STORAGE_KEY).toBe('oe_trainer_dock_width_v1');
  });

  it('clamps and rounds', () => {
    expect(clampDockWidth(100)).toBe(320);
    expect(clampDockWidth(9999)).toBe(560);
    expect(clampDockWidth(401.6)).toBe(402);
    expect(clampDockWidth(Number.NaN)).toBe(380);
    expect(clampDockWidth('400')).toBe(380);
  });

  it('stores a changed width and forgets the default', () => {
    store().setDockWidth(480);
    expect(store().dockWidth).toBe(480);
    expect(localStorage.getItem(DOCK_WIDTH_STORAGE_KEY)).toBe('480');
    store().resetDockWidth();
    expect(store().dockWidth).toBe(380);
    expect(localStorage.getItem(DOCK_WIDTH_STORAGE_KEY)).toBeNull();
  });

  it('reads a stored width on load, clamped, and survives broken storage', async () => {
    localStorage.setItem(DOCK_WIDTH_STORAGE_KEY, '9000');
    vi.resetModules();
    const fresh = await import('./useTrainerUiStore');
    expect(fresh.useTrainerUiStore.getState().dockWidth).toBe(560);

    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    try {
      store().setDockWidth(500);
      expect(store().dockWidth).toBe(500);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('dock and selection', () => {
  it('opens a task, collapses to the rail and expands again', () => {
    store().openTask('t2-markups');
    expect(store()).toMatchObject({ dockTaskId: 't2-markups', dockOpen: true, selectedTaskId: 't2-markups' });
    store().setSheetExpanded(true);
    store().collapseDock();
    expect(store()).toMatchObject({ dockTaskId: 't2-markups', dockOpen: false, sheetExpanded: false });
    store().expandDock();
    expect(store().dockOpen).toBe(true);
  });

  it('does not expand a dock that has no task', () => {
    store().closeDock();
    store().expandDock();
    expect(store().dockOpen).toBe(false);
  });

  it('selects a map station without opening the dock', () => {
    store().selectTask('t4-variation');
    expect(store()).toMatchObject({ selectedTaskId: 't4-variation', dockOpen: false, dockTaskId: null });
  });
});

describe('drafts and celebrations', () => {
  it('keeps drafts per task and per answer name', () => {
    store().setDraft('t2', 'overheads_amount', '3,581');
    store().setDraft('t2', 'grand_total', '10');
    store().setDraft('t3', 'overheads_amount', '1');
    store().clearDraft('t2', 'grand_total');
    expect(store().drafts).toEqual({ t2: { overheads_amount: '3,581' }, t3: { overheads_amount: '1' } });
    store().clearDrafts('t2');
    expect(store().drafts).toEqual({ t3: { overheads_amount: '1' } });
  });

  it('never writes drafts to storage', () => {
    store().setDraft('t2', 'overheads_amount', '3,581');
    expect(JSON.stringify({ ...localStorage })).not.toContain('3,581');
  });

  it('records each celebrated unlock once', () => {
    store().markCelebrated('bid_management');
    store().markCelebrated('bid_management');
    expect(store().celebrated).toEqual(['bid_management']);
  });

  it('reset forgets the session but keeps the width', () => {
    store().setDockWidth(500);
    store().openTask('t2');
    store().setDraft('t2', 'a', '1');
    store().markCelebrated('variations');
    store().reset();
    expect(store()).toMatchObject({
      dockTaskId: null,
      dockOpen: false,
      selectedTaskId: null,
      drafts: {},
      celebrated: [],
      dockWidth: 500,
    });
  });
});
