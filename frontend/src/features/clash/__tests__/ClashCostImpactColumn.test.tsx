/**
 * ClashCostImpactColumn UI tests.
 *
 * The component fetches ``GET /v1/clash-cost-impact/clash/{id}/impact``;
 * we stub the underlying ``apiGet`` helper so the tests are fully offline.
 * React Query retries are disabled so error states surface synchronously
 * (matches the BIM AssetsPage / audit-log test convention).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  render,
  screen,
  waitFor,
  cleanup,
  act,
  fireEvent,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── apiGet stub ────────────────────────────────────────────────────────────
//
// The component imports ``apiGet`` from ``@/shared/lib/api``; we replace
// it with a vi.fn so each test can dictate the response (success / null /
// throw) and assert on the URL the component calls.

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
}));

// MoneyDisplay reads from the preferences store; provide a minimal shim
// so the tests run without bootstrapping the whole Zustand graph.
// MoneyDisplay calls ``usePreferencesStore()`` without a selector and
// destructures the result, so the mock returns the state object directly
// (Zustand's stores DO support that pattern when called bare).
const __mockPrefState = { currency: 'EUR', numberLocale: 'en-US' };
vi.mock('@/stores/usePreferencesStore', () => ({
  usePreferencesStore: (sel?: (s: any) => any) =>
    sel ? sel(__mockPrefState) : __mockPrefState,
}));

import { apiGet } from '@/shared/lib/api';
import { ClashCostImpactColumn } from '../ClashCostImpactColumn';

const apiGetMock = apiGet as unknown as ReturnType<typeof vi.fn>;

function renderColumn(
  props: Partial<React.ComponentProps<typeof ClashCostImpactColumn>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <table>
          <tbody>
            <tr>
              <ClashCostImpactColumn
                clashId="clash-1"
                currency="EUR"
                {...props}
              />
            </tr>
          </tbody>
        </table>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  cleanup();
});

const samplePayload = {
  clash_id: 'clash-1',
  currency: 'EUR',
  components: {
    rework_positions_total: 5000,
    rework_factor_pct: 10,
    rework_subtotal: 500,
    labour_hours: 8,
    blended_rate: 50,
    labour_subtotal: 400,
  },
  total_estimate: 900,
  confidence: 'high' as const,
  affected_positions: [
    {
      position_id: 'pos-1',
      boq_id: 'boq-9',
      ordinal: '01.01.001',
      description: 'Concrete C30/37',
      total: 5000,
    },
  ],
};

describe('ClashCostImpactColumn', () => {
  it('renders the loading skeleton while the query is in flight', () => {
    // Never resolve — keeps the query in the loading state for the assertion.
    apiGetMock.mockReturnValue(new Promise(() => {}));
    renderColumn();
    expect(screen.getByTestId('clash-cost-skeleton')).toBeTruthy();
    expect(screen.getByTestId('clash-cost-cell').getAttribute('data-state')).toBe(
      'loading',
    );
  });

  it('renders formatted money + currency on success', async () => {
    apiGetMock.mockResolvedValue(samplePayload);
    renderColumn({ currency: 'EUR' });
    await waitFor(() =>
      expect(
        screen.getByTestId('clash-cost-cell').getAttribute('data-state'),
      ).toBe('ready'),
    );
    // Intl.NumberFormat for en-US + EUR yields "€900.00" — be flexible
    // about exact glyph (some Node versions emit a NBSP between symbol
    // and number) and just assert the digits are visible.
    const cell = screen.getByTestId('clash-cost-cell');
    expect(cell.textContent).toContain('900');
    // The currency code OR symbol must be present in the cell.
    expect(/€|EUR/.test(cell.textContent || '')).toBe(true);
    // Confidence pill renders.
    expect(screen.getByTestId('clash-cost-confidence').textContent).toBe('high');
  });

  it('calls the correct API endpoint with the clash id', async () => {
    apiGetMock.mockResolvedValue(samplePayload);
    renderColumn({ clashId: 'clash-XYZ' });
    await waitFor(() => expect(apiGetMock).toHaveBeenCalled());
    expect(apiGetMock).toHaveBeenCalledWith(
      '/v1/clash-cost-impact/clash/clash-XYZ/impact',
    );
  });

  it('renders an em-dash when the API returns null / empty', async () => {
    // apiGet resolves to null — guarded by the `!query.data` branch.
    apiGetMock.mockResolvedValue(null as any);
    renderColumn();
    await waitFor(() =>
      expect(
        screen.getByTestId('clash-cost-cell').getAttribute('data-state'),
      ).toBe('empty'),
    );
    expect(screen.getByTestId('clash-cost-cell').textContent).toContain('—');
  });

  it('surfaces the breakdown via the tooltip (title attribute)', async () => {
    apiGetMock.mockResolvedValue(samplePayload);
    renderColumn();
    await waitFor(() =>
      expect(
        screen.getByTestId('clash-cost-cell').getAttribute('data-state'),
      ).toBe('ready'),
    );
    const cell = screen.getByTestId('clash-cost-cell');
    const tooltip = cell.getAttribute('title') || '';
    expect(tooltip).toMatch(/Rework:/);
    expect(tooltip).toMatch(/Labour:/);
    expect(tooltip).toMatch(/Confidence: high/);
    // Numeric breakdown surfaces in the tooltip too.
    expect(tooltip).toMatch(/500\.00/);
    expect(tooltip).toMatch(/400\.00/);
  });

  it('fails soft on an API error (no crash, em-dash cell)', async () => {
    apiGetMock.mockRejectedValue(new Error('boom'));
    renderColumn();
    await waitFor(() =>
      expect(
        screen.getByTestId('clash-cost-cell').getAttribute('data-state'),
      ).toBe('error'),
    );
    expect(screen.getByTestId('clash-cost-cell').textContent).toContain('—');
  });

  it('does not call the API when ``queryEnabled`` is false', async () => {
    apiGetMock.mockResolvedValue(samplePayload);
    renderColumn({ queryEnabled: false });
    // Microtasks have a chance to flush — assert apiGet stayed untouched.
    await act(async () => {
      await Promise.resolve();
    });
    expect(apiGetMock).not.toHaveBeenCalled();
  });

  // ── CONN-27: BOQ drill-down popover ──────────────────────────────────
  it('opens a popover with per-position BOQ deep-links on high confidence', async () => {
    apiGetMock.mockResolvedValue(samplePayload);
    renderColumn();
    const trigger = await screen.findByTestId('clash-cost-trigger');
    fireEvent.click(trigger);
    const link = await screen.findByTestId('clash-cost-position-link');
    // Deep-link target is /boq/{boq_id}?highlight={position_id} — the
    // exact contract BOQEditorPage's ?highlight consumer expects.
    expect(link.getAttribute('href')).toBe('/boq/boq-9?highlight=pos-1');
    // Ordinal + description surface in the popover row.
    expect(screen.getByTestId('clash-cost-popover').textContent).toContain(
      '01.01.001',
    );
    expect(screen.getByTestId('clash-cost-popover').textContent).toContain(
      'Concrete C30/37',
    );
  });

  it('does NOT make the cell drillable when confidence is medium', async () => {
    apiGetMock.mockResolvedValue({
      ...samplePayload,
      confidence: 'medium',
      affected_positions: [],
    });
    renderColumn();
    await waitFor(() =>
      expect(
        screen.getByTestId('clash-cost-cell').getAttribute('data-state'),
      ).toBe('ready'),
    );
    // No trigger button rendered — the money cell stays read-only.
    expect(screen.queryByTestId('clash-cost-trigger')).toBeNull();
  });

  it('renders a non-navigable row when a position lacks boq_id', async () => {
    apiGetMock.mockResolvedValue({
      ...samplePayload,
      affected_positions: [
        {
          position_id: 'pos-x',
          ordinal: '02.02.002',
          description: 'Rebar',
          total: 100,
        },
      ],
    });
    renderColumn();
    const trigger = await screen.findByTestId('clash-cost-trigger');
    fireEvent.click(trigger);
    await screen.findByTestId('clash-cost-popover');
    // No link is rendered for a position without an owning boq_id.
    expect(screen.queryByTestId('clash-cost-position-link')).toBeNull();
    expect(screen.getByTestId('clash-cost-popover').textContent).toContain(
      '02.02.002',
    );
  });
});
