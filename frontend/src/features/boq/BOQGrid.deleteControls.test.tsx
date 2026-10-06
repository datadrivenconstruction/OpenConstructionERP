// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Deleting a section from the grid.
 *
 * A tester could add a section to a bill and then found no way to remove it.
 * The cascade delete worked on the server; the only control for it was a 10px
 * trash icon at opacity 0 that appeared on hover, so on a touch screen it did
 * not exist, and the section right-click menu offered everything but Delete
 * while the position menu had one. The tip above the grid promised a "(...)"
 * menu on sections that only positions had.
 *
 * Delete is also a `boq.delete` call (EDITOR and up on the server), so a role
 * below that must not be offered it: the server would refuse and the user
 * would read the refusal as a broken button.
 *
 * AG Grid is stubbed, as in BOQGrid.rowSelection.test, so the test reads the
 * context the grid hands its renderers and opens the menu through it the same
 * way a renderer does.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, act } from '@testing-library/react';
import { createElement } from 'react';

import BOQGrid from './BOQGrid';
import type { Position } from './api';
import { useAuthStore } from '@/stores/useAuthStore';

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
  useAuthStore.setState({ userRole: null });
});

const SECTION = { id: 'sec-1', ordinal: '01', description: 'Walls', _isSection: true } as Record<string, unknown>;

function makePosition(n: number): Position {
  return {
    id: `pos-${n}`,
    boq_id: 'boq-1',
    ordinal: `01.0${n}`,
    description: `Position ${n}`,
    unit: 'm2',
    quantity: 10,
    unit_rate: 5,
    total: 50,
    parent_id: 'sec-1',
    validation_status: 'valid',
    metadata: {},
  } as unknown as Position;
}

function renderGrid(overrides: Record<string, unknown> = {}) {
  const onDeleteSection = vi.fn();
  const onDeletePosition = vi.fn();
  render(
    createElement(BOQGrid, {
      positions: [makePosition(1)],
      onUpdatePosition: () => undefined,
      onDeletePosition,
      onAddPosition: () => undefined,
      onSelectSuggestion: () => undefined,
      onSaveToDatabase: () => undefined,
      onFormulaApplied: () => undefined,
      onDeleteSection,
      collapsedSections: new Set<string>(),
      onToggleSection: () => undefined,
      currencySymbol: '€',
      currencyCode: 'EUR',
      locale: 'en',
      footerRows: [],
      ...overrides,
    } as never),
  );
  return { onDeleteSection, onDeletePosition };
}

type GridContext = {
  onShowContextMenu: (e: unknown, type: string, data: Record<string, unknown>) => void;
  onDeleteSection?: (id: string) => void;
};

function lastContext(): GridContext {
  const props = seenProps[seenProps.length - 1];
  if (!props) throw new Error('AG Grid was never rendered');
  return props.context as GridContext;
}

function openMenu(type: 'section' | 'position', data: Record<string, unknown>) {
  const fake = { preventDefault: () => undefined, clientX: 20, clientY: 20 };
  act(() => lastContext().onShowContextMenu(fake, type, data));
}

describe('BOQGrid section delete', () => {
  it('offers Delete in the section context menu and calls onDeleteSection', () => {
    useAuthStore.setState({ userRole: 'editor' });
    const { onDeleteSection } = renderGrid();

    openMenu('section', SECTION);
    fireEvent.click(screen.getByRole('button', { name: 'Delete section with all positions' }));

    expect(onDeleteSection).toHaveBeenCalledWith('sec-1');
    // The menu closes behind the action.
    expect(screen.queryByRole('button', { name: 'Delete section with all positions' })).toBeNull();
  });

  it('hands the renderers onDeleteSection for a role that may delete', () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderGrid();
    expect(lastContext().onDeleteSection).toBeTypeOf('function');
  });

  it('offers no Delete on sections or positions to a role without boq.delete', () => {
    useAuthStore.setState({ userRole: 'viewer' });
    const { onDeletePosition } = renderGrid();

    // Renderers get nothing to call, so the section trash icon does not draw.
    expect(lastContext().onDeleteSection).toBeUndefined();

    openMenu('section', SECTION);
    expect(screen.queryByRole('button', { name: 'Delete section with all positions' })).toBeNull();
    // The menu itself is still there: a viewer can still collapse the section.
    expect(screen.getByRole('button', { name: /Collapse Section|Expand Section/ })).toBeTruthy();

    openMenu('position', { id: 'pos-1', description: 'Position 1', metadata: {} });
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(onDeletePosition).not.toHaveBeenCalled();
  });

  it('still offers Delete on a position to a role that may delete', () => {
    useAuthStore.setState({ userRole: 'editor' });
    const { onDeletePosition } = renderGrid();

    openMenu('position', { id: 'pos-1', description: 'Position 1', metadata: {} });
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

    expect(onDeletePosition).toHaveBeenCalledWith('pos-1');
  });

  it('opens a keyboard-triggered menu at its button, not at the screen corner', () => {
    // Enter or Space on a button fires a click with detail 0 and no pointer
    // position (clientX/Y are 0), so the menu must anchor to the button itself.
    useAuthStore.setState({ userRole: 'editor' });
    renderGrid();

    const button = document.createElement('button');
    button.getBoundingClientRect = () =>
      ({ left: 300, right: 324, top: 116, bottom: 140, width: 24, height: 24, x: 300, y: 116, toJSON: () => ({}) }) as DOMRect;
    const keyboardClick = { preventDefault: () => undefined, detail: 0, clientX: 0, clientY: 0, currentTarget: button };
    act(() => lastContext().onShowContextMenu(keyboardClick, 'section', SECTION));

    const menu = screen.getByRole('button', { name: 'Delete section with all positions' }).parentElement!;
    expect(menu.style.left).toBe('300px');
    expect(menu.style.top).toBe('140px');
  });

  it('offers no Delete on a locked bill even to an editor', () => {
    useAuthStore.setState({ userRole: 'editor' });
    renderGrid({ readOnly: true });

    openMenu('section', SECTION);
    expect(screen.queryByRole('button', { name: 'Delete section with all positions' })).toBeNull();
  });
});
