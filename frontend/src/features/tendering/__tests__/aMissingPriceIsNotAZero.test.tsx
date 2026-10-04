// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A bidder who gave no price on a line has not priced it at zero.
//
// The comparison grid printed "0,00" for a line a bidder left out, exactly as
// it prints a real zero, and a missing price then sat at the cheap end of the
// line. The endpoint now sends no figure for such a line (unit_rate null,
// priced false) and how complete each bid is (matched_lines of total_lines).
// The grid shows the gap as a gap, the bid total says it is incomplete, and
// the chart does not colour an incomplete bid as the lowest.
//
// Units are the second half: the grid and the leveling matrix printed the
// stored token ("m2", "lsum") where the BOQ editor prints "m²" and, in German,
// "psch". Both now go through the editor's own localizedUnitCode.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { cellRate, pricedRates, unpricedLineCount } from '../analysis';

const lang = vi.hoisted(() => ({ value: 'de' }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, second?: unknown) => {
      if (typeof second === 'string') return second;
      if (second && typeof second === 'object' && 'defaultValue' in second) {
        const opts = second as { defaultValue?: string } & Record<string, unknown>;
        let dv = String(opts.defaultValue ?? '');
        for (const [k, v] of Object.entries(opts)) {
          if (k === 'defaultValue') continue;
          dv = dv.replaceAll(`{{${k}}}`, String(v));
        }
        return dv;
      }
      return key;
    },
    i18n: { language: lang.value },
  }),
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: unknown }) => children,
  Trans: ({ children }: { children?: unknown }) => children ?? null,
}));

const apiMocks = vi.hoisted(() => ({ getLevelingMatrix: vi.fn(), levelBids: vi.fn() }));
vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api')>()), ...apiMocks }));

// jsdom has no ResizeObserver; the chart only uses it to follow its width.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const { BidComparisonTable } = await import('../TenderingPage');
const { LevelingMatrix } = await import('../LevelingMatrix');
const { BidComparisonChart } = await import('../BidComparisonChart');

const cell = (bid_id: string, unit_rate: number | null) => ({
  company_name: bid_id,
  bid_id,
  unit_rate,
  total: unit_rate === null ? null : unit_rate * 10,
  deviation_pct: 0,
  priced: unit_rate !== null,
});

// Gamma left the PV line out. Its total is the lowest only because of that.
const comparison = {
  package_id: 'pkg',
  package_name: 'Innenausbau',
  bid_count: 3,
  bid_companies: ['Alpha', 'Beta', 'Gamma'],
  budget_total: 3000,
  rows: [
    {
      position_id: 'p1',
      ordinal: '01.010',
      description: 'Trockenbauwand',
      unit: 'm2',
      budget_quantity: 10,
      budget_rate: 100,
      budget_total: 1000,
      bids: [cell('Alpha', 95), cell('Beta', 105), cell('Gamma', 99)],
    },
    {
      position_id: 'p2',
      ordinal: '01.020',
      description: 'PV-Anlage',
      unit: 'lsum',
      budget_quantity: 1,
      budget_rate: 2000,
      budget_total: 2000,
      bids: [cell('Alpha', 2100), cell('Beta', 1950), cell('Gamma', null)],
    },
  ],
  bid_totals: [
    { bid_id: 'Alpha', company_name: 'Alpha', total: 3050, currency: 'EUR', deviation_pct: 1.7, status: 'submitted',
      matched_lines: 2, total_lines: 2 },
    { bid_id: 'Beta', company_name: 'Beta', total: 3000, currency: 'EUR', deviation_pct: 0, status: 'submitted',
      matched_lines: 2, total_lines: 2 },
    { bid_id: 'Gamma', company_name: 'Gamma', total: 990, currency: 'EUR', deviation_pct: -67, status: 'submitted',
      matched_lines: 1, total_lines: 2 },
  ],
};

afterEach(() => {
  cleanup();
  lang.value = 'de';
});

describe('reading a cell', () => {
  it('keeps a missing price out of the line', () => {
    expect(cellRate(cell('x', null))).toBeNull();
    expect(cellRate({ unit_rate: 0, priced: false })).toBeNull();
    expect(cellRate({ unit_rate: 0, priced: true })).toBe(0);
    expect(pricedRates(comparison.rows[1]!.bids)).toEqual([2100, 1950]);
  });

  it('counts the lines a bid left unpriced', () => {
    expect(unpricedLineCount({ matched_lines: 1, total_lines: 2 })).toBe(1);
    expect(unpricedLineCount({ matched_lines: 2, total_lines: 2 })).toBe(0);
    // An answer with no coverage says nothing, rather than "all missing".
    expect(unpricedLineCount({})).toBe(0);
  });
});

describe('the comparison grid', () => {
  it('shows a missing price as missing, never as 0,00', () => {
    const view = render(<BidComparisonTable comparison={comparison} currency="EUR" />);
    const pvRow = [...view.container.querySelectorAll('tbody tr')].find((tr) =>
      tr.textContent?.includes('PV-Anlage'),
    )!;
    const gamma = pvRow.querySelectorAll('td')[4]!;
    expect(gamma.querySelector('[data-testid="bid-cell-unpriced"]')).not.toBeNull();
    expect(gamma.textContent).toContain('not priced');
    expect(gamma.textContent).not.toMatch(/0[,.]00/);
    expect(gamma.getAttribute('title')).toBe('This bidder gave no price for this line.');
  });

  it('says under the total that a bid is incomplete', () => {
    const view = render(<BidComparisonTable comparison={comparison} currency="EUR" />);
    const footer = view.container.querySelectorAll('tfoot td');
    expect(footer[4]!.textContent).toContain('Incomplete: 1');
    expect(footer[2]!.textContent).not.toContain('Incomplete');
  });

  it('prints units the way the BOQ editor does', () => {
    const view = render(<BidComparisonTable comparison={comparison} currency="EUR" />);
    const text = view.container.querySelector('tbody')!.textContent!;
    expect(text).toContain('m²');
    expect(text).toContain('psch');
    expect(text).not.toMatch(/\bm2\b|\blsum\b/);
  });
});

describe('the bid chart', () => {
  it('does not colour an incomplete bid as the lowest', () => {
    const view = render(
      <BidComparisonChart bidTotals={comparison.bid_totals} budgetTotal={3000} currency="EUR" />,
    );
    const bars = [...view.container.querySelectorAll('rect')]
      .map((r) => r.getAttribute('fill') ?? '')
      .filter((f) => /--oe-success|--oe-error|--color-oe-blue/.test(f));
    // In bid order: Alpha is the highest, Beta (3000) the lowest complete
    // bid, and Gamma (990) is cheaper only by the line it left out.
    expect(bars).toHaveLength(3);
    expect(bars[0]).toContain('--oe-error');
    expect(bars[1]).toContain('--oe-success');
    expect(bars[2]).toContain('--color-oe-blue');
  });

  it('lays its legend out as separate items, so a long label cannot run into the next', () => {
    const view = render(
      <BidComparisonChart bidTotals={comparison.bid_totals} budgetTotal={3000} currency="EUR" />,
    );
    const legend = view.getByTestId('bid-chart-legend');
    expect(legend.className).toMatch(/\bflex\b/);
    expect(legend.className).toMatch(/\bgap-x-/);
    expect(legend.children.length).toBe(4);
    // No legend text is drawn at fixed x offsets inside the SVG any more.
    expect(view.container.querySelector('svg text')?.textContent ?? '').not.toContain('Lowest');
  });
});

describe('the leveling matrix', () => {
  it('prints units the way the BOQ editor does', async () => {
    apiMocks.getLevelingMatrix.mockResolvedValue({
      package_id: 'pkg',
      package_name: 'Innenausbau',
      currency: 'EUR',
      excluded_off_currency: 0,
      bid_summaries: [],
      rows: [
        { position_id: 'p1', line_code: '01.010', description: 'Trockenbauwand', unit: 'm2', reference_quantity: 10,
          reference_rate: 100, reference_total: 1000, cells: [] },
        { position_id: 'p2', line_code: '01.020', description: 'PV-Anlage', unit: 'lsum', reference_quantity: 1,
          reference_rate: 2000, reference_total: 2000, cells: [] },
      ],
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const view = render(
      <QueryClientProvider client={client}>
        <LevelingMatrix packageId="pkg" currency="EUR" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(view.container.querySelector('tbody')).not.toBeNull());
    const text = view.container.querySelector('tbody')!.textContent!;
    expect(text).toContain('m²');
    expect(text).toContain('psch');
    expect(text).not.toMatch(/m2|lsum/);
  });
});
