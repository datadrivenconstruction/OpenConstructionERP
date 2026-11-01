// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * CoordinationTradeMatrix UI tests.
 *
 * The component renders a fixed 6×6 grid of buttons. Each cell is keyed
 * by ``matrix-cell-{row}-{col}`` so tests can find individual cells by
 * discipline pair and assert click navigation.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  render,
  screen,
  cleanup,
  fireEvent,
  act,
} from '@testing-library/react';
import { CoordinationTradeMatrix } from '../CoordinationTradeMatrix';
import type { TradeMatrixResponse } from '../types';

const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

// MoneyDisplay reads the preferences store — shim it so the cost-weighted
// view renders without a real provider.
const __mockPrefState = { currency: 'EUR', numberLocale: 'en-US' };
vi.mock('@/stores/usePreferencesStore', async (importOriginal) => ({
  // Keep the real exports so a newly added one never breaks this mock.
  ...(await importOriginal<Record<string, unknown>>()),
  usePreferencesStore: (sel?: (s: unknown) => unknown) =>
    sel ? sel(__mockPrefState) : __mockPrefState,
  // Money surfaces resolve the locale through this rather than off the raw
  // preference, so a wholesale mock of the store has to carry it too, and it
  // has to carry both shapes. The hook is for components; the plain call is
  // for the formatters in `shared/lib`, which run during render but are not
  // components and cannot hold a hook. A mock with only one of the pair
  // throws on the other, and the message it throws names the mock rather than
  // the line that reached for it.
  useNumberLocale: () => __mockPrefState.numberLocale,
  getNumberLocale: () => __mockPrefState.numberLocale,
}));

const TRADES = ['arch', 'struct', 'mep', 'landscape', 'civil', 'other'] as const;

const SAMPLE: TradeMatrixResponse = {
  project_id: 'p-1',
  trades: [...TRADES],
  cells: [
    { row: 'arch', col: 'struct', count: 12, open: 7, resolved: 5, cost_impact: '0' },
    { row: 'mep', col: 'struct', count: 8, open: 4, resolved: 4, cost_impact: '0' },
  ],
};

// Same shape but with cost weighting present — drives the toggle path.
const SAMPLE_WITH_COST: TradeMatrixResponse = {
  project_id: 'p-1',
  trades: [...TRADES],
  currency: 'EUR',
  total_cost_impact: '15000',
  cells: [
    { row: 'arch', col: 'struct', count: 12, open: 7, resolved: 5, cost_impact: '2000' },
    { row: 'mep', col: 'struct', count: 8, open: 4, resolved: 4, cost_impact: '13000' },
  ],
};

const EMPTY: TradeMatrixResponse = {
  project_id: 'p-1',
  trades: [...TRADES],
  currency: 'EUR',
  total_cost_impact: '0',
  cells: [],
};

beforeEach(() => {
  navigate.mockReset();
  cleanup();
});

describe('CoordinationTradeMatrix', () => {
  it('renders 36 cells (6×6 grid)', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    // Each row has one label cell + 6 button cells. We have 6 rows so
    // exactly 36 button-cells.
    const cells = screen
      .getAllByRole('button')
      .filter((el) => el.getAttribute('data-testid')?.startsWith('matrix-cell-'));
    expect(cells).toHaveLength(36);
  });

  it('shows the open count in populated cells', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-arch-struct');
    expect(cell).toHaveTextContent('7');
  });

  it('renders dash in empty cells', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-civil-landscape');
    expect(cell).toHaveTextContent('—');
    expect(cell).toBeDisabled();
  });

  it('navigates to /clash with disciplineA / disciplineB params on click', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-arch-struct');
    fireEvent.click(cell);
    expect(navigate).toHaveBeenCalledWith(
      '/clash?disciplineA=arch&disciplineB=struct',
    );
  });

  it('includes the project id in the query when provided', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} projectId="p-42" />);
    const cell = screen.getByTestId('matrix-cell-arch-struct');
    fireEvent.click(cell);
    expect(navigate).toHaveBeenCalledWith(
      '/clash?project=p-42&disciplineA=arch&disciplineB=struct',
    );
  });

  it('does not navigate on disabled (empty) cells', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-civil-landscape');
    fireEvent.click(cell);
    expect(navigate).not.toHaveBeenCalled();
  });

  it('renders the skeleton while loading', () => {
    render(<CoordinationTradeMatrix data={undefined} isLoading />);
    expect(
      screen.getByTestId('coordination-matrix-skeleton'),
    ).toBeInTheDocument();
  });

  it('mirrors a (row,col) cell across the diagonal', () => {
    // Only (arch, struct) was provided; the (struct, arch) lookup should
    // surface the same count via the symmetric fallback.
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const mirrored = screen.getByTestId('matrix-cell-struct-arch');
    expect(mirrored).toHaveTextContent('7');
  });

  it('shows the breakdown tooltip on hover for non-empty cells', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-arch-struct');
    act(() => {
      fireEvent.mouseEnter(cell.parentElement as HTMLElement);
    });
    const tooltip = screen.getByTestId('matrix-cell-tooltip-arch-struct');
    expect(tooltip).toBeInTheDocument();
    // Breakdown contents: Total, Open, Resolved (numeric labels)
    expect(tooltip).toHaveTextContent(/Total/);
    expect(tooltip).toHaveTextContent(/12/);
    expect(tooltip).toHaveTextContent(/Open/);
    expect(tooltip).toHaveTextContent(/7/);
    expect(tooltip).toHaveTextContent(/Resolved/);
    expect(tooltip).toHaveTextContent(/5/);
  });

  it('does not show a tooltip on empty cells', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-civil-landscape');
    act(() => {
      fireEvent.mouseEnter(cell.parentElement as HTMLElement);
    });
    expect(
      screen.queryByTestId('matrix-cell-tooltip-civil-landscape'),
    ).not.toBeInTheDocument();
  });

  it('navigates on Enter key for keyboard users (accessibility)', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} projectId="p-x" />);
    const cell = screen.getByTestId('matrix-cell-mep-struct');
    cell.focus();
    fireEvent.keyDown(cell, { key: 'Enter' });
    expect(navigate).toHaveBeenCalledWith(
      '/clash?project=p-x&disciplineA=mep&disciplineB=struct',
    );
  });

  it('exposes a descriptive aria-label on non-empty cells', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    const cell = screen.getByTestId('matrix-cell-arch-struct');
    const aria = cell.getAttribute('aria-label') ?? '';
    expect(aria).toMatch(/7/); // open count
    expect(aria.toLowerCase()).toMatch(/arch/);
    expect(aria.toLowerCase()).toMatch(/struct/);
  });

  // ── Empty state ───────────────────────────────────────────────────────

  it('renders a real empty state (not a grid) when there are no clashes', () => {
    render(<CoordinationTradeMatrix data={EMPTY} projectId="p-1" />);
    expect(
      screen.getByTestId('coordination-matrix-empty'),
    ).toBeInTheDocument();
    // The 6x6 grid of cells must NOT render.
    expect(
      screen.queryByTestId('matrix-cell-arch-struct'),
    ).not.toBeInTheDocument();
  });

  it('the empty-state CTA navigates to /clash for the project', () => {
    render(<CoordinationTradeMatrix data={EMPTY} projectId="p-9" />);
    fireEvent.click(screen.getByTestId('coordination-matrix-empty-cta'));
    expect(navigate).toHaveBeenCalledWith('/clash?project=p-9');
  });

  // ── Cost weighting toggle ─────────────────────────────────────────────

  it('does not offer the cost toggle when no cell carries cost', () => {
    render(<CoordinationTradeMatrix data={SAMPLE} />);
    expect(
      screen.queryByTestId('coordination-matrix-weight-cost'),
    ).not.toBeInTheDocument();
  });

  it('offers the count/cost toggle when cost is present', () => {
    render(<CoordinationTradeMatrix data={SAMPLE_WITH_COST} />);
    expect(
      screen.getByTestId('coordination-matrix-weight-count'),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId('coordination-matrix-weight-cost'),
    ).toBeInTheDocument();
  });

  it('defaults to count weighting (cell shows open count)', () => {
    render(<CoordinationTradeMatrix data={SAMPLE_WITH_COST} />);
    expect(screen.getByTestId('matrix-cell-arch-struct')).toHaveTextContent(
      '7',
    );
  });

  it('switches the cell figure to compact cost when cost weighting is picked', () => {
    render(<CoordinationTradeMatrix data={SAMPLE_WITH_COST} />);
    fireEvent.click(screen.getByTestId('coordination-matrix-weight-cost'));
    // 2000 -> "2k" compact; the mep/struct cell (13000) -> "13k".
    expect(screen.getByTestId('matrix-cell-arch-struct')).toHaveTextContent(
      '2k',
    );
    expect(screen.getByTestId('matrix-cell-mep-struct')).toHaveTextContent(
      '13k',
    );
  });

  it('shows the open cost impact in the tooltip when present', () => {
    render(<CoordinationTradeMatrix data={SAMPLE_WITH_COST} />);
    const cell = screen.getByTestId('matrix-cell-arch-struct');
    act(() => {
      fireEvent.mouseEnter(cell.parentElement as HTMLElement);
    });
    expect(
      screen.getByTestId('matrix-cell-tooltip-cost-arch-struct'),
    ).toBeInTheDocument();
  });
});
