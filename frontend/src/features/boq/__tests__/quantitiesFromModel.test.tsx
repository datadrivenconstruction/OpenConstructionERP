// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The BOQ editor's two ways into the model.
 *
 * Nothing in the editor pointed at the BIM side until a position already had
 * links, so a tester with a Revit model could not work out how to get model
 * quantities into the bill. The toolbar now has "Quantities from the model",
 * which opens the Quantity Rules page scoped to this project, BOQ and model,
 * and the grid gets a handler that opens the 3D model to pick elements for one
 * position. The grid is a stub that records what it is handed; the cell and
 * menu items that call the handler are pinned in the grid tests.
 *
 * Run:  npx vitest run src/features/boq/__tests__/quantitiesFromModel.test.tsx
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    const fallback = opts?.defaultValue;
    return typeof fallback === 'string' ? fallback : key;
  };
  const value = { t, i18n: { language: 'en', changeLanguage: () => {} } };
  return {
    useTranslation: () => value,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

const grid: { onLinkFromModel: unknown; bimModelId: unknown } = { onLinkFromModel: undefined, bimModelId: undefined };

// Backend modules switched off on the System Modules tab, as the shared
// catalogue reports them.
const modulesOff = vi.hoisted(() => new Set<string>());
vi.mock('@/shared/hooks/useBackendModuleOff', () => ({
  useBackendModuleOff: () => (name: string) => modulesOff.has(name),
}));

vi.mock('../BOQGrid', () => ({
  __esModule: true,
  default: React.forwardRef<unknown, { onLinkFromModel?: (id: string) => void; bimModelId?: string | null }>(
    function BOQGridStub(props, _ref) {
      grid.onLinkFromModel = props.onLinkFromModel;
      grid.bimModelId = props.bimModelId;
      return <div data-testid="boq-grid-stub" />;
    },
  ),
}));

vi.mock('@/features/bim/api', () => ({
  fetchBIMModels: vi.fn().mockResolvedValue({
    items: [{ id: 'm-1', name: 'Architecture', status: 'ready', element_count: 120 }],
    total: 1,
  }),
}));

const BOQ_ID = 'boq-1';
const PROJECT_ID = 'proj-1';
const bill = { locked: false };

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      get: vi.fn(async () => ({
        id: BOQ_ID,
        project_id: PROJECT_ID,
        name: 'Riverside HQ Bill',
        status: bill.locked ? 'final' : 'draft',
        is_locked: bill.locked,
        positions: [
          {
            id: 'p1',
            boq_id: BOQ_ID,
            parent_id: null,
            ordinal: '01.001',
            description: 'Reinforced concrete wall C30/37',
            unit: 'm2',
            quantity: 10,
            unit_rate: 50,
            total: 500,
            classification: {},
            source: 'manual',
            confidence: null,
            validation_status: 'pending',
            sort_order: 0,
            metadata: {},
          },
        ],
      })),
      getMarkups: vi.fn(async () => ({ markups: [] })),
      getCostBreakdown: vi.fn(async () => ({
        boq_id: BOQ_ID,
        grand_total: 500,
        direct_cost: 500,
        categories: [],
        markups: [],
        top_resources: [],
      })),
      getLimits: vi.fn(async () => ({ max_nesting_depth: 5 })),
      getActivity: vi.fn(async () => []),
    },
  };
});

vi.mock('@/features/projects/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/projects/api')>();
  return {
    ...actual,
    projectsApi: {
      ...actual.projectsApi,
      get: vi.fn(async () => ({ id: PROJECT_ID, name: 'Riverside HQ', currency: 'EUR', fx_rates: [] })),
    },
  };
});

import { BOQEditorPage } from '../BOQEditorPage';
import { useAuthStore } from '@/stores/useAuthStore';

let location = '';
function LocationProbe() {
  const loc = useLocation();
  location = `${loc.pathname}${loc.search}`;
  return null;
}

async function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/boq/${BOQ_ID}`]}>
        <Routes>
          <Route path="/boq/:boqId" element={<BOQEditorPage />} />
          <Route path="*" element={null} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByTestId('boq-grid-stub', {}, { timeout: 10_000 });
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  grid.onLinkFromModel = undefined;
  grid.bimModelId = undefined;
  location = '';
  modulesOff.clear();
  useAuthStore.setState({ userRole: 'editor' });
});

afterEach(() => cleanup());

describe('Quantities from the model', () => {
  it('opens the quantity rules for this project, BOQ and model in the same tab', async () => {
    bill.locked = false;
    await renderPage();
    await waitFor(() => expect(grid.bimModelId).toBe('m-1'), { timeout: 10_000 });
    const btn = screen.getByTestId('boq-quantities-from-model') as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    const url = new URL(location, 'http://x');
    expect(url.pathname).toBe('/bim/rules');
    expect(url.searchParams.get('project_id')).toBe(PROJECT_ID);
    expect(url.searchParams.get('boq_id')).toBe(BOQ_ID);
    expect(url.searchParams.get('model_id')).toBe('m-1');
    expect(url.searchParams.get('mode')).toBeNull();
  });

  it('is disabled on a locked bill, which a rule cannot write into', async () => {
    bill.locked = true;
    await renderPage();
    expect((screen.getByTestId('boq-quantities-from-model') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('Pick elements in the 3D model, for one position', () => {
  it('opens the model for that position', async () => {
    bill.locked = false;
    await renderPage();
    // The handler is only useful once the project model has resolved; the
    // stub keeps the one from the latest render.
    await waitFor(() => expect(grid.bimModelId).toBe('m-1'), { timeout: 10_000 });
    act(() => (grid.onLinkFromModel as (id: string) => void)('p1'));
    await waitFor(() => expect(location.startsWith('/projects/')).toBe(true));
    const url = new URL(location, 'http://x');
    expect(url.pathname).toBe(`/projects/${PROJECT_ID}/bim/m-1`);
    expect(url.searchParams.get('link_position')).toBe('p1');
    expect(url.searchParams.get('link_boq')).toBe(BOQ_ID);
    expect(url.searchParams.get('link_label')).toBe('01.001 Reinforced concrete wall C30/37');
  });

  it('is not handed to the grid of a locked bill', async () => {
    bill.locked = true;
    await renderPage();
    await waitFor(() => expect(grid.bimModelId).toBe('m-1'), { timeout: 10_000 });
    expect(grid.onLinkFromModel).toBeUndefined();
  });
});

// Linking elements (POST /bim_hub/links/) and applying rules (POST
// /bim_hub/quantity-maps/apply/) need bim.create, an editor permission, and
// BIM Hub switched on. Without either, both ways in would end in a refusal.
describe('the model entry points, by role and module', () => {
  it('are hidden from a viewer, who cannot link elements or apply rules', async () => {
    bill.locked = false;
    useAuthStore.setState({ userRole: 'viewer' });
    await renderPage();
    await waitFor(() => expect(grid.bimModelId).toBe('m-1'), { timeout: 10_000 });
    expect(screen.queryByTestId('boq-quantities-from-model')).toBeNull();
    expect(grid.onLinkFromModel).toBeUndefined();
  });

  it('are offered to an editor', async () => {
    bill.locked = false;
    await renderPage();
    await waitFor(() => expect(grid.bimModelId).toBe('m-1'), { timeout: 10_000 });
    expect(screen.getByTestId('boq-quantities-from-model')).toBeTruthy();
    expect(typeof grid.onLinkFromModel).toBe('function');
  });

  it('are hidden when BIM Hub is switched off', async () => {
    bill.locked = false;
    modulesOff.add('oe_bim_hub');
    await renderPage();
    await waitFor(() => expect(grid.bimModelId).toBe('m-1'), { timeout: 10_000 });
    expect(screen.queryByTestId('boq-quantities-from-model')).toBeNull();
    expect(grid.onLinkFromModel).toBeUndefined();
  });
});
