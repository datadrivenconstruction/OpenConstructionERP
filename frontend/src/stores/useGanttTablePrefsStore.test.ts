// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it, vi } from 'vitest';

const KEY = 'oe_gantt_table_prefs';

async function freshStore() {
  vi.resetModules();
  return import('./useGanttTablePrefsStore');
}

describe('useGanttTablePrefsStore', () => {
  beforeEach(() => localStorage.clear());

  it('defaults keep the table the chart always had', async () => {
    const { useGanttTablePrefsStore } = await freshStore();
    const s = useGanttTablePrefsStore.getState();
    expect(s.columns).toEqual(['name', 'start', 'end', 'progress']);
    expect(s.widths).toEqual({});
    expect(s.tableWidth).toBeNull();
  });

  it('toggles optional columns in table order and never drops the name', async () => {
    const { useGanttTablePrefsStore } = await freshStore();
    const store = useGanttTablePrefsStore.getState();
    store.toggleColumn('wbs');
    store.toggleColumn('predecessors');
    expect(useGanttTablePrefsStore.getState().columns).toEqual(['wbs', 'name', 'start', 'end', 'predecessors', 'progress']);
    store.toggleColumn('name');
    expect(useGanttTablePrefsStore.getState().columns).toContain('name');
    store.toggleColumn('wbs');
    expect(useGanttTablePrefsStore.getState().columns).not.toContain('wbs');
  });

  it('clamps column widths to what the column allows', async () => {
    const { useGanttTablePrefsStore, normalizeColumnWidth } = await freshStore();
    useGanttTablePrefsStore.getState().setColumnWidth('wbs', 5);
    expect(useGanttTablePrefsStore.getState().widths.wbs).toBe(40);
    useGanttTablePrefsStore.getState().setColumnWidth('wbs', 9999);
    expect(useGanttTablePrefsStore.getState().widths.wbs).toBe(160);
    expect(normalizeColumnWidth('wbs', 'wide')).toBe(64);
  });

  it('clamps the splitter and lets null give the width back to the columns', async () => {
    const { useGanttTablePrefsStore, GANTT_TABLE_MIN_WIDTH, GANTT_TABLE_MAX_WIDTH } = await freshStore();
    const store = useGanttTablePrefsStore.getState();
    store.setTableWidth(10);
    expect(useGanttTablePrefsStore.getState().tableWidth).toBe(GANTT_TABLE_MIN_WIDTH);
    store.setTableWidth(99999);
    expect(useGanttTablePrefsStore.getState().tableWidth).toBe(GANTT_TABLE_MAX_WIDTH);
    store.setTableWidth(null);
    expect(useGanttTablePrefsStore.getState().tableWidth).toBeNull();
  });

  it('persists and restores every preference', async () => {
    const first = await freshStore();
    const s = first.useGanttTablePrefsStore.getState();
    s.toggleColumn('duration');
    s.setColumnWidth('name', 220);
    s.setTableWidth(480);
    expect(JSON.parse(localStorage.getItem(KEY) as string)).toEqual({
      columns: ['name', 'start', 'end', 'duration', 'progress'],
      widths: { name: 220 },
      tableWidth: 480,
    });
    const second = await freshStore();
    const r = second.useGanttTablePrefsStore.getState();
    expect(r.columns).toEqual(['name', 'start', 'end', 'duration', 'progress']);
    expect(r.widths.name).toBe(220);
    expect(r.tableWidth).toBe(480);
  });

  it('survives corrupt storage and unknown columns', async () => {
    localStorage.setItem(KEY, '{not json');
    const { useGanttTablePrefsStore } = await freshStore();
    expect(useGanttTablePrefsStore.getState().columns).toEqual(['name', 'start', 'end', 'progress']);
    localStorage.setItem(KEY, JSON.stringify({ columns: ['bogus', 'wbs', 'wbs'], widths: { wbs: 'x' }, tableWidth: 'y' }));
    const again = await freshStore();
    const s = again.useGanttTablePrefsStore.getState();
    expect(s.columns).toEqual(['wbs', 'name']);
    expect(s.widths).toEqual({});
    expect(s.tableWidth).toBeNull();
  });

  it('reset restores the defaults', async () => {
    const { useGanttTablePrefsStore } = await freshStore();
    const s = useGanttTablePrefsStore.getState();
    s.toggleColumn('resources');
    s.setTableWidth(500);
    s.reset();
    const r = useGanttTablePrefsStore.getState();
    expect(r.columns).toEqual(['name', 'start', 'end', 'progress']);
    expect(r.tableWidth).toBeNull();
  });
});
