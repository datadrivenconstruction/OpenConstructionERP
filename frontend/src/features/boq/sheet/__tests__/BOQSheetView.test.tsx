// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sheet mode in the DOM: type to overwrite, Esc, F2, paste per locale, Ctrl+D,
 * undo, grid roles, and a 10,000-row bill that stays windowed and repaints
 * only the edited row.
 */

import React from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Position } from '../../api';
import { BOQSheetView } from '../BOQSheetView';
import type { SheetCellEdit } from '../commit';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    let s = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
    for (const [k, v] of Object.entries(opts ?? {})) s = s.replace(`{{${k}}}`, String(v));
    return s;
  };
  const value = { t, i18n: { language: 'en', changeLanguage: () => {} } };
  return { useTranslation: () => value };
});

afterEach(cleanup);

function bill(n: number): Position[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `p${i}`,
    boq_id: 'b',
    parent_id: null,
    ordinal: `01.${String(i + 1).padStart(4, '0')}`,
    description: `Line ${i}`,
    unit: 'm2',
    quantity: i + 1,
    unit_rate: 10,
    total: (i + 1) * 10,
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: i,
    validation_status: 'pending',
    metadata: {},
    version: 0,
  })) as Position[];
}

function setup(n = 5, locale = 'de-DE', extra: Partial<React.ComponentProps<typeof BOQSheetView>> = {}) {
  const commits: SheetCellEdit[][] = [];
  const onCommit = vi.fn(async (edits: SheetCellEdit[]) => {
    commits.push(edits);
  });
  const onCreateRows = vi.fn();
  const utils = render(
    <BOQSheetView positions={bill(n)} locale={locale} onCommit={onCommit} onCreateRows={onCreateRows} {...extra} />,
  );
  const grid = screen.getByRole('grid');
  return { ...utils, grid, commits, onCommit, onCreateRows };
}

const cell = (row: number, col: number) =>
  document.querySelector(`[data-row="${row}"][data-col="${col}"]`) as HTMLElement;

describe('sheet keyboard', () => {
  it('types to overwrite, commits on Enter and moves down', async () => {
    const { grid, commits } = setup();
    fireEvent.mouseDown(cell(0, 3));
    fireEvent.keyDown(grid, { key: '7' });
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: '7,5' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(commits).toHaveLength(1));
    expect(commits[0]).toEqual([{ id: 'p0', version: 0, fields: { quantity: '7.5' } }]);
    expect(cell(1, 3).getAttribute('class')).toContain('outline-oe-blue');
  });

  it('Esc cancels and F2 opens the current value', async () => {
    const { grid, onCommit } = setup();
    fireEvent.mouseDown(cell(1, 1));
    fireEvent.keyDown(grid, { key: 'F2' });
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('Line 1');
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' });
    expect(screen.queryByRole('textbox')).toBeNull();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('fills down with Ctrl+D and undoes the whole fill with Ctrl+Z', async () => {
    const { grid, commits } = setup();
    fireEvent.mouseDown(cell(0, 2));
    fireEvent.mouseDown(cell(3, 2), { shiftKey: true });
    fireEvent.keyDown(grid, { key: 'd', ctrlKey: true });
    // Same unit everywhere: nothing to write.
    expect(commits).toHaveLength(0);
    fireEvent.mouseDown(cell(0, 1));
    fireEvent.mouseDown(cell(2, 1), { shiftKey: true });
    fireEvent.keyDown(grid, { key: 'd', ctrlKey: true });
    await waitFor(() => expect(commits).toHaveLength(1));
    expect(commits[0]!.map((e) => e.fields.description)).toEqual(['Line 0', 'Line 0']);
    fireEvent.keyDown(grid, { key: 'z', ctrlKey: true });
    await waitFor(() => expect(commits).toHaveLength(2));
    expect(commits[1]!.map((e) => e.fields.description).sort()).toEqual(['Line 1', 'Line 2']);
  });

  it('pastes a German block into existing rows and previews the overflow as new rows', async () => {
    const { grid, commits } = setup(2);
    fireEvent.mouseDown(cell(1, 3));
    fireEvent.paste(grid, {
      clipboardData: { getData: () => '1.234,5\t12,40\r\n2\t3\r\n' },
    });
    await waitFor(() => expect(commits).toHaveLength(1));
    expect(commits[0]).toEqual([{ id: 'p1', version: 0, fields: { quantity: '1234.5', unit_rate: '12.4' } }]);
    expect(await screen.findByRole('dialog')).toBeTruthy();
  });

  it('copies the selection as TSV with the locale decimal', () => {
    const { grid } = setup(3, 'de-DE');
    fireEvent.mouseDown(cell(0, 3));
    fireEvent.mouseDown(cell(1, 4), { shiftKey: true });
    let copied = '';
    fireEvent.copy(grid, { clipboardData: { setData: (_: string, v: string) => (copied = v) } });
    expect(copied).toBe('1\t10\r\n2\t10');
  });

  it('shows a circular reference inline instead of saving it', async () => {
    const positions = bill(2);
    positions[1]!.metadata = { formula: '=pos("01.0001").qty' };
    const onCommit = vi.fn(async () => {});
    render(<BOQSheetView positions={positions} locale="en-US" onCommit={onCommit} onCreateRows={() => {}} />);
    const grid = screen.getByRole('grid');
    fireEvent.mouseDown(cell(0, 3));
    fireEvent.keyDown(grid, { key: '=' });
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '=pos("01.0002").qty' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(cell(0, 3).getAttribute('title')).toContain('Circular reference'));
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('exposes grid roles and labels to screen readers', () => {
    const { grid } = setup(3);
    expect(grid.getAttribute('aria-rowcount')).toBe('4');
    expect(screen.getAllByRole('columnheader').length).toBe(6);
    expect(cell(0, 0).getAttribute('role')).toBe('gridcell');
  });
});

describe('sheet performance on 10,000 positions', () => {
  it('renders a window of rows and repaints only the edited row', async () => {
    const renders = new Map<string, number>();
    const onRowRender = (id: string) => renders.set(id, (renders.get(id) ?? 0) + 1);
    const t0 = performance.now();
    const base = bill(10_000);
    const { grid, commits, rerender, onCommit } = setup(10_000, 'en-US', { positions: base, onRowRender, height: 600 });
    const mountMs = performance.now() - t0;
    const rowsInDom = document.querySelectorAll('[role="row"]').length - 1;
    expect(rowsInDom).toBeLessThan(60);
    expect(mountMs).toBeLessThan(3000);

    fireEvent.mouseDown(cell(5, 1));
    renders.clear();
    fireEvent.keyDown(grid, { key: 'ArrowDown' });
    // Moving the cursor repaints the row it leaves and the row it enters.
    expect(renders.size).toBeLessThanOrEqual(2);

    const next = base.slice();
    next[6] = { ...next[6]!, description: 'Changed', version: 1 };
    renders.clear();
    const t1 = performance.now();
    await act(async () => {
      rerender(
        <BOQSheetView
          positions={next}
          locale="en-US"
          onCommit={onCommit}
          onCreateRows={() => {}}
          onRowRender={onRowRender}
          height={600}
        />,
      );
    });
    const rerenderMs = performance.now() - t1;
    expect(rerenderMs).toBeLessThan(1500);
    // Only the changed row repaints; its neighbours keep their memoised output.
    expect([...renders.keys()]).toEqual(['p6']);
    expect(commits).toHaveLength(0);
    console.info(`[perf] 10k rows: mount ${mountMs.toFixed(0)} ms, rerender ${rerenderMs.toFixed(0)} ms, rows in DOM ${rowsInDom}`);
  });
});
