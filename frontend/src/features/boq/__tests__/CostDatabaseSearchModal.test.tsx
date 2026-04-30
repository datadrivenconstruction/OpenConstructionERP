// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// CostDatabaseSearchModal contract tests for the v2.7 paginated catalog:
//   • Initial render fetches page 1 + the category tree
//   • Combining a free-text query with a selected category sends both params
//   • The "Load more" fallback button (used when IntersectionObserver isn't
//     wired up under JSDOM) calls the next page with the previous cursor
//   • Selecting a region resets the selected classification path and refetches
//
// We intentionally drive pagination via the visible "Load more" button rather
// than IntersectionObserver because JSDOM's IO implementation never fires
// `isIntersecting=true` without manual orchestration.  The infinite-scroll
// observer wiring is exercised live by the Vite dev server; here we cover the
// pagination *contract* (cursor round-trip, queryKey scoping, page-flatten).

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Mock react-i18next with interpolation ───────────────────────────────
//
// The global setup mocks `useTranslation` with a `defaultValue`-only stub
// that does NOT interpolate `{{loaded}}` / `{{total}}` placeholders.  The
// modal renders count labels like "{{loaded}} of {{total}} items"; for these
// tests we need real interpolation so we can assert on rendered numbers.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (opts && typeof opts === 'object' && 'defaultValue' in opts) {
        let str = String(opts.defaultValue);
        for (const k of Object.keys(opts)) {
          if (k === 'defaultValue') continue;
          str = str.replace(new RegExp(`{{${k}}}`, 'g'), String(opts[k]));
        }
        return str;
      }
      return key;
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) =>
    children as React.ReactNode,
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: React.ReactNode }) =>
    children as React.ReactNode,
}));

// ── Mock API surface ─────────────────────────────────────────────────────
//
// `apiGet` is used for the `regions/` query and the legacy fallbacks inside
// the "add" loop; we stub it broadly so unrelated calls don't blow up.
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.startsWith('/v1/costs/regions/')) {
      return ['DE_BERLIN', 'CS_PRAGUE'];
    }
    return {};
  }),
  apiPost: vi.fn(async () => ({})),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchCostSearch: vi.fn(),
    fetchCategoryTree: vi.fn(),
  };
});

import { fetchCostSearch, fetchCategoryTree } from '../api';
import type { CategoryTreeNode, CostSearchPage } from '../api';
import { CostDatabaseSearchModal } from '../BOQModals';

// ── Sample data ──────────────────────────────────────────────────────────

const TREE: CategoryTreeNode[] = [
  {
    name: 'Buildings',
    count: 100,
    children: [{ name: 'Concrete', count: 50, children: [] }],
  },
];

function makePage(overrides: Partial<CostSearchPage> = {}): CostSearchPage {
  return {
    items: [
      {
        id: 'item-1',
        code: 'C30.001',
        description: 'Concrete C30/37 wall',
        unit: 'm3',
        rate: 150,
        currency: 'EUR',
        region: 'DE_BERLIN',
        classification: { collection: 'Buildings', department: 'Concrete' },
        components: [],
      },
    ],
    next_cursor: 'cursor-page-2',
    has_more: true,
    total: 1234,
    ...overrides,
  };
}

// ── Test harness ─────────────────────────────────────────────────────────

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const onClose = vi.fn();
  const onAdded = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <CostDatabaseSearchModal
        boqId="boq-1"
        onClose={onClose}
        onAdded={onAdded}
      />
    </QueryClientProvider>,
  );
  return { ...view, onClose, onAdded, client };
}

// ── Tests ────────────────────────────────────────────────────────────────

describe('CostDatabaseSearchModal — paginated catalog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchCategoryTree as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(TREE);
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(makePage());
  });

  it('fetches the first page + the category tree on mount', async () => {
    renderModal();

    await waitFor(() => expect(fetchCostSearch).toHaveBeenCalled());
    expect(fetchCategoryTree).toHaveBeenCalled();

    // First call has no cursor — that's how the backend distinguishes the
    // first page (and decides whether to populate `total`).
    const calls = (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const firstCallArgs = calls[0]?.[0];
    expect(firstCallArgs).toMatchObject({
      cursor: null,
      limit: 50,
    });

    expect(await screen.findByText('Concrete C30/37 wall')).toBeInTheDocument();
  });

  it('shows the total count returned on the first page', async () => {
    renderModal();
    await waitFor(() => expect(fetchCostSearch).toHaveBeenCalled());
    // Counter element appears immediately but its content flips through
    // "Loading..." while the query is in flight, so wait on the resolved
    // text rather than the bare element.
    await waitFor(() => {
      const counter = screen.getByTestId('cost-results-count');
      expect(counter.textContent).toContain('1,234');
    });
  });

  it('combines selected category + text query in a single fetch', async () => {
    renderModal();

    // Wait for the tree to render so we can click into it.
    await waitFor(() => expect(fetchCategoryTree).toHaveBeenCalled());
    fireEvent.click(await screen.findByText('Buildings'));

    // Now type a query.
    const searchInput = screen.getByPlaceholderText(/Search cost items/i);
    fireEvent.change(searchInput, { target: { value: 'concrete' } });

    await waitFor(() => {
      const last = (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mock.calls.at(
        -1,
      )?.[0];
      expect(last).toMatchObject({
        classification_path: 'Buildings',
        q: 'concrete',
      });
    });
  });

  it('calls the next page with the previous cursor when "Load more" is clicked', async () => {
    renderModal();
    await waitFor(() => expect(fetchCostSearch).toHaveBeenCalled());

    // Page 1 → page 2 → no more.
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      makePage({
        items: [
          {
            id: 'item-2',
            code: 'C30.002',
            description: 'Concrete C25/30 slab',
            unit: 'm2',
            rate: 90,
            currency: 'EUR',
            region: 'DE_BERLIN',
            classification: {},
            components: [],
          },
        ],
        next_cursor: null,
        has_more: false,
        total: null,
      }),
    );

    const loadMoreText = await screen.findByText('Load more');
    fireEvent.click(loadMoreText);

    await waitFor(() => {
      // Three call total: tree + first page + cursor-driven page.
      const cursorCall = (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mock.calls
        .map((c) => c[0])
        .find((args) => args?.cursor === 'cursor-page-2');
      expect(cursorCall).toBeDefined();
    });

    // Both page rows are rendered (pages.flatMap).
    expect(await screen.findByText('Concrete C25/30 slab')).toBeInTheDocument();
    expect(screen.getByText('Concrete C30/37 wall')).toBeInTheDocument();
  });

  it('resets the classification path when the region changes', async () => {
    renderModal();
    await waitFor(() => expect(fetchCategoryTree).toHaveBeenCalled());

    // Select "Buildings" so we have a non-empty path.
    fireEvent.click(await screen.findByText('Buildings'));
    await waitFor(() => {
      const last = (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mock.calls.at(
        -1,
      )?.[0];
      expect(last?.classification_path).toBe('Buildings');
    });

    // Filter chip is visible while the path is selected.
    expect(screen.getByTestId('filter-chip-category')).toBeInTheDocument();

    // The modal auto-selects the first country DB on mount (DE_BERLIN), so
    // click CS_PRAGUE to actually trigger a region change.
    const czTab = screen.getByText('Czech Republic');
    fireEvent.click(czTab);

    await waitFor(() => {
      const last = (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mock.calls.at(
        -1,
      )?.[0];
      expect(last?.region).toBe('CS_PRAGUE');
      // The path was cleared by the region-change effect.
      expect(last?.classification_path).toBeUndefined();
    });

    // Chip is gone.
    expect(screen.queryByTestId('filter-chip-category')).toBeNull();
  });

  it('shows the inline retry CTA when the category tree fails', async () => {
    (fetchCategoryTree as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('boom'),
    );

    renderModal();
    const sidebar = await screen.findByTestId('cost-modal-sidebar');
    expect(
      await within(sidebar).findByText('Could not load categories'),
    ).toBeInTheDocument();
    expect(within(sidebar).getByText('Retry')).toBeInTheDocument();

    // The list pane keeps working — the search query fired regardless.
    expect(fetchCostSearch).toHaveBeenCalled();
  });
});
