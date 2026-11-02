// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The selection config handed to AG Grid must keep its identity across
 * re-renders of the grid.
 *
 * AG Grid 32 reads a new `rowSelection` object as a settings change even when
 * every field is equal: it stops the cell editor that is open and rebuilds
 * every rendered row. BOQGrid re-renders whenever the editor page does, and the
 * page re-renders on a row click, on every save and on every sibling refetch.
 * With an inline literal the Unit Rate editor died about 200 ms after it
 * opened, so a price typed into it went nowhere, and each save paid for a full
 * redraw of the viewport. That was the "BOQ freezes when I enter a price"
 * report.
 *
 * AG Grid is stubbed here so the test reads exactly what the grid was given on
 * each render. The companion test in __tests__/rate-editor-survives-rerender
 * drives the real grid and checks the editor itself.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { createElement } from 'react';

import BOQGrid from './BOQGrid';
import type { Position } from './api';

const { seenProps } = vi.hoisted(() => ({ seenProps: [] as Array<Record<string, unknown>> }));

vi.mock('ag-grid-react', async () => {
  const React = await import('react');
  return {
    AgGridReact: React.forwardRef(function AgGridReactStub(
      props: Record<string, unknown>,
      _ref: unknown,
    ) {
      seenProps.push(props);
      return null;
    }),
  };
});

vi.mock('@/features/collab_locks', () => ({
  acquireLock: vi.fn(async () => ({ ok: true, lock: { id: 'lock-test' } })),
  releaseLock: vi.fn(async () => undefined),
}));

afterEach(() => {
  cleanup();
  seenProps.length = 0;
});

function makePosition(n: number): Position {
  return {
    id: `pos-${n}`,
    boq_id: 'boq-1',
    ordinal: `01.0${n}`,
    description: `Position ${n}`,
    unit: 'm2',
    quantity: 10 + n,
    unit_rate: 5 + n,
    total: (10 + n) * (5 + n),
    parent_id: null,
    validation_status: 'valid',
    metadata: {},
  } as unknown as Position;
}

function gridProps(overrides: Record<string, unknown> = {}) {
  return {
    positions: [makePosition(1), makePosition(2)],
    onUpdatePosition: () => undefined,
    onDeletePosition: () => undefined,
    onAddPosition: () => undefined,
    onSelectSuggestion: () => undefined,
    onSaveToDatabase: () => undefined,
    onFormulaApplied: () => undefined,
    collapsedSections: new Set<string>(),
    onToggleSection: () => undefined,
    currencySymbol: '€',
    currencyCode: 'EUR',
    locale: 'hr-HR',
    footerRows: [],
    ...overrides,
  };
}

type RowSelectionProp = {
  mode: string;
  isRowSelectable: (node: { data?: Record<string, unknown> }) => boolean;
};

function rowSelectionAt(i: number): RowSelectionProp {
  const props = seenProps[i];
  if (!props) throw new Error(`AG Grid was not rendered ${i + 1} times`);
  return props.rowSelection as RowSelectionProp;
}

describe('BOQGrid rowSelection identity', () => {
  it('keeps the same rowSelection object when the page re-renders the grid', () => {
    const positions = [makePosition(1), makePosition(2)];
    const { rerender } = render(createElement(BOQGrid, gridProps({ positions })));

    // What the editor page does on a row click or after a save: fresh
    // callback identities for the same data.
    rerender(createElement(BOQGrid, gridProps({ positions, onAddPosition: () => undefined })));
    rerender(createElement(BOQGrid, gridProps({ positions, onActiveRowChange: () => undefined })));
    // And a data change, which re-renders it for real.
    rerender(createElement(BOQGrid, gridProps({ positions: [makePosition(1), makePosition(3)] })));

    expect(seenProps.length, 'the stub must see every render').toBeGreaterThanOrEqual(4);
    const first = rowSelectionAt(0);
    for (let i = 1; i < seenProps.length; i++) {
      expect(rowSelectionAt(i), `render ${i + 1} passed a new rowSelection object`).toBe(first);
    }
  });

  it('lets positions and sections be selected, never footers or resources', () => {
    render(createElement(BOQGrid, gridProps()));
    const { mode, isRowSelectable } = rowSelectionAt(0);
    expect(mode).toBe('multiRow');
    expect(isRowSelectable({ data: { id: 'pos-1' } })).toBe(true);
    expect(isRowSelectable({ data: { id: 's', _isSection: true } })).toBe(true);
    expect(isRowSelectable({ data: { id: 'f', _isFooter: true } })).toBe(false);
    expect(isRowSelectable({ data: { id: 'r', _isResource: true } })).toBe(false);
    expect(isRowSelectable({ data: { id: 'a', _isAddResource: true } })).toBe(false);
  });

  it('ticks section rows with the same checkbox and select-all as positions', () => {
    render(createElement(BOQGrid, gridProps()));
    const sel = rowSelectionAt(0) as unknown as {
      checkboxes: boolean;
      headerCheckbox: boolean;
      selectAll: string;
      isRowSelectable: (n: { data: Record<string, unknown> }) => boolean;
    };
    expect(sel.checkboxes).toBe(true);
    expect(sel.headerCheckbox).toBe(true);
    // select-all walks the selectable rows, so sections follow the header box.
    expect(sel.selectAll).toBe('filtered');
    expect(sel.isRowSelectable({ data: { id: 's', _isSection: true } })).toBe(true);
  });
});
