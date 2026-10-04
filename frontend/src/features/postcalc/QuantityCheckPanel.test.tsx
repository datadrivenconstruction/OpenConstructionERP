// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The quantity check view: what the filters keep, what the footer totals and
 * that money is written by the shared formatter in the bill's currency.
 *
 * Expected money strings are computed with `formatCurrency` rather than
 * quoted, so the test holds in any number locale the runner has.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { formatCurrency } from '@/shared/lib/money';
import type { QuantityCheckLine, QuantityCheckReport } from './api';

vi.mock('./api', () => ({
  fetchQuantityCheck: vi.fn(),
  setQuantityBaseline: vi.fn(),
}));

import { fetchQuantityCheck } from './api';
import { QuantityCheckPanel } from './QuantityCheckPanel';
import { filterLines, isBeyondThreshold, totalsOf } from './quantityCheck';

const mockFetch = vi.mocked(fetchQuantityCheck);

function line(overrides: Partial<QuantityCheckLine>): QuantityCheckLine {
  return {
    position_id: overrides.ordinal ?? 'x',
    ordinal: '01.0010',
    description: 'Concrete',
    unit: 'm3',
    contract_quantity: '100.000',
    contract_unit_rate: '50',
    contract_value: '5000.00',
    measured_quantity: null,
    measured_source: null,
    difference: null,
    difference_pct: null,
    cost_effect: null,
    status: 'not_measured',
    in_baseline: true,
    in_bill: true,
    sheet_unchanged_since_baseline: false,
    contract_quantity_may_be_measured: false,
    ...overrides,
  };
}

const LINES: QuantityCheckLine[] = [
  // +12 %: over, beyond a 10 % band.
  line({
    ordinal: '01.0010',
    measured_quantity: '112.000',
    measured_source: 'measurement_sheet',
    difference: '12.000',
    difference_pct: '12.0',
    cost_effect: '600.00',
    status: 'over',
  }),
  // -10 %: under, exactly on a 10 % band, so not beyond it.
  line({
    ordinal: '01.0020',
    description: 'Formwork',
    unit: 'm2',
    contract_quantity: '200.000',
    contract_unit_rate: '10',
    contract_value: '2000.00',
    measured_quantity: '180.000',
    measured_source: 'gaeb_x31',
    difference: '-20.000',
    difference_pct: '-10.0',
    cost_effect: '-200.00',
    status: 'under',
  }),
  line({ ordinal: '01.0030', description: 'Anchors', unit: 'pcs', contract_quantity: '5.000', contract_value: '35.00' }),
  // Zero contract quantity: no ratio, beyond any band.
  line({
    ordinal: '01.0040',
    description: 'Joint',
    unit: 'm',
    contract_quantity: '0.000',
    contract_unit_rate: '30',
    contract_value: '0.00',
    measured_quantity: '4.000',
    measured_source: 'measurement_sheet',
    difference: '4.000',
    difference_pct: null,
    cost_effect: '120.00',
    status: 'over',
  }),
];

function report(overrides: Partial<QuantityCheckReport> = {}): QuantityCheckReport {
  return {
    project_id: 'p1',
    country_code: '',
    boqs: [{ id: 'b1', name: 'Main bill', is_locked: true, currency: 'CHF' }],
    boq_id: 'b1',
    boq_name: 'Main bill',
    currency: 'CHF',
    is_locked: true,
    baseline: {
      kind: 'snapshot',
      snapshot_id: 's1',
      name: 'Contract quantities (captured at lock)',
      created_at: '2026-09-01T10:00:00Z',
      designated: true,
      designated_reason: 'lock',
    },
    designated_snapshot_id: 's1',
    snapshots: [{ id: 's1', name: 'Contract quantities (captured at lock)', created_at: '2026-09-01T10:00:00Z', position_count: 4 }],
    warnings: [],
    lines: LINES,
    totals: {
      line_count: 4,
      measured_count: 3,
      not_measured_count: 1,
      over_count: 2,
      under_count: 1,
      matches_count: 0,
      contract_value: '7035.00',
      measured_contract_value: '7000.00',
      cost_effect_over: '720.00',
      cost_effect_under: '-200.00',
      cost_effect_net: '520.00',
    },
    ...overrides,
  };
}

const signed = (v: number, c = 'CHF') => formatCurrency(v, c, undefined, { signDisplay: 'exceptZero' });

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <QuantityCheckPanel projectId="p1" />
    </QueryClientProvider>,
  );
}

function shownRefs(): string[] {
  return screen.getAllByTestId('qc-row').map((row) => within(row).getAllByRole('cell')[0]!.textContent ?? '');
}

beforeEach(() => {
  mockFetch.mockReset();
  try {
    window.localStorage.removeItem('oce.postcalc.qc.threshold');
  } catch {
    // storage unavailable: the default band applies
  }
});

describe('quantity check helpers', () => {
  it('keeps over and under apart in the totals as well as netting them', () => {
    const totals = totalsOf(LINES);
    expect(totals.over).toBe(720);
    expect(totals.under).toBe(-200);
    expect(totals.net).toBe(520);
    expect(totals.count).toBe(4);
  });

  it('treats a measured line with no ratio as beyond any band, and the band edge as inside it', () => {
    expect(isBeyondThreshold(LINES[3]!, 1000)).toBe(true);
    expect(isBeyondThreshold(LINES[1]!, 10)).toBe(false);
    expect(isBeyondThreshold(LINES[1]!, 9.9)).toBe(true);
    expect(isBeyondThreshold(LINES[2]!, 0)).toBe(false);
  });

  it('filters by status and by band', () => {
    expect(filterLines(LINES, 'over', 10).map((l) => l.ordinal)).toEqual(['01.0010', '01.0040']);
    expect(filterLines(LINES, 'under', 10).map((l) => l.ordinal)).toEqual(['01.0020']);
    expect(filterLines(LINES, 'not_measured', 10).map((l) => l.ordinal)).toEqual(['01.0030']);
    expect(filterLines(LINES, 'beyond', 10).map((l) => l.ordinal)).toEqual(['01.0010', '01.0040']);
  });
});

describe('QuantityCheckPanel', () => {
  it('shows every position with its source and the bill-currency totals', async () => {
    mockFetch.mockResolvedValue(report());
    renderPanel();
    await waitFor(() => expect(screen.getAllByTestId('qc-row')).toHaveLength(4));

    expect(screen.getByText('GAEB X31')).toBeInTheDocument();
    expect(screen.getAllByText('Measurement sheet')).toHaveLength(2);
    // Money in the bill's own currency, through the shared formatter.
    expect(screen.getByTestId('qc-footer-net').textContent).toContain(signed(520));
    expect(screen.getByTestId('qc-footer-over').textContent).toContain(signed(720));
    expect(screen.getByTestId('qc-footer-under').textContent).toContain(signed(-200));
    const first = screen.getAllByTestId('qc-row')[0]!;
    expect(first.textContent).toContain(signed(600));
    expect(first.textContent).toContain(formatCurrency(50, 'CHF'));
  });

  it('the footer follows the filter', async () => {
    mockFetch.mockResolvedValue(report());
    renderPanel();
    await waitFor(() => expect(screen.getAllByTestId('qc-row')).toHaveLength(4));

    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'under' } });
    expect(shownRefs()).toEqual(['01.0020']);
    expect(screen.getByTestId('qc-footer-net').textContent).toContain(signed(-200));

    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'not_measured' } });
    expect(shownRefs()).toEqual(['01.0030']);
    expect(screen.getByTestId('qc-footer-net').textContent).toContain(signed(0));
  });

  it('the highlight band is the viewer setting, and narrowing it highlights more', async () => {
    mockFetch.mockResolvedValue(report());
    renderPanel();
    await waitFor(() => expect(screen.getAllByTestId('qc-row')).toHaveLength(4));
    const beyond = () =>
      screen
        .getAllByTestId('qc-row')
        .filter((r) => r.getAttribute('data-beyond') === 'true')
        .map((r) => within(r).getAllByRole('cell')[0]!.textContent);

    expect(beyond()).toEqual(['01.0010', '01.0040']);
    fireEvent.change(screen.getByLabelText('Highlight beyond +/- %'), { target: { value: '5' } });
    expect(beyond()).toEqual(['01.0010', '01.0020', '01.0040']);
  });

  it('says plainly when there is no baseline, and offers to freeze one', async () => {
    mockFetch.mockResolvedValue(
      report({
        baseline: { kind: 'current', snapshot_id: null, name: null, created_at: null, designated: false },
        designated_snapshot_id: null,
        snapshots: [],
        warnings: ['no_baseline'],
      }),
    );
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('qc-no-baseline')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Freeze current quantities as baseline' })).toBeInTheDocument();
  });

  it('offers the VOB hint only on a German project', async () => {
    mockFetch.mockResolvedValue(report({ country_code: 'GB' }));
    const { unmount } = renderPanel();
    await waitFor(() => expect(screen.getAllByTestId('qc-row')).toHaveLength(4));
    expect(screen.queryByTestId('qc-de-hint')).toBeNull();
    unmount();

    mockFetch.mockResolvedValue(report({ country_code: 'DE' }));
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('qc-de-hint')).toBeInTheDocument());
  });
});
