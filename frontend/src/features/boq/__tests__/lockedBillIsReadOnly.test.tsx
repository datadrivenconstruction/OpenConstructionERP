// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A locked bill offers nothing the server will refuse.
 *
 * The server refuses every write to a locked bill with a 409, and the grid
 * still offered all of them: cells opened their editors, sections showed Add
 * Position, the row menu offered Delete. The estimator typed, pressed Enter and
 * got an error. Locked, the grid is a read-only view: nothing opens an editor,
 * the write actions are gone, and what only reads (collapse, price analysis)
 * stays.
 *
 * Run:  npx vitest run src/features/boq/__tests__/lockedBillIsReadOnly.test.tsx
 */
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, fireEvent, act } from '@testing-library/react';
import { createElement } from 'react';

import BOQGrid from '../BOQGrid';
import type { Position } from '../api';

vi.mock('@/features/collab_locks', () => ({
  acquireLock: vi.fn(async () => ({ ok: true, lock: { id: 'lock-test' } })),
  releaseLock: vi.fn(async () => undefined),
}));

// jsdom has no layout: give every element a viewport-sized box or AG Grid
// renders zero rows and the test passes for the wrong reason.
beforeAll(() => {
  for (const prop of ['clientHeight', 'offsetHeight'] as const) {
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get: () => 800 });
  }
  for (const prop of ['clientWidth', 'offsetWidth'] as const) {
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get: () => 1600 });
  }
  HTMLElement.prototype.getBoundingClientRect = function () {
    return {
      width: 1600, height: 800, top: 0, left: 0, bottom: 800, right: 1600,
      x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect;
  };
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get() { return this.parentElement; },
  });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const SECTION = {
  id: 'sec-1',
  boq_id: 'boq-1',
  ordinal: '01',
  description: 'Concrete works',
  unit: '',
  quantity: 0,
  unit_rate: 0,
  total: 0,
  parent_id: null,
  validation_status: 'valid',
  metadata: {},
} as unknown as Position;

function position(n: number): Position {
  return {
    id: `pos-${n}`,
    boq_id: 'boq-1',
    ordinal: `01.0${n}`,
    description: `Position ${n}`,
    unit: 'm2',
    quantity: 10 + n,
    unit_rate: 5 + n,
    total: (10 + n) * (5 + n),
    parent_id: 'sec-1',
    validation_status: 'valid',
    metadata: {},
  } as unknown as Position;
}

const noop = () => undefined;

function renderGrid(readOnly: boolean) {
  const handlers = {
    onUpdatePosition: vi.fn(),
    onDeletePosition: vi.fn(),
    onAddPosition: vi.fn(),
    onPriceAnalysis: vi.fn(),
  };
  render(
    createElement(BOQGrid, {
      positions: [SECTION, position(1), position(2)],
      onSelectSuggestion: noop,
      onSaveToDatabase: noop,
      onFormulaApplied: noop,
      collapsedSections: new Set<string>(),
      onToggleSection: noop,
      currencySymbol: '€',
      currencyCode: 'EUR',
      locale: 'en-US',
      footerRows: [],
      readOnly,
      ...handlers,
    }),
  );
  return handlers;
}

async function flush(ms = 0) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

async function waitUntil(cond: () => boolean, what: string, timeoutMs = 4000) {
  const t0 = Date.now();
  while (!cond()) {
    if (Date.now() - t0 > timeoutMs) throw new Error(`timed out waiting for: ${what}`);
    await flush(25);
  }
}

function cell(rowId: string, colId: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`.ag-row[row-id="${rowId}"] .ag-cell[col-id="${colId}"]`);
  if (!el) throw new Error(`cell ${rowId}/${colId} not rendered`);
  return el;
}

/** Labels of the open context menu, by i18n key or English, whichever renders. */
function menuLabels(): string[] {
  return Array.from(document.querySelectorAll<HTMLElement>('button, [role="menuitem"]'))
    .map((el) => (el.textContent ?? '').trim())
    .filter(Boolean);
}

function isEditing(): boolean {
  return document.querySelector('.ag-cell-inline-editing, .ag-popup-editor') !== null;
}

async function open(readOnly: boolean) {
  const handlers = renderGrid(readOnly);
  await waitUntil(() => !!document.querySelector('.ag-row[row-id="pos-1"]'), 'grid rows to render');
  return handlers;
}

describe('the grid of a locked bill', { timeout: 30_000 }, () => {
  it('opens no editor on a quantity cell', async () => {
    await open(true);
    await act(async () => {
      fireEvent.click(cell('pos-1', 'quantity'));
      fireEvent.doubleClick(cell('pos-1', 'quantity'));
    });
    await flush(50);
    expect(isEditing()).toBe(false);
  });

  it('offers no Add Position on a section', async () => {
    await open(true);
    const addButtons = Array.from(document.querySelectorAll('button')).filter((b) =>
      ['boq.add_position', 'Add Position'].includes((b.textContent ?? '').trim()),
    );
    expect(addButtons).toHaveLength(0);
  });

  it('offers no Delete in the row menu but keeps what only reads', async () => {
    await open(true);
    await act(async () => {
      fireEvent.contextMenu(cell('pos-1', 'description'));
    });
    await flush(25);
    const labels = menuLabels();
    expect(labels.some((l) => ['common.delete', 'Delete'].includes(l))).toBe(false);
    expect(labels.some((l) => ['boq.duplicate_position', 'Duplicate Position'].includes(l))).toBe(false);
    expect(labels.some((l) => ['boq.price_analysis', 'Price analysis'].includes(l))).toBe(true);
  });
});

describe('the grid of an open bill, for contrast', { timeout: 30_000 }, () => {
  it('opens an editor on a quantity cell', async () => {
    await open(false);
    await act(async () => {
      fireEvent.click(cell('pos-1', 'quantity'));
      fireEvent.doubleClick(cell('pos-1', 'quantity'));
    });
    await waitUntil(isEditing, 'the quantity editor to open');
  });

  it('offers Add Position and Delete', async () => {
    await open(false);
    expect(
      Array.from(document.querySelectorAll('button')).some((b) =>
        ['boq.add_position', 'Add Position'].includes((b.textContent ?? '').trim()),
      ),
    ).toBe(true);
    await act(async () => {
      fireEvent.contextMenu(cell('pos-1', 'description'));
    });
    await flush(25);
    expect(menuLabels().some((l) => ['common.delete', 'Delete'].includes(l))).toBe(true);
  });
});
