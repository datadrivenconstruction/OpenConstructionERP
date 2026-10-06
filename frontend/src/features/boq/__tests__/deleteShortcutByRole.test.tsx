// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The BOQ editor's Delete key, pressed by a role that may not delete.
 *
 * The key runs the same tracked delete as the grid's trash and the batch bar:
 * the rows leave the grid at once, an undo toast appears, and the API call
 * goes out five seconds later. For a viewer that call is refused (boq.delete
 * is an editor permission), so the rows vanished and came back with an error.
 * The grid's own delete controls already ask `boq.delete`; the key must too,
 * for a section and a position alike.
 *
 * The grid is a stub that records the rows it is handed and the selection
 * callback, so the test selects rows the way the grid does and reads what the
 * editor shows afterwards.
 *
 * Run:  npx vitest run src/features/boq/__tests__/deleteShortcutByRole.test.tsx
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
          row('p1', '01.001', 'Reinforced concrete wall C30/37', 's1', 'm2'),
        ],
      })),
      deletePosition: api.deletePosition,
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
  await waitFor(() => expect(grid.rowIds).toEqual(expect.arrayContaining(['s1', 'p1'])), { timeout: 10_000 });
  act(() => grid.select?.(ids));
}

const deletedToasts = () => useToastStore.getState().toasts.filter((t) => t.title === 'Position deleted');

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  grid.rowIds = [];
  grid.select = undefined;
  useToastStore.setState({ toasts: [] });
});

afterEach(() => cleanup());

describe('the Delete key in the BOQ editor', () => {
  it.each([
    ['a section', ['s1']],
    ['a position', ['p1']],
    ['a section and a position', ['s1', 'p1']],
  ])('does nothing for a viewer who selected %s', async (_what, ids) => {
    useAuthStore.setState({ userRole: 'viewer' });
    await renderEditorAndSelect(ids);
    fireEvent.keyDown(document.body, { key: 'Delete' });
    fireEvent.keyDown(document.body, { key: 'Backspace' });
    // Nothing left the grid, no undo toast, nothing queued for the server.
    expect(grid.rowIds).toEqual(expect.arrayContaining(['s1', 'p1']));
    expect(deletedToasts()).toHaveLength(0);
    expect(api.deletePosition).not.toHaveBeenCalled();
  });

  it('still deletes for an editor (the gate is the role, not the key)', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    await renderEditorAndSelect(['p1']);
    fireEvent.keyDown(document.body, { key: 'Delete' });
    await waitFor(() => expect(grid.rowIds).not.toContain('p1'));
    expect(deletedToasts()).toHaveLength(1);
  });
});
