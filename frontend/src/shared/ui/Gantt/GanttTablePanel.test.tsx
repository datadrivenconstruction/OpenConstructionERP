// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { useGanttTablePrefsStore } from '@/stores/useGanttTablePrefsStore';
import { GanttTablePanel } from './GanttTablePanel';
import type { GanttActivity } from './ganttUtils';

const ROWS: GanttActivity[] = [
  {
    id: 'a1',
    name: 'Walls',
    start: '2026-05-04',
    end: '2026-05-08',
    progress: 10,
    wbs: '01.02',
    durationDays: 5,
    predecessors: [
      { code: '01.01', type: 'FS', lag: 3 },
      { code: '01.04', type: 'SS', lag: 0 },
    ],
    resources: 'Labour ×4',
  },
];

function renderPanel() {
  return render(
    <GanttTablePanel
      activities={ROWS}
      rowHeight={44}
      headerHeight={52}
      showCriticalPath
      dateColWidth={70}
      formatDate={(iso) => iso}
      bodyRef={() => {}}
      onBodyScroll={() => {}}
    />,
  );
}

describe('GanttTablePanel', () => {
  beforeEach(() => {
    localStorage.clear();
    useGanttTablePrefsStore.getState().reset();
  });

  it('shows the default columns and none of the optional ones', () => {
    renderPanel();
    expect(screen.getByTestId('gantt-start-a1')).toBeTruthy();
    expect(screen.queryByTestId('gantt-col-wbs-a1')).toBeNull();
    expect(screen.queryByTestId('gantt-col-predecessors-a1')).toBeNull();
  });

  it('draws the picked columns, predecessors written the planner way', () => {
    useGanttTablePrefsStore.getState().toggleColumn('wbs');
    useGanttTablePrefsStore.getState().toggleColumn('predecessors');
    useGanttTablePrefsStore.getState().toggleColumn('resources');
    renderPanel();
    expect(screen.getByTestId('gantt-col-wbs-a1').textContent).toBe('01.02');
    expect(screen.getByTestId('gantt-col-predecessors-a1').textContent).toBe('01.01 FS+3; 01.04 SS');
    expect(screen.getByTestId('gantt-col-resources-a1').textContent).toBe('Labour ×4');
  });

  it('picks a column from the menu', () => {
    renderPanel();
    fireEvent.click(screen.getByTestId('gantt-columns-button'));
    fireEvent.click(screen.getByTestId('gantt-column-toggle-duration'));
    expect(useGanttTablePrefsStore.getState().columns).toContain('duration');
    expect((screen.getByTestId('gantt-column-toggle-name') as HTMLInputElement).disabled).toBe(true);
  });

  it('moves the splitter with the arrow keys and resets on Home', () => {
    renderPanel();
    const splitter = screen.getByTestId('gantt-splitter');
    expect(splitter.getAttribute('role')).toBe('separator');
    expect(splitter.getAttribute('tabindex')).toBe('0');
    useGanttTablePrefsStore.getState().setTableWidth(400);
    fireEvent.keyDown(splitter, { key: 'ArrowRight' });
    const after = useGanttTablePrefsStore.getState().tableWidth as number;
    expect(after).toBeGreaterThanOrEqual(200);
    fireEvent.keyDown(splitter, { key: 'ArrowLeft' });
    expect(useGanttTablePrefsStore.getState().tableWidth).toBeLessThan(after);
    fireEvent.keyDown(splitter, { key: 'Home' });
    expect(useGanttTablePrefsStore.getState().tableWidth).toBeNull();
  });

  it('widens a column with the keyboard', () => {
    useGanttTablePrefsStore.getState().toggleColumn('wbs');
    renderPanel();
    fireEvent.keyDown(screen.getByTestId('gantt-col-resize-wbs'), { key: 'ArrowRight' });
    expect(useGanttTablePrefsStore.getState().widths.wbs).toBe(72);
  });

  it('reads the arrows the other way round in a right-to-left document', () => {
    document.documentElement.dir = 'rtl';
    try {
      useGanttTablePrefsStore.getState().toggleColumn('wbs');
      renderPanel();
      fireEvent.keyDown(screen.getByTestId('gantt-col-resize-wbs'), { key: 'ArrowLeft' });
      expect(useGanttTablePrefsStore.getState().widths.wbs).toBe(72);
    } finally {
      document.documentElement.dir = '';
    }
  });
});
