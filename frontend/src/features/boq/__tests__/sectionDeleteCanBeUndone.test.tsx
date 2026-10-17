// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Deleting a section waits out an undo window before the cascade goes out.
 *
 * The section and everything nested under it leave the grid at once. Undo
 * inside the window brings all of it back and nothing reaches the server;
 * without undo one cascade DELETE goes out when the window ends. A section
 * with positions still asks first, an empty one does not.
 *
 * Run:  npx vitest run src/features/boq/__tests__/sectionDeleteCanBeUndone.test.tsx
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
  onDeletePosition: (id: string) => void;
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

function position(id: string, ordinal: string, parent_id: string | null = null) {
  return {
    id,
    boq_id: BOQ_ID,
    parent_id,
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
      // Refuses a number the server still holds, as the real endpoint does.
      addSection: vi.fn(async (_boqId: string, data: { ordinal: string; description: string }) => {
        if (server.positions.some((p) => p.ordinal === data.ordinal)) {
          throw new Error(`Ordinal ${data.ordinal} is already used in this BOQ`);
        }
        const created = position(`new-${data.ordinal}`, data.ordinal);
        server.positions.push(created);
        return created;
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
  await screen.findByTestId('row-other', {}, { timeout: 10_000 });
}

function undoAction(): () => void {
  const toast = useToastStore.getState().toasts.find((t) => t.action);
  expect(toast, 'the delete toast offers an undo action').toBeTruthy();
  return toast!.action!.onClick;
}

const SECTION_UNDO_MS = 8000;

beforeEach(() => {
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  useToastStore.setState({ toasts: [] });
  server.positions = [
    position('sec', '01'),
    position('sub', '01.01', 'sec'),
    position('leaf', '01.01.001', 'sub'),
    position('empty', '02'),
    position('other', '03.001'),
  ];
  grid.props = null;
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('deleting a section', () => {
  // Keep this test first. The two below leave the fake clock ahead of the
  // real one, and a page mounted after them stays empty past the wait.
  it('sends the waiting delete before a section added inside the undo window is numbered', async () => {
    // One section, 01. Deleted on screen, the next free number there is 01
    // again, which the server still holds until the undo window ends.
    server.positions = [position('sec', '01'), position('other', '01.001', 'sec')];
    await renderPage();
    await act(async () => {
      void grid.props!.onDeleteSection('sec');
      await new Promise((r) => setTimeout(r, 50));
    });
    fireEvent.click(await screen.findByTestId('confirm-dialog-confirm', {}, { timeout: 10_000 }));
    await waitFor(() => expect(screen.queryByTestId('row-sec')).toBeNull());
    expect(boqApi.deletePosition).not.toHaveBeenCalled();

    fireEvent.click(screen.getAllByTitle('boq.add_section')[0]!);
    const name = (await screen.findByLabelText('Enter section name:')) as HTMLInputElement;
    fireEvent.change(name, { target: { value: 'Earthworks' } });
    fireEvent.click(screen.getByTestId('boq-add-section-confirm'));

    await waitFor(() => expect(boqApi.addSection).toHaveBeenCalled());
    expect(boqApi.deletePosition).toHaveBeenCalledWith('sec', { cascade: true });
    expect(vi.mocked(boqApi.deletePosition).mock.invocationCallOrder[0]!)
      .toBeLessThan(vi.mocked(boqApi.addSection).mock.invocationCallOrder[0]!);
    await waitFor(() =>
      expect(useToastStore.getState().toasts.some((t) => t.title === 'Section added')).toBe(true),
    );
    expect(useToastStore.getState().toasts.some((t) => t.title === 'Failed to add section')).toBe(false);
    // The delete went out once; the undo window ending does not send it again.
    expect(boqApi.deletePosition).toHaveBeenCalledTimes(1);
  }, 60_000);

  it('takes the section and its nested rows off the grid and undo brings all of them back', async () => {
    await renderPage();
    // The handler waits on the confirm dialog, so it is started, not awaited,
    // and the render it schedules is flushed inside act.
    await act(async () => {
      void grid.props!.onDeleteSection('sec');
      await new Promise((r) => setTimeout(r, 50));
    });
    // Two rows inside: the page asks first. Real timers until the dialog is
    // up; the undo window starts on the click, so fake them just before it.
    const confirmButton = await screen.findByTestId('confirm-dialog-confirm', {}, { timeout: 10_000 });
    expect(confirmButton.textContent).toContain('Delete');
    vi.useFakeTimers({ shouldAdvanceTime: true });
    fireEvent.click(confirmButton);

    await waitFor(() => expect(screen.queryByTestId('row-sec')).toBeNull(), { timeout: 10_000 });
    expect(screen.queryByTestId('row-sub')).toBeNull();
    expect(screen.queryByTestId('row-leaf')).toBeNull();
    expect(boqApi.deletePosition).not.toHaveBeenCalled();

    act(() => undoAction()());
    await waitFor(() => expect(screen.getByTestId('row-sec')).toBeTruthy());
    expect(screen.getByTestId('row-sub')).toBeTruthy();
    expect(screen.getByTestId('row-leaf')).toBeTruthy();

    await act(async () => {
      vi.advanceTimersByTime(SECTION_UNDO_MS + 500);
    });
    expect(boqApi.deletePosition).not.toHaveBeenCalled();
  }, 60_000);

  it('sends one cascade delete when the window ends without undo, and asks nothing for an empty section', async () => {
    await renderPage();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // The handler is async, so act gets an async callback and is awaited. A
    // sync act around it returns a promise nobody awaits, and React keeps the
    // render that drops the row in the act queue until some other act happens
    // to flush it; on a slow runner none does before the wait gives up.
    await act(async () => {
      await grid.props!.onDeleteSection('empty');
    });

    await waitFor(() => expect(screen.queryByTestId('row-empty')).toBeNull(), { timeout: 10_000 });
    expect(screen.queryByTestId('confirm-dialog-confirm')).toBeNull();
    expect(boqApi.deletePosition).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(SECTION_UNDO_MS + 100);
    });
    await waitFor(() => expect(boqApi.deletePosition).toHaveBeenCalledWith('empty', { cascade: true }));
    expect(boqApi.deletePosition).toHaveBeenCalledTimes(1);
  }, 60_000);
});
