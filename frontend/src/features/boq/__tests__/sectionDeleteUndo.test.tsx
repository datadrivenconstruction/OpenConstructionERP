// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Deleting a section can be undone.
 *
 * The section and everything under it leave the grid at once; the cascade
 * DELETE goes out only after the undo window, and Undo in that window brings
 * the whole subtree back without touching the server. A section with lines
 * under it still asks first, an empty one does not.
 *
 * The page stubs the grid down to a list of the row ids it is handed.
 *
 * Run:  npx vitest run src/features/boq/__tests__/sectionDeleteUndo.test.tsx
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, act, fireEvent } from '@testing-library/react';
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
  onDeleteSection: (id: string) => void;
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

vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [] }) }));

const BOQ_ID = 'boq-1';
const PROJECT_ID = 'proj-1';

function position(id: string, ordinal: string, parentId: string | null = null, unit = 'm2') {
  return {
    id,
    boq_id: BOQ_ID,
    parent_id: parentId,
    ordinal,
    description: `Line ${ordinal}`,
    unit,
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
import { useToastStore } from '@/stores/useToastStore';

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

/** The action of the newest toast titled ``title``. */
function toastAction(title: string) {
  const toast = [...useToastStore.getState().toasts].reverse().find((t) => t.title === title);
  expect(toast?.action).toBeTruthy();
  return toast!.action!;
}

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  server.positions = [
    position('s1', '01', null, ''),
    position('s1a', '01.01', 's1', ''),
    position('p1', '01.01.001', 's1a'),
    position('p2', '02.001'),
    position('s2', '03', null, ''),
  ];
  grid.props = null;
  useToastStore.setState({ toasts: [] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('deleting a section', () => {
  it('asks first, hides the subtree, and Undo brings it all back without a DELETE', async () => {
    await renderPage();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => grid.props!.onDeleteSection('s1'));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(screen.queryByTestId('row-s1')).toBeNull());
    expect(screen.queryByTestId('row-s1a')).toBeNull();
    expect(screen.queryByTestId('row-p1')).toBeNull();
    expect(screen.getByTestId('row-p2')).toBeTruthy();
    expect(boqApi.deletePosition).not.toHaveBeenCalled();

    act(() => toastAction('Section deleted with {{count}} positions').onClick());
    await waitFor(() => expect(screen.getByTestId('row-p1')).toBeTruthy());
    expect(screen.getByTestId('row-s1')).toBeTruthy();
    expect(screen.getByTestId('row-s1a')).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(boqApi.deletePosition).not.toHaveBeenCalled();
  });

  it('sends one cascade delete once the undo window has passed', async () => {
    await renderPage();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    act(() => grid.props!.onDeleteSection('s1'));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByTestId('row-s1')).toBeNull());

    await act(async () => {
      vi.advanceTimersByTime(8_100);
    });
    await waitFor(() => expect(boqApi.deletePosition).toHaveBeenCalledWith('s1', { cascade: true }));
    expect(boqApi.deletePosition).toHaveBeenCalledTimes(1);
  });

  it('removes an empty section without asking', async () => {
    await renderPage();
    act(() => grid.props!.onDeleteSection('s2'));
    await waitFor(() => expect(screen.queryByTestId('row-s2')).toBeNull());
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(toastAction('Section deleted')).toBeTruthy();
  });
});
