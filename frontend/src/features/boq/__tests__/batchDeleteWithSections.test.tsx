// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Batch delete with section rows selected: the Delete key opens the batch bar's
 * confirmation (sections named with their position counts), confirming offers
 * the section Undo toast, and Undo restores sections and positions in order.
 *
 * Run:  npx vitest run src/features/boq/__tests__/batchDeleteWithSections.test.tsx
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('react-i18next', () => {
  const t = (key: string, opts?: Record<string, unknown>) => {
    const fallback = opts?.defaultValue;
    if (typeof fallback !== 'string') return key;
    return fallback.replace(/\{\{(\w+)\}\}/g, (_m, k: string) => String(opts?.[k] ?? ''));
  };
  const value = { t, i18n: { language: 'en', changeLanguage: () => {} } };
  return {
    useTranslation: () => value,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: '3rdParty', init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

const grid: { rowIds: string[]; select: ((ids: string[]) => void) | undefined } = { rowIds: [], select: undefined };

vi.mock('../BOQGrid', () => ({
  __esModule: true,
  default: React.forwardRef<
    unknown,
    { positions?: { id: string }[]; onSelectionChanged?: (ids: string[]) => void }
  >(function BOQGridStub(props, _ref) {
    grid.rowIds = (props.positions ?? []).map((p) => p.id);
    grid.select = props.onSelectionChanged;
    return <div data-testid="boq-grid-stub" />;
  }),
}));

vi.mock('@/features/bim/api', () => ({
  fetchBIMModels: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}));

vi.mock('@/shared/hooks/useBackendModuleOff', () => ({
  useBackendModuleOff: () => () => false,
}));

const BOQ_ID = 'boq-1';
const PROJECT_ID = 'proj-1';

const row = (id: string, ordinal: string, description: string, parent_id: string | null, unit: string) => ({
  id,
  boq_id: BOQ_ID,
  parent_id,
  ordinal,
  description,
  unit,
  quantity: unit ? 10 : 0,
  unit_rate: unit ? 50 : 0,
  total: unit ? 500 : 0,
  classification: {},
  source: 'manual',
  confidence: null,
  validation_status: 'pending',
  sort_order: 0,
  metadata: {},
});

const ORDER = ['s1', 'p1', 'p2', 's2', 'p3', 'p4'];
const api = vi.hoisted(() => ({ deletePosition: vi.fn(async () => undefined) }));

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>();
  return {
    ...actual,
    boqApi: {
      get: vi.fn(async () => ({
        id: BOQ_ID,
        project_id: PROJECT_ID,
        name: 'Riverside HQ Bill',
        status: 'draft',
        is_locked: false,
        positions: [
          row('s1', '01', 'Shell', null, ''),
          row('p1', '01.001', 'Wall', 's1', 'm2'),
          row('p2', '01.002', 'Slab', 's1', 'm2'),
          row('s2', '02', 'Roof', null, ''),
          row('p3', '02.001', 'Tiles', 's2', 'm2'),
          row('p4', '03.001', 'Loose', null, 'm2'),
        ],
      })),
      deletePosition: api.deletePosition,
      getMarkups: vi.fn(async () => ({ markups: [] })),
      getCostBreakdown: vi.fn(async () => ({
        boq_id: BOQ_ID,
        grand_total: 0,
        direct_cost: 0,
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
import { useToastStore } from '@/stores/useToastStore';

async function renderEditorAndSelect(ids: string[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/boq/${BOQ_ID}`]}>
        <Routes>
          <Route path="/boq/:boqId" element={<BOQEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByTestId('boq-grid-stub', {}, { timeout: 10_000 });
  await waitFor(() => expect(grid.rowIds).toEqual(expect.arrayContaining(ORDER)), { timeout: 10_000 });
  act(() => grid.select?.(ids));
}

const undoAction = () => useToastStore.getState().toasts.find((t) => t.action)?.action;

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  grid.rowIds = [];
  grid.select = undefined;
  useToastStore.setState({ toasts: [] });
  useAuthStore.setState({ userRole: 'editor' });
});

afterEach(() => cleanup());

describe('batch delete with sections selected', () => {
  it('the Delete key opens the confirmation naming each section and its positions', async () => {
    await renderEditorAndSelect(['s1', 's2']);
    fireEvent.keyDown(document.body, { key: 'Delete' });
    const list = await screen.findByTestId('batch-delete-sections');
    expect(list.textContent).toContain('01 Shell');
    expect(list.textContent).toContain('2 positions');
    expect(list.textContent).toContain('02 Roof');
    expect(list.textContent).toContain('1 positions');
    // Nothing is deleted until the user confirms.
    expect(grid.rowIds).toEqual(ORDER);
  });

  it('confirming offers Undo, and Undo restores sections and positions in order', async () => {
    await renderEditorAndSelect(['s1', 'p4']);
    fireEvent.keyDown(document.body, { key: 'Delete' });
    await screen.findByTestId('batch-delete-sections');
    fireEvent.click(screen.getByRole('button', { name: /Delete 2 positions/ }));
    await waitFor(() => expect(grid.rowIds).toEqual(['s2', 'p3']));
    expect(api.deletePosition).not.toHaveBeenCalled();

    const undo = undoAction();
    expect(undo, 'the delete toast offers Undo').toBeTruthy();
    act(() => undo!.onClick());
    await waitFor(() => expect(grid.rowIds).toEqual(['s1', 'p1', 'p2', 's2', 'p3']));
    expect(api.deletePosition).not.toHaveBeenCalledWith('s1', expect.anything());
  });

  it('without Undo each section goes out as one cascade', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      await renderEditorAndSelect(['s1', 's2']);
      fireEvent.keyDown(document.body, { key: 'Delete' });
      await screen.findByTestId('batch-delete-sections');
      fireEvent.click(screen.getByRole('button', { name: /Delete 2 positions/ }));
      await waitFor(() => expect(grid.rowIds).toEqual(['p4']));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(api.deletePosition).toHaveBeenCalledWith('s1', { cascade: true });
      expect(api.deletePosition).toHaveBeenCalledWith('s2', { cascade: true });
      expect(api.deletePosition).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
