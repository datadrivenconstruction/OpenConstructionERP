// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A deleted position stays deleted while its delete waits for the undo window.
 *
 * Deleting a line takes it off the grid at once and sends the DELETE five
 * seconds later, so the undo toast can bring it back. Adding a position in
 * those five seconds refetches the bill, and the server still holds the line,
 * so the refetch put it straight back on the grid. When the DELETE then went
 * out nothing refetched again, and the ghost stayed until a reload.
 *
 * The page stubs the grid down to a list of the row ids it is handed, so the
 * tests read what the estimator would see without AG Grid's layout.
 *
 * Run:  npx vitest run src/features/boq/__tests__/deletedRowStaysDeleted.test.tsx
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';
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

type GridProps = {
  positions: Array<{ id: string }>;
  onDeletePosition: (id: string) => void;
};
const grid: { props: GridProps | null } = { props: null };

vi.mock('../BOQGrid', () => ({
  __esModule: true,
  default: React.forwardRef<unknown, GridProps>(function BOQGridStub(props, _ref) {
    grid.props = props;
    return (
      <ul data-testid="boq-grid-stub">
        {props.positions.map((p) => (
          <li key={p.id} data-testid={`row-${p.id}`} />
        ))}
      </ul>
    );
  }),
}));

vi.mock('../pdfReport', () => ({ generateBOQPdf: vi.fn() }));
vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [] }) }));

const BOQ_ID = 'boq-1';
const PROJECT_ID = 'proj-1';

function position(id: string, ordinal: string) {
  return {
    id,
    boq_id: BOQ_ID,
    parent_id: null,
    ordinal,
    description: `Line ${ordinal}`,
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
  };
}

/** What the server holds; the DELETE mock removes from it. */
const server: { positions: ReturnType<typeof position>[] } = { positions: [] };

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
        positions: server.positions.map((p) => ({ ...p })),
      })),
      deletePosition: vi.fn(async (id: string) => {
        server.positions = server.positions.filter((p) => p.id !== id);
      }),
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

import { boqApi } from '../api';
import { BOQEditorPage } from '../BOQEditorPage';

let client: QueryClient;

async function renderPage() {
  client = new QueryClient({
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
  await screen.findByTestId('row-p2', {}, { timeout: 10_000 });
}

/** The refetch every position write triggers, adding a line among them. */
async function refetchTheBill() {
  await act(async () => {
    await client.invalidateQueries({ queryKey: ['boq', BOQ_ID] });
  });
  // Let the page render what the refetch brought back.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  server.positions = [position('p1', '01.001'), position('p2', '01.002')];
  grid.props = null;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('a deleted position waiting for its undo window', () => {
  it('does not come back when the bill is refetched before the delete goes out', async () => {
    await renderPage();
    act(() => grid.props!.onDeletePosition('p1'));
    expect(screen.queryByTestId('row-p1')).toBeNull();

    // A new line was added: the page refetches while the server still has p1.
    await refetchTheBill();

    expect(boqApi.get).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId('row-p1')).toBeNull();
    expect(screen.getByTestId('row-p2')).toBeTruthy();
  });

  it('stays gone once the delete has gone out, with no reload in between', async () => {
    await renderPage();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => grid.props!.onDeletePosition('p1'));
    await refetchTheBill();

    await act(async () => {
      vi.advanceTimersByTime(5_100);
    });
    await waitFor(() => expect(boqApi.deletePosition).toHaveBeenCalledWith('p1', undefined));

    expect(screen.queryByTestId('row-p1')).toBeNull();
    expect(screen.getByTestId('row-p2')).toBeTruthy();
  });
});
