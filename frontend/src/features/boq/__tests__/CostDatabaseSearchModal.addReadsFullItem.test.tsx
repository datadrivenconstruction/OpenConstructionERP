// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The "From Database" modal lists slim cost rows (``lite=1``): no component
// breakdown and no variant catalogue, because those run to tens of kilobytes
// per CWICR row and the list renders neither. The add flow builds a position's
// resources and offers the variant picker from exactly those fields, so it
// must read each picked item in full before it posts anything.
//
// Every list row below is slim and every detail row is full, so an add flow
// that trusted the list row would post a position with no resources and no
// variant pick. That is the regression these tests hold the line against.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

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
  Trans: ({ children }: { children: React.ReactNode }) => children as React.ReactNode,
  initReactI18next: { type: '3rdParty', init: () => undefined },
  I18nextProvider: ({ children }: { children: React.ReactNode }) => children as React.ReactNode,
}));

// Full rows served by ``GET /v1/costs/{id}``. A test sets an entry to an
// Error to make that read fail.
const details: Record<string, unknown> = {};

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(async (path: string) => {
    if (path.startsWith('/v1/costs/regions/')) return ['DE_BERLIN'];
    const m = /^\/v1\/costs\/([^/?]+)$/.exec(path);
    if (m) {
      const detail = details[decodeURIComponent(m[1] ?? '')];
      if (detail instanceof Error) throw detail;
      if (detail === undefined) throw new Error(`unexpected detail read ${path}`);
      return detail;
    }
    if (path.endsWith('/structured/')) return { sections: [], positions: [] };
    if (path.startsWith('/v1/boq/boqs/')) return { positions: [] };
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

// A plain stand-in for the anchored picker: one button per variant, so a test
// can choose a specific one without driving the real popover's layout.
vi.mock('@/features/costs/VariantPicker', () => ({
  VariantPicker: ({
    variants,
    onApply,
  }: {
    variants: Array<{ index: number; label: string; price: number }>;
    onApply: (v: unknown) => void;
  }) => (
    <div data-testid="variant-picker">
      {variants.map((v) => (
        <button key={v.index} type="button" onClick={() => onApply(v)}>
          {`pick ${v.label}`}
        </button>
      ))}
    </div>
  ),
}));

import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { fetchCostSearch, fetchCategoryTree } from '../api';
import type { CostSearchPage } from '../api';
import { CostDatabaseSearchModal } from '../BOQModals';

// Testing Library waits 1 s by default. The first test of the file also pays
// for the modal's first render and query, and under a parallel run that alone
// took longer (the flake failed at 1.3 s). A wider window costs nothing when
// the modal is quick.
const SETTLE = { timeout: 10_000 };

// ── Rows ────────────────────────────────────────────────────────────────

const STATS = { min: 100, max: 140, mean: 120, median: 120, unit: 'm3', group: 'concrete', count: 3 };
const VARIANTS = [
  { index: 0, label: 'C20/25', price: 100, price_per_unit: null },
  { index: 1, label: 'C25/30', price: 120, price_per_unit: null },
  { index: 2, label: 'C30/37', price: 140, price_per_unit: null },
];

function slimRow(id: string, code: string, description: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    code,
    description,
    unit: 'm3',
    rate: 99,
    currency: 'EUR',
    region: 'DE_BERLIN',
    classification: {},
    components: [],
    components_count: 2,
    metadata_: { labor_cost: 30 },
    ...extra,
  };
}

const PLAIN_COMPONENTS = [
  { name: 'Formwork', code: 'R-1', unit: 'm2', quantity: 2, unit_rate: 15, cost: 30, type: 'material' },
  { name: 'Labour', code: 'R-2', unit: 'h', quantity: 1.5, unit_rate: 30, cost: 45, type: 'labor' },
];

function page(items: unknown[]): CostSearchPage {
  return { items, next_cursor: null, has_more: false, total: items.length } as CostSearchPage;
}

function renderModal(onSelectForResources?: (item: unknown, picked?: unknown) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const onClose = vi.fn();
  const onAdded = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <CostDatabaseSearchModal
        boqId="boq-1"
        onClose={onClose}
        onAdded={onAdded}
        onSelectForResources={onSelectForResources}
      />
    </QueryClientProvider>,
  );
  return { onAdded };
}

function positionPosts() {
  return (apiPost as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(
    ([path]) => typeof path === 'string' && path.includes('/positions/'),
  );
}

function detailReads() {
  return (apiGet as unknown as ReturnType<typeof vi.fn>).mock.calls
    .map(([path]) => path as string)
    .filter((path) => /^\/v1\/costs\/[^/?]+$/.test(path));
}

describe('CostDatabaseSearchModal - add reads the picked items in full', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom has no scrollIntoView; picking a row moves the keyboard cursor,
    // and the modal scrolls the cursor row into view.
    Element.prototype.scrollIntoView = vi.fn();
    for (const k of Object.keys(details)) delete details[k];
    useToastStore.setState({ toasts: [] });
    (fetchCategoryTree as unknown as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  });

  it('builds the resources of an item without variants from its full row', async () => {
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      page([slimRow('item-1', 'W-001', 'Concrete wall')]),
    );
    details['item-1'] = {
      ...slimRow('item-1', 'W-001', 'Concrete wall'),
      components: PLAIN_COMPONENTS,
      metadata_: { labor_cost: 30, scope_of_work: ['Set formwork', 'Pour'] },
    };
    const { onAdded } = renderModal();

    fireEvent.click(await screen.findByText('Concrete wall', {}, SETTLE));
    fireEvent.click(screen.getByText(/^Add 1 to BOQ/));

    await waitFor(() => expect(onAdded).toHaveBeenCalled(), SETTLE);
    expect(detailReads()).toEqual(['/v1/costs/item-1']);
    const posts = positionPosts();
    expect(posts).toHaveLength(1);
    const body = posts[0]?.[1] as {
      unit_rate: number;
      metadata: { resources?: Array<{ name: string; total: number }>; scope_of_work?: string[] };
    };
    expect(body.metadata.resources?.map((r) => r.name)).toEqual(['Formwork', 'Labour']);
    // Resource totals, not the catalogue rate of 99 the slim row also carries.
    expect(body.unit_rate).toBe(75);
    expect(body.metadata.resources?.map((r) => r.total)).toEqual([30, 45]);
    expect(body.metadata.scope_of_work).toEqual(['Set formwork', 'Pour']);
  });

  it('opens the variant picker from the full row and posts the chosen variant rate', async () => {
    // The slim row knows there are three variants (the list shows the count)
    // but carries no catalogue to pick from.
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      page([slimRow('item-2', 'C-100', 'Concrete slab', { components_count: 0, metadata_: { variant_stats: STATS } })]),
    );
    details['item-2'] = {
      ...slimRow('item-2', 'C-100', 'Concrete slab'),
      components: [],
      components_count: undefined,
      metadata_: { variants: VARIANTS, variant_stats: STATS },
    };
    const { onAdded } = renderModal();

    fireEvent.click(await screen.findByText('Concrete slab', {}, SETTLE));
    fireEvent.click(screen.getByText(/^Add 1 to BOQ/));

    expect(await screen.findByTestId('variant-picker', {}, SETTLE)).toBeInTheDocument();
    fireEvent.click(screen.getByText('pick C30/37'));

    await waitFor(() => expect(onAdded).toHaveBeenCalled(), SETTLE);
    const body = positionPosts()[0]?.[1] as {
      unit_rate: number;
      metadata: {
        variant?: { label: string; price: number; index: number };
        resources?: Array<{ unit_rate: number; variant?: { label: string } }>;
        cost_item_variant_count?: number;
      };
    };
    expect(body.metadata.variant).toEqual({ label: 'C30/37', price: 140, index: 2 });
    expect(body.unit_rate).toBe(140);
    expect(body.metadata.resources).toHaveLength(1);
    expect(body.metadata.resources?.[0]?.unit_rate).toBe(140);
    expect(body.metadata.cost_item_variant_count).toBe(3);
  });

  it('reads every picked item in a multi-add and posts each with its own resources', async () => {
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      page([slimRow('item-1', 'W-001', 'Concrete wall'), slimRow('item-3', 'F-010', 'Strip footing')]),
    );
    details['item-1'] = { ...slimRow('item-1', 'W-001', 'Concrete wall'), components: PLAIN_COMPONENTS };
    details['item-3'] = {
      ...slimRow('item-3', 'F-010', 'Strip footing'),
      components: [{ name: 'Excavation', code: 'R-9', unit: 'm3', quantity: 1, unit_rate: 22, cost: 22, type: 'equipment' }],
    };
    const { onAdded } = renderModal();

    fireEvent.click(await screen.findByText('Concrete wall', {}, SETTLE));
    fireEvent.click(screen.getByText('Strip footing'));
    fireEvent.click(screen.getByText(/^Add 2 to BOQ/));

    await waitFor(() => expect(onAdded).toHaveBeenCalled(), SETTLE);
    expect(detailReads().sort()).toEqual(['/v1/costs/item-1', '/v1/costs/item-3']);
    const bodies = positionPosts().map(
      (c) => c[1] as { description: string; unit_rate: number; metadata: { resources?: Array<{ name: string }> } },
    );
    expect(bodies.map((b) => b.description)).toEqual(['Concrete wall', 'Strip footing']);
    expect(bodies[0]?.metadata.resources?.map((r) => r.name)).toEqual(['Formwork', 'Labour']);
    expect(bodies[1]?.metadata.resources?.map((r) => r.name)).toEqual(['Excavation']);
    expect(bodies.map((b) => b.unit_rate)).toEqual([75, 22]);
  });

  it('shows an error and posts nothing when a picked item cannot be read', async () => {
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      page([slimRow('item-1', 'W-001', 'Concrete wall'), slimRow('item-3', 'F-010', 'Strip footing')]),
    );
    details['item-1'] = { ...slimRow('item-1', 'W-001', 'Concrete wall'), components: PLAIN_COMPONENTS };
    details['item-3'] = new Error('Cost item not found');
    const { onAdded } = renderModal();

    fireEvent.click(await screen.findByText('Concrete wall', {}, SETTLE));
    fireEvent.click(screen.getByText('Strip footing'));
    fireEvent.click(screen.getByText(/^Add 2 to BOQ/));

    await waitFor(
      () => expect(useToastStore.getState().toasts.some((toast) => toast.type === 'error')).toBe(true),
      SETTLE,
    );
    const toast = useToastStore.getState().toasts.find((x) => x.type === 'error');
    expect(toast?.message).toContain('Cost item not found');
    // All or nothing: the readable item is not posted on its own either.
    expect(positionPosts()).toHaveLength(0);
    expect(onAdded).not.toHaveBeenCalled();
  });

  it('hands the full row back in resource mode', async () => {
    (fetchCostSearch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      page([slimRow('item-1', 'W-001', 'Concrete wall')]),
    );
    details['item-1'] = { ...slimRow('item-1', 'W-001', 'Concrete wall'), components: PLAIN_COMPONENTS };
    const onSelectForResources = vi.fn();
    renderModal(onSelectForResources);

    fireEvent.click(await screen.findByText('Concrete wall', {}, SETTLE));
    fireEvent.click(screen.getByText(/^Add 1 as resources/));

    await waitFor(() => expect(onSelectForResources).toHaveBeenCalledTimes(1), SETTLE);
    const handed = onSelectForResources.mock.calls[0]?.[0] as { components: Array<{ name: string }> };
    expect(handed.components.map((c) => c.name)).toEqual(['Formwork', 'Labour']);
    expect(positionPosts()).toHaveLength(0);
  });
});
